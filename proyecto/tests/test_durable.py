"""Contratos de persistencia: fechas, idempotencia y recuperación WAL sin red."""
from decimal import Decimal

import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.almacen.durable import AlmacenDurable

T0 = pd.Timestamp("2026-11-23T23:59:59Z")


def filas():
    return [
        {"exchange": "okx", "recibido_utc": T0,
         "hora_exchange_utc": T0, "precio": Decimal("49123.00000001"),
         "niveles": [1.25, 0.1]},
        {"exchange": "okx", "recibido_utc": T0 + pd.Timedelta(seconds=2),
         "hora_exchange_utc": T0 + pd.Timedelta(seconds=1), "precio": Decimal("49123.50000001"),
         "niveles": [1.5]},
    ]


def test_lake_rechaza_fechas_ausentes_sin_perder_filas(tmp_path):
    lake = LakeParquet(tmp_path)
    with pytest.raises(ValueError, match="recibido_utc"):
        lake.guardar([{"exchange": "okx"}], "trades")
    with pytest.raises(ValueError, match="NaT"):
        lake.guardar([{"recibido_utc": pd.NaT}], "trades")
    assert not list(tmp_path.rglob("*.parquet"))


def test_lake_rechaza_nombre_de_fuente_peligroso(tmp_path):
    lake = LakeParquet(tmp_path)
    with pytest.raises(ValueError, match="fuente"):
        lake.guardar(filas(), "../otro")
    assert not list(tmp_path.rglob("*.parquet"))


def test_lote_idempotente_en_dos_dias(tmp_path):
    lake = LakeParquet(tmp_path)
    lote_id = "f" * 32
    a = lake.guardar_lote(filas(), "trades", lote_id)
    b = lake.guardar_lote(filas(), "trades", lote_id)
    assert a == b and len(a) == 2
    assert len(list(tmp_path.rglob("*.parquet"))) == 2
    assert len(lake.consultar("SELECT * FROM trades")) == 2


def test_wal_guarda_y_preserva_tipos(tmp_path):
    lake = LakeParquet(tmp_path / "lake")
    ruta = tmp_path / "wal" / "flujo.sqlite"
    with AlmacenDurable(lake, ruta, pausa_s=0) as writer:
        writer.guardar(filas(), "trades")
    with AlmacenDurable(lake, ruta, pausa_s=0) as writer:
        assert writer.contar_pendientes() == 0
    df = lake.consultar("SELECT * FROM trades ORDER BY recibido_utc")
    assert len(df) == 2
    assert df["precio"].notna().all()
    assert pd.to_datetime(df.hora_exchange_utc, utc=True).iloc[0] == T0


def test_wal_recupera_caida_despues_de_publicar_parquet(tmp_path):
    lake = LakeParquet(tmp_path / "lake")
    ruta = tmp_path / "wal" / "flujo.sqlite"

    class FalloAntesDeAck:
        def __init__(self):
            self.primera = True

        def guardar_lote(self, rows, fuente, identificador):
            paths = lake.guardar_lote(rows, fuente, identificador)
            if self.primera:
                self.primera = False
                raise OSError("fallo tras publicar, antes del ACK")
            return paths

    writer = AlmacenDurable(FalloAntesDeAck(), ruta, reintentos=0)
    writer.guardar(filas(), "trades")
    with pytest.raises(OSError, match="ACK"):
        writer.cerrar()
    assert len(list((tmp_path / "lake").rglob("*.parquet"))) == 2
    with AlmacenDurable(lake, ruta) as recuperado:
        pass
    with AlmacenDurable(lake, ruta) as comprobacion:
        assert comprobacion.contar_pendientes() == 0
    assert len(lake.consultar("SELECT * FROM trades")) == 2


def test_wal_reintenta_fallo_de_disco(tmp_path):
    lake = LakeParquet(tmp_path / "lake")
    ruta = tmp_path / "wal" / "flujo.sqlite"

    class FallaSiempre:
        def guardar_lote(self, *a):
            raise OSError("sin espacio")

    escritor = AlmacenDurable(FallaSiempre(), ruta, reintentos=0)
    escritor.guardar(filas()[:1], "trades")
    with pytest.raises(OSError, match="espacio"):
        escritor.cerrar()
    with AlmacenDurable(lake, ruta) as recuperado:
        pass
    assert len(lake.consultar("SELECT * FROM trades")) == 1
