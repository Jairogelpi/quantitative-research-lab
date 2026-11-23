"""Comprobaciones de salud de la captura con datos simulados, sin red."""
import pandas as pd

from radar.salud import diagnosticar

AHORA = pd.Timestamp("2026-11-23T10:00:00Z")


class AlmacenSimulado:
    def __init__(self, edad_segundos, fuentes=("cotizaciones", "libros_flujo")):
        self.edad = edad_segundos
        self.fuentes_simuladas = fuentes

    def fuentes(self):
        return list(self.fuentes_simuladas)

    def consultar(self, sql):
        return pd.DataFrame({
            "exchange": ["kraken", "okx", "bitvavo"],
            "ultima_utc": [AHORA - pd.Timedelta(seconds=self.edad)] * 3,
            "filas_10m": [200, 180, 190],
        })


def test_salud_detecta_capturas_recientes():
    d = diagnosticar(AlmacenSimulado(20), AHORA, 180)
    assert d["ok"]
    assert len(d["medidas"]) == 6
    assert all(f["ok"] for f in d["medidas"])


def test_salud_detecta_datos_obsoletos():
    d = diagnosticar(AlmacenSimulado(500), AHORA, 180)
    assert not d["ok"]
    assert len(d["problemas"]) == 6


def test_salud_detecta_fuente_que_falta():
    d = diagnosticar(AlmacenSimulado(1, ("cotizaciones",)), AHORA, 180)
    assert not d["ok"]
    assert sum(not f["ok"] for f in d["medidas"]) == 3
