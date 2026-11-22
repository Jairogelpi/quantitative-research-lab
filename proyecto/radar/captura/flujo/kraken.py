"""Protocolo de Kraken WS v2 (público): canales `book` (con checksum CRC32) y `trade`.

Verificado en la documentación oficial (22-11-2026) y con mensajes reales:
- URL `wss://ws.kraken.com/v2`; suscripción `{"method": "subscribe", "params": {"channel": "book", "symbol": [...],
  "depth": N, "snapshot": true}}` (https://docs.kraken.com/api/docs/websocket-v2/book).
- Libro: mensajes `type` "snapshot" / "update" con `data[]` → `bids`/`asks` como `{"price", "qty"}` NUMÉRICOS
  (con los ceros de su precisión en el texto: se leen como `Decimal` para no perderlos), `checksum` y `timestamp`
  RFC3339. Cantidad 0 = borrar; tras cada mensaje se trunca a la profundidad suscrita. No hay número de secuencia:
  la integridad la da el checksum (https://docs.kraken.com/api/docs/guides/spot-ws-book-v2).
- Trades: `side` es el lado del taker (buy/sell), `trade_id` secuencial por libro, `timestamp` RFC3339
  (https://docs.kraken.com/api/docs/websocket-v2/trade). Se pide sin snapshot (sin los 50 últimos), para no
  duplicar trades al reconectar.
- Control: `heartbeat`, `status` y las respuestas `subscribe`/`unsubscribe`/`pong` no traen datos; una respuesta con
  `"success": false` es un error.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import partial

import pandas as pd

from radar.mercado.reconstruccion import LibroIncremental, a_decimal, checksum_kraken

from .eventos import ACTUALIZACION, SNAPSHOT, ErrorDelExchange, EventoLibro, Trade
from .parametros import DECIMALES_CANTIDAD_KRAKEN, DECIMALES_PRECIO_KRAKEN, PROFUNDIDAD_KRAKEN, SIMBOLO_KRAKEN

URL = "wss://ws.kraken.com/v2"


def _hora(texto) -> pd.Timestamp | None:
    return None if texto is None else pd.Timestamp(texto).tz_convert("UTC")


class Kraken:
    nombre = "kraken"
    url = URL
    ping = json.dumps({"method": "ping"})
    con_buffer = False

    def __init__(self, simbolo: str = SIMBOLO_KRAKEN, profundidad: int = PROFUNDIDAD_KRAKEN):
        self.simbolo, self.profundidad = simbolo, profundidad

    def _libro(self, metodo: str) -> str:
        return json.dumps({"method": metodo, "params": {"channel": "book", "symbol": [self.simbolo],
                                                         "depth": self.profundidad, "snapshot": True}})

    def suscripcion(self) -> list[str]:
        return [self._libro("subscribe"),
                json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": [self.simbolo],
                                                               "snapshot": False}})]

    def resincronizacion(self) -> list[str]:
        """Darse de baja y de alta del libro: Kraken manda un snapshot nuevo."""
        return [self._libro("unsubscribe"), self._libro("subscribe")]

    def nuevo_libro(self) -> LibroIncremental:
        return LibroIncremental(self.nombre, profundidad=self.profundidad,
                                checksum=partial(checksum_kraken, decimales_precio=DECIMALES_PRECIO_KRAKEN,
                                                 decimales_cantidad=DECIMALES_CANTIDAD_KRAKEN))

    def interpretar(self, texto: str) -> list:
        mensaje = json.loads(texto, parse_float=Decimal)
        if "method" in mensaje:
            if mensaje.get("success") is False:
                raise ErrorDelExchange(f"kraken: {mensaje.get('method')}: {mensaje.get('error')}")
            return []
        canal = mensaje.get("channel")
        if canal == "book":
            tipo = SNAPSHOT if mensaje["type"] == "snapshot" else ACTUALIZACION
            return [EventoLibro(self.nombre, tipo,
                                tuple((a_decimal(n["price"]), a_decimal(n["qty"])) for n in d.get("bids", [])),
                                tuple((a_decimal(n["price"]), a_decimal(n["qty"])) for n in d.get("asks", [])),
                                _hora(d.get("timestamp")), checksum=d.get("checksum"))
                    for d in mensaje["data"]]
        if canal == "trade":
            return [Trade(self.nombre, _hora(d["timestamp"]), a_decimal(d["price"]), a_decimal(d["qty"]), d["side"],
                          str(d["trade_id"])) for d in mensaje["data"]]
        return []  # heartbeat, status
