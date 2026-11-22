"""Velas propias frente a las de Kraken (S4): diferencias, cobertura, correlación, estados y guardado."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis import comparacion_velas as cv
from radar.captura import historico_kraken as hk

T0 = pd.Timestamp("2026-11-22 12:00", tz="UTC")


def _velas(fuente: str, n: int = 60, intervalo_s: int = 60, semilla: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    cierre = 55000 * np.exp(np.cumsum(rng.normal(0, 5e-4, n)))
    apertura = np.r_[55000, cierre[:-1]]
    volumen = rng.uniform(0.5, 2.0, n)
    return pd.DataFrame({
        "fuente": fuente, "exchange": "kraken", "par": "BTC/EUR", "intervalo_s": intervalo_s,
        "inicio_utc": [T0 + pd.Timedelta(seconds=intervalo_s * i) for i in range(n)],
        "apertura": apertura, "maximo": np.maximum(apertura, cierre) + 5, "minimo": np.minimum(apertura, cierre) - 5,
        "cierre": cierre, "volumen_btc": volumen, "volumen_eur": volumen * cierre, "vwap": (apertura + cierre) / 2,
        "n_trades": rng.integers(5, 50, n).astype(float), "vacia": False, "completa": True,
        "recibido_utc": T0 + pd.Timedelta(hours=2)})


def test_velas_identicas_coinciden():
    k = _velas("kraken_historico")
    [r] = cv.comparar(k.assign(fuente="propia"), k, minimo=30)
    assert r.estado == cv.COINCIDEN
    assert r.n_comunes == 60 and r.cobertura == 1.0 and r.vacias_discrepantes == 0
    assert r.dif_cierre_bps == 0 and r.fraccion_identicas == 1.0 and r.dif_volumen_pct == 0
    assert r.corr_retornos == pytest.approx(1.0) and r.n_retornos == 59 and math.isnan(r.compensacion_frontera)
    assert r.hasta_utc == T0 + pd.Timedelta(hours=1)
    assert "coinciden" in r.conclusion()


def test_faltan_trades_propios_y_cobertura_con_velas_incompletas():
    k = _velas("kraken_historico")
    p = k.assign(fuente="propia", volumen_btc=k["volumen_btc"] * 0.9)
    p.loc[10:14, "completa"] = False                       # hueco de captura: no entran
    [r] = cv.comparar(p, k, minimo=30)
    assert r.estado == cv.FALTAN and r.dif_volumen_pct == pytest.approx(-10.0)
    assert r.n_propias == 55 and r.n_comunes == 55 and r.cobertura == pytest.approx(55 / 60)
    assert r.compensacion_frontera == pytest.approx(0.0)


def test_trades_en_la_vela_vecina_se_compensan():
    k = _velas("kraken_historico")
    p = k.assign(fuente="propia")
    for i in range(0, 60, 2):                               # 0,1 BTC pasa de cada vela par a la siguiente
        p.loc[i, "volumen_btc"] -= 0.1
        p.loc[i + 1, "volumen_btc"] += 0.1
    [r] = cv.comparar(p, k, minimo=30)
    assert r.estado == cv.FRONTERA and abs(r.dif_volumen_pct) < 1e-9
    assert r.compensacion_frontera == pytest.approx(1.0) and r.dif_volumen_mediana_pct > 1


def test_precios_desplazados_y_vacias_discrepantes():
    k = _velas("kraken_historico")
    p = k.assign(fuente="propia", cierre=k["cierre"] * (1 + 2e-4))      # 2 bps
    p.loc[5, ["vacia", "cierre", "apertura", "maximo", "minimo"]] = [True, np.nan, np.nan, np.nan, np.nan]
    p.loc[5, "volumen_btc"] = k.loc[5, "volumen_btc"]
    [r] = cv.comparar(p, k, minimo=30)
    assert r.dif_cierre_bps == pytest.approx(2.0) and r.dif_apertura_bps == 0
    assert r.vacias_discrepantes == 1 and r.n_comunes == 59
    assert r.n_retornos == 57                                # sin los dos retornos que tocan la vela 5
    assert math.isnan(r.compensacion_frontera)               # ninguna vela difiere en volumen
    assert r.estado == cv.DIFIEREN                           # el volumen cuadra, los precios no: no es frontera


def test_datos_insuficientes_y_a_fila():
    k = _velas("kraken_historico", n=10)
    [r] = cv.comparar(k.assign(fuente="propia"), k, minimo=30)
    assert r.estado == cv.INSUFICIENTE
    fila = r.a_fila()
    assert fila["estudio"] == "comparacion_velas" and fila["estado"] == cv.INSUFICIENTE
    assert "hacen falta 30" in fila["conclusion"] and fila["hasta_utc"] == r.hasta_utc


def test_solo_intervalos_y_tramo_de_las_propias():
    k = pd.concat([_velas("kraken_historico", n=120), _velas("kraken_historico", n=5, intervalo_s=3600)])
    p = _velas("propia", n=60).assign(inicio_utc=lambda d: d["inicio_utc"] + pd.Timedelta(minutes=30))
    [r] = cv.comparar(p, k, minimo=30)
    assert r.intervalo_s == 60 and r.n_kraken == 60 and r.n_comunes == 60


def test_comparar_velas_desde_el_lake_y_guardar(tmp_path):
    lake = LakeParquet(tmp_path)
    k = _velas("kraken_historico")
    assert hk.guardar_velas(lake, k) == 60
    lake.guardar(k.assign(fuente="propia").to_dict("records"), "velas")
    resultados = cv.comparar_velas(lake.consultar, minimo=30)
    assert [r.estado for r in resultados] == [cv.COINCIDEN]
    cv.guardar_comparacion_velas(resultados, lake, T0)
    guardado = lake.consultar("SELECT * FROM estudios_comparacion_velas")
    assert guardado["estado"].tolist() == [cv.COINCIDEN] and guardado["metodo"].tolist() == [cv.METODO]


def test_comparar_velas_sin_kraken_devuelve_vacio(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(_velas("propia").to_dict("records"), "velas")
    assert cv.comparar_velas(lake.consultar) == []
    assert math.isnan(cv._pct(1.0, 0.0))
