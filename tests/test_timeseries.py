"""P04 · Motor de series temporales: OHLCV, retornos, volatilidad, objetivo futuro y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p04.timeseries import (
    add_returns,
    add_target,
    add_volatility,
    build_ohlcv,
    compare_frequencies,
    fetch_trades,
    forward_fill_comparison,
    load_trades_csv,
    manual_ohlcv,
    return_decomposition,
    synthetic_trades,
    target_alignment,
    validate_trades,
    volatility_reaction,
)

FEATURES = ["simple_return", "log_return", "rolling_volatility", "realized_volatility",
            "price_range", "volume", "trade_count"]


@pytest.fixture
def example():
    return pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01 09:59:59", "2026-01-01 10:00:01", "2026-01-01 10:00:10",
        "2026-01-01 10:00:20", "2026-01-01 10:00:40", "2026-01-01 10:00:55",
        "2026-01-01 10:01:00", "2026-01-01 10:03:00"], utc=True),
        "price": [99, 100, 105, 98, 103, 104, 106, 108], "quantity": [.1, .2, .5, .3, .4, .6, .1, .1]})


@pytest.fixture(scope="module")
def synthetic():
    return synthetic_trades()[0]


@pytest.fixture(scope="module")
def series(synthetic):
    return add_target(add_volatility(add_returns(build_ohlcv(synthetic, "1min")), 10), 3)


# --- Validación -----------------------------------------------------------------

def test_valida_y_ordena(example):
    out = validate_trades(example.iloc[::-1])
    assert out.timestamp.is_monotonic_increasing and str(out.timestamp.dt.tz) == "UTC"


@pytest.mark.parametrize("bad", [
    pd.DataFrame({"timestamp": [], "price": [], "quantity": []}),
    pd.DataFrame({"timestamp": ["2026-01-01"], "price": [1.0]}),
])
def test_rechaza_vacio_o_sin_columnas(bad):
    with pytest.raises(ValueError, match="Faltan columnas"):
        validate_trades(bad)


@pytest.mark.parametrize("col, value", [("price", 0), ("quantity", -1), ("price", np.inf)])
def test_rechaza_datos_invalidos(example, col, value):
    bad = example.astype({"price": float})
    bad.loc[0, col] = value
    with pytest.raises(ValueError, match="inválidos"):
        validate_trades(bad)


def test_rechaza_ids_duplicados(example):
    bad = example.assign(trade_id=[1, 2, 3, 4, 5, 6, 7, 7])
    with pytest.raises(ValueError, match="IDs duplicados"):
        validate_trades(bad)


def test_no_elimina_trades_con_mismo_precio_y_hora(example):
    dup = pd.concat([example, example.iloc[[1]]])
    assert len(validate_trades(dup)) == len(example) + 1


def test_lee_csv_de_p03(tmp_path, example):
    path = tmp_path / "p03_live_trades.csv"
    example.assign(side="b", order_type="m", trade_id=range(1, 9)).to_csv(path, index=False)
    trades, provenance = load_trades_csv(path)
    assert len(trades) == 8 and provenance["mode"] == "csv"


# --- OHLCV: las 9 comprobaciones del cuaderno ------------------------------------

def test_vela_del_ejemplo_manual(example):
    bars = build_ohlcv(example)
    row = bars.loc["2026-01-01 10:01:00+00:00"]
    assert np.allclose(row[["open", "high", "low", "close", "volume"]].astype(float), [100, 105, 98, 104, 2])
    assert bars.loc["2026-01-01 10:02:00+00:00", "open"] == 106
    assert bars.loc["2026-01-01 10:03:00+00:00", "is_empty"]
    assert pd.isna(bars.loc["2026-01-01 10:03:00+00:00", "close"])
    assert list(bars.boundary_window) == [True, False, False, False, True]


def test_ohlcv_conserva_totales_y_coherencia(synthetic):
    bars = build_ohlcv(synthetic, "1min")
    assert bars.trade_count.sum() == len(synthetic)
    assert np.isclose(bars.volume.sum(), synthetic.quantity.sum())
    assert np.isclose(bars.notional_volume.sum(), (synthetic.price * synthetic.quantity).sum())
    valid = bars.loc[~bars.is_empty]
    assert (valid.high >= valid[["open", "close"]].max(axis=1)).all()
    assert (valid.low <= valid[["open", "close"]].min(axis=1)).all()


def test_sintetico_reproducible(synthetic):
    bars = build_ohlcv(synthetic, "1min")
    assert len(synthetic) == 1755 and len(bars) == 90
    assert list(bars.index[bars.is_empty].strftime("%H:%M")) == ["10:31", "10:32"]


def test_ventana_no_positiva(example):
    with pytest.raises(ValueError, match="no positiva"):
        build_ohlcv(example, "0s")


# --- Retornos, volatilidad y objetivo ---------------------------------------------

def test_retornos(series):
    assert np.allclose(np.log1p(series.simple_return.dropna()), series.log_return.dropna())
    assert series.loc[series.analysis_close.isna(), "simple_return"].isna().all()
    assert series.loc[series.analysis_close.shift(1).isna(), "simple_return"].isna().all()
    # El acumulado se reinicia en cada segmento: vale 0 en su primer cierre.
    firsts = series.dropna(subset=["analysis_close"]).groupby("segment_id").head(1)
    assert (firsts.cumulative_return == 0).all()


def test_volatilidad():
    probe = pd.DataFrame({"log_return": [.01, -.01, .01, np.nan, .02]})
    vol = add_volatility(probe, 3)
    assert np.isclose(vol.loc[2, "rolling_volatility"], np.std([.01, -.01, .01], ddof=1))
    assert np.isclose(vol.loc[2, "realized_volatility"], np.sqrt(3 * .01 ** 2))
    assert vol.loc[[0, 1, 3, 4], "rolling_volatility"].isna().all()
    with pytest.raises(ValueError, match="n debe ser"):
        add_volatility(probe, 1)


def test_objetivo_futuro(series):
    assert series.forward_return.tail(3).isna().all()
    assert series.loc[series.analysis_close.isna(), "forward_return"].isna().all()
    for step in range(1, 4):
        assert series.loc[series.analysis_close.shift(-step).isna(), "forward_return"].isna().all()
    check = pd.DataFrame({"analysis_close": [100., 110., 121., np.nan, 100., 120.],
                          "segment_id": pd.array([0, 0, 0, None, 1, 1], dtype="Int64")},
                         index=pd.date_range("2026-01-01", periods=6, freq="min", tz="UTC"))
    check = add_target(check, 2)
    assert np.isclose(check.forward_return.iloc[0], .21)
    assert check.forward_return.iloc[1:].isna().all()
    with pytest.raises(ValueError, match="h debe ser"):
        add_target(check, 0)


def test_tabla_de_investigacion(series):
    table = series[FEATURES + ["forward_return", "target_end_utc"]].dropna()
    assert len(table) == 60
    assert (table.target_end_utc > table.index).all()


def test_frecuencias_conservan_volumen(synthetic):
    table = compare_frequencies(synthetic)
    assert np.allclose(table.total_volume_btc, synthetic.quantity.sum())
    assert list(table.frequency) == ["5s", "15s", "1min", "5min"]
    assert table.bars.is_monotonic_decreasing


# --- Ejercicios E1–E5 ---------------------------------------------------------------

def test_e1_ohlcv_manual(example):
    group = example.iloc[1:6]
    assert list(manual_ohlcv(group)) == pytest.approx([100, 105, 98, 104, 2])
    assert list(manual_ohlcv(group.iloc[::-1])) == pytest.approx([100, 105, 98, 104, 2])
    empty = manual_ohlcv(group.iloc[:0])
    assert empty[["open", "high", "low", "close"]].isna().all() and empty["volume"] == 0


def test_e1_coincide_con_build_ohlcv(synthetic):
    bars = build_ohlcv(synthetic, "1min")
    end = bars.index[5]
    group = synthetic[(synthetic.timestamp >= end - pd.Timedelta("1min")) & (synthetic.timestamp < end)]
    expected = bars.loc[end, ["open", "high", "low", "close", "volume"]].astype(float)
    assert np.allclose(manual_ohlcv(group), expected)


def test_e2_retorno_compuesto_cero():
    r = return_decomposition([100., 110., 100.])
    assert list(r.simple_return) == pytest.approx([.1, -1 / 11])
    assert np.isclose(r.attrs["compounded"], 0)
    assert np.isclose(r.attrs["sum_simple"], .1 - 1 / 11) and r.attrs["sum_simple"] > 0
    assert np.isclose(r.attrs["sum_log"], 0)


def test_e3_la_ventana_corta_reacciona_antes(series):
    table = volatility_reaction(series, "2026-01-01T10:49:00Z", (5, 10, 20))
    lags = table["bars_after_start"].astype(float)
    assert lags.loc[5] <= lags.loc[10] <= lags.loc[20]
    assert (table["valid_values"].loc[5] > table["valid_values"].loc[20])


def test_e4_imputar_crea_retornos_artificiales(synthetic):
    bars = build_ohlcv(synthetic, "1min")
    table = forward_fill_comparison(bars)
    assert table.loc["Sin imputar", "valid_returns"] == 84
    assert table.loc["Último cierre (ffill)", "valid_returns"] == 87
    assert table.loc["Último cierre (ffill)", "zero_returns"] - table.loc["Sin imputar", "zero_returns"] == 2
    assert table.attrs["imputed_returns"] == 3


def test_e5_alineacion_temporal(series):
    table = target_alignment(series, (1, 3, 5))
    assert table[["all_after_observation", "exact_horizon", "no_gap_crossed"]].all().all()
    assert list(table.known_targets) == [84, 80, 76]
    assert list(table.unknown_tail) == [1, 3, 5]


@pytest.mark.live
def test_trades_kraken_en_vivo():
    trades, provenance = fetch_trades(count=50)
    assert len(trades) > 0 and provenance["mode"] == "live"
    assert len(build_ohlcv(trades, "1min")) > 0
