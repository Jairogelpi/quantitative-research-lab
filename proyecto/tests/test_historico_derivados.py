"""Histórico público de perpetuos (OKX y Kraken Futures): interpretación de respuestas, paginación y guardado idempotente.

Las respuestas son copias recortadas de respuestas reales (22-11-2026) de los endpoints citados en
`radar/captura/exchanges/derivados.py`.
"""

import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.captura import historico_derivados as hd
from radar.captura.exchanges import derivados as dv

AHORA = pd.Timestamp("2026-11-22 21:00", tz="UTC")
MS = 1795377600000  # 2026-11-22 20:00 UTC

OKX_FUNDING = {"code": "0", "msg": "", "data": [
    {"formulaType": "withRate", "fundingRate": "0.0000227750962068", "fundingTime": "1795363200000",
     "instId": "BTC-USDT-SWAP", "instType": "SWAP", "method": "current_period",
     "realizedRate": "0.0000227750962068"},
    {"formulaType": "withRate", "fundingRate": "0.0000340541459576", "fundingTime": "1795334400000",
     "instId": "BTC-USDT-SWAP", "instType": "SWAP", "method": "current_period",
     "realizedRate": "0.0000340541459576"}]}
OKX_MARK = {"code": "0", "msg": "", "data": [["1795377600000", "60710.5", "60736.9", "60665.8", "60669.8", "0"],
                                             ["1795374000000", "60650.0", "60720.0", "60600.1", "60710.5", "1"]]}
OKX_VELAS_PERP = {"code": "0", "msg": "", "data": [
    ["1795374000000", "60710.5", "60737.5", "60665.8", "60670.7", "13668.72", "136.6872", "8297755.09737", "1"]]}
OKX_OI = {"code": "0", "msg": "", "data": [
    ["1795377600000", "3162288.03000001302", "31622.8803000001302", "1920248809.60902790618668"],
    ["1795374000000", "3161443.04000001301", "31614.4304000001301", "1919255163.60928789813682"]]}
OKX_LIQ = {"code": "0", "msg": "", "data": [{"details": [
    {"bkLoss": "0", "bkPx": "60680.6", "ccy": "", "posSide": "short", "side": "buy", "sz": "0.29",
     "time": 1795374579782, "ts": "1795374579782"},
    {"bkLoss": "0", "bkPx": "60507.5", "ccy": "", "posSide": "long", "side": "sell", "sz": "0.19",
     "time": 1795370852875, "ts": "1795370852875"}],
    "instFamily": "BTC-USDT", "instId": "BTC-USDT-SWAP", "instType": "SWAP", "totalLoss": "0", "uly": "BTC-USDT"}]}
KRAKEN_FUNDING = {"result": "success", "serverTime": "2026-11-22T20:17:20.673Z", "rates": [
    {"timestamp": "2026-11-22T19:00:00Z", "fundingRate": -0.13208590926072977,
     "relativeFundingRate": -2.177308333333e-06},
    {"timestamp": "2026-11-22T20:00:00Z", "fundingRate": 0.18562393870464644,
     "relativeFundingRate": 3.061033333333e-06}]}
KRAKEN_VELAS = {"candles": [
    {"time": 1795374000000, "open": "60650", "high": "60720", "low": "60600", "close": "60710", "volume": "12.5"},
    {"time": 1795377600000, "open": "60710", "high": "60736", "low": "60665", "close": "60669", "volume": 3}],
    "more_candles": False}
KRAKEN_OI = {"result": {"timestamp": [1795374000, 1795377600],
                        "data": [["2262.4333", "2359.4003", "2262.4196", "2356.7727"],
                                 ["2356.7727", "2403.1115", "2355.588", "2402.5833"]], "more": False}, "errors": []}
KRAKEN_LIQ = {"result": {"timestamp": [1795374000, 1795377600], "data": ["0", "1.5862"], "more": False},
              "errors": []}


def test_okx_funding_usa_la_tasa_liquidada_y_el_periodo_entre_pagos():
    f = dv.interpretar_okx_funding(OKX_FUNDING)
    assert list(f["periodo_fin_utc"]) == [pd.Timestamp("2026-11-22 08:00", tz="UTC"),
                                          pd.Timestamp("2026-11-22 16:00", tz="UTC")]
    assert f["tasa"].iloc[1] == pytest.approx(0.0000227750962068)
    assert list(f["periodo_h"]) == [8.0, 8.0]          # el primero toma el intervalo del siguiente
    assert f["tasa_absoluta"].isna().all() and (f["exchange"] == "okx").all()


def test_okx_funding_con_error_lanza():
    with pytest.raises(ValueError, match="OKX"):
        dv.interpretar_okx_funding({"code": "51001", "msg": "Instrument ID does not exist", "data": []})


def test_okx_velas_marca_la_abierta_y_ordena():
    v = dv.interpretar_okx_velas(OKX_MARK)
    assert list(v["inicio_utc"]) == [pd.Timestamp(MS - 3600000, unit="ms", tz="UTC"), pd.Timestamp(MS, unit="ms", tz="UTC")]
    assert list(v["completa"]) == [True, False] and v["cierre"].iloc[1] == 60669.8
    assert v["volumen"].isna().all()                    # mark e índice no tienen volumen
    p = dv.interpretar_okx_velas(OKX_VELAS_PERP)
    assert p["volumen"].iloc[0] == pytest.approx(136.6872)   # en BTC (volCcy)


def test_okx_open_interest_en_btc():
    oi = dv.interpretar_okx_oi(OKX_OI)
    assert oi["oi_btc"].iloc[-1] == pytest.approx(31622.8803)
    assert oi["oi_usd"].iloc[0] == pytest.approx(1919255163.609)
    assert oi["inicio_utc"].is_monotonic_increasing


def test_okx_liquidaciones_en_btc_con_lado_de_la_posicion():
    liq = dv.interpretar_okx_liquidaciones(OKX_LIQ)
    assert list(liq["lado"]) == ["long", "short"]       # orden temporal
    assert liq["cantidad_btc"].iloc[1] == pytest.approx(0.29 * 0.01)
    assert liq["precio"].iloc[0] == 60507.5


def test_kraken_funding_horario_con_tasa_relativa_y_absoluta():
    f = dv.interpretar_kraken_funding(KRAKEN_FUNDING)
    assert list(f["periodo_fin_utc"]) == [pd.Timestamp("2026-11-22 20:00", tz="UTC"),
                                          pd.Timestamp("2026-11-22 21:00", tz="UTC")]
    assert (f["periodo_h"] == 1.0).all()
    assert f["tasa"].iloc[1] == pytest.approx(3.061033333333e-06)
    assert f["tasa_absoluta"].iloc[1] == pytest.approx(0.18562393870464644)


def test_kraken_funding_con_error_lanza():
    with pytest.raises(ValueError, match="Kraken"):
        dv.interpretar_kraken_funding({"result": "error", "error": "Invalid symbol"})


def test_kraken_velas_completas_segun_la_hora_de_descarga():
    v = dv.interpretar_kraken_velas(KRAKEN_VELAS, 3600, AHORA.replace(hour=20, minute=30))
    assert list(v["completa"]) == [True, False] and v["volumen"].iloc[1] == 3.0


def test_kraken_analitica_oi_toma_el_cierre_y_liquidaciones_el_volumen():
    oi = dv.interpretar_kraken_analitica(KRAKEN_OI)
    assert list(oi["valor"]) == [pytest.approx(2356.7727), pytest.approx(2402.5833)]
    liq = dv.interpretar_kraken_analitica(KRAKEN_LIQ)
    assert list(liq["valor"]) == [0.0, pytest.approx(1.5862)]
    assert liq["inicio_utc"].iloc[0] == pd.Timestamp(1795374000, unit="s", tz="UTC")


def test_paginar_okx_retrocede_con_after_hasta_desde():
    pedidas, pausas = [], []

    def pedir(url, params):
        pedidas.append(dict(params))
        after = params.get("after")
        if after is None:
            return {"code": "0", "data": [[str(10800000), "1", "1", "1", "1", "0"], [str(7200000), "1", "1", "1", "1", "1"]]}
        return {"code": "0", "data": [[str(int(after) - 3600000), "1", "1", "1", "1", "1"],
                                      [str(int(after) - 7200000), "1", "1", "1", "1", "1"]]}

    velas = dv.descargar_okx_velas(dv.URL_OKX_MARK, "BTC-USDT-SWAP", pd.Timestamp(0, unit="ms", tz="UTC") +
                                   pd.Timedelta(hours=1), pedir=pedir, dormir=pausas.append)
    assert [p.get("after") for p in pedidas] == [None, "7200000"]
    assert velas["inicio_utc"].min() == pd.Timestamp(3600000, unit="ms", tz="UTC")
    assert velas["inicio_utc"].is_unique and len(velas) == 3
    assert pausas == [dv.PAUSA_OKX_S]


def test_paginar_okx_para_si_la_pagina_viene_vacia():
    llamadas = []

    def pedir(url, params):
        llamadas.append(params)
        return {"code": "0", "data": [] if params.get("after") else [["7200000", "1", "1", "1", "1", "1"]]}

    velas = dv.descargar_okx_velas(dv.URL_OKX_MARK, "BTC-USDT-SWAP", pd.Timestamp(0, tz="UTC"), pedir=pedir,
                                   dormir=lambda s: None)
    assert len(llamadas) == 2 and len(velas) == 1


def test_paginar_kraken_velas_avanza_con_from():
    pedidas = []

    def pedir(url, params):
        pedidas.append(dict(params))
        desde = params["from"]
        horas = [desde + 3600 * i for i in range(3) if desde + 3600 * i <= params["to"]]
        return {"candles": [{"time": h * 1000, "open": "1", "high": "1", "low": "1", "close": "1", "volume": 0}
                            for h in horas], "more_candles": False}

    desde = pd.Timestamp("2026-11-01", tz="UTC")
    velas = dv.descargar_kraken_velas("mark", desde, desde + pd.Timedelta(hours=5), AHORA, pedir=pedir,
                                      dormir=lambda s: None, por_pagina=3)
    assert len(velas) == 6 and velas["inicio_utc"].is_unique
    assert pedidas[1]["from"] == pedidas[0]["from"] + 3 * 3600


def test_paginar_kraken_analitica_sigue_mientras_more():
    pedidas = []

    def pedir(url, params):
        pedidas.append(dict(params))
        s = params["since"]
        return {"result": {"timestamp": [s, s + 3600], "data": ["1", "2"], "more": s <= 1795374000 + 7200}, "errors": []}

    datos = dv.descargar_kraken_analitica("liquidation-volume", pd.Timestamp(1795374000, unit="s", tz="UTC"),
                                          AHORA + pd.Timedelta(days=1), pedir=pedir, dormir=lambda s: None)
    assert [p["since"] for p in pedidas] == [1795374000, 1795381200, 1795388400]
    assert len(datos) == 6


def _lake_con(tmp_path, ahora=AHORA):
    almacen = LakeParquet(tmp_path)
    datos = {"funding": dv.interpretar_kraken_funding(KRAKEN_FUNDING),
             "precios": {"mark": dv.interpretar_kraken_velas(KRAKEN_VELAS, 3600, ahora)},
             "oi": dv.interpretar_kraken_analitica(KRAKEN_OI),
             "liquidaciones": dv.interpretar_kraken_analitica(KRAKEN_LIQ)}
    resumen = hd.guardar_descarga(almacen, "kraken", datos, ahora)
    return almacen, resumen


def test_guardar_es_idempotente(tmp_path):
    almacen, primero = _lake_con(tmp_path)
    assert primero == {"derivados_funding": 2, "derivados_precios": 2, "derivados_oi": 2, "derivados_liquidaciones": 2}
    _, segundo = _lake_con(tmp_path, AHORA + pd.Timedelta(minutes=5))
    assert segundo == {"derivados_funding": 0, "derivados_precios": 0, "derivados_oi": 0, "derivados_liquidaciones": 0}
    assert len(almacen.consultar("SELECT * FROM derivados_funding")) == 2


def test_guardar_reescribe_una_vela_que_cambio_y_gana_la_mas_reciente(tmp_path):
    almacen = LakeParquet(tmp_path)
    abierta = dv.interpretar_okx_velas(OKX_MARK)
    assert hd.guardar_filas(almacen, hd.filas_precios(abierta, "okx", "BTC-USDT-SWAP", "mark", 3600, AHORA),
                            hd.FUENTE_PRECIOS) == 2
    cerrada = abierta.copy()
    cerrada.loc[1, ["cierre", "completa"]] = [60700.0, True]
    despues = AHORA + pd.Timedelta(hours=1)
    assert hd.guardar_filas(almacen, hd.filas_precios(cerrada, "okx", "BTC-USDT-SWAP", "mark", 3600, despues),
                            hd.FUENTE_PRECIOS) == 1
    ultimas = hd.leer_ultimas(almacen.consultar, hd.FUENTE_PRECIOS)
    assert len(ultimas) == 2 and ultimas.sort_values("inicio_utc")["cierre"].iloc[-1] == 60700.0


def test_leer_ultimas_sin_fuente_devuelve_vacio(tmp_path):
    assert hd.leer_ultimas(LakeParquet(tmp_path).consultar, hd.FUENTE_FUNDING).empty


def test_actualizar_derivados_con_lectores_falsos(tmp_path):
    almacen = LakeParquet(tmp_path)
    lectores = {
        "okx": lambda desde, ahora: {"funding": dv.interpretar_okx_funding(OKX_FUNDING),
                                     "precios": {"mark": dv.interpretar_okx_velas(OKX_MARK),
                                                 "perp": dv.interpretar_okx_velas(OKX_VELAS_PERP)},
                                     "oi": dv.interpretar_okx_oi(OKX_OI),
                                     "liquidaciones": dv.interpretar_okx_liquidaciones(OKX_LIQ)},
        "kraken": lambda desde, ahora: {"funding": dv.interpretar_kraken_funding(KRAKEN_FUNDING),
                                        "precios": {"mark": dv.interpretar_kraken_velas(KRAKEN_VELAS, 3600, ahora)},
                                        "oi": dv.interpretar_kraken_analitica(KRAKEN_OI),
                                        "liquidaciones": dv.interpretar_kraken_analitica(KRAKEN_LIQ)}}
    r = hd.actualizar_derivados(almacen, dias=30, ahora_utc=AHORA, lectores=lectores)
    assert r["okx"]["escritas"]["derivados_precios"] == 3 and r["kraken"]["escritas"]["derivados_oi"] == 2
    liq = hd.leer_ultimas(almacen.consultar, hd.FUENTE_LIQUIDACIONES)
    assert set(liq["lado"]) == {"long", "short", "total"}
    assert set(liq.loc[liq.exchange == "okx", "intervalo_s"]) == {0}


@pytest.mark.live
def test_okx_funding_real():
    f = dv.interpretar_okx_funding(dv.pedir_json(dv.URL_OKX_FUNDING, {"instId": dv.OKX_SWAP, "limit": 5}))
    assert len(f) == 5 and (f["periodo_h"] > 0).all()


@pytest.mark.live
def test_kraken_funding_real():
    f = dv.interpretar_kraken_funding(dv.pedir_json(dv.URL_KRAKEN_FUNDING, {"symbol": dv.KRAKEN_PERP}))
    assert len(f) > 1000 and (f["periodo_h"] == 1).all()
