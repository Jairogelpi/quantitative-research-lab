import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.ofi import impacto_contemporaneo, ofi, pares_ofi_retorno
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def m(*filas):
    return np.array(filas, dtype=float)


def test_ofi_de_cont_kukanov_stoikov_en_el_mejor_nivel():
    # Mismo precio en los dos lados: bid 2 → 5 BTC (+3) y ask 4 → 1 BTC (se comieron 3 asks: +3).
    assert ofi(m([100], [100]), m([2], [5]), m([101], [101]), m([4], [1]))[0] == pytest.approx(6)
    # Sube el bid: toda su cantidad nueva es presión compradora.
    assert ofi(m([100], [100.5]), m([2], [7]), m([101], [101]), m([4], [4]))[0] == pytest.approx(7)
    # Baja el bid: se fue toda la cantidad anterior.
    assert ofi(m([100], [99.5]), m([2], [7]), m([101], [101]), m([4], [4]))[0] == pytest.approx(-2)
    # Baja el ask: llegó oferta nueva (presión vendedora).
    assert ofi(m([100], [100]), m([2], [2]), m([101], [100.5]), m([4], [3]))[0] == pytest.approx(-3)


def test_ofi_multinivel_suma_los_niveles():
    bp, ap = m([100, 99], [100, 99]), m([101, 102], [101, 102])
    bq, aq = m([1, 1], [2, 4]), m([1, 1], [1, 1])
    assert ofi(bp, bq, ap, aq)[0] == pytest.approx(1 + 3)
    assert ofi(bp[:, :1], bq[:, :1], ap[:, :1], aq[:, :1])[0] == pytest.approx(1)


def libro(segundo, bid, cantidad_bid):
    t = T0 + pd.Timedelta(seconds=segundo)
    return Libro("kraken", "BTC/EUR", (Nivel(bid, cantidad_bid), Nivel(bid - 1, 1)),
                 (Nivel(bid + 1, 1), Nivel(bid + 2, 1)), t, t)


def test_pares_ofi_retorno_desde_los_libros_guardados_y_sin_cruzar_cortes(tmp_path):
    lake = LakeParquet(tmp_path)
    segundos = [0, 1, 2, 3, 30, 31]  # entre 3 y 30 hubo un corte
    libros = [libro(s, 100 + i, 1 + i) for i, s in enumerate(segundos)]
    lake.guardar([l.a_fila(2) for l in libros], "libros")
    pares = pares_ofi_retorno(lake.consultar, horizontes=(1,), niveles=(1, 2))
    uno = pares[pares.banda_bps == 1].sort_values("recibido_utc")
    # Fotos con OFI y retorno futuro válidos: 1 y 2. La 3 tiene su futuro al otro lado del corte, la 30 no tiene
    # OFI (el intervalo 3 → 30 cruza el corte) y la 31 no tiene futuro.
    assert list(uno.recibido_utc) == [T0 + pd.Timedelta(seconds=s) for s in (1, 2)]
    # El bid sube cada segundo: OFI del mejor nivel = cantidad nueva del bid; el ask también sube (+ su cantidad previa).
    assert list(uno.imbalance) == pytest.approx([2 + 1, 3 + 1])
    assert uno.ret_bps.iloc[0] == pytest.approx((102.5 / 101.5 - 1) * 1e4)  # mid del segundo 1 → del segundo 2
    assert set(pares.banda_bps) == {1, 2} and {"ret_actual_bps", "spread_bps", "ret_pasado_bps"} <= set(pares.columns)


def test_impacto_contemporaneo_estima_bps_por_btc():
    rng = np.random.default_rng(0)
    flujo = rng.normal(size=500)
    pares = pd.DataFrame({"exchange": "kraken", "banda_bps": 1, "horizonte_rondas": 1,
                          "recibido_utc": [T0 + pd.Timedelta(seconds=i) for i in range(500)], "imbalance": flujo,
                          "ret_actual_bps": 0.3 * flujo + rng.normal(scale=0.1, size=500)})
    (r,) = impacto_contemporaneo(pares)
    assert r.beta_bps_por_btc == pytest.approx(0.3, abs=0.02) and r.t_hac > 10 and r.r2 > 0.8
    assert r.estado == "explica el precio" and "+0.30" in r.conclusion()
    (pocos,) = impacto_contemporaneo(pares.head(50))
    assert pocos.estado == "datos insuficientes" and "hacen falta 200" in pocos.conclusion()
