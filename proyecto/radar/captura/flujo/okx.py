"""Protocolo de OKX v5 (público): canales `books` (400 niveles, con `seqId`/`prevSeqId`) y `trades`.

Verificado en la documentación oficial (22-11-2026, https://www.okx.com/docs-v5/en/, secciones "WS / Order book
channel" y "WS / Trades channel") y con mensajes reales:
- URL `wss://ws.okx.com/ws/v5/public` (el puerto 8443 se retira: aviso 64010 del propio servidor); suscripción
  `{"op": "subscribe", "args": [{"channel": "books", "instId": "BTC-EUR"}, ...]}`.
- Libro: `action` "snapshot" / "update"; niveles `[precio, cantidad, "0" (obsoleto), nº de órdenes]` en texto;
  `ts` en milisegundos; cantidad "0" = borrar. Cada actualización trae `prevSeqId` = `seqId` del mensaje anterior
  (el snapshot trae `prevSeqId` = -1). El `checksum` está OBSOLETO (vale siempre 0): no se verifica.
- Trades: `px`, `sz`, `side` (lado del taker), `tradeId` (el último de la agregación), `ts` en ms. Un mensaje
  agrega las ejecuciones de una orden taker a un mismo precio (`count`).
- Mantener viva la conexión: OKX corta a los 30 s sin tráfico; si no llega nada en N < 30 s se manda el texto
  'ping' y contesta 'pong'.
"""

from __future__ import annotations

import json

import pandas as pd

from radar.mercado.reconstruccion import LibroIncremental, a_decimal, continua_okx

from .eventos import ACTUALIZACION, SNAPSHOT, ErrorDelExchange, EventoLibro, Trade
from .parametros import INSTRUMENTO_OKX

URL = "wss://ws.okx.com/ws/v5/public"


def _ms(texto) -> pd.Timestamp:
    return pd.to_datetime(int(texto), unit="ms", utc=True)


def _niveles(lista) -> tuple:
    return tuple((a_decimal(n[0]), a_decimal(n[1])) for n in lista)


class OKX:
    nombre = "okx"
    url = URL
    ping = "ping"
    con_buffer = False

    def __init__(self, instrumento: str = INSTRUMENTO_OKX):
        self.instrumento = instrumento

    def _mensaje(self, op: str, *canales: str) -> str:
        return json.dumps({"op": op, "args": [{"channel": c, "instId": self.instrumento} for c in canales]})

    def suscripcion(self) -> list[str]:
        return [self._mensaje("subscribe", "books", "trades")]

    def resincronizacion(self) -> list[str]:
        """Darse de baja y de alta de `books`: OKX manda un snapshot nuevo."""
        return [self._mensaje("unsubscribe", "books"), self._mensaje("subscribe", "books")]

    def nuevo_libro(self) -> LibroIncremental:
        return LibroIncremental(self.nombre, regla_secuencia=continua_okx)

    def interpretar(self, texto: str) -> list:
        if texto == "pong":
            return []
        mensaje = json.loads(texto)
        if "event" in mensaje:
            if mensaje["event"] == "error":
                raise ErrorDelExchange(f"okx: {mensaje.get('code')}: {mensaje.get('msg')}")
            return []  # subscribe, unsubscribe, notice
        canal = mensaje.get("arg", {}).get("channel")
        if canal == "books":
            tipo = SNAPSHOT if mensaje["action"] == "snapshot" else ACTUALIZACION
            return [EventoLibro(self.nombre, tipo, _niveles(d["bids"]), _niveles(d["asks"]), _ms(d["ts"]),
                                secuencia=int(d["seqId"]), secuencia_previa=int(d["prevSeqId"]))
                    for d in mensaje["data"]]
        if canal == "trades":
            return [Trade(self.nombre, _ms(d["ts"]), a_decimal(d["px"]), a_decimal(d["sz"]), d["side"],
                          str(d["tradeId"])) for d in mensaje["data"]]
        return []
