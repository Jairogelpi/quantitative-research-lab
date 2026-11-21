import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis import estudiar_imbalance, pares_imbalance_retorno


def pares(ret_positivos, ret_negativos, exchange="kraken", banda=1):
    filas = [(exchange, banda, 0.5, r) for r in ret_positivos] + [(exchange, banda, -0.5, r) for r in ret_negativos]
    return pd.DataFrame(filas, columns=["exchange", "banda_bps", "imbalance", "ret_bps"])


def test_relacion_clara_se_distingue_del_azar():
    rng = np.random.default_rng(7)
    r = estudiar_imbalance(pares(1 + rng.normal(0, 3, 300), -1 + rng.normal(0, 3, 300)))[0]
    assert (r.n_positivo, r.n_negativo) == (300, 300) and r.suficiente
    assert r.diferencia_bps == pytest.approx(2, abs=0.6) and r.t > 2 and r.distinguible
    assert "la diferencia es clara" in r.conclusion()


def test_sin_relacion_no_se_distingue_del_azar():
    mismos = [1.0, -1.0] * 150
    r = estudiar_imbalance(pares(mismos, mismos))[0]
    assert r.diferencia_bps == 0 and r.t == 0 and not r.distinguible
    assert r.conclusion() == ("kraken, banda 1 bps: con imbalance positivo el mid se movió +0.000 bps de media y "
                              "con negativo +0.000 bps (diferencia +0.000 bps, t = 0.00): no se distingue del azar.")


def test_pocos_datos_no_permiten_concluir():
    datos = pd.concat([pares([1.0, 2.0], [0.0] * 300), pares([5.0], [])], ignore_index=True)
    datos.loc[datos.index[-1], "imbalance"] = 0.0                         # imbalance 0 no cuenta en ningún grupo
    r = estudiar_imbalance(datos, min_por_grupo=200)[0]
    assert (r.n_positivo, r.n_negativo) == (2, 300) and not r.suficiente and not r.distinguible
    assert r.conclusion() == ("kraken, banda 1 bps: datos insuficientes (2 rondas con imbalance positivo y 300 con "
                              "negativo; hacen falta 200 en cada grupo).")


def test_un_resultado_por_exchange_y_banda():
    datos = pd.concat([pares([1.0], [1.0], "okx", 5), pares([1.0], [1.0], "kraken", 1), pares([1.0], [1.0], "kraken", 5)])
    assert [(r.exchange, r.banda_bps) for r in estudiar_imbalance(datos)] == [("kraken", 1), ("kraken", 5), ("okx", 5)]


def test_pares_desde_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    t0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")
    segundos, mids = [0, 1, 2, 3, 20], [100.0, 101.0, 103.0, 102.0, 90.0]  # salto de 17 s: otra captura
    t = [t0 + pd.Timedelta(seconds=s) for s in segundos]
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "mid": m} for ti, m in zip(t, mids)], "cotizaciones")
    lake.guardar([{"exchange": "kraken", "recibido_utc": ti, "banda_bps": 1, "imbalance": 0.3, "cubierta": True}
                  for ti in t], "desequilibrios")
    p = pares_imbalance_retorno(lake.consultar, horizonte_rondas=1, intervalo_s=1)
    assert list(p.ret_bps.round(6)) == [100.0, pytest.approx(198.019802), pytest.approx(-97.087379)]  # sin 102 → 90
    p2 = pares_imbalance_retorno(lake.consultar, horizonte_rondas=2, intervalo_s=1)
    assert list(p2.ret_bps.round(6)) == [300.0, pytest.approx(99.009901)]  # 100 → 103 y 101 → 102
