"""Diagnóstico local y de solo lectura de la salud de la captura QuantLab.

No diagnostica que una captura sea perfecta: mide frescura y cobertura observable.
La ausencia de trades no implica por sí misma caída del mercado o de la conexión.
"""
from __future__ import annotations

import pandas as pd

from radar.configuracion import EXCHANGES

FUENTES_CRITICAS = ("cotizaciones", "libros_flujo")


def diagnosticar(almacen, ahora=None, umbral_s: float = 180.0) -> dict:
    if umbral_s <= 0:
        raise ValueError("umbral_s debe ser positivo")
    instante = pd.Timestamp.now(tz="UTC") if ahora is None else pd.Timestamp(ahora)
    instante = instante.tz_localize("UTC") if instante.tzinfo is None else instante.tz_convert("UTC")
    desde = instante - pd.Timedelta(days=2)
    ventana = instante - pd.Timedelta(minutes=10)
    presentes = set(almacen.fuentes())
    medidas, problemas = [], []
    for fuente in FUENTES_CRITICAS:
        por_exchange = {}
        if fuente in presentes:
            consulta = f"""
                SELECT exchange, max(recibido_utc) AS ultima_utc,
                       count(*) FILTER (WHERE recibido_utc >= TIMESTAMPTZ '{ventana.isoformat()}') AS filas_10m
                FROM {fuente}
                WHERE recibido_utc >= TIMESTAMPTZ '{desde.isoformat()}'
                GROUP BY exchange
            """
            try:
                datos = almacen.consultar(consulta)
                por_exchange = {str(fila.exchange): fila for fila in datos.itertuples(index=False)}
            except Exception as exc:
                problemas.append(f"{fuente}: error de consulta: {type(exc).__name__}: {exc}")
        for exchange in EXCHANGES:
            fila = por_exchange.get(exchange)
            ultima = pd.Timestamp(fila.ultima_utc) if fila is not None else None
            edad = None
            if ultima is not None and not pd.isna(ultima):
                ultima = ultima.tz_localize("UTC") if ultima.tzinfo is None else ultima.tz_convert("UTC")
                edad = max(0.0, (instante - ultima).total_seconds())
            n = int(fila.filas_10m) if fila is not None else 0
            ok = edad is not None and edad <= umbral_s and n > 0
            medidas.append({"fuente": fuente, "exchange": exchange,
                            "ultima_utc": ultima.isoformat() if ultima is not None else None,
                            "edad_s": round(edad, 2) if edad is not None else None,
                            "filas_10m": n, "ok": ok})
            if not ok:
                problemas.append(f"{fuente}/{exchange}: sin datos recientes fiables (edad={edad})")
    if "errores_captura" in presentes:
        try:
            errores = almacen.consultar(
                f"SELECT count(*) AS n FROM errores_captura "
                f"WHERE recibido_utc >= TIMESTAMPTZ '{ventana.isoformat()}'")
            errores_10m = int(errores.n.iloc[0])
        except Exception as exc:
            errores_10m = None
            problemas.append(f"errores_captura: error de consulta: {exc}")
    else:
        errores_10m = 0
    return {"instante_utc": instante.isoformat(), "umbral_s": umbral_s,
            "medidas": medidas, "errores_10m": errores_10m,
            "problemas": problemas, "ok": not problemas}
