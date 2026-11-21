import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.ejecucion import (cargar_libros, comparar_estrategias, desplazar, ejecutar_plan, plan_todo_de_golpe,
                             plan_twap)
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-21 10:00:00", tz="UTC")


def libro(segundo, subida=0.0, exchange="kraken"):
    """Libro fijo: asks 100 × 1, 101 × 1, 102 × 100; bids 99 × 100. `subida` desplaza todos los precios (€)."""
    t = T0 + pd.Timedelta(seconds=segundo)
    return Libro(exchange, "BTC/EUR", (Nivel(99 + subida, 100),),
                 (Nivel(100 + subida, 1), Nivel(101 + subida, 1), Nivel(102 + subida, 100)), t, t)


def test_desplazar_mueve_todos_los_precios():
    d = desplazar(libro(0), 100)  # +100 bps = +1 %
    assert [n.precio for n in d.asks] == pytest.approx([101, 102.01, 103.02]) and d.bids[0].precio == pytest.approx(99.99)
    assert d.asks[0].cantidad == 1 and d.recibido_utc == T0


def test_planes():
    assert plan_todo_de_golpe(150) == [(0.0, 150)]
    assert plan_twap(150, trozos=3, duracion_s=60) == [(0.0, 50), (20.0, 50), (40.0, 50)]
    with pytest.raises(ValueError):
        plan_twap(150, trozos=0, duracion_s=60)


def test_twap_evita_el_slippage_en_un_libro_que_se_rellena():
    libros = [libro(s) for s in range(0, 61)]
    golpe = ejecutar_plan(libros, plan_todo_de_golpe(150), T0, comision=0, estrategia="golpe")
    twap = ejecutar_plan(libros, plan_twap(150, 3, 60), T0, comision=0, estrategia="twap")
    # De golpe: 1 BTC a 100 € y 50 € a 101 €. En trozos de 50 €, todo cabe en el mejor ask (100 €).
    assert golpe.cantidad_btc == pytest.approx(1 + 50 / 101) and twap.cantidad_btc == pytest.approx(1.5)
    assert golpe.coste_temporal_eur > twap.coste_temporal_eur and twap.coste_timing_eur == pytest.approx(0)
    assert golpe.mid_decision == 99.5 and twap.completa


def test_impacto_permanente_encarece_los_trozos_siguientes():
    libros = [libro(s) for s in range(0, 61)]
    r = ejecutar_plan(libros, plan_twap(150, 3, 60), T0, comision=0.001, impacto_bps_por_100k=100_000)
    impactos = [t.impacto_bps for t in r.trozos]
    assert impactos == pytest.approx([0, 50, 100])  # 50 € y 100 € ya ejecutados antes de cada trozo
    assert r.coste_impacto_eur > 0 and r.comisiones_eur == pytest.approx(r.importe_eur * 0.001)
    partes = r.coste_temporal_eur + r.coste_impacto_eur + r.coste_timing_eur + r.comisiones_eur
    assert r.shortfall_eur == pytest.approx(partes)  # el shortfall se reparte en cuatro piezas, sin resto
    assert r.shortfall_bps == pytest.approx(r.shortfall_eur / (r.cantidad_btc * r.mid_decision) * 1e4)


def test_esperar_cuesta_si_el_precio_sube_riesgo_de_timing():
    libros = [libro(s, subida=s / 10) for s in range(0, 61)]  # el precio sube 0,10 € por segundo
    golpe = ejecutar_plan(libros, plan_todo_de_golpe(50), T0, comision=0)
    twap = ejecutar_plan(libros, plan_twap(50, 2, 60), T0, comision=0)
    assert golpe.coste_timing_eur == pytest.approx(0) and twap.coste_timing_eur > 0


def test_sin_libro_cerca_del_momento_del_trozo_no_se_simula():
    libros = [libro(0), libro(1), libro(50)]  # el trozo del segundo 30 no tiene foto cerca
    assert ejecutar_plan(libros, plan_twap(50, 2, 60), T0, comision=0) is None


def test_comparar_estrategias_en_ventanas_sin_solaparse():
    libros = [libro(s) for s in range(0, 300)]
    resumen = comparar_estrategias(libros, 150, trozos=3, duracion_s=60, comision=0, impactos=(0, 5), minimo=3)
    claves = [(r.estrategia, r.impacto_bps_por_100k) for r in resumen]
    assert claves == [("todo de golpe", 0), ("twap", 0), ("todo de golpe", 5), ("twap", 5)]
    golpe, twap = resumen[0], resumen[1]
    assert golpe.n == twap.n == 4  # ventanas de 60 s que caben enteras en 300 s: 0, 60, 120, 180
    assert twap.media_bps < golpe.media_bps and twap.desviacion_bps == pytest.approx(0)
    assert "twap" in twap.conclusion() and "bps" in twap.conclusion()
    pocos = comparar_estrategias(libros[:61], 150, trozos=3, duracion_s=60, comision=0, impactos=(0,), minimo=3)
    assert "datos insuficientes" in pocos[0].conclusion()


def test_cargar_libros_desde_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([libro(s).a_fila(50) for s in (2, 0, 1)] + [libro(0, exchange="okx").a_fila(50)], "libros")
    libros = cargar_libros(lake.consultar, "kraken")
    assert [l.recibido_utc for l in libros] == [T0, T0 + pd.Timedelta(seconds=1), T0 + pd.Timedelta(seconds=2)]
    assert libros[0].asks == libro(0).asks


def test_comparar_texto():
    from radar.ejecucion import comparar_texto
    libros = [libro(s) for s in range(0, 300)]
    frases = comparar_texto(comparar_estrategias(libros, 150, trozos=3, duracion_s=60, comision=0, impactos=(0,),
                                                 minimo=3))
    assert len(frases) == 1 and frases[0].startswith("Impacto 0 bps por 100.000 €: TWAP cuesta ")
    assert "bps menos de media que todo de golpe" in frases[0]
    assert frases[0].endswith("más barato de media: TWAP.")


def test_las_estrategias_se_comparan_en_las_mismas_ventanas():
    libros = [libro(s) for s in range(0, 300) if not 75 <= s <= 90]  # falta el trozo del segundo 80
    golpe, twap = comparar_estrategias(libros, 150, trozos=3, duracion_s=60, comision=0, impactos=(0,), minimo=1)
    assert golpe.n == twap.n == 3  # la ventana del segundo 60 se descarta para las dos, no solo para TWAP


# Paso 3 · Almgren-Chriss.

def test_almgren_chriss_sin_urgencia_es_twap():
    from radar.ejecucion import plan_almgren_chriss
    assert plan_almgren_chriss(100, trozos=4, duracion_s=40, urgencia=0) == plan_twap(100, 4, 40)
    casi_cero = plan_almgren_chriss(100, trozos=4, duracion_s=40, urgencia=1e-6)  # continuidad: tiende a TWAP
    assert [i for _, i in casi_cero] == pytest.approx([25, 25, 25, 25], rel=1e-4)


def test_almgren_chriss_con_urgencia_compra_mas_al_principio():
    from radar.ejecucion import plan_almgren_chriss
    plan = plan_almgren_chriss(100, trozos=4, duracion_s=40, urgencia=3)
    importes = [i for _, i in plan]
    assert [s for s, _ in plan] == [0, 10, 20, 30] and sum(importes) == pytest.approx(100)
    assert importes == sorted(importes, reverse=True) and importes[0] > 25  # decreciente: front-loading
    # x(t) = X · sinh(κ(T − t)) / sinh(κT): lo pendiente tras el primer trozo, con κT = 3 y t = T/4.
    assert 100 - importes[0] == pytest.approx(100 * np.sinh(3 * 0.75) / np.sinh(3))
    casi_golpe = plan_almgren_chriss(100, trozos=4, duracion_s=40, urgencia=50)
    assert casi_golpe[0][1] > 99.9  # urgencia enorme: casi todo de golpe


def test_estimar_volatilidad_e_impacto_temporal():
    from radar.ejecucion import estimar_impacto_temporal, estimar_volatilidad
    # El mid sube y baja 1 € cada segundo: varianza de 1 €² por segundo.
    zigzag = [libro(s, subida=(s % 2)) for s in range(0, 101)]
    assert estimar_volatilidad(zigzag) == pytest.approx(1.0)
    # Asks cada 0,10 € con 1 BTC cada uno: comprar q BTC cuesta de media ≈ 0,05 · q € más por BTC.
    t = T0
    escalera = Libro("kraken", "BTC/EUR", (Nivel(99, 100),), tuple(Nivel(100 + 0.1 * i, 1) for i in range(50)), t, t)
    assert estimar_impacto_temporal([escalera], cantidades_btc=(5, 10, 20)) == pytest.approx(0.05, rel=0.1)


def test_comparar_estrategias_incluye_almgren_chriss_por_urgencia():
    libros = [libro(s) for s in range(0, 300)]
    resumen = comparar_estrategias(libros, 150, trozos=3, duracion_s=60, comision=0, impactos=(0,), minimo=3,
                                   urgencias=(1, 3))
    assert [r.estrategia for r in resumen] == ["todo de golpe", "twap", "almgren-chriss κT=1", "almgren-chriss κT=3"]
