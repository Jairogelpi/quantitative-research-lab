import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from radar.almacen import LakeParquet
from radar.analisis import (CALIDAD_INSUFICIENTE, CONFIRMADA, INSUFICIENTE, NO_CONFIRMADA, PENDIENTE, SE_CAE,
                            SE_DEBILITA, SE_MANTIENE, SIN_EVIDENCIA, Calidad, estudiar_imbalance, evaluar_calidad,
                            guardar_estudio, leer_ultimo_estudio, pares_imbalance_retorno, revalidar)

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")


def serie(n=2000, efecto=1.0, efecto_segunda_mitad=None, ruido=3.0, semilla=1, exchange="kraken", banda=1,
          horizonte=1):
    """Pares ordenados en el tiempo: ret = efecto · imbalance + ruido."""
    rng = np.random.default_rng(semilla)
    imbalance = rng.uniform(-1, 1, n)
    efectos = np.where(np.arange(n) < n // 2, efecto, efecto if efecto_segunda_mitad is None else efecto_segunda_mitad)
    return pd.DataFrame({"exchange": exchange, "banda_bps": banda, "horizonte_rondas": horizonte,
                         "recibido_utc": [T0 + pd.Timedelta(seconds=i) for i in range(n)], "imbalance": imbalance,
                         "ret_bps": efectos * imbalance + rng.normal(0, ruido, n),
                         "ret_pasado_bps": rng.normal(0, ruido, n), "spread_bps": rng.uniform(0.01, 2, n)})


def test_senal_real_se_confirma_fuera_de_muestra():
    r = estudiar_imbalance(serie())[0]
    assert r.estado == CONFIRMADA and r.diferencia_descubrimiento > 0 and r.diferencia_confirmacion > 0
    assert r.t_confirmacion > 2 and r.p_ajustado < 0.05 and r.ic > 0
    assert r.quintiles == sorted(r.quintiles) and r.monotona  # más imbalance, más retorno
    assert r.corte_utc == T0 + pd.Timedelta(seconds=1000)     # descubre en la 1.ª mitad, confirma en la 2.ª


def test_ruido_puro_no_tiene_evidencia():
    r = estudiar_imbalance(serie(efecto=0, semilla=3))[0]
    assert r.estado == SIN_EVIDENCIA and r.p_ajustado >= 0.05
    assert "sin evidencia" in r.conclusion()


def test_senal_que_desaparece_no_se_confirma():
    r = estudiar_imbalance(serie(efecto=1.5, efecto_segunda_mitad=0, semilla=2))[0]
    assert r.estado == NO_CONFIRMADA and r.p_ajustado < 0.05 and abs(r.t_confirmacion) < 2


def test_pocos_datos_no_permiten_concluir():
    r = estudiar_imbalance(serie(n=100), min_por_grupo=200)[0]
    assert r.estado == INSUFICIENTE and np.isnan(r.p_ajustado)
    assert r.conclusion().startswith("kraken, banda 1 bps, horizonte 1: datos insuficientes")


def test_errores_hac_no_se_dejan_engañar_por_datos_repetidos():
    base = serie(n=1000, efecto=0.6, semilla=5)
    repetida = base.loc[base.index.repeat(10)].reset_index(drop=True)  # cada ronda 10 veces seguidas
    repetida["recibido_utc"] = [T0 + pd.Timedelta(seconds=i) for i in range(len(repetida))]
    t_base = estudiar_imbalance(base, min_por_grupo=50)[0].t_descubrimiento
    t_repetida = estudiar_imbalance(repetida, min_por_grupo=50)[0].t_descubrimiento
    # Un t ingenuo crecería ≈ √10 ≈ 3,2 veces sin información nueva; el de Newey-West apenas cambia.
    assert t_repetida < 1.6 * t_base


def test_benjamini_hochberg_sobre_todas_las_pruebas():
    pares = pd.concat([serie(efecto=0, semilla=s, banda=b) for s, b in zip(range(10, 16), (1, 2, 3, 4, 5, 6))])
    resultados = estudiar_imbalance(pares)
    crudos = [r.p_descubrimiento for r in resultados]
    assert [r.p_ajustado for r in resultados] == pytest.approx(list(multipletests(crudos, method="fdr_bh")[1]))
    assert all(r.p_ajustado >= r.p_descubrimiento for r in resultados)


def test_un_resultado_por_exchange_banda_y_horizonte():
    pares = pd.concat([serie(exchange="okx", banda=5), serie(horizonte=5), serie(horizonte=1)])
    claves = [(r.exchange, r.banda_bps, r.horizonte_rondas) for r in estudiar_imbalance(pares)]
    assert claves == [("kraken", 1, 1), ("kraken", 1, 5), ("okx", 5, 1)]


def test_significacion_economica_frente_al_equilibrio():
    caro = estudiar_imbalance(serie(), equilibrio_bps={"kraken": 160.0})[0]
    assert not caro.rentable_taker and "no rentable para un taker" in caro.conclusion()
    barato = estudiar_imbalance(serie(efecto=8, ruido=1), equilibrio_bps={"kraken": 0.5})[0]
    assert barato.rentable_taker and barato.movimiento_bps > 0.5
    assert estudiar_imbalance(serie())[0].rentable_taker is None  # sin equilibrio, no se opina


def test_guardar_y_leer_el_ultimo_estudio(tmp_path):
    lake = LakeParquet(tmp_path)
    resultados = estudiar_imbalance(pd.concat([serie(), serie(exchange="okx")]), equilibrio_bps={"kraken": 160.0})
    guardar_estudio(resultados, lake, T0)
    guardar_estudio(resultados[:1], lake, T0 + pd.Timedelta(hours=1))  # ejecución posterior
    ultimo = leer_ultimo_estudio(lake.consultar)
    assert len(ultimo) == 1 and ultimo.exchange[0] == "kraken" and ultimo.estado[0] == CONFIRMADA
    assert ultimo.metodo[0] == "imbalance_retorno/v3" and ultimo.conclusion[0] == resultados[0].conclusion()
    assert {"ic", "p_ajustado", "q1", "q5", "desde_utc", "hasta_utc", "corte_utc", "rentable_taker"} <= set(ultimo)


def test_pares_desde_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    segundos, mids = [0, 1, 2, 3, 20], [100.0, 101.0, 103.0, 102.0, 90.0]  # salto de 17 s: otra captura
    t = [T0 + pd.Timedelta(seconds=s) for s in segundos]
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "mid": m, "bid": m - 1, "ask": m + 1, "cantidad_bid": 3.0,
                   "cantidad_ask": 1.0, "spread_bps": 2 / m * 1e4} for ti, m in zip(t, mids)], "cotizaciones")
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "banda_bps": 1, "imbalance": 0.3, "cubierta": True}
                  for ti in t], "desequilibrios")
    p = pares_imbalance_retorno(lake.consultar, horizontes=(1, 2), intervalo_s=1)
    h1, h2 = p[p.horizonte_rondas == 1], p[p.horizonte_rondas == 2]
    assert list(h1.ret_bps.round(6)) == [100.0, pytest.approx(198.019802), pytest.approx(-97.087379)]  # sin 102 → 90
    assert list(h2.ret_bps.round(6)) == [300.0, pytest.approx(99.009901)]  # 100 → 103 y 101 → 102
    assert h1.ret_pasado_bps.isna().iloc[0] and h1.ret_pasado_bps.iloc[1] == pytest.approx(100)  # 100 → 101
    assert h1.spread_bps.iloc[0] == pytest.approx(200)
    # Microprice = (bid · cantidad_ask + ask · cantidad_bid) / (cantidad_bid + cantidad_ask): 3 BTC en el bid lo
    # acercan al ask. Mid 100 → microprice 100,5; mid 101 → 101,5.
    micro = pares_imbalance_retorno(lake.consultar, horizontes=(1,), intervalo_s=1, precio="microprice")
    assert micro.ret_bps.iloc[0] == pytest.approx((101.5 / 100.5 - 1) * 1e4)
    with pytest.raises(ValueError, match="precio"):
        pares_imbalance_retorno(lake.consultar, precio="last")
    with pytest.raises(ValueError):
        pares_imbalance_retorno(lake.consultar, horizontes=(0,))


# 1 · Walk-forward y revalidación con datos posteriores.

def test_walk_forward_cuenta_las_ventanas_que_repiten_el_signo():
    r = estudiar_imbalance(serie(n=4000))[0]
    assert (r.ventanas_mismo_signo, r.ventanas_total) == (4, 4) and "4/4 ventanas" in r.conclusion()
    s = estudiar_imbalance(serie(n=4000, efecto=1.5, efecto_segunda_mitad=-1.5, semilla=4))[0]
    assert s.ventanas_mismo_signo == 2 and s.ventanas_total == 4


def anterior(estado=CONFIRMADA, diferencia=0.6, hasta=T0 + pd.Timedelta(seconds=999)):
    return pd.DataFrame([{"exchange": "kraken", "banda_bps": 1, "horizonte_rondas": 1, "estado": estado,
                          "diferencia_descubrimiento": diferencia, "hasta_utc": hasta}])


def test_revalidacion_solo_con_datos_posteriores_al_estudio():
    datos = serie(n=3000)  # la señal sigue igual de fuerte después del estudio
    r = revalidar(datos, anterior())[0]
    assert r.estado == SE_MANTIENE and r.n_positivo + r.n_negativo < 2100  # solo las 2.000 rondas posteriores
    assert r.desde_utc == T0 + pd.Timedelta(seconds=1000) and "se mantiene" in r.conclusion()


def test_revalidacion_se_debilita_se_cae_o_queda_pendiente():
    assert revalidar(serie(n=3000, efecto=0.15, semilla=8), anterior())[0].estado == SE_DEBILITA
    assert revalidar(serie(n=3000, efecto=-1.0, semilla=9), anterior())[0].estado == SE_CAE
    pocos = revalidar(serie(n=1100), anterior())[0]  # solo 100 rondas nuevas
    assert pocos.estado == PENDIENTE and "pendiente" in pocos.conclusion()
    assert revalidar(serie(), anterior(estado=SIN_EVIDENCIA)) == []  # solo se revalidan los confirmados


# 2 · Controles: retorno pasado y spread.

def test_controles_el_imbalance_sobrevive_si_aporta_algo_propio():
    r = estudiar_imbalance(serie())[0]
    assert r.sobrevive_controles and r.t_controlado > 2 and "sobrevive a los controles" in r.conclusion()


def test_controles_detectan_una_senal_que_solo_era_momentum():
    datos = serie(efecto=0)
    datos["ret_pasado_bps"] = datos.imbalance * 4 + np.random.default_rng(2).normal(0, 0.5, len(datos))
    datos["ret_bps"] = 0.5 * datos.ret_pasado_bps + np.random.default_rng(3).normal(0, 1, len(datos))
    r = estudiar_imbalance(datos)[0]
    assert r.estado == CONFIRMADA and not r.sobrevive_controles  # parecía señal, pero era el retorno pasado
    assert "no sobrevive a los controles" in r.conclusion()


# 3 · Intervalos de confianza.

def test_intervalo_de_confianza_del_efecto():
    r = estudiar_imbalance(serie())[0]
    assert r.int95_inferior < r.diferencia_confirmacion < r.int95_superior and r.int95_inferior > 0
    assert r.int95_superior - r.int95_inferior == pytest.approx(2 * 1.96 * r.diferencia_confirmacion / r.t_confirmacion)
    assert "intervalo 95 %" in r.conclusion()


# 4 · Puerta de calidad de los datos.

def test_calidad_mala_impide_concluir():
    mala = {"kraken": Calidad("kraken", rondas=2000, huecos=300, errores=0, latencia_p99_s=0.5)}
    r = estudiar_imbalance(serie(), calidad=mala)[0]
    assert r.estado == CALIDAD_INSUFICIENTE and np.isnan(r.p_ajustado)
    assert "huecos 15.0 %" in r.conclusion()
    buena = {"kraken": Calidad("kraken", rondas=2000, huecos=10, errores=5, latencia_p99_s=0.9)}
    assert estudiar_imbalance(serie(), calidad=buena)[0].estado == CONFIRMADA


def test_evaluar_calidad_desde_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    segundos = [0, 1, 2, 6, 7, 200, 201]  # 2 → 6: hueco; 7 → 200: otra sesión, no es hueco
    lake.guardar([{"exchange": "kraken", "recibido_utc": T0 + pd.Timedelta(seconds=s), "latencia_s": 0.4 + i / 10}
                  for i, s in enumerate(segundos)], "cotizaciones")
    lake.guardar([{"exchange": "kraken", "recibido_utc": T0, "error": "Timeout"}], "errores_captura")
    c = evaluar_calidad(lake.consultar, lake.fuentes(), intervalo_s=1)["kraken"]
    assert (c.rondas, c.huecos, c.errores) == (7, 1, 1) and c.latencia_p99_s == pytest.approx(0.994)
    assert not c.pasa and c.motivo == "huecos 14.3 %, errores 12.5 %"  # 1 hueco en 7 rondas, 1 error en 8
    sin_errores = LakeParquet(tmp_path / "otro")
    sin_errores.guardar([{"exchange": "okx", "recibido_utc": T0, "latencia_s": 5.0}], "cotizaciones")
    c = evaluar_calidad(sin_errores.consultar, sin_errores.fuentes())["okx"]
    assert c.errores == 0 and not c.pasa and "latencia" in c.motivo


def test_la_calidad_de_la_captura_rest_no_cuenta_los_errores_del_websocket(tmp_path):
    from radar.almacen import LakeParquet
    from radar.analisis import evaluar_calidad
    lake, t0 = LakeParquet(tmp_path), pd.Timestamp("2026-11-22 10:00", tz="UTC")
    lake.guardar([{"exchange": "kraken", "recibido_utc": t0 + pd.Timedelta(seconds=i), "latencia_s": 0.1}
                  for i in range(10)], "cotizaciones")
    lake.guardar([{"exchange": "kraken", "recibido_utc": t0, "ronda": 3, "error": "HTTP 500"}], "errores_captura")
    lake.guardar([{"exchange": "kraken", "recibido_utc": t0 + pd.Timedelta(seconds=5), "error": "hueco de secuencia",
                   "origen": "flujo"}],
                 "errores_captura")
    assert len(lake.consultar("SELECT * FROM errores_captura")) == 2  # las dos filas están en el lake
    assert evaluar_calidad(lake.consultar, lake.fuentes())["kraken"].errores == 1
