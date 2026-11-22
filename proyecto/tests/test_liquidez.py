import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.liquidez import (FUENTE_LIQUIDEZ, estudiar_liquidez, guardar_estudio_liquidez, lambda_kyle,
                                     medidas_trades, spreads_trades)
from radar.mercado import Libro, Nivel

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def libros(segundos=120, mid=lambda s: 100.0, desfase=0.0, exchange="kraken"):
    """Un libro por segundo (en s + desfase): bid mid − 0,5 y ask mid + 0,5 (100 bps con mid 100)."""
    filas = []
    for s in range(segundos):
        t, m = T0 + pd.Timedelta(seconds=s + desfase), mid(s)
        filas.append(Libro(exchange, "BTC/EUR", (Nivel(m - 0.5, 1), Nivel(m - 50, 1)),
                           (Nivel(m + 0.5, 1), Nivel(m + 50, 1)), t, t).a_fila(2))
    return pd.DataFrame(filas)


def trades(*filas, exchange="kraken"):
    return pd.DataFrame([{"exchange": exchange, "recibido_utc": T0 + pd.Timedelta(seconds=s), "precio": p,
                          "cantidad": q, "lado_agresor": lado} for s, p, q, lado in filas],
                        columns=["exchange", "recibido_utc", "precio", "cantidad", "lado_agresor"])


def test_spread_efectivo_conocido_con_el_mid_estrictamente_anterior():
    # El mid pasa de 100 a 101 justo en el segundo 10: un trade en ese mismo instante usa todavía el mid 100.
    lb = libros(mid=lambda s: 100.0 if s < 10 else 101.0)
    tr = trades((5, 100.5, 1.0, "buy"), (6, 99.6, 1.0, "sell"), (10, 100.5, 1.0, "buy"))
    m = medidas_trades(lb, tr, horizontes=(5,))
    assert m["mid_antes"].tolist() == [100.0, 100.0, 100.0]
    assert m["efectivo_bps"].tolist() == pytest.approx([100.0, 80.0, 100.0])
    assert m["cotizado_bps"].tolist() == pytest.approx([100.0, 100.0, 100.0])
    # Realizado a 5 s del tercero: el mid ya es 101, el comprador pagó por debajo: 2 · (100,5 − 101) / 100.
    assert m["realizado_5_bps"].iloc[2] == pytest.approx(2 * (100.5 - 101) / 100 * 1e4)
    assert m["impacto_5_bps"].iloc[2] == pytest.approx(2 * (101 - 100) / 100 * 1e4)


def test_efectivo_es_realizado_mas_impacto_en_cada_trade():
    rng = np.random.default_rng(1)
    camino = 100 + np.cumsum(rng.normal(scale=0.05, size=400))
    lb = libros(segundos=400, mid=lambda s: float(camino[s]))
    filas = [(s + 0.3, float(camino[s]) + rng.choice([-0.5, 0.5]) + rng.normal(scale=0.02), rng.uniform(0.01, 1),
              rng.choice(["buy", "sell"])) for s in range(1, 330)]
    m = medidas_trades(lb, trades(*filas), horizontes=(1, 5, 60))
    for h in (1, 5, 60):
        completas = m.dropna(subset=[f"realizado_{h}_bps"])
        assert len(completas) > 250
        assert np.allclose(completas.efectivo_bps, completas[f"realizado_{h}_bps"] + completas[f"impacto_{h}_bps"],
                           rtol=0, atol=1e-9)


def test_resumen_ponderado_por_volumen_y_simple():
    lb = libros()
    # Dos trades: uno grande con efectivo 100 bps y uno pequeño con 80 bps.
    tr = trades((5, 100.5, 3.0, "buy"), (8, 99.6, 1.0, "sell"))
    (r,) = spreads_trades(lb, tr, horizontes=(5,), minimo=1)
    assert r.efectivo_bps == pytest.approx(90.0) and r.efectivo_vw_bps == pytest.approx(95.0)
    assert r.cotizado_bps == pytest.approx(100.0) and r.n_trades == 2 and r.n_segundos == 2
    assert r.realizado_bps + r.impacto_bps == pytest.approx(r.efectivo_bps)
    assert r.hasta_utc == T0 + pd.Timedelta(seconds=8)
    assert r.estado == "medido" and "spread efectivo" in r.conclusion()
    assert r.a_fila()["estudio"] == "spread_trades"
    pocos = spreads_trades(lb, tr, horizontes=(5,), minimo=10)[0]
    assert pocos.estado == "datos insuficientes" and "hacen falta 10" in pocos.conclusion()


def test_lambda_de_kyle_recupera_la_pendiente():
    """Δmid (bps) en cada intervalo de 5 s = 0,8 · volumen firmado (BTC) + ruido."""
    rng = np.random.default_rng(7)
    n_int, lam = 400, 0.8
    volumen = rng.normal(scale=2.0, size=n_int)
    m = [50_000.0]
    for v in volumen:
        m.append(m[-1] * (1 + (lam * v + rng.normal(scale=0.5)) / 1e4))
    # Libros en s + 0,5: el libro de cada intervalo j (segundos 5j .. 5j + 4) tiene el mid tras su flujo.
    lb = libros(segundos=5 * n_int, mid=lambda s: m[s // 5 + 1], desfase=0.5)
    filas = [(5 * j + 0.2, m[j], abs(v) / 2, "buy" if v > 0 else "sell") for j, v in enumerate(volumen)]
    filas += [(5 * j + 0.3, m[j], abs(v) / 2, "buy" if v > 0 else "sell") for j, v in enumerate(volumen)]
    tr = trades(*sorted(filas))
    (r,) = lambda_kyle(lb, tr, intervalos_s=(5,), minimo=100)
    assert r.lambda_bps_btc == pytest.approx(lam, abs=0.05)
    assert abs(r.t) > 10 and r.estado == "impacto significativo"
    assert r.lambda_bps_100k == pytest.approx(r.lambda_bps_btc * 100_000 / r.precio_medio)
    assert "por cada 100.000 €" in r.conclusion()
    assert lambda_kyle(lb, tr.head(20), intervalos_s=(5,), minimo=10_000)[0].estado == "datos insuficientes"


def test_estudio_desde_el_lake_y_guardado(tmp_path):
    lake = LakeParquet(tmp_path)
    lb = libros(segundos=200)
    tr = trades(*[(s + 0.4, 100.5 if s % 2 else 99.5, 0.1, "buy" if s % 2 else "sell") for s in range(1, 190)])
    lake.guardar(lb.to_dict("records"), "libros_flujo")
    lake.guardar(tr.assign(hora_exchange_utc=tr.recibido_utc, trade_id="x").to_dict("records"), "trades")
    spreads, lambdas = estudiar_liquidez(lake.consultar)
    assert {r.horizonte_s for r in spreads} >= {5, 60} and {r.intervalo_s for r in lambdas} == {5, 60}
    ahora = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")
    guardar_estudio_liquidez(spreads + lambdas, lake, ahora)
    leido = lake.consultar(f"SELECT * FROM {FUENTE_LIQUIDEZ}")
    assert len(leido) == len(spreads) + len(lambdas)
    assert set(leido.estudio) == {"spread_trades", "lambda_kyle"} and leido.hasta_utc.notna().all()


def test_con_los_eventos_del_websocket_usa_el_mid_exacto_antes_de_cada_trade(tmp_path):
    """El libro de cada segundo (`libros_flujo`) puede tener hasta 1 s de antigüedad: con `eventos_libro` el mid es el
    del último cambio del libro antes del trade."""
    from radar.analisis.liquidez import medidas_trades, mids_exactos
    t0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")
    ev = lambda s, tipo, lado, precio, cantidad: {"exchange": "kraken", "recibido_utc": t0 + pd.Timedelta(seconds=s),
                                                   "hora_exchange_utc": t0 + pd.Timedelta(seconds=s), "tipo": tipo,
                                                   "lado": lado, "precio": precio, "cantidad": cantidad,
                                                   "secuencia": np.nan}
    lake = LakeParquet(tmp_path)
    lake.guardar([ev(0, "snapshot", "bid", 100.0, 1), ev(0, "snapshot", "ask", 101.0, 1),
                  ev(0.5, "update", "ask", 100.5, 1)], "eventos_libro")  # el ask baja medio segundo después
    mids = mids_exactos(lake.consultar)
    assert list(mids["mid"]) == [100.5, 100.25] and list(mids["cotizado_bps"]) == pytest.approx(
        [1 / 100.5 * 1e4, 0.5 / 100.25 * 1e4])
    m = medidas_trades(mids, trades((0.6, 100.5, 0.1, "buy")), horizontes=(5,))
    assert m["mid_antes"].iloc[0] == 100.25  # el del cambio de 0,5 s, no el de la foto de 0 s
    assert m["efectivo_bps"].iloc[0] == pytest.approx(2 * (100.5 - 100.25) / 100.25 * 1e4)
