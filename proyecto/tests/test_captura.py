import itertools
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from radar.captura.capturador import FUENTE_COTIZACIONES, FUENTE_ERRORES, capturar, ronda
from radar.captura.exchanges import crear_fuentes
from radar.captura.exchanges import bitvavo, kraken, okx
from radar.captura.puertos import LibroLeido

# Respuestas reales de los endpoints de profundidad (21-11-2026), 3 niveles por lado.
KRAKEN = {"error": [], "result": {"XXBTZEUR": {
    "asks": [["54977.60000", "0.313", 1795288243], ["54978.40000", "0.154", 1795288243],
             ["54980.00000", "0.249", 1795288243]],
    "bids": [["54977.50000", "0.249", 1795288243], ["54975.40000", "0.415", 1795288242],
             ["54973.50000", "0.415", 1795288243]]}}}
OKX = {"code": "0", "msg": "", "data": [{
    "asks": [["54992.1", "0.12755635", "0", "2"], ["54993.2", "0.16612727", "0", "1"], ["54994.7", "0.24919045", "0", "1"]],
    "bids": [["54980.4", "0.01032605", "0", "1"], ["54980.1", "0.007644", "0", "1"], ["54980", "0.01032605", "0", "1"]],
    "ts": "1795288244752", "seqId": 9076190845}]}
BITVAVO = {"market": "BTC-EUR", "nonce": 464466439,
           "bids": [["54980", "0.3015911"], ["54978", "0.035561"], ["54977", "0.76864445"]],
           "asks": [["54981", "0.08313502"], ["54984", "0.53575869"], ["54985", "0.00015719"]],
           "timestamp": 1795288245381137578}


def test_adaptadores_interpretan_cada_formato():
    k = kraken.interpretar(KRAKEN)
    assert len(k.bids) == 3 and k.bids[1] == ("54975.40000", "0.415") and k.asks[2] == ("54980.00000", "0.249")
    assert k.hora_exchange_utc == pd.Timestamp(1795288243, unit="s", tz="UTC")
    o = okx.interpretar(OKX)
    assert o.bids[0] == ("54980.4", "0.01032605") and o.asks[1] == ("54993.2", "0.16612727")
    assert o.hora_exchange_utc == pd.Timestamp(1795288244752, unit="ms", tz="UTC")
    b = bitvavo.interpretar(BITVAVO)
    assert b.bids[2] == ("54977", "0.76864445") and b.asks[0] == ("54981", "0.08313502")
    assert b.hora_exchange_utc == pd.Timestamp(1795288245381137578, unit="ns", tz="UTC")  # nanosegundos


def test_foto_del_libro_y_su_mejor_nivel():
    from radar.captura.capturador import foto, foto_libro
    fuente = Fija("bitvavo", bitvavo.interpretar(BITVAVO))
    libro = foto_libro(fuente, 3, reloj_falso())
    assert libro.exchange == "bitvavo" and [n.precio for n in libro.asks] == [54981, 54984, 54985]
    cot = foto(fuente, reloj_falso())
    assert (cot.bid, cot.ask) == (54980, 54981)
    assert fuente.pedidos == [3, 1]  # la foto de la Fase 1 sigue pidiendo solo el mejor nivel


@pytest.mark.parametrize("modulo, datos", [
    (kraken, {"error": ["EGeneral:Invalid arguments"], "result": {}}),
    (okx, {"code": "51001", "msg": "Instrument ID does not exist", "data": []}),
    (bitvavo, {"errorCode": 205, "error": "market parameter is invalid."}),
])
def test_adaptadores_rechazan_errores_de_la_api(modulo, datos):
    with pytest.raises(ValueError, match="error|mercado"):
        modulo.interpretar(datos)


def test_crear_fuentes():
    assert [f.nombre for f in crear_fuentes(["okx", "kraken"])] == ["okx", "kraken"]
    with pytest.raises(ValueError, match="desconocidos"):
        crear_fuentes(["binance"])


class Fija:
    def __init__(self, nombre, libro=None, error=None):
        self.nombre, self.libro, self.error, self.pedidos = nombre, libro, error, []

    def leer(self, niveles):
        self.pedidos.append(niveles)
        if self.error:
            raise self.error
        return self.libro


def leido(bid, ask, cantidad_bid, cantidad_ask):
    return LibroLeido(((bid, cantidad_bid),), ((ask, cantidad_ask),))


class Memoria:
    def __init__(self):
        self.lotes = []

    def guardar(self, filas, fuente):
        self.lotes.append((fuente, list(filas)))
        return []


def reloj_falso():
    instantes = (pd.Timestamp("2026-11-21", tz="UTC") + pd.Timedelta(milliseconds=100 * i) for i in itertools.count())
    return lambda: next(instantes)


FUENTES = [Fija("kraken", leido("60000", "60004", "1", "1")),
           Fija("okx", error=ConnectionError("sin red")),
           Fija("bitvavo", leido("60010", "60000", "1", "1"))]  # libro cruzado


def test_ronda_registra_errores_sin_inventar_datos():
    with ThreadPoolExecutor(3) as hilos:
        libros, errores = ronda(FUENTES, 7, hilos, reloj_falso(), niveles=20)
    assert [l.exchange for l in libros] == ["kraken"] and libros[0].mejor_nivel().spread_eur == 4
    assert {e["exchange"]: e["error"].split(":")[0] for e in errores} == {"okx": "ConnectionError",
                                                                          "bitvavo": "CotizacionInvalida"}
    assert all(e["ronda"] == 7 for e in errores) and libros[0].mejor_nivel().latencia_s > 0
    assert FUENTES[0].pedidos[-1] == 20  # pide los niveles indicados


def test_filas_de_ronda_con_y_sin_comparacion():
    from radar.captura.capturador import FUENTE_COMPARACIONES, FUENTE_CONCLUSIONES, filas_de_ronda
    with ThreadPoolExecutor(3) as hilos:
        libros, errores = ronda(FUENTES, 3, hilos, reloj_falso())
    sin = filas_de_ronda(3, libros, errores)
    assert set(sin) == {FUENTE_COTIZACIONES, FUENTE_ERRORES} and sin[FUENTE_COTIZACIONES][0]["ronda"] == 3
    con = filas_de_ronda(3, libros, errores, 1000, {"kraken": 0.008})
    assert con[FUENTE_COMPARACIONES][0]["exchange"] == "kraken" and con[FUENTE_COMPARACIONES][0]["ronda"] == 3
    assert con[FUENTE_CONCLUSIONES][0]["mas_barato_ejecutable"] == "kraken"
    from radar.captura.capturador import FUENTE_DESEQUILIBRIOS
    filas = filas_de_ronda(3, libros, errores, bandas_bps=(1, 5))[FUENTE_DESEQUILIBRIOS]
    assert [(f["exchange"], f["banda_bps"], f["ronda"]) for f in filas] == [("kraken", 1, 3), ("kraken", 5, 3)]
    assert FUENTE_DESEQUILIBRIOS not in sin  # sin bandas, no se calcula


def test_capturar_guarda_en_lotes():
    tiempo = itertools.count(0, 1)  # cada llamada a monotonic avanza 1 s: sin esperas reales
    almacen = Memoria()
    resumen = capturar(FUENTES[:1], almacen, segundos=5, tam_lote=2, reloj=reloj_falso(),
                       dormir=lambda s: None, monotonic=lambda: next(tiempo))
    cot = [filas for fuente, filas in almacen.lotes if fuente == FUENTE_COTIZACIONES]
    assert resumen == {"rondas": sum(len(f) for f in cot), "errores": 0}
    assert all(len(f) <= 2 for f in cot) and sum(len(f) for f in cot) == resumen["rondas"]
    assert FUENTE_ERRORES in [fuente for fuente, _ in almacen.lotes]


def test_capturar_guarda_comparaciones_y_conclusiones():
    from radar.captura.capturador import FUENTE_COMPARACIONES, FUENTE_CONCLUSIONES
    tiempo = itertools.count(0, 1)
    almacen = Memoria()
    capturar(FUENTES[:1], almacen, segundos=3, importe_eur=1000, comisiones={"kraken": 0.008}, reloj=reloj_falso(),
             dormir=lambda s: None, monotonic=lambda: next(tiempo))
    por_fuente = {}
    for fuente, filas in almacen.lotes:
        por_fuente.setdefault(fuente, []).extend(filas)
    n = len(por_fuente[FUENTE_COTIZACIONES])
    assert len(por_fuente[FUENTE_COMPARACIONES]) == n and len(por_fuente[FUENTE_CONCLUSIONES]) == n


def test_filas_de_ronda_guarda_los_libros_si_se_pide():
    from radar.captura.capturador import FUENTE_LIBROS, filas_de_ronda
    with ThreadPoolExecutor(3) as hilos:
        libros, errores = ronda(FUENTES, 4, hilos, reloj_falso())
    assert FUENTE_LIBROS not in filas_de_ronda(4, libros, errores)
    filas = filas_de_ronda(4, libros, errores, niveles_guardados=50)[FUENTE_LIBROS]
    assert [(f["exchange"], f["ronda"], f["bid_precios"]) for f in filas] == [("kraken", 4, [60000.0])]
