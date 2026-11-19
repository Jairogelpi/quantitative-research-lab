"""Condiciones de ejecución: precio, coste y veredicto deterministas para una orden inmediata.

Solo usa conceptos de P01 (Bid, Ask, Mid, Spread, bps, validación). NO predice la
dirección del precio: responde "cómo, cuándo y a qué coste", nunca "si conviene comprar".

Concepto: docs/conceptos/condiciones_de_ejecucion.md
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from quantlab.quotes import quote_metrics, validate_quote

# Kraken Pro, nivel 1 (< 2.500 $ en 30 días), orden taker. Consultado el 19-11-2026.
# Comprueba tu nivel en https://www.kraken.com/pro/fees
DEFAULT_FEE_RATE = 0.0080
DEFAULT_MIN_HISTORY = 10
# El mismo spread en € da bps ligeramente distintos si el mid cambia (0,1 € / 58.000 vs / 58.030).
# Diferencias < 0,001 bps (≈ 0,006 € a 60.000 €, menos que el tick de 0,1 €) se tratan como iguales.
SPREAD_TOLERANCE_BPS = 0.001

EJECUTAR = "EJECUTAR"
NORMAL = "NORMAL"
ESPERAR = "ESPERAR"
SIN_HISTORIAL = "SIN_HISTORIAL"
PROFUNDIDAD_INSUFICIENTE = "PROFUNDIDAD_INSUFICIENTE"
DATO_NO_VALIDO = "DATO_NO_VALIDO"


def spread_regime(current_bps: float, history_bps: Iterable[float], min_history: int = DEFAULT_MIN_HISTORY) -> dict:
    """Compara el spread actual con su historia reciente.

    <= mediana -> EJECUTAR · <= p90 -> NORMAL · > p90 -> ESPERAR.
    Con menos de `min_history` observaciones no se juzga (SIN_HISTORIAL).
    """
    hist = np.asarray([h for h in history_bps if np.isfinite(h)], dtype=float)
    if len(hist) < min_history:
        return {"regime": SIN_HISTORIAL, "n": int(len(hist)), "median_bps": None, "p90_bps": None}
    median, p90 = (float(x) for x in np.percentile(hist, [50, 90]))
    if current_bps <= median + SPREAD_TOLERANCE_BPS:
        regime = EJECUTAR
    elif current_bps <= p90 + SPREAD_TOLERANCE_BPS:
        regime = NORMAL
    else:
        regime = ESPERAR
    return {"regime": regime, "n": int(len(hist)), "median_bps": median, "p90_bps": p90}


def breakeven_price(side: str, best_bid: float, best_ask: float, fee_rate: float) -> float:
    """Precio al que habría que cerrar la posición para no ganar ni perder (spread + comisiones).

    buy:  compro al ask pagando comisión y vendo luego al bid' pagando comisión
          -> bid' = ask · (1 + f) / (1 − f)
    sell: vendo al bid pagando comisión y recompro luego al ask'
          -> ask' = bid · (1 − f) / (1 + f)
    """
    if side == "buy":
        return best_ask * (1 + fee_rate) / (1 - fee_rate)
    if side == "sell":
        return best_bid * (1 - fee_rate) / (1 + fee_rate)
    raise ValueError(f"side debe ser 'buy' o 'sell', no {side!r}")


def execution_report(
    quote: dict,
    side: str,
    qty: float,
    fee_rate: float = DEFAULT_FEE_RATE,
    history_spread_bps: Iterable[float] = (),
    min_history: int = DEFAULT_MIN_HISTORY,
) -> dict:
    """Informe determinista para una orden inmediata de `qty` en el lado `side`.

    Mismas entradas -> misma salida. No hace llamadas de red.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side debe ser 'buy' o 'sell', no {side!r}")
    if qty <= 0:
        raise ValueError(f"Cantidad no válida: {qty}")
    if not 0 <= fee_rate < 1:
        raise ValueError(f"Comisión no válida: {fee_rate}")

    bid, ask, last = quote.get("best_bid"), quote.get("best_ask"), quote.get("last_price")
    try:
        validate_quote(bid, ask, last)
    except (ValueError, TypeError) as exc:
        return {"verdict": DATO_NO_VALIDO, "reason": str(exc), "side": side, "qty": qty}

    m = quote_metrics(bid, ask, last)
    mid = m["mid_price"]

    exec_price = ask if side == "buy" else bid          # comprar cruza el Ask, vender cruza el Bid
    notional = qty * exec_price
    fee = notional * fee_rate
    spread_cost_vs_mid = qty * m["spread"] / 2           # medio spread por pata
    round_trip_spread = qty * m["spread"]
    round_trip_fees = qty * (ask + bid) * fee_rate       # aproximación: ambas patas a precios actuales
    be_price = breakeven_price(side, bid, ask, fee_rate)
    be_move = be_price - bid if side == "buy" else ask - be_price  # cuánto debe moverse a favor

    available = quote.get("best_ask_volume" if side == "buy" else "best_bid_volume")
    depth_ok = None if available is None else qty <= available

    regime = spread_regime(m["spread_bps"], history_spread_bps, min_history)
    if depth_ok is False:
        verdict, reason = PROFUNDIDAD_INSUFICIENTE, (
            f"{qty} BTC > {available} disponibles al mejor precio: habrá slippage (lección 1.3)")
    elif regime["regime"] == SIN_HISTORIAL:
        verdict, reason = SIN_HISTORIAL, (
            f"Solo {regime['n']} observaciones (mínimo {min_history}); coste calculado, sin juicio de spread")
    elif regime["regime"] == EJECUTAR:
        verdict, reason = EJECUTAR, "Spread por debajo o igual a la mediana reciente"
    elif regime["regime"] == NORMAL:
        verdict, reason = NORMAL, "Spread entre la mediana y el percentil 90 reciente"
    else:
        verdict, reason = ESPERAR, "Spread por encima del percentil 90 reciente: anormalmente caro"

    return {
        "verdict": verdict,
        "reason": reason,
        "side": side,
        "qty": qty,
        "fee_rate": fee_rate,
        **m,
        "exec_price": exec_price,
        "notional": notional,
        "fee": fee,
        "spread_cost_vs_mid": spread_cost_vs_mid,
        "round_trip_spread": round_trip_spread,
        "round_trip_fees": round_trip_fees,
        "round_trip_total": round_trip_spread + round_trip_fees,
        "breakeven_price": be_price,
        "breakeven_move": be_move,
        "breakeven_move_pct": be_move / mid * 100,
        "available_at_best": available,
        "depth_ok": depth_ok,
        "spread_median_bps": regime["median_bps"],
        "spread_p90_bps": regime["p90_bps"],
        "history_n": regime["n"],
    }
