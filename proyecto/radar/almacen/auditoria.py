"""Auditoría de archivos Parquet de QuantLab, de solo lectura.

La auditoría rápida inspecciona metadata; --profundo comprueba todos los
recibido_utc de cada archivo respecto a su partición de calendario UTC.
No elimina temporales ni reescribe ni compacta datos automáticamente.
"""
from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import pyarrow.parquet as pq


def auditar_lake(raiz, profundo: bool = False) -> dict:
    raiz = Path(raiz)
    informe = {"raiz": str(raiz), "profundo": bool(profundo),
               "archivos": 0, "filas": 0, "bytes": 0,
               "temporales": [], "incidencias": [], "fuentes": {}}
    if not raiz.exists():
        informe["incidencias"].append("No existe el directorio del data lake")
        informe["ok"] = False
        return informe
    for tmp in sorted(raiz.rglob("*.tmp")):
        informe["temporales"].append(str(tmp.relative_to(raiz)))
    for ruta in sorted(raiz.rglob("*.parquet")):
        relativo = ruta.relative_to(raiz)
        fuente = relativo.parts[0] if relativo.parts else "?"
        estad = informe["fuentes"].setdefault(fuente, {"archivos": 0, "filas": 0, "bytes": 0})
        informe["archivos"] += 1
        estad["archivos"] += 1
        try:
            nbytes = ruta.stat().st_size
            estad["bytes"] += nbytes
            informe["bytes"] += nbytes
            pf = pq.ParquetFile(ruta)
            cantidad = pf.metadata.num_rows
            estad["filas"] += cantidad
            informe["filas"] += cantidad
            campos = set(pf.schema_arrow.names)
            if "recibido_utc" not in campos:
                raise ValueError("no existe la columna recibido_utc")
            particion = next((x[6:] for x in relativo.parts if x.startswith("fecha=")), None)
            if particion is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", particion):
                raise ValueError("partición fecha=AAAA-MM-DD ausente o mal formada")
            if profundo:
                fechas = pd.to_datetime(pf.read(columns=["recibido_utc"]).to_pandas()
                                       ["recibido_utc"], utc=True, errors="coerce")
                if fechas.isna().any():
                    raise ValueError("recibido_utc tiene fechas nulas o inválidas")
                if not fechas.dt.strftime("%Y-%m-%d").eq(particion).all():
                    raise ValueError("datos de fecha UTC distinta de la partición")
        except Exception as exc:
            informe["incidencias"].append(f"{relativo}: {type(exc).__name__}: {exc}")
    # Un temporal puede estar siendo escrito en este mismo momento:
    # el operador decidirá si es huérfano tras verificar la captura.
    informe["ok"] = not informe["incidencias"] and not informe["temporales"]
    return informe
