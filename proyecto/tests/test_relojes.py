"""Relojes: desfase y deriva entre la hora del exchange y la nuestra, sobre un lake temporal (sin red)."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.relojes import (COHERENTE, DERIVA, DESFASE, FUENTE_RELOJES, INSUFICIENTE, RANCIA, diagnostico_comun,
                                    guardar_relojes, incertidumbre_lead_lag, medir_relojes)

INICIO = pd.Timestamp("2026-11-22 10:00", tz="UTC")


def _eventos(exchange, n, desfase_s, deriva_s_h=0.0, latencia_media_s=0.02, horas=2.0, semilla=0, salto=None):
    """Mensajes del libro: hora del exchange en SU reloj; recibido = hora + latencia + desfase(t) (nuestro reloj)."""
    rng = np.random.default_rng(semilla)
    t = np.sort(rng.uniform(0, horas * 3600, n))
    latencia = 0.005 + rng.exponential(latencia_media_s, n)
    desfase = desfase_s + deriva_s_h * t / 3600
    if salto is not None:
        desfase = desfase + np.where(t > salto[0], salto[1], 0.0)
    hora = INICIO + pd.to_timedelta(t, unit="s")
    recibido = hora + pd.to_timedelta(latencia + desfase, unit="s")
    return [{"exchange": exchange, "recibido_utc": r, "hora_exchange_utc": h, "tipo": "update", "lado": "bid",
             "precio": 100.0, "cantidad": 1.0, "secuencia": float(i)} for i, (r, h) in enumerate(zip(recibido, hora))]


def _cotizaciones(exchange, n, desfase_s, rtt_s=0.1, semilla=1, rancia_s=0.0):
    """Fotos REST: el exchange pone la hora a mitad del viaje (o `rancia_s` antes: hora de la última actualización)."""
    rng = np.random.default_rng(semilla)
    t = np.arange(n, dtype=float)
    rtt = rtt_s + rng.exponential(0.02, n)
    solicitado = INICIO + pd.to_timedelta(t, unit="s")
    recibido = solicitado + pd.to_timedelta(rtt, unit="s")
    hora = solicitado + pd.to_timedelta(rtt / 2 - desfase_s - rancia_s, unit="s")
    return [{"exchange": exchange, "par": "BTC-EUR", "solicitado_utc": s, "recibido_utc": r, "hora_exchange_utc": h,
             "latencia_s": float(l), "mid": 100.0} for s, r, h, l in zip(solicitado, recibido, hora, rtt)]


def _por(resultados, exchange, fuente="eventos_libro"):
    return next(r for r in resultados if r.exchange == exchange and r.fuente == fuente)


@pytest.fixture
def lake(tmp_path):
    return LakeParquet(tmp_path)


def test_reloj_coherente_con_latencia_positiva(lake):
    lake.guardar(_eventos("a", 5000, desfase_s=0.0), "eventos_libro")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.estado == COHERENTE
    assert r.p1_s > 0
    assert r.mediana_s == pytest.approx(0.005 + 0.02 * math.log(2), abs=0.004)
    assert abs(r.deriva_ms_h) < 3
    assert "reloj coherente" in r.conclusion()


def test_desfase_negativo_es_imposible_y_se_detecta(lake):
    lake.guardar(_eventos("a", 5000, desfase_s=-0.3), "eventos_libro")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.estado == DESFASE
    assert r.p1_s == pytest.approx(-0.295, abs=0.003)
    assert r.suelo_s == pytest.approx(-0.294, abs=0.003)
    assert "antes de que el exchange" in r.conclusion()


def test_deriva_medida_en_ms_por_hora(lake):
    lake.guardar(_eventos("a", 20000, desfase_s=0.5, deriva_s_h=0.05), "eventos_libro")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.deriva_ms_h == pytest.approx(50, abs=3)
    assert r.estado == DERIVA


def test_salto_de_sincronizacion_parte_la_deriva(lake):
    """Un salto (resincronización del reloj) abre un segmento nuevo: la deriva no se mezcla con el salto."""
    lake.guardar(_eventos("a", 20000, desfase_s=0.2, deriva_s_h=0.0, salto=(3600, 1.0)), "eventos_libro")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.saltos == 1 and r.segmentos == 2
    assert abs(r.deriva_ms_h) < 3


def test_rest_hora_posterior_a_la_recepcion_es_desfase_y_anterior_es_rancia(lake):
    lake.guardar(_cotizaciones("a", 3000, desfase_s=-0.5) + _cotizaciones("b", 3000, desfase_s=0.0, rancia_s=2.0),
                 "cotizaciones")
    resultados = medir_relojes(lake.consultar)
    a, b = _por(resultados, "a", "cotizaciones"), _por(resultados, "b", "cotizaciones")
    assert a.frac_posterior_recepcion == pytest.approx(1.0)
    assert a.estado == DESFASE
    assert b.frac_posterior_recepcion == 0 and b.frac_anterior_solicitud == pytest.approx(1.0)
    assert b.estado == RANCIA and "no sirve para medir el reloj" in b.conclusion()
    assert b.rtt_min_s == pytest.approx(0.1, abs=0.002)


def test_desfase_estimado_con_rtt_de_la_fuente_rest(lake):
    """Cristian: desfase ≈ suelo − rtt/2. El RTT del REST del mismo exchange acota la latencia mínima."""
    lake.guardar(_eventos("a", 5000, desfase_s=-0.3, latencia_media_s=0.01), "eventos_libro")
    lake.guardar(_cotizaciones("a", 3000, desfase_s=-0.3, rtt_s=0.01), "cotizaciones")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.rtt_min_s == pytest.approx(0.01, abs=0.002)
    assert r.desfase_estimado_s == pytest.approx(-0.3, abs=0.01)


def test_datos_insuficientes(lake):
    lake.guardar(_eventos("a", 50, desfase_s=0.0), "eventos_libro")
    r = _por(medir_relojes(lake.consultar), "a")
    assert r.estado == INSUFICIENTE
    assert "datos insuficientes" in r.conclusion()


def test_incertidumbre_de_un_par_y_diagnostico_comun(lake):
    lake.guardar(_eventos("a", 5000, -0.3, deriva_s_h=-0.1, semilla=1)
                 + _eventos("b", 5000, -0.3, deriva_s_h=-0.1, latencia_media_s=0.08, semilla=2), "eventos_libro")
    lake.guardar(_cotizaciones("a", 3000, -0.3, rtt_s=0.02) + _cotizaciones("b", 3000, -0.3, rtt_s=0.05),
                 "cotizaciones")
    resultados = medir_relojes(lake.consultar)
    u_rec = incertidumbre_lead_lag(resultados, "a", "b", "recepcion")
    u_ex = incertidumbre_lead_lag(resultados, "a", "b", "exchange")
    # recepción: la diferencia de latencias típicas (≈ (0.08 − 0.02)·ln2 ≈ 42 ms) más el margen de los RTT
    assert 0.04 < u_rec < 0.15
    # exchange: los suelos coinciden; queda el margen de la latencia mínima desconocida (≤ RTT)
    assert 0.015 < u_ex < 0.08
    assert math.isnan(incertidumbre_lead_lag(resultados, "a", "zzz", "exchange"))
    assert "común" in diagnostico_comun(resultados)


def test_guardar_relojes_con_hasta_utc(lake):
    lake.guardar(_eventos("a", 5000, desfase_s=0.0), "eventos_libro")
    resultados = medir_relojes(lake.consultar)
    ejecutado = pd.Timestamp("2026-11-22 15:00", tz="UTC")
    guardar_relojes(resultados, lake, ejecutado)
    df = lake.consultar(f"SELECT * FROM {FUENTE_RELOJES}")
    assert len(df) == len(resultados)
    assert {"hasta_utc", "estado", "conclusion", "deriva_ms_h", "metodo"} <= set(df.columns)
    assert pd.to_datetime(df.hasta_utc, utc=True).max() <= ejecutado  # DuckDB puede devolver naive
