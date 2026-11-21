import pandas as pd
import pytest

from radar.mercado import CotizacionInvalida, Libro, Nivel, barrer_compra, barrer_venta

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
T1 = T0 + pd.Timedelta(milliseconds=250)


def libro(bids=((60000, 0.01), (59990, 0.02), (59950, 1)), asks=((60004, 0.01), (60010, 0.02), (60050, 1))):
    return Libro("okx", "BTC/EUR", tuple(Nivel(p, c) for p, c in bids), tuple(Nivel(p, c) for p, c in asks), T0, T1)


def test_mejor_nivel_es_la_cotizacion_de_la_fase_1():
    cot = libro().mejor_nivel()
    assert (cot.bid, cot.ask, cot.cantidad_bid, cot.cantidad_ask) == (60000, 60004, 0.01, 0.01)
    assert cot.exchange == "okx" and cot.recibido_utc == T1


@pytest.mark.parametrize("bids, asks, mensaje", [
    ((), ((60004, 1),), "lado vacío"),
    (((60000, 1), (60001, 1)), ((60004, 1),), "bids deben bajar"),
    (((60000, 1),), ((60004, 1), (60004, 1)), "asks deben subir"),
    (((60005, 1),), ((60004, 1),), "libro cruzado"),
    (((60000, 0),), ((60004, 1),), "no es un número positivo"),
])
def test_libros_imposibles(bids, asks, mensaje):
    with pytest.raises(CotizacionInvalida, match=mensaje):
        libro(bids, asks)


def test_compra_que_cabe_en_el_mejor_nivel_no_tiene_slippage():
    e = barrer_compra(libro(), 300)
    assert e.precio_medio == pytest.approx(60004) and e.niveles_usados == 1 and e.completa
    assert e.cantidad_btc == pytest.approx(300 / 60004) and e.slippage_eur == pytest.approx(0)


def test_compra_que_barre_dos_niveles():
    e = barrer_compra(libro(), 1500)
    # Nivel 1: 0,01 BTC · 60.004 = 600,04 €. Quedan 899,96 € para el nivel 2, a 60.010.
    cantidad = 0.01 + 899.96 / 60010
    assert e.cantidad_btc == pytest.approx(cantidad) and e.importe_eur == pytest.approx(1500)
    assert e.niveles_usados == 2 and e.completa
    assert e.precio_medio == pytest.approx(1500 / cantidad)            # ≈ 60.007,6: peor que el mejor ask
    assert e.slippage_eur == pytest.approx(1500 - cantidad * 60004)    # lo pagado de más frente al mejor ask
    assert e.slippage_bps == pytest.approx((1500 / cantidad / 60004 - 1) * 1e4)


def test_compra_mas_grande_que_el_libro_queda_incompleta():
    e = barrer_compra(libro(), 1_000_000)
    assert not e.completa and e.niveles_usados == 3
    assert e.cantidad_btc == pytest.approx(1.03)                      # todo lo que había, ni un satoshi inventado
    assert e.importe_eur == pytest.approx(0.01 * 60004 + 0.02 * 60010 + 1 * 60050)


def test_venta_barre_los_bids_hacia_abajo():
    e = barrer_venta(libro(), 0.02)
    # 0,01 BTC a 60.000 y 0,01 a 59.990.
    assert e.importe_eur == pytest.approx(0.01 * 60000 + 0.01 * 59990) and e.niveles_usados == 2
    assert e.precio_medio == pytest.approx(59995) and e.completa
    assert e.slippage_eur == pytest.approx(0.02 * 60000 - e.importe_eur)  # lo cobrado de menos frente al mejor bid


def test_barrido_rechaza_cantidades_no_positivas():
    with pytest.raises(ValueError):
        barrer_compra(libro(), 0)
    with pytest.raises(ValueError):
        barrer_venta(libro(), -1)
