"""Histórico público BTC/EUR de OKX y Bitvavo; sin inventar barras ausentes.

Velas no equivalen a trades ni a históricos de libro L2.
Docs: https://www.okx.com/docs-v5/en/ y https://docs.bitvavo.com/docs/rest-api/get-candlestick-data/
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from radar.analisis.velas import leer_velas
from radar.captura.exchanges.http import pedir_json
from radar.captura.historico_kraken import COLUMNAS, nuevas_o_mejores
from radar.configuracion import PAR

OKX_URL = "https://www.okx.com/api/v5/market/history-candles"
BITVAVO_URL = "https://api.bitvavo.com/v2/BTC-EUR/candles"
INTERVALOS = {
    60: ("1m", "1m"), 300: ("5m", "5m"), 900: ("15m", "15m"),
    3600: ("1H", "1h"), 14400: ("4H", "4h"), 86400: ("1Dutc", "1d"),
}


def _utc(valor) -> pd.Timestamp:
    ts = pd.Timestamp(valor)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fila(exchange, intervalo_s, ts_ms, apertura, maximo, minimo, cierre,
          volumen_btc, volumen_eur, completo, recibido_utc) -> dict:
    inicio = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
    volumen = float(volumen_btc)
    if not np.isfinite(volumen) or volumen < 0:
        raise ValueError(f"{exchange}: volumen BTC inválido")
    vacia = volumen == 0
    precios = [float(v) for v in (apertura, maximo, minimo, cierre)]
    if not vacia and (not all(np.isfinite(precios)) or min(precios) <= 0
                      or precios[1] < max(precios[0], precios[3])
                      or precios[2] > min(precios[0], precios[3])):
        raise ValueError(f"{exchange}: OHLC inválido en {inicio}")
    eur = float(volumen_eur) if volumen_eur is not None else np.nan
    if np.isfinite(eur) and eur < 0:
        raise ValueError(f"{exchange}: volumen EUR negativo")
    return dict(fuente=f"{exchange}_historico", exchange=exchange, par=PAR,
                intervalo_s=intervalo_s, inicio_utc=inicio,
                apertura=np.nan if vacia else precios[0], maximo=np.nan if vacia else precios[1],
                minimo=np.nan if vacia else precios[2], cierre=np.nan if vacia else precios[3],
                volumen_btc=volumen, volumen_eur=0.0 if vacia else eur,
                vwap=eur / volumen if volumen > 0 and np.isfinite(eur) else np.nan,
                n_trades=np.nan, vacia=vacia,
                completa=bool(completo) and inicio + pd.Timedelta(seconds=intervalo_s) <= recibido_utc,
                recibido_utc=recibido_utc)


def interpretar_okx(datos: dict, intervalo_s: int, recibido_utc) -> pd.DataFrame:
    if not isinstance(datos, dict) or str(datos.get("code")) != "0":
        raise ValueError(f"OKX histórico: error {datos!r}"[:350])
    ahora = _utc(recibido_utc)
    filas = []
    for barra in datos.get("data", []):
        if len(barra) < 9:
            raise ValueError("OKX histórico: vela incompleta")
        # 'vol' es BTC spot y 'volCcyQuote' es EUR para BTC-EUR.
        filas.append(_fila("okx", intervalo_s, barra[0], *barra[1:5], barra[5], barra[7],
                           barra[8] == "1", ahora))
    return pd.DataFrame(filas, columns=COLUMNAS)


def interpretar_bitvavo(datos: list, intervalo_s: int, recibido_utc) -> pd.DataFrame:
    if not isinstance(datos, list):
        raise ValueError(f"Bitvavo histórico: error {datos!r}"[:350])
    ahora = _utc(recibido_utc)
    filas = []
    for barra in datos:
        if len(barra) < 6:
            raise ValueError("Bitvavo histórico: vela incompleta")
        # La API no publica VWAP, volumen EUR ni contador de trades.
        filas.append(_fila("bitvavo", intervalo_s, barra[0], *barra[1:5], barra[5], None,
                           True, ahora))
    return pd.DataFrame(filas, columns=COLUMNAS)


def descargar_okx(desde, hasta, intervalo_s: int, max_paginas: int, pedir=pedir_json,
                  dormir=time.sleep, pausa_s: float = 0.15) -> tuple[pd.DataFrame, int, bool]:
    cursor = int(_utc(hasta).timestamp() * 1000)
    limite = int(_utc(desde).timestamp() * 1000)
    datos, paginas, alcanzado = [], 0, False
    while paginas < max_paginas:
        respuesta = pedir(OKX_URL, {"instId": "BTC-EUR", "bar": INTERVALOS[intervalo_s][0],
                                   "after": str(cursor), "limit": "100"})
        pagina = interpretar_okx(respuesta, intervalo_s, pd.Timestamp.now(tz="UTC"))
        paginas += 1
        if pagina.empty:
            # El agotamiento de la API no demuestra cobertura hasta 'desde'.
            alcanzado = False
            break
        datos.append(pagina)
        viejo = int(pagina["inicio_utc"].min().timestamp() * 1000)
        if viejo >= cursor:
            raise RuntimeError("OKX no avanzó el cursor histórico")
        if viejo <= limite:
            alcanzado = True
            break
        cursor = viejo
        if paginas < max_paginas:
            dormir(pausa_s)
    result = pd.concat(datos, ignore_index=True) if datos else pd.DataFrame(columns=COLUMNAS)
    result = result[(result.inicio_utc >= _utc(desde)) & (result.inicio_utc < _utc(hasta))]
    return result.drop_duplicates("inicio_utc").sort_values("inicio_utc"), paginas, alcanzado


def descargar_bitvavo(desde, hasta, intervalo_s: int, max_paginas: int, pedir=pedir_json,
                      dormir=time.sleep, pausa_s: float = 0.15) -> tuple[pd.DataFrame, int, bool]:
    cursor = _utc(desde).ceil(f"{intervalo_s}s")
    fin = _utc(hasta).floor(f"{intervalo_s}s")
    datos, paginas = [], 0
    while cursor < fin and paginas < max_paginas:
        siguiente = min(cursor + pd.Timedelta(seconds=intervalo_s * 1439), fin)
        respuesta = pedir(BITVAVO_URL, {"interval": INTERVALOS[intervalo_s][1],
                                        "start": int(cursor.timestamp() * 1000),
                                        "end": int(siguiente.timestamp() * 1000), "limit": 1440})
        datos.append(interpretar_bitvavo(respuesta, intervalo_s, pd.Timestamp.now(tz="UTC")))
        paginas += 1
        cursor = siguiente
        if cursor < fin and paginas < max_paginas:
            dormir(pausa_s)
    result = pd.concat(datos, ignore_index=True) if datos else pd.DataFrame(columns=COLUMNAS)
    if not result.empty:
        result = result[(result.inicio_utc >= _utc(desde)) & (result.inicio_utc < _utc(hasta))]
        result = result.drop_duplicates("inicio_utc").sort_values("inicio_utc")
    # Bitvavo omite velas de periodos sin trades: no se rellenan.
    return result, paginas, cursor >= fin


def guardar_spot(almacen, velas: pd.DataFrame) -> int:
    if velas.empty:
        return 0
    escritas = 0
    for (exchange, intervalo_s), grupo in velas.groupby(["exchange", "intervalo_s"]):
        if "velas" in almacen.fuentes():
            guardadas = leer_velas(almacen.consultar, f"{exchange}_historico", exchange,
                                   int(intervalo_s), grupo.inicio_utc.min(),
                                   grupo.inicio_utc.max() + pd.Timedelta(seconds=1))
        else:
            guardadas = pd.DataFrame(columns=COLUMNAS)
        nuevas = nuevas_o_mejores(grupo, guardadas)
        if not nuevas.empty:
            almacen.guardar(nuevas.to_dict("records"), "velas")
            escritas += len(nuevas)
    return escritas


def actualizar_spot(almacen, exchanges=("okx", "bitvavo"), intervalos_s=(60, 3600, 86400),
                    desde=None, hasta=None, max_paginas: int = 30,
                    pedir=pedir_json, dormir=time.sleep) -> list[dict]:
    """Actualiza velas comunes y declara explícitamente los errores o límites de cobertura."""
    hasta = _utc(hasta) if hasta is not None else pd.Timestamp.now(tz="UTC")
    desde = _utc(desde) if desde is not None else hasta - pd.Timedelta(days=1)
    if desde >= hasta or max_paginas < 1:
        raise ValueError("Se requiere desde < hasta y max_paginas >= 1")
    if any(x not in INTERVALOS for x in intervalos_s):
        raise ValueError(f"Intervalos admitidos: {sorted(INTERVALOS)}")
    if any(x not in ("okx", "bitvavo") for x in exchanges):
        raise ValueError("Exchanges soportados: okx, bitvavo")
    salida = []
    for exchange in exchanges:
        for intervalo_s in intervalos_s:
            try:
                lector = descargar_okx if exchange == "okx" else descargar_bitvavo
                velas, paginas, cubierta = lector(desde, hasta, intervalo_s, max_paginas, pedir, dormir)
                escritas = guardar_spot(almacen, velas)
                salida.append(dict(exchange=exchange, intervalo_s=intervalo_s, paginas=paginas,
                                   recibidas=len(velas), escritas=escritas,
                                   ventana_completa=bool(cubierta),
                                   primera_utc=velas.inicio_utc.min() if len(velas) else None,
                                   ultima_utc=velas.inicio_utc.max() if len(velas) else None))
            except Exception as exc:
                salida.append(dict(exchange=exchange, intervalo_s=intervalo_s,
                                   error=f"{type(exc).__name__}: {exc}"))
    return salida
