"""Estudio descriptivo de perpetuos: basis, funding, carry de la cobertura, OI, liquidaciones y margen."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis import derivados as de
from radar.analisis import registro
from radar.captura import historico_derivados as hd

T0 = pd.Timestamp("2026-11-01", tz="UTC")


def horas(n, indice=100.0, perp=101.0, mark=100.5):
    inicio = pd.date_range(T0, periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"indice": indice, "perp": perp, "mark": mark}, index=pd.Index(inicio, name="inicio_utc"))


def funding(fines, tasa, periodo_h=8.0, absoluta=math.nan):
    return pd.DataFrame({"periodo_fin_utc": [T0 + pd.Timedelta(hours=h) for h in fines], "periodo_h": periodo_h,
                         "tasa": tasa, "tasa_absoluta": absoluta})


def test_basis_en_bps_y_anualizado_con_la_convergencia_de_8_horas():
    b = de.basis_bps(pd.Series([101.0, 99.0]), pd.Series([100.0, 100.0]))
    assert list(b) == [pytest.approx(100.0), pytest.approx(-100.0)]
    assert de.anualizar_basis(100.0) == pytest.approx(0.01 * 8760 / 8)


def test_funding_anualizado_segun_el_periodo():
    assert de.anualizar_funding(0.0001, 8) == pytest.approx(0.0001 * 1095)
    assert de.anualizar_funding(0.0001, 1) == pytest.approx(0.876)


def test_carry_solo_con_funding_observado_despues_de_entrar():
    h = horas(24)
    f = funding([0, 8, 16, 24, 32], 0.001)       # 00:00 es antes de entrar; 32:00 es después de salir
    c = de.carry_cobertura(h, f, q_btc=1.0, comision_spot=0.0, comision_perp=0.0, garantia=0.5)
    assert c["n_pagos"] == 3
    assert c["funding_usd"] == pytest.approx(3 * 100.5 * 0.001)
    assert c["pnl_basis_usd"] == pytest.approx(0.0) and c["comisiones_usd"] == 0.0
    assert c["neto_usd"] == pytest.approx(0.3015)
    assert c["capital_usd"] == pytest.approx(100 + 0.5 * 101)
    assert c["horas"] == 23
    assert c["rentabilidad_anual"] == pytest.approx(0.3015 / 150.5 * 8760 / 23)


def test_carry_resta_las_comisiones_de_las_dos_piernas():
    c = de.carry_cobertura(horas(24), funding([8, 16, 24], 0.001), q_btc=1.0, comision_spot=0.001,
                           comision_perp=0.0005, garantia=0.5)
    assert c["comisiones_usd"] == pytest.approx(200 * 0.001 + 202 * 0.0005)
    assert c["neto_usd"] == pytest.approx(0.3015 - 0.301)


def test_carry_usa_el_pago_absoluto_si_lo_hay_y_el_cambio_de_basis():
    h = horas(24)
    h.loc[h.index[-1], "perp"] = 102.0          # el perpetuo sube 1 sin que lo haga el índice
    c = de.carry_cobertura(h, funding([8, 16], 0.0, periodo_h=1.0, absoluta=0.25), q_btc=2.0, comision_spot=0.0,
                           comision_perp=0.0, garantia=0.5)
    assert c["funding_usd"] == pytest.approx(2 * 2 * 0.25)
    assert c["pnl_basis_usd"] == pytest.approx(-2.0)


def test_carry_marca_el_cruce_del_mantenimiento_del_short():
    h = horas(24)
    h.loc[h.index[10], "mark"] = 111.0
    c = de.carry_cobertura(h, funding([8], 0.0), q_btc=1.0, comision_spot=0.0, comision_perp=0.0, garantia=0.1,
                           mantenimiento=0.005)
    # garantía 10,1 + (101 − 111) = 0,1 ≤ 111 · 0,005
    assert c["cruza_mantenimiento"] and c["garantia_minima_usd"] == pytest.approx(0.1)
    sin = de.carry_cobertura(horas(24), funding([8], 0.0), q_btc=1.0, comision_spot=0.0, comision_perp=0.0,
                             garantia=0.1, mantenimiento=0.005)
    assert not sin["cruza_mantenimiento"]


def test_carry_sin_pagos_es_nan():
    c = de.carry_cobertura(horas(24), funding([], 0.0), q_btc=1.0, comision_spot=0.0, comision_perp=0.0, garantia=0.5)
    assert c["n_pagos"] == 0 and math.isnan(c["neto_usd"])


def test_relacion_basis_funding_por_periodo():
    h = horas(24)
    h["mark"] = [100 * (1 + p / 1e4) for p in [5] * 8 + [10] * 8 + [20] * 8]
    r = de.relacion_basis_funding(h, funding([8, 16, 24], [5e-4, 10e-4, 20e-4]))
    assert r["n_periodos"] == 3
    assert r["correlacion"] == pytest.approx(1.0) and r["pendiente"] == pytest.approx(1.0)
    assert r["prima_media_bps"] == pytest.approx(35 / 3)


def test_oi_baja_en_los_movimientos_grandes():
    n = 50
    oi = pd.Series(1000 * np.cumprod([1.0] + [1.01] * (n - 1)), index=horas(n).index)
    grandes = pd.Series(False, index=oi.index)
    grandes.iloc[[10, 30]] = True
    oi.iloc[10:] = oi.iloc[10:] * 0.95 / 1.01
    oi.iloc[30:] = oi.iloc[30:] * 0.95 / 1.01
    r = de.oi_y_movimientos(oi, grandes, pd.Series(1.0, index=oi.index))
    assert r["cambio_oi_grandes_pct"] == pytest.approx(-5.0)
    assert r["cambio_oi_resto_pct"] == pytest.approx(1.0)
    assert r["n_horas_oi"] == n - 1


def test_grupos_de_liquidacion_frente_a_movimientos_grandes():
    idx = horas(100).index
    liq = pd.Series(0.0, index=idx)
    liq.iloc[[10, 11, 30]] = 50.0
    grandes = pd.Series(False, index=idx)
    grandes.iloc[[11, 50]] = True
    r = de.grupos_liquidacion(liq, grandes, umbral_btc=10.0, vecindad_h=1)
    assert r["n_grupos"] == 2
    assert r["fraccion_con_movimiento"] == pytest.approx(0.5)
    assert r["fraccion_base"] == pytest.approx(0.06)
    assert r["concentracion"] == pytest.approx(1.0)        # todo el volumen está en los grupos


def test_ejemplo_de_margen_10x():
    m = de.ejemplo_margen(precio=100.0, apalancamiento=10, mantenimiento=0.005)
    assert m["garantia_usd"] == pytest.approx(10.0)
    assert m["subida_que_liquida"] == pytest.approx(1.1 / 1.005 - 1)


def _lake_sintetico(tmp_path, n=24 * 40):
    almacen = LakeParquet(tmp_path)
    rng = np.random.default_rng(7)
    inicio = pd.date_range(T0, periods=n, freq="h", tz="UTC")
    indice = 60000 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    prima = 0.0003 + 0.0002 * np.sin(np.arange(n) / 30)
    ahora = inicio[-1] + pd.Timedelta(hours=2)
    for tipo, precio in [("indice", indice), ("mark", indice * (1 + prima)), ("perp", indice * (1 + prima * 1.1))]:
        velas = pd.DataFrame({"inicio_utc": inicio, "apertura": precio, "maximo": precio, "minimo": precio,
                              "cierre": precio, "volumen": np.nan, "completa": True})
        hd.guardar_filas(almacen, hd.filas_precios(velas, "kraken", "PF_XBTUSD", tipo, 3600, ahora), hd.FUENTE_PRECIOS)
    fines = inicio + pd.Timedelta(hours=1)
    f = pd.DataFrame({"exchange": "kraken", "instrumento": "PF_XBTUSD", "periodo_fin_utc": fines, "periodo_h": 1.0,
                      "tasa": prima / 8, "tasa_prevista": np.nan, "tasa_absoluta": indice * prima / 8})
    hd.guardar_filas(almacen, hd.filas_funding(f, ahora), hd.FUENTE_FUNDING)
    oi = pd.DataFrame({"inicio_utc": inicio, "valor": 2000 + rng.normal(0, 5, n)})
    hd.guardar_filas(almacen, hd.filas_oi(oi, "kraken", "PF_XBTUSD", ahora), hd.FUENTE_OI)
    liq = pd.DataFrame({"inicio_utc": inicio, "valor": rng.gamma(0.3, 2.0, n)})
    hd.guardar_filas(almacen, hd.filas_liquidaciones(liq, "kraken", "PF_XBTUSD", ahora), hd.FUENTE_LIQUIDACIONES)
    return almacen


def test_estudio_completo_desde_el_lake_es_descriptivo(tmp_path):
    almacen = _lake_sintetico(tmp_path)
    resultados = de.estudiar_derivados_lake(almacen.consultar)
    assert [r.exchange for r in resultados] == ["kraken"]
    r = resultados[0]
    assert r.estado == de.DESCRITO and r.n_horas == 24 * 40
    assert r.basis_medio_bps == pytest.approx(3.0 * 1.1, abs=0.5)
    assert r.relacion_correlacion > 0.99                  # funding = prima / 8 por construcción
    assert r.hasta_utc == T0 + pd.Timedelta(hours=24 * 40)
    texto = r.conclusion()
    assert texto.startswith("kraken PF_XBTUSD") and "basis" in texto and "carry" in texto
    fila = r.a_fila()
    assert fila["hasta_utc"] == r.hasta_utc and fila["estado"] == de.DESCRITO and fila["conclusion"] == texto
    assert not [c for c in fila if c.startswith(("p_", "t_")) or c == "t" or c in ("media_bps", "error_bps")]
    assert fila["estado"] not in registro.HALLAZGOS
    de.guardar_estudio_derivados(resultados, almacen, pd.Timestamp("2026-12-15", tz="UTC"))
    guardado = almacen.consultar("SELECT * FROM estudios_derivados")
    assert len(guardado) == 1 and guardado["metodo"].iloc[0] == de.METODO
    pruebas = registro.registrar_pruebas(almacen.consultar, [de.FUENTE_ESTUDIO])
    assert pruebas == []                                  # descriptivo: no entra en la familia de pruebas


def test_estudio_con_pocas_horas_no_concluye(tmp_path):
    almacen = _lake_sintetico(tmp_path, n=48)
    r = de.estudiar_derivados_lake(almacen.consultar)[0]
    assert r.estado == de.INSUFICIENTE and "datos insuficientes" in r.conclusion()


def test_estudio_sin_datos_devuelve_lista_vacia(tmp_path):
    assert de.estudiar_derivados_lake(LakeParquet(tmp_path).consultar) == []
