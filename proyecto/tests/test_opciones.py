"""Valoración de opciones (Fase 7, S2): payoffs, Black-76, griegas, volatilidad implícita, paridad put-call,
sonrisa, estructura temporal y comparación con la volatilidad realizada."""

import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis import opciones as op
from radar.captura import opciones as cap

# --- payoffs ----------------------------------------------------------------------------------------------------


def test_payoffs_de_futuro_call_put_y_combinaciones():
    s = np.array([50_000.0, 60_000.0, 70_000.0])
    assert op.payoff_futuro(s, 60_000).tolist() == [-10_000, 0, 10_000]
    assert op.payoff_futuro(s, 60_000, posicion=-1).tolist() == [10_000, 0, -10_000]
    assert op.payoff_call(s, 60_000).tolist() == [0, 0, 10_000]
    assert op.payoff_put(s, 60_000).tolist() == [10_000, 0, 0]
    assert op.payoff_straddle(s, 60_000).tolist() == [10_000, 0, 10_000]
    # put protectora: spot + put; nunca vale menos que el strike al vencimiento
    assert op.payoff_put_protectora(s, 60_000).tolist() == [60_000, 60_000, 70_000]
    # opción inversa: el mismo payoff en USD se paga en BTC al precio de liquidación
    assert op.payoff_inverso_btc(op.payoff_call(s, 60_000), s).tolist() == pytest.approx([0, 0, 10_000 / 70_000])


def test_beneficio_resta_la_prima_pagada():
    assert op.beneficio(op.payoff_call(np.array([70_000.0]), 60_000), prima=2_000).tolist() == [8_000]


# --- Black-76 ---------------------------------------------------------------------------------------------------


def test_black76_reproduce_los_ejemplos_de_hull():
    # Hull, Options, Futures, and Other Derivatives: Black-Scholes con S=42, K=40, r=10 %, σ=20 %, T=0,5
    # → call 4,76 y put 0,81. Black-76 sobre el forward F = S·e^{rT} da lo mismo.
    f = 42 * math.exp(0.1 * 0.5)
    assert op.black76(f, 40, 0.5, 0.2, "call", r=0.1) == pytest.approx(4.76, abs=0.005)
    assert op.black76(f, 40, 0.5, 0.2, "put", r=0.1) == pytest.approx(0.81, abs=0.005)
    # Hull, modelo de Black: put sobre un futuro F=20, K=20, r=9 %, σ=25 %, T=4 meses → 1,12
    assert op.black76(20, 20, 4 / 12, 0.25, "put", r=0.09) == pytest.approx(1.12, abs=0.005)


def test_paridad_put_call_se_cumple_con_precios_del_modelo():
    for k in (40_000, 60_000, 90_000):
        for r in (0.0, 0.05):
            c = op.black76(61_000, k, 0.3, 0.6, "call", r=r)
            p = op.black76(61_000, k, 0.3, 0.6, "put", r=r)
            assert c - p == pytest.approx(math.exp(-r * 0.3) * (61_000 - k), rel=1e-12, abs=1e-8)


def test_precio_btc_sigue_la_convencion_de_deribit():
    # Ticker real BTC-26MAR27-40000-C: F 61 594,9, mark_iv 64 %, mark 0,3687 BTC (redondeado al tick 0,0001)
    t = op.anos_hasta(pd.Timestamp("2027-03-26 08:00", tz="UTC"), pd.Timestamp(1795378531188, unit="ms", tz="UTC"))
    assert op.precio_btc(61594.9, 40_000, t, 0.64, "call") == pytest.approx(0.3687, abs=0.00005)


@pytest.mark.parametrize("tipo", ["call", "put"])
@pytest.mark.parametrize("k", [45_000, 61_000, 80_000])
def test_griegas_coinciden_con_diferencias_finitas(tipo, k):
    f, t, s, r = 61_000.0, 0.25, 0.55, 0.03
    g = op.griegas(f, k, t, s, tipo, r=r)
    v = lambda **c: op.black76(c.get("f", f), k, c.get("t", t), c.get("s", s), tipo, r=c.get("r", r))
    hf, ht, hs, hr = 1.0, 1e-5, 1e-5, 1e-6
    assert g["delta"] == pytest.approx((v(f=f + hf) - v(f=f - hf)) / (2 * hf), rel=1e-5)
    assert g["gamma"] == pytest.approx((v(f=f + hf) - 2 * v() + v(f=f - hf)) / hf ** 2, rel=1e-3)
    assert g["vega"] == pytest.approx((v(s=s + hs) - v(s=s - hs)) / (2 * hs), rel=1e-5)
    assert g["theta"] == pytest.approx(-(v(t=t + ht) - v(t=t - ht)) / (2 * ht), rel=1e-4)
    assert g["rho"] == pytest.approx((v(r=r + hr) - v(r=r - hr)) / (2 * hr), rel=1e-4)


# Tickers reales (22-11-2026): (instrumento, vencimiento, F, mark_iv, hora ms, griegas publicadas)
TICKERS = [
    ("call", 40_000, "2027-03-26 08:00", 61594.9, 0.64, 1795378531188,
     {"delta": 0.91081, "gamma": 1e-05, "vega": 57.78978, "theta": -14.97577, "rho": 112.97981}),
    ("put", 60_000, "2027-03-26 08:00", 61566.2, 0.4882, 1795378745709,
     {"delta": -0.40799, "gamma": 2e-05, "vega": 139.04481, "theta": -27.48723, "rho": -105.64461}),
    # vence en menos de un día: Deribit publica la theta de la vida que le queda, no la de un día
    ("call", 61_000, "2026-11-23 08:00", 60566.29, 0.6481, 1795378745709,
     {"delta": 0.38605, "gamma": 0.00027, "vega": 8.46171, "theta": -274.2164, "rho": 0.30674}),
    ("put", 60_000, "2026-11-23 08:00", 60566.29, 0.6937, 1795378745709,
     {"delta": -0.35068, "gamma": 0.00024, "vega": 8.19859, "theta": -284.35999, "rho": -0.28818}),
]


@pytest.mark.parametrize("tipo,k,vence,f,iv,hora,publicadas", TICKERS)
def test_griegas_deribit_reproducen_las_publicadas(tipo, k, vence, f, iv, hora, publicadas):
    t = op.anos_hasta(pd.Timestamp(vence, tz="UTC"), pd.Timestamp(hora, unit="ms", tz="UTC"))
    g = op.griegas_deribit(f, k, t, iv, tipo)
    assert g["delta"] == pytest.approx(publicadas["delta"], abs=2e-5)
    assert g["gamma"] == pytest.approx(publicadas["gamma"], abs=6e-6)   # Deribit redondea a 5 decimales
    for nombre in ("vega", "theta", "rho"):
        assert g[nombre] == pytest.approx(publicadas[nombre], rel=2e-4, abs=2e-3)


# --- volatilidad implícita --------------------------------------------------------------------------------------


@pytest.mark.parametrize("tipo", ["call", "put"])
@pytest.mark.parametrize("sigma", [0.05, 0.4, 1.2, 3.0])
@pytest.mark.parametrize("k", [30_000, 60_000, 100_000])
def test_volatilidad_implicita_ida_y_vuelta(tipo, sigma, k):
    f, t = 60_000.0, 0.1
    precio = op.black76(f, k, t, sigma, tipo)
    if precio - op.cotas_sin_arbitraje(f, k, t, tipo)[0] < 1e-6 * f:
        pytest.skip("precio indistinguible del valor intrínseco: la volatilidad no está identificada")
    assert op.volatilidad_implicita(precio, f, k, t, tipo) == pytest.approx(sigma, rel=1e-6)


def test_volatilidad_implicita_fuera_de_las_cotas_es_nan():
    f, k, t = 60_000.0, 50_000.0, 0.1
    inferior, superior = op.cotas_sin_arbitraje(f, k, t, "call")
    assert (inferior, superior) == (10_000.0, 60_000.0)
    assert math.isnan(op.volatilidad_implicita(9_999.0, f, k, t, "call"))      # bajo el intrínseco
    assert math.isnan(op.volatilidad_implicita(60_000.0, f, k, t, "call"))     # igual o sobre el forward
    assert math.isnan(op.volatilidad_implicita(-1.0, f, k, t, "put"))
    assert math.isnan(op.volatilidad_implicita(100.0, f, k, 0.0, "call"))      # ya vencida
    assert math.isnan(op.volatilidad_implicita(float("nan"), f, k, t, "call"))


# --- cadenas sintéticas -----------------------------------------------------------------------------------------

HORA = pd.Timestamp("2026-11-22 19:00", tz="UTC")
VENCIMIENTOS = {"BTC-29NOV26": HORA + pd.Timedelta(days=7) - pd.Timedelta(hours=11),
                "BTC-25DEC26": HORA + pd.Timedelta(days=33) - pd.Timedelta(hours=11),
                "BTC-26MAR27": HORA + pd.Timedelta(days=124) - pd.Timedelta(hours=11)}
FORWARDS = {"BTC-29NOV26": 60_600.0, "BTC-25DEC26": 60_800.0, "BTC-26MAR27": 61_600.0}


def iv_sintetica(k, f, nivel):
    m = math.log(k / f)
    return nivel - 0.25 * m + 0.6 * m * m   # skew de puts (más caras abajo) y algo de sonrisa


def cadena_sintetica(medio_spread_btc=0.0005, niveles=(0.55, 0.52, 0.50)):
    filas = []
    for (sub, vence), nivel in zip(VENCIMIENTOS.items(), niveles):
        f = FORWARDS[sub]
        t = op.anos_hasta(vence, HORA)
        for k in range(40_000, 90_001, 2_000):
            iv = iv_sintetica(k, f, nivel)
            for tipo in ("call", "put"):
                mark = op.precio_btc(f, k, t, iv, tipo)
                g = op.griegas_deribit(f, k, t, iv, tipo)
                filas.append({
                    "instantanea_utc": HORA, "recibido_utc": HORA, "instrumento": f"{sub}-{k}-{tipo[0].upper()}",
                    "vencimiento_utc": vence, "strike": float(k), "tipo_opcion": tipo, "mark_btc": mark,
                    "bid_btc": max(mark - medio_spread_btc, 0.0) if mark > medio_spread_btc else math.nan,
                    "ask_btc": mark + medio_spread_btc, "iv_mark": iv, "iv_bid": math.nan, "iv_ask": math.nan,
                    "subyacente_usd": f, "subyacente_ticker_usd": f, "iv_mark_ticker": iv, "indice_subyacente": sub, "subyacente_es_futuro": sub != "BTC-29NOV26",
                    "indice_usd": 60_500.0, "interes": 0.0, "open_interest": 10.0, "comision_taker": 0.0003,
                    "tamano_contrato": 1.0, "cantidad_bid": 1.0, "cantidad_ask": 1.0, "hora_resumen_utc": HORA,
                    "hora_ticker_utc": HORA, **g})
    return pd.DataFrame(filas)[cap.COLUMNAS]


def test_paridad_sin_violaciones_en_precios_del_modelo():
    tabla = op.paridad(cadena_sintetica())
    assert len(tabla) == 3 * 26
    con_cotas = tabla[tabla.con_cotizaciones]
    assert len(con_cotas) > 0 and not con_cotas.violacion.any()
    assert tabla.desviacion_bps.abs().max() < 1e-6


def test_paridad_detecta_una_violacion_fuera_del_spread():
    cadena = cadena_sintetica()
    i = cadena.index[(cadena.instrumento == "BTC-25DEC26-60000-C")][0]
    cadena.loc[i, ["bid_btc", "ask_btc", "mark_btc"]] = cadena.loc[i, "mark_btc"] + np.array([0.004, 0.005, 0.0045])
    tabla = op.paridad(cadena).set_index(["indice_subyacente", "strike"])
    fila = tabla.loc[("BTC-25DEC26", 60_000.0)]
    assert bool(fila.violacion) and fila.exceso_bps == pytest.approx(35.0, abs=1e-6)   # 0,004 − 0,0005 del put
    assert fila.desviacion_bps == pytest.approx(45.0, abs=1e-6)
    assert bool(fila.violacion_tras_comisiones) is True   # 35 bps > 2 · 3 bps de comisión taker
    assert tabla.violacion.sum() == 1


def test_forward_implicito_de_la_paridad_recupera_el_forward():
    tabla = op.paridad(cadena_sintetica())
    fwd = op.forward_implicito(tabla)
    assert fwd["BTC-25DEC26"] == pytest.approx(60_800.0, rel=1e-9)


def test_sonrisa_atm_y_skew_por_vencimiento():
    cadena = cadena_sintetica()
    sonrisas = {r.indice_subyacente: r for r in op.estudiar_sonrisa(cadena)}
    r = sonrisas["BTC-25DEC26"]
    assert r.iv_atm == pytest.approx(0.52, abs=2e-3)
    assert r.rr25 < -0.01 and r.estado == op.SKEW_PUTS   # convención de mercado: σ(25Δ call) − σ(25Δ put)
    assert "BTC-25DEC26" in r.conclusion() and r.a_fila()["hasta_utc"] == HORA


def test_estructura_temporal_creciente_o_invertida():
    creciente = op.estudiar_estructura(cadena_sintetica(niveles=(0.45, 0.50, 0.55)))
    assert creciente.forma == op.CRECIENTE and creciente.n_vencimientos == 3
    invertida = op.estudiar_estructura(cadena_sintetica(niveles=(0.60, 0.52, 0.48)))
    assert invertida.forma == op.INVERTIDA


def test_iv_atm_interpolada_en_varianza_total():
    estructura = pd.DataFrame({"anos": [0.1, 0.3], "iv_atm": [0.5, 0.6]})
    t = 0.2
    esperada = math.sqrt((0.5 ** 2 * 0.1 + (0.6 ** 2 * 0.3 - 0.5 ** 2 * 0.1) * 0.5) / t)
    assert op.iv_atm_a_plazo(estructura, t) == pytest.approx(esperada)
    assert math.isnan(op.iv_atm_a_plazo(estructura, 0.5))   # no se extrapola


def test_validacion_contra_deribit_coincide_en_una_cadena_coherente():
    v = op.validar_contra_deribit(cadena_sintetica())
    assert v.estado == op.COINCIDE
    assert v.mediana_dif_iv_puntos < 1e-6 and v.n_fallos_iv == 0
    assert v.mediana_dif_delta < 1e-9


def test_validacion_detecta_greeks_que_no_cuadran():
    cadena = cadena_sintetica()
    cadena["vega"] = cadena["vega"] * 1.5
    assert op.validar_contra_deribit(cadena).estado == op.DISCREPA


def velas_horarias(n=24 * 40, sigma_hora=0.01, hasta=HORA):
    inicio = hasta.floor("h") - pd.Timedelta(hours=n)
    signos = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    precios = 50_000 * np.exp(np.cumsum(signos * sigma_hora))
    return pd.DataFrame({
        "fuente": "kraken_historico", "exchange": "kraken", "par": "BTC/EUR", "intervalo_s": 3600,
        "inicio_utc": pd.date_range(inicio, periods=n, freq="h"), "apertura": precios, "maximo": precios,
        "minimo": precios, "cierre": precios, "volumen_btc": 1.0, "volumen_eur": precios, "vwap": precios,
        "n_trades": 5.0, "vacia": False, "completa": True, "recibido_utc": hasta})


def test_vol_realizada_de_velas_horarias_anualizada_24_7():
    vol, n = op.vol_realizada(velas_horarias(), HORA, dias=30)
    # retornos ±1 % alternos: desviación muestral ≈ 0,01 · √(n/(n−1)); anualizada con √(365 · 24)
    assert n == 30 * 24 - 1
    assert vol == pytest.approx(0.01 * math.sqrt(n / (n - 1)) * math.sqrt(365 * 24), rel=1e-5)


def test_estudio_completo_en_el_lake(tmp_path):
    lake = LakeParquet(tmp_path)
    cap.guardar_cadena(cadena_sintetica(), lake)
    lake.guardar(velas_horarias().to_dict("records"), "velas")
    resultados = op.estudiar_opciones_lake(lake.consultar)
    estudios = {r.a_fila()["estudio"] for r in resultados}
    assert estudios == {"paridad", "validacion", "sonrisa", "estructura", "realizada"}
    realizadas = [r for r in resultados if r.a_fila()["estudio"] == "realizada"]
    assert {r.dias for r in realizadas} == set(op.VENTANAS_REALIZADA)
    assert all(r.conclusion() for r in resultados)
    op.guardar_estudio_opciones(resultados, lake, pd.Timestamp("2026-11-22 20:00", tz="UTC"))
    guardado = lake.consultar(f"SELECT * FROM {op.FUENTE_OPCIONES}")
    assert len(guardado) == len(resultados) and guardado.hasta_utc.notna().all()
    prohibidas = {"p_descubrimiento", "p_valor", "p_sustitutos", "t_descubrimiento", "t_hac", "t_conjunto",
                  "t_interaccion", "t", "t_r1"}
    assert not prohibidas & set(guardado.columns)   # descriptivo: el registro de pruebas no lo cuenta


def test_estudio_sin_cadena_devuelve_lista_vacia(tmp_path):
    assert op.estudiar_opciones_lake(LakeParquet(tmp_path).consultar) == []
