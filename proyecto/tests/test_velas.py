import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.velas import (COLUMNAS_VELA, FUENTE_PROPIA, FUENTE_VELAS, actualizar_velas, construir_velas,
                                  cobertura_desde_latidos, leer_velas, quitar_errores)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def s(segundos: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=segundos)


def trades_ejemplo(exchange="kraken"):
    filas = [(5, 100.0, 1.0, "a"), (20, 105.0, 0.5, "b"), (40, 98.0, 0.25, "c"), (59.9, 104.0, 0.25, "d"),
             (130, 101.0, 1.0, "e")]
    return pd.DataFrame([{"exchange": exchange, "hora_exchange_utc": s(t), "recibido_utc": s(t + 0.3), "precio": p,
                          "cantidad": q, "lado_agresor": "compra", "trade_id": i} for t, p, q, i in filas])


def latidos(desde_s=-120, hasta_s=330, sin=()):
    """Una foto por segundo de `libros_flujo`, salvo en los tramos (a, b) de `sin`."""
    t = np.arange(desde_s, hasta_s + 1)
    for a, b in sin:
        t = t[(t <= a) | (t >= b)]
    return pd.DataFrame({"exchange": "kraken", "recibido_utc": [s(x) for x in t]})


def test_vela_ohlcv_volumenes_vwap_y_numero_de_trades():
    velas = construir_velas(trades_ejemplo(), 60, cobertura_desde_latidos(latidos()))
    v = velas.set_index("inicio_utc").loc[T0]
    assert (v.apertura, v.maximo, v.minimo, v.cierre) == (100.0, 105.0, 98.0, 104.0)
    assert v.volumen_btc == pytest.approx(2.0)
    assert v.volumen_eur == pytest.approx(100 + 52.5 + 24.5 + 26)
    assert v.vwap == pytest.approx(203 / 2)
    assert v.n_trades == 4 and not v.vacia and v.completa
    assert (v.fuente, v.exchange, v.par, v.intervalo_s) == (FUENTE_PROPIA, "kraken", "BTC/EUR", 60)
    assert set(COLUMNAS_VELA) <= set(velas.columns)


def test_vela_vacia_no_inventa_precio_y_sigue_completa_si_la_captura_la_cubrio():
    velas = construir_velas(trades_ejemplo(), 60, cobertura_desde_latidos(latidos())).set_index("inicio_utc")
    v = velas.loc[s(60)]
    assert v.vacia and v.completa
    assert all(math.isnan(v[c]) for c in ("apertura", "maximo", "minimo", "cierre", "vwap"))
    assert v.volumen_btc == 0 and v.volumen_eur == 0 and v.n_trades == 0


def test_velas_de_frontera_al_principio_y_al_final_de_los_datos_no_estan_completas():
    velas = construir_velas(trades_ejemplo(), 60, cobertura_desde_latidos(latidos())).set_index("inicio_utc")
    assert velas.index.min() == s(-120) and velas.index.max() == s(300)
    assert not velas.loc[s(-120), "completa"]          # la captura empieza a las 09:58:00 (+ margen de reloj)
    assert not velas.loc[s(300), "completa"]           # termina a las 10:05:30: la vela no se cubrió entera
    assert velas.loc[s(-60), "completa"] and velas.loc[s(240), "completa"]


def test_un_hueco_de_captura_deja_incompletas_las_velas_que_toca():
    velas = construir_velas(trades_ejemplo(), 60, cobertura_desde_latidos(latidos(sin=[(190, 230)])))
    completa = velas.set_index("inicio_utc").completa
    assert not completa[s(180)]
    assert completa[s(120)] and completa[s(240)]


def test_un_error_del_websocket_deja_incompleta_su_vela():
    errores = pd.DataFrame({"exchange": ["kraken", "okx"], "recibido_utc": [s(270), s(150)], "origen": "flujo"})
    cobertura = quitar_errores(cobertura_desde_latidos(latidos()), errores)
    completa = construir_velas(trades_ejemplo(), 60, cobertura).set_index("inicio_utc").completa
    assert not completa[s(240)]
    assert completa[s(120)]                             # el error de okx no afecta a kraken


def test_hueco_corto_de_reinicio_tolera_la_vela_horaria_pero_no_la_de_un_minuto():
    t = np.arange(-10, 7210)
    t = t[(t <= 1800) | (t >= 1812)]                    # reinicio de la captura de 12 s
    lat = pd.DataFrame({"exchange": "kraken", "recibido_utc": [s(x) for x in t]})
    trades = pd.DataFrame({"exchange": "kraken", "hora_exchange_utc": [s(100), s(1805)], "precio": [1.0, 2.0],
                           "cantidad": [1.0, 1.0], "trade_id": ["x", "y"]})
    hora = construir_velas(trades, 3600, cobertura_desde_latidos(lat)).set_index("inicio_utc")
    assert hora.loc[T0, "completa"] and hora.loc[T0, "cobertura"] < 1
    minuto = construir_velas(trades, 60, cobertura_desde_latidos(lat)).set_index("inicio_utc")
    assert not minuto.loc[s(1800), "completa"]


def test_trades_duplicados_por_reconexion_cuentan_una_vez():
    trades = pd.concat([trades_ejemplo(), trades_ejemplo().iloc[[0]]], ignore_index=True)
    v = construir_velas(trades, 60, cobertura_desde_latidos(latidos())).set_index("inicio_utc").loc[T0]
    assert v.n_trades == 4 and v.volumen_btc == pytest.approx(2.0)


def _lake_con_captura(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(trades_ejemplo().to_dict("records"), "trades")
    lake.guardar(latidos().assign(par="BTC/EUR").to_dict("records"), "libros_flujo")
    return lake


def test_volver_a_calcular_no_duplica_velas_y_leer_velas_da_la_mas_reciente(tmp_path):
    lake = _lake_con_captura(tmp_path)
    primero = actualizar_velas(lake, intervalos_s=(60, 300), ahora=s(400))
    assert primero["escritas"] > 0
    antes = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60)
    segundo = actualizar_velas(lake, intervalos_s=(60, 300), ahora=s(500))
    assert segundo["escritas"] == 0                     # nada cambió: no se escribe nada nuevo
    despues = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60)
    assert len(despues) == len(antes) == 8
    assert not despues.duplicated(["fuente", "exchange", "par", "intervalo_s", "inicio_utc"]).any()

    # Un trade nuevo en la vela de las 10:01: se recalcula esa vela y se lee la versión nueva, sin duplicarla.
    lake.guardar([{"exchange": "kraken", "hora_exchange_utc": s(90), "recibido_utc": s(90.3), "precio": 99.0,
                   "cantidad": 2.0, "lado_agresor": "venta", "trade_id": "f"}], "trades")
    tercero = actualizar_velas(lake, intervalos_s=(60,), ahora=s(600))
    assert tercero["escritas"] == 1
    v = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60).set_index("inicio_utc")
    assert len(v) == 8 and v.loc[s(60), "cierre"] == 99.0 and not v.loc[s(60), "vacia"]
    filtradas = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60, desde=s(60), hasta=s(180))
    assert list(filtradas.inicio_utc) == [s(60), s(120)]
    assert FUENTE_VELAS in lake.fuentes()


def test_actualizar_velas_con_horas_no_marca_como_frontera_el_inicio_de_la_ventana(tmp_path):
    lake = _lake_con_captura(tmp_path)
    actualizar_velas(lake, intervalos_s=(60,), ahora=s(400))
    completo = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60).set_index("inicio_utc")
    actualizar_velas(lake, intervalos_s=(60,), horas=(400 - 60) / 3600, ahora=s(400))
    reciente = leer_velas(lake.consultar, FUENTE_PROPIA, "kraken", 60).set_index("inicio_utc")
    pd.testing.assert_series_equal(completo.completa, reciente.completa)
