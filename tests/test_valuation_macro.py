"""P10 · Valoración y macro: valor temporal, bonos, DCF, inflación, curva, estudio de eventos y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p10.valuation_macro import (
    align_events,
    availability_report,
    bond_price,
    bond_shock,
    dcf,
    dcf_sensitivity,
    development_horizons,
    fetch_fred,
    fisher_comparison,
    fred_indicators,
    inverted_curve,
    manual_pv,
    present_value,
    real_return,
    split_events,
    surprise_groups,
    synthetic_events_and_prices,
    synthetic_macro,
    validate_events_prices,
    value_per_share,
    yoy_by_date,
)

FLOWS = 100 * 1.04 ** np.arange(5)


@pytest.fixture(scope="module")
def study():
    events, prices = validate_events_prices(*synthetic_events_and_prices(42))
    results, cutoff = split_events(align_events(events, prices))
    return events, prices, results, cutoff, surprise_groups(results[results.eligible])


# --- Valor temporal, bonos y DCF ----------------------------------------------------------

def test_valor_actual_y_bonos():
    assert np.isclose(present_value([110], .10), 100)
    assert np.isclose(bond_price(1000, .04, .04, 5), 1000)
    prices = [bond_price(1000, .04, r, 5) for r in (.02, .03, .04, .05, .06, .07)]
    assert (np.diff(prices) < 0).all()
    with pytest.raises(ValueError):
        present_value([100], -1)


def test_dcf():
    assert np.isclose(dcf([100], .10, 0)["enterprise_value"], 1000)
    base = dcf(FLOWS, .08, .02)
    assert np.isclose(base["enterprise_value"], 1783.43, atol=.01)
    assert dcf(FLOWS, .09, .02)["enterprise_value"] < base["enterprise_value"]
    assert np.isclose(value_per_share(FLOWS, .08, .02, 300, 100), 14.8343, atol=1e-4)
    for args in [(FLOWS, .02, .02), (FLOWS, .08, -1), ([], .08, .02), ([100, -5], .08, .02)]:
        with pytest.raises(ValueError):
            dcf(*args)


def test_sensibilidad_dcf_monotona():
    table = dcf_sensitivity(FLOWS, [.06, .08, .10, .12], [0, .02, .04], 300, 100)
    assert (table.diff().dropna() < 0).all().all()          # más tasa, menos valor
    assert (table.T.diff().dropna() > 0).all().all()        # más crecimiento, más valor


# --- Inflación y curva --------------------------------------------------------------------

def test_inflacion_y_fisher():
    m = synthetic_macro()
    assert m.inflation_yoy_pct.iloc[:12].isna().all() and m.inflation_yoy_pct.iloc[12:].notna().all()
    assert np.isclose(real_return(.05, .03), 1.05 / 1.03 - 1)


def test_inflacion_compara_el_mismo_mes_aunque_falte_uno():
    idx = pd.date_range("2024-01-01", periods=24, freq="MS")
    cpi = pd.Series(100 * 1.01 ** np.arange(24), index=idx).drop(idx[20])  # falta un mes
    yoy = yoy_by_date(cpi)
    expected = (cpi.loc[idx[22]] / cpi.loc[idx[10]] - 1) * 100
    assert np.isclose(yoy.loc[idx[22]], expected)
    positional = cpi.pct_change(12, fill_method=None) * 100
    assert not np.isclose(positional.loc[idx[22]], expected)  # por posición se compara con otro mes


def test_fred_indicators_sin_mezclar_frecuencias():
    idx = pd.date_range("2023-01-01", periods=15, freq="MS")
    days = pd.date_range("2023-01-02", periods=10, freq="D")
    fred = {"CPIAUCSL": pd.Series(np.linspace(300, 315, 15), index=idx).drop(idx[13]),
            "DGS10": pd.Series(4.0, index=days), "DGS2": pd.Series(4.5, index=days)}
    monthly, curve = fred_indicators(fred)
    assert len(monthly) == 15 and pd.isna(monthly.loc[idx[13], "cpi_index"])
    cpi = fred["CPIAUCSL"]
    assert np.isclose(monthly.loc[idx[14], "inflation_yoy_pct"], (cpi.loc[idx[14]] / cpi.loc[idx[2]] - 1) * 100)
    assert (curve == -50).all() and len(curve) == 10


# --- Estudio de eventos --------------------------------------------------------------------

@pytest.mark.parametrize("mutate, message", [
    (lambda e, p: (e.assign(consensus_at=e.available_at + pd.Timedelta("1h")), p), "posterior"),
    (lambda e, p: (pd.concat([e, e.iloc[[0]]]), p), "duplicados"),
    (lambda e, p: (e.assign(actual_pct=np.inf), p), "no finito"),
    (lambda e, p: (e, p.assign(price=0.0)), "Precios no válidos"),
    (lambda e, p: (e, pd.concat([p, p.iloc[[0]]])), "duplicados o vacíos"),
])
def test_validacion_de_eventos(mutate, message):
    events, prices = synthetic_events_and_prices(42)
    with pytest.raises(ValueError, match=message):
        validate_events_prices(*mutate(events, prices))


def test_exige_zona_horaria_en_csv():
    events, prices = synthetic_events_and_prices(42)
    naive = events.assign(available_at=events.available_at.dt.tz_localize(None))
    with pytest.raises(ValueError, match="zona horaria"):
        validate_events_prices(naive, prices, require_tz=True)


def test_alineacion_causal(study):
    _, _, results, cutoff, valid = study
    assert (results.pre_timestamp < results.available_at).all()
    for h in (1, 6, 24):
        stamp = results[f"post_timestamp_{h}h"]
        assert (stamp >= results.available_at).all() and (stamp <= results.available_at + pd.Timedelta(hours=h)).all()
    assert (valid.loc[valid.split == "development", "available_at"] + pd.Timedelta(hours=24) < cutoff).all()
    assert not valid.overlap_24h.any()


def test_alineacion_sin_precio_previo_queda_ausente():
    events, prices = synthetic_events_and_prices(42)
    events, prices = validate_events_prices(events, prices)
    gap = prices[(prices.timestamp < events.available_at[0] - pd.Timedelta("2h")) | (prices.timestamp >= events.available_at[0])]
    out = align_events(events, gap)
    assert pd.isna(out.pre_price.iloc[0]) and pd.isna(out.return_1h_bps.iloc[0])


def test_el_efecto_programado_aparece_en_desarrollo(study):
    valid = study[4]
    dev = valid[valid.split == "development"].groupby("surprise_group").return_1h_bps.mean()
    assert dev["Inferior"] > 0 > dev["Superior"]
    assert valid[valid.split == "development"].surprise_pp.corr(valid[valid.split == "development"].return_1h_bps) < -.7


# --- Ejercicios E1–E8 -------------------------------------------------------------------------

def test_e1_valor_actual_manual():
    assert np.isclose(manual_pv([110], .10), 100)
    assert np.isclose(manual_pv(FLOWS, .08), present_value(FLOWS, .08))


def test_e2_el_bono_largo_pierde_mas():
    t = bond_shock((2, 5, 10))
    assert t.change_pct.is_monotonic_decreasing and (t.change_pct < 0).all()
    assert np.isclose(t.loc[10, "change_pct"], -7.722, atol=1e-3)


def test_e3_dcf_con_tasa_mas_alta():
    assert np.isclose(value_per_share(FLOWS, .10, .02, 300, 100), 10.3374, atol=1e-4)


def test_e4_fisher_exacto_frente_a_aproximado():
    f = fisher_comparison(.15, .10)
    assert np.isclose(f["approx"], .05) and np.isclose(f["exact"], 1.15 / 1.10 - 1)
    assert f["error_pp"] > fisher_comparison(.05, .03)["error_pp"]


def test_e5_curva_invertida():
    inv = inverted_curve(synthetic_macro())
    assert inv["count"] == 4 and np.isclose(inv["share"], 4 / 48)


def test_e6_horizontes_en_desarrollo(study):
    t = development_horizons(study[4])
    dev = t.loc["development"]
    assert (dev[("return_1h_bps", "count")] == [6, 19, 6]).all()
    assert "Superior" not in t.loc["validation"].dropna().index


def test_e8_informe_de_ausencias():
    events = pd.DataFrame({"event_id": ["a", "b", "c"], "available_at": [pd.NaT, pd.NaT, pd.NaT],
                           "consensus_at": [pd.NaT] * 3, "actual_pct": [3.0, 2.9, np.nan],
                           "consensus_pct": [np.nan] * 3})
    report = availability_report(events)
    assert report.loc["sin consenso", "n"] == 3 and report.loc["sin dato publicado", "n"] == 1
    assert np.isclose(report.loc["sin consenso", "pct"], 100)


@pytest.mark.live
def test_fred_en_vivo():
    cpi = fetch_fred("CPIAUCSL", "2024-01-01", "2024-12-31")
    assert len(cpi) == 12 and (cpi > 0).all()
