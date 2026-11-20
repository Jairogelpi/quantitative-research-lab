"""P07 · Derivados: normalización, basis, OI, funding, eventos de liquidación, cobertura, margen y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p07.derivatives import (
    PRICE_COLS,
    add_features,
    apply_price_shock,
    basis_bps,
    carry_decomposition,
    event_study,
    event_study_horizons,
    funding_payments,
    hedge_curve,
    make_synthetic,
    margin_breach_table,
    margin_scenario,
    normalize,
    oi_change_comparison,
    oi_regime,
    okx_get,
    okx_snapshot,
)


@pytest.fixture(scope="module")
def d():
    return add_features(normalize(make_synthetic()))


@pytest.fixture(scope="module")
def week(d):
    return d.iloc[:168]


@pytest.fixture
def flat_case():
    case = make_synthetic(3)
    case.loc[:, PRICE_COLS] = 60000
    case.loc[:, "funding_rate"] = [.0001, .0001, -.0001]
    return case


# --- Normalización ----------------------------------------------------------------

def test_sintetico_reproducible(d):
    assert len(d) == 720 and d.index.is_unique and d.index.is_monotonic_increasing
    assert int((d.funding_rate != 0).sum()) == 90  # un pago cada 8 h


def test_reindexa_huecos_sin_rellenar():
    raw = make_synthetic(5).drop(index=2)
    out = normalize(raw)
    assert len(out) == 5 and out.iloc[2].isna().all()


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.drop(columns="mark_price"), "Faltan columnas"),
    (lambda r: pd.concat([r, r.iloc[[0]]]), "duplicados"),
    (lambda r: r.assign(timestamp=r.timestamp + pd.Timedelta(minutes=30)), "cierres horarios"),
    (lambda r: r.assign(spot_price=np.inf), "infinitos"),
    (lambda r: r.assign(perp_price=0.0), "no positivos"),
    (lambda r: r.assign(long_liquidation_usdt=-1.0), "negativas"),
])
def test_normalizacion_rechaza_datos_invalidos(mutate, message):
    with pytest.raises(ValueError, match=message):
        normalize(mutate(make_synthetic(5)))


# --- Indicadores ---------------------------------------------------------------------

def test_basis_funding_y_liquidaciones(d):
    row = d.iloc[10]
    assert np.isclose(row.basis_bps, (row.perp_price / row.spot_price - 1) * 1e4)
    assert np.isclose(row.short_funding_usdt, .02 * row.mark_price * row.funding_rate)
    assert d.liquidation_imbalance.dropna().between(-1, 1).all()
    assert np.isclose(row.oi_notional_usdt, row.open_interest_btc * row.mark_price)


def test_regimen_de_oi_cubre_todas_las_horas(d):
    table = oi_regime(d)
    assert table.to_numpy().sum() == 719 and table.shape == (2, 2)


# --- Estudio de eventos ------------------------------------------------------------------

def test_eventos_sin_fugas_y_umbral_de_desarrollo(d):
    results, threshold, train, test = event_study(d, 3)
    assert train.index[-1] + pd.Timedelta(hours=3) < test.index[0]
    assert np.isclose(threshold, train.liquidation_total_usdt.quantile(.95))
    assert d.assign(f=(d.spot_price.shift(-3) / d.spot_price - 1)).f.tail(3).isna().all()
    assert results.loc[("desarrollo", "Liquidación long dominante"), "n"] == 12
    assert results.loc[("validacion", "Liquidación long dominante"), "n"] == 4


def test_historico_insuficiente():
    with pytest.raises(ValueError, match="insuficiente"):
        event_study(add_features(normalize(make_synthetic(6))), 3)


# --- Cobertura y margen ---------------------------------------------------------------------

def test_cobertura_con_precios_constantes(flat_case):
    h = hedge_curve(normalize(flat_case), .1, 1000, 0)
    assert np.isclose(h.funding_pnl.iloc[0], 0)  # entramos después del primer pago
    assert np.isclose(h.net_pnl.iloc[1], .6) and np.isclose(h.net_pnl.iloc[2], 0)
    fees = hedge_curve(normalize(flat_case), .1, 1000, 10)
    assert np.isclose(fees.fees.iloc[-1], 24)  # 4 ejecuciones · 0,1 BTC · 60.000 · 0,1 %


def test_funding_desconocido_deja_el_pnl_indefinido(flat_case):
    flat_case.loc[1, "funding_rate"] = np.nan
    assert hedge_curve(normalize(flat_case), .1, 1000, 0).net_pnl.iloc[1:].isna().all()


def test_cobertura_rechaza_parametros_invalidos(week):
    for q, margin, fee in [(0, 600, 10), (.02, 0, 10), (.02, 600, -1)]:
        with pytest.raises(ValueError, match="inválidos"):
            hedge_curve(week, q, margin, fee)


def test_pnl_de_precio_es_la_variacion_del_basis(week):
    h = hedge_curve(week, .02, 600, 0)
    basis_usdt = week.perp_price - week.spot_price
    assert np.allclose(h.price_pnl, -.02 * (basis_usdt - basis_usdt.iloc[0]))


def test_escenario_de_margen():
    s = margin_scenario(1000, 100)
    assert list(s.umbral_superado) == [False, False, False, False, True, True]
    assert np.isclose(s.loc[2, "pnl_short_usdt"], -50)


# --- Ejercicios E1–E6 ------------------------------------------------------------------------

def test_e1_basis():
    assert np.isclose(basis_bps(60000, 60300), 50)
    assert basis_bps(60000, 59700) < 0
    for spot in (0, -1, np.nan):
        with pytest.raises(ValueError):
            basis_bps(spot, 60300)


def test_e2_oi_en_btc_frente_a_usdt(d):
    table = oi_change_comparison(d)
    assert table.sign_differs.sum() == 235
    differ = table[table.sign_differs]
    # Cuando difieren, el precio se movió en sentido contrario al OI y con más fuerza.
    assert (np.sign(differ.mark_change_pct) != np.sign(differ.oi_change_btc_pct)).all()


@pytest.mark.parametrize("q, rate, short", [(.1, .0001, .6), (.1, -.0001, -.6), (.5, .0001, 3.0)])
def test_e3_pagos_de_funding(q, rate, short):
    p = funding_payments(q, 60000, rate)
    assert np.isclose(p["short_usdt"], short) and np.isclose(p["long_usdt"], -short)


def test_e4_horizontes_con_umbral_propio(d):
    table = event_study_horizons(d, (1, 3, 6))
    assert set(table.index.get_level_values("horizon_h")) == {1, 3, 6}
    long_n = table.xs("Liquidación long dominante", level="event")["n"]
    assert (long_n.xs("validacion", level="periodo") == 4).all()


def test_e5_descomposicion_del_carry(week):
    table = carry_decomposition(week, .02, 600, (0, 10, 20))
    assert np.allclose(table.basis_change_pnl + table.funding_pnl + table.fees, table.net_pnl)
    assert table.net_pnl.is_monotonic_decreasing
    flipped = carry_decomposition(week, .02, 600, (0,), flip_funding=True)
    assert np.isclose(flipped.funding_pnl.iloc[0], -table.funding_pnl.iloc[0])
    assert np.isclose(table.capital_usdt.iloc[0], .02 * week.spot_price.iloc[0] + 600)


def test_e6_cruce_de_margen_con_estres(week):
    calm = margin_breach_table(week, .02, (100, 300, 600))
    assert calm.first_breach_utc.isna().all()
    assert calm.breach_mark_rise_pct.is_monotonic_increasing
    stressed = margin_breach_table(apply_price_shock(week, week.index[100], .15), .02, (100, 300, 600))
    assert stressed.loc[100, "first_breach_utc"] == week.index[100]
    assert stressed.loc[100, "spot_pnl_at_breach_usdt"] > 0  # el spot gana y aun así se cruza el umbral
    assert stressed.loc[[300, 600], "first_breach_utc"].isna().all()


def test_okx_registra_errores(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "51001", "msg": "Instrument ID does not exist", "data": []}
    monkeypatch.setattr("quantlab.p07.derivatives.requests.get", lambda *a, **k: Response())
    with pytest.raises(RuntimeError, match="51001"):
        okx_get("/api/v5/public/funding-rate", {"instId": "X"})


@pytest.mark.live
def test_okx_en_vivo():
    rows, hist, _ = okx_snapshot(history=3)
    assert len(rows) == 10 and len(hist) == 3
