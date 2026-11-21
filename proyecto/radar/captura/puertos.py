"""Puerto de entrada de la captura: lo que el capturador necesita de un exchange, sin saber cuál es.

- Puerto (port): contrato que el núcleo define y otros implementan. El capturador solo conoce
  `FuenteCotizaciones`; Kraken, OKX y Bitvavo son ADAPTADORES que lo cumplen (`exchanges/`). En los tests se
  usa una fuente falsa, sin red.
- Profundidad pedida (depth): cuántos niveles de cada lado se piden. 1 = solo el mejor nivel (Fase 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class LibroLeido:
    """Niveles tal como los publica el exchange: pares (precio, cantidad) en texto o número, antes de validarlos
    como `Libro`. Bids del mejor (más alto) al peor; asks del mejor (más bajo) al peor."""

    bids: tuple
    asks: tuple
    hora_exchange_utc: pd.Timestamp | None = None


class FuenteCotizaciones(Protocol):
    """Cualquier origen de cotizaciones: tiene un nombre y sabe leer los primeros `niveles` del libro."""

    nombre: str

    def leer(self, niveles: int) -> LibroLeido:
        """Pide el libro; lanza una excepción si falla (el capturador la registra)."""
        ...
