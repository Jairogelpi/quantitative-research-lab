"""Puerto de salida: lo que el núcleo necesita para guardar datos, sin saber dónde ni cómo.

El adaptador real es `LakeParquet`; en los tests se usa un almacén en memoria.
"""

from typing import Protocol


class Almacen(Protocol):
    def guardar(self, filas: list[dict], fuente: str) -> list:
        """Guarda un lote de filas de una fuente (por ejemplo 'cotizaciones'); devuelve dónde quedó."""
        ...
