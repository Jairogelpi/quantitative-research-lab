import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.hallazgos import (FUENTE_REVALIDACIONES, PENDIENTE, SE_CAE, SE_DEBILITA, SE_MANTIENE,
                                      Revalidacion, clasificar, guardar_revalidaciones)
from radar.analisis.leadlag import FUENTE_LEAD_LAG, estudiar_lead_lag, mids_alineados
from radar.analisis.ofi import FUENTE_ESTUDIOS_OFI, estudiar_ofi, guardar_estudio_ofi, impacto_contemporaneo
from radar.analisis.revalidacion import (RevalidacionEstudio, guardar_estudio_senales,
                                         guardar_revalidaciones_estudios, revalidar_lead_lag, revalidar_ofi,
                                         revalidar_senales, revalidar_todo, ultimo_estudio)
from radar.analisis.senales import FUENTE_SENALES, aporte_senales, decaimiento, interacciones

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
AHORA = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")
SEG = pd.Timedelta(seconds=1)


# 0 · La regla común y la revalidación del imbalance, sin cambios.

def test_clasificar_usa_las_reglas_de_la_revalidacion():
    assert clasificar(False, 1.0, 1.0, 5.0) == PENDIENTE
    assert clasificar(True, 1.0, -0.1, -5.0) == SE_CAE
    assert clasificar(True, -1.0, -0.5, -2.0) == SE_MANTIENE
    assert clasificar(True, 1.0, 0.5, 1.99) == SE_DEBILITA


def test_la_revalidacion_del_imbalance_no_cambia_ni_su_estado_ni_sus_columnas():
    """Oráculo: la regla tal como estaba escrita en `Revalidacion.estado` antes de generalizarla."""
    def estado_original(r):
        if min(r.n_positivo, r.n_negativo) < r.min_por_grupo:
            return PENDIENTE
        if np.sign(r.diferencia) != np.sign(r.diferencia_anterior):
            return SE_CAE
        return SE_MANTIENE if abs(r.t) >= 2.0 else SE_DEBILITA

    casos = [Revalidacion("kraken", 1, 1, T0, pos, neg, ant, dif, t, 200)
             for pos, neg in ((50, 300), (300, 300)) for ant in (0.6, -0.6)
             for dif, t in ((0.5, 3.0), (0.5, 1.0), (-0.5, -3.0), (0.0, 0.0), (math.nan, math.nan))]
    assert [c.estado for c in casos] == [estado_original(c) for c in casos]
    assert list(casos[0].a_fila()) == ["exchange", "banda_bps", "horizonte_rondas", "desde_utc", "n_positivo",
                                       "n_negativo", "diferencia_anterior", "diferencia", "t", "min_por_grupo",
                                       "estado", "conclusion"]


# 1 · OFI: poder predictivo e impacto contemporáneo.

def serie_ofi(n, efecto=1.0, impacto=2.0, semilla=1, inicio=0, niveles=5, horizonte=1):
    """Pares OFI → retorno: ret = efecto · ofi + ruido y Δmid del mismo intervalo = impacto · ofi + ruido."""
    rng = np.random.default_rng(semilla)
    flujo = rng.uniform(-1, 1, n)
    return pd.DataFrame({"exchange": "kraken", "banda_bps": niveles, "horizonte_rondas": horizonte,
                         "recibido_utc": [T0 + (inicio + i) * SEG for i in range(n)], "imbalance": flujo,
                         "ret_bps": efecto * flujo + rng.normal(0, 3, n), "ret_pasado_bps": rng.normal(0, 3, n),
                         "spread_bps": rng.uniform(0.01, 2, n),
                         "ret_actual_bps": impacto * flujo + rng.normal(0, 1, n)})


def estudio_ofi_guardado(tmp_path, primera):
    lake = LakeParquet(tmp_path)
    guardar_estudio_ofi(impacto_contemporaneo(primera), estudiar_ofi(primera), lake, AHORA)
    return lake, ultimo_estudio(lake.consultar, FUENTE_ESTUDIOS_OFI)


def test_ofi_se_mantiene_solo_con_datos_posteriores_al_estudio(tmp_path):
    pares = serie_ofi(4000)
    hasta = T0 + 1999 * SEG
    _, anteriores = estudio_ofi_guardado(tmp_path, pares[pares.recibido_utc <= hasta])
    assert anteriores.loc[anteriores.estudio == "ofi_impacto", "hasta_utc"].iloc[0] == hasta  # el impacto lo guarda
    r = {x.estudio: x for x in revalidar_ofi(pares, anteriores)}
    assert set(r) == {"ofi_retorno", "ofi_impacto"}
    retorno, impacto = r["ofi_retorno"], r["ofi_impacto"]
    assert retorno.estado == SE_MANTIENE and retorno.hasta_utc == hasta and retorno.desde_utc == hasta + SEG
    descubierto = anteriores.loc[anteriores.estudio == "ofi_retorno", "diferencia_descubrimiento"].iloc[0]
    assert retorno.efecto_anterior == pytest.approx(descubierto) and retorno.efecto == pytest.approx(1.0, abs=0.3)
    assert retorno.t >= 2 and "kraken, OFI 5 niveles, horizonte 1" in retorno.conclusion()
    assert impacto.estado == SE_MANTIENE and impacto.n == 2000 and impacto.efecto == pytest.approx(2.0, abs=0.1)
    assert "se mantiene con datos posteriores al estudio" in impacto.conclusion()


def test_ofi_se_cae_si_el_signo_cambia_y_queda_pendiente_con_pocos_datos(tmp_path):
    primera = serie_ofi(2000)
    _, anteriores = estudio_ofi_guardado(tmp_path, primera)
    al_reves = pd.concat([primera, serie_ofi(2000, efecto=-1.0, impacto=-2.0, semilla=2, inicio=2000)])
    assert {x.estudio: x.estado for x in revalidar_ofi(al_reves, anteriores)} == {"ofi_retorno": SE_CAE,
                                                                                  "ofi_impacto": SE_CAE}
    pocos = pd.concat([primera, serie_ofi(100, semilla=3, inicio=2000)])
    pendientes = revalidar_ofi(pocos, anteriores)
    assert [x.estado for x in pendientes] == [PENDIENTE, PENDIENTE]
    assert all("pendiente" in x.conclusion() and "hacen falta 200" in x.conclusion() for x in pendientes)


def test_ofi_con_horizonte_largo_leido_del_lake(tmp_path):
    """En `estudios_ofi` el horizonte se lee como decimal (las filas de impacto no lo tienen): 30.0 rondas."""
    pares = serie_ofi(4000, horizonte=30)
    _, anteriores = estudio_ofi_guardado(tmp_path, pares.iloc[:2000])
    r = next(x for x in revalidar_ofi(pares, anteriores) if x.estudio == "ofi_retorno")
    assert r.estado == SE_MANTIENE and "horizonte 30" in r.hallazgo


def test_un_impacto_guardado_sin_hasta_utc_no_se_puede_revalidar(tmp_path):
    lake = LakeParquet(tmp_path)
    viejo = {k: v for k, v in impacto_contemporaneo(serie_ofi(1000))[0].a_fila().items() if k != "hasta_utc"}
    lake.guardar([{"metodo": "ofi_retorno/v1", "ejecutado_utc": AHORA, "recibido_utc": AHORA, "estudio": "ofi_impacto",
                   **viejo}], FUENTE_ESTUDIOS_OFI)
    (r,) = revalidar_ofi(serie_ofi(3000), ultimo_estudio(lake.consultar, FUENTE_ESTUDIOS_OFI))
    assert r.estado == PENDIENTE and r.n == 0 and "hasta_utc" in r.motivo and r.motivo in r.conclusion()


# 2 · Lead-lag.

def lake_lider(tmp_path, n=2400, coef_despues=0.5, n_estudio=1200):
    """kraken lidera: r_okx(t) = coef · r_kraken(t − 1) + ruido; coef = 0,5 en el estudio y `coef_despues` luego."""
    rng = np.random.default_rng(1)
    rk = rng.normal(size=n)
    coef = np.where(np.arange(n) < n_estudio, 0.5, coef_despues)
    ro = coef * np.r_[0, rk[:-1]] + rng.normal(scale=0.3, size=n)
    mid_k, mid_o = 50_000 * np.cumprod(1 + rk / 1e4), 50_000 * np.cumprod(1 + ro / 1e4)
    filas = []
    for i in range(n):
        t = T0 + i * SEG
        filas.append({"exchange": "kraken", "solicitado_utc": t, "recibido_utc": t, "latencia_s": 0.2,
                      "mid": mid_k[i]})
        filas.append({"exchange": "okx", "solicitado_utc": t + pd.Timedelta(milliseconds=5), "recibido_utc": t,
                      "latencia_s": 0.2, "mid": mid_o[i]})
    lake = LakeParquet(tmp_path)
    lake.guardar(filas, "cotizaciones")
    alineados = mids_alineados(lake.consultar)
    estudio = estudiar_lead_lag(alineados.iloc[:n_estudio], minimo=300)
    lake.guardar([{"ejecutado_utc": AHORA, "recibido_utc": AHORA, **r.a_fila()} for r in estudio], FUENTE_LEAD_LAG)
    return lake, alineados, estudio


def test_lead_lag_guarda_el_final_de_sus_datos_y_se_mantiene_despues(tmp_path):
    lake, alineados, estudio = lake_lider(tmp_path)
    hasta = alineados["solicitado_utc"].iloc[1199]
    assert all(r.hasta_utc == hasta for r in estudio) and "hasta_utc" in estudio[0].a_fila()
    anteriores = ultimo_estudio(lake.consultar, FUENTE_LEAD_LAG)
    reval = revalidar_lead_lag(alineados, anteriores)
    assert len(reval) == sum(r.estado == "confirmada" for r in estudio)  # solo los confirmados
    r = next(x for x in reval if x.hallazgo == "kraken anticipa a okx a 1 ronda(s)")
    assert r.estudio == "lead_lag" and r.estado == SE_MANTIENE and r.efecto == pytest.approx(0.5, abs=0.05)
    assert r.desde_utc > hasta and 1150 <= r.n < 1200  # solo las rondas posteriores al estudio


def test_lead_lag_se_cae_si_el_lider_se_invierte(tmp_path):
    lake, alineados, _ = lake_lider(tmp_path, coef_despues=-0.5)
    reval = revalidar_lead_lag(alineados, ultimo_estudio(lake.consultar, FUENTE_LEAD_LAG))
    r = next(x for x in reval if x.hallazgo == "kraken anticipa a okx a 1 ronda(s)")
    assert r.estado == SE_CAE and r.efecto < 0 < r.efecto_anterior and "se cae" in r.conclusion()


def test_lead_lag_guardado_sin_hasta_utc_queda_pendiente(tmp_path):
    lake, alineados, estudio = lake_lider(tmp_path / "a")
    viejo = LakeParquet(tmp_path / "b")
    viejo.guardar([{"ejecutado_utc": AHORA, "recibido_utc": AHORA,
                    **{k: v for k, v in r.a_fila().items() if k != "hasta_utc"}} for r in estudio], FUENTE_LEAD_LAG)
    reval = revalidar_lead_lag(alineados, ultimo_estudio(viejo.consultar, FUENTE_LEAD_LAG))
    assert reval and all(x.estado == PENDIENTE and "hasta_utc" in x.motivo for x in reval)


def test_revalidar_todo_lee_el_lake_y_guarda_junto_a_las_del_imbalance(tmp_path):
    lake, _, _ = lake_lider(tmp_path)
    guardar_revalidaciones([Revalidacion("kraken", 1, 1, T0, 300, 300, 0.6, 0.5, 3.0, 200)], lake, AHORA)
    reval = revalidar_todo(lake.consultar, lake.fuentes())
    assert reval and {x.estudio for x in reval} == {"lead_lag"}
    guardar_revalidaciones_estudios(reval, lake, AHORA)
    filas = lake.consultar(f"SELECT * FROM {FUENTE_REVALIDACIONES} ORDER BY estudio NULLS FIRST")
    assert len(filas) == 1 + len(reval)
    imbalance, nuevas = filas.iloc[0], filas.iloc[1:]
    assert pd.isna(imbalance.estudio) and imbalance.diferencia == 0.5 and imbalance.estado == SE_MANTIENE
    assert set(nuevas.estudio) == {"lead_lag"} and nuevas.estado.isin([SE_MANTIENE, SE_DEBILITA]).all()
    assert {"hallazgo", "hasta_utc", "desde_utc", "n", "minimo", "efecto_anterior", "efecto", "t", "unidad",
            "motivo", "conclusion"} <= set(filas.columns)


def test_revalidar_todo_sin_datos_nuevos_ni_estudios(tmp_path):
    lake = LakeParquet(tmp_path)
    assert revalidar_todo(lake.consultar, lake.fuentes()) == []
    primera = serie_ofi(2000)
    guardar_estudio_ofi(impacto_contemporaneo(primera), estudiar_ofi(primera), lake, AHORA)
    reval = revalidar_todo(lake.consultar, lake.fuentes())  # sin libros en el lake: nada posterior
    assert {x.estudio for x in reval} == {"ofi_retorno", "ofi_impacto"}
    assert all(x.estado == PENDIENTE and x.n == 0 for x in reval)


# 3 · Señales: aporte propio e interacciones.

def tabla(n, signo_lider=1.0, signo_inter=1.0, semilla=0, inicio=0):
    """lider predice el retorno a 5 rondas; imbalance solo funciona con spread alto (> 1)."""
    rng = np.random.default_rng(semilla)
    lider, imbalance, spread = rng.normal(size=n), rng.normal(size=n), rng.uniform(0, 2, size=n)
    t = pd.DataFrame({"exchange": "kraken", "recibido_utc": [T0 + (inicio + i) * SEG for i in range(n)],
                      "lider": lider, "ofi": rng.normal(size=n), "imbalance": imbalance, "spread_bps": spread,
                      "volatilidad_bps": rng.uniform(0, 1, size=n), "ret_pasado_bps": rng.normal(size=n)})
    for k in (1, 2, 3, 5, 10):
        t[f"ret_{k}"] = (0.3 * signo_lider * lider + 0.4 * signo_inter * imbalance * (spread > 1)
                         + rng.normal(scale=0.5, size=n))
    return t


def estudio_senales_guardado(tmp_path, primera):
    lake = LakeParquet(tmp_path)
    resultados = (aporte_senales(primera, minimo=500) + interacciones(primera, minimo=500)
                  + decaimiento(primera, horizontes=(1, 2, 3, 5, 10), minimo=500))
    guardar_estudio_senales(resultados, primera, lake, AHORA)
    return lake, ultimo_estudio(lake.consultar, FUENTE_SENALES)


def test_senales_guardan_el_final_y_se_mantienen_con_datos_posteriores(tmp_path):
    primera = tabla(4000)
    lake, anteriores = estudio_senales_guardado(tmp_path, primera)
    hasta = T0 + 3999 * SEG
    assert (anteriores.hasta_utc == hasta).all() and set(anteriores.estudio) == {"aporte", "interaccion", "decaimiento"}
    confirmadas = anteriores[anteriores.estado.isin(["aporta información propia", "confirmada"])]
    reval = {x.hallazgo: x for x in revalidar_senales(pd.concat([primera, tabla(4000, semilla=5, inicio=4000)]),
                                                         anteriores)}
    assert len(reval) == len(confirmadas)
    aporte = reval["kraken, lider aporta información propia, horizonte 5"]
    assert aporte.estudio == "aporte" and aporte.estado == SE_MANTIENE and aporte.desde_utc == hasta + SEG
    assert aporte.n == 4000 and aporte.efecto == pytest.approx(0.3, abs=0.05)
    inter = next(x for x in reval.values() if x.estudio == "interaccion" and x.hallazgo.startswith("kraken, imbalance × el spread"))
    assert inter.estado == SE_MANTIENE and inter.efecto == pytest.approx(0.4, abs=0.1)
    assert "bps por desviación" in inter.conclusion()


def test_senales_se_caen_si_el_efecto_cambia_de_signo_y_quedan_pendientes_con_pocos_datos(tmp_path):
    primera = tabla(4000)
    _, anteriores = estudio_senales_guardado(tmp_path, primera)
    al_reves = pd.concat([primera, tabla(4000, signo_lider=-1, signo_inter=-1, semilla=6, inicio=4000)])
    reval = {x.hallazgo: x for x in revalidar_senales(al_reves, anteriores)}
    assert reval["kraken, lider aporta información propia, horizonte 5"].estado == SE_CAE
    assert next(x for x in reval.values() if x.hallazgo.startswith("kraken, imbalance × el spread")).estado == SE_CAE
    pocos = revalidar_senales(pd.concat([primera, tabla(100, semilla=7, inicio=4000)]), anteriores)
    assert pocos and all(x.estado == PENDIENTE and "hacen falta 500" in x.conclusion() for x in pocos)


def test_senales_guardadas_sin_hasta_utc_no_se_pueden_revalidar(tmp_path):
    primera = tabla(4000)
    lake = LakeParquet(tmp_path)
    lake.guardar([{"ejecutado_utc": AHORA, "recibido_utc": AHORA, **r.a_fila()} for r in aporte_senales(primera, minimo=500)],
                 FUENTE_SENALES)  # como lo guardaba `senales` antes
    reval = revalidar_senales(pd.concat([primera, tabla(4000, semilla=5, inicio=4000)]),
                              ultimo_estudio(lake.consultar, FUENTE_SENALES))
    assert reval and all(x.estado == PENDIENTE and "hasta_utc" in x.motivo for x in reval)


def test_la_fila_de_una_revalidacion_tiene_estudio_y_estado():
    r = RevalidacionEstudio("lead_lag", "kraken anticipa a okx a 1 ronda(s)", T0, T0 + SEG, 1000, 300, 0.5, 0.45,
                            8.0, "bps por bps")
    fila = r.a_fila()
    assert fila["estudio"] == "lead_lag" and fila["estado"] == SE_MANTIENE and fila["motivo"] == ""
    assert "efecto +0.500 bps por bps al descubrirlo y +0.450 ahora (t HAC 8.00)" in fila["conclusion"]
