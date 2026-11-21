import pandas as pd
import pytest

from radar.mercado import Cotizacion, CotizacionInvalida

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
T1 = T0 + pd.Timedelta(milliseconds=250)


def cot(bid="60000", ask="60004", cb="0.5", ca="0.3", **kw):
    return Cotizacion("kraken", "BTC/EUR", bid, ask, cb, ca, kw.get("sol", T0), kw.get("rec", T1))


def test_calculos_de_la_cotizacion():
    c = cot()
    assert c.bid == 60000.0 and isinstance(c.bid, float)  # el texto de la API se convierte a número
    assert c.mid == 60002 and c.spread_eur == 4 and c.spread_bps == pytest.approx(4 / 60002 * 1e4)
    assert c.latencia_s == pytest.approx(0.25)


def test_spread_redondeado_a_centimos():
    assert cot("53666.1", "53666.4").spread_eur == 0.3  # sin el resto de coma flotante 0.30000000000291


@pytest.mark.parametrize("campos, mensaje", [
    ({"bid": "60004", "ask": "60000"}, "libro cruzado"),
    ({"bid": "60000", "ask": "60000"}, "libro cruzado"),
    ({"bid": "0"}, "bid no es un número positivo"),
    ({"ca": "-1"}, "cantidad_ask no es un número positivo"),
    ({"bid": "nan"}, "bid no es un número positivo"),
])
def test_cotizaciones_imposibles(campos, mensaje):
    with pytest.raises(CotizacionInvalida, match=mensaje):
        cot(**campos)


def test_recibida_antes_de_solicitar():
    with pytest.raises(CotizacionInvalida, match="antes de solicitarla"):
        cot(sol=T1, rec=T0)


def test_inmutable_y_fila_para_el_almacen():
    c = cot()
    with pytest.raises(Exception):
        c.bid = 1
    fila = c.a_fila()
    assert list(fila) == ["exchange", "par", "solicitado_utc", "recibido_utc", "latencia_s", "hora_exchange_utc",
                          "bid", "ask", "cantidad_bid", "cantidad_ask", "mid", "spread_eur", "spread_bps"]
