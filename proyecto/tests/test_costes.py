import pandas as pd
import pytest

from radar.mercado import Libro, Nivel, comparar_costes, coste_ida_y_vuelta

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
T1 = T0 + pd.Timedelta(milliseconds=250)


def libro(bids, asks, exchange="kraken"):
    return Libro(exchange, "BTC/EUR", tuple(Nivel(p, c) for p, c in bids), tuple(Nivel(p, c) for p, c in asks), T0, T1)


def test_coste_con_un_nivel_coincide_con_la_fase_1():
    k = coste_ida_y_vuelta(libro([(60000, 1)], [(60004, 1)]), 1000, 0.008)
    venta = 1000 / 60004 * 60000
    assert k.coste_spread_eur == pytest.approx(1000 - venta) and k.slippage_eur == pytest.approx(0)
    assert k.comisiones_eur == pytest.approx((1000 + venta) * 0.008) and k.completa
    assert k.coste_total_eur == pytest.approx(k.coste_spread_eur + k.comisiones_eur)


def test_coste_con_slippage_en_las_dos_patas():
    k = coste_ida_y_vuelta(libro([(60000, 0.01), (59990, 1)], [(60004, 0.01), (60010, 1)]), 1500, 0.001)
    cantidad = 0.01 + 899.96 / 60010                  # compra: barre dos asks
    venta = 0.01 * 60000 + (cantidad - 0.01) * 59990  # venta: barre dos bids
    assert k.cantidad_btc == pytest.approx(cantidad) and k.venta.importe_eur == pytest.approx(venta)
    assert k.coste_spread_eur == pytest.approx(cantidad * 4)                       # mejor ask − mejor bid
    assert k.slippage_eur == pytest.approx(k.compra.slippage_eur + k.venta.slippage_eur) and k.slippage_eur > 0
    assert k.comisiones_eur == pytest.approx((1500 + venta) * 0.001)
    # Lo que se pierde de verdad = lo pagado − lo cobrado + comisiones, y se reparte en las tres piezas.
    assert k.coste_total_eur == pytest.approx(1500 - venta + k.comisiones_eur)
    assert k.coste_total_eur == pytest.approx(k.coste_spread_eur + k.slippage_eur + k.comisiones_eur)


def test_punto_de_equilibrio():
    un_nivel = libro([(60000, 1)], [(60000.01, 1)])
    assert coste_ida_y_vuelta(un_nivel, 1000, 0.008).punto_equilibrio_pct == pytest.approx(1.6129, abs=1e-3)
    assert coste_ida_y_vuelta(un_nivel, 1000, 0.001).punto_equilibrio_pct == pytest.approx(0.2002, abs=1e-3)
    sin_comision = coste_ida_y_vuelta(libro([(60000, 1)], [(60004, 1)]), 1000, 0)
    assert sin_comision.punto_equilibrio_pct == pytest.approx(4 / 60000 * 100)    # solo el spread
    k = coste_ida_y_vuelta(libro([(60000, 0.01), (59990, 1)], [(60004, 0.01), (60010, 1)]), 1500, 0.001)
    medio = k.compra.precio_medio * 1.001 / 0.999 / k.venta.precio_medio - 1     # con precios medios de ejecución
    assert k.punto_equilibrio_pct == pytest.approx(medio * 100)


def test_coste_incompleto_si_el_libro_capturado_no_alcanza():
    k = coste_ida_y_vuelta(libro([(60000, 0.01)], [(60004, 0.01)]), 1000, 0.001)
    assert not k.completa and k.compra.importe_eur == pytest.approx(600.04)
    with pytest.raises(ValueError):
        coste_ida_y_vuelta(libro([(60000, 1)], [(60004, 1)]), 0, 0.001)


COMISIONES = {"kraken": 0.008, "okx": 0.001, "bitvavo": 0.0025}
LIBROS = [libro([(60000, 1)], [(60000.1, 1)], "kraken"),
          libro([(60000, 0.001), (59999, 1)], [(60005, 0.001), (60006, 1)], "okx"),  # poco en el mejor nivel
          libro([(60000, 1)], [(60001, 1)], "bitvavo")]


def test_comparacion_cuenta_el_slippage_en_vez_de_descartar():
    c = comparar_costes(LIBROS, 1000, COMISIONES)
    assert c.mas_barato_por_comision.exchange == "okx" and c.incompletos == []
    assert c.mas_barato_ejecutable.exchange == "okx"  # en la Fase 1 se descartaba por "falta de profundidad"
    frases = c.conclusiones()
    assert frases[0] == "Más barato por comisión: okx (0.10% por pata)."
    assert frases[1].startswith("Más barato ejecutable con 1.000 €: okx, coste total 2.")
    assert "slippage 0.0" in frases[1] and "punto de equilibrio" in frases[1]
    filas = {f["exchange"]: f for f in c.a_filas()}
    assert filas["okx"]["es_mas_barato_ejecutable"] and filas["okx"]["niveles_compra"] == 2
    assert filas["okx"]["slippage_eur"] > 0 and filas["kraken"]["slippage_eur"] == pytest.approx(0)
    resumen = c.a_conclusion()
    assert resumen["mas_barato_ejecutable"] == "okx" and resumen["incompletos"] == ""
    assert resumen["texto"] == " ".join(frases)


def test_comparacion_con_libros_insuficientes_y_errores():
    c = comparar_costes([libro([(60000, 0.001)], [(60001, 0.001)])], 1000, COMISIONES)
    assert c.mas_barato_ejecutable is None and c.incompletos == ["kraken"]
    frases = c.conclusiones()
    assert "Ningún exchange" in frases[1]
    assert frases[2] == "kraken: el libro capturado solo alcanza para 60.00 € de los 1.000 €."
    with pytest.raises(ValueError, match="Falta la comisión"):
        comparar_costes([libro([(60000, 1)], [(60001, 1)], "binance")], 1000, COMISIONES)
    with pytest.raises(ValueError, match="al menos un"):
        comparar_costes([], 1000, COMISIONES)
