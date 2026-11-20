"""P11 · Eficiencia del mercado: controles, autocorrelación, Ljung–Box, pruebas múltiples, costes y ejercicios."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from quantlab.p11.efficiency import (
    bonferroni_manual,
    diagnostics,
    false_positive_table,
    ljung_box_power,
    ljung_box_table,
    load_p04,
    longest_valid_run,
    make_market,
    make_markets,
    manual_autocorrelation,
    max_ic_by_count,
    monte_carlo_false_positives,
    null_signal_experiment,
    pearson_many,
    random_walk_acf,
    regime_detection_delay,
    rolling_autocorr,
    split_returns,
    trade_experiment,
)


@pytest.fixture(scope="module")
def markets():
    return make_markets()


@pytest.fixture(scope="module")
def null_returns(markets):
    r = split_returns(markets["Aleatorio"])
    return r["Desarrollo"].dropna().to_numpy(), r["Validación"].dropna().to_numpy()


# --- Mercados y datos -------------------------------------------------------------------

def test_mercados_comparten_ruido(markets):
    assert all(len(p) == 2400 for p in markets.values())
    cut = int(2400 * .65)
    r = {k: np.log(v).diff() for k, v in markets.items()}
    # Tras el corte, Decaimiento tiene φ = 0: sus retornos coinciden con los del control aleatorio.
    assert np.allclose(r["Decaimiento"].iloc[cut + 1:], r["Aleatorio"].iloc[cut + 1:])


def test_carga_csv_de_p04(tmp_path):
    path = tmp_path / "p04_series.csv"
    pd.DataFrame({"bar_end_utc": ["2026-01-01T00:01:00Z", "2026-01-01T00:03:00Z"],
                  "analysis_close": [100.0, 101.0]}).to_csv(path, index=False)
    close = load_p04(path)
    assert len(close) == 3 and pd.isna(close.iloc[1])  # el hueco queda como NaN, sin rellenar


# --- Autocorrelación y Ljung–Box ------------------------------------------------------------

def test_tramo_valido_mas_largo_y_corte():
    assert len(longest_valid_run(pd.Series([1., 2., np.nan, 3., 4., 5.]))) == 3
    parts = split_returns(pd.Series(np.arange(1., 101.)))
    assert parts["Desarrollo"].isna().iloc[0] and parts["Validación"].isna().iloc[0]  # ningún retorno cruza el corte


def test_diagnosticos_de_los_controles(markets):
    d, acf = diagnostics(markets)
    d = d.set_index(["mercado", "periodo"])
    assert d.loc[("Persistente", "Desarrollo"), "p_ljung_box"] < 1e-6
    assert d.loc[("Persistente", "Validación"), "acf_1"] > .3
    assert d.loc[("Aleatorio", "Validación"), "p_ljung_box"] > .05
    assert d.loc[("Decaimiento", "Desarrollo"), "acf_1"] > .4 > d.loc[("Decaimiento", "Validación"), "acf_1"]
    assert len(acf) == 3 * 2 * 10


def test_serie_corta_no_se_contrasta():
    d, _ = diagnostics({"corta": make_market(0, n=50)})
    assert d.acf_1.isna().all() and d.p_ljung_box.isna().all()


# --- Pruebas múltiples ------------------------------------------------------------------------

def test_pearson_many_coincide_con_scipy():
    corr, p = pearson_many(np.array([[1.], [2.], [4.], [3.]]), np.array([1., 2., 3., 4.]))
    ref = stats.pearsonr([1, 2, 4, 3], [1, 2, 3, 4])
    assert np.isclose(corr[0], ref.statistic) and np.isclose(p[0], ref.pvalue)


def test_senales_nulas(null_returns):
    table, best, direction = null_signal_experiment(*null_returns, 500, seed=52)
    assert (table.p_dev < .05).sum() == 20
    assert (table.p_bonferroni < .05).sum() == 0 and (table.p_bh < .05).sum() == 0
    assert best == 105 and np.isclose(direction * table.ic_dev[best], .0756, atol=1e-4)
    assert table.p_test[best] > .05


def test_monte_carlo_de_falsos_positivos():
    mc = monte_carlo_false_positives(3000, 500, .05, 62)
    assert abs(mc["mean"] - 25) < .5 and mc["p_at_least_one"] == 1
    assert abs(mc["p_at_least_one_bonferroni"] - .05) < .01


# --- Economía ------------------------------------------------------------------------------------

def test_experimento_economico(markets):
    perf = pd.concat([trade_experiment(p, 20).assign(m=n) for n, p in markets.items()])
    assert np.allclose(perf.gross_bps - perf.net_bps, 20)
    assert (perf.net_bps < 0).all()
    flat = trade_experiment(pd.Series(np.arange(100., 200.)), 0).iloc[0]
    assert np.isclose(flat.gross_bps, flat.net_bps)


# --- Ejercicios E1–E7 -----------------------------------------------------------------------------

def test_e1_autocorrelacion_manual(markets):
    s = longest_valid_run(split_returns(markets["Persistente"])["Desarrollo"])
    for k in (1, 2, 5):
        assert np.isclose(manual_autocorrelation(s.to_numpy(), k), s.autocorr(k))
    with_gap = np.array([1., 2., np.nan, 4., 5., 6., 7.])
    assert np.isfinite(manual_autocorrelation(with_gap, 1))
    with pytest.raises(ValueError):
        manual_autocorrelation(with_gap, 0)


def test_e2_niveles_frente_a_retornos():
    t = random_walk_acf(50, 500, seed=7)
    assert (t.acf_levels > .9).all() and abs(t.acf_returns.mean()) < .02


def test_e3_ljung_box_y_potencia(markets):
    lb = ljung_box_table(split_returns(markets["Persistente"])["Desarrollo"], (5, 10))
    assert list(lb.index) == [5, 10] and (lb.lb_pvalue < 1e-6).all()
    power = ljung_box_power(.05, (300, 5000), reps=60)
    assert power.rejection_rate.iloc[1] > power.rejection_rate.iloc[0]


def test_e4_bonferroni_y_falsos_positivos():
    p = np.array([.0001, .001, .01, .04, .2])
    assert list(bonferroni_manual(p, .05)) == [True, True, False, False, False]  # umbral 0,01
    t = false_positive_table((20, 100), n_simulations=1000)
    assert np.allclose(t.expected_theory, [1, 5])
    assert (abs(t.p_at_least_one_mc - t.p_at_least_one_theory) < .05).all()


def test_e5_el_ic_maximo_crece_con_el_numero_de_senales(null_returns):
    t = max_ic_by_count(*null_returns, (100, 500, 1000), (101, 202, 303))
    assert t.max_abs_ic_dev.is_monotonic_increasing
    assert (t.p_test > .05).all()


def test_e6_autocorrelacion_movil_sin_futuro(markets):
    r = np.log(markets["Decaimiento"]).diff()
    roll = rolling_autocorr(r, 200)
    truncated = rolling_autocorr(r.iloc[:1000], 200)
    assert np.allclose(roll.iloc[:1000].dropna(), truncated.dropna())  # no usa datos futuros
    cut = markets["Decaimiento"].index[int(2400 * .65)]
    delay = regime_detection_delay(roll, cut, .2)
    assert delay["bars_after_change"] > 0


def test_e7_el_coste_elimina_el_patron(markets):
    valid = pd.concat([trade_experiment(markets["Persistente"], c).assign(cost=c) for c in (0, 5, 10, 40)])
    valid = valid[valid.periodo == "Validación"]
    assert valid.set_index("cost").loc[0, "net_bps"] > 0 > valid.set_index("cost").loc[5, "net_bps"]
