import pytest

from quantlab.p01.quotes import (
    SYNTHETIC_QUOTE,
    fetch_kraken_ticker,
    quote_metrics,
    round_trip_cost,
    validate_quote,
)

BID, ASK, LAST = SYNTHETIC_QUOTE["best_bid"], SYNTHETIC_QUOTE["best_ask"], SYNTHETIC_QUOTE["last_price"]


# --- Métricas con el ejemplo ficticio (P01) ---------------------------------

def test_mid_y_spread_del_ejemplo():
    m = quote_metrics(BID, ASK, LAST)
    assert m["mid_price"] == 60_000.0
    assert m["spread"] == 4.0


def test_spread_relativo_y_bps():
    m = quote_metrics(BID, ASK, LAST)
    assert m["relative_spread"] == pytest.approx(4 / 60_000)
    assert m["spread_bps"] == pytest.approx(0.6667, abs=1e-4)


def test_desviacion_del_ultimo_precio():
    m = quote_metrics(BID, ASK, LAST)
    assert m["last_price_deviation"] == -1.0
    assert m["last_price_deviation_bps"] == pytest.approx(-1 / 60_000 * 10_000)


def test_coste_ida_y_vuelta_001_btc():
    assert round_trip_cost(BID, ASK, 0.01) == pytest.approx(0.04)


def test_coste_ida_y_vuelta_es_cantidad_por_spread():
    assert round_trip_cost(100.0, 101.5, 3) == pytest.approx(3 * 1.5)


def test_libro_bloqueado_se_rechaza():
    # bid == ask: libro bloqueado, misma regla que P02 (normalize_book)
    with pytest.raises(ValueError):
        quote_metrics(100.0, 100.0, 100.0)
    with pytest.raises(ValueError):
        round_trip_cost(100.0, 100.0, 1)


# --- Validación ---------------------------------------------------------------

def test_cotizacion_valida_no_lanza():
    validate_quote(BID, ASK, LAST)


@pytest.mark.parametrize(
    "bid, ask, last",
    [
        (0.0, 1.0, 1.0),      # bid = 0
        (-5.0, 1.0, 1.0),     # bid negativo
        (101.0, 100.0, 100),  # libro cruzado
        (100.0, 101.0, 0.0),  # last = 0
        (float("nan"), float("nan"), float("nan")),  # NaN
        (100.0, float("nan"), 100.0),  # ask ausente
        (100.0, float("inf"), 100.0),  # ask infinito
        (100.0, 101.0, float("nan")),  # last NaN
    ],
)
def test_cotizaciones_invalidas(bid, ask, last):
    with pytest.raises(ValueError):
        quote_metrics(bid, ask, last)


def test_cantidad_no_valida():
    with pytest.raises(ValueError):
        round_trip_cost(BID, ASK, 0)


# --- Modo en vivo (requiere Internet): pytest -m live --------------------------

@pytest.mark.live
def test_kraken_quote_con_volumen_real():
    from quantlab.p01.quotes import fetch_kraken_quote
    q = fetch_kraken_quote()
    assert q["best_ask"] >= q["best_bid"] > 0
    assert q["best_bid_volume"] > 0 and q["best_ask_volume"] > 0


@pytest.mark.live
def test_kraken_en_vivo():
    q = fetch_kraken_ticker()
    assert q["source"] == "kraken_public_ticker"
    assert q["best_ask"] >= q["best_bid"] > 0
    assert quote_metrics(q["best_bid"], q["best_ask"], q["last_price"])["spread_bps"] >= 0
