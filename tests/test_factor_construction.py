import numpy as np
import pandas as pd
import pytest

from quantlab.p16.factor_construction import (SCORES, add_scores, annualized_basis, breakeven_cost_bps, build_factor,
                                              crypto_monthly_panel, derivative_pnl, factor_table, fit_model,
                                              long_short_weights, manual_long_short, market_excess, momentum_12_2,
                                              monthly_returns, multiple_testing, perp_carry_score, period_summary,
                                              quantile_comparison, read_ff_monthly, spanning_alpha, summarize,
                                              swap_net_flow, synthetic_panel, validate_panel)


@pytest.fixture(scope="module")
def built():
    panel, mom, lowvol, months = add_scores(validate_panel(synthetic_panel(42)))
    details, net, gross = factor_table(panel)
    return panel, mom, lowvol, months, details, net, gross, months[int(len(months) * .65)]


def test_panel_sintetico_valida():
    panel = validate_panel(synthetic_panel(42))
    assert len(panel) == 7200 and panel.asset.nunique() == 60 and panel.month.nunique() == 120
    assert (panel.available_at < panel.month).all()


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.assign(available_at=p.month), "no disponibles"),
    (lambda p: pd.concat([p, p.head(1)]), "duplicadas"),
    (lambda p: p.assign(month=p.month + pd.Timedelta(days=3)), "primer día"),
    (lambda p: p.assign(asset_return=p.asset_return.where(p.index != 0, -1.5)), "−100"),
    (lambda p: p.assign(rf=np.where(p.index == 0, .01, p.rf)), "RF distinto"),
    (lambda p: p.drop(columns="rf"), "Faltan"),
])
def test_validate_panel_rechaza(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_panel(mutate(synthetic_panel(42)))


def test_pesos_long_short():
    test = pd.DataFrame({"asset": list("ABCD"), "score": [1, 2, 3, 4]})
    w = long_short_weights(test, "score", .25)
    assert np.isclose(w.sum(), 0) and np.isclose(w.abs().sum(), 2)
    assert w["A"] == -1 and w["D"] == 1
    assert long_short_weights(test.assign(score=1), "score", .25).empty
    assert long_short_weights(test.assign(score=[1, np.nan, np.nan, 4]), "score", .25).empty  # 2 válidos → k = 0
    with pytest.raises(ValueError):
        long_short_weights(test, "score", .6)


def test_scores_sin_informacion_futura(built):
    panel, mom, lowvol, *_ = built
    assert mom.iloc[:12].isna().all().all() and mom.iloc[12].notna().all()
    assert lowvol.iloc[:6].isna().all().all()
    # Cambiar el retorno de los meses t y t−1 no altera el momentum 12-2 del mes t.
    asset = "A000"
    r = panel[panel.asset == asset].set_index("month").asset_return
    month = r.index[30]
    altered = r.copy()
    altered.loc[[month, r.index[29]]] = .5
    assert np.isclose(momentum_12_2(r, month), momentum_12_2(altered, month))
    assert np.isclose(momentum_12_2(r, month), panel.set_index(["month", "asset"]).momentum[(month, asset)])


def test_momentum_con_hueco_es_desconocido():
    r = pd.Series(.01, index=pd.date_range("2020-01-01", periods=14, freq="MS")).drop(pd.Timestamp("2020-05-01"))
    assert np.isnan(momentum_12_2(r, "2021-02-01"))


def test_build_factor_reconcilia_y_marca_desconocidos(built):
    *_, details, net, gross, split = built
    for d in details.values():
        assert np.allclose(d.gross - d.cost, d.net, equal_nan=True) and (d.cost >= 0).all()
    assert details["value"].turnover.iloc[0] == 2  # apertura inicial
    panel = validate_panel(synthetic_panel(42))
    first = panel.month.min()
    hole = panel.copy()
    hole.loc[(hole.month == first) & (hole.asset.isin(hole.loc[hole.month == first].nlargest(1, "book_to_market").asset)),
             "asset_return"] = np.nan
    hole, *_ = add_scores(hole)
    assert np.isnan(build_factor(hole, "value").gross.iloc[0])


def test_resultados_sinteticos(built):
    *_, net, gross, split = built
    dev, val = period_summary(net, split)
    assert split == pd.Timestamp("2021-07-01")
    assert round(dev.loc["value", "mean_bps"], 2) == 118.99 and round(val.loc["value", "t_hac"], 2) == 4.55
    assert round(val.loc["carry", "mean_bps"], 2) == -67.53
    assert dev.loc["momentum", "n"] == 66 and dev.loc["low_vol", "n"] == 72


def test_summarize_sin_hac_con_huecos():
    s = pd.Series(np.linspace(-.01, .02, 20), index=pd.date_range("2020-01-01", periods=20, freq="MS"))
    assert np.isfinite(summarize(s).t_hac)
    assert np.isnan(summarize(s.drop(s.index[5])).t_hac)
    assert np.isnan(summarize(s.iloc[:5]).mean_bps)


def test_market_excess_nan_si_falta_retorno():
    panel = validate_panel(synthetic_panel(42))
    panel.loc[0, "asset_return"] = np.nan
    m = market_excess(panel)
    assert np.isnan(m.loc[panel.loc[0, "month"]]) and m.notna().sum() == 119


def test_multiple_testing():
    t = multiple_testing(pd.Series({"a": .001, "b": .02, "c": .04, "d": .5}))
    assert np.allclose(t.p_bonferroni, [.004, .08, .16, 1])
    assert t.rechaza_bonferroni.tolist() == [True, False, False, False]
    assert np.allclose(t.p_bh, [.004, .04, .05333333, .5])
    assert t.rechaza_bh.tolist() == [True, True, False, False]


def test_lector_ff(tmp_path):
    fake = tmp_path / "ff.csv"
    fake.write_text("cabecera\n,Mkt-RF,SMB,HML,RF\n202001,1,-2,3,0.1\n202002,-99.99,1,1,0.1\n2020,10,10,10,1\n")
    parsed = read_ff_monthly(fake, ["Mkt-RF", "SMB", "HML", "RF"])
    assert len(parsed) == 2 and np.isclose(parsed.iloc[0].SMB, -.02) and np.isnan(parsed.iloc[1]["Mkt-RF"])
    (tmp_path / "vacio.csv").write_text("sin datos\n")
    with pytest.raises(ValueError):
        read_ff_monthly(tmp_path / "vacio.csv", ["RF"])


def test_fit_model_recupera_parametros_y_exige_meses_consecutivos():
    idx = pd.date_range("2015-01-01", periods=60, freq="MS")
    x = pd.DataFrame({"f": np.random.default_rng(1).normal(0, .04, 60)}, index=idx)
    y = .002 + 1.5 * x.f
    fit = fit_model(y, x)
    assert np.isclose(fit.params["const"], .002) and np.isclose(fit.params["f"], 1.5)
    with pytest.raises(ValueError, match="consecutivos"):
        fit_model(y.drop(idx[10]), x)
    with pytest.raises(ValueError, match="24"):
        fit_model(y.iloc[:10], x)


def test_derivados():
    assert derivative_pnl([60000]).iloc[0].tolist() == [0, -2000, -2000]
    assert derivative_pnl([62000]).iloc[0]["Call comprada"] == 0
    assert derivative_pnl([58000]).iloc[0]["Put comprada"] == 0
    assert np.isclose(swap_net_flow(1_000_000, .04, .03), 10_000)
    assert np.isclose(swap_net_flow(1_000_000, .03, .04, .5), -5_000)
    assert np.isclose(annualized_basis(61500, 60000, 90), .1013888889)


def test_e1_manual_coincide(built):
    out = manual_long_short({"A": 1, "B": 2, "C": 3, "D": 4}, {"A": .01, "B": .02, "C": .03, "D": .04})
    assert out["k"] == 1 and out["net"] == 0 and out["gross"] == 2 and np.isclose(out["factor_return"], .03)
    panel, *_ = built
    g = panel[panel.month == panel.month.unique()[12]]
    manual = manual_long_short(dict(zip(g.asset, g.value)), dict(zip(g.asset, g.asset_return)))
    w = long_short_weights(g, "value")
    assert all(np.isclose(manual["weights"][a], w.get(a, 0)) for a in g.asset)


def test_e3_e4_e5(built):
    panel, *_, details, net, gross, split = built
    table = quantile_comparison(panel, split, fractions=(1 / 3, .2))
    assert table.loc[("value", .2), "activos_por_lado"] == 12 and table.loc[("value", 1 / 3), "activos_por_lado"] == 20
    assert table.loc[("value", .2), "bruto_bps"] > table.loc[("value", 1 / 3), "bruto_bps"]
    be = breakeven_cost_bps(details["value"], split)
    dev = details["value"][details["value"].index < split]
    assert np.isclose(dev.gross.mean() - be / 1e4 * dev.turnover.mean(), 0)
    out = spanning_alpha(net[net.index < split], "carry", ["value", "size"])
    assert out["n"] == 78 and 0 <= out["r2"] < .1


def test_e6_carry_perpetuo():
    times = pd.date_range("2026-01-01", periods=24, freq="8h", tz="UTC")
    funding = pd.DataFrame({"funding_time": times, "rate": .0001, "kind": "observado"})
    funding.loc[23, ["rate", "kind"]] = [.0009, "estimado"]
    funding.loc[22, "rate"] = .0050  # liquidado DESPUÉS de la formación: no puede entrar
    out = perp_carry_score(funding, times[22], lookback=21)
    assert out["n_observados"] == 21 and np.isclose(out["funding_medio"], .0001)
    assert np.isclose(out["carry_largo_anual"], -.0001 * 3 * 365)
    assert np.isclose(out["estimado_siguiente"], .0009)  # se informa, pero no entra en el score
    later = perp_carry_score(funding, times[23], 21)  # ahora el 0,50 % ya se liquidó y sí cuenta
    assert np.isclose(later["funding_medio"], (20 * .0001 + .0050) / 21)
    with pytest.raises(ValueError, match="Solo"):
        perp_carry_score(funding, times[5], 21)


def test_panel_cripto_mensual():
    days = pd.date_range("2020-01-01", "2020-04-30", freq="D")
    close = pd.DataFrame({"X": np.linspace(100, 200, len(days)), "Y": 50.}, index=days)
    close.loc["2020-03-31", "Y"] = np.nan  # sin cierre al final de marzo
    volume = pd.DataFrame(1e6, index=days, columns=["X", "Y"])
    rf = pd.Series(.001, index=pd.date_range("2020-01-01", periods=4, freq="MS"))
    panel = crypto_monthly_panel(close, volume, rf)
    p = panel.set_index(["month", "asset"])
    assert np.isclose(p.asset_return[(pd.Timestamp("2020-02-01"), "X")], close.X["2020-02-29"] / close.X["2020-01-31"] - 1)
    assert np.isnan(p.asset_return[(pd.Timestamp("2020-03-01"), "Y")]) and np.isnan(p.asset_return[(pd.Timestamp("2020-04-01"), "Y")])
    assert (panel.available_at < panel.month).all() and validate_panel(panel).shape[0] == len(panel)
    feb = close.X.pct_change()["2020-02-01":"2020-02-29"].abs().div(1e6).mean() * 1e9
    assert np.isclose(p.illiquidity[(pd.Timestamp("2020-03-01"), "X")], feb)  # conocida al empezar marzo


def test_monthly_returns():
    days = pd.bdate_range("2020-01-01", "2020-03-31")
    close = pd.Series(np.arange(len(days), dtype=float) + 100, index=days)
    r = monthly_returns(close)
    assert list(r.index) == [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01")]
    assert np.isclose(r.iloc[0], close["2020-02-28"] / close["2020-01-31"] - 1)


def test_scores_cripto_solo_precios():
    days = pd.date_range("2019-01-01", "2021-03-31", freq="D")
    rng = np.random.default_rng(3)
    close = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, .02, (len(days), 6)), axis=0)) * 100, index=days, columns=list("ABCDEF"))
    volume = pd.DataFrame(1e7, index=days, columns=close.columns)
    rf = pd.Series(.001, index=pd.date_range("2019-01-01", "2021-03-01", freq="MS"))
    panel, *_ = add_scores(validate_panel(crypto_monthly_panel(close, volume, rf)))
    assert {"momentum", "low_vol", "liquidity"} <= set(panel) and not {"value", "quality", "size"} & set(panel)
    details, net, _ = factor_table(panel, ["momentum", "low_vol", "liquidity"])
    assert details["momentum"].gross.notna().sum() > 0 and set(SCORES) - set(net) == {"size", "value", "quality", "carry", "investment"}
