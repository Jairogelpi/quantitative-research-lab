"""P15 · Regímenes y diversificación: validación, indicadores, unión point-in-time, riesgo, beta y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p15.regimes import (
    ASSETS,
    align_panel,
    balance_vs_rates,
    correlation_difference,
    delayed_publication_demo,
    diversification_curve,
    macro_indicators,
    portfolio_risk,
    regime_correlations,
    regime_summary,
    synthetic_inputs,
    systematic_decomposition,
    two_asset_variance,
    validate_macro,
    validate_returns,
    zero_variance_weight,
)

WEIGHTS = pd.Series([.25, .35, .30, .10], index=ASSETS)


@pytest.fixture(scope="module")
def data():
    r, m = synthetic_inputs(42)
    r, m = validate_returns(r), macro_indicators(validate_macro(m))
    panel, cutoff = align_panel(r, m, WEIGHTS)
    return r, m, panel, cutoff


# --- Validación e indicadores ----------------------------------------------------------------

@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.iloc[:50], "80 retornos"),
    (lambda r: r.drop(index=r.index[10]), "consecutivos"),
    (lambda r: r.assign(BTC=np.nan), "no finitos"),
])
def test_validacion_de_retornos(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_returns(mutate(synthetic_inputs(42)[0]))


def test_validacion_macro():
    _, m = synthetic_inputs(42)
    with pytest.raises(ValueError, match="duplicado"):
        validate_macro(pd.concat([m, m.iloc[[0]]]))


def test_indicadores_y_regimenes(data):
    _, m, _, _ = data
    assert m.regime.iloc[0] == "Desconocido"
    assert set(m.regime.iloc[1:]) == {"Subida", "Estable", "Bajada"}
    row = m.iloc[5]
    assert np.isclose(row.yield_curve_bps, (row.yield_10y_pct - row.yield_2y_pct) * 100)
    assert np.isclose(row.real_policy_proxy_pct, row.policy_rate_pct - row.inflation_yoy_pct)


def test_union_sin_datos_futuros(data):
    _, _, panel, cutoff = data
    known = panel.available_at.notna()
    assert (panel.loc[known, "available_at"] <= panel.loc[known, "decision_at"]).all()
    assert ((panel.decision_at - panel.available_at).dropna() <= pd.Timedelta(days=75)).all()
    assert panel[panel.split == "Desarrollo"].date.max() < panel[panel.split == "Validación"].date.min()
    assert (~panel.known_regime).sum() == 3


# --- Riesgo y beta ---------------------------------------------------------------------------------

def test_riesgo_de_cartera(data):
    r, _, panel, _ = data
    vol, contribution = portfolio_risk(r, WEIGHTS)
    assert np.isclose(vol, (r @ WEIGHTS).std()) and np.isclose(contribution.sum(), vol)
    assert vol < r.std() @ WEIGHTS  # diversificación: menor que la media ponderada de volatilidades
    assert np.allclose(panel.portfolio_return, r.to_numpy() @ WEIGHTS.to_numpy())


def test_descomposicion_sistematica(data):
    _, _, panel, _ = data
    s = systematic_decomposition(panel[panel.split == "Desarrollo"], panel[panel.split == "Validación"])
    assert np.isclose(s["systematic_var"] + s["residual_var"], s["total_var"])
    assert abs(np.dot(s["resid"], s["x"])) < 1e-9


def test_resumen_y_correlaciones_por_regimen(data):
    _, _, panel, _ = data
    means, counts = regime_summary(panel, ASSETS + ["portfolio_return"])
    assert counts.loc[("Validación", "Subida")] == 27
    corr = regime_correlations(panel)
    assert corr.loc[("Desarrollo", "Subida")] > 0 > corr.loc[("Desarrollo", "Bajada")]


# --- Ejercicios E1–E8 ---------------------------------------------------------------------------------

def test_e1_varianza_de_dos_activos():
    assert np.isclose(two_asset_variance(.5, .4, .15, 1), .275 ** 2)
    assert np.isclose(two_asset_variance(.5, .4, .15, 0), .045625)
    assert np.isclose(two_asset_variance(.5, .2, .2, -1), 0)
    w = zero_variance_weight(.4, .15)
    assert np.isclose(two_asset_variance(w, .4, .15, -1), 0, atol=1e-15)
    with pytest.raises(ValueError):
        two_asset_variance(.5, .4, .15, 1.5)


def test_e2_contribuciones_con_otros_pesos(data):
    r = data[0]
    vol, c = portfolio_risk(r, pd.Series([.4, .3, .2, .1], index=ASSETS))
    assert c.idxmax() == "BTC" and np.isclose(c.sum(), vol)


def test_e3_el_riesgo_sistematico_no_desaparece():
    t = diversification_curve((1, 10, 200), weeks=3000)
    assert t.vol_simulated.is_monotonic_decreasing
    assert t.vol_simulated.iloc[-1] > .95 * t.systematic_floor.iloc[-1]
    assert np.allclose(t.vol_simulated, t.vol_theory, rtol=.05)


def test_e5_balance_frente_a_tipos(data):
    table = balance_vs_rates(data[1])
    assert table.loc["Subida", "Contracción"] == 25 and table.loc["Bajada", "Expansión"] == 24


def test_e6_union_por_disponibilidad():
    demo = delayed_publication_demo(12, 15)
    early = demo[demo.known_by_reference & ~demo.known_by_availability]
    assert len(early) == 7  # 7 semanas en que la unión por referencia usaría un dato aún no publicado
    known = demo[demo.known_by_availability]
    assert (known.date >= known.available_at).all()


def test_e6_umbral_de_antiguedad(data):
    r, m, _, _ = data
    strict, _ = align_panel(r, m, WEIGHTS, max_age_days=30)
    assert (~strict.known_regime).sum() > 3


def test_e8_diferencia_de_correlacion(data):
    out = correlation_difference(data[2], "Subida", period="Desarrollo")
    assert out["n_regime"] + out["n_rest"] == data[2].query("split == 'Desarrollo' and known_regime").shape[0]
    assert out["significant"] and out["diff"] > 0
