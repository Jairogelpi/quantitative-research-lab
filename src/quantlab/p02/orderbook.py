"""Libro de órdenes (nivel 2): normalización, profundidad, OBI, microprice y simulación de ejecución.

Origen: P02 · Análisis del libro de órdenes. Concepto: docs/conceptos/libro_de_ordenes.md
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

EXAMPLE_BOOK = {
    "bids": [[59998, 0.2], [59995, 0.5], [59990, 0.8], [59980, 1.2], [59960, 2]],
    "asks": [[60002, 0.1], [60005, 0.3], [60010, 0.6], [60020, 1], [60040, 1.5]],
}

_EPS = 1e-12


def fetch_kraken_book(pair: str = "XBTEUR", levels: int = 50, timeout: float = 15) -> tuple[dict, str]:
    """Snapshot público del libro (endpoint Depth). Devuelve (libro, hora de recepción UTC).

    Si la API falla lanza la excepción: nunca se sustituye por datos ficticios.
    """
    response = requests.get("https://api.kraken.com/0/public/Depth",
                            params={"pair": pair, "count": levels}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload["error"]:
        raise RuntimeError(payload["error"])
    return next(iter(payload["result"].values())), datetime.now(timezone.utc).isoformat()


def normalize_book(raw: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bids de mayor a menor precio, asks de menor a mayor. Valida y añade nocional y acumulado."""
    tables = []
    for side in ("bids", "asks"):
        rows = raw.get(side)
        if not rows:
            raise ValueError(f"Lado vacío: {side}")
        df = pd.DataFrame(rows, columns=["price", "quantity_btc", "level_timestamp_s"][: len(rows[0])])
        df[["price", "quantity_btc"]] = df[["price", "quantity_btc"]].astype(float)
        values = df[["price", "quantity_btc"]]
        if not np.isfinite(values).all().all() or (values <= 0).any().any():
            raise ValueError("Precio o cantidad inválidos")
        if df.price.duplicated().any():
            raise ValueError("Niveles de precio duplicados")
        df = df.sort_values("price", ascending=side == "asks").reset_index(drop=True)
        df["notional_eur"] = df.price * df.quantity_btc
        df["cumulative_btc"] = df.quantity_btc.cumsum()
        df["side"] = side
        tables.append(df)
    bids, asks = tables
    if bids.price.iloc[0] >= asks.price.iloc[0]:
        raise ValueError("Libro cruzado o bloqueado; revisar snapshot")
    return bids, asks


def book_features(bids: pd.DataFrame, asks: pd.DataFrame, n_levels: int = 5) -> dict:
    """Profundidad, OBI y microprice con los N primeros niveles de cada lado."""
    if not 1 <= n_levels <= min(len(bids), len(asks)):
        raise ValueError("Número de niveles no disponible en ambos lados")
    b, a = bids.head(n_levels), asks.head(n_levels)
    bid, ask = b.price.iloc[0], a.price.iloc[0]
    mid = (bid + ask) / 2
    bd, ad = b.quantity_btc.sum(), a.quantity_btc.sum()
    bq, aq = b.quantity_btc.iloc[0], a.quantity_btc.iloc[0]
    return {
        "n_levels": n_levels, "best_bid": bid, "best_ask": ask,
        "mid_price": mid, "spread_bps": (ask - bid) / mid * 10_000,
        "bid_depth_btc": bd, "ask_depth_btc": ad,
        "bid_notional_eur": b.notional_eur.sum(), "ask_notional_eur": a.notional_eur.sum(),
        "order_book_imbalance": (bd - ad) / (bd + ad),
        "microprice": (ask * bq + bid * aq) / (bq + aq),
    }


def depth_within_bps(bids: pd.DataFrame, asks: pd.DataFrame, band_bps: float = 5) -> dict:
    """E4 · Profundidad en BTC dentro de ±band_bps del mid (solo niveles del snapshot).

    `complete_*` es False si el último nivel recibido sigue dentro de la banda:
    entonces puede haber más liquidez fuera del snapshot y la cifra es un mínimo.
    """
    if not np.isfinite(band_bps) or band_bps < 0:
        raise ValueError("La banda debe ser >= 0 bps")
    mid = (bids.price.iloc[0] + asks.price.iloc[0]) / 2
    lo, hi = mid * (1 - band_bps / 10_000), mid * (1 + band_bps / 10_000)
    b_in, a_in = bids[bids.price >= lo], asks[asks.price <= hi]
    return {
        "band_bps": band_bps, "mid_price": mid,
        "bid_depth_btc": float(b_in.quantity_btc.sum()), "ask_depth_btc": float(a_in.quantity_btc.sum()),
        "bid_levels": len(b_in), "ask_levels": len(a_in),
        "complete_bid": len(b_in) < len(bids), "complete_ask": len(a_in) < len(asks),
    }


def simulate_market_order(bids: pd.DataFrame, asks: pd.DataFrame, side: str, quantity_btc: float):
    """Recorre el libro en orden de ejecución. No inventa liquidez más allá del snapshot.

    Slippage adverso frente al mejor precio del lado ejecutado:
    compra (VWAP/best_ask − 1)·10.000 · venta (1 − VWAP/best_bid)·10.000
    """
    if side not in ("buy", "sell") or not np.isfinite(quantity_btc) or quantity_btc <= 0:
        raise ValueError("Lado o cantidad inválidos")
    book = asks if side == "buy" else bids
    best = book.price.iloc[0]
    remaining = float(quantity_btc)
    fills = []
    for row in book.itertuples(index=False):
        take = min(remaining, row.quantity_btc)
        if take <= _EPS:
            break
        fills.append({"price": row.price, "filled_btc": take, "notional_eur": take * row.price})
        remaining -= take
    fills = pd.DataFrame(fills, columns=["price", "filled_btc", "notional_eur"])
    filled = float(fills.filled_btc.sum())
    notional = float(fills.notional_eur.sum())
    vwap = notional / filled if filled else np.nan
    slippage = (vwap / best - 1) * 10_000 * (1 if side == "buy" else -1)
    return {
        "side": side, "requested_btc": quantity_btc, "filled_btc": filled,
        "unfilled_btc": max(0.0, quantity_btc - filled),
        "complete": bool(np.isclose(filled, quantity_btc, rtol=0, atol=_EPS)),
        "best_price": best, "execution_price": vwap, "slippage_bps": slippage,
        "levels_used": len(fills), "notional_eur": notional,
    }, fills
