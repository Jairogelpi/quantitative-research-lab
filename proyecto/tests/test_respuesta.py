import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.respuesta import (FUENTE_RESPUESTA, eventos_trades, estudiar_respuesta,
                                      guardar_estudio_respuesta, respuesta_precio)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")
PASO_S = 0.1


def signos_independientes(n, semilla):
    return np.random.default_rng(semilla).choice([-1.0, 1.0], size=n)


def signos_correlacionados(n, alfa, semilla):
    """Rachas de signo aleatorio con longitud de Pareto (cola α): C(ℓ) ∝ ℓ^−(α − 1)."""
    rng, partes, total = np.random.default_rng(semilla), [], 0
    while total < n:
        largo = int(np.floor(rng.pareto(alfa) + 1))
        largo = min(largo, n)
        partes.append(np.full(largo, rng.choice([-1.0, 1.0])))
        total += largo
    return np.concatenate(partes)[:n]


def propagador(k, permanente, tau=10.0):
    """G(k) = permanente + (1 − permanente) · e^(−k/τ), en bps; G(1) ≈ 1."""
    k = np.asarray(k, dtype=float)
    return permanente + (1 - permanente) * np.exp(-(k - 1) / tau)


def mercado(signos, permanente, ruido_bps=0.05, semilla=0, cotizado_bps=2.0, exchange="kraken"):
    """Modelo de propagador (Bouchaud et al. 2004, ec. 12): m_n = Σ_{n'<n} G(n − n') ε_n' + ruido, en bps sobre
    100.000. Un cambio del libro 50 ms antes de cada trade fija el mid que ve ese trade."""
    n = len(signos)
    k = np.arange(1, 400)
    transitorio = np.concatenate([[0.0], propagador(k, permanente) - permanente])
    x = np.convolve(signos, transitorio)[:n]
    x += permanente * np.concatenate([[0.0], np.cumsum(signos)[:-1]])
    x += np.cumsum(np.random.default_rng(semilla + 1).normal(scale=ruido_bps, size=n))
    mid = 100_000 * (1 + x / 1e4)
    t_ns = (T0.value + (np.arange(n) * PASO_S * 1e9)).astype(np.int64)
    libros = pd.DataFrame({"exchange": exchange, "recibido_ns": t_ns - 50_000_000, "mid": mid,
                           "cotizado_bps": cotizado_bps})
    trades = pd.DataFrame({"exchange": exchange, "recibido_utc": pd.to_datetime(t_ns, utc=True),
                           "precio": mid, "cantidad": 0.01,
                           "lado_agresor": np.where(signos > 0, "buy", "sell")})
    return libros, trades


def test_con_signos_independientes_la_respuesta_es_el_propagador_y_es_transitoria():
    libros, trades = mercado(signos_independientes(60_000, 1), permanente=0.3)
    (r,) = respuesta_precio(libros, trades, retardo_max=100)
    esperado = propagador(np.array(r.retardos), 0.3)
    assert np.allclose(r.r_bps, esperado, atol=0.05)
    assert r.r1_bps == pytest.approx(1.0, abs=0.03) and r.error_r1_bps < 0.02
    assert r.persistencia == pytest.approx(0.3, abs=0.06)
    assert r.persistencia_propagador == pytest.approx(0.3, abs=0.08)
    assert r.estado == "impacto mayormente transitorio"
    # Signos independientes: C(ℓ) ≈ 0 y no hay ley de potencia que estimar.
    assert max(abs(c) for c in r.c) < 0.03 and r.estado_gamma == "datos insuficientes"
    texto = r.conclusion()
    assert "se queda" in texto and "se revierte" in texto and "datos insuficientes" in texto


def test_impacto_permanente_si_el_propagador_no_decae():
    libros, trades = mercado(signos_independientes(40_000, 2), permanente=1.0)
    (r,) = respuesta_precio(libros, trades, retardo_max=50)
    assert r.persistencia == pytest.approx(1.0, abs=0.1) and r.estado == "impacto permanente"
    assert "el 10" in r.conclusion() or "el 9" in r.conclusion()


def test_correlacion_de_signos_en_ley_de_potencia_recupera_gamma():
    signos = signos_correlacionados(200_000, alfa=1.5, semilla=3)  # γ = α − 1 = 0,5
    libros, trades = mercado(signos, permanente=0.3)
    (r,) = respuesta_precio(libros, trades, retardo_max=200)
    assert r.estado_gamma == "medido"
    assert r.gamma == pytest.approx(0.5, abs=0.15) and 0 < r.error_gamma < 0.2
    assert r.c[0] > 0.3 and r.c[-1] > 0


def test_con_signos_correlacionados_la_respuesta_crece_y_el_propagador_se_recupera():
    signos = signos_correlacionados(200_000, alfa=1.5, semilla=4)
    libros, trades = mercado(signos, permanente=0.3)
    (r,) = respuesta_precio(libros, trades, retardo_max=100)
    retardos = np.array(r.retardos)
    # R(ℓ) mezcla el impacto de un trade con el de los siguientes del mismo signo: queda por encima de G(ℓ).
    assert all(np.array(r.r_bps)[retardos >= 5] > propagador(retardos[retardos >= 5], 0.3) + 0.2)
    # Invirtiendo la relación de Bouchaud et al. (ec. 17) se recupera G.
    assert np.allclose(r.propagador_bps, propagador(retardos, 0.3), atol=0.15)
    assert r.persistencia_propagador == pytest.approx(0.3, abs=0.12)


def test_unidades_de_medio_spread_y_tiempo_fisico():
    libros, trades = mercado(signos_independientes(30_000, 5), permanente=1.0, cotizado_bps=4.0)
    (r,) = respuesta_precio(libros, trades, retardo_max=20, taus_s=(0.1, 1.0, 5.0))
    # Medio spread = 2 bps: R en medios spreads = R en bps / 2.
    assert np.allclose(r.r_medio_spread, np.array(r.r_bps) / 2, rtol=1e-6)
    assert r.medio_spread_bps == pytest.approx(2.0)
    # 0,1 s después de un trade el siguiente aún no ha movido el libro (llega 50 ms antes del trade siguiente,
    # es decir, a 50 ms): con impacto permanente G = 1, R(0,1 s) ≈ G(1) = 1 bps; R(1 s) ≈ 1 bps también.
    assert r.taus_s == [0.1, 1.0, 5.0]
    assert r.r_tiempo_bps[0] == pytest.approx(1.0, abs=0.05) and r.r_tiempo_bps[1] == pytest.approx(1.0, abs=0.1)


def test_datos_insuficientes():
    libros, trades = mercado(signos_independientes(300, 6), permanente=0.5)
    (r,) = respuesta_precio(libros, trades, retardo_max=20, minimo=1000)
    assert r.estado == "datos insuficientes" and "hacen falta 1000" in r.conclusion()


def test_trades_del_mismo_instante_y_signo_son_un_solo_evento():
    libros = pd.DataFrame({"exchange": "kraken", "recibido_ns": [T0.value], "mid": [100.0], "cotizado_bps": [2.0]})
    t = [T0 + pd.Timedelta(seconds=s) for s in (1, 1, 1, 2)]
    trades = pd.DataFrame({"exchange": "kraken", "recibido_utc": t, "precio": 100.0, "cantidad": [1.0, 2.0, 0.5, 1.0],
                           "lado_agresor": ["buy", "buy", "sell", "buy"]})
    ev = eventos_trades(libros, trades)
    assert ev["signo"].tolist() == [1.0, -1.0, 1.0] and ev["cantidad"].tolist() == [3.0, 0.5, 1.0]
    assert ev["n_trades"].tolist() == [2, 1, 1] and ev["mid_antes"].tolist() == [100.0] * 3
    assert len(eventos_trades(libros, trades, agrupar=False)) == 4


def test_estudio_desde_el_lake_y_guardado(tmp_path):
    """Libro reconstruido desde `eventos_libro`: el mid sube 1 bps medio segundo después de cada compra y baja tras
    cada venta, y vuelve a la mitad un segundo después (la mitad del impacto se queda)."""
    rng = np.random.default_rng(8)
    eventos, trades, mid = [], [], 100_000.0
    ev = lambda s, tipo, lado, precio: {"exchange": "kraken", "recibido_utc": T0 + pd.Timedelta(seconds=s),
                                        "hora_exchange_utc": T0 + pd.Timedelta(seconds=s), "tipo": tipo,
                                        "lado": lado, "precio": precio, "cantidad": 1.0, "secuencia": np.nan}

    def libro(s, m):
        return [ev(s, "snapshot" if s == 0 else "update", "bid", round(m - 5, 2)),
                ev(s, "snapshot" if s == 0 else "update", "ask", round(m + 5, 2))]

    eventos += libro(0, mid)
    for i in range(1500):
        s = 2.0 * (i + 1)
        signo = rng.choice([-1.0, 1.0])
        trades.append({"exchange": "kraken", "recibido_utc": T0 + pd.Timedelta(seconds=s), "precio": mid,
                       "cantidad": 0.1, "lado_agresor": "buy" if signo > 0 else "sell",
                       "hora_exchange_utc": T0 + pd.Timedelta(seconds=s), "trade_id": str(i)})
        anterior = mid
        mid = anterior * (1 + signo * 1e-4)
        eventos += [{**e, "cantidad": 0.0} for e in libro(s + 0.5, anterior)]  # borra los niveles viejos
        eventos += libro(s + 0.5, mid)
        mid = anterior * (1 + signo * 0.5e-4)
        eventos += [{**e, "cantidad": 0.0} for e in libro(s + 1.5, anterior * (1 + signo * 1e-4))]
        eventos += libro(s + 1.5, mid)
    lake = LakeParquet(tmp_path)
    lake.guardar(eventos, "eventos_libro")
    lake.guardar(trades, "trades")
    resultados = estudiar_respuesta(lake.consultar, retardo_max=10, taus_s=(1.0, 1.9), minimo=500)
    (r,) = resultados
    assert r.exchange == "kraken" and r.n_eventos == 1500
    # En tiempo físico: a 1 s el mid ha subido 1 bps; a 1,9 s, ya revertido a la mitad.
    assert r.r_tiempo_bps[0] == pytest.approx(1.0, abs=0.02) and r.r_tiempo_bps[1] == pytest.approx(0.5, abs=0.02)
    assert r.r1_bps == pytest.approx(0.5, abs=0.02) and r.hasta_utc == trades[-1]["recibido_utc"]
    ahora = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")
    guardar_estudio_respuesta(resultados, lake, ahora)
    leido = lake.consultar(f"SELECT * FROM {FUENTE_RESPUESTA}")
    assert len(leido) == 1 and leido.estudio.iloc[0] == "respuesta_precio"
    assert list(leido.retardos.iloc[0]) == r.retardos and len(leido.r_bps.iloc[0]) == len(r.retardos)
    assert leido.hasta_utc.notna().all() and leido.conclusion.iloc[0] == r.conclusion()
    # La ventana `desde_utc` deja fuera los trades anteriores.
    (tarde,) = estudiar_respuesta(lake.consultar, desde_utc=T0 + pd.Timedelta(seconds=2001), retardo_max=10,
                                   minimo=1)
    assert tarde.n_eventos == 500


def test_impacto_mixto_y_sin_determinar_segun_el_intervalo_de_la_persistencia():
    libros, trades = mercado(signos_independientes(60_000, 9), permanente=0.65)
    (r,) = respuesta_precio(libros, trades, retardo_max=50)
    assert r.persistencia == pytest.approx(0.65, abs=0.06) and r.estado == "impacto mixto"
    # Mismo modelo con mucho ruido y pocos eventos: el intervalo ± 2 errores cruza un umbral y no se decide.
    libros, trades = mercado(signos_independientes(2_000, 10), permanente=0.65, ruido_bps=1.0)
    (r,) = respuesta_precio(libros, trades, retardo_max=50, minimo=1000)
    assert r.error_persistencia > 0.1 and r.estado == "persistencia sin determinar"
    assert "se queda" in r.conclusion()
