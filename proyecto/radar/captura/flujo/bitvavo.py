"""Protocolo de Bitvavo v2 (público): canales `book` (cambios con `nonce`), `trades` y la acción `getBook`.

Verificado en la documentación oficial (22-11-2026) y con mensajes reales:
- URL `wss://ws.bitvavo.com/v2/`; suscripción `{"action": "subscribe", "channels": [{"name": "book", "markets":
  ["BTC-EUR"]}, ...]}` (https://docs.bitvavo.com/docs/websocket-api/book-subscription/).
- Libro: eventos `"event": "book"` con `nonce`, `bids`/`asks` como `[precio, cantidad]` en texto (cantidad "0" =
  borrar) y `timestamp` en NANOSEGUNDOS. Los cambios llegan de TODO el libro, no solo de los primeros niveles.
- Snapshot: acción `getBook` (hasta 1000 niveles por lado) con su `nonce`
  (https://docs.bitvavo.com/docs/websocket-api/get-order-book/). Orden oficial
  (https://docs.bitvavo.com/docs/manage-order-book/): suscribirse, guardar los cambios, pedir el snapshot,
  descartar los cambios con `nonce` ≤ el del snapshot y aplicar el resto; cada `nonce` debe ser el anterior + 1.
  El mismo precio puede venir como "55719" (getBook) y "55719.00" (cambios). No hay checksum.
- Trades: `"event": "trade"` con `id`, `price`, `amount`, `side` (lado del taker), `timestamp` (ms) y
  `timestampNs` (ns) (https://docs.bitvavo.com/docs/websocket-api/trades-subscription/).
- Errores: mensajes con `errorCode` y `error`.
"""

from __future__ import annotations

import json

import pandas as pd

from radar.mercado.reconstruccion import LibroIncremental, a_decimal, continua_bitvavo

from .eventos import ACTUALIZACION, SNAPSHOT, ErrorDelExchange, EventoLibro, Trade
from .parametros import MERCADO_BITVAVO, PROFUNDIDAD_BITVAVO

URL = "wss://ws.bitvavo.com/v2/"


def _ns(valor) -> pd.Timestamp | None:
    return None if valor is None else pd.to_datetime(int(valor), unit="ns", utc=True)


def _niveles(lista) -> tuple:
    return tuple((a_decimal(p), a_decimal(c)) for p, c in lista)


class Bitvavo:
    nombre = "bitvavo"
    url = URL
    ping = None  # basta el ping de protocolo websocket que manda la librería
    con_buffer = True

    def __init__(self, mercado: str = MERCADO_BITVAVO, profundidad: int = PROFUNDIDAD_BITVAVO):
        self.mercado, self.profundidad = mercado, profundidad

    def _pedir_libro(self) -> str:
        return json.dumps({"action": "getBook", "market": self.mercado, "depth": self.profundidad, "requestId": 1})

    def suscripcion(self) -> list[str]:
        return [json.dumps({"action": "subscribe", "channels": [{"name": "book", "markets": [self.mercado]},
                                                                  {"name": "trades", "markets": [self.mercado]}]}),
                self._pedir_libro()]

    def resincronizacion(self) -> list[str]:
        """Pedir otro snapshot; la suscripción sigue y sus cambios se guardan mientras llega."""
        return [self._pedir_libro()]

    def nuevo_libro(self) -> LibroIncremental:
        return LibroIncremental(self.nombre, regla_secuencia=continua_bitvavo, solo_rango_snapshot=True)

    def interpretar(self, texto: str) -> list:
        mensaje = json.loads(texto)
        if "errorCode" in mensaje or "error" in mensaje:
            raise ErrorDelExchange(f"bitvavo: {mensaje.get('errorCode')}: {mensaje.get('error')}")
        if mensaje.get("action") == "getBook":
            r = mensaje["response"]
            return [EventoLibro(self.nombre, SNAPSHOT, _niveles(r["bids"]), _niveles(r["asks"]), _ns(r.get("timestamp")),
                                secuencia=int(r["nonce"]))]
        evento = mensaje.get("event")
        if evento == "book":
            return [EventoLibro(self.nombre, ACTUALIZACION, _niveles(mensaje["bids"]), _niveles(mensaje["asks"]),
                                _ns(mensaje.get("timestamp")), secuencia=int(mensaje["nonce"]))]
        if evento == "trade":
            hora = _ns(mensaje["timestampNs"]) if "timestampNs" in mensaje else \
                pd.to_datetime(int(mensaje["timestamp"]), unit="ms", utc=True)
            return [Trade(self.nombre, hora, a_decimal(mensaje["price"]), a_decimal(mensaje["amount"]), mensaje["side"],
                          str(mensaje["id"]))]
        return []  # subscribed
