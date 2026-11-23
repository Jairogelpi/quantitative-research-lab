"""Caso de uso: capturar por websocket el flujo del libro y los trades, reconstruir el libro y guardarlo todo.

Conceptos:
- Flujo (stream) frente a fotos: en vez de pedir el libro cada segundo, se recibe CADA cambio en cuanto ocurre;
  entre dos fotos no se pierde nada.
- Una conexión por exchange, todas a la vez en un bucle `asyncio` (concurrencia sin hilos: mientras una conexión
  espera datos, las otras trabajan).
- Reconexión con espera exponencial (backoff): tras un fallo se espera 1 s, luego 2, 4… hasta un máximo; así no
  se martillea a un exchange caído. Al reconectar, el libro empieza de cero con un snapshot nuevo.
- Resincronización: ante un hueco de secuencia o un checksum distinto se descarta el libro, se registra la
  incidencia y se pide otro snapshot por la misma conexión.
- Mantener viva la conexión: si no llega nada en `espera_mensaje` segundos se manda un ping del exchange; si sigue
  sin llegar nada, la conexión se da por muerta y se reconecta.
- Foto periódica: cada `intervalo_libros` segundos se guarda el libro reconstruido de cada exchange (mismo formato
  que `libros`, fuente aparte). Si un exchange no tiene libro sincronizado en ese momento, NO hay foto: no se
  inventa ni se repite la anterior.
- Lote (batch): las filas se acumulan por fuente y se escriben juntas (`Almacen.guardar`).
- UTC: todas las horas en tiempo universal.

Fuentes que escribe: `eventos_libro` (una fila por nivel cambiado; todo lo recibido, también lo que llegó antes
del snapshot), `trades`, `libros_flujo` (la foto periódica, con la `secuencia` del libro) y `errores_captura`
(con `origen` = "flujo").
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Callable

import pandas as pd

from radar.almacen.puertos import Almacen
from radar.configuracion import NIVELES_GUARDADOS, PAR
from radar.mercado import CotizacionInvalida

from .eventos import EventoLibro, Trade
from .parametros import (ESPERA_MAX_RECONEXION_S, ESPERA_MENSAJE_S, ESPERA_RECONEXION_S, INTERVALO_LIBROS_S,
                         INTERVALO_VOLCADO_S, TAM_LOTE_FLUJO)
from .sincronizacion import Sincronizador

FUENTE_EVENTOS, FUENTE_TRADES = "eventos_libro", "trades"
FUENTE_LIBROS_FLUJO, FUENTE_ERRORES = "libros_flujo", "errores_captura"
ORIGEN = "flujo"


def ahora_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


# --- filas (puras) -------------------------------------------------------------------------------------------------

def filas_evento(evento: EventoLibro, recibido: pd.Timestamp) -> list[dict]:
    """Una fila por nivel cambiado (o enviado en el snapshot)."""
    comun = {"exchange": evento.exchange, "recibido_utc": recibido, "hora_exchange_utc": evento.hora_exchange_utc,
             "tipo": evento.tipo}
    return [{**comun, "lado": lado, "precio": float(p), "cantidad": float(c), "secuencia": evento.secuencia}
            for lado, niveles in (("bid", evento.bids), ("ask", evento.asks)) for p, c in niveles]


def fila_trade(trade: Trade, recibido: pd.Timestamp) -> dict:
    return {"exchange": trade.exchange, "recibido_utc": recibido, "hora_exchange_utc": trade.hora_exchange_utc,
            "precio": float(trade.precio), "cantidad": float(trade.cantidad), "lado_agresor": trade.lado_agresor,
            "trade_id": trade.trade_id}


def fila_error(exchange: str, recibido: pd.Timestamp, error: BaseException) -> dict:
    """Misma forma que los errores de `capturador` (sin `ronda`, que aquí no existe; con `origen`)."""
    return {"exchange": exchange, "recibido_utc": recibido, "error": f"{type(error).__name__}: {error}",
            "origen": ORIGEN}


# --- estado compartido de una captura ------------------------------------------------------------------------------

class _Captura:
    def __init__(self, almacen: Almacen, tam_lote: int, reloj: Callable[[], pd.Timestamp]):
        self.almacen, self.tam_lote, self.reloj = almacen, tam_lote, reloj
        self.lotes: dict[str, list] = {}
        self.captura_id = uuid.uuid4().hex
        self.conexiones: dict[str, str] = {}
        self.sincronizadores: dict[str, Sincronizador | None] = {}
        self.cuenta = {"eventos_libro": 0, "trades": 0, "libros": 0, "errores": 0, "resincronizaciones": 0,
                       "reconexiones": 0}

    def anadir(self, fuente: str, filas: list[dict]):
        lote = self.lotes.setdefault(fuente, [])
        lote.extend([{**fila, "captura_id": self.captura_id} for fila in filas])
        while len(lote) >= self.tam_lote:
            self.almacen.guardar(lote[:self.tam_lote], fuente)
            del lote[:self.tam_lote]

    def volcar(self):
        """Escribe lo pendiente de cada fuente. La que falla conserva sus filas para el próximo volcado y las que
        ya se escribieron se vacían, para no escribirlas dos veces al reintentar."""
        fallo = None
        for fuente, filas in self.lotes.items():
            if not filas:
                continue
            try:
                self.almacen.guardar(list(filas), fuente)
            except Exception as exc:  # noqa: BLE001 — se reintenta en el siguiente volcado
                fallo = fallo or exc
                continue
            filas.clear()
        if fallo is not None:
            raise fallo

    def error(self, exchange: str, error: BaseException):
        self.anadir(FUENTE_ERRORES, [{**fila_error(exchange, self.reloj(), error),
                                      "conexion_id": self.conexiones.get(exchange)}])
        self.cuenta["errores"] += 1

    def foto(self, niveles: int, par: str):
        instante = self.reloj()
        for nombre, sinc in self.sincronizadores.items():
            if sinc is None or sinc.esperando_snapshot:
                continue
            try:
                libro = sinc.libro.libro(niveles, instante, par)
            except (CotizacionInvalida, ValueError) as exc:  # libro cruzado o vacío: se registra, no se guarda
                self.error(nombre, exc)
                continue
            self.anadir(FUENTE_LIBROS_FLUJO, [{**libro.a_fila(niveles), "secuencia": sinc.libro.secuencia,
                                                "conexion_id": self.conexiones.get(nombre)}])
            self.cuenta["libros"] += 1


# --- bucles asíncronos ---------------------------------------------------------------------------------------------

async def _recibir(ws, protocolo, espera: float) -> str:
    """Siguiente mensaje; tras `espera` s sin nada manda un ping y, si sigue sin llegar nada, lanza TimeoutError."""
    try:
        return await asyncio.wait_for(ws.recv(), espera)
    except asyncio.TimeoutError:
        if protocolo.ping is not None:
            await ws.send(protocolo.ping)
    try:
        return await asyncio.wait_for(ws.recv(), espera)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{protocolo.nombre}: sin mensajes en {2 * espera:.0f} s") from None


async def _sesion(protocolo, c: _Captura, conectar, espera_mensaje: float, espera_reconexion: float,
                  espera_max: float):
    """Conexión de un exchange, para siempre (la cancela `_capturar` al terminar el tiempo)."""
    espera = espera_reconexion
    while True:
        try:
            async with conectar(protocolo.url) as ws:
                c.conexiones[protocolo.nombre] = uuid.uuid4().hex
                sinc = Sincronizador(protocolo.nuevo_libro(), con_buffer=protocolo.con_buffer)
                c.sincronizadores[protocolo.nombre] = sinc
                for mensaje in protocolo.suscripcion():
                    await ws.send(mensaje)
                while True:
                    texto = await _recibir(ws, protocolo, espera_mensaje)
                    recibido = c.reloj()
                    for evento in protocolo.interpretar(texto):
                        espera = espera_reconexion  # llegan datos: la conexión funciona
                        if isinstance(evento, Trade):
                            c.anadir(FUENTE_TRADES, [{**fila_trade(evento, recibido),
                                                       "conexion_id": c.conexiones.get(protocolo.nombre)}])
                            c.cuenta["trades"] += 1
                            continue
                        filas = filas_evento(evento, recibido)
                        niveles_decimales = (*evento.bids, *evento.asks)
                        filas = [{**fila, "secuencia_previa": evento.secuencia_previa,
                                  "checksum": evento.checksum,
                                  "precio_decimal": str(nivel[0]), "cantidad_decimal": str(nivel[1]),
                                  "conexion_id": c.conexiones.get(protocolo.nombre)}
                                 for fila, nivel in zip(filas, niveles_decimales)]
                        c.anadir(FUENTE_EVENTOS, filas)
                        c.cuenta["eventos_libro"] += len(filas)
                        desincronizacion = sinc.aplicar(evento)
                        if desincronizacion is not None:
                            c.error(protocolo.nombre, desincronizacion)
                            c.cuenta["resincronizaciones"] += 1
                            for mensaje in protocolo.resincronizacion():
                                await ws.send(mensaje)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # red, exchange, mensaje ilegible: se registra y se reconecta
            c.sincronizadores[protocolo.nombre] = None  # sin conexión no hay libro fiable
            c.error(protocolo.nombre, exc)
            c.cuenta["reconexiones"] += 1
            await asyncio.sleep(espera)
            espera = min(2 * espera, espera_max)


async def _fotos(c: _Captura, intervalo: float, intervalo_volcado: float, niveles: int, par: str):
    bucle = asyncio.get_running_loop()
    ultimo_volcado = bucle.time()
    while True:
        await asyncio.sleep(intervalo)
        # Una escritura fallida (disco ocupado, fichero bloqueado) se registra y se reintenta: no puede terminar
        # en silencio con las fotos y los volcados del resto de la captura.
        try:
            c.foto(niveles, par)
            if bucle.time() - ultimo_volcado >= intervalo_volcado:
                c.volcar()
                ultimo_volcado = bucle.time()
        except Exception as exc:  # noqa: BLE001
            c.error(ORIGEN, exc)


async def _capturar(protocolos, c: _Captura, segundos: float, conectar, intervalo_libros: float,
                    intervalo_volcado: float, niveles: int, par: str, espera_mensaje: float,
                    espera_reconexion: float, espera_max: float):
    tareas = [asyncio.create_task(_sesion(p, c, conectar, espera_mensaje, espera_reconexion, espera_max))
              for p in protocolos]
    tareas.append(asyncio.create_task(_fotos(c, intervalo_libros, intervalo_volcado, niveles, par)))
    # No dejar tareas receptoras muertas silenciosamente: cualquier excepción
    # inesperada termina el servicio y permite al supervisor reiniciarlo.
    temporizador = asyncio.create_task(asyncio.sleep(segundos)) if segundos is not None else None
    try:
        pendientes = [*tareas, *([temporizador] if temporizador is not None else [])]
        terminadas, _ = await asyncio.wait(pendientes, return_when=asyncio.FIRST_COMPLETED)
        for tarea in terminadas:
            if tarea is not temporizador:
                tarea.result()  # propaga el error original
                raise RuntimeError("Terminó inesperadamente una tarea de captura")
    finally:
        if temporizador is not None:
            temporizador.cancel()
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)


def _conectar_websocket(url: str):
    from websockets.asyncio.client import connect
    return connect(url, max_size=None)


def crear_protocolos(nombres) -> list:
    from . import bitvavo, kraken, okx
    clases = {"kraken": kraken.Kraken, "okx": okx.OKX, "bitvavo": bitvavo.Bitvavo}
    return [clases[n]() for n in nombres]


def capturar_flujo(exchanges, almacen: Almacen, segundos: float | None, tam_lote: int = TAM_LOTE_FLUJO,
                   intervalo_libros: float = INTERVALO_LIBROS_S, intervalo_volcado: float = INTERVALO_VOLCADO_S,
                   niveles_guardados: int = NIVELES_GUARDADOS, par: str = PAR, conectar=_conectar_websocket,
                   espera_mensaje: float = ESPERA_MENSAJE_S, espera_reconexion: float = ESPERA_RECONEXION_S,
                   espera_max: float = ESPERA_MAX_RECONEXION_S, reloj=ahora_utc,
                   escritura_en_hilo: bool = False) -> dict:
    """Captura `segundos` de flujo de los `exchanges` (nombres o protocolos) y lo guarda en `almacen`.
    Devuelve un resumen con lo guardado y las incidencias."""
    protocolos = [crear_protocolos([e])[0] if isinstance(e, str) else e for e in exchanges]
    from radar.almacen.cola import ColaEscritura

    escritor = ColaEscritura(almacen) if escritura_en_hilo else almacen
    c = _Captura(escritor, tam_lote, reloj)
    try:
        asyncio.run(_capturar(protocolos, c, segundos, conectar, intervalo_libros, intervalo_volcado,
                              niveles_guardados, par, espera_mensaje, espera_reconexion, espera_max))
    finally:
        try:
            c.volcar()
        finally:
            if escritura_en_hilo:
                escritor.cerrar()
    return dict(c.cuenta)
