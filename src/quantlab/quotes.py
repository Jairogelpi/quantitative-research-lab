"""Cotizaciones Bid/Ask: obtención, validación y métricas básicas.

Conceptos: docs/conceptos/precios_de_cotizacion.md, spread_y_costes.md
y validacion_de_datos.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"

SYNTHETIC_QUOTE = {
    "source": "synthetic_example",
    "received_at": None,
    "symbol": "BTC/EUR",
    "best_bid": 59998.0,
    "best_ask": 60002.0,
    "last_price": 59999.0,
    "best_bid_volume": 1.0,
    "best_ask_volume": 1.0,
}


def validate_quote(best_bid: float, best_ask: float, last_price: float | None = None) -> None:
    """Lanza ValueError si la cotización no tiene sentido (precios <= 0 o libro cruzado)."""
    if best_bid <= 0:
        raise ValueError(f"Bid no válido: {best_bid}")
    if best_ask < best_bid:
        raise ValueError(f"Libro cruzado: ask {best_ask} < bid {best_bid}")
    if last_price is not None and last_price <= 0:
        raise ValueError(f"Last price no válido: {last_price}")


def quote_metrics(best_bid: float, best_ask: float, last_price: float) -> dict:
    """Métricas básicas de una cotización Bid/Ask y del último precio.

    `last_price_deviation` = last − mid (EUR). No está definida en las lecciones
    1.1 y 1.2; es la convención de este proyecto.
    """
    validate_quote(best_bid, best_ask, last_price)
    mid_price = (best_ask + best_bid) / 2
    spread = best_ask - best_bid
    relative_spread = spread / mid_price
    last_price_deviation = last_price - mid_price
    return {
        "mid_price": mid_price,
        "spread": spread,
        "relative_spread": relative_spread,
        "spread_bps": relative_spread * 10_000,
        "last_price_deviation": last_price_deviation,
        "last_price_deviation_bps": last_price_deviation / mid_price * 10_000,
    }


def round_trip_cost(best_bid: float, best_ask: float, qty: float) -> float:
    """Coste en EUR de comprar y vender `qty` al instante.

    Sin comisiones, con precios constantes y profundidad suficiente en el primer nivel.
    """
    validate_quote(best_bid, best_ask)
    if qty <= 0:
        raise ValueError(f"Cantidad no válida: {qty}")
    return qty * best_ask - qty * best_bid


def fetch_kraken_ticker(pair: str = "XBTEUR", symbol: str = "BTC/EUR", timeout: float = 15) -> dict:
    """Consulta el ticker público de Kraken. No requiere credenciales ni envía órdenes.

    `received_at` es la hora de recepción local, no la hora del evento en el exchange.
    """
    response = requests.get(KRAKEN_TICKER_URL, params={"pair": pair}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload["error"]:
        raise RuntimeError(payload["error"])
    ticker = next(iter(payload["result"].values()))
    quote = {
        "source": "kraken_public_ticker",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "best_bid": float(ticker["b"][0]),
        "best_ask": float(ticker["a"][0]),
        "last_price": float(ticker["c"][0]),
    }
    validate_quote(quote["best_bid"], quote["best_ask"], quote["last_price"])
    return quote


def _kraken_get(endpoint: str, params: dict, timeout: float) -> dict:
    response = requests.get(f"https://api.kraken.com/0/public/{endpoint}", params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload["error"]:
        raise RuntimeError(payload["error"])
    return next(iter(payload["result"].values()))


def fetch_kraken_quote(pair: str = "XBTEUR", symbol: str = "BTC/EUR", timeout: float = 15) -> dict:
    """Bid/Ask y volumen disponible en el mejor nivel (libro de órdenes) + último precio (ticker).

    El volumen del campo "a"/"b" del ticker NO es fiable (Kraken devuelve siempre 1,
    comprobado el 19-11-2026), por eso Bid/Ask y volúmenes salen del endpoint Depth.
    """
    book = _kraken_get("Depth", {"pair": pair, "count": 1}, timeout)
    ticker = _kraken_get("Ticker", {"pair": pair}, timeout)
    quote = {
        "source": "kraken_public_depth+ticker",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "best_bid": float(book["bids"][0][0]),
        "best_ask": float(book["asks"][0][0]),
        "last_price": float(ticker["c"][0]),
        "best_bid_volume": float(book["bids"][0][1]),
        "best_ask_volume": float(book["asks"][0][1]),
    }
    validate_quote(quote["best_bid"], quote["best_ask"], quote["last_price"])
    return quote
