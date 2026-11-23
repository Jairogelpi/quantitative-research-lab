"""El escritor de fondo no bloquea por conversión Parquet y comunica errores."""
import time

import pytest

from radar.almacen.cola import ColaEscritura


class Almacen:
    def __init__(self, fallos=0):
        self.fallos, self.intentos, self.lotes = fallos, 0, []

    def guardar(self, filas, fuente):
        self.intentos += 1
        if self.intentos <= self.fallos:
            raise OSError("disco ocupado")
        self.lotes.append((fuente, list(filas)))
        return ["archivo.parquet"]


def test_se_espera_a_todas_las_escrituras_antes_de_salir():
    destino = Almacen()
    with ColaEscritura(destino, max_pendientes=2, pausa_s=0) as cola:
        for i in range(10):
            cola.guardar([{"id": i}], "trades")
    assert len(destino.lotes) == 10
    assert [l[1][0]["id"] for l in destino.lotes] == list(range(10))


def test_reintenta_fallo_transitorio():
    destino = Almacen(fallos=1)
    with ColaEscritura(destino, reintentos=2, pausa_s=0) as cola:
        cola.guardar([{"id": 1}], "eventos_libro")
    assert destino.intentos == 2
    assert len(destino.lotes) == 1


def test_fallo_permanente_se_propaga():
    destino = Almacen(fallos=10)
    cola = ColaEscritura(destino, reintentos=1, pausa_s=0)
    cola.guardar([{"id": 1}], "eventos_libro")
    with pytest.raises(OSError, match="disco ocupado"):
        cola.cerrar()


def test_no_se_pueden_encolar_lotes_tras_cerrar():
    cola = ColaEscritura(Almacen())
    cola.cerrar()
    with pytest.raises(RuntimeError, match="cerrada"):
        cola.guardar([{"id": 1}], "trades")
