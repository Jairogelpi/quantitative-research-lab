import pandas as pd
import pytest

from radar.mercado import Libro, Nivel, desequilibrio

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
T1 = T0 + pd.Timedelta(milliseconds=250)

# Mid = 60.002. Con 5 bps, la banda llega hasta ±30 € del mid: 59.972 – 60.032.
LIBRO = Libro("kraken", "BTC/EUR", (Nivel(60000, 1), Nivel(59990, 2), Nivel(59900, 5)),
              (Nivel(60004, 3), Nivel(60010, 1), Nivel(60200, 5)), T0, T1)


def test_imbalance_dentro_de_la_banda():
    d = desequilibrio(LIBRO, 5)
    assert (d.cantidad_bids, d.cantidad_asks) == (3, 4)  # 59.900 y 60.200 quedan fuera de la banda
    assert d.cubierta and d.imbalance == pytest.approx((3 - 4) / (3 + 4))  # algo más de vendedores


def test_banda_mas_ancha_que_el_libro_capturado_no_inventa():
    d = desequilibrio(LIBRO, 50)  # ±300 €: el último bid capturado (59.900) está dentro de la banda
    assert not d.cubierta and d.imbalance is None


def test_banda_sin_cantidad_y_banda_invalida():
    d = desequilibrio(LIBRO, 0.1)  # ±0,60 €: más estrecha que medio spread, no entra ningún nivel
    assert d.cubierta and (d.cantidad_bids, d.cantidad_asks) == (0, 0) and d.imbalance is None
    with pytest.raises(ValueError):
        desequilibrio(LIBRO, 0)


def test_a_fila_para_el_almacen():
    fila = desequilibrio(LIBRO, 5).a_fila()
    assert fila == {"banda_bps": 5, "cantidad_bids": 3, "cantidad_asks": 4, "cubierta": True,
                    "imbalance": pytest.approx(-1 / 7)}
