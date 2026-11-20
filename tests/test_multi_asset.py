"""P14 · Multiactivo y capitalización: capitalización, calendario semanal, divisa, métricas y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p14.multi_asset import (
    cagr,
    compound_return,
    dividend_paths,
    equivalent_rate,
    eur_return,
    future_value,
    fx_decomposition,
    manual_compound,
    performance,
    prepare_weekly,
    present_value,
    split_halves,
    synthetic_prices,
    total_return,
)


@pytest.fixture(scope="module")
def weekly():
    raw = synthetic_prices()
    usd, eur, n = prepare_weekly(raw)
    return raw, usd, eur, n


# --- Capitalización ----------------------------------------------------------------------

def test_capitalizacion():
    assert np.isclose(future_value(1000, .1, 2), 1210) and np.isclose(present_value(1210, .1, 2), 1000)
    assert np.isclose(compound_return([.5, -.5]), -.25)
    with pytest.raises(ValueError):
        future_value(1000, -1, 1)
    with pytest.raises(ValueError):
        compound_return([-1.5])


def test_retorno_total_y_real():
    assert np.isclose(total_return(100, 98, 4), .02)
    with pytest.raises(ValueError):
        total_return(0, 98, 4)


# --- Calendario y divisa -------------------------------------------------------------------

def test_calendario_semanal(weekly):
    raw, usd, eur, n = weekly
    assert n == len(raw) and len(eur) == 260
    assert (eur.index.to_series().diff().dropna() == pd.Timedelta(days=7)).all()
    assert list(eur.columns) == ["BTC", "Acciones", "Bonos", "Oro", "Global", "USD efectivo"]


def test_conversion_a_eur(weekly):
    _, usd, eur, _ = weekly
    assert np.allclose(eur.Acciones, usd.Acciones / usd.EURUSD)
    assert np.allclose(eur["USD efectivo"], 1 / usd.EURUSD)
    returns = eur.pct_change(fill_method=None).iloc[1:]
    reconstructed = fx_decomposition(usd)
    assert np.allclose(reconstructed, returns[reconstructed.columns])


@pytest.mark.parametrize("mutate, message", [
    (lambda r: pd.concat([r, r.iloc[[0]]]), "duplicadas"),
    (lambda r: r.assign(BTC=-1.0), "no positivos"),
    (lambda r: r.iloc[:100], "53 semanas"),
])
def test_validacion_de_precios(mutate, message):
    with pytest.raises(ValueError, match=message):
        prepare_weekly(mutate(synthetic_prices()))


# --- Métricas ------------------------------------------------------------------------------

def test_metricas(weekly):
    _, _, eur, _ = weekly
    m = performance(eur)
    returns = eur.pct_change(fill_method=None).iloc[1:]
    assert np.allclose((1 + returns).prod(), eur.iloc[-1] / eur.iloc[0])
    assert (m.max_drawdown_pct >= 0).all() and (m.drag_pp >= -1e-10).all()
    assert np.isclose(m.loc["BTC", "return_pct"], -74.97, atol=.01)


# --- Ejercicios E1–E8 ------------------------------------------------------------------------

def test_e1_capitalizacion_manual():
    assert np.isclose(manual_compound(1000, [.2, -.1, .15, -.05]), 1179.90)
    assert np.isclose(manual_compound(1000, [.2, -.1]), 1000 * (1 + compound_return([.2, -.1])))


def test_e2_tipo_mensual_equivalente():
    monthly = equivalent_rate(.12, 12)
    assert np.isclose(monthly, .009489, atol=1e-6) and monthly < .01
    assert np.isclose((1 + monthly) ** 12 - 1, .12)


def test_e3_cagr():
    assert np.isclose(cagr(1000, 2000, 10), 2 ** .1 - 1)
    values = [cagr(1000, 2000, y) for y in (3, 10, 20)]
    assert values[0] > values[1] > values[2]
    assert all(c < 1 / y for c, y in zip(values, (3, 10, 20)))  # el CAGR queda por debajo de la media aritmética


def test_e4_semana_interior_ausente():
    raw = synthetic_prices()
    week = raw.index[(raw.index >= "2023-03-06") & (raw.index <= "2023-03-10")]
    with pytest.raises(ValueError, match="sin huecos"):
        prepare_weekly(raw.drop(index=week))


def test_e5_retorno_en_eur():
    assert np.isclose(eur_return(.10, .05), .047619, atol=1e-6)


def test_e6_dividendos():
    t = dividend_paths([100, 105, 98, 110], [3, 3, 3])
    assert np.isclose(t.price_return_pct.iloc[-1], 10) and np.isclose(t.total_cash_pct.iloc[-1], 19)
    assert t.total_reinvested_pct.iloc[-1] > t.total_cash_pct.iloc[-1]
    with pytest.raises(ValueError):
        dividend_paths([100, 105], [1, 2])


def test_e8_mitades_rebasadas(weekly):
    _, _, eur, _ = weekly
    halves = split_halves(eur, 1000)
    assert halves["primera"]["end"] == halves["segunda"]["start"]
    for half in halves.values():
        assert np.allclose(half["levels"].iloc[0], 1000)
