import pytest

from quantlab.p01.execution import (
    DATO_NO_VALIDO,
    EJECUTAR,
    ESPERAR,
    NORMAL,
    PROFUNDIDAD_INSUFICIENTE,
    SIN_HISTORIAL,
    breakeven_price,
    execution_report,
    spread_regime,
)
from quantlab.p01.quotes import SYNTHETIC_QUOTE

HIST = [0.5, 0.6, 0.6, 0.7, 0.7, 0.7, 0.8, 0.9, 1.0, 1.2]  # mediana 0,7 · p90 1,02


# --- Régimen de spread --------------------------------------------------------

@pytest.mark.parametrize("current, expected", [(0.4, EJECUTAR), (0.7, EJECUTAR), (0.9, NORMAL), (1.5, ESPERAR)])
def test_spread_regime(current, expected):
    assert spread_regime(current, HIST)["regime"] == expected


def test_mismo_spread_en_euros_con_otro_mid_cuenta_como_igual():
    # Caso real: spread de 0,1 € (tick mínimo) con mids ligeramente distintos
    hist = [0.1 / 58_020 * 10_000] * 10
    assert spread_regime(0.1 / 58_034.15 * 10_000, hist)["regime"] == EJECUTAR


def test_sin_historial_suficiente():
    r = spread_regime(0.1, [0.5] * 9, min_history=10)
    assert r["regime"] == SIN_HISTORIAL and r["median_bps"] is None


# --- Precio y costes (ejemplo ficticio: bid 59.998, ask 60.002) ----------------

def test_compra_al_ask_venta_al_bid():
    assert execution_report(SYNTHETIC_QUOTE, "buy", 0.01, 0)["exec_price"] == 60_002.0
    assert execution_report(SYNTHETIC_QUOTE, "sell", 0.01, 0)["exec_price"] == 59_998.0


def test_costes_sin_comision():
    r = execution_report(SYNTHETIC_QUOTE, "buy", 0.01, fee_rate=0)
    assert r["notional"] == pytest.approx(600.02)
    assert r["fee"] == 0
    assert r["spread_cost_vs_mid"] == pytest.approx(0.02)
    assert r["round_trip_total"] == pytest.approx(0.04)
    assert r["breakeven_move"] == pytest.approx(4.0)  # sin comisión basta con recuperar el spread


def test_costes_con_comision():
    r = execution_report(SYNTHETIC_QUOTE, "buy", 0.01, fee_rate=0.008)
    assert r["fee"] == pytest.approx(600.02 * 0.008)
    assert r["round_trip_fees"] == pytest.approx(0.01 * 120_000 * 0.008)
    assert r["round_trip_fees"] > 100 * r["round_trip_spread"]  # la comisión domina


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_punto_de_equilibrio_no_gana_ni_pierde(side):
    f, qty = 0.008, 0.01
    bid, ask = SYNTHETIC_QUOTE["best_bid"], SYNTHETIC_QUOTE["best_ask"]
    be = breakeven_price(side, bid, ask, f)
    if side == "buy":
        pnl = qty * be * (1 - f) - qty * ask * (1 + f)
    else:
        pnl = qty * bid * (1 - f) - qty * be * (1 + f)
    assert pnl == pytest.approx(0, abs=1e-9)


# --- Veredictos ---------------------------------------------------------------

def test_veredicto_sin_historial():
    assert execution_report(SYNTHETIC_QUOTE, "buy", 0.01)["verdict"] == SIN_HISTORIAL


def test_veredicto_con_historial():
    # spread ficticio = 0,667 bps <= mediana 0,7 -> EJECUTAR
    assert execution_report(SYNTHETIC_QUOTE, "buy", 0.01, history_spread_bps=HIST)["verdict"] == EJECUTAR
    caro = [0.1] * 10
    assert execution_report(SYNTHETIC_QUOTE, "buy", 0.01, history_spread_bps=caro)["verdict"] == ESPERAR


def test_profundidad_insuficiente():
    r = execution_report(SYNTHETIC_QUOTE, "buy", 2.0, history_spread_bps=HIST)  # solo 1 BTC al ask
    assert r["verdict"] == PROFUNDIDAD_INSUFICIENTE and r["depth_ok"] is False


@pytest.mark.parametrize("quote", [
    {},                                                            # sin datos (red caída)
    {**SYNTHETIC_QUOTE, "best_ask": 59_000.0},                     # libro cruzado
    {**SYNTHETIC_QUOTE, "best_bid": 0.0},                          # bid = 0
])
def test_dato_no_valido(quote):
    assert execution_report(quote, "buy", 0.01)["verdict"] == DATO_NO_VALIDO


def test_determinista():
    a = execution_report(SYNTHETIC_QUOTE, "sell", 0.3, 0.004, HIST)
    b = execution_report(SYNTHETIC_QUOTE, "sell", 0.3, 0.004, HIST)
    assert a == b


@pytest.mark.parametrize("kwargs", [{"side": "hold"}, {"qty": 0}, {"fee_rate": 1.5}])
def test_parametros_invalidos(kwargs):
    params = {"quote": SYNTHETIC_QUOTE, "side": "buy", "qty": 0.01, **kwargs}
    with pytest.raises(ValueError):
        execution_report(**params)


# --- Con libro completo (P02): VWAP y slippage ------------------------------

from quantlab.p02.orderbook import EXAMPLE_BOOK, normalize_book, simulate_market_order  # noqa: E402


def _fills(qty):
    bids, asks = normalize_book(EXAMPLE_BOOK)
    return simulate_market_order(bids, asks, "buy", qty)[0], simulate_market_order(bids, asks, "sell", qty)[0]


def test_con_libro_usa_vwap_y_slippage():
    buy, sell = _fills(0.5)
    r = execution_report(SYNTHETIC_QUOTE, "buy", 0.5, 0, HIST, buy_fill=buy, sell_fill=sell)
    assert r["uses_book"] and r["exec_price"] == pytest.approx(60_005.4)
    assert r["slippage_cost"] == pytest.approx(0.5 * 3.4)
    assert r["levels_used"] == 3
    # venta de 0,5: 0,2 a 59.998 + 0,3 a 59.995 -> VWAP 59.996,2
    assert r["round_trip_market"] == pytest.approx(0.5 * (60_005.4 - 59_996.2))
    assert r["breakeven_move"] == pytest.approx(60_005.4 - 59_996.2)  # sin comisión


def test_con_libro_sin_slippage_coincide_con_p01():
    buy, sell = _fills(0.1)  # cabe en el mejor nivel de ambos lados
    a = execution_report(SYNTHETIC_QUOTE, "buy", 0.1, 0.008, HIST, buy_fill=buy, sell_fill=sell)
    b = execution_report(SYNTHETIC_QUOTE, "buy", 0.1, 0.008, HIST)
    for k in ("exec_price", "round_trip_total", "breakeven_price", "breakeven_move"):
        assert a[k] == pytest.approx(b[k])
    assert a["slippage_cost"] == pytest.approx(0, abs=1e-9)


def test_con_libro_orden_que_no_cabe():
    buy, sell = _fills(4)  # ask solo tiene 3,5 BTC
    r = execution_report(SYNTHETIC_QUOTE, "buy", 4, 0.008, HIST, buy_fill=buy, sell_fill=sell)
    assert r["verdict"] == PROFUNDIDAD_INSUFICIENTE and r["depth_ok"] is False
