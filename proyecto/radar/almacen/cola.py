"""Escritor de Parquet en un hilo separado y con presión de retorno.

El lector WebSocket no realiza la conversión a Parquet en el bucle asyncio.
IMPORTANTE: los lotes aceptados están en memoria hasta su escritura; NO es un
WAL persistente. Un apagón puede perder los últimos lotes. No ofrece exactly-once.
"""
from __future__ import annotations

import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor


class ColaEscritura:
    def __init__(self, destino, max_pendientes: int = 16, reintentos: int = 2,
                 pausa_s: float = 0.5):
        if max_pendientes < 1 or reintentos < 0:
            raise ValueError("La capacidad debe ser positiva y los reintentos no negativos")
        self.destino = destino
        self.max_pendientes = max_pendientes
        self.reintentos = reintentos
        self.pausa_s = pausa_s
        self.pendientes: deque[Future] = deque()
        self.ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quantlab-parquet")
        self.cerrada = False
        self.fallo = None

    def _escribir(self, filas, fuente):
        for intento in range(self.reintentos + 1):
            try:
                return self.destino.guardar(filas, fuente)
            except OSError:
                if intento == self.reintentos:
                    raise
                time.sleep(self.pausa_s * 2 ** intento)

    def _resultado(self, futuro):
        try:
            return futuro.result()
        except Exception as exc:
            self.fallo = self.fallo or exc
            raise

    def _comprobar(self, esperar=False):
        if self.fallo is not None:
            raise RuntimeError("Falló el escritor Parquet") from self.fallo
        while self.pendientes and (esperar or self.pendientes[0].done()):
            self._resultado(self.pendientes.popleft())

    def guardar(self, filas, fuente):
        if self.cerrada:
            raise RuntimeError("Cola de escritura cerrada")
        if not filas:
            return []
        self._comprobar()
        # Cuando el disco no da abasto, se aplica backpressure en vez de crecer
        # indefinidamente en memoria. Esto debe vigilarse con métricas.
        while len(self.pendientes) >= self.max_pendientes:
            self._resultado(self.pendientes.popleft())
        self.pendientes.append(self.ejecutor.submit(self._escribir, list(filas), fuente))
        return []  # las rutas físicas se conocen al completar el trabajo

    def cerrar(self):
        if self.cerrada:
            return
        self.cerrada = True
        primero = None
        try:
            while self.pendientes:
                futuro = self.pendientes.popleft()
                try:
                    futuro.result()
                except Exception as exc:
                    primero = primero or exc
        finally:
            self.ejecutor.shutdown(wait=True)
        if primero is not None:
            raise primero
        if self.fallo is not None:
            raise RuntimeError("Falló un lote de escritura anterior") from self.fallo

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cerrar()
