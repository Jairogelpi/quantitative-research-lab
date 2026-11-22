import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.presion import (FUENTE_PRESION, estudiar_presion, exposicion_flujo, guardar_estudio_presion,
                                    interacciones_intensidad, intervalos_presion, relaciones_presion, vwap_mid)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")   # múltiplo de 60 s desde la época
S0 = T0.timestamp()


def mids(*cambios, exchange="kraken"):
    """Cambios del mid como los devuelve `mids_exactos`: (segundos desde T0, mid)."""
    return pd.DataFrame({"exchange": exchange,
                         "recibido_ns": [int(round((S0 + s) * 1e9)) for s, _ in cambios],
                         "mid": [float(m) for _, m in cambios], "cotizado_bps": 1.0})


def trades(*filas, exchange="kraken"):
    return pd.DataFrame([{"exchange": exchange, "recibido_utc": T0 + pd.Timedelta(seconds=s), "precio": p,
                          "cantidad": q, "lado_agresor": lado} for s, p, q, lado in filas],
                        columns=["exchange", "recibido_utc", "precio", "cantidad", "lado_agresor"])


def test_agregacion_por_intervalo_volumenes_imbalance_cvd_vwap_y_exposicion():
    m = mids((-1, 100), (5, 102), (31, 102.5))
    tr = trades((1, 101, 1.0, "buy"), (2, 102, 0.5, "buy"), (3, 99, 0.5, "sell"),  # intervalo [0, 10)
                (25, 100, 1.0, "sell"))                                             # [20, 30); [10, 20) vacío
    t = intervalos_presion(m, tr, 10).set_index("inicio_s")
    assert list(t.index - S0) == [0, 10, 20]
    a, vacio, c = t.iloc[0], t.iloc[1], t.iloc[2]
    assert (a.n_compras, a.n_ventas, a.n_trades) == (2, 1, 3)
    assert (a.compra_btc, a.venta_btc, a.firmado_btc) == pytest.approx((1.5, 0.5, 1.0))
    assert (a.compra_eur, a.venta_eur, a.firmado_eur) == pytest.approx((152.0, 49.5, 102.5))
    assert a.imbalance_btc == pytest.approx(0.5) and a.imbalance_n == pytest.approx(1 / 3)
    assert a.intensidad == pytest.approx(0.3)
    assert a.vwap == pytest.approx(201.5 / 2) and a.vwap_compra == pytest.approx(152 / 1.5)
    assert a.vwap_venta == pytest.approx(99.0)
    assert (a.neta_eur, a.bruta_eur, a.neta_bruta) == pytest.approx((102.5, 201.5, 102.5 / 201.5))
    # Mid exacto: 100 hasta el segundo 5, 102 después; medio tiempo a cada uno.
    assert (a.mid_inicio, a.mid_fin, a.mid_twap) == pytest.approx((100.0, 102.0, 101.0))
    assert a.dmid_bps == pytest.approx(200.0) and a.dmid_sig_bps == pytest.approx(0.0)
    # Una ventana vacía tiene volumen 0 pero imbalance y VWAP indefinidos (no 0).
    assert vacio.n_trades == 0 and vacio.firmado_btc == 0 and vacio.intensidad == 0
    assert np.isnan(vacio.imbalance_btc) and np.isnan(vacio.imbalance_n) and np.isnan(vacio.vwap)
    assert np.isnan(vacio.neta_bruta)
    assert list(t.cvd_btc) == pytest.approx([1.0, 1.0, 0.0])
    assert list(t.cvd_eur) == pytest.approx([102.5, 102.5, 2.5])
    assert c.imbalance_btc == -1 and c.vwap_compra != c.vwap_compra  # sin compras: VWAP de compras indefinido
    assert np.isnan(c.dmid_sig_bps)  # no hay intervalo siguiente con mid


def test_trades_fuera_del_libro_o_antes_del_inicio_no_cuentan():
    m = mids((-1, 100), (31, 100))
    tr = trades((-5, 100, 1.0, "buy"), (15, 100, 2.0, "buy"))
    t = intervalos_presion(m, tr, 10, desde_utc=T0 + pd.Timedelta(seconds=10))
    assert list(t.inicio_s - S0) == [10, 20]
    assert list(t.cvd_btc) == pytest.approx([2.0, 2.0])


def _tabla(n, rng, exchange="kraken", intervalo=10):
    imb = rng.uniform(-1, 1, n)
    return pd.DataFrame({"exchange": exchange, "intervalo_s": intervalo, "inicio_s": S0 + intervalo * np.arange(n),
                         "imbalance_btc": imb, "imbalance_n": np.clip(imb + rng.normal(0, 0.3, n), -1, 1),
                         "intensidad": rng.exponential(2.0, n), "n_trades": rng.integers(1, 50, n)})


def test_relacion_contemporanea_y_predictiva_recupera_los_efectos():
    rng = np.random.default_rng(1)
    t = _tabla(4000, rng)
    t["dmid_bps"] = 3.0 * t.imbalance_btc + rng.normal(0, 1, len(t))
    t["dmid_sig_bps"] = 0.5 * t.imbalance_btc + rng.normal(0, 1, len(t))
    r = {(x.medida, x.relacion): x for x in relaciones_presion(t, minimo=200)}
    c, p = r[("volumen", "contemporanea")], r[("volumen", "predictiva")]
    assert c.coef == pytest.approx(3.0, abs=0.15) and c.estado == "confirmada"
    assert p.coef == pytest.approx(0.5, abs=0.15) and p.estado == "confirmada"
    assert "confirmada" in c.conclusion() and c.a_fila()["hasta_utc"] == pd.Timestamp(S0 + 3999 * 10 + 10,
                                                                                      unit="s", tz="UTC")
    assert c.a_fila()["estudio"] == "presion_relacion"


def test_relacion_sin_efecto_y_datos_insuficientes():
    rng = np.random.default_rng(2)
    t = _tabla(4000, rng)
    t["dmid_bps"] = rng.normal(0, 1, len(t))
    t["dmid_sig_bps"] = rng.normal(0, 1, len(t))
    estados = {x.estado for x in relaciones_presion(t, minimo=200)}
    assert estados <= {"sin evidencia", "no confirmada fuera de muestra"} and "sin evidencia" in estados
    pocos = relaciones_presion(t.iloc[:100], minimo=200)
    assert {x.estado for x in pocos} == {"datos insuficientes"}
    assert "datos insuficientes" in pocos[0].conclusion()


def test_interaccion_con_la_intensidad_recupera_el_efecto_extra():
    rng = np.random.default_rng(3)
    t = _tabla(6000, rng)
    mediana = t.intensidad.iloc[:3000].median()
    alto = (t.intensidad > mediana).astype(float)
    t["dmid_bps"] = 1.0 * t.imbalance_btc + 4.0 * t.imbalance_btc * alto + rng.normal(0, 1, len(t))
    t["dmid_sig_bps"] = rng.normal(0, 1, len(t))
    r = {x.relacion: x for x in interacciones_intensidad(t, minimo=200)}
    c = r["contemporanea"]
    assert c.umbral == pytest.approx(mediana)
    assert c.coef_bajo == pytest.approx(1.0, abs=0.2) and c.coef_interaccion == pytest.approx(4.0, abs=0.3)
    assert c.estado == "confirmada" and "más fuerte" in c.conclusion()
    assert r["predictiva"].estado in {"sin evidencia", "no confirmada fuera de muestra"}
    assert c.a_fila()["estudio"] == "presion_intensidad"


def test_vwap_frente_al_mid_firmado_por_el_lado_neto():
    rng = np.random.default_rng(4)
    n = 500
    lado = np.where(rng.uniform(size=n) > 0.5, 1.0, -1.0)
    twap = 100.0 + rng.normal(0, 0.1, n)
    t = pd.DataFrame({"exchange": "kraken", "intervalo_s": 10, "inicio_s": S0 + 10 * np.arange(n),
                      "firmado_btc": lado, "mid_twap": twap, "vwap": twap * (1 + lado * 2e-4),
                      "vwap_compra": twap * (1 + 1e-4), "vwap_venta": twap * (1 - 1e-4),
                      "cotizado_bps": 1.5, "n_trades": 5})
    r = vwap_mid(t, minimo=100)[0]
    assert r.desvio_neto_bps == pytest.approx(2.0, abs=1e-6) and r.brecha_compra_venta_bps == pytest.approx(2.0, abs=1e-6)
    assert r.estado == "el lado neto paga sobre el mid" and "2.000 bps" in r.conclusion()
    assert r.a_fila()["estudio"] == "presion_vwap"


def test_exposicion_neta_y_bruta_recupera_el_efecto_del_flujo_de_un_lado():
    rng = np.random.default_rng(5)
    n = 4000
    ratio = rng.uniform(0, 1, n)
    bruta = rng.lognormal(10, 1, n)
    t = pd.DataFrame({"exchange": "kraken", "intervalo_s": 10, "inicio_s": S0 + 10 * np.arange(n),
                      "neta_bruta": ratio, "bruta_eur": bruta, "neta_eur": ratio * bruta,
                      "n_trades": rng.integers(1, 50, n)})
    t["dmid_bps"] = np.where(rng.uniform(size=n) > 0.5, 1, -1) * (2.0 + 5.0 * ratio + rng.normal(0, 1, n))
    r = exposicion_flujo(t, minimo=200)[0]
    assert r.coef == pytest.approx(5.0, abs=0.3) and r.estado == "confirmada"
    assert r.ratio_p50 == pytest.approx(0.5, abs=0.05)
    assert r.dmid_abs_un_lado_bps == pytest.approx(2 + 5 * 0.95, abs=0.3)
    assert r.dmid_abs_equilibrado_bps == pytest.approx(2 + 5 / 6, abs=0.3)
    assert r.solo_un_lado == 0 and "un solo lado" in r.conclusion()
    assert r.a_fila()["estudio"] == "presion_exposicion"


def test_estudio_desde_el_lake_con_eventos_y_trades_y_guardado(tmp_path):
    def ev(s, tipo, lado, precio, cantidad):
        return {"exchange": "kraken", "recibido_utc": T0 + pd.Timedelta(seconds=s),
                "hora_exchange_utc": T0 + pd.Timedelta(seconds=s), "tipo": tipo, "lado": lado, "precio": precio,
                "cantidad": cantidad, "secuencia": np.nan}

    rng = np.random.default_rng(6)
    eventos = [ev(0, "snapshot", "bid", 99.5, 1), ev(0, "snapshot", "ask", 100.5, 1)]
    filas, mid = [], 100.0
    for s in range(1, 1200):
        lado = "buy" if rng.uniform() > 0.5 else "sell"
        filas.append((s + 0.3, mid + (0.5 if lado == "buy" else -0.5), 0.1, lado))
        mid += 0.5 if lado == "buy" else -0.5   # cada compra sube el mid y cada venta lo baja
        eventos += [ev(s + 0.6, "update", "bid", mid - 0.5, 1), ev(s + 0.6, "update", "ask", mid + 0.5, 1)]
        # Se borra el nivel que ha quedado en el nuevo mid (el ask antiguo tras una compra, el bid tras una venta).
        eventos.append(ev(s + 0.6, "update", "ask" if lado == "buy" else "bid", mid, 0))
    lake = LakeParquet(tmp_path)
    lake.guardar(eventos, "eventos_libro")
    tr = trades(*filas)
    lake.guardar(tr.assign(hora_exchange_utc=tr.recibido_utc, trade_id=[str(i) for i in range(len(tr))])
                 .to_dict("records"), "trades")
    resultados = estudiar_presion(lake.consultar, T0, intervalos_s=(10,), minimo=20)
    rel = {(r.medida, r.relacion): r for r in resultados if r.a_fila()["estudio"] == "presion_relacion"}
    assert rel[("volumen", "contemporanea")].coef > 0 and rel[("volumen", "contemporanea")].estado == "confirmada"
    ahora = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")
    guardar_estudio_presion(resultados, lake, ahora)
    leido = lake.consultar(f"SELECT * FROM {FUENTE_PRESION}")
    assert len(leido) == len(resultados) and leido.hasta_utc.notna().all()
    assert set(leido.estudio) == {"presion_relacion", "presion_intensidad", "presion_vwap", "presion_exposicion"}
