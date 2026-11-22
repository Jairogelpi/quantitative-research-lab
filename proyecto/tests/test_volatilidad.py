import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.volatilidad import (FUENTE_VOLATILIDAD, estudiar_volatilidad, guardar_estudio_volatilidad,
                                        rv_media, signature_plot, tsrv, volatilidad_ts)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")
SIGMA = 1e-4    # 1 bp por segundo en el precio eficiente
RUIDO = 2e-4    # 2 bps de ruido i.i.d. en cada observación


def precio_con_ruido(n=20_000, semilla=0):
    rng = np.random.default_rng(semilla)
    eficiente = np.cumsum(rng.normal(scale=SIGMA, size=n))
    return np.log(50_000) + eficiente + rng.normal(scale=RUIDO, size=n), eficiente


def test_tsrv_recupera_la_varianza_cuando_la_rv_de_1_s_esta_muy_sesgada():
    logp, eficiente = precio_con_ruido()
    verdadera = float(np.sum(np.diff(eficiente) ** 2))   # varianza integrada realizada del precio eficiente
    ingenua = rv_media(logp, 1)
    # Sesgo teórico de la RV a 1 s: 2 · n · E(ruido²) = 8 veces la varianza verdadera.
    assert ingenua > 5 * verdadera
    estimada = tsrv(logp)
    assert estimada.varianza == pytest.approx(verdadera, rel=0.15)
    assert estimada.ruido == pytest.approx(RUIDO, rel=0.1)


def test_signature_plot_baja_con_el_intervalo_y_recomienda_una_frecuencia():
    logp, _ = precio_con_ruido()
    t = T0 + pd.to_timedelta(np.arange(len(logp)), unit="s")
    mids = pd.DataFrame({"exchange": "kraken", "recibido_utc": t, "mid": np.exp(logp)})
    (f,) = signature_plot(mids, intervalos_s=(1, 2, 5, 10, 30, 60, 300), minimo=1000)
    vol = np.array(f.vol_bps_hora)
    assert np.all(np.diff(vol[:5]) < 0)                        # el ruido infla la RV a escalas finas
    assert vol[0] / f.tsrv_bps_hora == pytest.approx(3.0, rel=0.15)   # sqrt(9): la vol a 1 s triplica la verdadera
    assert f.tsrv_bps_hora == pytest.approx(SIGMA * 1e4 * 60, rel=0.1)
    assert f.frecuencia_recomendada_s >= 30
    assert f.estado == "ruido apreciable"
    texto = f.conclusion()
    assert "sobreestima" in texto and f"{f.frecuencia_recomendada_s} s" in texto
    assert f.a_fila()["estudio"] == "signature_plot" and f.hasta_utc == t[-1]
    pocos = signature_plot(mids.head(100), minimo=1000)[0]
    assert pocos.estado == "datos insuficientes" and "hacen falta 1000" in pocos.conclusion()


def test_volatilidad_ts_solo_usa_el_pasado():
    logp, _ = precio_con_ruido(n=3000, semilla=4)
    t = np.arange(len(logp), dtype=float)
    antes = volatilidad_ts(t, np.exp(logp))
    cambiado = logp.copy()
    cambiado[2000:] += np.random.default_rng(9).normal(scale=0.01, size=1000)   # otro futuro
    despues = volatilidad_ts(t, np.exp(cambiado))
    assert np.array_equal(antes[:2000], despues[:2000], equal_nan=True)
    assert not np.allclose(antes[2000:], despues[2000:], equal_nan=True)
    # Lejos del arranque, la estimación robusta está cerca de 1 bp por segundo (la ingenua estaría en ~3).
    assert np.nanmedian(antes[1000:2000]) == pytest.approx(SIGMA * 1e4, rel=0.3)
    assert np.isnan(antes[:10]).all()


def test_volatilidad_ts_ignora_los_huecos():
    t = np.r_[np.arange(1000.0), np.arange(5000.0, 6000.0)]
    mid = np.exp(np.r_[np.zeros(1000), np.full(1000, 0.05)])   # salto del 5 % durante el hueco
    v = volatilidad_ts(t, mid)
    assert np.nanmax(v) == 0.0


def test_estudio_desde_el_lake_y_guardado(tmp_path):
    lake = LakeParquet(tmp_path)
    logp, _ = precio_con_ruido(n=4000)
    cot = [{"exchange": "okx", "solicitado_utc": T0 + pd.Timedelta(seconds=i),
            "recibido_utc": T0 + pd.Timedelta(seconds=i + 0.1), "mid": float(np.exp(x)), "spread_bps": 1.0}
           for i, x in enumerate(logp)]
    lake.guardar(cot, "cotizaciones")
    (f,) = estudiar_volatilidad(lake.consultar)
    assert f.exchange == "okx" and f.n_segundos == 3999
    guardar_estudio_volatilidad([f], lake, pd.Timestamp("2026-11-22 12:00:00", tz="UTC"))
    leido = lake.consultar(f"SELECT * FROM {FUENTE_VOLATILIDAD}")
    assert len(leido) == 1 and leido.hasta_utc.notna().all() and leido.estudio.iloc[0] == "signature_plot"
