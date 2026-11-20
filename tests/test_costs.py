"""P08 · Costes de ejecución: comisión, libro, motor de ejecución, ida y vuelta, umbral, maker, rotación y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p02.orderbook import simulate_market_order
from quantlab.p08.costs import (
    break_even,
    break_even_comparison,
    cost_attribution,
    fee_eur,
    fee_move_grid,
    fetch_kraken_book,
    manual_fee,
    maker_vs_taker,
    markout,
    max_round_trips,
    round_trip,
    size_table,
    synthetic_book,
    turnover_table,
    validate_book,
    walk_book,
)


@pytest.fixture(scope="module")
def book():
    return synthetic_book()


# --- Comisión y libro ------------------------------------------------------------------

def test_comision():
    assert np.isclose(fee_eur(.1, 60000, 10), 6) and np.isclose(fee_eur(.1, 60000, 5), 3)
    assert fee_eur(0, 60000, 10) == 0
    for args in [(-1, 60000, 10), (.1, 0, 10), (.1, 60000, np.nan)]:
        with pytest.raises(ValueError, match="inválidos"):
            fee_eur(*args)


def test_libro_agrega_niveles_repetidos():
    b = validate_book(pd.DataFrame({"side": ["bid", "bid", "ask"], "price": [99, 99, 101], "quantity": [1, 2, 1]}))
    assert b.loc[b.side == "bid", "quantity"].iloc[0] == 3


@pytest.mark.parametrize("rows, message", [
    ([("buy", 99, 1), ("ask", 101, 1)], "Lado desconocido"),
    ([("bid", 99, 0), ("ask", 101, 1)], "no positivos"),
    ([("bid", 99, 1)], "incompleto"),
    ([("bid", 101, 1), ("ask", 101, 1)], "bloqueado"),
    ([("bid", 102, 1), ("ask", 101, 1)], "cruzado"),
])
def test_libro_rechaza_datos_invalidos(rows, message):
    with pytest.raises(ValueError, match=message):
        validate_book(pd.DataFrame(rows, columns=["side", "price", "quantity"]))


# --- Motor de ejecución: las comprobaciones del cuaderno ----------------------------------

def test_compra_de_0_1_btc(book):
    r = walk_book(book, "buy", .1, 10)
    assert np.isclose(r["execution_price"], 60005.1) and r["levels_used"] == 2
    assert np.isclose(r["spread_cost"], .3) and np.isclose(r["slippage_cost"], .21)
    assert np.isclose(r["execution_cost"], r["implementation_shortfall"])
    assert np.isclose(r["execution_cost"], r["spread_cost"] + r["slippage_cost"] + r["fee"])


def test_coste_de_retraso_y_fill_parcial(book):
    assert np.isclose(walk_book(book, "buy", .1, 10, 59990)["delay_cost"], 1)
    partial = walk_book(book, "buy", 4)
    assert np.isclose(partial["filled_qty"], 2) and np.isclose(partial["fill_ratio"], .5)
    with pytest.raises(ValueError, match="Orden inválida"):
        walk_book(book, "hold", 1)
    with pytest.raises(ValueError, match="Mid de decisión"):
        walk_book(book, "buy", .1, 10, -1)


def test_coincide_con_el_motor_de_p02(book):
    bids = (book[book.side == "bid"].rename(columns={"quantity": "quantity_btc"})
            .sort_values("price", ascending=False).reset_index(drop=True))
    asks = book[book.side == "ask"].rename(columns={"quantity": "quantity_btc"}).sort_values("price").reset_index(drop=True)
    for side in ("buy", "sell"):
        for q in (.01, .1, 1., 3.):
            p02, _ = simulate_market_order(bids, asks, side, q)
            assert np.isclose(walk_book(book, side, q)["execution_price"], p02["execution_price"])


def test_tabla_de_tamanos(book):
    t = size_table(book)
    assert len(t) == 10
    buys = t[t.side == "buy"]
    assert buys.execution_cost_bps.is_monotonic_increasing
    assert list(buys.fill_ratio.round(4)) == [1, 1, 1, 1, .6667]


# --- Ida y vuelta y umbral -------------------------------------------------------------------

def test_ida_y_vuelta_concilia(book):
    trade = round_trip(book, synthetic_book(60000 * 1.0035), .1, 10, 10)
    assert np.isclose(trade["gross_pnl"], 21) and np.isclose(trade["net_pnl"], 7.98897)
    assert np.isclose(trade["gross_pnl"] - trade["total_cost"], trade["net_pnl"])
    assert np.isclose(trade["total_cost"], trade["spread_cost"] + trade["slippage_cost"] + trade["fees"])


def test_umbral_exacto_da_pnl_cero(book):
    be = break_even(synthetic_book, .1, 10, 10)
    assert np.isclose(be["break_even_move_bps"], 21.67172, atol=1e-4)
    assert np.isclose(round_trip(book, synthetic_book(be["break_even_mid"]), .1, 10, 10)["net_pnl"], 0)


def test_rechaza_ida_y_vuelta_incompleta(book):
    with pytest.raises(ValueError, match="incompleto"):
        round_trip(book, synthetic_book(60210), 4, 10, 10)


def test_mas_comision_menos_pnl():
    grid = fee_move_grid(synthetic_book, .1, (0, 5, 10, 25, 40), (0, 35))
    for _, g in grid.groupby("move_bps"):
        assert g.sort_values("fee_bps").net_pnl.is_monotonic_decreasing


# --- Maker y rotación ---------------------------------------------------------------------------

def test_markout_maker():
    values = [markout("buy", .1, 59997, m, 5) for m in (59970, 59997, 60000, 60030)]
    assert np.allclose(values, [-5.6999, -2.9999, -2.6999, .3001], atol=1e-4)
    assert np.isclose(markout("sell", .1, 60003, 59970, 5), .1 * 33 - fee_eur(.1, 60003, 5))


def test_rotacion():
    t = turnover_table()
    assert list(t.net_pnl) == [75, 50, 0, -100, -200]
    assert list(t.turnover_two_sided) == [2, 4, 8, 16, 24]


# --- Ejercicios E1–E8 -----------------------------------------------------------------------------

def test_e1_comision_manual():
    assert np.isclose(manual_fee(2000, 30), 6)
    assert np.isclose(manual_fee(.1 * 60000, 10), fee_eur(.1, 60000, 10))
    with pytest.raises(ValueError):
        manual_fee(-1, 10)


def test_e2_compra_a_mano(book):
    r = walk_book(book, "buy", .1, 10)
    by_hand = (.03 * 60003 + .07 * 60006) / .1
    assert np.isclose(r["execution_price"], by_hand)
    assert np.isclose(r["fee"], .1 * by_hand * .001)
    assert np.isclose(r["slippage_cost"], .07 * (60006 - 60003))


def test_e3_cuando_se_agota_el_mejor_nivel_y_la_profundidad(book):
    t = size_table(book, (.01, .03, .04, .1, 2., 3.))
    buys = t[t.side == "buy"].set_index("requested_qty")
    assert buys.loc[.03, "levels_used"] == 1 and buys.loc[.1, "levels_used"] == 2
    assert np.isclose(buys.loc[2., "fill_ratio"], 1) and buys.loc[3., "fill_ratio"] < 1


def test_e4_umbral_exacto_frente_a_aproximado():
    t = break_even_comparison(synthetic_book, .1, (5, 10, 25))
    assert (t.exact_move_bps > t.approx_move_bps).all()
    assert t.difference_bps.is_monotonic_increasing
    assert np.isclose(t.loc[10, "approx_move_bps"], 21.65)


def test_e5_maker_frente_a_taker(book):
    t = maker_vs_taker(book, .1, 59997)
    assert np.allclose(t.maker_advantage_eur, t.maker_advantage_eur.iloc[0])  # ventaja constante si hay fill
    assert np.isclose(t.attrs["taker_price"], 60005.1)


def test_e6_operaciones_maximas():
    t = max_round_trips(100, 1000, (10, 25, 50))
    assert list(t.break_even_round_trips) == [100, 40, 20]
    assert list(t.max_profitable_round_trips) == [99, 39, 19]


def test_e8_atribucion_de_costes_detecta_problemas():
    t0 = pd.Timestamp("2026-01-01T10:00:00Z")
    rows = pd.DataFrame([
        dict(fill_id="a", side="buy", quantity=.1, decision_mid=60000, decision_at=t0, quote_mid=60002,
             quote_at=t0 - pd.Timedelta("0.5s"), best_price=60005, fill_price=60008, fill_at=t0 + pd.Timedelta("1s"), fee_eur=6),
        dict(fill_id="b", side="sell", quantity=.1, decision_mid=60000, decision_at=t0, quote_mid=59990,
             quote_at=t0 - pd.Timedelta("5s"), best_price=59987, fill_price=59985, fill_at=t0 + pd.Timedelta("1s"), fee_eur=6),
        dict(fill_id="b", side="sell", quantity=.1, decision_mid=60000, decision_at=t0, quote_mid=59990,
             quote_at=t0, best_price=59987, fill_price=59985, fill_at=t0 - pd.Timedelta("1s"), fee_eur=6),
        dict(fill_id="c", side="buy", quantity=.1, decision_mid=60000, decision_at=t0, quote_mid=60002,
             quote_at=t0 + pd.Timedelta("0.2s"), best_price=60005, fill_price=60005, fill_at=t0 + pd.Timedelta("1s"), fee_eur=6),
    ])
    out = cost_attribution(rows)
    a = out.iloc[0]
    assert np.isclose(a.delay_cost, .2) and np.isclose(a.spread_cost, .3) and np.isclose(a.slippage_cost, .3)
    assert np.isclose(a.implementation_shortfall, .1 * (60008 - 60000) + 6)
    assert out.reconciles.all()
    assert list(out.stale_quote) == [False, True, False, False]
    assert list(out.future_quote) == [False, False, False, True]
    assert list(out.fill_before_decision) == [False, False, True, False]
    assert list(out.duplicated_fill) == [False, True, True, False]
    with pytest.raises(ValueError, match="Faltan columnas"):
        cost_attribution(rows.drop(columns="fee_eur"))


@pytest.mark.live
def test_libro_kraken_en_vivo():
    book, provenance = fetch_kraken_book(levels=10)
    assert len(book) == 20 and provenance["received_at"]
    assert walk_book(book, "buy", .001)["fill_ratio"] == 1
