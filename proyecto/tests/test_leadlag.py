import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.leadlag import (estudiar_lead_lag, lead_lag_ratio, matriz_correlaciones, mids_alineados,
                                    retornos)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def lake_con_lider(tmp_path, n=1200, latencia_okx=0.3):
    """kraken lidera: el retorno de okx en t es la mitad del de kraken en t − 1, más ruido."""
    rng = np.random.default_rng(1)
    rk = rng.normal(scale=1.0, size=n)
    ro = 0.5 * np.r_[0, rk[:-1]] + rng.normal(scale=0.3, size=n)
    mid_k, mid_o = 50_000 * np.cumprod(1 + rk / 1e4), 50_000 * np.cumprod(1 + ro / 1e4)
    filas = []
    for i in range(n):
        t = T0 + pd.Timedelta(seconds=i)
        filas.append({"exchange": "kraken", "ronda": i % 400, "solicitado_utc": t, "recibido_utc": t,
                      "latencia_s": 0.2, "mid": mid_k[i]})
        filas.append({"exchange": "okx", "ronda": i % 400, "solicitado_utc": t + pd.Timedelta(milliseconds=5),
                      "recibido_utc": t, "latencia_s": latencia_okx, "mid": mid_o[i]})
    lake = LakeParquet(tmp_path)
    lake.guardar(filas, "cotizaciones")
    return lake


def test_alinea_por_hora_de_solicitud_y_corta_en_los_huecos(tmp_path):
    lake = lake_con_lider(tmp_path, n=20)
    alineados = mids_alineados(lake.consultar)
    assert len(alineados) == 20 and {"mid_kraken", "mid_okx", "latencia_okx"} <= set(alineados.columns)
    hueco = pd.concat([alineados.iloc[:10], alineados.iloc[10:].assign(t=lambda d: d.t + 60)], ignore_index=True)
    r = retornos(hueco)
    assert r["r_kraken"].isna().tolist() == [True] + [False] * 9 + [True] + [False] * 9


def test_detecta_quien_lidera_y_confirma_fuera_de_muestra(tmp_path):
    alineados = mids_alineados(lake_con_lider(tmp_path).consultar)
    resultados = {(r.lider, r.seguidor, r.retardo_rondas): r for r in estudiar_lead_lag(alineados, minimo=300)}
    kraken_okx = resultados[("kraken", "okx", 1)]
    assert kraken_okx.estado == "confirmada" and kraken_okx.coef_descubrimiento == pytest.approx(0.5, abs=0.05)
    assert kraken_okx.lead_lag_ratio > 10 and not kraken_okx.sospecha_latencia
    assert resultados[("okx", "kraken", 1)].estado == "sin evidencia"
    assert resultados[("kraken", "okx", 3)].estado == "sin evidencia"
    assert "¿kraken anticipa a okx a 1 ronda(s)? confirmada" in kraken_okx.conclusion()
    assert lead_lag_ratio(retornos(alineados), "okx", "kraken") < 0.1
    assert matriz_correlaciones(alineados).loc["kraken", "okx"] == pytest.approx(0, abs=0.1)


def test_avisa_si_el_lider_responde_mas_tarde(tmp_path):
    alineados = mids_alineados(lake_con_lider(tmp_path, latencia_okx=0.1).consultar)
    alineados["latencia_kraken"] = 0.6
    r = {(x.lider, x.seguidor, x.retardo_rondas): x for x in estudiar_lead_lag(alineados, minimo=300)}
    assert r[("kraken", "okx", 1)].sospecha_latencia and "puede ser solo latencia" in r[("kraken", "okx", 1)].conclusion()
    assert not r[("kraken", "okx", 2)].sospecha_latencia
    (pocos, *_) = estudiar_lead_lag(alineados.head(100), minimo=300)
    assert pocos.estado == "datos insuficientes"
