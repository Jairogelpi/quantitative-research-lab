"""Adaptador del histórico PÚBLICO de perpetuos BTC: OKX (BTC-USDT-SWAP) y Kraken Futures (PF_XBTUSD).

Nuestros exchanges spot (BTC/EUR) no tienen derivados; estos dos sí publican su histórico sin clave.

Conceptos (comprobado en la documentación oficial y con respuestas reales del 22-11-2026):
- OKX, documentación v5: https://www.okx.com/docs-v5/en/ . Todas las respuestas son `{"code": "0", "msg": "",
  "data": [...]}`; un `code` distinto de "0" es un error. Las listas llegan de la más reciente a la más antigua
  y `after` pide registros ANTERIORES al cursor dado (paginación hacia atrás).
  - Funding, `GET /api/v5/public/funding-rate-history` (sección "Get funding rate history"): "This endpoint can
    return data up to three months". `limit` máximo 400; 10 peticiones / 2 s por IP e instrumento. Cada fila trae
    `fundingTime` (hora del cobro, ms), `fundingRate` y `realizedRate` (la tasa que se liquidó). Se usa
    `realizedRate`. Comprobado: 286 pagos (19-08-2026 → 22-11-2026), cada 8 h, y una petición más antigua devuelve
    vacío. El intervalo de un contrato puede cambiar: se toma la diferencia entre pagos consecutivos.
  - Mark, `GET /api/v5/market/history-mark-price-candles` ("candlestick charts of mark price from recent
    years"; `limit` 100; 20 peticiones / 2 s). Índice, `GET /api/v5/market/history-index-candles` (instId
    `BTC-USDT`; `limit` 100; 10 / 2 s). Precio negociado del perpetuo, `GET /api/v5/market/history-candles`
    (`limit` 100; 20 / 2 s). Barras `[ts, o, h, l, c, confirm]` (mark e índice) y `[ts, o, h, l, c, vol, volCcy,
    volCcyQuote, confirm]` (perpetuo; `volCcy` en BTC); `confirm` = "1" si la barra está cerrada; `bar=1H` es la
    hora UTC. Comprobado: hay barras horarias al menos desde 2023. `/market/mark-price-candles` y
    `/market/index-candles` (sin "history") solo sirven las últimas 1 440 barras.
  - Open interest, `GET /api/v5/rubik/stat/contracts/open-interest-history` ("can retrieve the latest 1,440 data
    entries"; `limit` 100; paginación con `end`; 10 / 2 s). Filas `[ts, oi (contratos), oiCcy (BTC), oiUsd]`. Con
    `period=1H` son 60 días: comprobado, nada antes del 22-09-2026. La fila de la hora en curso se actualiza (su
    `ts` es el inicio de la hora). `/rubik/stat/contracts/open-interest-volume` (por moneda, todos los contratos)
    solo da "1H granularity ... within 30 days at most" y no se usa.
  - Liquidaciones, `GET /api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled`: ya NO está en
    la documentación v5 (solo el canal WebSocket "liquidation-orders", que avisa: "This data doesn't represent the
    total number of liquidations on OKX"), pero responde. Cada orden: `posSide` (lado de la posición liquidada),
    `bkPx` (precio de quiebra), `sz` (contratos; `ctVal` = 0,01 BTC y `lotSz` = 0,01 en BTC-USDT-SWAP, comprobado
    en `/api/v5/public/instruments`), `time` (ms). Páginas de 100 con `after`; comprobado: unas 33 páginas, ~24 h.
    Es una muestra, no el total.
- Kraken Futures (https://docs.kraken.com/api-reference/ ; servidor https://futures.kraken.com):
  - Funding, `GET /derivatives/api/v3/historical-funding-rates?symbol=PF_XBTUSD`
    (https://docs.kraken.com/api-reference/historical-funding-rates/historical-funding-rates): lista ascendente con
    `timestamp` = "Start of the period to which the funding rate applies", `fundingRate` ("absolute funding rate",
    USD por contrato y periodo) y `relativeFundingRate` (la misma tasa dividida por el precio). Comprobado: una
    fila por HORA, 8 839 filas desde el 19-11-2025 (un año) en una sola respuesta, y `fundingRate /
    relativeFundingRate` ≈ el precio de BTC. El contrato PF_XBTUSD vale 1 BTC (`contractSize` = 1 en
    `/derivatives/api/v3/instruments`), así que el pago por BTC y hora es `fundingRate` en USD.
  - Velas, `GET /api/charts/v1/{tick_type}/{symbol}/{resolution}?from=&to=` (segundos)
    (https://docs.kraken.com/api-reference/candles/market-candles): `tick_type` ∈ {spot, mark, trade}
    (https://docs.kraken.com/api-reference/candles/tick-types); `spot` es el índice de referencia del subyacente,
    `mark` el precio de marca y `trade` el negociado. Velas `{time (ms), open, high, low, close, volume}`.
    Comprobado: hasta 2 000 velas por petición y horas desde 2022 (el contrato abrió el 22-03-2022).
  - Analítica, `GET /api/charts/v1/analytics/{symbol}/{analytics_type}?since=&interval=&to=` (especificación
    OpenAPI https://docs.kraken.com/openapi/futures-charts-rest.yaml, tipos `open-interest`,
    `liquidation-volume`, `funding`…; `interval` en segundos, 3600 = hora). Respuesta `{"result": {"timestamp":
    [...], "data": [...], "more": bool}}`. Open interest: OHLC por hora en contratos (= BTC); se usa el cierre.
    Liquidaciones: volumen liquidado por hora en contratos (= BTC), SIN separar largos y cortos. Comprobado: 2 000
    horas por petición y `more` = true si hay más; datos desde marzo de 2022.
- Límites: OKX documenta 10-20 peticiones / 2 s; `PAUSA_OKX_S` = 0,25 s (4 por segundo) queda por debajo. Kraken no
  documenta el límite de la API de gráficos; `PAUSA_KRAKEN_S` = 0,5 s es una pausa prudente.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from .http import pedir_json

OKX = "https://www.okx.com"
URL_OKX_FUNDING = f"{OKX}/api/v5/public/funding-rate-history"
URL_OKX_MARK = f"{OKX}/api/v5/market/history-mark-price-candles"
URL_OKX_INDICE = f"{OKX}/api/v5/market/history-index-candles"
URL_OKX_PERP = f"{OKX}/api/v5/market/history-candles"
URL_OKX_OI = f"{OKX}/api/v5/rubik/stat/contracts/open-interest-history"
URL_OKX_LIQUIDACIONES = f"{OKX}/api/v5/public/liquidation-orders"
OKX_SWAP, OKX_INDICE, OKX_SUBYACENTE = "BTC-USDT-SWAP", "BTC-USDT", "BTC-USDT"
OKX_CT_VAL = 0.01                  # BTC por contrato de BTC-USDT-SWAP
OKX_LIMITE_VELAS, OKX_LIMITE_FUNDING, OKX_LIMITE_OI = 100, 400, 100

KRAKEN = "https://futures.kraken.com"
URL_KRAKEN_FUNDING = f"{KRAKEN}/derivatives/api/v3/historical-funding-rates"
URL_KRAKEN_VELAS = f"{KRAKEN}/api/charts/v1"
URL_KRAKEN_ANALITICA = f"{KRAKEN}/api/charts/v1/analytics"
KRAKEN_PERP = "PF_XBTUSD"
KRAKEN_TIPOS = {"mark": "mark", "indice": "spot", "perp": "trade"}   # nuestro nombre → tick_type de Kraken
KRAKEN_MAX_VELAS = 2000

PAUSA_OKX_S = 0.25
PAUSA_KRAKEN_S = 0.5
HORA_S = 3600
FUNDING = ["exchange", "instrumento", "periodo_fin_utc", "periodo_h", "tasa", "tasa_prevista", "tasa_absoluta"]
VELA = ["inicio_utc", "apertura", "maximo", "minimo", "cierre", "volumen", "completa"]
OI = ["inicio_utc", "oi_contratos", "oi_btc", "oi_usd"]
LIQUIDACION = ["hora_utc", "lado", "precio", "cantidad_btc"]
ANALITICA = ["inicio_utc", "valor"]


def _ms(serie) -> pd.Series:
    return pd.to_datetime(pd.Series(serie).astype("int64"), unit="ms", utc=True)


def _ok_okx(datos) -> list:
    if str(datos.get("code")) != "0":
        raise ValueError(f"OKX devolvió un error: {datos.get('code')} {datos.get('msg')}")
    return datos.get("data") or []


def _ok_kraken(datos) -> dict:
    resultado = datos.get("result")
    if (isinstance(resultado, str) and resultado != "success") or datos.get("errors") or datos.get("error"):
        raise ValueError(f"Kraken Futures devolvió un error: {datos.get('error') or datos.get('errors')}")
    return datos


# --- Interpretación de respuestas ---------------------------------------------------------------------------------

def interpretar_okx_funding(datos, instrumento: str = OKX_SWAP) -> pd.DataFrame:
    """`/public/funding-rate-history` → pagos (columnas `FUNDING`), en orden temporal; `tasa` = `realizedRate`."""
    filas = _ok_okx(datos)
    if not filas:
        return pd.DataFrame(columns=FUNDING)
    crudo = pd.DataFrame(filas)
    f = pd.DataFrame({"periodo_fin_utc": _ms(crudo["fundingTime"]),
                      "tasa": pd.to_numeric(crudo["realizedRate"], errors="coerce"),
                      "tasa_prevista": pd.to_numeric(crudo["fundingRate"], errors="coerce")})
    f = f.sort_values("periodo_fin_utc").reset_index(drop=True)
    horas = f["periodo_fin_utc"].diff().dt.total_seconds() / HORA_S
    f["periodo_h"] = horas.bfill() if len(f) > 1 else 8.0      # el primero: el intervalo del siguiente
    f["tasa"] = f["tasa"].fillna(f["tasa_prevista"])
    f["exchange"], f["instrumento"], f["tasa_absoluta"] = "okx", instrumento, np.nan
    return f[FUNDING]


def interpretar_okx_velas(datos) -> pd.DataFrame:
    """Barras de mark, índice o perpetuo de OKX → `VELA` en orden temporal (volumen en BTC solo en el perpetuo)."""
    filas = _ok_okx(datos)
    if not filas:
        return pd.DataFrame(columns=VELA)
    v = pd.DataFrame({"inicio_utc": _ms([f[0] for f in filas])})
    for i, col in enumerate(["apertura", "maximo", "minimo", "cierre"], start=1):
        v[col] = [float(f[i]) for f in filas]
    v["volumen"] = [float(f[6]) if len(f) >= 9 else math.nan for f in filas]
    v["completa"] = [str(f[-1]) == "1" for f in filas]
    return v.sort_values("inicio_utc").reset_index(drop=True)[VELA]


def interpretar_okx_oi(datos) -> pd.DataFrame:
    """`/rubik/stat/contracts/open-interest-history` → `OI` en orden temporal."""
    filas = _ok_okx(datos)
    if not filas:
        return pd.DataFrame(columns=OI)
    oi = pd.DataFrame({"inicio_utc": _ms([f[0] for f in filas]), "oi_contratos": [float(f[1]) for f in filas],
                       "oi_btc": [float(f[2]) for f in filas], "oi_usd": [float(f[3]) for f in filas]})
    return oi.sort_values("inicio_utc").reset_index(drop=True)


def interpretar_okx_liquidaciones(datos, instrumento: str = OKX_SWAP, ct_val: float = OKX_CT_VAL) -> pd.DataFrame:
    """`/public/liquidation-orders` → órdenes (`LIQUIDACION`) del instrumento, en orden temporal."""
    filas = [d for bloque in _ok_okx(datos) if bloque.get("instId", instrumento) == instrumento
             for d in bloque.get("details", [])]
    if not filas:
        return pd.DataFrame(columns=LIQUIDACION)
    liq = pd.DataFrame({"hora_utc": _ms([int(d.get("time") or d["ts"]) for d in filas]),
                        "lado": [d["posSide"] for d in filas], "precio": [float(d["bkPx"]) for d in filas],
                        "cantidad_btc": [float(d["sz"]) * ct_val for d in filas]})
    return liq.sort_values("hora_utc", kind="stable").reset_index(drop=True)


def interpretar_kraken_funding(datos, instrumento: str = KRAKEN_PERP) -> pd.DataFrame:
    """`historical-funding-rates` → pagos horarios (`FUNDING`); el periodo empieza en `timestamp` y dura 1 h."""
    filas = _ok_kraken(datos).get("rates")
    if filas is None:
        raise ValueError(f"Kraken Futures devolvió un error: {datos}")
    if not filas:
        return pd.DataFrame(columns=FUNDING)
    crudo = pd.DataFrame(filas)
    inicio = pd.to_datetime(crudo["timestamp"], utc=True)
    f = pd.DataFrame({"periodo_fin_utc": inicio + pd.Timedelta(hours=1), "periodo_h": 1.0,
                      "tasa": crudo["relativeFundingRate"].astype(float), "tasa_prevista": np.nan,
                      "tasa_absoluta": crudo["fundingRate"].astype(float)})
    f["exchange"], f["instrumento"] = "kraken", instrumento
    return f.sort_values("periodo_fin_utc").reset_index(drop=True)[FUNDING]


def interpretar_kraken_velas(datos, intervalo_s: int, recibido_utc) -> pd.DataFrame:
    """Velas de la API de gráficos → `VELA`; completa si terminó antes de `recibido_utc`."""
    filas = datos.get("candles")
    if filas is None:
        raise ValueError(f"Kraken Futures devolvió un error: {datos}")
    if not filas:
        return pd.DataFrame(columns=VELA)
    crudo = pd.DataFrame(filas)
    v = pd.DataFrame({"inicio_utc": _ms(crudo["time"])})
    for destino, origen in zip(VELA[1:6], ["open", "high", "low", "close", "volume"]):
        v[destino] = pd.to_numeric(crudo[origen]).astype(float)
    v["completa"] = v["inicio_utc"] + pd.Timedelta(seconds=intervalo_s) <= pd.Timestamp(recibido_utc)
    return v.sort_values("inicio_utc").drop_duplicates("inicio_utc").reset_index(drop=True)[VELA]


def interpretar_kraken_analitica(datos) -> pd.DataFrame:
    """Analítica de Kraken → (`inicio_utc`, `valor`): el cierre si cada dato es un OHLC, el número si no."""
    r = _ok_kraken(datos).get("result")
    if r is None:
        raise ValueError(f"Kraken Futures devolvió un error: {datos}")
    tiempos, valores = r.get("timestamp") or [], r.get("data") or []
    escala = 1000 if tiempos and max(tiempos) > 10 ** 11 else 1    # `funding` responde en ms; el resto, en s
    valor = [float(x[3]) if isinstance(x, (list, tuple)) else float(x) for x in valores]
    return pd.DataFrame({"inicio_utc": pd.to_datetime(pd.Series(tiempos, dtype="int64") // escala, unit="s",
                                                      utc=True), "valor": valor})


# --- Paginación --------------------------------------------------------------------------------------------------

def _ms_de(t) -> str:
    return str(int(pd.Timestamp(t).value // 1_000_000))


def _hacia_atras(url, params, cursor, interpretar, columna, desde_utc, pedir, dormir, pausa_s) -> pd.DataFrame:
    """Pide páginas de OKX hacia atrás (`cursor` = 'after' o 'end') hasta pasar `desde_utc` o recibir una vacía."""
    paginas, valor = [], None
    while True:
        p = dict(params)
        if valor is not None:
            p[cursor] = valor
        pagina = interpretar(pedir(url, p))
        if pagina.empty:
            break
        paginas.append(pagina)
        primero = pagina[columna].min()
        nuevo = _ms_de(primero)
        if primero <= desde_utc or nuevo == valor:
            break
        valor = nuevo
        dormir(pausa_s)
    if not paginas:
        return interpretar({"code": "0", "data": []})
    todo = pd.concat(paginas, ignore_index=True)
    todo = todo[todo[columna] >= desde_utc]
    return todo.sort_values(columna, kind="stable").reset_index(drop=True)


def descargar_okx_velas(url, instrumento, desde_utc, pedir=pedir_json, dormir=time.sleep, pausa_s=PAUSA_OKX_S,
                        barra: str = "1H") -> pd.DataFrame:
    v = _hacia_atras(url, {"instId": instrumento, "bar": barra, "limit": OKX_LIMITE_VELAS}, "after",
                     interpretar_okx_velas, "inicio_utc", pd.Timestamp(desde_utc), pedir, dormir, pausa_s)
    return v.drop_duplicates("inicio_utc", keep="last").reset_index(drop=True)


def descargar_okx_funding(desde_utc, pedir=pedir_json, dormir=time.sleep, pausa_s=PAUSA_OKX_S) -> pd.DataFrame:
    f = _hacia_atras(URL_OKX_FUNDING, {"instId": OKX_SWAP, "limit": OKX_LIMITE_FUNDING}, "after",
                     interpretar_okx_funding, "periodo_fin_utc", pd.Timestamp(desde_utc), pedir, dormir, pausa_s)
    f = f.drop_duplicates("periodo_fin_utc").reset_index(drop=True)
    if len(f) > 1:   # recalcula el periodo con la serie entera (las páginas cortan pares de pagos)
        f["periodo_h"] = (f["periodo_fin_utc"].diff().dt.total_seconds() / HORA_S).bfill()
    return f


def descargar_okx_oi(desde_utc, pedir=pedir_json, dormir=time.sleep, pausa_s=PAUSA_OKX_S) -> pd.DataFrame:
    oi = _hacia_atras(URL_OKX_OI, {"instId": OKX_SWAP, "period": "1H", "limit": OKX_LIMITE_OI}, "end",
                      interpretar_okx_oi, "inicio_utc", pd.Timestamp(desde_utc), pedir, dormir, pausa_s)
    return oi.drop_duplicates("inicio_utc", keep="last").reset_index(drop=True)


def descargar_okx_liquidaciones(desde_utc, pedir=pedir_json, dormir=time.sleep, pausa_s=PAUSA_OKX_S) -> pd.DataFrame:
    params = {"instType": "SWAP", "uly": OKX_SUBYACENTE, "state": "filled"}
    return _hacia_atras(URL_OKX_LIQUIDACIONES, params, "after", interpretar_okx_liquidaciones, "hora_utc",
                        pd.Timestamp(desde_utc), pedir, dormir, pausa_s)


def descargar_kraken_velas(tipo: str, desde_utc, hasta_utc, recibido_utc, pedir=pedir_json, dormir=time.sleep,
                           pausa_s=PAUSA_KRAKEN_S, por_pagina: int = KRAKEN_MAX_VELAS) -> pd.DataFrame:
    """Velas horarias de `tipo` (mark, indice, perp) de [desde, hasta], en páginas de `por_pagina` horas."""
    url = f"{URL_KRAKEN_VELAS}/{KRAKEN_TIPOS[tipo]}/{KRAKEN_PERP}/1h"
    inicio, fin = int(pd.Timestamp(desde_utc).timestamp()), int(pd.Timestamp(hasta_utc).timestamp())
    paginas = []
    while inicio <= fin:
        hasta = min(fin, inicio + (por_pagina - 1) * HORA_S)
        paginas.append(interpretar_kraken_velas(pedir(url, {"from": inicio, "to": hasta}), HORA_S, recibido_utc))
        inicio = hasta + HORA_S
        if inicio <= fin:
            dormir(pausa_s)
    v = pd.concat([p for p in paginas if not p.empty] or [pd.DataFrame(columns=VELA)], ignore_index=True)
    return v.drop_duplicates("inicio_utc", keep="last").sort_values("inicio_utc").reset_index(drop=True)


def descargar_kraken_analitica(tipo: str, desde_utc, hasta_utc, pedir=pedir_json, dormir=time.sleep,
                               pausa_s=PAUSA_KRAKEN_S) -> pd.DataFrame:
    """Analítica horaria (`open-interest`, `liquidation-volume`) desde `desde_utc`, siguiendo `more`."""
    url = f"{URL_KRAKEN_ANALITICA}/{KRAKEN_PERP}/{tipo}"
    desde, hasta = int(pd.Timestamp(desde_utc).timestamp()), int(pd.Timestamp(hasta_utc).timestamp())
    paginas = []
    while desde <= hasta:
        datos = pedir(url, {"since": desde, "interval": HORA_S, "to": hasta})
        pagina = interpretar_kraken_analitica(datos)
        if pagina.empty:
            break
        paginas.append(pagina)
        siguiente = int(pagina["inicio_utc"].max().timestamp()) + HORA_S
        if not datos["result"].get("more") or siguiente <= desde:
            break
        desde = siguiente
        dormir(pausa_s)
    v = pd.concat(paginas or [pd.DataFrame(columns=ANALITICA)], ignore_index=True)
    return v.drop_duplicates("inicio_utc", keep="last").sort_values("inicio_utc").reset_index(drop=True)


# --- Descargas completas por exchange ------------------------------------------------------------------------------

def leer_okx(desde_utc, ahora_utc, pedir=pedir_json, dormir=time.sleep) -> dict:
    """Todo lo que OKX sirve desde `desde_utc` (cada endpoint, hasta donde llegue su histórico)."""
    return {"funding": descargar_okx_funding(desde_utc, pedir, dormir),
            "precios": {"mark": descargar_okx_velas(URL_OKX_MARK, OKX_SWAP, desde_utc, pedir, dormir),
                        "indice": descargar_okx_velas(URL_OKX_INDICE, OKX_INDICE, desde_utc, pedir, dormir),
                        "perp": descargar_okx_velas(URL_OKX_PERP, OKX_SWAP, desde_utc, pedir, dormir)},
            "oi": descargar_okx_oi(desde_utc, pedir, dormir),
            "liquidaciones": descargar_okx_liquidaciones(desde_utc, pedir, dormir)}


def leer_kraken(desde_utc, ahora_utc, pedir=pedir_json, dormir=time.sleep) -> dict:
    """Todo lo que Kraken Futures sirve desde `desde_utc` (el funding: el año que devuelve el endpoint)."""
    f = interpretar_kraken_funding(pedir(URL_KRAKEN_FUNDING, {"symbol": KRAKEN_PERP}))
    return {"funding": f[f["periodo_fin_utc"] >= pd.Timestamp(desde_utc)].reset_index(drop=True),
            "precios": {t: descargar_kraken_velas(t, desde_utc, ahora_utc, ahora_utc, pedir, dormir)
                        for t in KRAKEN_TIPOS},
            "oi": descargar_kraken_analitica("open-interest", desde_utc, ahora_utc, pedir, dormir),
            "liquidaciones": descargar_kraken_analitica("liquidation-volume", desde_utc, ahora_utc, pedir, dormir)}


LECTORES = {"okx": leer_okx, "kraken": leer_kraken}
