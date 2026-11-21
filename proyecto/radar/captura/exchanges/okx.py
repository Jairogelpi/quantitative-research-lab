"""Adaptador de OKX: endpoint market/books del par BTC-EUR con `sz` = niveles por lado (hora `ts` en ms).

Cada nivel llega como [precio, cantidad, "0" (campo obsoleto), número de órdenes en ese nivel].
"""

import pandas as pd

from radar.captura.puertos import LibroLeido

from .http import pedir_json

URL = "https://www.okx.com/api/v5/market/books"


class OKX:
    nombre = "okx"

    def leer(self, niveles: int) -> LibroLeido:
        return interpretar(pedir_json(URL, {"instId": "BTC-EUR", "sz": niveles}))


def interpretar(datos) -> LibroLeido:
    """Traduce la respuesta JSON de OKX a `LibroLeido`. `code` distinto de "0" es un error de la API."""
    if datos["code"] != "0":
        raise ValueError(f"OKX devolvió un error: {datos.get('msg')}")
    d = datos["data"][0]
    return LibroLeido(tuple((n[0], n[1]) for n in d["bids"]), tuple((n[0], n[1]) for n in d["asks"]),
                      pd.to_datetime(int(d["ts"]), unit="ms", utc=True))
