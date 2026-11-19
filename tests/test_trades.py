"""P03 · Análisis de operaciones ejecutadas: volumen, VWAP, Trade Imbalance, CVD y ventanas."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p03.trades import (
    EXAMPLE_TRADES,
    add_trade_features,
    aggregate_trades,
    compare_windows,
    count_imbalance,
    fetch_recent_trades,
    normalize_trades,
    summarize_trades,
    synthetic_trades,
    top_volume_windows,
    trade_metrics,
)


@pytest.fixture
def example():
    return normalize_trades(EXAMPLE_TRADES)


@pytest.fixture
def synthetic():
    return synthetic_trades()[0]


# --- Las 12 comprobaciones del ejemplo del cuaderno P03 ---------------------

def test_resumen_del_ejemplo(example):
    expected = {"trade_count": 5, "trade_volume": 2, "notional_volume": 120014.30,
                "buy_volume": 1.4, "sell_volume": .6, "signed_volume": .8,
                "trade_imbalance": .4, "vwap": 60007.15, "average_trade_size": .4}
    summary = summarize_trades(example)
    for field, value in expected.items():
        assert np.isclose(summary[field], value), field


def test_cvd_y_vwap_acumulado(example):
    features = add_trade_features(example)
    assert list(features["signed_volume"]) == pytest.approx([.1, .5, -.2, .8, -.4])
    assert np.isclose(features["cvd"].iloc[-1], .8)
    assert np.isclose(features["cumulative_vwap"].iloc[-1], 60007.15)


def test_muestra_vacia_tiene_imbalance_indefinido(example):
    assert np.isnan(summarize_trades(example.iloc[:0])["trade_imbalance"])


# --- Validación ---------------------------------------------------------------

def test_normaliza_tipos_y_orden(example):
    assert example["price"].dtype == float or np.issubdtype(example["price"].dtype, np.number)
    assert str(example["timestamp"].dt.tz) == "UTC"
    assert list(example["trade_id"]) == ["1", "2", "3", "4", "5"]
    shuffled = normalize_trades(EXAMPLE_TRADES[::-1])
    assert list(shuffled["trade_id"]) == ["1", "2", "3", "4", "5"]


@pytest.mark.parametrize("rows", [
    [],
    [["60000", "0.1", 1.0, "b"]],
])
def test_rechaza_respuesta_vacia_o_esquema_inesperado(rows):
    with pytest.raises(ValueError, match="esquema inesperado"):
        normalize_trades(rows)


@pytest.mark.parametrize("change", [
    {0: "0"},            # precio cero
    {1: "-0.1"},         # cantidad negativa
    {0: float("inf")},   # precio no finito
    {3: "x"},            # lado desconocido
])
def test_rechaza_valores_invalidos(change):
    rows = [list(r) for r in EXAMPLE_TRADES]
    for idx, value in change.items():
        rows[0][idx] = value
    with pytest.raises(ValueError, match="inválidos"):
        normalize_trades(rows)


def test_rechaza_ids_duplicados():
    rows = [list(r) for r in EXAMPLE_TRADES]
    rows[1][6] = rows[0][6]
    with pytest.raises(ValueError, match="IDs duplicados"):
        normalize_trades(rows)


# --- Muestra sintética y agregación -------------------------------------------

def test_sintetico_reproducible(synthetic):
    summary = summarize_trades(synthetic)
    assert len(synthetic) == 240
    assert synthetic["price"].iloc[0] == 59999.55
    assert np.isclose(summary["trade_volume"], 19.6904)
    assert np.isclose(summary["buy_volume"], 9.8701)
    assert synthetic_trades()[1]["mode"] == "synthetic"


def test_las_4_comprobaciones_de_agregacion(synthetic):
    bars = aggregate_trades(synthetic, "10s")
    features = add_trade_features(synthetic)
    assert bars.trade_count.sum() == len(synthetic)
    assert np.isclose(bars.trade_volume.sum(), synthetic.quantity.sum())
    assert np.isclose(bars.signed_volume.sum(), features.signed_volume.sum())
    assert bars.trade_imbalance.dropna().between(-1, 1).all()


def test_ventanas_del_ejemplo(example):
    bars = aggregate_trades(example, "2s")
    # [10:00:00, 10:00:02) contiene el trade de las 10:00:01, etiquetado con su cierre.
    assert bars.index[0] == pd.Timestamp("2026-01-01T10:00:02Z")
    assert list(bars["trade_count"]) == [1, 2, 2]
    assert list(bars["boundary_window"]) == [True, False, True]
    assert np.isclose(bars["trade_intensity"].iloc[1], 1.0)


def test_ventana_vacia_tiene_vwap_e_imbalance_indefinidos():
    rows = [list(EXAMPLE_TRADES[0]), list(EXAMPLE_TRADES[4])]  # 10:00:01 y 10:00:05
    bars = aggregate_trades(normalize_trades(rows), "1s")
    empty = bars.loc[bars["trade_count"] == 0]
    assert len(empty) == 3
    assert (empty["trade_volume"] == 0).all()
    assert empty["vwap"].isna().all() and empty["trade_imbalance"].isna().all()


# --- Ejercicios E1–E4 ---------------------------------------------------------

def test_e1_vwap_imbalance_y_media(example):
    m = trade_metrics(example)
    assert np.isclose(m["vwap"], 60007.15)
    assert np.isclose(m["trade_imbalance"], .4)
    assert np.isclose(m["arithmetic_mean_price"], 60005.2)
    s = summarize_trades(example)
    assert np.isclose(m["vwap"], s["vwap"]) and np.isclose(m["trade_imbalance"], s["trade_imbalance"])


def test_e1_muestra_vacia(example):
    m = trade_metrics(example.iloc[:0])
    assert np.isnan(m["vwap"]) and np.isnan(m["trade_imbalance"]) and np.isnan(m["arithmetic_mean_price"])


def test_e2_imbalance_por_numero(example):
    assert np.isclose(count_imbalance(example), (3 - 2) / 5)
    assert np.isnan(count_imbalance(example.iloc[:0]))


def test_e3_compara_ventanas(synthetic):
    table = compare_windows(synthetic, ("5s", "10s", "30s"))
    assert list(table.index) == ["5s", "10s", "30s"]
    assert (table["complete_windows"] > 0).all()
    assert table.loc["5s", "complete_windows"] > table.loc["30s", "complete_windows"]
    assert table["extreme_share"].between(0, 1).all()


def test_e4_top_ventanas_y_retorno_contemporaneo(synthetic):
    bars = aggregate_trades(synthetic, "10s")
    top = top_volume_windows(bars, 5)
    assert len(top) == 5
    assert top["trade_volume"].is_monotonic_decreasing
    assert not bars.loc[top.index, "boundary_window"].any()
    first = top.index[0]
    prev = bars.index[bars.index.get_loc(first) - 1]
    expected = (bars.loc[first, "last_price"] / bars.loc[prev, "last_price"] - 1) * 10_000
    assert np.isclose(top.loc[first, "contemporaneous_return_bps"], expected)


def test_e4_sin_cierre_anterior_no_hay_retorno():
    rows = [list(EXAMPLE_TRADES[0]), list(EXAMPLE_TRADES[2]), list(EXAMPLE_TRADES[4])]  # 10:00:01, :03, :05
    bars = aggregate_trades(normalize_trades(rows), "1s")
    top = top_volume_windows(bars, 5)
    # La ventana de las 10:00:04 (trade de :03) va precedida de una ventana vacía: no hay retorno.
    assert np.isnan(top.loc[pd.Timestamp("2026-01-01T10:00:04Z"), "contemporaneous_return_bps"])


@pytest.mark.live
def test_trades_kraken_en_vivo():
    trades, provenance = fetch_recent_trades(count=50)
    assert len(trades) > 0 and provenance["mode"] == "live" and provenance["received_at"]
