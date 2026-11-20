"""P06 · Comparación entre exchanges: adaptadores, validación, alineación, lead-lag, arbitraje y ejercicios."""
import numpy as np
import pandas as pd
import pytest

from quantlab.p06.cross_exchange import (
    EXCHANGES,
    align_quotes,
    capture_report,
    collect_live,
    delay_receipt,
    episodes,
    fee_sensitivity,
    fresh_returns,
    lag_profile,
    leadlag_summary,
    manual_cross_correlation,
    mid_and_spread,
    parse_quote,
    route_summary,
    scan_pair,
    scan_routes,
    size_comparison,
    synthetic_quotes,
    validate_quotes,
)

FEES = {e: 10.0 for e in EXCHANGES}


@pytest.fixture(scope="module")
def raw():
    return synthetic_quotes()


@pytest.fixture(scope="module")
def aligned(raw):
    return align_quotes(validate_quotes(raw))


@pytest.fixture(scope="module")
def returns(aligned):
    return fresh_returns(aligned)


@pytest.fixture(scope="module")
def scans(aligned):
    return scan_routes(aligned, .01, FEES)


# --- Adaptadores -----------------------------------------------------------------

def test_adaptadores_con_respuestas_ficticias():
    k = parse_quote("kraken", {"error": [], "result": {"X": {"b": ["99", "0", "0.2"], "a": ["100", "0", "0.3"]}}})
    o = parse_quote("okx", {"code": "0", "data": [{"instId": "BTC-EUR", "bidPx": "101", "askPx": "102",
                                                  "bidSz": "0.4", "askSz": "0.5", "ts": "1735689600000"}]})
    b = parse_quote("bitvavo", {"market": "BTC-EUR", "bid": "99", "ask": "100", "bidSize": "0.2", "askSize": "0.3"})
    assert k["bid_size"] == .2 and k["ask"] == 100
    assert o["bid"] == 101 and o["ask_size"] == .5 and o["exchange_at"] == pd.Timestamp("2025-01-01", tz="UTC")
    assert b["bid"] == 99 and b["ask_size"] == .3 and pd.isna(b["exchange_at"])


def test_kraken_lee_el_libro_depth():
    payload = {"error": [], "result": {"XXBTZEUR": {"asks": [["56674.0", "0.273", 1795119693]],
                                                     "bids": [["56673.9", "0.006", 1795119683]]}}}
    q = parse_quote("kraken", payload)
    assert (q["bid"], q["ask"], q["bid_size"], q["ask_size"]) == (56673.9, 56674.0, .006, .273)
    assert pd.isna(q["exchange_at"])  # el timestamp de un nivel no es el instante de la cotización


@pytest.mark.parametrize("exchange, payload, message", [
    ("kraken", {"error": ["EQuery:Unknown asset pair"], "result": {}}, "Unknown"),
    ("okx", {"code": "51001", "msg": "Instrument ID does not exist", "data": []}, "Instrument"),
    ("okx", {"code": "0", "data": [{"instId": "BTC-USDT", "bidPx": "1", "askPx": "1", "bidSz": "1",
                                    "askSz": "1", "ts": "0"}]}, "Par incorrecto"),
    ("bitvavo", {"market": "BTC-USDC", "bid": "1", "ask": "1", "bidSize": "1", "askSize": "1"}, "Par incorrecto"),
    ("binance", {}, "binance"),
])
def test_adaptadores_rechazan_errores_y_otros_pares(exchange, payload, message):
    with pytest.raises(ValueError, match=message):
        parse_quote(exchange, payload)


def test_captura_en_vivo_registra_errores(monkeypatch):
    def failing(exchange, okx_base):
        if exchange == "okx":
            raise RuntimeError("región no disponible")
        return {"exchange": exchange}
    monkeypatch.setattr("quantlab.p06.cross_exchange.fetch_quote", failing)
    monkeypatch.setattr("quantlab.p06.cross_exchange.time.sleep", lambda s: None)
    rows, errors = collect_live(2)
    assert len(rows) == 4 and list(errors.exchange) == ["okx", "okx"]
    assert errors.error.str.contains("región").all()


# --- Validación --------------------------------------------------------------------

def test_validacion_anade_mid_spread_y_rtt(raw):
    q = validate_quotes(raw)
    first = q.iloc[0]
    assert np.isclose(first.mid, (first.bid + first.ask) / 2)
    assert np.isclose(first.rtt_ms, 80)
    assert q.received_at.is_monotonic_increasing


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.drop(columns="ask_size"), "Faltan columnas"),
    (lambda d: d[d.exchange != "okx"], "tres exchanges"),
    (lambda d: d.assign(symbol="BTC/USDT"), "único par"),
    (lambda d: d.assign(ask=d.bid - 1), "inválida"),
    (lambda d: d.assign(bid_size=0.0), "inválida"),
    (lambda d: pd.concat([d, d.iloc[[0]]]), "duplicada"),
    (lambda d: d.assign(request_at=d.received_at + pd.Timedelta("1s")), "inconsistentes"),
])
def test_validacion_rechaza_datos_invalidos(raw, mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_quotes(mutate(raw.copy()))


# --- Alineación causal y retornos ------------------------------------------------------

def test_alineacion_nunca_usa_datos_futuros(aligned):
    for e in EXCHANGES:
        a = aligned[e]
        known = a.received_at.notna()
        assert (a.loc[known, "received_at"] <= a.index[known]).all()
        assert a.loc[known, "age_ms"].le(2000).all()
        assert a.loc[~a.valid, "mid"].isna().all()


def test_alineacion_descarta_eventos_antiguos():
    when = pd.Timestamp("2025-01-01T00:00:00.500Z")
    rows = [dict(exchange=e, symbol="BTC/EUR", received_at=when + pd.Timedelta(seconds=s), bid=99., ask=101.,
                 bid_size=1., ask_size=1., exchange_at=when + pd.Timedelta(seconds=s) - pd.Timedelta(seconds=lag))
            for e, lag in [("kraken", 0), ("okx", 3), ("bitvavo", 0)] for s in range(3)]
    aligned = align_quotes(validate_quotes(pd.DataFrame(rows)))
    assert aligned["kraken"].valid.all() and not aligned["okx"].valid.any()


def test_retornos_solo_entre_cotizaciones_nuevas():
    idx = pd.date_range("2025-01-01", periods=4, freq="1s", tz="UTC")
    received = pd.Series([idx[0], idx[1], idx[1], idx[3]], index=idx)  # el segundo 2 arrastra el 1
    cols = {}
    for e in EXCHANGES:
        cols[(e, "mid")] = pd.Series([100., 101., 101., 102.], index=idx)
        cols[(e, "received_at")] = received
    r = fresh_returns(pd.DataFrame(cols))
    assert np.isclose(r.kraken.iloc[1], np.log(101 / 100))
    assert r.kraken.iloc[[0, 2, 3]].isna().all()


def test_correlacion_simultanea_casi_nula_por_los_retrasos(returns):
    corr = returns.corr(min_periods=20)
    assert abs(corr.loc["kraken", "okx"]) < .1 and abs(corr.loc["kraken", "bitvavo"]) < .1


# --- Lead-lag ------------------------------------------------------------------------------

def test_lead_lag_recupera_los_retrasos_introducidos(returns):
    summary, _ = leadlag_summary(returns)
    s = summary.set_index("target")
    assert s.loc["okx", "lag_s"] == 2 and s.loc["bitvavo", "lag_s"] == 1


def test_spearman_es_robusto_a_los_desajustes_extremos(returns):
    pearson, _ = leadlag_summary(returns)
    spearman, _ = leadlag_summary(returns, method="spearman")
    p, s = pearson.set_index("target"), spearman.set_index("target")
    assert p.loc["okx", "dev_corr"] < .5 and s.loc["okx", "dev_corr"] > .9
    assert p.loc["bitvavo", "test_corr"] < .5 and s.loc["bitvavo", "test_corr"] > .9


def test_perfil_exige_un_minimo_de_pares():
    x = pd.Series(np.arange(10, dtype=float))
    assert lag_profile(x, x, 2)["corr"].isna().all()


# --- Arbitraje ---------------------------------------------------------------------------------

def test_aritmetica_de_costes():
    idx = pd.DatetimeIndex([pd.Timestamp("2025-01-01", tz="UTC")])
    t = idx[0]

    def block(bid, ask):
        return {"bid": bid, "ask": ask, "bid_size": 1., "ask_size": 1., "received_at": t, "valid": True}
    aligned = pd.concat({"A": pd.DataFrame([block(59990, 60000)], index=idx),
                         "B": pd.DataFrame([block(60150, 60160)], index=idx)}, axis=1)
    out = scan_pair(aligned, "A", "B", 1.0, {"A": 10, "B": 10}, extra_bps=0)
    assert np.isclose(out.net_eur.iloc[0], 60150 * (1 - .001) - 60000 * (1 + .001))  # 29,85 €
    assert out.candidate.iloc[0]
    small = scan_pair(aligned, "A", "B", 2.0, {"A": 10, "B": 10}, extra_bps=0)
    assert not small.eligible.iloc[0] and pd.isna(small.net_eur.iloc[0])


def test_rutas_candidatos_y_episodios(scans):
    for d in scans.values():
        assert d.loc[~d.eligible, "net_eur"].isna().all()
        assert d.loc[d.candidate, "net_eur"].gt(0).all()
    table = route_summary(scans)
    assert len(table) == 6 and table.candidate_seconds.sum() == 16
    eps = episodes(scans)
    assert len(eps) == 6 and eps.observed_seconds.sum() == 16


def test_sensibilidad_a_comisiones(aligned):
    table = fee_sensitivity(aligned, .01)
    assert table.candidate_route_seconds.is_monotonic_decreasing
    assert list(table.candidate_route_seconds) == [45, 16, 16, 0, 0]


# --- Ejercicios E1–E6 ------------------------------------------------------------------------------

def test_e1_mid_y_spread():
    mid, spread = mid_and_spread(59990, 60010)
    assert mid == 60000 and np.isclose(spread, 10 / 3)
    q = validate_quotes(pd.DataFrame([dict(exchange=e, symbol="BTC/EUR", received_at="2025-01-01T00:00:00Z",
                                           bid=59990, ask=60010, bid_size=1, ask_size=1) for e in EXCHANGES]))
    assert np.allclose(q.mid, mid) and np.allclose(q.spread_bps, spread)
    with pytest.raises(ValueError):
        mid_and_spread(60010, 59990)


def test_e2_correlacion_cruzada_manual(returns):
    cut = int(len(returns) * .65)
    dev = returns.iloc[:cut]
    manual = manual_cross_correlation(dev.kraken, dev.okx, 5)
    assert manual.idxmax() == 2
    assert np.allclose(manual.dropna(), lag_profile(dev.kraken, dev.okx, 5)["corr"].dropna())


def test_e3_mas_tamano_nunca_mas_candidatos(aligned):
    table = size_comparison(aligned, (.01, .05, .1))
    assert table.candidate_route_seconds.is_monotonic_decreasing
    assert table.eligible_route_seconds.is_monotonic_decreasing


def test_e5_retrasar_la_recepcion_cambia_el_lag(raw):
    delayed = delay_receipt(raw, "bitvavo", pd.Timedelta(seconds=1))
    assert (pd.to_datetime(delayed.exchange_at, utc=True) == pd.to_datetime(raw.exchange_at, utc=True)).all()
    assert (delayed.bid == raw.bid).all()
    summary, _ = leadlag_summary(fresh_returns(align_quotes(validate_quotes(delayed))))
    assert summary.set_index("target").loc["bitvavo", "lag_s"] == 2


def test_e6_informe_de_captura(raw, aligned, scans):
    q = validate_quotes(raw)
    errors = pd.DataFrame([(0, "okx", "timeout")], columns=["round", "exchange", "error"])
    report = capture_report(q, errors, aligned, scans)
    assert report.loc["okx", "errors"] == 1 and report.loc["kraken", "errors"] == 0
    assert report.coverage_pct.between(0, 100).all()
    assert np.isclose(report.loc["kraken", "rtt_ms_median"], 80)


@pytest.mark.live
def test_cotizaciones_en_vivo():
    rows, errors = collect_live(2)
    assert len(rows) + len(errors) == 6
