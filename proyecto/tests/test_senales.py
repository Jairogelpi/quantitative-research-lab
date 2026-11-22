import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.senales import aporte_senales, correlaciones, decaimiento, interacciones, tabla_senales
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def tabla_sintetica(n=2000, semilla=0):
    """lider predice el retorno a 5 rondas; ofi es casi una copia de lider (redundante); imbalance solo funciona
    con spread alto; el efecto de lider se acumula en 2 rondas y luego se queda."""
    rng = np.random.default_rng(semilla)
    lider, imbalance = rng.normal(size=n), rng.normal(size=n)
    ofi = lider + rng.normal(scale=0.2, size=n)
    spread = rng.uniform(0, 2, size=n)
    ruido = lambda: rng.normal(scale=0.5, size=n)
    tabla = pd.DataFrame({"exchange": "kraken", "recibido_utc": [T0 + pd.Timedelta(seconds=i) for i in range(n)],
                          "lider": lider, "ofi": ofi, "imbalance": imbalance, "spread_bps": spread,
                          "volatilidad_bps": rng.uniform(0, 1, size=n), "ret_pasado_bps": rng.normal(size=n)})
    for k in (1, 2, 3, 5, 10):
        tabla[f"ret_{k}"] = 0.3 * lider * min(k, 2) / 2 + 0.4 * imbalance * (spread > 1) + ruido()
    return tabla


def test_aporte_separa_informacion_propia_de_redundante():
    r = {a.senal: a for a in aporte_senales(tabla_sintetica(), minimo=500)}
    assert r["lider"].estado == "aporta información propia" and r["lider"].con_cual == "ofi"
    assert r["ofi"].estado == "redundante con las demás" and r["ofi"].correlacion_max > 0.9
    assert "correlación máxima" in r["ofi"].conclusion()
    (pocos, *_) = aporte_senales(tabla_sintetica(n=600), minimo=500)
    assert pocos.estado == "datos insuficientes"


def test_interaccion_con_el_spread_confirmada_y_sin_interaccion_con_la_volatilidad():
    r = {(i.senal, i.contexto): i for i in interacciones(tabla_sintetica(4000), minimo=500)}
    spread = r[("imbalance", "spread_bps")]
    assert spread.estado == "confirmada" and spread.coef_interaccion > 0.3 and abs(spread.coef_bajo) < 0.1
    assert "más fuerte cuando el spread es alto" in spread.conclusion()
    assert r[("imbalance", "volatilidad_bps")].estado == "sin evidencia"
    assert "la volatilidad alta" in r[("imbalance", "volatilidad_bps")].conclusion()


def test_decaimiento_mide_el_tiempo_a_la_mitad_y_la_persistencia():
    r = {d.senal: d for d in decaimiento(tabla_sintetica(), horizontes=(1, 2, 3, 5, 10), minimo=500)}
    lider = r["lider"]
    assert lider.estado == "con efecto" and lider.tiempo_mitad == 1 and lider.persistencia == pytest.approx(1, abs=0.15)
    assert lider.betas[0] == pytest.approx(0.15, abs=0.05) and "la mitad del efecto llega a 1 rondas" in lider.conclusion()
    assert r["imbalance"].a_fila()["estudio"] == "decaimiento"


def test_tabla_senales_desde_el_lake(tmp_path):
    lake, cot, des, libros = LakeParquet(tmp_path), [], [], []
    for i in range(80):
        t = T0 + pd.Timedelta(seconds=i)
        for ex, mid in (("kraken", 100 + i * 0.01), ("okx", 100 + i * 0.02)):
            cot.append({"exchange": ex, "solicitado_utc": t, "recibido_utc": t, "latencia_s": 0.1, "mid": mid,
                        "spread_bps": 1.0})
            des.append({"exchange": ex, "recibido_utc": t, "banda_bps": 5.0, "imbalance": 0.5, "cubierta": True})
            libros.append(Libro(ex, "BTC/EUR", tuple(Nivel(mid - 0.005 - j, 1) for j in range(5)),
                                tuple(Nivel(mid + 0.005 + j, 1) for j in range(5)), t, t).a_fila(5))
    lake.guardar(cot, "cotizaciones"), lake.guardar(des, "desequilibrios"), lake.guardar(libros, "libros")
    tabla = tabla_senales(lake.consultar, horizontes=(5,))
    k = tabla[tabla.exchange == "kraken"].reset_index(drop=True)
    # lider de kraken = retorno de okx de la ronda ANTERIOR (8 → 9): el de la ronda 9 → 10 llega más tarde que la
    # foto propia de la ronda 10 si okx responde más lento; el futuro a 5 rondas es el de su propio mid.
    assert k.loc[10, "lider"] == pytest.approx((100.18 / 100.16 - 1) * 1e4)
    assert k.loc[10, "ret_5"] == pytest.approx((100.15 / 100.10 - 1) * 1e4)
    assert k.loc[10, "imbalance"] == 0.5 and not np.isnan(k.loc[10, "ofi"]) and k["volatilidad_bps"].notna().any()
    assert list(correlaciones(tabla, "kraken").columns) == ["imbalance", "ofi", "lider", "spread_bps", "volatilidad_bps"]


def test_lider_no_se_cuela_el_futuro_por_la_latencia(tmp_path):
    """Un único precio, sin lead-lag real. okx responde 0,55 s más tarde que kraken, así que su foto de la ronda t
    ve el precio de t + 0,6 y kraken el de t + 0,05: la señal no puede tomar el retorno de okx de esa ronda."""
    rng = np.random.default_rng(3)
    n, paso = 2500, 0.05
    precio = 50_000 * np.cumprod(1 + rng.normal(scale=0.3, size=int((n + 2) / paso)) / 1e4)
    en = lambda segundo: precio[int(round(segundo / paso))]
    lake, cot, des, libros = LakeParquet(tmp_path), [], [], []
    for i in range(1, n):
        t = T0 + pd.Timedelta(seconds=i)
        for ex, latencia in (("kraken", 0.05), ("okx", 0.6)):
            mid = en(i + latencia)
            cot.append({"exchange": ex, "solicitado_utc": t, "recibido_utc": t + pd.Timedelta(seconds=latencia),
                        "latencia_s": latencia, "mid": mid, "spread_bps": 1.0})
            des.append({"exchange": ex, "recibido_utc": t + pd.Timedelta(seconds=latencia), "banda_bps": 5.0,
                        "imbalance": rng.uniform(-1, 1), "cubierta": True})
            libros.append(Libro(ex, "BTC/EUR", (Nivel(mid - 0.5, rng.uniform(1, 2)), Nivel(mid - 1, 1)),
                                (Nivel(mid + 0.5, rng.uniform(1, 2)), Nivel(mid + 1, 1)), t,
                                t + pd.Timedelta(seconds=latencia)).a_fila(2))
    lake.guardar(cot, "cotizaciones"), lake.guardar(des, "desequilibrios"), lake.guardar(libros, "libros")
    tabla = tabla_senales(lake.consultar, niveles_ofi=2, horizontes=(5,))
    r = {(a.exchange, a.senal): a for a in aporte_senales(tabla, minimo=500)}
    assert r[("kraken", "lider")].estado == "sin evidencia"
