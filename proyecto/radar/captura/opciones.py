"""Foto de la cadena completa de opciones BTC de Deribit, guardada en `opciones_cadena` (Fase 7, S2).

Conceptos:
- Ubicación: el adaptador (`captura/exchanges/deribit.py`) solo habla con Deribit y traduce sus formatos; este caso
  de uso decide qué pedir, une las respuestas y guarda una fila por instrumento y foto.
- Cadena de opciones: todos los strikes de todos los vencimientos vivos, calls y puts. Se lee con
  `get_instruments` (strike, vencimiento, tipo), `get_book_summary_by_currency` (mark, bid, ask, IV del mark,
  subyacente, open interest: toda la cadena en una llamada) y, opcionalmente, un `ticker` por instrumento (griegas
  publicadas, IV de bid y ask, tamaños). Más `get_instruments` de futuros (¿el subyacente de cada vencimiento es
  un futuro listado o un forward sintético?) y `get_index_price` (índice spot btc_usd).
  https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency
- Subyacente por vencimiento: Deribit calcula la IV contra `underlying_price`, "the underlying future, or
  index_price": el futuro de ese vencimiento o, si no lo hay, un forward sintético. `subyacente_es_futuro` lo
  distingue cruzando `underlying_index` con los futuros listados. El 22-11-2026 los 12 vencimientos de opciones
  (también los diarios) tenían su futuro listado.
- Foto no sincronizada: el resumen es casi simultáneo (milisegundos entre filas), pero los tickers se piden uno
  a uno y tardan minutos. Por eso cada ticker guarda su propia hora, subyacente e IV del mark
  (`hora_ticker_utc`, `subyacente_ticker_usd`, `iv_mark_ticker`): las griegas se comparan con esos valores.
- Ritmo educado: la documentación habla de ~20 peticiones por segundo sostenidas
  (https://docs.deribit.com/articles/rate-limits), pero las públicas se limitan por IP y en la práctica
  (22-11-2026) Deribit devolvió HTTP 429 a partir de unas 240 peticiones seguidas a ~4 por segundo, y luego incluso
  a ~3 por segundo. Por eso: `PAUSA_S` entre tickers (2 por segundo), `REINTENTOS` con espera exponencial
  (`ESPERA_S`, 2·`ESPERA_S`...) y, por defecto, solo `MAX_TICKERS` opciones: las más cercanas al forward,
  repartidas entre vencimientos (las que más importan para comparar griegas). El resumen ya trae mark, bid, ask
  e IV de TODA la cadena en una llamada. Un ticker que agota los reintentos deja sus columnas en NaN.
- Idempotencia: `instantanea_utc` = hora más reciente del resumen (`creation_timestamp`). Guardar dos veces la
  misma foto no escribe nada (el lake es append-only y se consulta antes de escribir).
"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np
import pandas as pd

from .exchanges.deribit import Deribit

FUENTE_CADENA = "opciones_cadena"
PAUSA_S = 0.5
MAX_TICKERS = 120
REINTENTOS = 3
ESPERA_S = 2.0
GRIEGAS = ("delta", "gamma", "vega", "theta", "rho")
DEL_TICKER = (*GRIEGAS, "iv_bid", "iv_ask", "iv_mark_ticker", "subyacente_ticker_usd", "cantidad_bid",
              "cantidad_ask", "hora_ticker_utc")
COLUMNAS = ["instantanea_utc", "recibido_utc", "instrumento", "vencimiento_utc", "strike", "tipo_opcion",
            "mark_btc", "bid_btc", "ask_btc", "iv_mark", "iv_bid", "iv_ask", "subyacente_usd", "indice_subyacente",
            "subyacente_es_futuro", "indice_usd", "interes", "open_interest", "comision_taker", "tamano_contrato",
            *GRIEGAS, "iv_mark_ticker", "subyacente_ticker_usd", "cantidad_bid", "cantidad_ask", "hora_resumen_utc",
            "hora_ticker_utc"]


def seleccionar_tickers(cadena: pd.DataFrame, maximo: int | None) -> list[str]:
    """Instrumentos a los que pedir ticker: todos si `maximo` es None; si no, los `maximo` más cercanos al
    forward, repartidos por igual entre vencimientos (primero el más cercano de cada uno, luego el segundo...)."""
    if maximo is None:
        return list(cadena.instrumento)
    distancia = np.abs(np.log(cadena.strike / cadena.subyacente_usd))
    orden = cadena.assign(distancia=distancia).sort_values(["vencimiento_utc", "distancia", "instrumento"])
    orden["puesto"] = orden.groupby("vencimiento_utc").cumcount()
    return list(orden.sort_values(["puesto", "vencimiento_utc", "instrumento"]).instrumento.head(maximo))


def _ticker(cliente, nombre: str, reintentos: int, espera_s: float, dormir: Callable[[float], None]) -> dict:
    for intento in range(reintentos + 1):
        try:
            return cliente.ticker(nombre)
        except Exception:   # 429 (límite por IP), otro error HTTP o de la API
            if intento < reintentos:
                dormir(espera_s * 2 ** intento)
    return {"instrumento": nombre}   # sin griegas publicadas


def _tickers(cliente, instrumentos, pausa_s: float, reintentos: int, espera_s: float,
             dormir: Callable[[float], None]) -> pd.DataFrame:
    filas = []
    for nombre in instrumentos:
        dormir(pausa_s)
        filas.append(_ticker(cliente, nombre, reintentos, espera_s, dormir))
    return pd.DataFrame(filas).reindex(columns=["instrumento", *DEL_TICKER])


def leer_cadena(cliente=None, moneda: str = "BTC", griegas: bool = True, max_tickers: int | None = MAX_TICKERS,
                pausa_s: float = PAUSA_S, reintentos: int = REINTENTOS, espera_s: float = ESPERA_S,
                dormir: Callable[[float], None] = time.sleep, ahora=None) -> pd.DataFrame:
    """Una fila por opción viva con su mark, bid, ask, IV y subyacente; si `griegas`, las griegas publicadas de
    `max_tickers` opciones cercanas al dinero (None: todas)."""
    cliente = cliente or Deribit()
    instrumentos = cliente.instrumentos(moneda, "option")
    resumen = cliente.resumen(moneda, "option")
    futuros = set(cliente.instrumentos(moneda, "future").instrumento)
    indice = cliente.indice(f"{moneda.lower()}_usd")
    cadena = instrumentos.drop(columns=["tipo", "moneda_liquidacion", "tipo_instrumento"]).merge(
        resumen, on="instrumento", how="inner")
    if griegas:
        elegidos = seleccionar_tickers(cadena, max_tickers)
        cadena = cadena.merge(_tickers(cliente, elegidos, pausa_s, reintentos, espera_s, dormir), on="instrumento",
                              how="left")
    else:
        cadena = cadena.reindex(columns=[*cadena.columns, *DEL_TICKER])
    cadena["subyacente_es_futuro"] = cadena.indice_subyacente.isin(futuros)
    cadena["indice_usd"] = indice
    cadena["instantanea_utc"] = cadena.hora_resumen_utc.max()
    cadena["recibido_utc"] = pd.Timestamp.now(tz="UTC") if ahora is None else pd.Timestamp(ahora)
    cadena["hora_ticker_utc"] = pd.to_datetime(cadena.hora_ticker_utc, utc=True)
    for c in DEL_TICKER:
        if c != "hora_ticker_utc":
            cadena[c] = cadena[c].astype(float)
    return cadena[COLUMNAS].sort_values(["vencimiento_utc", "strike", "tipo_opcion"]).reset_index(drop=True)


def _ya_guardada(almacen, instantanea: pd.Timestamp) -> bool:
    if FUENTE_CADENA not in almacen.fuentes():
        return False
    n = almacen.consultar(f"SELECT count(*) AS n FROM {FUENTE_CADENA} "
                          f"WHERE instantanea_utc = TIMESTAMPTZ '{pd.Timestamp(instantanea).isoformat()}'")
    return int(n.n.iloc[0]) > 0


def guardar_cadena(cadena: pd.DataFrame, almacen) -> list:
    """Guarda cada foto (`instantanea_utc`) que aún no esté en `opciones_cadena`. Devuelve las rutas escritas."""
    rutas = []
    for instantanea, foto in cadena.groupby("instantanea_utc"):
        if not _ya_guardada(almacen, instantanea):
            rutas += almacen.guardar(foto.to_dict("records"), FUENTE_CADENA)
    return rutas


def capturar_opciones(almacen, cliente=None, griegas: bool = True, **opciones) -> tuple[pd.DataFrame, list]:
    """Lee la cadena completa y la guarda; (cadena, rutas escritas)."""
    cadena = leer_cadena(cliente, griegas=griegas, **opciones)
    return cadena, guardar_cadena(cadena, almacen)


def resumen_captura(cadena: pd.DataFrame) -> str:
    """Una línea para la consola: tamaño de la foto y cobertura de los tickers."""
    if cadena.empty:
        return "Deribit no devolvió opciones."
    con_griegas = int(cadena.delta.notna().sum())
    vencimientos = cadena.vencimiento_utc.nunique()
    hora = cadena.instantanea_utc.iloc[0]
    sin = len(cadena) - con_griegas
    return (f"Cadena de opciones BTC de Deribit a las {hora:%Y-%m-%d %H:%M:%S} UTC: {len(cadena)} opciones en "
            f"{vencimientos} vencimientos; {con_griegas} con griegas publicadas"
            + (f" ({sin} sin ticker)." if sin else "."))
