"""P05 · Momentum y Mean Reversion: indicadores, alineación, separación temporal, IC, simulación y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p05.signals import (
    add_target,
    breakeven_costs,
    build_features,
    cost_sensitivity,
    development_grid,
    fetch_kraken_ohlc,
    information_table,
    load_p04_series,
    manual_momentum,
    manual_zscore,
    regularize,
    simulate,
    split_train_test,
    strategy_table,
    synthetic_prices,
)


@pytest.fixture(scope="module")
def close():
    return regularize(synthetic_prices()[0], "1min")


@pytest.fixture(scope="module")
def dataset(close):
    return add_target(build_features(close, 20), 5)


@pytest.fixture(scope="module")
def split(dataset):
    return split_train_test(dataset, .65)


@pytest.fixture
def probe():
    return pd.Series([100., 102., 104., 106., 108., 110., np.nan, 112., 114.],
                     index=pd.date_range("2026-01-01", periods=9, freq="1min", tz="UTC"))


# --- Datos y regularización ------------------------------------------------------

def test_sintetico_reproducible(close):
    assert len(close) == 1800 and int(close.isna().sum()) == 3
    assert close.index.min() == pd.Timestamp("2026-01-01T10:01:00Z")
    assert close.iloc[0] == 60000


def test_regularize_inserta_huecos_sin_rellenar():
    idx = pd.to_datetime(["2026-01-01 10:00", "2026-01-01 10:01", "2026-01-01 10:03"], utc=True)
    out = regularize(pd.Series([1., 2., 3.], index=idx), "1min")
    assert len(out) == 4 and pd.isna(out.iloc[2]) and out.index.name == "bar_end_utc"


@pytest.mark.parametrize("series, message", [
    (pd.Series([], dtype=float, index=pd.DatetimeIndex([], tz="UTC")), "vacío"),
    (pd.Series([1., 2.], index=pd.to_datetime(["2026-01-01 10:00"] * 2, utc=True)), "duplicado"),
    (pd.Series([1., 2.], index=pd.to_datetime(["2026-01-01 10:00:00", "2026-01-01 10:00:30"], utc=True)), "incompatibles"),
    (pd.Series([1., -2.], index=pd.to_datetime(["2026-01-01 10:00", "2026-01-01 10:01"], utc=True)), "no válidos"),
])
def test_regularize_rechaza_datos_invalidos(series, message):
    with pytest.raises(ValueError, match=message):
        regularize(series, "1min")


def test_lee_csv_de_p04(tmp_path):
    path = tmp_path / "p04_series.csv"
    pd.DataFrame({"bar_end_utc": ["2026-01-01T10:01:00Z", "2026-01-01T10:02:00Z"],
                  "analysis_close": [100.0, 101.0]}).to_csv(path, index=False)
    close, provenance = load_p04_series(path)
    assert list(close) == [100.0, 101.0] and str(close.index.tz) == "UTC"
    pd.DataFrame({"close": [1.0]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="analysis_close"):
        load_p04_series(path)


def test_kraken_exige_intervalo_coherente():
    with pytest.raises(ValueError, match="deben coincidir"):
        fetch_kraken_ohlc(interval_min=5, window="1min")


# --- Las 10 comprobaciones del cuaderno --------------------------------------------

def test_formulas_y_huecos(probe):
    f = build_features(probe, 2)
    t = add_target(f, 2)
    assert np.isclose(f.momentum.iloc[2], .04)
    assert np.isclose(f.sma.iloc[2], 103)
    assert np.isclose(f.rolling_std.iloc[2], np.sqrt(2))
    assert np.isclose(f.z_score.iloc[2], 1 / np.sqrt(2))
    assert np.isclose(t.forward_return.iloc[0], 106 / 102 - 1)
    assert pd.isna(t.forward_return.iloc[3])
    assert pd.isna(f.momentum.iloc[7])
    assert pd.isna(build_features(pd.Series([1., 1., 1.]), 2).z_score.iloc[-1])


def test_features_causales(close):
    features = build_features(close, 20)
    cut = len(close) // 2
    pd.testing.assert_frame_equal(build_features(close.iloc[:cut], 20), features.iloc[:cut], check_freq=False)


def test_fechas_del_objetivo(dataset):
    valid = dataset.dropna(subset=["forward_return"])
    assert (valid.entry_time > valid.index).all() and (valid.exit_time > valid.entry_time).all()
    assert ((valid.entry_time - valid.index) == pd.Timedelta("1min")).all()
    assert ((valid.exit_time - valid.entry_time) == pd.Timedelta("5min")).all()


def test_ema_se_reinicia_tras_hueco(probe):
    f = build_features(probe, 2)
    # Tras el hueco solo hay 2 cierres: la EMA del nuevo segmento empieza con su segundo cierre.
    assert pd.isna(f.ema.iloc[6]) and pd.isna(f.ema.iloc[7]) and f.ema.iloc[8] > 0
    with pytest.raises(ValueError, match="n >= 2"):
        build_features(probe, 1)


# --- Separación temporal, IC y simulación ----------------------------------------------

def test_separacion_sin_fugas(split):
    train, test, split_time = split
    assert len(train) == 1115 and len(test) == 624
    assert train.exit_time.max() < split_time and test.index.min() >= split_time


def test_tabla_ic_usa_cuantiles_de_desarrollo(split):
    train, test, _ = split
    table = information_table(train, test)
    assert list(table.period) == ["desarrollo", "validación"] * 2
    dev = table.iloc[0]
    assert dev.n_low == dev.n_high == 223  # 20 % de 1.115 en desarrollo
    assert table.iloc[1].n_low != table.iloc[1].n_high  # en validación los cuantiles no se recalculan
    assert np.isclose(table.ic_pearson.iloc[0], train.momentum_signal.corr(train.forward_return))


def test_simulacion_sin_solapamiento_y_costes(split):
    train, _, _ = split
    for rule in ("momentum", "mean_reversion", "periodic_long"):
        trades = simulate(train, rule, 20)
        assert (trades.entry_time.iloc[1:].to_numpy() > trades.exit_time.iloc[:-1].to_numpy()).all()
        assert np.allclose(trades.gross_return - trades.net_return, .002)
        assert np.isclose(trades.equity.iloc[-1], (1 + trades.net_return).prod())
    with pytest.raises(ValueError, match="Regla desconocida"):
        simulate(train, "otra", 20)


def test_reglas_de_entrada(split):
    train, _, _ = split
    mom = simulate(train, "momentum", 0)
    assert (train.loc[mom.signal_time, "momentum"] > 0).all()
    rev = simulate(train, "mean_reversion", 0, z_threshold=1.5)
    assert (train.loc[rev.signal_time, "z_score"] < -1.5).all()


def test_simulacion_vacia():
    empty = pd.DataFrame(columns=["momentum", "z_score", "entry_time", "exit_time", "forward_return"])
    out = simulate(empty, "momentum", 20)
    assert out.empty and "equity" in out


def test_tabla_de_estrategias_y_costes(split):
    train, test, _ = split
    table, logs = strategy_table({"desarrollo": train, "validación": test}, 20)
    assert len(table) == 6 and set(logs) == {(p, r) for p in ("desarrollo", "validación")
                                            for r in ("momentum", "mean_reversion", "periodic_long")}
    costs = cost_sensitivity(test, (0, 10, 20, 40))
    for _, group in costs.groupby("rule"):
        # Mismas operaciones con cualquier coste; el neto baja exactamente 10 bps cada 10 bps de coste.
        assert group.trades.nunique() == 1
        assert np.allclose(np.diff(group.mean_net_bps), [-10, -10, -20])


# --- Ejercicios E1–E5 ---------------------------------------------------------------------

def test_e1_momentum_manual():
    m = manual_momentum([100, 102, 104, 106], 2)
    assert m[0] is None and m[1] is None
    assert np.isclose(m[2], .04) and np.isclose(m[3], 106 / 102 - 1)
    f = build_features(pd.Series([100., 102., 104., 106.]), 2)
    assert np.allclose(f.momentum.iloc[2:], m[2:])


def test_e2_zscore_manual():
    z = manual_zscore([100, 102, 104])
    assert np.isclose(z["sma"], 102) and np.isclose(z["std"], 2) and np.isclose(z["z_score"], 1)
    low = manual_zscore([104, 102, 100])
    assert low["z_score"] < 0
    assert np.isnan(manual_zscore([5, 5, 5])["z_score"])


def test_e3_objetivo_no_atraviesa_huecos(dataset, close):
    gap = close.index[close.isna()]
    valid = dataset.dropna(subset=["forward_return"])
    crosses = [(row.Index <= g <= row.exit_time) for row in valid.itertuples() for g in gap]
    assert not any(crosses)


def test_e4_rejilla_solo_en_desarrollo(close):
    grid = development_grid(close, (5, 20, 60), (1, 5, 10))
    assert len(grid) == 9
    # Con un horizonte más largo se pierden más filas al final del desarrollo y alrededor del hueco.
    assert (grid.groupby("lookback").n_train.diff().dropna() < 0).all()
    row = grid.query("lookback == 20 and horizon == 5").iloc[0]
    assert row.n_train == 1115


def test_e5_coste_de_equilibrio(split):
    train, test, _ = split
    periods = {"desarrollo": train, "validación": test}
    _, logs = strategy_table(periods, 20)
    table = breakeven_costs(logs, periods)
    row = table.query("period == 'validación' and rule == 'momentum'").iloc[0]
    trades = logs[("validación", "momentum")]
    assert np.isclose(row.breakeven_cost_bps, trades.gross_return.mean() * 1e4)
    assert table.exposure_pct.between(0, 100).all()
    periodic = table.query("rule == 'periodic_long'").exposure_pct
    assert (periodic > table.query("rule == 'mean_reversion'").exposure_pct.to_numpy()).all()


@pytest.mark.live
def test_ohlc_kraken_en_vivo():
    close, provenance = fetch_kraken_ohlc()
    close = regularize(close, "1min")
    assert len(close) > 100 and provenance["pair"]
