"""Adaptador de Deribit (API pública v2, JSON-RPC sobre HTTP GET): cadena de opciones de BTC (Fase 7, S2).

Conceptos:
- Respuesta JSON-RPC: `{"jsonrpc": "2.0", "result": ..., "usIn", "usOut", "usDiff"}`; si falla, trae `error`
  (`code`, `message`) en lugar de `result`, y aquí se convierte en excepción.
- `public/get_instruments` (currency, kind, expired): instrumentos vivos con `expiration_timestamp` (ms),
  `strike`, `option_type`, `contract_size`, `settlement_currency`, `instrument_type` (`linear` o `reversed`) y
  comisiones. Las opciones BTC son `reversed` (inversas): contrato de 1 BTC, strike en USD, prima y liquidación
  en BTC; vencen a las 08:00 UTC (comprobado en todos los vencimientos vivos el 22-11-2026).
  https://docs.deribit.com/api-reference/market-data/public-get_instruments
- `public/get_book_summary_by_currency` (currency, kind): una fila por instrumento con `mark_price`, `mark_iv`,
  `bid_price` / `ask_price` (`null` sin órdenes), `underlying_price` ("underlying price for implied volatility
  calculations"), `underlying_index` ("name of the underlying future, or index_price"), `interest_rate`,
  `open_interest` y `creation_timestamp`. Precios de opciones en BTC; `mark_iv` en puntos porcentuales (64.0 =
  64 %). Toda la cadena en una sola llamada.
  https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency
- `public/ticker` (instrument_name): añade `bid_iv`, `ask_iv`, `best_bid_amount` / `best_ask_amount`,
  `index_price` y `greeks` (delta, gamma, vega, theta, rho; "Black Scholes Delta for individual option
  expiries"; theta como el mínimo entre la de un día y la de la vida restante). `best_bid_price` es 0, no
  `null`, sin órdenes. Una llamada por instrumento.
  https://docs.deribit.com/api-reference/market-data/public-ticker
- `public/get_index_price` (index_name = btc_usd): índice spot de Deribit en USD.
- Límites de peticiones: las públicas se limitan por IP; por defecto, ráfagas de hasta 100 y ~20 por segundo
  sostenidas. Superarlos puede rechazar llamadas o cortar la conexión. https://docs.deribit.com/articles/rate-limits
"""

from __future__ import annotations

import math

import pandas as pd

from .http import pedir_json

URL = "https://www.deribit.com/api/v2/public/"


def resultado(datos):
    """`result` de una respuesta JSON-RPC; un `error` lanza excepción."""
    if "error" in datos:
        error = datos["error"]
        raise ValueError(f"Deribit devolvió un error: {error.get('code')} {error.get('message')}")
    return datos["result"]


def _hora(ms) -> pd.Timestamp:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC")


def _num(v) -> float:
    return math.nan if v is None else float(v)


def interpretar_instrumentos(filas) -> pd.DataFrame:
    """`public/get_instruments` → una fila por instrumento (opción o futuro)."""
    return pd.DataFrame([{
        "instrumento": f["instrument_name"], "tipo": f.get("kind"), "vencimiento_utc": _hora(f["expiration_timestamp"]),
        "strike": _num(f.get("strike")), "tipo_opcion": f.get("option_type"),
        "tamano_contrato": _num(f.get("contract_size")), "moneda_liquidacion": f.get("settlement_currency"),
        "tipo_instrumento": f.get("instrument_type"), "comision_taker": _num(f.get("taker_commission")),
    } for f in filas], columns=["instrumento", "tipo", "vencimiento_utc", "strike", "tipo_opcion", "tamano_contrato",
                                "moneda_liquidacion", "tipo_instrumento", "comision_taker"])


def interpretar_resumen(filas) -> pd.DataFrame:
    """`public/get_book_summary_by_currency` → una fila por instrumento; IV en fracción (0,64), no en puntos."""
    return pd.DataFrame([{
        "instrumento": f["instrument_name"], "mark_btc": _num(f.get("mark_price")), "bid_btc": _num(f.get("bid_price")),
        "ask_btc": _num(f.get("ask_price")), "iv_mark": _num(f.get("mark_iv")) / 100,
        "subyacente_usd": _num(f.get("underlying_price")), "indice_subyacente": f.get("underlying_index"),
        "interes": _num(f.get("interest_rate")), "open_interest": _num(f.get("open_interest")),
        "precio_entrega_estimado": _num(f.get("estimated_delivery_price")),
        "hora_resumen_utc": _hora(f["creation_timestamp"]),
    } for f in filas], columns=["instrumento", "mark_btc", "bid_btc", "ask_btc", "iv_mark", "subyacente_usd",
                                "indice_subyacente", "interes", "open_interest", "precio_entrega_estimado",
                                "hora_resumen_utc"])


def interpretar_ticker(t) -> dict:
    """`public/ticker` de una opción → griegas publicadas, IV de bid y ask (fracción; NaN sin órdenes) y tamaños."""
    griegas = t.get("greeks") or {}
    sin_bid = not t.get("best_bid_price")
    sin_ask = not t.get("best_ask_price")
    return {
        "instrumento": t["instrument_name"], **{g: _num(griegas.get(g)) for g in ("delta", "gamma", "vega", "theta",
                                                                                  "rho")},
        "iv_bid": math.nan if sin_bid else _num(t.get("bid_iv")) / 100,
        "iv_ask": math.nan if sin_ask else _num(t.get("ask_iv")) / 100,
        "iv_mark_ticker": _num(t.get("mark_iv")) / 100, "subyacente_ticker_usd": _num(t.get("underlying_price")),
        "cantidad_bid": _num(t.get("best_bid_amount")), "cantidad_ask": _num(t.get("best_ask_amount")),
        "indice_usd": _num(t.get("index_price")), "hora_ticker_utc": _hora(t["timestamp"]),
    }


class Deribit:
    nombre = "deribit"

    def __init__(self, pedir=pedir_json):
        self._pedir = pedir

    def _llamar(self, metodo: str, **params):
        return resultado(self._pedir(URL + metodo, params))

    def instrumentos(self, moneda: str = "BTC", tipo: str = "option") -> pd.DataFrame:
        return interpretar_instrumentos(self._llamar("get_instruments", currency=moneda, kind=tipo, expired="false"))

    def resumen(self, moneda: str = "BTC", tipo: str = "option") -> pd.DataFrame:
        return interpretar_resumen(self._llamar("get_book_summary_by_currency", currency=moneda, kind=tipo))

    def ticker(self, instrumento: str) -> dict:
        return interpretar_ticker(self._llamar("ticker", instrument_name=instrumento))

    def indice(self, nombre: str = "btc_usd") -> float:
        return float(self._llamar("get_index_price", index_name=nombre)["index_price"])
