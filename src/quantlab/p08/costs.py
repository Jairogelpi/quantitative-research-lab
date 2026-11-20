"""Costes de ejecución spot: comisión, spread, profundidad (slippage), retraso, ida y vuelta,
umbral de equilibrio, markout maker y erosión por rotación.

Origen: P08 · Motor de costes operativos y ejecución. Concepto: docs/conceptos/costes_de_ejecucion.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.p02.orderbook import fetch_kraken_book as _fetch_kraken_depth

COST_COMPONENTS = ["spread_cost", "slippage_cost", "fee"]


# --- Comisión y libro ----------------------------------------------------------

def fee_eur(quantity: float, price: float, fee_bps: float) -> float:
    """Comisión en EUR: q · p · bps / 10.000. Lanza ValueError con cantidad < 0, precio <= 0 o valores no finitos."""
    if not np.isfinite([quantity, price, fee_bps]).all() or quantity < 0 or price <= 0:
        raise ValueError("Cantidad, precio o tarifa inválidos")
    return quantity * price * fee_bps / 10_000


def validate_book(book: pd.DataFrame) -> pd.DataFrame:
    """Libro L2 en formato largo (side, price, quantity). Agrega niveles repetidos.

    Lanza ValueError con lados desconocidos, niveles <= 0 o no finitos, o un libro incompleto,
    bloqueado o cruzado.
    """
    b = book[["side", "price", "quantity"]].copy()
    if not b.side.isin(["bid", "ask"]).all():
        raise ValueError("Lado desconocido")
    b[["price", "quantity"]] = b[["price", "quantity"]].apply(pd.to_numeric)
    if not np.isfinite(b[["price", "quantity"]]).all().all() or (b[["price", "quantity"]] <= 0).any().any():
        raise ValueError("Niveles no positivos o no finitos")
    b = b.groupby(["side", "price"], as_index=False).quantity.sum()
    if set(b.side) != {"bid", "ask"} or b.loc[b.side == "bid", "price"].max() >= b.loc[b.side == "ask", "price"].min():
        raise ValueError("Libro incompleto, bloqueado o cruzado")
    return b


def synthetic_book(mid: float = 60000) -> pd.DataFrame:
    """Seis niveles por lado a 3, 6, 12, 24, 48 y 96 EUR del mid (2 BTC por lado en total)."""
    offsets = [3, 6, 12, 24, 48, 96]
    return validate_book(pd.DataFrame(
        [(side, mid + sign * d, q) for side, sign, qs in
         [("ask", 1, [.03, .07, .15, .25, .5, 1]), ("bid", -1, [.04, .06, .12, .28, .5, 1])]
         for d, q in zip(offsets, qs)], columns=["side", "price", "quantity"]))


def fetch_kraken_book(pair: str = "XBTEUR", levels: int = 50) -> tuple[pd.DataFrame, dict]:
    """Snapshot público del libro de Kraken en formato largo (reutiliza la descarga de P02)."""
    started = pd.Timestamp.now(tz="UTC")
    raw, received_at = _fetch_kraken_depth(pair, levels)
    rows = [(side, r[0], r[1]) for side, key in [("bid", "bids"), ("ask", "asks")] for r in raw[key]]
    book = validate_book(pd.DataFrame(rows, columns=["side", "price", "quantity"]))
    return book, {"source": "https://api.kraken.com/0/public/Depth", "pair": pair, "symbol": "BTC/EUR",
                  "request_at": started.isoformat(), "received_at": received_at}


# --- Motor de ejecución -----------------------------------------------------------

def walk_book(book: pd.DataFrame, side: str, quantity: float, fee_bps: float = 10., decision_mid: float | None = None) -> dict:
    """Ejecuta una orden a mercado recorriendo el libro y desglosa su coste.

    C_spread = s·q·(best − mid); C_depth = s·q·(p_exec − best); C_delay = s·q·(mid − mid_decisión).
    Con ejecución parcial, los costes se miden sobre lo ejecutado (sin coste de oportunidad del resto).
    """
    if side not in ["buy", "sell"] or not np.isfinite(quantity) or quantity <= 0 or not np.isfinite(fee_bps):
        raise ValueError("Orden inválida")
    b = validate_book(book)
    bid = b.loc[b.side == "bid", "price"].max()
    ask = b.loc[b.side == "ask", "price"].min()
    mid = (bid + ask) / 2
    sign = 1 if side == "buy" else -1
    levels = b[b.side == ("ask" if sign == 1 else "bid")].sort_values("price", ascending=sign == 1)
    best = levels.price.iloc[0]
    remaining, nominal, filled, used = quantity, 0., 0., 0
    for row in levels.itertuples():
        take = min(remaining, row.quantity)
        nominal += take * row.price
        filled += take
        remaining -= take
        used += 1
        if remaining <= 1e-12:
            break
    px = nominal / filled
    fee = fee_eur(filled, px, fee_bps)
    spread = sign * filled * (best - mid)
    depth = sign * filled * (px - best)
    if decision_mid is None:
        decision_mid = mid
    if not np.isfinite(decision_mid) or decision_mid <= 0:
        raise ValueError("Mid de decisión inválido")
    delay = sign * filled * (mid - decision_mid)
    return dict(side=side, requested_qty=quantity, filled_qty=filled, fill_ratio=min(1., filled / quantity),
                levels_used=used, execution_price=px, mid=mid, best_price=best, notional=nominal, fee=fee,
                spread_cost=spread, slippage_cost=depth, delay_cost=delay,
                execution_cost=spread + depth + fee, implementation_shortfall=spread + depth + delay + fee,
                execution_cost_bps=(spread + depth + fee) / (filled * mid) * 1e4)


def size_table(book: pd.DataFrame, sizes=(.01, .1, .5, 1., 3.), fee_bps: float = 10.) -> pd.DataFrame:
    """Compras y ventas de varios tamaños sobre el mismo libro."""
    return pd.DataFrame([walk_book(book, s, q, fee_bps) for q in sizes for s in ["buy", "sell"]])


# --- Ida y vuelta y umbral -------------------------------------------------------------

def round_trip(entry_book: pd.DataFrame, exit_book: pd.DataFrame, quantity: float,
               fee_buy_bps: float, fee_sell_bps: float) -> dict:
    """Compra en `entry_book` y venta de la misma cantidad en `exit_book`.

    net = nominal de venta − nominal de compra − comisiones; gross = q·(mid_salida − mid_entrada).
    Se cumple gross − (spread + profundidad + comisiones) = net: ningún coste se cuenta dos veces.
    Lanza ValueError si alguna pierna no se ejecuta entera.
    """
    buy = walk_book(entry_book, "buy", quantity, fee_buy_bps)
    sell = walk_book(exit_book, "sell", quantity, fee_sell_bps)
    if not (np.isclose(buy["fill_ratio"], 1, atol=1e-10, rtol=0) and np.isclose(sell["fill_ratio"], 1, atol=1e-10, rtol=0)):
        raise ValueError("Round trip incompleto: no se presume cerrada la posición")
    gross = quantity * (sell["mid"] - buy["mid"])
    costs = buy["execution_cost"] + sell["execution_cost"]
    net = sell["notional"] - buy["notional"] - buy["fee"] - sell["fee"]
    return {"gross_pnl": gross, "spread_cost": buy["spread_cost"] + sell["spread_cost"],
            "slippage_cost": buy["slippage_cost"] + sell["slippage_cost"], "fees": buy["fee"] + sell["fee"],
            "net_pnl": net, "net_return_bps": net / (buy["notional"] + buy["fee"]) * 1e4,
            "entry_price": buy["execution_price"], "exit_price": sell["execution_price"], "total_cost": costs}


def break_even(book_factory, quantity: float, fee_buy_bps: float, fee_sell_bps: float, mid: float = 60000) -> dict:
    """Umbral exacto: p_s* = p_b·(1 + f_b)/(1 − f_s) en precio ejecutado, y el movimiento de mid equivalente.

    Supone que el libro de salida es el mismo libro desplazado (`book_factory(mid_salida)`), de modo que
    la distancia entre el mid y el precio de venta ejecutado no cambia.
    """
    fb, fs = fee_buy_bps / 1e4, fee_sell_bps / 1e4
    entry = walk_book(book_factory(mid), "buy", quantity, fee_buy_bps)["execution_price"]
    exit_offset = mid - walk_book(book_factory(mid), "sell", quantity, fee_sell_bps)["execution_price"]
    exec_price = entry * (1 + fb) / (1 - fs)
    mid_price = exec_price + exit_offset
    return {"entry_price": entry, "break_even_exec_price": exec_price, "break_even_mid": mid_price,
            "break_even_move_bps": (mid_price / mid - 1) * 1e4}


def fee_move_grid(book_factory, quantity: float, fees=(0, 5, 10, 25, 40), moves=range(-20, 101, 5),
                  mid: float = 60000) -> pd.DataFrame:
    """PnL de ida y vuelta para cada combinación de comisión taker (por lado) y movimiento del mid."""
    base = book_factory(mid)
    rows = []
    for fee in fees:
        for move in moves:
            r = round_trip(base, book_factory(mid * (1 + move / 10000)), quantity, fee, fee)
            rows.append({"fee_bps": fee, "move_bps": move, **r})
    return pd.DataFrame(rows)


# --- Maker, markout y rotación ------------------------------------------------------------

def markout(side: str, quantity: float, fill_price: float, future_mid: float, fee_bps: float) -> float:
    """Markout neto de comisión: s·q·(mid_{t+h} − p_fill) − comisión. No es el PnL de una posición cerrada."""
    sign = {"buy": 1, "sell": -1}[side]
    return sign * quantity * (future_mid - fill_price) - fee_eur(quantity, fill_price, fee_bps)


def turnover_table(round_trips=(10, 20, 40, 80, 120), capital: float = 10000., nominal: float = 1000.,
                   gross_total: float = 100., cost_bps: float = 25.) -> pd.DataFrame:
    """Mismo beneficio bruto total repartido en más o menos operaciones de nominal fijo."""
    t = pd.DataFrame({"round_trips": list(round_trips)})
    t["turnover_two_sided"] = 2 * nominal * t.round_trips / capital
    t["cost_eur"] = nominal * t.round_trips * cost_bps / 1e4
    t["net_pnl"] = gross_total - t.cost_eur
    t["net_return_pct"] = 100 * t.net_pnl / capital
    return t


# --- Ejercicios -------------------------------------------------------------------------------

def manual_fee(notional_eur: float, fee_bps: float) -> float:
    """E1 · Comisión a partir del nominal: nominal · bps / 10.000."""
    if not np.isfinite([notional_eur, fee_bps]).all() or notional_eur < 0 or fee_bps < 0:
        raise ValueError("Nominal o tarifa inválidos")
    return notional_eur * fee_bps / 10_000


def break_even_comparison(book_factory, quantity: float, fees=(5, 10, 25), mid: float = 60000) -> pd.DataFrame:
    """E4 · Umbral exacto frente a la aproximación de sumar costes en bps (2 comisiones + spread + profundidad)."""
    base = book_factory(mid)
    buy = walk_book(base, "buy", quantity, 0)
    sell = walk_book(base, "sell", quantity, 0)
    execution_bps = (buy["spread_cost"] + buy["slippage_cost"] + sell["spread_cost"] + sell["slippage_cost"]) / (quantity * mid) * 1e4
    rows = []
    for fee in fees:
        exact = break_even(book_factory, quantity, fee, fee, mid)["break_even_move_bps"]
        approx = 2 * fee + execution_bps
        rows.append({"fee_bps_per_side": fee, "exact_move_bps": exact, "approx_move_bps": approx,
                     "difference_bps": exact - approx})
    return pd.DataFrame(rows).set_index("fee_bps_per_side")


def maker_vs_taker(book: pd.DataFrame, quantity: float, maker_price: float, future_mids=(59970, 60000, 60030),
                   maker_fee_bps: float = 5., taker_fee_bps: float = 10.) -> pd.DataFrame:
    """E5 · Markout de una compra maker hipotética (rellenada) frente a una compra taker."""
    taker = walk_book(book, "buy", quantity, taker_fee_bps)
    rows = []
    for m in future_mids:
        rows.append({"future_mid": m,
                     "maker_markout_eur": markout("buy", quantity, maker_price, m, maker_fee_bps),
                     "taker_markout_eur": markout("buy", quantity, taker["execution_price"], m, taker_fee_bps)})
    out = pd.DataFrame(rows).set_index("future_mid")
    out["maker_advantage_eur"] = out.maker_markout_eur - out.taker_markout_eur
    out.attrs = {"taker_price": taker["execution_price"], "maker_price": maker_price}
    return out


def max_round_trips(gross_total: float = 100., nominal: float = 1000., cost_levels=(10, 25, 50)) -> pd.DataFrame:
    """E6 · Operaciones que soporta un beneficio bruto fijo antes de perder dinero: bruto / coste por operación."""
    rows = []
    for cost in cost_levels:
        per_trade = nominal * cost / 1e4
        rows.append({"cost_bps": cost, "cost_per_round_trip_eur": per_trade,
                     "break_even_round_trips": gross_total / per_trade,
                     "max_profitable_round_trips": int(np.ceil(gross_total / per_trade) - 1)})
    return pd.DataFrame(rows).set_index("cost_bps")


def cost_attribution(executions: pd.DataFrame, max_quote_age=pd.Timedelta(seconds=2)) -> pd.DataFrame:
    """E8 · Interfaz de costes para P05/P06: una fila por fill.

    Columnas requeridas: fill_id, side, quantity, decision_mid, decision_at, quote_mid, quote_at,
    best_price, fill_price, fill_at, fee_eur. Cada coste se calcula una sola vez sobre su tramo:
    retraso (decisión → cotización), spread (cotización → mejor precio), profundidad (mejor precio → fill).
    Marca cotizaciones obsoletas (más antiguas que `max_quote_age` al decidir), cotizaciones
    posteriores a la decisión (*look-ahead*), fills anteriores a la decisión y fill_id duplicados.
    """
    required = {"fill_id", "side", "quantity", "decision_mid", "decision_at", "quote_mid", "quote_at",
                "best_price", "fill_price", "fill_at", "fee_eur"}
    missing = required - set(executions)
    if missing:
        raise ValueError(f"Faltan columnas: {missing}")
    e = executions.copy()
    for col in ["decision_at", "quote_at", "fill_at"]:
        e[col] = pd.to_datetime(e[col], utc=True)
    if not e.side.isin(["buy", "sell"]).all() or (e.quantity <= 0).any():
        raise ValueError("Lado o cantidad inválidos")
    s = np.where(e.side.eq("buy"), 1, -1)
    e["delay_cost"] = s * e.quantity * (e.quote_mid - e.decision_mid)
    e["spread_cost"] = s * e.quantity * (e.best_price - e.quote_mid)
    e["slippage_cost"] = s * e.quantity * (e.fill_price - e.best_price)
    e["implementation_shortfall"] = e.delay_cost + e.spread_cost + e.slippage_cost + e.fee_eur
    # Identidad: el shortfall debe ser exactamente s·q·(fill − decisión) + comisión. Si no, algo se duplicó.
    e["reconciles"] = np.isclose(e.implementation_shortfall, s * e.quantity * (e.fill_price - e.decision_mid) + e.fee_eur)
    e["quote_age"] = e.decision_at - e.quote_at
    e["stale_quote"] = e.quote_age > max_quote_age
    e["future_quote"] = e.quote_at > e.decision_at
    e["fill_before_decision"] = e.fill_at < e.decision_at
    e["duplicated_fill"] = e.fill_id.duplicated(keep=False)
    return e
