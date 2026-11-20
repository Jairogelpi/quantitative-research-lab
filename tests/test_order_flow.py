"""P13 · Order flow: reconstrucción L2, OFI, cotizaciones, regresiones, impacto, exposición y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p13.order_flow import (
    add_future,
    exposure,
    features,
    impact_by_quartile,
    impact_experiment,
    manual_ofi,
    manual_ofi_series,
    ofi_regressions,
    prepare_quotes,
    replay,
    sign_rule,
    simulate_quotes,
    window_ofi,
)

SNAPSHOT = {"bid": {99: 2., 98: 3.}, "ask": {101: 2., 102: 4.}}
UPDATES = [(1, "bid", 99, 3., "alta bid"), (2, "ask", 101, 1., "ejecución compra"),
           (3, "bid", 99, 1., "cancelación bid"), (4, "ask", 101, 0., "ejecución compra"),
           (5, "bid", 100, 1.5, "mejora bid"), (6, "ask", 101, 2., "mejora ask")]


@pytest.fixture(scope="module")
def quotes():
    x = prepare_quotes(simulate_quotes())
    cut = int(len(x) * .65)
    return add_future(add_future(x, 1, cut), 5, cut), cut


# --- Libro y OFI ----------------------------------------------------------------------

def test_reconstruccion_y_ofi_del_ejemplo():
    ex = features(replay(SNAPSHOT, UPDATES))
    assert np.isnan(ex.ofi_event.iloc[0])
    assert np.allclose(ex.ofi_event.iloc[1:], [1, 1, -2, 1, 1.5, -2])
    assert list(ex.bid_depth) == [5, 6, 6, 4, 4, 5.5, 5.5]


@pytest.mark.parametrize("updates, message", [
    ([UPDATES[1]], "Secuencia perdida"),
    ([(1, "mid", 100, 1., "x")], "inválida"),
    ([(1, "bid", 99, -1., "x")], "inválida"),
    ([(1, "bid", 101.5, 1., "x")], "cruzado"),
])
def test_replay_rechaza_mensajes_invalidos(updates, message):
    with pytest.raises(ValueError, match=message):
        replay(SNAPSHOT, updates)


def test_obi_y_mid():
    ex = features(replay(SNAPSHOT, UPDATES))
    assert np.isclose(ex.obi.iloc[1], (3 - 2) / 5) and ex.obi.between(-1, 1).all()
    assert np.isclose(ex.mid_change_bps.iloc[4], 50)


# --- Cotizaciones ------------------------------------------------------------------------

def test_segmentos_cortan_en_huecos():
    raw = simulate_quotes(100)
    raw.loc[50:, "received_at"] += pd.Timedelta(seconds=10)
    x = prepare_quotes(raw)
    assert x.segment.nunique() == 2
    assert x.loc[x.segment.ne(x.segment.shift()), ["ofi_event", "mid_change_bps"]].isna().all().all()


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.drop(columns="ask_size"), "Faltan"),
    (lambda r: r.iloc[:30], "al menos"),
    (lambda r: r.assign(ask=r.bid - 1), "inválidos"),
    (lambda r: pd.concat([r, r.iloc[[0]]]), "al menos"),
])
def test_prepare_rechaza_datos_invalidos(mutate, message):
    with pytest.raises(ValueError, match=message):
        prepare_quotes(mutate(simulate_quotes(100)))


def test_filtra_un_solo_mercado():
    raw = pd.concat([simulate_quotes(100), simulate_quotes(100, exchange="okx")])
    assert len(prepare_quotes(raw, "kraken")) == 100


# --- Regresiones y regla --------------------------------------------------------------------

def test_futuro_no_cruza_el_corte(quotes):
    x, cut = quotes
    assert np.isnan(x.loc[cut - 1, "future_bps"])
    assert x.loc[cut - 5:cut - 1, "future_5_bps"].isna().all()
    assert np.isclose(x.loc[10, "future_bps"], 10000 * (x.loc[11, "mid"] / x.loc[10, "mid"] - 1))


def test_relacion_contemporanea_mecanica_y_futura_debil(quotes):
    x, cut = quotes
    r = ofi_regressions(x, cut, {"contemporáneo": "mid_change_bps", "futuro": "future_bps",
                                 "futuro 5": "future_5_bps"}).set_index(["target", "period"])
    assert r.loc[("contemporáneo", "validación"), "r2"] > .5
    assert r.loc[("futuro", "validación"), "r2"] < .05
    assert r.loc[("futuro 5", "validación"), "p_value"] > .05


def test_regla_no_cubre_costes(quotes):
    x, cut = quotes
    out = sign_rule(x, cut, .0467, "future_bps", 20)
    assert out["trades"] > 0 and np.isclose(out["gross_bps"] - out["net_bps"], 20)
    assert out["net_bps"] < 0
    assert sign_rule(x, cut, 0.)["trades"] == 0


# --- Impacto y exposición ---------------------------------------------------------------------

def test_impacto_decae():
    events, h = impact_experiment()
    means = events[[f"response_{x}s_bps" for x in h]].mean()
    assert means.is_monotonic_decreasing and means.iloc[-1] > 0


def test_exposicion_cobertura():
    positions = pd.DataFrame({"instrument": ["BTC spot", "BTC perpetual"], "quantity": [.1, -.1],
                              "entry_price": [60000, 60000], "current_price": [63000, 63100]})
    ledger, e = exposure(positions, 7000)
    assert np.isclose(ledger.unrealized_pnl.sum(), -10)
    assert np.isclose(e["gross_exposure"], 12610) and np.isclose(e["net_exposure"], -10)
    with pytest.raises(ValueError):
        exposure(positions, 0)


# --- Ejercicios E1–E6 ----------------------------------------------------------------------------

def test_e1_nivel_no_optimo_no_mueve_el_ofi():
    extra = UPDATES + [(7, "bid", 98, 0., "elimina nivel no óptimo"), (8, "ask", 100.5, 1., "mejora ask")]
    ex = features(replay(SNAPSHOT, extra))
    assert ex.ofi_event.iloc[7] == 0 and ex.bid_depth.iloc[7] == ex.bid_depth.iloc[6] - 3
    assert ex.ofi_event.iloc[8] == -1


def test_e2_ofi_manual():
    ex = features(replay(SNAPSHOT, UPDATES))
    assert np.allclose(manual_ofi_series(ex), ex.ofi_event, equal_nan=True)
    assert manual_ofi({"bid": 99, "ask": 101, "bid_size": 2, "ask_size": 2},
                      {"bid": 99, "ask": 101, "bid_size": 3, "ask_size": 2}) == 1


def test_e2_coincide_en_la_simulacion(quotes):
    x, _ = quotes
    sample = x.iloc[:200]
    assert np.allclose(manual_ofi_series(sample).iloc[1:], features(sample).ofi_event.iloc[1:])


def test_e3_ventanas_completas(quotes):
    x, _ = quotes
    w5 = window_ofi(x, "5s")
    assert (w5.n == 5).all() and len(w5) > 400
    assert w5.ofi.corr(w5.mid_change_bps) > .7


def test_e5_impacto_por_cuartil():
    events, _ = impact_experiment()
    t = impact_by_quartile(events, (0, 5, 30))
    assert t["response_0s_bps"].is_monotonic_increasing
    assert (t.reverted_share > .5).all()


def test_e6_exposicion():
    positions = pd.DataFrame({"instrument": ["BTC", "ETH", "SOL", "XRP"], "quantity": [3000, 2000, -1500, -500],
                              "entry_price": 1., "current_price": 1.})
    _, e = exposure(positions, 5000)
    assert (e["net_exposure"], e["gross_exposure"], e["gross_leverage"]) == (3000, 7000, 1.4)
