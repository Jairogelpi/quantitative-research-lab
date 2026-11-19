import numpy as np
import pytest

from quantlab.p02.orderbook import (
    EXAMPLE_BOOK,
    book_features,
    depth_within_bps,
    fetch_kraken_book,
    normalize_book,
    simulate_market_order,
)


@pytest.fixture
def book():
    return normalize_book(EXAMPLE_BOOK)


# --- Las 9 comprobaciones del cuaderno P02 ---------------------------------

def test_features_del_ejemplo(book):
    f = book_features(*book, 5)
    assert np.isclose(f["mid_price"], 60_000)
    assert np.isclose(f["bid_depth_btc"], 4.7)
    assert np.isclose(f["ask_depth_btc"], 3.5)
    assert np.isclose(f["order_book_imbalance"], 1.2 / 8.2)
    assert np.isclose(f["microprice"], 60_000 + 2 / 3)


def test_compra_05_btc(book):
    r, fills = simulate_market_order(*book, "buy", 0.5)
    assert r["complete"] and np.isclose(r["execution_price"], 60_005.4)
    assert np.isclose(r["slippage_bps"], (60_005.4 / 60_002 - 1) * 10_000)
    assert list(fills.filled_btc) == pytest.approx([0.1, 0.3, 0.1])


def test_compra_que_agota_el_libro(book):
    r, _ = simulate_market_order(*book, "buy", 4)
    assert not r["complete"] and np.isclose(r["filled_btc"], 3.5) and np.isclose(r["unfilled_btc"], 0.5)


def test_venta_al_mejor_bid(book):
    r, _ = simulate_market_order(*book, "sell", 0.1)
    assert r["complete"] and np.isclose(r["execution_price"], 59_998) and np.isclose(r["slippage_bps"], 0)


# --- E1: OBI por niveles ----------------------------------------------------

def test_obi_cambia_de_signo_con_n(book):
    obi = {n: book_features(*book, n)["order_book_imbalance"] for n in (1, 3, 5)}
    assert obi[1] == pytest.approx((0.2 - 0.1) / 0.3)    # +0,333
    assert obi[3] == pytest.approx((1.5 - 1.0) / 2.5)    # +0,200
    assert obi[5] == pytest.approx(1.2 / 8.2)            # +0,146
    # Libro donde el signo cambia: más cantidad al mejor bid, pero más asks detrás
    b, a = normalize_book({"bids": [[99, 2], [98, 0.1]], "asks": [[101, 1], [102, 5]]})
    assert book_features(b, a, 1)["order_book_imbalance"] > 0
    assert book_features(b, a, 2)["order_book_imbalance"] < 0


def test_niveles_no_disponibles(book):
    with pytest.raises(ValueError):
        book_features(*book, 6)


# --- E2/E3: tamaño y slippage -----------------------------------------------

@pytest.mark.parametrize("side", ["buy", "sell"])
def test_slippage_no_decrece_con_el_tamano(book, side):
    s = [simulate_market_order(*book, side, q)[0]["slippage_bps"] for q in (0.05, 0.5, 2)]
    assert s == sorted(s)


def test_costes_asimetricos(book):
    buy, _ = simulate_market_order(*book, "buy", 2)
    sell, _ = simulate_market_order(*book, "sell", 2)
    assert buy["slippage_bps"] > sell["slippage_bps"]  # menos profundidad en el lado ask


# --- E4: profundidad en banda -----------------------------------------------

def test_profundidad_5_bps(book):
    d = depth_within_bps(*book, 5)   # mid 60.000 -> [59.970, 60.030]
    assert d["bid_depth_btc"] == pytest.approx(0.2 + 0.5 + 0.8 + 1.2)
    assert d["ask_depth_btc"] == pytest.approx(0.1 + 0.3 + 0.6 + 1.0)
    assert d["complete_bid"] and d["complete_ask"]


def test_ampliar_banda_no_reduce_profundidad(book):
    bands = [0, 0.5, 1, 2, 5, 10, 50]
    for side in ("bid_depth_btc", "ask_depth_btc"):
        depths = [depth_within_bps(*book, b)[side] for b in bands]
        assert depths == sorted(depths)


def test_banda_que_cubre_todo_el_snapshot_es_incompleta(book):
    d = depth_within_bps(*book, 100)
    assert d["bid_depth_btc"] == pytest.approx(4.7) and not d["complete_bid"]


# --- Validación ----------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    {"bids": [], "asks": [[1, 1]]},                       # lado vacío
    {"bids": [[100, 1]], "asks": [[99, 1]]},              # libro cruzado
    {"bids": [[100, 1]], "asks": [[100, 1]]},             # libro bloqueado
    {"bids": [[100, -1]], "asks": [[101, 1]]},            # cantidad negativa
    {"bids": [[100, 1], [100, 2]], "asks": [[101, 1]]},   # nivel duplicado
])
def test_libros_invalidos(raw):
    with pytest.raises(ValueError):
        normalize_book(raw)


@pytest.mark.parametrize("side, qty", [("hold", 1), ("buy", 0), ("buy", float("nan"))])
def test_ordenes_invalidas(book, side, qty):
    with pytest.raises(ValueError):
        simulate_market_order(*book, side, qty)


@pytest.mark.live
def test_libro_kraken_en_vivo():
    raw, received_at = fetch_kraken_book(levels=10)
    bids, asks = normalize_book(raw)
    assert len(bids) == len(asks) == 10 and received_at
