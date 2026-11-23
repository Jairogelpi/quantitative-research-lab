"""Captura por websocket: intérpretes de cada exchange, sincronización del libro y caso de uso (sin red)."""

import asyncio
import json
from decimal import Decimal

import pandas as pd
import pytest

from radar.captura.flujo import capturar_flujo
from radar.captura.flujo import bitvavo, kraken, okx
from radar.captura.flujo.captura import (FUENTE_ERRORES, FUENTE_EVENTOS, FUENTE_LIBROS_FLUJO, FUENTE_TRADES,
                                         filas_evento, fila_trade)
from radar.captura.flujo.eventos import ErrorDelExchange, EventoLibro, Trade
from radar.captura.flujo.sincronizacion import Sincronizador
from radar.mercado.reconstruccion import HUECO

D = Decimal

# --- mensajes reales (capturados el 22-11-2026, recortados) --------------------------------------------------------

KRAKEN_SNAPSHOT = ('{"channel":"book","type":"snapshot","data":[{"symbol":"BTC/EUR",'
                   '"bids":[{"price":55703.4,"qty":0.02937000},{"price":55702.8,"qty":0.05988956}],'
                   '"asks":[{"price":55729.8,"qty":0.27793726},{"price":55729.9,"qty":0.15390000}],'
                   '"checksum":CK,"timestamp":"2026-11-22T11:59:04.100000Z"}]}')
KRAKEN_UPDATE = ('{"channel":"book","type":"update","data":[{"symbol":"BTC/EUR","bids":[{"price":55702.8,'
                 '"qty":0.00000000},{"price":55691.3,"qty":0.00448892}],"asks":[],"checksum":2534080052,'
                 '"timestamp":"2026-11-22T11:59:04.239502Z"}]}')
KRAKEN_TRADE = ('{"channel":"trade","type":"update","data":[{"symbol":"BTC/EUR","side":"sell","price":55703.4,'
                '"qty":0.00120000,"ord_type":"market","trade_id":81234567,"timestamp":"2026-11-22T11:59:05.000001Z"}]}')
OKX_SNAPSHOT = ('{"arg":{"channel":"books","instId":"BTC-EUR"},"action":"snapshot","data":[{"asks":[["55732.5",'
                '"0.00191549","0","1"],["55734","0.24580143","0","1"]],"bids":[["55704","0.16395176","0","1"],'
                '["55702.7","0.00221393","0","1"]],"ts":"1795348745803","checksum":0,"prevSeqId":-1,"seqId":100}]}')
OKX_UPDATE = ('{"arg":{"channel":"books","instId":"BTC-EUR"},"action":"update","data":[{"asks":[],"bids":[["55704",'
              '"0","0","0"],["55701.2","0.32790352","0","1"]],"ts":"1795348746203","checksum":0,"seqId":116,'
              '"prevSeqId":100}]}')
OKX_TRADE = ('{"arg":{"channel":"trades","instId":"BTC-EUR"},"data":[{"instId":"BTC-EUR","tradeId":"130639474",'
             '"px":"55720.1","sz":"0.0102","side":"buy","ts":"1795348746300","count":"2","source":"0","seqId":1234}]}')
BITVAVO_UPDATE = ('{"event":"book","market":"BTC-EUR","nonce":465068489,"bids":[["55552.00","0.00082298"],'
                  '["49194.00","0"]],"asks":[],"timestamp":1795348747149582605}')
BITVAVO_GETBOOK = ('{"action":"getBook","requestId":1,"response":{"market":"BTC-EUR","nonce":465068488,"bids":'
                   '[["55719","0.06634963"],["55717","0.01637832"]],"asks":[["55720","0.12283742"],["55721",'
                   '"0.64272701"]],"timestamp":1795348747050592541}}')
BITVAVO_TRADE = ('{"event":"trade","id":"391f4d94-485f-4fb0-b11f-39da1cfcfc2d","amount":"0.00096361","price":"55720",'
                 '"timestamp":1795348747300,"market":"BTC-EUR","side":"sell","timestampNs":1795348747300123456}')


def kraken_snapshot_valido():
    """Snapshot de Kraken con el checksum que corresponde a sus niveles (calculado con la regla oficial)."""
    from radar.mercado.reconstruccion import LibroIncremental, checksum_kraken
    libro = LibroIncremental("kraken")
    ev = kraken.Kraken().interpretar(KRAKEN_SNAPSHOT.replace("CK", "0"))[0]
    libro.aplicar_snapshot(ev.bids, ev.asks)
    return KRAKEN_SNAPSHOT.replace("CK", str(checksum_kraken(libro, 1, 8)))


# --- intérpretes ---------------------------------------------------------------------------------------------------

def test_kraken_interpreta_libro_y_trade_con_decimales_exactos():
    p = kraken.Kraken()
    snap = p.interpretar(KRAKEN_SNAPSHOT.replace("CK", "123"))[0]
    assert isinstance(snap, EventoLibro) and snap.tipo == "snapshot" and snap.checksum == 123
    assert snap.bids[0] == (D("55703.4"), D("0.02937000")) and str(snap.bids[0][1]) == "0.02937000"
    assert snap.hora_exchange_utc == pd.Timestamp("2026-11-22T11:59:04.1Z")
    upd = p.interpretar(KRAKEN_UPDATE)[0]
    assert upd.tipo == "update" and upd.bids[0] == (D("55702.8"), D(0)) and upd.asks == ()
    trade = p.interpretar(KRAKEN_TRADE)[0]
    assert trade == Trade("kraken", pd.Timestamp("2026-11-22T11:59:05.000001Z"), D("55703.4"), D("0.00120000"),
                          "sell", "81234567")


def test_kraken_ignora_control_y_rechaza_errores():
    p = kraken.Kraken()
    for texto in ('{"channel":"heartbeat"}', '{"channel":"status","type":"update","data":[{"system":"online"}]}',
                  '{"method":"subscribe","result":{"channel":"book"},"success":true}', '{"method":"pong"}'):
        assert p.interpretar(texto) == []
    with pytest.raises(ErrorDelExchange, match="Currency pair not supported"):
        p.interpretar('{"method":"subscribe","success":false,"error":"Currency pair not supported XXX/EUR"}')


def test_okx_interpreta_libro_secuencia_y_trade():
    p = okx.OKX()
    snap = p.interpretar(OKX_SNAPSHOT)[0]
    assert (snap.tipo, snap.secuencia, snap.secuencia_previa) == ("snapshot", 100, -1)
    assert snap.asks[1] == (D("55734"), D("0.24580143"))
    assert snap.checksum is None  # el checksum de OKX está obsoleto (siempre 0): no se usa
    assert snap.hora_exchange_utc == pd.Timestamp(1795348745803, unit="ms", tz="UTC")
    upd = p.interpretar(OKX_UPDATE)[0]
    assert (upd.tipo, upd.secuencia, upd.secuencia_previa) == ("update", 116, 100)
    assert p.interpretar(OKX_TRADE) == [Trade("okx", pd.Timestamp(1795348746300, unit="ms", tz="UTC"), D("55720.1"),
                                              D("0.0102"), "buy", "130639474")]
    assert p.interpretar("pong") == []
    assert p.interpretar('{"event":"subscribe","arg":{"channel":"books","instId":"BTC-EUR"},"connId":"a"}') == []
    with pytest.raises(ErrorDelExchange, match="60012"):
        p.interpretar('{"event":"error","code":"60012","msg":"Invalid request","connId":"a"}')


def test_bitvavo_interpreta_getbook_actualizacion_y_trade():
    p = bitvavo.Bitvavo()
    snap = p.interpretar(BITVAVO_GETBOOK)[0]
    assert (snap.tipo, snap.secuencia) == ("snapshot", 465068488)
    assert snap.hora_exchange_utc == pd.Timestamp(1795348747050592541, unit="ns", tz="UTC")
    upd = p.interpretar(BITVAVO_UPDATE)[0]
    assert (upd.tipo, upd.secuencia) == ("update", 465068489) and upd.bids[1] == (D("49194.00"), D(0))
    trade = p.interpretar(BITVAVO_TRADE)[0]
    assert trade == Trade("bitvavo", pd.Timestamp(1795348747300123456, unit="ns", tz="UTC"), D("55720"),
                          D("0.00096361"), "sell", "391f4d94-485f-4fb0-b11f-39da1cfcfc2d")
    assert p.interpretar('{"event":"subscribed","subscriptions":{"book":["BTC-EUR"]}}') == []
    with pytest.raises(ErrorDelExchange, match="205"):
        p.interpretar('{"action":"getBook","errorCode":205,"error":"market parameter is invalid."}')


def test_suscripciones_piden_libro_y_trades_del_par():
    k = [json.loads(m) for m in kraken.Kraken().suscripcion()]
    assert {(m["params"]["channel"], m["params"]["symbol"][0]) for m in k} == {("book", "BTC/EUR"), ("trade", "BTC/EUR")}
    o = json.loads(okx.OKX().suscripcion()[0])
    assert o["op"] == "subscribe" and {a["channel"] for a in o["args"]} == {"books", "trades"}
    b = [json.loads(m) for m in bitvavo.Bitvavo().suscripcion()]
    assert b[0]["action"] == "subscribe" and b[1]["action"] == "getBook" and b[1]["market"] == "BTC-EUR"


# --- filas ---------------------------------------------------------------------------------------------------------

def test_filas_de_eventos_una_por_nivel_y_de_trades():
    recibido = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")
    filas = filas_evento(okx.OKX().interpretar(OKX_UPDATE)[0], recibido)
    assert filas == [
        {"exchange": "okx", "recibido_utc": recibido, "hora_exchange_utc": pd.Timestamp(1795348746203, unit="ms", tz="UTC"),
         "tipo": "update", "lado": "bid", "precio": 55704.0, "cantidad": 0.0, "secuencia": 116},
        {"exchange": "okx", "recibido_utc": recibido, "hora_exchange_utc": pd.Timestamp(1795348746203, unit="ms", tz="UTC"),
         "tipo": "update", "lado": "bid", "precio": 55701.2, "cantidad": 0.32790352, "secuencia": 116}]
    t = fila_trade(okx.OKX().interpretar(OKX_TRADE)[0], recibido)
    assert t == {"exchange": "okx", "recibido_utc": recibido,
                 "hora_exchange_utc": pd.Timestamp(1795348746300, unit="ms", tz="UTC"), "precio": 55720.1,
                 "cantidad": 0.0102, "lado_agresor": "buy", "trade_id": "130639474"}


# --- sincronización ------------------------------------------------------------------------------------------------

def test_sincronizador_ignora_cambios_antes_del_snapshot_sin_buffer():
    p = okx.OKX()
    s = Sincronizador(p.nuevo_libro())
    assert s.aplicar(p.interpretar(OKX_UPDATE)[0]) is None and s.ignorados == 1 and not s.libro.sincronizado
    s.aplicar(p.interpretar(OKX_SNAPSHOT)[0])
    assert s.aplicar(p.interpretar(OKX_UPDATE)[0]) is None
    assert s.libro.mejores("bid", 1) == ((D("55702.7"), D("0.00221393")),)


def test_sincronizador_okx_avisa_del_hueco():
    p = okx.OKX()
    s = Sincronizador(p.nuevo_libro())
    s.aplicar(p.interpretar(OKX_SNAPSHOT)[0])
    hueco = s.aplicar(p.interpretar(OKX_UPDATE.replace('"prevSeqId":100', '"prevSeqId":105'))[0])
    assert hueco is not None and hueco.motivo == HUECO and not s.libro.sincronizado


def test_sincronizador_kraken_checksum():
    p = kraken.Kraken()
    s = Sincronizador(p.nuevo_libro())
    assert s.aplicar(p.interpretar(kraken_snapshot_valido())[0]) is None and s.libro.sincronizado
    mal = s.aplicar(p.interpretar(KRAKEN_UPDATE)[0])  # su checksum es del libro real de 10 niveles, no de este
    assert mal is not None and mal.motivo == "checksum"


def test_sincronizador_bitvavo_guarda_cambios_y_descarta_los_viejos():
    p = bitvavo.Bitvavo()
    s = Sincronizador(p.nuevo_libro(), con_buffer=True)
    viejo = BITVAVO_UPDATE.replace("465068489", "465068487")
    assert s.aplicar(p.interpretar(viejo)[0]) is None and s.aplicar(p.interpretar(BITVAVO_UPDATE)[0]) is None
    assert s.aplicar(p.interpretar(BITVAVO_GETBOOK)[0]) is None  # nonce 488: descarta 487, aplica 489
    assert s.libro.secuencia == 465068489
    assert s.libro.mejores("bid", 3) == ((D("55719"), D("0.06634963")), (D("55717"), D("0.01637832")))  # 55552 fuera de rango
    hueco = s.aplicar(p.interpretar(BITVAVO_UPDATE.replace("465068489", "465068495"))[0])
    assert hueco is not None and hueco.motivo == HUECO and s.esperando_snapshot


def test_sincronizador_bitvavo_hueco_entre_snapshot_y_buffer():
    p = bitvavo.Bitvavo()
    s = Sincronizador(p.nuevo_libro(), con_buffer=True)
    s.aplicar(p.interpretar(BITVAVO_UPDATE.replace("465068489", "465068491"))[0])
    hueco = s.aplicar(p.interpretar(BITVAVO_GETBOOK)[0])  # 488 → 491: faltan 489 y 490
    assert hueco is not None and hueco.motivo == HUECO


# --- caso de uso con conexiones falsas -----------------------------------------------------------------------------

class AlmacenFalso:
    def __init__(self):
        self.guardados = []

    def guardar(self, filas, fuente):
        self.guardados.append((fuente, list(filas)))

    def filas(self, fuente):
        return [f for nombre, filas in self.guardados if nombre == fuente for f in filas]


class ConexionFalsa:
    """Devuelve los mensajes del guion; si un mensaje es una excepción, la lanza (conexión caída)."""

    def __init__(self, guion, enviados):
        self.guion, self.enviados = list(guion), enviados

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, texto):
        self.enviados.append(texto)

    async def recv(self):
        if not self.guion:
            await asyncio.sleep(10)
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, BaseException):
            raise siguiente
        await asyncio.sleep(0)
        return siguiente


def conectar_falso(guiones, enviados):
    """`guiones`: {url: [guion de la 1.ª conexión, de la 2.ª, ...]}; una excepción en lugar de guion = fallo al conectar."""
    def conectar(url):
        siguiente = guiones[url].pop(0) if guiones[url] else []
        if isinstance(siguiente, BaseException):
            raise siguiente
        return ConexionFalsa(siguiente, enviados.setdefault(url, []))
    return conectar


def capturar_prueba(protocolos, guiones, segundos=0.4, **opciones):
    almacen, enviados = AlmacenFalso(), {}
    resumen = capturar_flujo(protocolos, almacen, segundos, conectar=conectar_falso(guiones, enviados),
                             intervalo_libros=0.05, espera_mensaje=5, espera_reconexion=0.01, **opciones)
    return almacen, enviados, resumen


def test_captura_guarda_eventos_trades_y_libros_reconstruidos_en_lotes():
    p = okx.OKX()
    almacen, enviados, resumen = capturar_prueba([p], {p.url: [[OKX_SNAPSHOT, OKX_UPDATE, OKX_TRADE]]}, tam_lote=3)
    eventos = almacen.filas(FUENTE_EVENTOS)
    assert len(eventos) == 6 and {e["tipo"] for e in eventos} == {"snapshot", "update"}
    assert all(len(filas) <= 3 for fuente, filas in almacen.guardados if fuente == FUENTE_EVENTOS)  # en lotes
    assert [t["trade_id"] for t in almacen.filas(FUENTE_TRADES)] == ["130639474"]
    libros = almacen.filas(FUENTE_LIBROS_FLUJO)
    assert libros and libros[-1]["bid_precios"] == [55702.7, 55701.2] and libros[-1]["exchange"] == "okx"
    assert libros[-1]["secuencia"] == 116
    assert almacen.filas(FUENTE_ERRORES) == []
    assert resumen["eventos_libro"] == 6 and resumen["trades"] == 1 and resumen["errores"] == 0
    assert json.loads(enviados[p.url][0])["op"] == "subscribe"


def test_captura_resincroniza_tras_un_hueco_y_lo_registra():
    p = okx.OKX()
    hueco = OKX_UPDATE.replace('"prevSeqId":100', '"prevSeqId":105')
    almacen, enviados, resumen = capturar_prueba([p], {p.url: [[OKX_SNAPSHOT, hueco, OKX_SNAPSHOT, OKX_UPDATE]]})
    errores = almacen.filas(FUENTE_ERRORES)
    assert len(errores) == 1 and errores[0]["exchange"] == "okx" and "hueco_secuencia" in errores[0]["error"]
    ops = [json.loads(m)["op"] for m in enviados[p.url]]
    assert ops == ["subscribe", "unsubscribe", "subscribe"]  # se vuelve a pedir el snapshot
    assert almacen.filas(FUENTE_LIBROS_FLUJO)[-1]["bid_precios"] == [55702.7, 55701.2]
    assert resumen["resincronizaciones"] == 1


def test_sin_libro_sincronizado_no_se_inventa_ninguna_foto():
    p = okx.OKX()
    almacen, _, _ = capturar_prueba([p], {p.url: [[OKX_UPDATE]]}, segundos=0.2)
    assert almacen.filas(FUENTE_LIBROS_FLUJO) == []


def test_captura_reconecta_y_registra_la_caida():
    p = bitvavo.Bitvavo()
    guiones = {p.url: [OSError("sin red"), [BITVAVO_GETBOOK, ConnectionResetError("cortada")],
                       [BITVAVO_GETBOOK, BITVAVO_TRADE]]}
    almacen, enviados, resumen = capturar_prueba([p], guiones)
    errores = [e["error"] for e in almacen.filas(FUENTE_ERRORES)]
    assert any("sin red" in e for e in errores) and any("cortada" in e for e in errores)
    assert all(e.get("origen") == "flujo" for e in almacen.filas(FUENTE_ERRORES))
    assert [t["trade_id"] for t in almacen.filas(FUENTE_TRADES)] == ["391f4d94-485f-4fb0-b11f-39da1cfcfc2d"]
    assert resumen["reconexiones"] >= 2


def test_captura_de_varios_exchanges_a_la_vez():
    k, b = kraken.Kraken(), bitvavo.Bitvavo()
    almacen, _, _ = capturar_prueba([k, b], {k.url: [[kraken_snapshot_valido(), KRAKEN_TRADE]],
                                             b.url: [[BITVAVO_GETBOOK]]})
    assert {l["exchange"] for l in almacen.filas(FUENTE_LIBROS_FLUJO)} == {"kraken", "bitvavo"}
    assert [t["exchange"] for t in almacen.filas(FUENTE_TRADES)] == ["kraken"]


@pytest.mark.live
def test_captura_real_unos_segundos():
    almacen = AlmacenFalso()
    resumen = capturar_flujo([kraken.Kraken(), okx.OKX(), bitvavo.Bitvavo()], almacen, 8)
    assert resumen["eventos_libro"] > 0
    assert {l["exchange"] for l in almacen.filas(FUENTE_LIBROS_FLUJO)} == {"kraken", "okx", "bitvavo"}


class AlmacenQueFallaUnaVez(AlmacenFalso):
    """Falla la primera escritura de `fuente` (un disco lleno un momento, un fichero bloqueado)."""

    def __init__(self, fuente):
        super().__init__()
        self.fuente, self.fallo = fuente, False

    def guardar(self, filas, fuente):
        if fuente == self.fuente and not self.fallo:
            self.fallo = True
            raise OSError("disco ocupado")
        super().guardar(filas, fuente)


def test_una_escritura_fallida_no_detiene_las_fotos_ni_duplica_filas():
    p = okx.OKX()
    almacen, enviados = AlmacenQueFallaUnaVez(FUENTE_LIBROS_FLUJO), {}
    resumen = capturar_flujo([p], almacen, 0.6, conectar=conectar_falso({p.url: [[OKX_SNAPSHOT, OKX_UPDATE]]}, enviados),
                             intervalo_libros=0.05, intervalo_volcado=0.1, espera_mensaje=5, espera_reconexion=0.01)
    libros = almacen.filas(FUENTE_LIBROS_FLUJO)
    assert len(libros) >= 5 and resumen["libros"] == len(libros)  # las fotos siguieron y ninguna se perdió
    errores = almacen.filas(FUENTE_ERRORES)
    assert len(errores) == 1 and "disco ocupado" in errores[0]["error"] and resumen["errores"] == 1
    eventos = almacen.filas(FUENTE_EVENTOS)
    assert len(eventos) == len({(e["tipo"], e["lado"], e["precio"], e["secuencia"]) for e in eventos})  # sin duplicados


def test_eventos_persistidos_tienen_trazabilidad_de_sesion_y_decimales():
    p = okx.OKX()
    almacen, _, _ = capturar_prueba(
        [p], {p.url: [[OKX_SNAPSHOT, OKX_UPDATE, OKX_TRADE]]}, segundos=0.2)
    eventos = almacen.filas(FUENTE_EVENTOS)
    trades = almacen.filas(FUENTE_TRADES)
    libros = almacen.filas(FUENTE_LIBROS_FLUJO)
    assert eventos and trades and libros
    assert len({f["captura_id"] for f in eventos + trades + libros}) == 1
    assert len({f["conexion_id"] for f in eventos + trades + libros}) == 1
    assert all("secuencia_previa" in f and "checksum" in f for f in eventos)
    assert all("precio_decimal" in f and "cantidad_decimal" in f for f in eventos)
    assert any(f["secuencia_previa"] == 100 for f in eventos)
