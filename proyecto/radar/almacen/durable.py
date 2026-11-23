"""WAL de lotes Parquet con SQLite: ACK durable antes de escribir Parquet.

Garantía: tras confirmar el INSERT en SQLite (synchronous=FULL), un reinicio
puede reintentar lotes pendientes mediante nombres Parquet deterministas.
No recupera eventos no recibidos ni ofrece transacciones atómicas entre
múltiples particiones a lectores concurrentes. Usar un WAL por proceso.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd


def _serializar(valor):
    if valor is pd.NaT or valor is pd.NA:
        return {"__qt_tipo__": "nulo"}
    if isinstance(valor, (pd.Timestamp, dt.datetime, np.datetime64)):
        return {"__qt_tipo__": "fecha", "valor": pd.Timestamp(valor).isoformat()}
    if isinstance(valor, Decimal):
        return {"__qt_tipo__": "decimal", "valor": str(valor)}
    if isinstance(valor, np.ndarray):
        return valor.tolist()
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, (dt.date,)):
        return {"__qt_tipo__": "fecha", "valor": pd.Timestamp(valor).isoformat()}
    raise TypeError(f"Tipo no serializable en WAL: {type(valor).__name__}")


def _deserializar(dic):
    if dic.get("__qt_tipo__") == "fecha" and set(dic) == {"__qt_tipo__", "valor"}:
        return pd.Timestamp(dic["valor"])
    if dic.get("__qt_tipo__") == "decimal" and set(dic) == {"__qt_tipo__", "valor"}:
        return Decimal(dic["valor"])
    if dic.get("__qt_tipo__") == "nulo" and set(dic) == {"__qt_tipo__"}:
        return None
    return dic


class AlmacenDurable:
    """Guardado asíncrono con recuperación y deduplicación por ID de lote.

    `guardar` confirma el lote en SQLite, luego agenda su publicación.
    `cerrar` espera los trabajos. La recuperación se inicia al construir una
    nueva instancia con la misma ruta. Los fallos no eliminan los pendientes.
    """

    def __init__(self, destino, ruta: Path, max_pendientes: int = 16,
                 reintentos: int = 2, pausa_s: float = 0.5):
        if max_pendientes < 1 or reintentos < 0 or pausa_s < 0:
            raise ValueError("Capacidad, reintentos o pausa inválidos")
        if not hasattr(destino, "guardar_lote"):
            raise TypeError("El destino requiere guardar_lote(filas, fuente, lote_id)")
        self.destino = destino
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.max_pendientes, self.reintentos, self.pausa_s = max_pendientes, reintentos, pausa_s
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.ruta), timeout=30, check_same_thread=False, isolation_level=None)
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS pendientes (
                id TEXT PRIMARY KEY, fuente TEXT NOT NULL,
                payload TEXT NOT NULL, creado_utc TEXT NOT NULL)""")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quantlab-wal")
        self.pendientes: deque[Future] = deque()
        self.fallo = None
        self.cerrado = False
        # Los registros confirmados antes de una caída se procesan primero.
        with self.lock:
            antiguos = self.conn.execute("SELECT id FROM pendientes ORDER BY rowid").fetchall()
        for (identificador,) in antiguos:
            self._agendar(identificador)

    def _ejecutar(self, identificador: str):
        with self.lock:
            fila = self.conn.execute(
                "SELECT fuente, payload FROM pendientes WHERE id=?", (identificador,)).fetchone()
        if fila is None:
            return []
        fuente, payload = fila
        datos = json.loads(payload, object_hook=_deserializar)
        for intento in range(self.reintentos + 1):
            try:
                rutas = self.destino.guardar_lote(datos, fuente, identificador)
                break
            except OSError:
                if intento == self.reintentos:
                    raise
                time.sleep(self.pausa_s * (2 ** intento))
        with self.lock:
            self.conn.execute("DELETE FROM pendientes WHERE id=?", (identificador,))
        return rutas

    def _terminado(self, futuro: Future):
        try:
            return futuro.result()
        except Exception as exc:
            self.fallo = self.fallo or exc
            raise

    def _comprobar(self):
        if self.fallo is not None:
            raise RuntimeError("Falló la persistencia del WAL; reiniciar para recuperar") from self.fallo
        while self.pendientes and self.pendientes[0].done():
            self._terminado(self.pendientes.popleft())

    def _agendar(self, identificador: str):
        self._comprobar()
        while len(self.pendientes) >= self.max_pendientes:
            self._terminado(self.pendientes.popleft())
        self.pendientes.append(self.executor.submit(self._ejecutar, identificador))

    def guardar(self, filas, fuente):
        if self.cerrado:
            raise RuntimeError("WAL cerrado")
        if not filas:
            return []
        self._comprobar()
        datos = json.dumps(list(filas), default=_serializar, ensure_ascii=False,
                           allow_nan=True, separators=(",", ":"))
        identificador = uuid.uuid4().hex
        with self.lock:
            self.conn.execute(
                "INSERT INTO pendientes(id, fuente, payload, creado_utc) VALUES (?, ?, ?, ?)",
                (identificador, fuente, datos, pd.Timestamp.now(tz="UTC").isoformat()))
        self._agendar(identificador)
        return []  # Las rutas definitivas se conocerán tras la escritura asíncrona.

    def contar_pendientes(self) -> int:
        with self.lock:
            return self.conn.execute("SELECT count(*) FROM pendientes").fetchone()[0]

    def cerrar(self):
        if self.cerrado:
            return
        self.cerrado = True
        primero = None
        try:
            while self.pendientes:
                try:
                    self._terminado(self.pendientes.popleft())
                except Exception as exc:
                    primero = primero or exc
        finally:
            self.executor.shutdown(wait=True)
            with self.lock:
                self.conn.close()
        if primero is not None:
            raise primero
        if self.fallo is not None:
            raise RuntimeError("Persistencia del WAL incompleta") from self.fallo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()
