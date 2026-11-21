"""Libro de órdenes con varios niveles y barrido de una orden de mercado (Fase 2 · lecciones 2.x).

Conceptos:
- Nivel (price level): un precio y la cantidad total que espera a ese precio.
- Libro de órdenes (order book): los bids ordenados de MAYOR a menor precio y los asks de MENOR a mayor.
  El primero de cada lado es el mejor nivel (la `Cotizacion` de la Fase 1).
- Orden de mercado (market order): "ejecútame ya, al precio que haya". Nunca espera en el libro.
- Barrido del libro (walking the book): si el mejor nivel no alcanza, la orden se come el siguiente, y el
  siguiente, cada uno peor que el anterior.
- Precio medio de ejecución (average fill price): importe total / cantidad total.
- Slippage (deslizamiento): lo pagado de más (compra) o cobrado de menos (venta) frente al mejor nivel.
  En EUR y en bps (sobre el importe que habría costado todo al mejor precio).
- Ejecución incompleta: si el libro capturado se acaba, se ejecuta solo lo que había. No se inventa liquidez:
  el libro real puede tener más niveles, pero el sistema solo sabe lo que leyó.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .cotizacion import Cotizacion, CotizacionInvalida

COMPRA, VENTA = "compra", "venta"


@dataclass(frozen=True)
class Nivel:
    precio: float
    cantidad: float

    def __post_init__(self):
        for campo in ("precio", "cantidad"):
            valor = float(getattr(self, campo))
            if not (math.isfinite(valor) and valor > 0):
                raise CotizacionInvalida(f"{campo} del nivel no es un número positivo ({getattr(self, campo)!r})")
            object.__setattr__(self, campo, valor)


@dataclass(frozen=True)
class Libro:
    """Foto de varios niveles del libro de un exchange. Inmutable y validada al crearse."""

    exchange: str
    par: str
    bids: tuple[Nivel, ...]
    asks: tuple[Nivel, ...]
    solicitado_utc: pd.Timestamp
    recibido_utc: pd.Timestamp
    hora_exchange_utc: pd.Timestamp | None = None

    def __post_init__(self):
        if not self.bids or not self.asks:
            raise CotizacionInvalida(f"{self.exchange}: lado vacío en el libro")
        if any(a.precio <= b.precio for a, b in zip(self.bids, self.bids[1:])):
            raise CotizacionInvalida(f"{self.exchange}: los bids deben bajar de precio nivel a nivel")
        if any(b.precio <= a.precio for a, b in zip(self.asks, self.asks[1:])):
            raise CotizacionInvalida(f"{self.exchange}: los asks deben subir de precio nivel a nivel")
        self.mejor_nivel()  # valida libro cruzado y horas con las reglas de la Fase 1

    def mejor_nivel(self) -> Cotizacion:
        """El primer nivel de cada lado: la cotización de la Fase 1."""
        bid, ask = self.bids[0], self.asks[0]
        return Cotizacion(self.exchange, self.par, bid.precio, ask.precio, bid.cantidad, ask.cantidad,
                          self.solicitado_utc, self.recibido_utc, self.hora_exchange_utc)


@dataclass(frozen=True)
class Ejecucion:
    """Resultado de barrer el libro con una orden de mercado."""

    lado: str
    cantidad_btc: float
    importe_eur: float
    mejor_precio: float
    niveles_usados: int
    completa: bool

    @property
    def precio_medio(self) -> float:
        return self.importe_eur / self.cantidad_btc

    @property
    def slippage_eur(self) -> float:
        """Diferencia frente a haber ejecutado TODA la cantidad al mejor precio (siempre ≥ 0)."""
        al_mejor_precio = self.cantidad_btc * self.mejor_precio
        return self.importe_eur - al_mejor_precio if self.lado == COMPRA else al_mejor_precio - self.importe_eur

    @property
    def slippage_bps(self) -> float:
        return self.slippage_eur / (self.cantidad_btc * self.mejor_precio) * 10_000


def _barrer(lado: str, niveles: tuple[Nivel, ...], presupuesto: float, en_eur: bool) -> Ejecucion:
    """Recorre los niveles hasta gastar `presupuesto` (EUR si `en_eur`, si no BTC)."""
    if not (math.isfinite(presupuesto) and presupuesto > 0):
        raise ValueError("La cantidad de la orden debe ser positiva")
    restante, cantidad_btc, importe_eur, usados = presupuesto, 0.0, 0.0, 0
    for nivel in niveles:
        if restante <= presupuesto * 1e-12:  # tolerancia de coma flotante: ya se completó
            break
        disponible = nivel.cantidad * nivel.precio if en_eur else nivel.cantidad
        tomado = min(restante, disponible)
        btc = tomado / nivel.precio if en_eur else tomado
        cantidad_btc += btc
        importe_eur += btc * nivel.precio
        restante -= tomado
        usados += 1
    return Ejecucion(lado, cantidad_btc, importe_eur, niveles[0].precio, usados,
                     completa=restante <= presupuesto * 1e-12)


def barrer_compra(libro: Libro, importe_eur: float) -> Ejecucion:
    """Orden de mercado de compra por `importe_eur`: se come los asks de menor a mayor precio."""
    return _barrer(COMPRA, libro.asks, importe_eur, en_eur=True)


def barrer_venta(libro: Libro, cantidad_btc: float) -> Ejecucion:
    """Orden de mercado de venta de `cantidad_btc`: se come los bids de mayor a menor precio."""
    return _barrer(VENTA, libro.bids, cantidad_btc, en_eur=False)
