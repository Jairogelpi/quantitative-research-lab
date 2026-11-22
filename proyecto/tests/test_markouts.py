import pandas as pd
import pytest

from radar.analisis.markouts import colocaciones, llenado_limit, markouts_trades
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def libros(segundos=120, mid=lambda s: 100.0, bids=10, asks=10):
    """Un libro por segundo: bid mid − 0,5 y ask mid + 0,5 (a 50 bps), y otro nivel a 50 € (banda de 100 bps cubierta)."""
    filas = []
    for s in range(segundos):
        t, m = T0 + pd.Timedelta(seconds=s), mid(s)
        filas.append(Libro("kraken", "BTC/EUR", (Nivel(m - 0.5, bids), Nivel(m - 50, 1)),
                           (Nivel(m + 0.5, asks), Nivel(m + 50, 1)), t, t).a_fila(2))
    return pd.DataFrame(filas)


def trades(*filas):
    return pd.DataFrame([{"exchange": "kraken", "recibido_utc": T0 + pd.Timedelta(seconds=s), "precio": p,
                          "cantidad": 0.1, "lado_agresor": lado} for s, p, lado in filas],
                        columns=["exchange", "recibido_utc", "precio", "cantidad", "lado_agresor"])


def test_markout_desde_el_taker():
    sube = libros(mid=lambda s: 100.0 + s * 0.01)
    tr = trades(*[(s, 100.5 + s * 0.01, "buy") for s in range(0, 100, 1)])
    (uno, *_), = [markouts_trades(sube, tr, horizontes=(1, 5), minimo=50)]
    # El comprador pagó el ask (mid + 0,5) y un segundo después el mid subió 0,01: perdió casi medio spread.
    assert uno.horizonte_s == 1 and uno.n == 100
    esperado = sum(((100 + (s + 1) * 0.01) / (100.5 + s * 0.01) - 1) * 1e4 for s in range(100)) / 100
    assert uno.media_bps == pytest.approx(esperado)
    assert uno.estado == "los takers pierden" and "100 trades" in uno.conclusion()
    pocos = markouts_trades(sube, tr.head(10), horizontes=(1,), minimo=50)[0]
    assert pocos.estado == "datos insuficientes"


def test_trades_del_mismo_segundo_cuentan_una_vez():
    tr = trades((5, 100.5, "buy"), (5.2, 100.5, "buy"), (5.4, 100.5, "buy"))
    (m,) = markouts_trades(libros(), tr, horizontes=(1,), minimo=1)
    assert m.n == 1


def test_llenado_seguro_posible_y_no():
    lb = libros(segundos=60)  # colocación cada 10 s: en 0, 10, ..., 50; compra a 99,5 y venta a 100,5
    tr = trades((2, 99.4, "sell"),     # pasa por debajo de nuestro bid: la compra del segundo 0 se llena seguro
                (12, 99.5, "sell"),    # justo a nuestro precio: depende de la cola
                (22, 100.0, "buy"))    # un comprador a 100: no llega a nuestra venta a 100,5
    r = {(x.espera_s, x.imbalance): x for x in llenado_limit(lb, tr, esperas=(5,), minimo=1)}
    todos = r[(5, "todos")]
    assert todos.colocadas == 12 and todos.llenadas_seguro == 1 and todos.llenadas_posible == 1
    assert todos.tasa_seguro == pytest.approx(1 / 12) and todos.tasa_posible == pytest.approx(2 / 12)
    # Llenada a 99,5 con mid 100 treinta segundos después: +50 bps para el comprador.
    assert todos.markout_llenadas_bps == pytest.approx((100 / 99.5 - 1) * 1e4)
    assert "se llenan con seguridad el 8.3%" in todos.conclusion()


def test_imbalance_a_favor_y_en_contra():
    # Muchos bids: imbalance positivo. Para la compra va en contra; para la venta, a favor.
    o = colocaciones(libros(segundos=20, bids=30, asks=10), banda_bps=100)
    compra, venta = o[o.lado > 0].iloc[0], o[o.lado < 0].iloc[0]
    assert compra.favor == -1 and venta.favor == 1 and compra.precio == 99.5 and venta.precio == 100.5
    tr = trades((3, 100.6, "buy"))  # un comprador agresivo pasa por encima de nuestra venta
    r = {(x.espera_s, x.imbalance): x
         for x in llenado_limit(libros(20, bids=30, asks=10), tr, esperas=(5,), minimo=1, banda_bps=100)}
    assert r[(5, "a favor")].llenadas_seguro == 1 and r[(5, "en contra")].llenadas_seguro == 0
