"""Desequilibrio del libro (order book imbalance) en una banda de precios alrededor del mid (Fase 2).

Conceptos:
- Imbalance: (cantidad en bids − cantidad en asks) / (cantidad en bids + cantidad en asks). Va de −1 (solo
  vendedores esperando) a +1 (solo compradores). Hipótesis a comprobar con datos: un imbalance positivo
  anticipa subidas del precio.
- Banda en bps alrededor del mid: se suma la cantidad de los niveles a menos de `banda_bps` del mid. Contar
  niveles no sirve para comparar exchanges: con ticks distintos (Kraken 0,1 €, Bitvavo 1 €), 5 niveles son
  ventanas de precio distintas. Los bps además valen igual a cualquier precio del BTC.
- Banda cubierta: el libro capturado llega MÁS ALLÁ del borde de la banda en los dos lados. Si no, podría haber
  órdenes dentro de la banda que no se leyeron, y el imbalance no se calcula (no se inventa).
"""

from __future__ import annotations

from dataclasses import dataclass

from .libro import Libro


@dataclass(frozen=True)
class Desequilibrio:
    banda_bps: float
    cantidad_bids: float
    cantidad_asks: float
    cubierta: bool

    @property
    def imbalance(self) -> float | None:
        """None si la banda no está cubierta o no tiene cantidad en ningún lado."""
        total = self.cantidad_bids + self.cantidad_asks
        if not self.cubierta or total == 0:
            return None
        return (self.cantidad_bids - self.cantidad_asks) / total

    def a_fila(self) -> dict:
        return {"banda_bps": self.banda_bps, "cantidad_bids": self.cantidad_bids, "cantidad_asks": self.cantidad_asks,
                "cubierta": self.cubierta, "imbalance": self.imbalance}


def desequilibrio(libro: Libro, banda_bps: float) -> Desequilibrio:
    """Suma la cantidad de cada lado a menos de `banda_bps` del mid y calcula el imbalance."""
    if banda_bps <= 0:
        raise ValueError("La banda debe ser positiva")
    mid = libro.mejor_nivel().mid
    desde, hasta = mid * (1 - banda_bps / 10_000), mid * (1 + banda_bps / 10_000)
    cubierta = libro.bids[-1].precio < desde and libro.asks[-1].precio > hasta
    return Desequilibrio(banda_bps, sum(n.cantidad for n in libro.bids if n.precio >= desde),
                         sum(n.cantidad for n in libro.asks if n.precio <= hasta), cubierta)
