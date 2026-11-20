"""P09 · Rentabilidad y riesgo: validación, equity, drawdown, ratios, operaciones, costes, ruina y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p09.performance import (
    break_even_daily_cost,
    cost_sensitivity,
    drawdown,
    equity_curve,
    load_daily_csv,
    manual_equity_drawdown,
    performance_metrics,
    recovery_return,
    risk_free_comparison,
    ruin_grid,
    ruin_table,
    simulate_ruin,
    split_stability,
    synthetic_daily,
    trade_log_to_pnl,
    trade_metrics,
    validate_daily,
)


@pytest.fixture(scope="module")
def data():
    daily, trades = synthetic_daily()
    return validate_daily(daily), trades


# --- Validación ------------------------------------------------------------------

def test_sintetico_reproducible_y_reconciliado(data):
    daily, trades = data
    assert len(daily) == 365
    equity = equity_curve(daily.net_return)
    assert np.isclose(trades.net_pnl.sum(), equity.iloc[-1] - 1000)
    assert np.allclose(trades.gross_pnl - trades.cost, trades.net_pnl)
    assert np.isclose(equity.iloc[-1], 444.4704, atol=1e-4)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.iloc[:1], "insuficientes"),
    (lambda d: pd.concat([d.iloc[:3], d.iloc[[2]]]), "duplicadas"),
    (lambda d: d.drop(index=d.index[5]), "irregular"),
    (lambda d: d.drop(columns="net_return"), "Falta net_return"),
    (lambda d: d.assign(net_return=-1.0), "inválidos"),
    (lambda d: d.assign(gross_return=np.inf), "inválidos"),
])
def test_validacion_rechaza_datos_invalidos(data, mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_daily(mutate(data[0].copy()))


def test_lee_csv(tmp_path, data):
    path = tmp_path / "daily_returns.csv"
    data[0].iloc[:5].reset_index().to_csv(path, index=False)
    assert len(load_daily_csv(path)) == 5


# --- Las 12 comprobaciones del cuaderno ------------------------------------------------

def test_equity_y_drawdown():
    e = equity_curve(pd.Series([-.1, .2]), 1000)
    assert np.allclose(e, [1000, 900, 1080])
    assert np.isclose(drawdown(e).min(), -.1)
    assert np.isclose(performance_metrics([-.1, .2]).cumulative_return, .08)
    with pytest.raises(ValueError):
        equity_curve([-1.0])


def test_metricas_por_operacion():
    t = trade_metrics([10, -5, 0, 15, -10])
    assert np.isclose(t.win_rate, .4) and np.isclose(t.flat_rate, .2)
    assert np.isclose(t.profit_factor, 25 / 15) and np.isclose(t.expectancy, 2)
    assert np.isclose(t.payoff_ratio, 12.5 / 7.5)
    assert np.isinf(trade_metrics([1, 2]).profit_factor)
    assert np.isnan(trade_metrics([0, 0]).profit_factor)


def test_sharpe_indefinido_y_ruina_trivial():
    assert np.isnan(performance_metrics([0., 0.]).sharpe_ratio)
    assert simulate_ruin([-.1, .1], exposure=0, block=1, paths=20)[0] == 0
    assert simulate_ruin([-.9, -.9], block=1, horizon=1, paths=20)[0] == 1


def test_metricas_de_la_estrategia_sintetica(data):
    m = performance_metrics(data[0].net_return)
    assert np.isclose(m.max_drawdown, .5710, atol=1e-4) and m.sharpe_ratio < 0
    assert m.calmar_ratio < 0  # CAGR negativo no se vuelve positivo al dividir por el MDD


# --- Costes y ruina --------------------------------------------------------------------------

def test_sensibilidad_a_costes(data):
    t = cost_sensitivity(data[0].gross_return)
    assert t.total_return_pct.is_monotonic_decreasing
    assert np.isclose(t.set_index("cost_bps_per_day").loc[20, "total_return_pct"], -55.553, atol=1e-3)


def test_mas_exposicion_mas_ruina(data):
    t = ruin_table(data[0].net_return, (.25, .5, 1., 1.5), seed=42)
    assert t.risk_of_ruin.is_monotonic_increasing
    assert list(t.risk_of_ruin.round(3)) == [0, 0, .031, .402]
    with pytest.raises(ValueError):
        simulate_ruin([.01, .02], block=5)


# --- Ejercicios E1–E8 ----------------------------------------------------------------------------

def test_e1_equity_y_drawdown_manuales():
    m = manual_equity_drawdown([-.1, .2], 1000)
    assert np.allclose(m.equity, [1000, 900, 1080]) and np.allclose(m.drawdown, [0, -.1, 0])
    returns = pd.Series(np.random.default_rng(1).normal(0, .02, 50))
    e = equity_curve(returns)
    manual = manual_equity_drawdown(returns)
    assert np.allclose(manual.equity, e) and np.allclose(manual.drawdown, drawdown(e))


def test_e2_retorno_de_recuperacion():
    assert np.allclose(recovery_return([.1, .25, .5]), [1 / 9, 1 / 3, 1])
    assert recovery_return(0) == 0
    with pytest.raises(ValueError):
        recovery_return(1)


def test_e3_acierto_frente_a_esperanza():
    a, b = trade_metrics([1] * 9 + [-20]), trade_metrics([10] * 3 + [-2] * 7)
    assert a.win_rate == .9 and np.isclose(a.expectancy, -1.1)
    assert b.win_rate == .3 and np.isclose(b.expectancy, 1.6)


def test_e4_tipo_libre_de_riesgo(data):
    t = risk_free_comparison(data[0].net_return, (0., .02, .05))
    assert t.sharpe_ratio.is_monotonic_decreasing
    constant = risk_free_comparison(pd.Series([.001] * 30), (0., .05))
    assert constant.isna().all().all()  # desviación típica nula: Sharpe y Sortino indefinidos
    below_rf = risk_free_comparison(pd.Series([.0001] * 30), (.05,))
    assert np.isnan(below_rf.sharpe_ratio.iloc[0]) and np.isclose(below_rf.sortino_ratio.iloc[0], -np.sqrt(365))


def test_e5_coste_de_equilibrio(data):
    losing = break_even_daily_cost(data[0].gross_return)
    assert losing["already_losing"] and losing["break_even_bps"] == 0
    winning = break_even_daily_cost(data[0].benchmark_return)
    bps = winning["break_even_bps"]
    assert not winning["already_losing"] and 3 < bps < 4
    g = data[0].benchmark_return
    assert (1 + g - (bps - .01) / 1e4).prod() > 1 > (1 + g - (bps + .01) / 1e4).prod()


def test_e6_rejilla_de_ruina(data):
    t = ruin_grid(data[0].net_return, (.5, .7), (180, 365), (1, 10), paths=500)
    assert len(t) == 8 and t.risk_of_ruin.between(0, 1).all()
    by = t.set_index(["threshold", "horizon", "block"]).risk_of_ruin
    assert by[(.7, 365, 1)] > by[(.5, 180, 1)]  # umbral más exigente y horizonte más largo: más ruina


def test_e7_registro_de_operaciones_a_pnl():
    log = pd.DataFrame({"gross_return": [.01, -.02, .03], "net_return": [.008, -.022, .028]})
    out = trade_log_to_pnl(log, 1000)
    assert np.allclose(out.capital_before, [1000, 1008, 1008 * .978])
    assert np.isclose(1000 + out.net_pnl.sum(), 1000 * (1 + log.net_return).prod())


def test_e8_estabilidad_por_tramos(data):
    t = split_stability(data[0].net_return)
    assert list(t.columns) == ["primer tramo", "segundo tramo"]
    assert (t.loc["sharpe_ratio"] < 0).all()
