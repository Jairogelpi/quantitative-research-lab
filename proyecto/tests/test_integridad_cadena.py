"""Integridad del lake y continuidad de captura (datos sintéticos sin red)."""
import pandas as pd

from radar.almacen import LakeParquet
from radar.almacen.auditoria import auditar_lake
from radar.analisis.continuidad import diagnosticar_continuidad

T0 = pd.Timestamp("2026-11-23T10:00:00Z")


def test_auditoria_lake_correcto(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([{"recibido_utc": T0, "exchange": "kraken", "bid": 100}], "cotizaciones")
    r = auditar_lake(tmp_path, profundo=True)
    assert r["ok"] and r["archivos"] == 1 and r["filas"] == 1
    assert r["fuentes"]["cotizaciones"]["archivos"] == 1


def test_auditoria_detecta_temporal_y_parquet_corrupto(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([{"recibido_utc": T0}], "trades")
    raiz = tmp_path / "trades" / "fecha=2026-11-23"
    (raiz / "resto.tmp").write_text("incompleto")
    (raiz / "roto.parquet").write_bytes(b"no es parquet")
    r = auditar_lake(tmp_path)
    assert not r["ok"] and len(r["temporales"]) == 1 and len(r["incidencias"]) == 1


def test_auditoria_profunda_detecta_particion_incorrecta(tmp_path):
    lake = LakeParquet(tmp_path)
    rutas = lake.guardar([{"recibido_utc": T0}], "cotizaciones")
    nuevo = rutas[0].parent.parent / "fecha=2026-11-22" / rutas[0].name
    nuevo.parent.mkdir()
    rutas[0].rename(nuevo)
    r = auditar_lake(tmp_path, profundo=True)
    assert not r["ok"] and "partición" in r["incidencias"][0]


def test_continuidad_informa_corte_largo_y_bordes(tmp_path):
    lake = LakeParquet(tmp_path)
    for fuente in ("cotizaciones", "libros_flujo"):
        filas = [
            {"recibido_utc": T0 + pd.Timedelta(seconds=x), "exchange": ex}
            for ex in ("kraken", "okx", "bitvavo") for x in (10, 11, 120)
        ]
        lake.guardar(filas, fuente)
    r = diagnosticar_continuidad(lake, T0, T0 + pd.Timedelta(seconds=150), 5)
    assert not r["ok"]
    assert len([x for x in r["cortes"] if x["clase"] == "interior"]) == 6
    assert len([x for x in r["cortes"] if x["clase"] == "inicio"]) == 6
    assert len([x for x in r["cortes"] if x["clase"] == "final"]) == 6


def test_continuidad_distingue_fuente_ausente(tmp_path):
    lake = LakeParquet(tmp_path)
    r = diagnosticar_continuidad(lake, T0, T0 + pd.Timedelta(minutes=1))
    assert not r["ok"] and len(r["cortes"]) == 6
    assert {x["clase"] for x in r["cortes"]} == {"sin_fuente"}
