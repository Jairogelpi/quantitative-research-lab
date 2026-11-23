"""Continuidad temporal de la captura REST y libros WebSocket.

A diferencia de la puerta estadística original, registra también periodos
largos (>60 s), el inicio y el final de la ventana y la ausencia total
de datos. Una separación temporal no prueba pérdida de mensajes específicos.
"""
from __future__ import annotations

import pandas as pd

from radar.configuracion import EXCHANGES

FUENTES = ("cotizaciones", "libros_flujo")


def _utc(v):
    ts = pd.Timestamp(v)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def diagnosticar_continuidad(almacen, desde, hasta, umbral_s: float = 5.0) -> dict:
    inicio, fin = _utc(desde), _utc(hasta)
    if inicio >= fin or umbral_s <= 0:
        raise ValueError("Ventana o umbral no válido")
    a, b = inicio.isoformat(), fin.isoformat()
    presentes = set(almacen.fuentes())
    cortes, totales, errores = [], [], []
    for fuente in FUENTES:
        if fuente not in presentes:
            for exchange in EXCHANGES:
                cortes.append(dict(fuente=fuente, exchange=exchange, clase="sin_fuente",
                                   desde_utc=a, hasta_utc=b, duracion_s=(fin - inicio).total_seconds()))
            continue
        try:
            resumen = almacen.consultar(f"""
                SELECT exchange, count(*) AS n,
                       min(recibido_utc) AS primera, max(recibido_utc) AS ultima
                FROM {fuente}
                WHERE recibido_utc >= TIMESTAMPTZ '{a}' AND recibido_utc < TIMESTAMPTZ '{b}'
                GROUP BY exchange""")
            internos = almacen.consultar(f"""
                WITH filas AS (
                   SELECT exchange, recibido_utc AS fin,
                          lag(recibido_utc) OVER (PARTITION BY exchange ORDER BY recibido_utc) AS comienzo
                   FROM {fuente}
                   WHERE recibido_utc >= TIMESTAMPTZ '{a}' AND recibido_utc < TIMESTAMPTZ '{b}'
                )
                SELECT exchange, comienzo, fin,
                       epoch(fin) - epoch(comienzo) AS duracion_s
                FROM filas
                WHERE comienzo IS NOT NULL
                AND epoch(fin) - epoch(comienzo) > {float(umbral_s)}
                ORDER BY exchange, comienzo""")
        except Exception as exc:
            errores.append(f"{fuente}: {type(exc).__name__}: {exc}")
            continue
        mapa = {str(r.exchange): r for r in resumen.itertuples(index=False)}
        for exchange in EXCHANGES:
            r = mapa.get(exchange)
            if r is None:
                cortes.append(dict(fuente=fuente, exchange=exchange, clase="sin_datos",
                                   desde_utc=a, hasta_utc=b, duracion_s=(fin - inicio).total_seconds()))
                totales.append(dict(fuente=fuente, exchange=exchange, n=0))
                continue
            primera, ultima = _utc(r.primera), _utc(r.ultima)
            totales.append(dict(fuente=fuente, exchange=exchange, n=int(r.n),
                                primera_utc=primera.isoformat(), ultima_utc=ultima.isoformat()))
            bordes = [("inicio", inicio, primera), ("final", ultima, fin)]
            for clase, x, y in bordes:
                segundos = (y - x).total_seconds()
                if segundos > umbral_s:
                    cortes.append(dict(fuente=fuente, exchange=exchange, clase=clase,
                                       desde_utc=x.isoformat(), hasta_utc=y.isoformat(), duracion_s=segundos))
        for r in internos.itertuples(index=False):
            cortes.append(dict(fuente=fuente, exchange=str(r.exchange), clase="interior",
                               desde_utc=_utc(r.comienzo).isoformat(), hasta_utc=_utc(r.fin).isoformat(),
                               duracion_s=float(r.duracion_s)))
    return {"desde_utc": a, "hasta_utc": b, "umbral_s": float(umbral_s),
            "totales": totales, "cortes": cortes, "errores": errores,
            "ok": not cortes and not errores}
