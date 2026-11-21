"""Adaptador de Bitvavo: endpoint /{mercado}/book con `depth` = niveles por lado.

Cada nivel llega como [precio, cantidad] en texto. La hora `timestamp` viene en NANOSEGUNDOS Unix.
"""

import pandas as pd

from radar.captura.puertos import LibroLeido

from .http import pedir_json

URL = "https://api.bitvavo.com/v2/BTC-EUR/book"


class Bitvavo:
    nombre = "bitvavo"

    def leer(self, niveles: int) -> LibroLeido:
        return interpretar(pedir_json(URL, {"depth": niveles}))


def interpretar(datos) -> LibroLeido:
    """Traduce la respuesta JSON de Bitvavo a `LibroLeido`."""
    if datos.get("market") != "BTC-EUR":
        raise ValueError(f"Bitvavo devolvió otro mercado o un error: {datos}")
    return LibroLeido(tuple((p, c) for p, c in datos["bids"]), tuple((p, c) for p, c in datos["asks"]),
                      pd.to_datetime(int(datos["timestamp"]), unit="ns", utc=True))
