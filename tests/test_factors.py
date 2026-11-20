"""P12 · Alpha, beta y factores: validación, Jensen, multifactor, atribución, validación congelada, factores y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p12.factors import (
    active_vs_alpha,
    annualized_attribution,
    attribution,
    chronological_split,
    daily_risk_free,
    daily_rule_returns,
    factor_after_costs,
    fit_model,
    frozen_validation,
    long_short_factor,
    manual_alpha_beta,
    model_table,
    omitted_factor_table,
    read_daily,
    rolling_beta,
    synthetic_factor_data,
    synthetic_universe,
    validate_daily_factors,
)

FACTORS = ["market_excess", "momentum_factor", "liquidity_factor"]
SPECS = {"Mercado": ["market_excess"], "Multifactor": FACTORS}


@pytest.fixture(scope="module")
def data():
    d = validate_daily_factors(synthetic_factor_data(42, 900), ["A", "B"])
    train, test = chronological_split(d, .65, 5, 3)
    table, models = model_table(train, ["A", "B"], SPECS)
    return d, train, test, table, models


# --- Datos y validación ----------------------------------------------------------------

def test_tipo_diario():
    assert np.isclose((1 + daily_risk_free(.02, 365)) ** 365 - 1, .02)
    with pytest.raises(ValueError):
        daily_risk_free(-1)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.assign(A=np.nan), "no finitos"),
    (lambda d: d.drop(index=d.index[10]), "consecutivos"),
    (lambda d: d.iloc[:50], "insuficiente"),
    (lambda d: d.assign(B=-1.0), "inválido"),
])
def test_validacion_rechaza_datos_invalidos(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_daily_factors(mutate(synthetic_factor_data(42, 900)), ["A", "B"])


def test_lee_csv_y_rechaza_duplicados(tmp_path):
    path = tmp_path / "daily.csv"
    pd.DataFrame({"timestamp": ["2024-01-01", "2024-01-01"], "net_return": [.01, .02]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicados"):
        read_daily(path)


def test_separacion_cronologica(data):
    d, train, test, _, _ = data
    assert train.index.max() < test.index.min() and len(train) + len(test) == len(d) and len(train) == 585


# --- Regresión, atribución y validación ---------------------------------------------------

def test_jensen_recupera_parametros_conocidos():
    x = np.linspace(-.02, .02, 100)
    toy = pd.DataFrame({"market_excess": x, "risk_free_return": 0., "toy": .001 + 1.5 * x})
    fit = fit_model(toy, "toy", ["market_excess"])
    assert np.isclose(fit.params["const"], .001) and np.isclose(fit.params["market_excess"], 1.5)


def test_factores_colineales():
    d = validate_daily_factors(synthetic_factor_data(42, 200), ["A"]).assign(dup=lambda f: f.market_excess * 2)
    with pytest.raises(ValueError, match="colineales"):
        fit_model(d, "A", ["market_excess", "dup"])


def test_tabla_de_modelos_reproduce_la_referencia(data):
    t = data[3].set_index(["strategy", "model"])
    assert np.isclose(t.loc[("A", "Mercado"), "alpha_daily_bps"], 6.2938, atol=1e-4)
    assert t.loc[("A", "Mercado"), "alpha_p_value"] < .05 < t.loc[("A", "Multifactor"), "alpha_p_value"]
    assert np.isclose(t.loc[("B", "Multifactor"), "alpha_daily_bps"], 5.5939, atol=1e-4)


def test_atribucion_reconcilia(data):
    _, train, test, _, models = data
    for s in ("A", "B"):
        for frame in (train, test):
            parts = attribution(frame, s, models[s, "Multifactor"])
            assert np.allclose(parts.sum(axis=1), frame[s])
        assert abs(attribution(train, s, models[s, "Multifactor"]).residual.mean()) < 1e-10


def test_validacion_congelada(data):
    _, _, test, _, models = data
    v, parts = frozen_validation(test, ["A", "B"], models, "Multifactor", FACTORS)
    v = v.set_index("strategy")
    assert np.isclose(v.loc["B", "frozen_unexplained_bps"] - v.loc["A", "frozen_unexplained_bps"],
                      (models["B", "Multifactor"].params["const"] - models["A", "Multifactor"].params["const"]) * 1e4)
    assert v.loc["A", "diagnostic_alpha_p"] > .05 > v.loc["B", "diagnostic_alpha_p"]


def test_beta_movil_solo_usa_el_pasado(data):
    d = data[0]
    full = rolling_beta(d, ["A"], 90)
    cut = rolling_beta(d.iloc[:400], ["A"], 90)
    assert np.allclose(full.iloc[:400].dropna(), cut.dropna())
    assert full.A.iloc[:89].isna().all()


# --- Factores long-short ------------------------------------------------------------------------

def test_factor_momentum_sin_mirar_el_futuro():
    u = synthetic_universe(43)
    m = long_short_factor(u, 20, 2)
    assert m["factor"].iloc[:20].isna().all() and np.isfinite(m["factor"].iloc[20:]).all()
    assert np.allclose(m["score"].iloc[20].to_numpy(), (1 + u.iloc[:20]).prod().to_numpy() - 1)
    assert (m["long_mask"].iloc[20:].sum(axis=1) == 2).all() and (m["short_mask"].iloc[20:].sum(axis=1) == 2).all()
    # Cambiar el retorno de hoy no cambia la cartera de hoy.
    shocked = u.copy()
    shocked.iloc[60] = shocked.iloc[60] * 10
    assert (long_short_factor(shocked)["long_mask"].iloc[60] == m["long_mask"].iloc[60]).all()


# --- Ejercicios E1–E7 -----------------------------------------------------------------------------

def test_e1_alpha_beta_manual(data):
    _, train, _, _, models = data
    for s in ("A", "B"):
        alpha, beta = manual_alpha_beta(train[s] - train.risk_free_return, train.market_excess)
        assert np.allclose([alpha, beta], models[s, "Mercado"].params.to_numpy())
    with pytest.raises(ValueError):
        manual_alpha_beta([1, 2, 3], [0, 0, 0])


def test_e2_retorno_activo_frente_a_alpha(data):
    _, train, _, _, models = data
    t = active_vs_alpha(train, ["A", "B"], models)
    # media(r_s − r_m) = α + (β − 1) · media(r_m − r_f): la diferencia entre activo y alpha viene de la beta
    assert np.allclose(t.alpha_bps + t.beta_gap_bps, t.active_bps, atol=1e-6)


def test_e3_factor_omitido(data):
    t = omitted_factor_table(data[1], "A", FACTORS)
    assert t.loc["Completo", "r_squared"] > t.loc["Sin momentum_factor", "r_squared"]
    assert t.loc["Sin momentum_factor", "alpha_p_value"] < .05 < t.loc["Completo", "alpha_p_value"]


def test_e4_atribucion_anual(data):
    _, train, _, _, models = data
    attr = pd.DataFrame({s: attribution(train, s, models[s, "Multifactor"]).mean() * 1e4 for s in ("A", "B")}).T
    ann = annualized_attribution(attr)
    assert np.allclose(ann.total, train[["A", "B"]].mean() * 365 * 100)


def test_e5_ventana_mas_larga_mas_estable(data):
    d = data[0]
    stds = [rolling_beta(d, ["A"], w).A.std() for w in (30, 90, 180)]
    assert stds[0] > stds[1] > stds[2]


def test_e6_reversion_y_costes():
    u = synthetic_universe(43)
    m, rv = long_short_factor(u), long_short_factor(u, reverse=True)
    assert np.allclose((m["factor"] + rv["factor"]).dropna(), 0)
    assert rv["turnover"].dropna().iloc[0] == 1  # el primer día se construye la cartera completa
    assert np.isclose(factor_after_costs(rv["factor"], rv["turnover"], 0).mean(), rv["factor"].mean())
    assert factor_after_costs(rv["factor"], rv["turnover"], 20).mean() < rv["factor"].mean()


def test_e7_regla_diaria_sin_mirar_el_futuro():
    close = pd.Series(np.r_[np.linspace(100, 120, 30), np.linspace(120, 90, 30)],
                      index=pd.date_range("2025-01-01", periods=60, freq="D", tz="UTC"))
    out = daily_rule_returns(close, 5, 20.)
    mom = close / close.shift(5) - 1
    assert (out.position == (mom.shift(1).loc[out.index] > 0).astype(float)).all()
    switch = out.index[out.position.diff().abs() == 1][0]
    assert np.isclose(out.loc[switch, "strategy"],
                      out.loc[switch, "position"] * out.loc[switch, "benchmark_return"] - .001)
