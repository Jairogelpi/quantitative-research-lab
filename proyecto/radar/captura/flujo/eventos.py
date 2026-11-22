"""Eventos normalizados del flujo: lo que cada intérprete de exchange devuelve, igual para los tres.

Conceptos:
- Evento del libro: un snapshot (libro entero) o una actualización (solo los niveles que cambian), con la hora del
  exchange y, si el exchange los da, el número de secuencia, el anterior y el checksum.
- Trade (operación ejecutada): precio, cantidad, lado del agresor (taker: quien cruzó el spread con una orden que
  se ejecutó al momento) y el identificador del exchange.
- Precios y cantidades en `Decimal`: exactos, tal como los publica el exchange.
- Error del exchange: el exchange contestó con un error (suscripción rechazada, petición inválida). Se registra y
  se reconecta; nunca se ignora.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

SNAPSHOT, ACTUALIZACION = "snapshot", "update"
COMPRA, VENTA = "buy", "sell"


class ErrorDelExchange(Exception):
    """Mensaje de error enviado por el exchange por el websocket."""


@dataclass(frozen=True)
class EventoLibro:
    exchange: str
    tipo: str                               # SNAPSHOT o ACTUALIZACION
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    hora_exchange_utc: pd.Timestamp | None
    secuencia: int | None = None
    secuencia_previa: int | None = None
    checksum: int | None = None


@dataclass(frozen=True)
class Trade:
    exchange: str
    hora_exchange_utc: pd.Timestamp
    precio: Decimal
    cantidad: Decimal
    lado_agresor: str                       # COMPRA o VENTA
    trade_id: str
