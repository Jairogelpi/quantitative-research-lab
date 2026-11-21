import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from radar.almacen import LakeParquet
from radar.analisis import (CONFIRMADA, INSUFICIENTE, NO_CONFIRMADA, SIN_EVIDENCIA, estudiar_imbalance,
                            guardar_estudio, leer_ultimo_estudio, pares_imbalance_retorno)

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")


def serie(n=2000, efecto=1.0, efecto_segunda_mitad=None, ruido=3.0, semilla=1, exchange="kraken", banda=1,
          horizonte=1):
    """Pares ordenados en el tiempo: ret = efecto · imbalance + ruido."""
    rng = np.random.default_rng(semilla)
    imbalance = rng.uniform(-1, 1, n)
    efectos = np.where(np.arange(n) < n // 2, efecto, efecto if efecto_segunda_mitad is None else efecto_segunda_mitad)
    return pd.DataFrame({"exchange": exchange, "banda_bps": banda, "horizonte_rondas": horizonte,
                         "recibido_utc": [T0 + pd.Timedelta(seconds=i) for i in range(n)], "imbalance": imbalance,
                         "ret_bps": efectos * imbalance + rng.normal(0, ruido, n)})


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
    assert ultimo.metodo[0] == "imbalance_retorno/v2" and ultimo.conclusion[0] == resultados[0].conclusion()
    assert {"ic", "p_ajustado", "q1", "q5", "desde_utc", "hasta_utc", "corte_utc", "rentable_taker"} <= set(ultimo)


def test_pares_desde_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    segundos, mids = [0, 1, 2, 3, 20], [100.0, 101.0, 103.0, 102.0, 90.0]  # salto de 17 s: otra captura
    t = [T0 + pd.Timedelta(seconds=s) for s in segundos]
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "mid": m} for ti, m in zip(t, mids)], "cotizaciones")
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "banda_bps": 1, "imbalance": 0.3, "cubierta": True}
                  for ti in t], "desequilibrios")
    p = pares_imbalance_retorno(lake.consultar, horizontes=(1, 2), intervalo_s=1)
    h1, h2 = p[p.horizonte_rondas == 1], p[p.horizonte_rondas == 2]
    assert list(h1.ret_bps.round(6)) == [100.0, pytest.approx(198.019802), pytest.approx(-97.087379)]  # sin 102 → 90
    assert list(h2.ret_bps.round(6)) == [300.0, pytest.approx(99.009901)]  # 100 → 103 y 101 → 102
    with pytest.raises(ValueError):
        pares_imbalance_retorno(lake.consultar, horizontes=(0,))
