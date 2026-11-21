"""Adaptadores de exchanges: cada uno traduce el formato de su API pública a `LibroLeido`.

| Campo | Kraken (Depth) | OKX (market/books) | Bitvavo (BTC-EUR/book) |
|---|---|---|---|
| niveles pedidos | count | sz | depth |
| cada nivel | [precio, cantidad, hora] | [precio, cantidad, "0", nº órdenes] | [precio, cantidad] |
| hora del exchange | por nivel, segundos Unix | ts, milisegundos Unix | timestamp, nanosegundos Unix |
| tick de BTC/EUR | 0,1 € | 0,1 € | 1 € |

Añadir un exchange = escribir un adaptador con `nombre` y `leer(niveles)` y registrarlo aquí; el resto no cambia.
"""

from .bitvavo import Bitvavo
from .kraken import Kraken
from .okx import OKX

FUENTES = {"kraken": Kraken, "okx": OKX, "bitvavo": Bitvavo}


def crear_fuentes(nombres):
    """Instancia los adaptadores pedidos; error claro si el nombre no existe."""
    desconocidos = sorted(set(nombres) - set(FUENTES))
    if desconocidos:
        raise ValueError(f"Exchanges desconocidos: {desconocidos}; disponibles: {sorted(FUENTES)}")
    return [FUENTES[n]() for n in nombres]
