"""Hayashi-Yoshida y lead-lag de Hoffmann-Rosenbaum-Yoshida sobre series asíncronas sintéticas (sin red)."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.hayashi_yoshida import (CONFIRMADA, FUENTE_HY, INSUFICIENTE, NS, SIMULTANEO, correlacion_hy,
                                            covarianza_hy, curva_hy, estudiar_hayashi_yoshida,
                                            guardar_hayashi_yoshida, mids_desde_eventos, mids_flujo, rotar)

INICIO = pd.Timestamp("2026-11-22 10:00", tz="UTC")


def _browniano(rng, duracion_s, paso_s=0.001, sigma=1.0):
    t = np.arange(0, duracion_s, paso_s)
    return t, np.cumsum(rng.normal(0, sigma * math.sqrt(paso_s), len(t)))


def _observar(rng, t, x, intensidad, retardo_s=0.0):
    """Observa x(t − retardo) en tiempos de Poisson: el que observa con retardo SIGUE al otro."""
    n = rng.poisson(intensidad * (t[-1] - t[0]))
    tiempos = np.sort(rng.uniform(t[0] + max(retardo_s, 0) + 0.01, t[-1], n))
    idx = np.searchsorted(t, tiempos - retardo_s, side="right") - 1
    return (tiempos * NS).astype(np.int64), x[idx]


def _bruto(ta, xa, tb, xb, theta=0):
    """Definición directa: Σ_I Σ_J ΔX(I) ΔY(J) 1{I ∩ (J − θ) ≠ ∅}, con intervalos (izquierda, derecha]."""
    total = 0.0
    for i in range(1, len(ta)):
        for j in range(1, len(tb)):
            if tb[j - 1] - theta < ta[i] and ta[i - 1] < tb[j] - theta:
                total += (xa[i] - xa[i - 1]) * (xb[j] - xb[j - 1])
    return total


def test_intervalos_que_no_se_solapan_no_cuentan():
    ta, xa = np.array([0, 1, 2]) * NS, np.array([0.0, 1.0, 3.0])
    tb, xb = np.array([5, 6, 7]) * NS, np.array([0.0, 2.0, -1.0])
    assert covarianza_hy(ta, xa, tb, xb) == 0.0
    # solo se solapan (1, 2] y (1.5, 3]: 2 · 4
    assert covarianza_hy(ta, xa, np.array([1.5, 3]) * NS, np.array([0.0, 4.0])) == pytest.approx(8.0)


def test_coincide_con_la_definicion_directa():
    rng = np.random.default_rng(3)
    ta, tb = np.sort(rng.integers(0, 10 * NS, 40)), np.sort(rng.integers(0, 10 * NS, 30))
    ta, tb = np.unique(ta), np.unique(tb)
    xa, xb = rng.normal(size=len(ta)).cumsum(), rng.normal(size=len(tb)).cumsum()
    for theta in (0, int(0.37 * NS), int(-1.2 * NS)):
        assert covarianza_hy(ta, xa, tb, xb, theta) == pytest.approx(_bruto(ta, xa, tb, xb, theta))
    rejilla = np.arange(-2 * NS, 2 * NS + 1, NS // 10)
    curva = curva_hy(ta, xa, tb, xb, rejilla[0], NS // 10, len(rejilla), limite_pares=50)
    assert curva == pytest.approx([_bruto(ta, xa, tb, xb, th) for th in rejilla])


def test_recupera_la_correlacion_de_series_asincronas():
    rng = np.random.default_rng(7)
    t, w1 = _browniano(rng, 3000)
    _, w2 = _browniano(rng, 3000)
    rho = 0.6
    x, y = w1, rho * w1 + math.sqrt(1 - rho ** 2) * w2
    ta, xa = _observar(rng, t, x, 2.0)
    tb, yb = _observar(rng, t, y, 3.0)
    assert correlacion_hy(ta, xa, tb, yb) == pytest.approx(rho, abs=0.05)


@pytest.mark.parametrize("retardo", [0.25, -0.4])
def test_recupera_el_retardo_de_un_lider(retardo):
    """B = A desplazado: B(t) = A(t − retardo). Con retardo > 0, A lidera y θ̂ ≈ +retardo."""
    rng = np.random.default_rng(11)
    t, x = _browniano(rng, 2000)
    if retardo > 0:
        ta, xa = _observar(rng, t, x, 5.0)
        tb, xb = _observar(rng, t, x, 4.0, retardo)
    else:
        ta, xa = _observar(rng, t, x, 5.0, -retardo)
        tb, xb = _observar(rng, t, x, 4.0)
    paso = NS // 100
    rejilla = np.arange(-2 * NS, 2 * NS + 1, paso)
    curva = curva_hy(ta, xa, tb, xb, rejilla[0], paso, len(rejilla))
    theta = rejilla[np.argmax(np.abs(curva))] / NS
    assert theta == pytest.approx(retardo, abs=0.02)


def test_rotar_conserva_los_incrementos_y_la_duracion():
    t = np.array([0, 1, 3, 6, 10]) * NS
    x = np.array([0.0, 1.0, -1.0, 2.0, 2.5])
    tr, xr = rotar(t, x, 2)
    assert np.all(np.diff(tr) > 0)
    assert sorted(np.round(np.diff(xr), 9)) == sorted(np.round(np.r_[np.diff(x), 0.0], 9))
    assert tr[0] == t[0]


def test_mids_desde_eventos_reconstruye_el_libro():
    h = lambda s: INICIO + pd.Timedelta(seconds=s)
    filas = [  # (recibido, tipo, lado, precio, cantidad, secuencia)
        (0.0, "update", "bid", 100.5, 1, 11),     # llega antes del snapshot (buffer de Bitvavo) y vale: 11 > 10
        (0.1, "snapshot", "bid", 100, 1, 10), (0.1, "snapshot", "bid", 99, 1, 10),
        (0.1, "snapshot", "ask", 101, 1, 10), (0.1, "snapshot", "ask", 102, 1, 10),
        (0.2, "update", "ask", 101, 0, 12),       # borra el mejor ask
        (0.3, "update", "bid", 99, 2, 13),        # no cambia el mid: no se emite
        (0.4, "update", "bid", 100.5, 0, 14),     # borra el mejor bid
    ]
    eventos = pd.DataFrame([{"recibido_utc": h(r), "hora_exchange_utc": h(r - 0.05), "tipo": ti, "lado": la,
                             "precio": float(p), "cantidad": float(c), "secuencia": float(s)}
                            for r, ti, la, p, c, s in filas])
    mids = mids_desde_eventos(eventos, con_buffer=True)
    assert mids["mid"].tolist() == [100.75, 101.25, 101.0]
    assert mids["recibido_ns"].iloc[0] == h(0.1).value
    assert mids["exchange_ns"].iloc[-1] == h(0.35).value


def _libro_sintetico(exchange, tiempos_s, mids, desfase_exchange_s=0.0):
    filas, previo = [], None
    for k, (t, m) in enumerate(zip(tiempos_s, mids)):
        recibido = INICIO + pd.Timedelta(seconds=float(t))
        hora = recibido - pd.Timedelta(seconds=0.02 + desfase_exchange_s)
        tipo = "snapshot" if k == 0 else "update"
        niveles = [("bid", m - 0.5, 1.0), ("ask", m + 0.5, 1.0)]
        if previo is not None:
            niveles += [("bid", previo - 0.5, 0.0), ("ask", previo + 0.5, 0.0)]
        filas += [{"exchange": exchange, "recibido_utc": recibido, "hora_exchange_utc": hora, "tipo": tipo,
                   "lado": lado, "precio": p, "cantidad": c, "secuencia": float(k)} for lado, p, c in niveles]
        previo = m
    return filas


def _lake_con_lider(tmp_path, retardo_s=0.3, duracion_s=1800):
    rng = np.random.default_rng(5)
    t, x = _browniano(rng, duracion_s, sigma=0.5)
    precio = 50000 + np.round(x * 20)          # en euros, con tick de 1 €
    lake = LakeParquet(tmp_path)
    ta, _ = _observar(rng, t, precio, 3.0)
    tb, _ = _observar(rng, t, precio, 3.0, retardo_s)
    filas = []
    for nombre, tiempos, retardo in (("a", ta / NS, 0.0), ("b", tb / NS, retardo_s)):
        idx = np.searchsorted(t, tiempos - retardo, side="right") - 1
        filas += _libro_sintetico(nombre, tiempos, precio[idx])
    lake.guardar(filas, "eventos_libro")
    return lake


def test_estudio_sobre_el_lake_encuentra_al_lider_y_guarda(tmp_path):
    lake = _lake_con_lider(tmp_path)
    mids = mids_flujo(lake.consultar)
    assert set(mids.exchange) == {"a", "b"}
    resultados = estudiar_hayashi_yoshida(mids, rango_s=1.0, paso_s=0.01, n_sustitutos=39, minimo=200)
    rec = next(r for r in resultados if r.base == "recepcion")
    assert rec.lider == "a" and rec.seguidor == "b"
    assert rec.retardo_ms == pytest.approx(300, abs=30)   # resolución ≈ intervalo entre cambios / 10
    assert rec.estado == CONFIRMADA
    assert rec.p_sustitutos == pytest.approx(1 / 40)
    assert len(rec.curva_rho) == len(rec.curva_theta_s) == 201
    assert "a anticipa a b" in rec.conclusion()
    ejecutado = pd.Timestamp("2026-11-22 15:00", tz="UTC")
    guardar_hayashi_yoshida(resultados, lake, ejecutado)
    df = lake.consultar(f"SELECT * FROM {FUENTE_HY}")
    assert len(df) == len(resultados) == 2
    assert {"hasta_utc", "theta_s", "estado", "conclusion", "incertidumbre_s"} <= set(df.columns)


def test_incertidumbre_del_reloj_y_simultaneidad(tmp_path):
    lake = _lake_con_lider(tmp_path, retardo_s=0.0)
    mids = mids_flujo(lake.consultar)
    r = estudiar_hayashi_yoshida(mids, rango_s=1.0, paso_s=0.01, n_sustitutos=39, minimo=200,
                                 incertidumbres={("a", "b", "recepcion"): 0.05})
    rec = next(x for x in r if x.base == "recepcion")
    assert abs(rec.theta_s) <= 0.01
    assert rec.estado == SIMULTANEO
    assert rec.incertidumbre_s == 0.05 and rec.supera_incertidumbre is False


def test_datos_insuficientes(tmp_path):
    lake = _lake_con_lider(tmp_path, duracion_s=60)
    r = estudiar_hayashi_yoshida(mids_flujo(lake.consultar), n_sustitutos=19, minimo=1000)
    assert all(x.estado == INSUFICIENTE for x in r)
    assert "datos insuficientes" in r[0].conclusion()
