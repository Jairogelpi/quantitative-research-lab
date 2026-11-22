"""OFI evento a evento (Cont, Kukanov y Stoikov, 2014) sobre libros reconstruidos sintéticos (sin red)."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.hayashi_yoshida import NS
from radar.analisis.imbalance import CONFIRMADA, INSUFICIENTE, SIN_EVIDENCIA
from radar.analisis.ofi_eventos import (EXPLICA, FUENTE_OFI_EVENTOS, contribuciones, estudiar_ofi_eventos,
                                        estudio_ofi_eventos, guardar_ofi_eventos, intervalos_ofi)

INICIO = pd.Timestamp("2026-11-22 10:00", tz="UTC")


# --- contribución de cada evento -------------------------------------------------------------------------------------

@pytest.mark.parametrize("caso, antes, despues, esperado", [
    # (bid, cantidad bid, ask, cantidad ask)
    ("bid sube: orden que mejora el precio", (100, 1, 102, 1), (101, 2, 102, 1), 2.0),
    ("bid igual, cantidad sube", (100, 1, 102, 1), (100, 3, 102, 1), 2.0),
    ("bid igual, cantidad baja", (100, 3, 102, 1), (100, 1, 102, 1), -2.0),
    ("bid baja: se fue la cola entera", (100, 1, 102, 1), (99, 5, 102, 1), -1.0),
    ("ask baja: orden de venta que mejora", (100, 1, 102, 1), (100, 1, 101.5, 4), -4.0),
    ("ask sube: se fue la cola del ask", (100, 1, 102, 1), (100, 1, 103, 2), 1.0),
    ("ask igual, cantidad baja", (100, 1, 102, 1), (100, 1, 102, 0.5), 0.5),
    ("sin cambios", (100, 1, 102, 1), (100, 1, 102, 1), 0.0),
])
def test_contribucion_de_cada_evento(caso, antes, despues, esperado):
    bp, bq, ap, aq = (np.array([a, d], float) for a, d in zip(antes, despues))
    assert contribuciones(bp, bq, ap, aq) == pytest.approx([esperado]), caso


def test_contribuciones_de_una_secuencia():
    bp = np.array([100, 101, 101, 100])
    bq = np.array([1, 2, 5, 4])
    ap = np.array([102, 102, 101.5, 101.5])
    aq = np.array([1, 1, 3, 1])
    # 1: bid sube (+2); 2: bid +3, ask baja (−3); 3: bid baja (−5), ask cantidad −2 (+2)
    assert contribuciones(bp, bq, ap, aq) == pytest.approx([2.0, 0.0, -3.0])


# --- agregación en intervalos ----------------------------------------------------------------------------------------

def _mejores(filas, exchange="x"):
    """filas: (segundo, tramo, bid, cantidad bid, ask, cantidad ask)."""
    return pd.DataFrame([{"exchange": exchange, "recibido_ns": int((INICIO + pd.Timedelta(seconds=s)).value),
                          "exchange_ns": int((INICIO + pd.Timedelta(seconds=s)).value), "tramo": t,
                          "bid": b, "bid_cantidad": qb, "ask": a, "ask_cantidad": qa}
                         for s, t, b, qb, a, qa in filas])


def test_agrega_ofi_y_cambio_del_mid_por_intervalo():
    mejores = _mejores([
        (0.1, 0, 100, 1, 101, 1),    # intervalo 0: el primero no tiene mid anterior, se descarta
        (1.2, 0, 100, 3, 101, 1),    # intervalo 1: +2
        (1.7, 0, 101, 1, 102, 1),    # intervalo 1: bid sube (+1), ask sube (+1) → +2; mid 100,5 → 101,5
        (3.4, 0, 101, 1, 102, 4),    # intervalo 3: ask +3 → −3 (el 2 no tiene eventos: OFI 0, mid igual)
        (4.5, 1, 90, 1, 91, 1),      # nuevo tramo (snapshot): el intervalo 4 se descarta
        (5.5, 1, 90, 2, 91, 1),      # intervalo 5: +1
    ])
    r = intervalos_ofi(mejores, intervalos_s=(1.0,), ticks={"x": 0.5}, hueco_s=30.0)
    r = r.set_index("intervalo")
    assert r.index.tolist() == [1, 2, 3, 5]
    assert r["ofi"].tolist() == pytest.approx([4.0, 0.0, -3.0, 1.0])
    assert r["dp_ticks"].tolist() == pytest.approx([2.0, 0.0, 0.0, 0.0])
    assert r.loc[1, "dp_bps"] == pytest.approx((101.5 / 100.5 - 1) * 1e4)
    assert r.loc[1, "n_eventos"] == 2 and r.loc[2, "n_eventos"] == 0
    # el siguiente intervalo del mismo tramo, para la predicción
    assert r.loc[1, "dp_siguiente_ticks"] == 0.0
    assert math.isnan(r.loc[3, "dp_siguiente_ticks"])
    assert r.loc[1, "profundidad"] == pytest.approx(np.mean([(3 + 1) / 2, (1 + 1) / 2]))
    assert set(r["intervalo_s"]) == {1.0} and set(r["exchange"]) == {"x"}


def test_un_hueco_largo_corta_el_tramo():
    mejores = _mejores([(0.1, 0, 100, 1, 101, 1), (1.1, 0, 100, 2, 101, 1),
                        (100.1, 0, 100, 3, 101, 1), (101.1, 0, 100, 4, 101, 1)])
    r = intervalos_ofi(mejores, intervalos_s=(1.0,), ticks={"x": 1.0}, hueco_s=30.0)
    # sin hueco habría 100 intervalos; con él, solo el 1 y el 101 (cada tramo pierde su primero)
    assert r["intervalo"].tolist() == [1, 101]
    assert r["ofi"].tolist() == pytest.approx([1.0, 1.0])


def test_intervalos_de_varios_tamanos():
    mejores = _mejores([(s / 10, 0, 100, 1 + (s % 3), 101, 1) for s in range(0, 300)])
    r = intervalos_ofi(mejores, intervalos_s=(1.0, 10.0), ticks={"x": 1.0})
    assert set(r["intervalo_s"]) == {1.0, 10.0}
    # el OFI total no depende del tamaño del intervalo (salvo el primero de cada uno, que se descarta)
    uno, diez = r[r.intervalo_s == 1.0], r[r.intervalo_s == 10.0]
    assert len(uno) == 29 and len(diez) == 2


# --- regresión contemporánea, profundidad y predicción --------------------------------------------------------------

def _intervalos(rng, n, beta, ruido=0.3, siguiente=0.0, profundidades=(1.0,), exchange="x", intervalo_s=10.0):
    ofi = rng.normal(0, 2, n)
    profundidad = np.repeat(profundidades, int(math.ceil(n / len(profundidades))))[:n]
    b = beta / profundidad
    dp = b * ofi + rng.normal(0, ruido, n)
    dp_sig = np.r_[siguiente * ofi[:-1] + rng.normal(0, ruido, n - 1), np.nan]
    inicio = INICIO.value + (np.arange(n) * intervalo_s * NS).astype(np.int64)
    return pd.DataFrame({"exchange": exchange, "intervalo_s": intervalo_s, "intervalo": np.arange(n),
                         "inicio_ns": inicio, "fin_ns": inicio + int(intervalo_s * NS), "n_eventos": 5, "ofi": ofi,
                         "dp_ticks": dp, "dp_bps": dp * 0.2, "dp_siguiente_ticks": dp_sig,
                         "dp_siguiente_bps": dp_sig * 0.2, "profundidad": profundidad})


def test_regresion_recupera_beta_conocido():
    rng = np.random.default_rng(1)
    impactos, _ = estudiar_ofi_eventos(_intervalos(rng, 2000, beta=0.5), minimo=200)
    (i,) = impactos
    assert i.beta_ticks_por_btc == pytest.approx(0.5, abs=0.02)
    assert i.beta_bps_por_btc == pytest.approx(0.1, abs=0.005)
    assert i.r2 > 0.9 and i.t_hac > 10
    assert i.estado == EXPLICA
    assert "explica" in i.conclusion() and "R²" in i.conclusion()
    fila = i.a_fila()
    assert fila["hasta_utc"] == pd.Timestamp(INICIO.value + 2000 * 10 * NS, tz="UTC")
    assert {"estado", "conclusion", "desde_utc", "r2_fotos"} <= set(fila)


def test_beta_inversamente_proporcional_a_la_profundidad():
    """β_i = c / AD_i (λ = 1): la regresión log-log de las ventanas recupera c y λ."""
    rng = np.random.default_rng(2)
    # 10 s por intervalo, ventanas de 30 min = 180 intervalos; 8 ventanas con profundidades distintas
    profundidades = (0.5, 1.0, 2.0, 4.0, 0.7, 1.5, 3.0, 6.0)
    datos = _intervalos(rng, 180 * 8, beta=2.0, ruido=0.05, profundidades=profundidades)
    (i,), _ = estudiar_ofi_eventos(datos, minimo=200)
    assert i.ventanas_profundidad == 8
    assert i.lambda_profundidad == pytest.approx(1.0, abs=0.05)
    assert i.c_profundidad == pytest.approx(2.0, rel=0.1)


def test_datos_insuficientes():
    rng = np.random.default_rng(3)
    impactos, predicciones = estudiar_ofi_eventos(_intervalos(rng, 50, beta=0.5), minimo=200)
    assert impactos[0].estado == INSUFICIENTE and predicciones[0].estado == INSUFICIENTE
    assert "datos insuficientes" in impactos[0].conclusion()
    assert "datos insuficientes" in predicciones[0].conclusion()


def test_prediccion_confirmada_y_sin_evidencia():
    rng = np.random.default_rng(4)
    con = _intervalos(rng, 3000, beta=0.5, siguiente=0.3, exchange="a")
    sin = _intervalos(rng, 3000, beta=0.5, siguiente=0.0, exchange="b")
    _, predicciones = estudiar_ofi_eventos(pd.concat([con, sin], ignore_index=True), minimo=200)
    por = {p.exchange: p for p in predicciones}
    assert por["a"].estado == CONFIRMADA
    assert por["a"].beta_descubrimiento == pytest.approx(0.3, abs=0.03)
    assert por["a"].t_confirmacion > 2
    assert por["b"].estado == SIN_EVIDENCIA
    assert "siguiente" in por["a"].conclusion()
    assert por["a"].a_fila()["hasta_utc"] is not pd.NaT


# --- extremo a extremo sobre el lake ---------------------------------------------------------------------------------

def _eventos_sinteticos(rng, exchange="x", duracion_s=900, paso_s=0.2):
    """Libro de un nivel con tick 1. Tres eventos: sube cantidad del bid, sube el precio un tick, lo baja."""
    filas, b, qb, qa, k = [], 1000.0, 1.0, 1.0, 0

    def fila(t, tipo, lado, p, c):
        recibido = INICIO + pd.Timedelta(seconds=t)
        filas.append({"exchange": exchange, "recibido_utc": recibido,
                      "hora_exchange_utc": recibido - pd.Timedelta(milliseconds=20), "tipo": tipo, "lado": lado,
                      "precio": p, "cantidad": c, "secuencia": float(k)})

    fila(0.0, "snapshot", "bid", b, qb)
    fila(0.0, "snapshot", "ask", b + 1, qa)
    for t in np.arange(paso_s, duracion_s, paso_s):
        k += 1
        u = rng.random()
        if u < 0.4:                       # llega cantidad al bid: OFI +, el mid no se mueve
            qb += 1
            fila(t, "update", "bid", b, qb)
        elif u < 0.7:                     # sube un tick: OFI = 1 + qa
            fila(t, "update", "bid", b, 0.0)
            fila(t, "update", "ask", b + 1, 0.0)
            b, qb, qa = b + 1, 1.0, 1.0
            fila(t, "update", "bid", b, qb)
            fila(t, "update", "ask", b + 1, qa)
        else:                             # baja un tick: OFI = −qb − 1
            fila(t, "update", "bid", b, 0.0)
            fila(t, "update", "ask", b + 1, 0.0)
            b, qb, qa = b - 1, 1.0, 1.0
            fila(t, "update", "bid", b, qb)
            fila(t, "update", "ask", b + 1, qa)
    return filas


def _libros_sinteticos(rng, exchange="x", duracion_s=900):
    filas, mid = [], 1000.5
    for s in range(duracion_s):
        mid += rng.choice([-1, 0, 1])
        q = float(rng.integers(1, 5))
        filas.append({"exchange": exchange, "recibido_utc": INICIO + pd.Timedelta(seconds=s),
                      "bid_precios": [mid - 0.5], "bid_cantidades": [q], "ask_precios": [mid + 0.5],
                      "ask_cantidades": [1.0]})
    return filas


def test_estudio_sobre_el_lake_y_guarda(tmp_path):
    rng = np.random.default_rng(5)
    lake = LakeParquet(tmp_path)
    lake.guardar(_eventos_sinteticos(rng), "eventos_libro")
    lake.guardar(_libros_sinteticos(rng), "libros")
    impactos, predicciones = estudio_ofi_eventos(lake.consultar, desde_utc=INICIO - pd.Timedelta(hours=1),
                                                 intervalos_s=(1.0, 10.0), ticks={"x": 1.0}, minimo=50)
    assert {(i.exchange, i.intervalo_s) for i in impactos} == {("x", 1.0), ("x", 10.0)}
    uno = next(i for i in impactos if i.intervalo_s == 1.0)
    assert uno.n > 800 and uno.n_eventos > 4000
    assert uno.estado == EXPLICA and uno.beta_ticks_por_btc > 0 and uno.r2 > 0.3
    assert math.isfinite(uno.r2_fotos)          # comparación con el OFI de las fotos de 1 s, misma ventana
    assert uno.hasta_utc <= INICIO + pd.Timedelta(seconds=900)
    ejecutado = pd.Timestamp("2026-11-22 15:00", tz="UTC")
    guardar_ofi_eventos(impactos, predicciones, lake, ejecutado)
    df = lake.consultar(f"SELECT * FROM {FUENTE_OFI_EVENTOS}")
    assert len(df) == len(impactos) + len(predicciones) == 4
    assert set(df["estudio"]) == {"ofi_eventos_impacto", "ofi_eventos_prediccion"}
    assert {"hasta_utc", "estado", "conclusion", "metodo"} <= set(df.columns)


def test_estudio_sin_fotos_ni_eventos(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(_eventos_sinteticos(np.random.default_rng(6), duracion_s=60), "eventos_libro")
    impactos, _ = estudio_ofi_eventos(lake.consultar, ticks={"x": 1.0}, con_fotos=False)
    assert all(math.isnan(i.r2_fotos) for i in impactos)
    vacio = estudio_ofi_eventos(lake.consultar, desde_utc=INICIO + pd.Timedelta(days=1), con_fotos=False)
    assert vacio == ([], [])
