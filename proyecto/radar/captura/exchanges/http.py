"""Petición HTTP común a todos los adaptadores (API pública: dirección web que devuelve JSON)."""

import requests

from radar.configuracion import TIMEOUT_HTTP_S


def pedir_json(url, params):
    """GET con espera máxima; un error HTTP (por ejemplo 503) lanza excepción en lugar de devolver datos rotos."""
    respuesta = requests.get(url, params=params, timeout=TIMEOUT_HTTP_S)
    respuesta.raise_for_status()
    return respuesta.json()
