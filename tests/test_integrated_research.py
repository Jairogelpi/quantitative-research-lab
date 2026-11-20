import numpy as np
import pandas as pd
import pytest

from quantlab.p17.integrated_research import (EXCHANGES, audit_capture, block_ci, circular_shift_null, decision,
                                              evaluate, fee_sensitivity, lead_lag, opportunities, opportunity_metrics,
                                              partial_fill_engine, predictability, register_protocol, returns_bps, run_study,
                                              session_lead_lag, summarize_pnl, synchronize, synthetic_quotes, validate)


@pytest.fixture(scope="module")
def study():
    quotes = validate(synthetic_quotes())
    g = synchronize(quotes)
    cut = g.index[int(len(g) * .60)]
    all_op = opportunities(g, cut)
    d = all_op[all_op.observed]
    dev, val = d[d.split == "dev"], d[d.split == "val"]
    threshold = max(0., dev.signal_bps.quantile(.7))
    return quotes, g, cut, all_op, dev, val, threshold


def test_resultado_de_referencia(study):
    quotes, g, cut, all_op, dev, val, threshold = study
    assert len(synthetic_quotes()) == 21453 and len(g) == 7199 and cut == pd.Timestamp("2025-01-01 01:12:00", tz="UTC")
    stats, oos, a, b = predictability(dev, val)
    assert round(oos, 4) == .3294 and len(dev) == 843 and len(val) == 561
    s = summarize_pnl(evaluate(val, threshold))
    assert s.fills == 143 and s.failed_depth == 15 and round(s.gross_eur, 2) == 9.95 and round(s.net_eur_conditional, 2) == -183.55
    assert (all_op.split == "val").sum() - len(val) == 14


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.drop(columns="bid_size"), "Faltan"),
    (lambda r: r[r.exchange != "okx"], "Cobertura"),
    (lambda r: pd.concat([r, r.head(1)]), "Cobertura"),
    (lambda r: r.assign(ask=np.where(r.index == 5, r.bid - 1, r.ask)), "inválidas"),
    (lambda r: r.assign(bid_size=np.where(r.index == 5, 0, r.bid_size)), "inválidas"),
])
def test_validate_rechaza(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate(mutate(synthetic_quotes(n=800)))


def test_rejilla_causal_y_antiguedad(study):
    quotes, g, *_ = study
    for e in EXCHANGES:
        age = g[e + "_age_s"].dropna()
        assert (age >= 0).all() and (age <= 1.5).all()
    with pytest.raises(ValueError, match="insuficiente"):
        synchronize(validate(synthetic_quotes(n=300)))


def test_lead_lag_recupera_retrasos(study):
    _, g, cut, *_ = study
    r = returns_bps(g)
    assert lead_lag(r[r.index < cut]).idxmax().to_dict() == {"okx": 3, "bitvavo": 2}
    sessions = session_lead_lag(r[r.index < cut])
    assert len(sessions) == 4 and set(sessions.lag_max) == {2, 3}


def test_oportunidades_sin_cruzar_el_corte(study):
    _, g, cut, all_op, dev, val, _ = study
    assert (dev.exit_time < cut).all() and (val.index >= cut).all()
    assert (val.index.to_series().diff().dropna() >= pd.Timedelta(seconds=5)).all()
    t = dev.index[10]
    assert np.isclose(dev.loc[t, "entry_ask"], g.loc[t + pd.Timedelta(seconds=1), "okx_ask"])
    assert np.isclose(dev.loc[t, "exit_bid"], g.loc[t + pd.Timedelta(seconds=5), "okx_bid"])


def test_motor_de_ejecucion(study):
    *_, val, threshold = study
    pv = evaluate(val, threshold)
    f = pv[pv.filled]
    assert np.allclose(f.net_pnl, .01 * (f.sell_px - f.buy_px) - f.fees)
    assert (f[["spread_slippage", "fees"]] >= 0).all().all()
    assert pv.loc[~pv.intent, "net_pnl"].eq(0).all() and pv.loc[pv.failed_depth, "net_pnl"].isna().all()
    sens = fee_sensitivity(val, threshold)
    assert (sens.diff().dropna() <= 1e-10).all() and round(sens[0], 3) == -11.541


def test_ejemplo_manual_de_una_operacion():
    frame = pd.DataFrame({"signal_bps": [5.], "entry_ask": [100.], "entry_mid": [99.5], "exit_bid": [101.],
                          "exit_mid": [101.5], "entry_depth_ok": [True], "exit_depth_ok": [True]})
    p = evaluate(frame, 1., qty=1., fee_bps=10., extra_bps=0.).iloc[0]
    assert np.isclose(p.gross_pnl, 2.) and np.isclose(p.fees, .201) and np.isclose(p.net_pnl, 1 - .201)
    assert np.isclose(p.spread_slippage, 1.)


def test_bootstrap_y_decision(study):
    _, g, cut, all_op, dev, val, threshold = study
    pv = evaluate(val, threshold)
    ci = block_ci(pv.net_pnl)
    assert np.allclose(ci, [-.372974, -.298504], atol=1e-6)
    *_, b = predictability(dev, val)
    out = decision(b, pv, all_op, ci)
    assert out["stat_ok"] and not out["econ_ok"]
    lo, hi = block_ci(np.r_[np.full(50, 1.), np.full(50, 3.)], block=5, reps=500)
    assert 1 < lo < 2 < hi < 3


def test_protocolo_huella_estable():
    p = {"señal": "kraken 3 s", "umbral": "p70 desarrollo"}
    assert register_protocol(p) == register_protocol(dict(reversed(list(p.items()))))
    assert register_protocol(p) != register_protocol({**p, "umbral": "p80"})


def test_auditoria(study):
    quotes, g, *_ = study
    audit = audit_capture(quotes, g)
    assert audit.sin_futuro.all() and (audit.duplicados == 0).all() and (audit.edad_max_s <= 1.5).all()
    assert audit.loc["kraken", "filas"] == (quotes.exchange == "kraken").sum()


def test_null_circular():
    rng = np.random.default_rng(0)
    x = rng.normal(size=400)
    out = circular_shift_null(x, x + rng.normal(size=400), n_null=200)
    assert out["p_circular"] < .01 and out["n"] == 400
    noise = circular_shift_null(x, rng.normal(size=400), n_null=200)
    assert noise["p_circular"] > .05
    with_nan = circular_shift_null(np.r_[x[:200], np.full(5, np.nan)], np.r_[x[:200], np.ones(5)], n_null=50)
    assert with_nan["n"] == 200
    # Con autocorrelación fuerte, barajar da un null demasiado estrecho.
    trend = np.cumsum(rng.normal(size=400))
    walk = circular_shift_null(trend, np.cumsum(rng.normal(size=400)), n_null=300)
    assert walk["sd_shuffle"] < walk["sd_circular"]


def test_ejecucion_parcial_con_inventario():
    times = pd.date_range("2025-01-01", periods=12, freq="s", tz="UTC")
    g = pd.DataFrame({"okx_bid": 100., "okx_ask": 101., "okx_mid": 100.5, "okx_bid_size": .004, "okx_ask_size": .02},
                     index=times)
    frame = pd.DataFrame({"signal_bps": [5.], "entry_ask": [101.], "entry_mid": [100.5], "entry_ask_size": [.006],
                          "entry_time": [times[1]], "exit_time": [times[5]]}, index=[times[0]])
    out = partial_fill_engine(g, frame, 1., qty=.01, fee_bps=0., extra_bps=0., max_wait_s=1).iloc[0]
    assert out.partial_entry and np.isclose(out.bought, .006) and np.isclose(out.sold, .006)  # 0,004 + 0,002
    assert np.isclose(out.realized_eur, .006 * (100 - 101)) and out.used_wait
    short_wait = partial_fill_engine(g, frame, 1., qty=.01, fee_bps=0., extra_bps=0., max_wait_s=0).iloc[0]
    assert np.isclose(short_wait.inventory_open, .002)
    assert np.isclose(short_wait.marked_eur, .004 * (100 - 101) + .002 * (100.5 - 101))


def test_ejecucion_parcial_sin_solapamiento(study):
    _, g, _, _, _, val, threshold = study
    pf = partial_fill_engine(g, val, threshold)
    assert len(pf) <= evaluate(val, threshold).intent.sum()
    assert (pf.entry_time.iloc[1:].to_numpy() > pf.closed_at.iloc[:-1].to_numpy()).all()


def test_metricas_por_oportunidad():
    bps = pd.Series([0., 10., -5., np.nan, 0.])
    eur = pd.Series([0., 1., -.5, np.nan, 0.])
    m = opportunity_metrics(bps, eur, 10.)
    assert m["n"] == 4 and np.isclose(m["media_bps"], 1.25) and np.isclose(m["acierto_operaciones"], .5)
    assert np.isclose(m["caida_max_pct"], .5 / 11 * 100)


def test_run_study_equivale_al_protocolo_paso_a_paso(study):
    out = run_study(synthetic_quotes())
    assert round(out["oos_r2"], 4) == .3294 and out["summary"].loc["fills", "validation"] == 143
    assert np.allclose(out["ci"], [-.372974, -.298504], atol=1e-6) and not out["decision"]["econ_ok"]
    with pytest.raises(ValueError, match="insuficiente"):
        run_study(synthetic_quotes(n=600))  # ~48 oportunidades en validación
