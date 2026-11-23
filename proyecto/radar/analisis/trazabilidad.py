"""Manifiestos de ejecución para relacionar un estudio con su entrada Parquet.

La huella utiliza rutas, tamaños y mtime_ns; NO es un hash del contenido,
ni una transacción de lectura. Si cambia el conjunto durante el estudio,
se registra la diferencia y no se promete reproducibilidad bit a bit.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from radar.configuracion import RAIZ_LAKE, RAIZ_PROYECTO

RUN_ACTUAL = ContextVar('quantlab_run_actual', default=None)


def run_id_actual():
    return RUN_ACTUAL.get()


def manifiesto_datos(raiz=RAIZ_LAKE) -> dict:
    raiz = Path(raiz)
    archivos = []
    for ruta in sorted(raiz.rglob("*.parquet")) if raiz.exists() else ():
        stat = ruta.stat()
        archivos.append({"ruta": ruta.relative_to(raiz).as_posix(),
                         "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    serializado = json.dumps(archivos, sort_keys=True, separators=(",", ":"))
    return {"archivos": archivos, "n_archivos": len(archivos),
            "total_bytes": sum(x["bytes"] for x in archivos),
            "sha256_metadatos": hashlib.sha256(serializado.encode("utf-8")).hexdigest()}


def _commit_git():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=RAIZ_PROYECTO,
            timeout=3, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.SubprocessError):
        return None


@contextmanager
def registrar_estudio(comando: str, parametros: dict, raiz_lake=RAIZ_LAKE, raiz_runs=None):
    """Guardar parámetros, versión de código y conjunto de archivos antes/después."""
    destino = Path(raiz_runs) if raiz_runs is not None else Path(RAIZ_LAKE).parent / "ejecuciones"
    destino.mkdir(parents=True, exist_ok=True)
    identificador = uuid.uuid4().hex
    inicio = pd.Timestamp.now(tz="UTC")
    antes = manifiesto_datos(raiz_lake)
    estado, error = "correcto", None
    token = RUN_ACTUAL.set(identificador)
    try:
        yield identificador
    except BaseException as exc:
        estado = "error"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        RUN_ACTUAL.reset(token)
        despues = manifiesto_datos(raiz_lake)
        fila = {
            "run_id": identificador, "comando": comando, "parametros": parametros,
            "inicio_utc": inicio.isoformat(),
            "fin_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "commit_git": _commit_git(), "estado": estado, "error": error,
            "datos_entrada": antes, "datos_salida": despues,
            "datos_cambiaron_durante_ejecucion":
                antes["sha256_metadatos"] != despues["sha256_metadatos"],
            "limitacion": ("Huella de nombre/tamaño/mtime; no hash completo de bytes. "
                           "El data lake puede seguir recibiendo escrituras concurrentes.")
        }
        ruta = destino / f"{identificador}.json"
        temporal = destino / f"{identificador}.tmp"
        try:
            temporal.write_text(json.dumps(fila, ensure_ascii=False, indent=2, default=str),
                                encoding="utf-8")
            os.replace(temporal, ruta)
        finally:
            temporal.unlink(missing_ok=True)
