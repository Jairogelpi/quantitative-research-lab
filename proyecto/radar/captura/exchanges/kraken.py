"""Adaptador de Kraken: endpoint Depth con `count` = niveles pedidos por lado.

Cada nivel llega como [precio, cantidad, hora Unix]: precio y cantidad en texto, con punto decimal; la hora en
segundos desde 1970. Kraken llama XBT al bitcoin y el par interno es 'XXBTZEUR'.
"""

import pandas as pd

from radar.captura.puertos import LibroLeido

from .http import pedir_json

URL = "https://api.kraken.com/0/public/Depth"


class Kraken:
    nombre = "kraken"

    def leer(self, niveles: int) -> LibroLeido:
        return interpretar(pedir_json(URL, {"pair": "XBTEUR", "count": niveles}))


def interpretar(datos) -> LibroLeido:
    """Traduce la respuesta JSON de Kraken a `LibroLeido`."""
    if datos["error"]:
        raise ValueError(f"Kraken devolvió un error: {datos['error']}")
    libro = next(iter(datos["result"].values()))
    hora = max(libro["bids"][0][2], libro["asks"][0][2])  # última actualización del mejor nivel
    return LibroLeido(tuple((p, c) for p, c, _ in libro["bids"]), tuple((p, c) for p, c, _ in libro["asks"]),
                      pd.to_datetime(hora, unit="s", utc=True))
