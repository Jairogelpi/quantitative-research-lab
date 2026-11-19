"""Operaciones ejecutadas (trades): normalización, volumen, VWAP, Trade Imbalance, CVD y agregación temporal.

Origen: P03 · Análisis de operaciones ejecutadas. Concepto: docs/conceptos/operaciones_ejecutadas.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import requests

KRAKEN_TRADES_URL = "https://api.kraken.com/0/public/Trades"

SYNTHETIC_BASE_S = pd.Timestamp("2026-01-01T10:00:00Z").timestamp()

# Cinco operaciones de ejemplo con el esquema de Kraken:
# [precio, cantidad, timestamp (s), lado, tipo de orden, misceláneo, trade_id]
EXAMPLE_TRADES = [
    [p, q, SYNTHETIC_BASE_S + t, side, order_type, "", trade_id]
    for p, q, t, side, order_type, trade_id in [
        ("60000", "0.10", 1, "b", "m", 1),
        ("60005", "0.50", 2, "b", "m", 2),
        ("60003", "0.20", 3, "s", "l", 3),
        ("60010", "0.80", 4, "b", "l", 4),
        ("60008", "0.40", 5, "s", "m", 5),
    ]
]


def normalize_trades(rows: list) -> pd.DataFrame:
    """Convierte filas de Kraken en un DataFrame validado y ordenado por timestamp.

    Lanza ValueError si la respuesta está vacía, tiene un esquema inesperado, valores
    inválidos (precio o cantidad <= 0 o no finitos, lado distinto de b/s) o IDs duplicados.
    """
    if not rows or any(len(r) not in (6, 7) for r in rows):
        raise ValueError("Respuesta vacía o esquema inesperado")
    records = [{"price": r[0], "quantity": r[1], "timestamp": r[2],
                "side": r[3], "order_type": r[4],
                "trade_id": str(r[6]) if len(r) == 7 else None} for r in rows]
    df = pd.DataFrame(records)
    for col in ["price", "quantity"]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True, errors="raise")
    if (not np.isfinite(df[["price", "quantity"]]).all().all()
            or (df[["price", "quantity"]] <= 0).any().any()
            or df["timestamp"].isna().any() or not df["side"].isin(["b", "s"]).all()):
        raise ValueError("Precios, cantidades, timestamps o lados inválidos")
    ids = df["trade_id"].dropna()
    if ids.duplicated().any():
        raise ValueError("IDs duplicados: revisar la captura")
    # Conserva el orden de llegada si dos eventos tienen la misma hora.
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def add_trade_features(df: pd.DataFrame) -> pd.DataFrame:
    """Añade nocional, volumen con signo (+compra / −venta agresiva), CVD y VWAP acumulado."""
    out = df.copy()
    out["notional"] = out["price"] * out["quantity"]
    out["signed_volume"] = out["quantity"] * out["side"].map({"b": 1, "s": -1})
    out["cvd"] = out["signed_volume"].cumsum()
    out["cumulative_vwap"] = out["notional"].cumsum() / out["quantity"].cumsum()
    return out


def summarize_trades(df: pd.DataFrame) -> pd.Series:
    """Resumen de una muestra: volumen base y nominal, compras, ventas, imbalance, VWAP y tamaño medio."""
    volume = df["quantity"].sum()
    buy = df.loc[df["side"].eq("b"), "quantity"].sum()
    sell = df.loc[df["side"].eq("s"), "quantity"].sum()
    notional = (df["price"] * df["quantity"]).sum()
    return pd.Series({"trade_count": len(df), "trade_volume": volume,
                      "notional_volume": notional, "buy_volume": buy,
                      "sell_volume": sell, "signed_volume": buy - sell,
                      "trade_imbalance": (buy - sell) / volume if volume else np.nan,
                      "vwap": notional / volume if volume else np.nan,
                      "average_trade_size": volume / len(df) if len(df) else np.nan})


def aggregate_trades(df: pd.DataFrame, window: str = "10s") -> pd.DataFrame:
    """Ventanas no solapadas [inicio, fin) etiquetadas con su cierre.

    Una ventana vacía tiene volumen 0, pero VWAP e imbalance indefinidos (NaN).
    La primera y la última ventana se marcan como frontera (`boundary_window`): pueden estar incompletas.
    """
    data = add_trade_features(df).set_index("timestamp")
    data["buy_quantity"] = data["quantity"].where(data["side"].eq("b"), 0)
    data["sell_quantity"] = data["quantity"].where(data["side"].eq("s"), 0)
    grouped = data.resample(window, label="right", closed="left")
    out = grouped.agg(trade_count=("price", "count"), trade_volume=("quantity", "sum"),
                      notional_volume=("notional", "sum"), buy_volume=("buy_quantity", "sum"),
                      sell_volume=("sell_quantity", "sum"), last_price=("price", "last"))
    nonzero = out["trade_volume"].replace(0, np.nan)
    out["signed_volume"] = out["buy_volume"] - out["sell_volume"]
    out["trade_imbalance"] = out["signed_volume"] / nonzero
    out["vwap"] = out["notional_volume"] / nonzero
    out["trade_intensity"] = out["trade_count"] / pd.Timedelta(window).total_seconds()
    out["average_trade_size"] = out["trade_volume"] / out["trade_count"].replace(0, np.nan)
    out["boundary_window"] = False
    out.loc[out.index[[0, -1]], "boundary_window"] = True
    return out


def fetch_recent_trades(pair: str = "XBTEUR", count: int = 1000, symbol: str = "BTC/EUR",
                        timeout: float = 20) -> tuple[pd.DataFrame, dict]:
    """Operaciones recientes del endpoint público Trades de Kraken. Devuelve (trades, procedencia).

    Si la API falla lanza la excepción: nunca se sustituye por datos ficticios.
    `received_at` es la hora local de recepción del lote, no la de los trades.
    """
    response = requests.get(KRAKEN_TRADES_URL, params={"pair": pair, "count": count}, timeout=timeout)
    response.raise_for_status()
    received_at = pd.Timestamp.now(tz="UTC").isoformat()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    result = payload["result"]
    keys = [k for k in result if k != "last"]
    if len(keys) != 1:
        raise ValueError("Se esperaba exactamente un mercado")
    df = normalize_trades(result[keys[0]])
    return df, {"source": KRAKEN_TRADES_URL, "pair": pair, "symbol": symbol,
                "exchange_pair": keys[0], "received_at": received_at,
                "cursor": str(result["last"]), "mode": "live", "count_requested": count}


def synthetic_trades(pair: str = "XBTEUR", symbol: str = "BTC/EUR") -> tuple[pd.DataFrame, dict]:
    """240 operaciones ficticias y reproducibles (semilla 31). No pretenden modelar el mercado real."""
    rng = np.random.default_rng(31)
    n = 240
    times = SYNTHETIC_BASE_S + np.cumsum(rng.uniform(.3, 2.4, n))
    # Patrón elegido para visualizar compras y ventas, no para inferir alpha.
    sides = np.where(rng.random(n) < np.where(np.arange(n) < 120, .65, .35), "b", "s")
    sizes = np.round(rng.uniform(.01, .15, n), 4)
    prices = np.round(60000 + np.cumsum(rng.normal(0, 4, n) + np.where(sides == "b", 1, -1)), 2)
    rows = [[p, q, t, s, "m", "", i + 1] for i, (p, q, t, s) in enumerate(zip(prices, sizes, times, sides))]
    return normalize_trades(rows), {"source": "synthetic_seed_31", "pair": pair, "symbol": symbol,
                                    "received_at": None, "cursor": None, "mode": "synthetic"}


# --- Ejercicios -------------------------------------------------------------

def trade_metrics(df: pd.DataFrame) -> dict:
    """E1 · VWAP, Trade Imbalance y media aritmética del precio, sin usar `summarize_trades`."""
    quantity = df["quantity"].to_numpy(dtype=float)
    price = df["price"].to_numpy(dtype=float)
    sign = np.where(df["side"].to_numpy() == "b", 1.0, -1.0)
    volume = quantity.sum()
    return {"vwap": (price * quantity).sum() / volume if volume else np.nan,
            "trade_imbalance": (sign * quantity).sum() / volume if volume else np.nan,
            "arithmetic_mean_price": price.mean() if len(price) else np.nan}


def count_imbalance(df: pd.DataFrame) -> float:
    """E2 · Desequilibrio por número de operaciones: (n_compras − n_ventas) / n_total."""
    n = len(df)
    if not n:
        return np.nan
    buys = int(df["side"].eq("b").sum())
    return (buys - (n - buys)) / n


def compare_windows(df: pd.DataFrame, windows=("5s", "10s", "30s"), extreme: float = 0.8) -> pd.DataFrame:
    """E3 · Compara escalas temporales con ventanas completas (sin fronteras).

    `extreme_share` es la fracción de ventanas con trades y |TI| >= `extreme`.
    Las ventanas vacías cuentan en `empty_windows` y quedan indefinidas (NaN) para VWAP e imbalance.
    """
    rows = {}
    for window in windows:
        bars = aggregate_trades(df, window)
        complete = bars.loc[~bars["boundary_window"]]
        traded = complete.loc[complete["trade_count"] > 0]
        is_extreme = traded["trade_imbalance"].abs() >= extreme
        rows[window] = {
            "complete_windows": len(complete),
            "empty_windows": int((complete["trade_count"] == 0).sum()),
            "mean_trades": traded["trade_count"].mean(),
            "ti_std": traded["trade_imbalance"].std(),
            "extreme_share": is_extreme.mean() if len(traded) else np.nan,
            "extreme_windows": int(is_extreme.sum()),
            "mean_trades_extreme": traded.loc[is_extreme, "trade_count"].mean(),
            "mean_trades_rest": traded.loc[~is_extreme, "trade_count"].mean(),
        }
    return pd.DataFrame(rows).T


def top_volume_windows(bars: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """E4 · Las `n` ventanas completas de mayor volumen.

    `contemporaneous_return_bps` compara el último precio de la ventana con el de la ventana
    inmediatamente anterior, solo si esa ventana existe, es consecutiva y tuvo operaciones.
    Es un retorno contemporáneo: describe lo que pasó, no anticipa nada.
    """
    step = bars.index.to_series().diff()
    window = step.min()
    prev_close = bars["last_price"].shift(1)
    consecutive = step.eq(window) & prev_close.notna() & bars["last_price"].notna()
    ret = (bars["last_price"] / prev_close - 1) * 10_000
    table = bars.assign(contemporaneous_return_bps=ret.where(consecutive))
    table = table.loc[~table["boundary_window"]]
    cols = ["trade_count", "trade_volume", "vwap", "trade_imbalance", "contemporaneous_return_bps"]
    return table.nlargest(n, "trade_volume")[cols]
