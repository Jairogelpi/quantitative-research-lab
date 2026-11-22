"""Captura de la cadena de opciones BTC de Deribit: interpretación de respuestas grabadas, caso de uso y lake.

Las respuestas son literales recortados de llamadas reales a la API pública (22-11-2026, ~19:15 UTC).
"""

import math

import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.captura import opciones as cap
from radar.captura.exchanges import deribit

INSTRUMENTO_CALL = {
    "state": "open", "price_index": "btc_usd", "kind": "option", "instrument_name": "BTC-26MAR27-40000-C",
    "maker_commission": 0.0003, "taker_commission": 0.0003, "instrument_type": "reversed",
    "expiration_timestamp": 1806048000000, "is_active": True, "contract_size": 1.0, "tick_size": 0.0001,
    "strike": 40000.0, "counter_currency": "USD", "option_type": "call", "settlement_currency": "BTC",
    "settlement_period": "month", "base_currency": "BTC", "quote_currency": "BTC"}
INSTRUMENTO_PUT = {**INSTRUMENTO_CALL, "instrument_name": "BTC-26MAR27-40000-P", "option_type": "put"}
FUTURO = {"kind": "future", "instrument_name": "BTC-26MAR27", "expiration_timestamp": 1806048000000,
          "settlement_period": "month", "instrument_type": "reversed", "contract_size": 10.0,
          "settlement_currency": "BTC", "taker_commission": 0.0005}

RESUMEN_CALL = {
    "high": 0.3765, "low": 0.3735, "last": 0.3765, "instrument_name": "BTC-26MAR27-40000-C", "bid_price": 0.3665,
    "ask_price": 0.371, "open_interest": 104.7, "mark_price": 0.36862541, "interest_rate": 0.0,
    "creation_timestamp": 1795378520088, "estimated_delivery_price": 60601.66, "price_change": 0.8032,
    "volume": 15.6, "mark_iv": 64.0, "underlying_price": 61591.56, "underlying_index": "BTC-26MAR27",
    "base_currency": "BTC", "quote_currency": "BTC", "volume_usd": 356505.1, "mid_price": 0.36875}
RESUMEN_PUT_SIN_BID = {**RESUMEN_CALL, "instrument_name": "BTC-26MAR27-40000-P", "bid_price": None,
                       "ask_price": 0.0035, "mark_price": 0.00321, "mark_iv": 66.1, "mid_price": None}

TICKER_CALL = {
    "timestamp": 1795378531188, "state": "open",
    "greeks": {"delta": 0.91081, "gamma": 1e-05, "vega": 57.78978, "theta": -14.97577, "rho": 112.97981},
    "index_price": 60604.87, "instrument_name": "BTC-26MAR27-40000-C", "last_price": 0.3765,
    "open_interest": 104.7, "mark_price": 0.3687, "interest_rate": 0.0, "best_ask_price": 0.371,
    "best_bid_price": 0.3665, "estimated_delivery_price": 60604.87, "mark_iv": 64.0, "bid_iv": 61.64,
    "ask_iv": 66.44, "underlying_price": 61594.9, "underlying_index": "BTC-26MAR27", "best_ask_amount": 1.0,
    "best_bid_amount": 4.0}
TICKER_PUT_SIN_BID = {**TICKER_CALL, "instrument_name": "BTC-26MAR27-40000-P", "best_bid_price": 0.0,
                      "best_bid_amount": 0.0, "bid_iv": 0.0, "ask_iv": 70.2,
                      "greeks": {"delta": -0.0892, "gamma": 1e-05, "vega": 57.8, "theta": -15.0, "rho": -23.4}}


def _respuesta(result):
    return {"jsonrpc": "2.0", "result": result, "usIn": 1, "usOut": 2, "usDiff": 1, "testnet": False}


def test_interpretar_instrumentos_traduce_vencimiento_strike_y_tipo():
    df = deribit.interpretar_instrumentos([INSTRUMENTO_CALL, INSTRUMENTO_PUT])
    fila = df.iloc[0]
    assert fila.instrumento == "BTC-26MAR27-40000-C"
    assert fila.vencimiento_utc == pd.Timestamp("2027-03-26 08:00", tz="UTC")
    assert fila.strike == 40000.0 and fila.tipo_opcion == "call" and df.iloc[1].tipo_opcion == "put"
    assert fila.tamano_contrato == 1.0 and fila.moneda_liquidacion == "BTC" and fila.tipo_instrumento == "reversed"
    assert fila.comision_taker == 0.0003


def test_interpretar_resumen_pasa_iv_a_fraccion_y_bid_ausente_a_nan():
    df = deribit.interpretar_resumen([RESUMEN_CALL, RESUMEN_PUT_SIN_BID]).set_index("instrumento")
    c = df.loc["BTC-26MAR27-40000-C"]
    assert c.mark_btc == 0.36862541 and c.bid_btc == 0.3665 and c.ask_btc == 0.371
    assert c.iv_mark == pytest.approx(0.64)
    assert c.subyacente_usd == 61591.56 and c.indice_subyacente == "BTC-26MAR27"
    assert c.open_interest == 104.7 and c.interes == 0.0
    assert c.hora_resumen_utc == pd.Timestamp(1795378520088, unit="ms", tz="UTC")
    assert math.isnan(df.loc["BTC-26MAR27-40000-P"].bid_btc)


def test_interpretar_ticker_extrae_griegas_publicadas_e_iv_de_bid_y_ask():
    t = deribit.interpretar_ticker(TICKER_CALL)
    assert t["instrumento"] == "BTC-26MAR27-40000-C"
    assert (t["delta"], t["gamma"], t["vega"], t["theta"], t["rho"]) == (0.91081, 1e-05, 57.78978, -14.97577,
                                                                          112.97981)
    assert t["iv_bid"] == pytest.approx(0.6164) and t["iv_ask"] == pytest.approx(0.6644)
    assert t["indice_usd"] == 60604.87 and t["cantidad_bid"] == 4.0
    assert t["hora_ticker_utc"] == pd.Timestamp(1795378531188, unit="ms", tz="UTC")
    sin_bid = deribit.interpretar_ticker(TICKER_PUT_SIN_BID)
    assert math.isnan(sin_bid["iv_bid"]) and sin_bid["iv_ask"] == pytest.approx(0.702)


def test_un_error_de_la_api_lanza_excepcion():
    with pytest.raises(ValueError, match="Deribit"):
        deribit.resultado({"jsonrpc": "2.0", "error": {"code": 10009, "message": "not_found"}})
    assert deribit.resultado(_respuesta([1])) == [1]


class ClienteFalso:
    """Imita al adaptador con respuestas grabadas; cuenta las llamadas a `ticker`."""

    def __init__(self, ticker_falla=(), fallos_por_ticker=10**9):
        self.tickers = []
        self.ticker_falla = set(ticker_falla)
        self.fallos_por_ticker = fallos_por_ticker

    def instrumentos(self, moneda="BTC", tipo="option"):
        return deribit.interpretar_instrumentos([INSTRUMENTO_CALL, INSTRUMENTO_PUT] if tipo == "option" else [FUTURO])

    def resumen(self, moneda="BTC", tipo="option"):
        return deribit.interpretar_resumen([RESUMEN_CALL, RESUMEN_PUT_SIN_BID])

    def ticker(self, instrumento):
        self.tickers.append(instrumento)
        if instrumento in self.ticker_falla and self.tickers.count(instrumento) <= self.fallos_por_ticker:
            raise ValueError("Deribit devolvió un error: too_many_requests")
        return deribit.interpretar_ticker(TICKER_CALL if instrumento.endswith("C") else TICKER_PUT_SIN_BID)

    def indice(self, nombre="btc_usd"):
        return 60604.87


def test_leer_cadena_une_instrumentos_resumen_y_ticker_con_pausa_entre_tickers():
    cliente, pausas = ClienteFalso(), []
    ahora = pd.Timestamp("2026-11-22 19:15:30", tz="UTC")
    cadena = cap.leer_cadena(cliente, pausa_s=0.2, dormir=pausas.append, ahora=ahora)
    assert list(cadena.columns) == cap.COLUMNAS
    assert len(cadena) == 2 and cliente.tickers == ["BTC-26MAR27-40000-C", "BTC-26MAR27-40000-P"]
    assert pausas == [0.2, 0.2]
    c = cadena.set_index("instrumento").loc["BTC-26MAR27-40000-C"]
    assert c.delta == 0.91081 and c.iv_bid == pytest.approx(0.6164) and c.strike == 40000.0
    assert bool(c.subyacente_es_futuro) is True
    assert c.instantanea_utc == pd.Timestamp(1795378520088, unit="ms", tz="UTC")
    assert c.recibido_utc == ahora and c.indice_usd == 60604.87


def test_leer_cadena_sin_griegas_no_pide_tickers():
    cliente = ClienteFalso()
    cadena = cap.leer_cadena(cliente, griegas=False, dormir=lambda s: None)
    assert cliente.tickers == [] and cadena.delta.isna().all() and cadena.iv_mark.notna().all()


def test_un_ticker_que_falla_deja_sus_griegas_en_nan_sin_abortar():
    cliente, pausas = ClienteFalso(ticker_falla={"BTC-26MAR27-40000-P"}), []
    cadena = cap.leer_cadena(cliente, pausa_s=0.2, reintentos=2, espera_s=1.0, dormir=pausas.append)
    cadena = cadena.set_index("instrumento")
    assert math.isnan(cadena.loc["BTC-26MAR27-40000-P"].delta)
    assert cadena.loc["BTC-26MAR27-40000-C"].delta == 0.91081
    assert cliente.tickers.count("BTC-26MAR27-40000-P") == 3          # 1 intento + 2 reintentos
    assert pausas == [0.2, 0.2, 1.0, 2.0]                              # espera exponencial entre reintentos


def test_un_ticker_rechazado_una_vez_se_recupera_al_reintentar():
    cliente, pausas = ClienteFalso(ticker_falla={"BTC-26MAR27-40000-P"}, fallos_por_ticker=1), []
    cadena = cap.leer_cadena(cliente, pausa_s=0.2, espera_s=1.0, dormir=pausas.append).set_index("instrumento")
    assert cadena.loc["BTC-26MAR27-40000-P"].delta == -0.0892
    assert pausas == [0.2, 0.2, 1.0]


def test_max_tickers_elige_los_strikes_mas_cercanos_al_forward_en_cada_vencimiento():
    resumen = deribit.interpretar_resumen([RESUMEN_CALL, RESUMEN_PUT_SIN_BID])
    lejos = {**INSTRUMENTO_CALL, "instrument_name": "BTC-26MAR27-90000-C", "strike": 90000.0}
    cadena = deribit.interpretar_instrumentos([INSTRUMENTO_CALL, lejos]).merge(
        pd.concat([resumen.iloc[[0]], resumen.iloc[[0]].assign(instrumento="BTC-26MAR27-90000-C")]), on="instrumento")
    # F = 61 591,56: |ln(40 000 / F)| = 0,43 y |ln(90 000 / F)| = 0,38
    assert cap.seleccionar_tickers(cadena, 1) == ["BTC-26MAR27-90000-C"]
    assert sorted(cap.seleccionar_tickers(cadena, None)) == ["BTC-26MAR27-40000-C", "BTC-26MAR27-90000-C"]


def test_guardar_cadena_es_idempotente_por_instantanea(tmp_path):
    lake = LakeParquet(tmp_path)
    cadena = cap.leer_cadena(ClienteFalso(), dormir=lambda s: None)
    assert len(cap.guardar_cadena(cadena, lake)) == 1
    assert cap.guardar_cadena(cadena, lake) == []
    guardado = lake.consultar(f"SELECT * FROM {cap.FUENTE_CADENA}")
    assert len(guardado) == 2
    assert set(guardado.instrumento) == {"BTC-26MAR27-40000-C", "BTC-26MAR27-40000-P"}
    otra = cadena.assign(instantanea_utc=cadena.instantanea_utc + pd.Timedelta(minutes=5))
    assert len(cap.guardar_cadena(otra, lake)) == 1
    assert len(lake.consultar(f"SELECT * FROM {cap.FUENTE_CADENA}")) == 4


@pytest.mark.live
def test_live_cadena_real_de_deribit():
    cadena = cap.leer_cadena(deribit.Deribit(), griegas=False)
    assert len(cadena) > 100
    assert cadena.tipo_opcion.isin(["call", "put"]).all() and (cadena.subyacente_usd > 0).all()
    assert cadena.vencimiento_utc.dt.hour.eq(8).all()
