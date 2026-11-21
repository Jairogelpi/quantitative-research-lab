"""Cotización del mejor nivel del libro (Fase 1 · lecciones 1.1 y 1.2).

Conceptos:
- Libro de órdenes (order book): órdenes limitadas que esperan, de compra (bids) y de venta (asks).
- Bid (mejor precio de compra): la orden de compra MÁS ALTA; lo máximo que te pagan si vendes ya.
- Ask (mejor precio de venta, "offer"): la orden de venta MÁS BAJA; lo mínimo que pagas si compras ya.
- Profundidad del mejor nivel: cantidad (BTC) que espera en el bid y en el ask.
- Mid price: (bid + ask) / 2. Spread absoluto: ask − bid (EUR). Spread relativo: spread / mid × 10.000 (bps).
- Tick (tick size): salto mínimo de precio de cada exchange (Kraken 0,1 €; Bitvavo 1 €).
- Validación (quote validation): precios y cantidades finitos y > 0, y ask > bid.
- Libro cruzado (crossed book): ask ≤ bid. Imposible en un mercado real (el motor de emparejamiento lo
  ejecutaría al instante): indica datos erróneos y se rechaza.
- Hora de solicitud, de recepción y del exchange: la de RECEPCIÓN es lo que el sistema sabía; la del exchange
  depende de su reloj. Latencia = recepción − solicitud.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


class CotizacionInvalida(ValueError):
    """La cotización es imposible en un mercado real (no se corrige ni se sustituye)."""


@dataclass(frozen=True)
class Cotizacion:
    """Mejor nivel de un exchange en un instante. Inmutable: una vez creada y validada, no cambia."""

    exchange: str
    par: str
    bid: float
    ask: float
    cantidad_bid: float
    cantidad_ask: float
    solicitado_utc: pd.Timestamp
    recibido_utc: pd.Timestamp
    hora_exchange_utc: pd.Timestamp | None = None

    def __post_init__(self):
        for campo in ("bid", "ask", "cantidad_bid", "cantidad_ask"):
            valor = float(getattr(self, campo))
            if not (math.isfinite(valor) and valor > 0):
                raise CotizacionInvalida(f"{self.exchange}: {campo} no es un número positivo ({getattr(self, campo)!r})")
            object.__setattr__(self, campo, valor)  # guarda el número ya convertido desde texto
        if self.ask <= self.bid:
            raise CotizacionInvalida(f"{self.exchange}: libro cruzado (ask {self.ask} ≤ bid {self.bid})")
        if self.recibido_utc < self.solicitado_utc:
            raise CotizacionInvalida(f"{self.exchange}: recibida antes de solicitarla")

    @property
    def mid(self) -> float:
        """Mid price: punto medio entre bid y ask."""
        return (self.bid + self.ask) / 2

    @property
    def spread_eur(self) -> float:
        """Spread absoluto en EUR, redondeado a céntimos (la resta en coma flotante deja restos minúsculos)."""
        return round(self.ask - self.bid, 2)

    @property
    def spread_bps(self) -> float:
        """Spread relativo en puntos básicos (1 bp = 0,01 %): compara activos de precios muy distintos."""
        return (self.ask - self.bid) / self.mid * 10_000

    @property
    def latencia_s(self) -> float:
        """Latencia: recepción − solicitud, en segundos."""
        return (self.recibido_utc - self.solicitado_utc).total_seconds()

    def a_fila(self) -> dict:
        """Fila para el almacén: los campos y los valores calculados (mismas columnas que el lake)."""
        return {"exchange": self.exchange, "par": self.par, "solicitado_utc": self.solicitado_utc,
                "recibido_utc": self.recibido_utc, "latencia_s": self.latencia_s,
                "hora_exchange_utc": self.hora_exchange_utc, "bid": self.bid, "ask": self.ask,
                "cantidad_bid": self.cantidad_bid, "cantidad_ask": self.cantidad_ask, "mid": self.mid,
                "spread_eur": self.spread_eur, "spread_bps": self.spread_bps}
