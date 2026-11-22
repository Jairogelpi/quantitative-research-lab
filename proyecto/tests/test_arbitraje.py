"""Arbitraje entre exchanges: ventaja bruta y neta, episodios, tamaño ejecutable y alcance con nuestra latencia."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.arbitraje import (
    ALCANZABLES,
    FUENTE_ARBITRAJE,
    INALCANZABLES,
    INSUFICIENTE,
    NS,
    SIN_OPORTUNIDADES,
    TODOS,
    alcanzable,
    episodios,
    estudiar_arbitraje,
    guardar_arbitraje,
    serie_par,
    tamano_ejecutable,
    ventaja_bps,
)
from radar.analisis.registro import estadistico
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def mejores(*filas):
    """Mejores niveles como los da `mejores_desde_eventos`: (segundo, bid, bid_cant, ask, ask_cant)."""
    return pd.DataFrame({"recibido_ns": [T0.value + int(s * NS) for s, *_ in filas],
                         "bid": [f[1] for f in filas], "bid_cantidad": [f[2] for f in filas],
                         "ask": [f[3] for f in filas], "ask_cantidad": [f[4] for f in filas]})


def libro(exchange, bids, asks, t=T0):
    return Libro(exchange, "BTC/EUR", tuple(Nivel(p, c) for p, c in bids), tuple(Nivel(p, c) for p, c in asks), t, t)


# --- ventaja bruta y neta -------------------------------------------------------------------------------------------

def test_ventaja_bruta_y_neta_tras_comisiones_en_las_dos_patas():
    assert ventaja_bps(100.0, 101.0) == pytest.approx(100.0)
    # Vender en B cobra 101 · (1 − 0,25 %) y comprar en A cuesta 100 · (1 + 0,20 %), sobre lo que cuesta comprar.
    assert ventaja_bps(100.0, 101.0, 0.002, 0.0025) == pytest.approx((101 * 0.9975 - 100 * 1.002) / 100 * 1e4)
    assert ventaja_bps(100.0, 100.5, 0.004, 0.004) < 0 < ventaja_bps(100.0, 100.5)
    np.testing.assert_allclose(ventaja_bps(np.array([100.0, 200.0]), np.array([99.0, 202.0])), [-100.0, 100.0])


# --- episodios ------------------------------------------------------------------------------------------------------

def test_episodios_son_las_rachas_maximas_con_ventaja_neta_positiva():
    compra = mejores((0, 99.0, 1, 100.0, 0.3), (6, 99.0, 1, 103.0, 0.3))           # A: ask 100 hasta el segundo 6
    venta = mejores((0, 99.0, 1, 99.5, 1), (1, 101.0, 0.2, 101.5, 1), (2, 102.0, 0.5, 102.5, 1),
                    (3, 99.5, 1, 100.5, 1), (5, 100.5, 0.4, 101.0, 1))              # B: bid sube, baja y vuelve
    s = serie_par(compra, venta)
    assert s["t_ns"].tolist() == [T0.value + k * NS for k in (0, 1, 2, 3, 5, 6)]
    assert s["bruto_bps"].tolist() == pytest.approx([-100.0, 100.0, 200.0, -50.0, 50.0, -242.718446], rel=1e-6)
    e = episodios(s)
    assert len(e) == 2
    primero, segundo = e.iloc[0], e.iloc[1]
    assert primero["inicio_ns"] == T0.value + NS and primero["fin_ns"] == T0.value + 3 * NS
    assert primero["duracion_s"] == pytest.approx(2.0) and not primero["censurado"]
    assert primero["max_neto_bps"] == pytest.approx(200.0)
    assert primero["media_neto_bps"] == pytest.approx(150.0)                       # 1 s a 100 y 1 s a 200 bps
    # Tamaño en el mejor nivel en el pico: min(0,3 BTC de ask en A, 0,5 BTC de bid en B) · (102 − 100).
    assert primero["cantidad_tope_btc"] == pytest.approx(0.3)
    assert primero["beneficio_tope_eur"] == pytest.approx(0.3 * 2.0)
    assert segundo["duracion_s"] == pytest.approx(1.0) and segundo["max_neto_bps"] == pytest.approx(50.0)
    # Con comisiones de 1 % por pata ya no queda ninguno.
    assert episodios(serie_par(compra, venta, 0.01, 0.01)).empty


def test_un_episodio_que_llega_al_final_queda_censurado():
    compra = mejores((0, 99.0, 1, 100.0, 1), (4, 99.0, 1, 100.0, 1))
    venta = mejores((0, 99.0, 1, 99.5, 1), (2, 101.0, 1, 101.5, 1))
    e = episodios(serie_par(compra, venta))
    assert len(e) == 1 and e["censurado"].iloc[0] and e["duracion_s"].iloc[0] == pytest.approx(2.0)


def test_un_libro_sin_mensajes_mas_alla_del_silencio_maximo_no_cuenta():
    # B deja de publicar 60 s: su último bid (101) no se usa más allá de `max_silencio_s`.
    compra = mejores(*[(s, 99.0, 1, 100.0, 1) for s in range(0, 61, 2)])
    venta = mejores((0, 101.0, 1, 101.5, 1))
    s = serie_par(compra, venta, max_silencio_s=10)
    assert s["valido"].tolist()[:6] == [True] * 6 and not s["valido"].iloc[6]
    e = episodios(s)
    assert len(e) == 1 and e["duracion_s"].iloc[0] == pytest.approx(12.0)     # de 0 a 12 s (primera fila inválida)


# --- tamaño ejecutable ----------------------------------------------------------------------------------------------

def test_tamano_ejecutable_barre_los_dos_libros_hasta_que_la_ventaja_marginal_deja_de_ser_positiva():
    a = libro("kraken", [(99.0, 1)], [(100.0, 1), (100.5, 1), (102.0, 5)])
    b = libro("okx", [(101.0, 0.5), (100.8, 2), (99.0, 5)], [(101.5, 1)])
    r = tamano_ejecutable(a, b)
    # [0; 0,5]: 101 − 100; [0,5; 1]: 100,8 − 100; [1; 2]: 100,8 − 100,5; en 2 BTC el ask pasa a 102: se para.
    assert r.cantidad_btc == pytest.approx(2.0)
    assert r.coste_eur == pytest.approx(200.5) and r.ingreso_eur == pytest.approx(0.5 * 101 + 1.5 * 100.8)
    assert r.beneficio_eur == pytest.approx(0.5 * 101 + 1.5 * 100.8 - 200.5)
    con = tamano_ejecutable(a, b, 0.004, 0.004)                    # con comisiones solo vale el primer tramo
    assert con.cantidad_btc == pytest.approx(0.5)
    assert con.beneficio_eur == pytest.approx(0.5 * (101 * 0.996 - 100 * 1.004))
    sin = tamano_ejecutable(a, libro("okx", [(99.5, 1)], [(101.5, 1)]))
    assert sin.cantidad_btc == 0 and sin.beneficio_eur == 0


# --- alcance con nuestra latencia -----------------------------------------------------------------------------------

def test_un_episodio_es_alcanzable_solo_si_dura_al_menos_el_mayor_rtt_de_las_dos_patas():
    assert not alcanzable(0.3, 0.2, 0.4)
    assert alcanzable(0.4, 0.2, 0.4) and alcanzable(0.5, 0.2, 0.4)
    assert not alcanzable(10.0, math.nan, 0.1)                       # sin RTT medido no se da por alcanzable
    np.testing.assert_array_equal(alcanzable(np.array([0.1, 1.0]), 0.2, 0.3), [False, True])


# --- desde el lake --------------------------------------------------------------------------------------------------

def _evento(ex, s, tipo, lado, precio, cantidad):
    t = T0 + pd.Timedelta(seconds=s)
    return {"exchange": ex, "recibido_utc": t, "hora_exchange_utc": t, "tipo": tipo, "lado": lado, "precio": precio,
            "cantidad": cantidad, "secuencia": np.nan}


def _lake(tmp_path):
    """Kraken y OKX 120 s. Kraken: ask 100 siempre. OKX: bid 99,9 salvo entre 50 y 52,5 s, cuando sube a 101,5 (con
    1 BTC): +150 bps brutos, +49,7 netos con taker (0,80 % + 0,20 %). Un libro por segundo en `libros_flujo`."""
    ev = [_evento("kraken", 0, "snapshot", "bid", 99.8, 1), _evento("kraken", 0, "snapshot", "ask", 100.0, 2),
          _evento("okx", 0, "snapshot", "bid", 99.9, 1), _evento("okx", 0, "snapshot", "ask", 100.1, 1)]
    for s in range(1, 120):
        ev.append(_evento("kraken", s + 0.1, "update", "bid", 99.8, 1 + s / 1000))   # latidos: el libro sigue vivo
        ev.append(_evento("okx", s + 0.2, "update", "bid", 99.0, 1 + s / 1000))
    ev += [_evento("okx", 50.0, "update", "ask", 100.1, 0), _evento("okx", 50.0, "update", "ask", 101.6, 1),
           _evento("okx", 50.0, "update", "bid", 101.5, 1)]
    ev += [_evento("okx", 52.5, "update", "bid", 101.5, 0), _evento("okx", 52.5, "update", "ask", 100.1, 1)]
    ev.sort(key=lambda e: e["recibido_utc"])
    lake = LakeParquet(tmp_path)
    lake.guardar(ev, "eventos_libro")
    fotos = []
    for s in range(120):
        t = T0 + pd.Timedelta(seconds=s + 0.5)
        fotos.append(libro("kraken", [(99.8, 1)], [(100.0, 2), (100.5, 3), (103.0, 5)], t).a_fila(50))
        en = 50 <= s + 0.5 < 52.5
        bids = [(101.5, 1), (101.4, 2), (99.0, 5)] if en else [(99.9, 1), (99.0, 5)]
        asks = [(101.6, 1)] if en else [(100.1, 1)]
        fotos.append(libro("okx", bids, asks, t).a_fila(50))
    lake.guardar(fotos, "libros_flujo")
    return lake


def test_estudio_desde_el_lake_episodios_tamano_alcance_y_guardado(tmp_path):
    lake = _lake(tmp_path)
    desde = T0 + pd.Timedelta(seconds=10)
    resumenes, eps = estudiar_arbitraje(lake.consultar, desde, rtt_s={"kraken": 0.5, "okx": 3.0}, minimo=60)
    taker = {(r.compra, r.venta): r for r in resumenes if r.escenario == "taker"}
    kr_okx = taker[("kraken", "okx")]
    assert kr_okx.n_episodios == 1 and kr_okx.estado == INALCANZABLES    # 2,5 s < RTT de OKX (3 s)
    assert kr_okx.max_neto_bps == pytest.approx((101.5 * 0.998 - 100 * 1.008) / 100 * 1e4)
    assert kr_okx.duracion_max_s == pytest.approx(2.5)
    assert kr_okx.segundos_validos == pytest.approx(109.2)    # de 10 s al último mensaje (119,2 s)
    assert kr_okx.frac_tiempo_positivo == pytest.approx(2.5 / kr_okx.segundos_validos)
    e = eps[(eps.escenario == "taker") & (eps.compra == "kraken") & (eps.venta == "okx")].iloc[0]
    # Fotos de 50,5, 51,5 y 52,5 s: dentro del episodio solo las dos primeras (en 52,5 ya terminó). Barrido: 1 BTC
    # a 100 contra 101,5, y 1 BTC a 100 contra 101,4 (el 2.º ask es 100,5: 101,4 · 0,998 − 100,5 · 1,008 < 0).
    assert e["fuente_tamano"] == "libros_flujo" and e["cantidad_btc"] == pytest.approx(2.0)
    assert e["beneficio_eur"] == pytest.approx((101.5 + 101.4) * 0.998 - 200 * 1.008)
    assert not e["alcanzable"]
    assert taker[("okx", "kraken")].estado == SIN_OPORTUNIDADES
    # Con un RTT menor que la duración, el mismo episodio es alcanzable.
    resumenes2, _ = estudiar_arbitraje(lake.consultar, desde, rtt_s={"kraken": 0.5, "okx": 0.5}, minimo=60)
    r2 = next(r for r in resumenes2 if r.escenario == "taker" and (r.compra, r.venta) == ("kraken", "okx"))
    assert r2.estado == ALCANZABLES and r2.beneficio_alcanzable_eur == pytest.approx(r2.beneficio_total_eur)
    total = next(r for r in resumenes2 if r.escenario == "taker" and r.compra == TODOS)
    assert total.n_episodios == 1 and total.beneficio_total_eur == pytest.approx(r2.beneficio_total_eur)
    assert "EUR en kraken y BTC en okx" in r2.conclusion()
    # Sin comisiones el episodio también está; con muy pocos datos, insuficiente.
    assert any(r.escenario == "sin comisiones" and r.n_episodios == 1 for r in resumenes)
    corto, _ = estudiar_arbitraje(lake.consultar, desde, rtt_s={"kraken": 0.5, "okx": 0.5}, minimo=10_000)
    assert {r.estado for r in corto} == {INSUFICIENTE}

    ahora = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")
    guardar_arbitraje(resumenes, lake, ahora)
    leido = lake.consultar(f"SELECT * FROM {FUENTE_ARBITRAJE}")
    assert len(leido) == len(resumenes) and leido["hasta_utc"].notna().all() and leido["conclusion"].notna().all()
    # Estudio descriptivo: el registro global de pruebas no encuentra estadístico que corregir.
    assert all(estadistico(f) is None for f in leido.to_dict("records"))
