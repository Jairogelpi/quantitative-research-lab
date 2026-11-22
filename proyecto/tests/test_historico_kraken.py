"""Histórico oficial de Kraken (S2): REST OHLC, CSV OHLCVT, ZIP por partes, vacías, huecos y guardado idempotente."""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.captura import historico_kraken as hk
from radar.captura.exchanges import kraken_historico as kh

# Respuesta real de /0/public/OHLC?pair=XBTEUR&interval=1 (22-11-2026), recortada; la penúltima barra es una vacía
# con el formato que Kraken usa para ellas (tomado de XBTEURC: count 0, vwap "0.0", precios = cierre anterior).
OHLC_REST = {"error": [], "result": {"XXBTZEUR": [
    [1795329540, "53967.1", "54017.7", "53966.8", "53991.1", "53996.9", "0.02717489", 10],
    [1795329600, "54008.4", "54008.4", "53942.3", "53954.7", "53991.6", "0.28802963", 10],
    [1795329660, "53954.7", "53954.7", "53954.7", "53954.7", "0.0", "0.00000000", 0],
    [1795329720, "53964.6", "53968.5", "53937.5", "53938.4", "53943.4", "0.06082100", 6]],
    "last": 1795329660}}

# Formato oficial OHLCVT, sin cabecera (filas reales de XBTEUR_1440.csv del ZIP 2026Q3 y de XBTEUR_60.csv simuladas).
CSV_DIARIO = ("1782864000,51302.0,53899.9,50650.1,52701.6,619.6276025399945,40702\n"
              "1782950400,52701.7,54241.1,52334.0,53831.8,549.1010156099932,29909\n")
CSV_HORARIO = ("1782864000,100.0,101.0,99.0,100.5,2.0,4\n"
               "1782867600,100.5,102.0,100.0,101.0,1.0,2\n"
               "1782878400,101.0,101.0,100.0,100.0,3.0,1\n")   # faltan 02:00 y 03:00: vacías

T0 = pd.Timestamp("2026-07-01 00:00", tz="UTC")
AHORA = pd.Timestamp("2026-11-22 12:00", tz="UTC")


def _zip(ficheros: dict, carpeta: str = "") -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, texto in ficheros.items():
            z.writestr(carpeta + nombre, texto)
    return memoria.getvalue()


def test_ohlc_rest_traduce_columnas_y_cursor():
    barras, last = kh.interpretar_ohlc(OHLC_REST)
    assert last == 1795329660 and len(barras) == 4
    assert list(barras.columns) == kh.BARRA
    assert barras["inicio_utc"].iloc[0] == pd.Timestamp(1795329540, unit="s", tz="UTC")
    assert barras.iloc[0][["apertura", "maximo", "minimo", "cierre", "vwap", "volumen_btc", "n_trades"]].tolist() \
        == [53967.1, 54017.7, 53966.8, 53991.1, 53996.9, 0.02717489, 10.0]


def test_ohlc_rest_con_error_lanza():
    with pytest.raises(ValueError, match="EQuery:Unknown asset pair"):
        kh.interpretar_ohlc({"error": ["EQuery:Unknown asset pair"], "result": {}})


def test_velas_rest_vacia_sin_precios_de_relleno_y_ultima_abierta():
    barras, _ = kh.interpretar_ohlc(OHLC_REST)
    ahora = pd.Timestamp(1795329750, unit="s", tz="UTC")        # dentro de la última barra
    v = hk.velas_rest(barras, 60, ahora)
    assert list(v.columns) == hk.COLUMNAS
    assert v["vacia"].tolist() == [False, False, True, False]
    vacia = v.iloc[2]
    assert np.isnan(vacia["apertura"]) and np.isnan(vacia["cierre"]) and np.isnan(vacia["vwap"])
    assert vacia["volumen_btc"] == 0 and vacia["volumen_eur"] == 0 and vacia["n_trades"] == 0
    assert v["completa"].tolist() == [True, True, True, False]
    assert v["volumen_eur"].iloc[0] == pytest.approx(53996.9 * 0.02717489)
    assert set(v["fuente"]) == {"kraken_historico"} and set(v["exchange"]) == {"kraken"}
    assert set(v["par"]) == {"BTC/EUR"} and set(v["intervalo_s"]) == {60}


def test_csv_ohlcvt_sin_cabecera_y_sin_vwap():
    barras = kh.interpretar_csv_ohlcvt(CSV_DIARIO)
    assert len(barras) == 2 and barras["inicio_utc"].iloc[0] == T0
    assert barras.iloc[0][["apertura", "maximo", "minimo", "cierre", "volumen_btc", "n_trades"]].tolist() \
        == [51302.0, 53899.9, 50650.1, 52701.6, 619.6276025399945, 40702.0]
    assert barras["vwap"].isna().all()


def test_velas_archivo_rellena_las_vacias_que_el_csv_omite():
    v = hk.velas_archivo(kh.interpretar_csv_ohlcvt(CSV_HORARIO), 3600, AHORA)
    assert v["inicio_utc"].tolist() == [T0 + pd.Timedelta(hours=h) for h in range(5)]
    assert v["vacia"].tolist() == [False, False, True, True, False]
    assert v["completa"].all()
    assert v.loc[v["vacia"], "volumen_btc"].eq(0).all() and v.loc[v["vacia"], "cierre"].isna().all()
    assert v.loc[~v["vacia"], "volumen_eur"].isna().all()       # el CSV no da VWAP: € desconocidos


def test_zip_local_con_carpeta_y_por_partes(tmp_path):
    contenido = _zip({"XBTEUR_60.csv": CSV_HORARIO, "XBTEURC_60.csv": "1,1,1,1,1,1,1\n"}, carpeta="Kraken/")
    corte = len(contenido) // 3
    partes = [tmp_path / "a.part00", tmp_path / "a.part01"]
    partes[0].write_bytes(contenido[:corte])
    partes[1].write_bytes(contenido[corte:])
    with kh.abrir_zip(partes) as z:
        barras = kh.leer_csv_de_zip(z, 60)
        assert kh.leer_csv_de_zip(z, 1440) is None
    assert barras["cierre"].tolist() == [100.5, 101.0, 100.0]


def test_importar_zip_es_idempotente(tmp_path):
    ruta = tmp_path / "Kraken_OHLCVT_2026Q3.zip"
    ruta.write_bytes(_zip({"XBTEUR_60.csv": CSV_HORARIO, "XBTEUR_1440.csv": CSV_DIARIO}))
    lake = LakeParquet(tmp_path / "lake")
    primero = hk.importar_zip(lake, ruta, (60, 1440, 5), AHORA)
    assert [r["escritas"] for r in primero] == [5, 2, 0]
    assert primero[2]["aviso"] == "el ZIP no trae XBTEUR_5.csv"
    segundo = hk.importar_zip(lake, ruta, (60, 1440), AHORA + pd.Timedelta(days=1))
    assert [r["escritas"] for r in segundo] == [0, 0]
    assert len(lake.consultar("SELECT * FROM velas")) == 7


def test_rest_aporta_vwap_y_el_csv_no_lo_pisa(tmp_path):
    lake = LakeParquet(tmp_path)
    t = int(T0.timestamp())
    rest = {"error": [], "result": {"XXBTZEUR": [[t, "100.0", "101.0", "99.0", "100.5", "100.2", "2.0", 4]],
                                    "last": t}}
    csv = kh.interpretar_csv_ohlcvt(CSV_HORARIO.splitlines()[0] + "\n")
    assert hk.guardar_velas(lake, hk.velas_archivo(csv, 3600, AHORA)) == 1
    assert hk.guardar_velas(lake, hk.velas_rest(kh.interpretar_ohlc(rest)[0], 3600, AHORA + pd.Timedelta(1, "h"))) == 1
    assert hk.guardar_velas(lake, hk.velas_archivo(csv, 3600, AHORA + pd.Timedelta(2, "h"))) == 0
    ultima = lake.consultar("SELECT * FROM velas ORDER BY recibido_utc DESC LIMIT 1").iloc[0]
    assert ultima["vwap"] == 100.2 and ultima["volumen_eur"] == pytest.approx(200.4)


def test_csv_que_discrepa_no_pisa_la_vela_rest(tmp_path):
    # Caso real (vela diaria del 23-06-2026): el ZIP da 34 729 trades y la REST 34 811.
    lake = LakeParquet(tmp_path)
    t = int(T0.timestamp())
    rest = {"error": [], "result": {"XXBTZEUR": [[t, "100.0", "101.0", "99.0", "100.5", "100.2", "2.5", 5]],
                                    "last": t}}
    csv = kh.interpretar_csv_ohlcvt(CSV_HORARIO.splitlines()[0] + "\n")
    assert hk.guardar_velas(lake, hk.velas_rest(kh.interpretar_ohlc(rest)[0], 3600, AHORA)) == 1
    assert hk.guardar_velas(lake, hk.velas_archivo(csv, 3600, AHORA + pd.Timedelta(1, "h"))) == 0
    assert hk.guardar_velas(lake, hk.velas_rest(kh.interpretar_ohlc(rest)[0], 3600, AHORA + pd.Timedelta(2, "h"))) == 0


def test_vela_abierta_no_pisa_completa_y_cierre_si_se_guarda(tmp_path):
    lake = LakeParquet(tmp_path)
    barras, _ = kh.interpretar_ohlc(OHLC_REST)
    fin = pd.Timestamp(1795329780, unit="s", tz="UTC")
    assert hk.guardar_velas(lake, hk.velas_rest(barras, 60, fin - pd.Timedelta(seconds=10))) == 4
    assert hk.guardar_velas(lake, hk.velas_rest(barras, 60, fin)) == 1          # la última ya terminó
    assert hk.guardar_velas(lake, hk.velas_rest(barras, 60, fin - pd.Timedelta(seconds=5))) == 0


def test_huecos_entre_origenes():
    v = hk.velas_archivo(kh.interpretar_csv_ohlcvt(CSV_HORARIO), 3600, AHORA)
    despues = v.assign(inicio_utc=v["inicio_utc"] + pd.Timedelta(hours=10))
    h = hk.huecos(pd.concat([v, despues]), 3600)
    assert h.to_dict("records") == [{"desde_utc": T0 + pd.Timedelta(hours=5), "hasta_utc": T0 + pd.Timedelta(hours=10),
                                     "n_velas": 5}]
    assert hk.huecos(v, 3600).empty                              # las vacías no son huecos


def test_velas_trades_solo_velas_enteras_y_vwap():
    trades = pd.DataFrame({"hora_exchange_utc": [T0 + pd.Timedelta(seconds=s) for s in (-5, 10, 30, 70, 200)],
                           "precio": [1.0, 100.0, 102.0, 101.0, 99.0], "cantidad": [9.0, 1.0, 3.0, 2.0, 1.0],
                           "lado_agresor": "buy", "trade_id": range(5)})
    v = hk.velas_trades(trades, 60, T0 - pd.Timedelta(seconds=20), T0 + pd.Timedelta(seconds=185), AHORA)
    assert v["inicio_utc"].tolist() == [T0, T0 + pd.Timedelta(minutes=1), T0 + pd.Timedelta(minutes=2)]
    assert v["vacia"].tolist() == [False, False, True]          # el trade de 200 s cae en una vela cortada
    assert v.iloc[0][["apertura", "maximo", "minimo", "cierre", "volumen_btc", "n_trades"]].tolist() \
        == [100.0, 102.0, 100.0, 102.0, 4.0, 2.0]
    assert v["vwap"].iloc[0] == pytest.approx((100 + 306) / 4)


def test_paginar_trades_sigue_el_cursor_y_para_al_pasar_hasta():
    def pagina(ts, ultimo):
        return {"error": [], "result": {"XXBTZEUR": [[f"{100 + i}", "1.0", t, "b", "l", "", i] for i, t in ts],
                                        "last": ultimo}}
    t0 = T0.timestamp()
    respuestas = {int(T0.value): pagina([(1, t0 + 1), (2, t0 + 2)], int(T0.value) + 2_000_000_000),
                  int(T0.value) + 2_000_000_000: pagina([(3, t0 + 3), (4, t0 + 9)], int(T0.value) + 9_000_000_000)}
    pedidos, pausas = [], []

    def pedir(url, params):
        pedidos.append(params["since"])
        return respuestas[params["since"]]
    paginas = list(kh.paginar_trades(T0, T0 + pd.Timedelta(seconds=5), pedir, pausas.append, 1.0))
    assert pedidos == [int(T0.value), int(T0.value) + 2_000_000_000] and pausas == [1.0]
    assert pd.concat(paginas)["trade_id"].tolist() == [1, 2, 3, 4]      # la última página entera: dice hasta dónde llegó


def test_actualizar_rest_respeta_la_pausa_entre_peticiones(tmp_path):
    pausas = []
    resumen = hk.actualizar_rest(LakeParquet(tmp_path), (1, 60), AHORA, leer=lambda m: kh.interpretar_ohlc(OHLC_REST),
                                 dormir=pausas.append)
    assert pausas == [kh.PAUSA_S] and [r["intervalo_s"] for r in resumen] == [60, 3600]


@pytest.mark.live
def test_rest_ohlc_real():
    barras, _ = kh.leer_ohlc(60)
    assert 700 <= len(barras) <= 721 and barras["inicio_utc"].diff().dropna().eq(pd.Timedelta(hours=1)).all()


@pytest.mark.live
def test_zip_trimestral_remoto_por_rangos():
    with kh.abrir_zip(kh.url_trimestre("2026Q3")) as z:
        barras = kh.leer_csv_de_zip(z, 1440)
    assert barras["inicio_utc"].min() == T0 and len(barras) == 92


def test_rellenar_con_trades_incluye_la_ultima_vela_si_se_paso_de_hasta(tmp_path):
    def trades(segundos):
        return pd.DataFrame({"hora_exchange_utc": [T0 + pd.Timedelta(seconds=s) for s in segundos],
                             "precio": 100.0, "cantidad": 1.0, "lado_agresor": "buy", "trade_id": range(len(segundos))})

    def paginar(desde, hasta):
        yield trades([5, 65])
        yield trades([130, 200])                                  # 200 s > hasta: la paginación llegó al final
    resumen = hk.rellenar_con_trades(LakeParquet(tmp_path), T0, T0 + pd.Timedelta(minutes=3), (1,), AHORA,
                                     paginar=paginar)
    assert resumen[0]["velas"] == 3 and resumen[0]["hasta_utc"] == T0 + pd.Timedelta(minutes=2)

    def corta(desde, hasta):
        yield trades([5, 65, 130])                                # se acabaron los trades antes de `hasta`
    resumen = hk.rellenar_con_trades(LakeParquet(tmp_path / "b"), T0, T0 + pd.Timedelta(minutes=3), (1,), AHORA,
                                     paginar=corta)
    assert resumen[0]["velas"] == 2                               # la vela de 130 s no se sabe si terminó
