"""Adaptador del almacén: data lake de ficheros Parquet, consultado con DuckDB.

Conceptos:
- Data lake: los datos se guardan como ficheros en carpetas, no dentro de un servidor de base de datos.
- Parquet: formato columnar, comprimido y tipado; estándar de la industria (pandas, DuckDB, Spark, Polars…).
- Particionado por fecha (estilo Hive): `<raíz>/<fuente>/fecha=AAAA-MM-DD/…parquet`; una consulta de un día
  solo abre los ficheros de ese día.
- Append-only: cada lote es un fichero NUEVO que no se modifica; el capturador escribe mientras otros leen.
- Nombre único: hora del primer dato + número de filas + un sufijo aleatorio. Sin el sufijo, dos lotes igual de
  largos que empiezan en el mismo instante (dos capturas a la vez) tendrían el mismo nombre y uno pisaría al otro.
- Escritura atómica: se escribe en un `.tmp` y se renombra al terminar. Las consultas solo leen `*.parquet`, así
  que nunca ven un fichero a medio escribir.
- DuckDB: motor SQL analítico que consulta los Parquet sin servidor.
- Evolución del esquema: ficheros con columnas distintas se unen por nombre (`union_by_name`).
- Vista (view): consulta guardada con nombre, sin copiar datos; el catálogo `.duckdb` las expone a DBeaver.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import duckdb
import pandas as pd

from radar.configuracion import CATALOGO, RAIZ_LAKE


class LakeParquet:
    def __init__(self, raiz: Path = RAIZ_LAKE):
        self.raiz = Path(raiz)

    def guardar(self, filas, fuente):
        """Escritura tradicional append-only; un archivo nuevo por partición y lote."""
        return self._guardar(filas, fuente)

    def guardar_lote(self, filas, fuente, lote_id: str):
        """Publica un lote con nombre estable; reintentarlo no duplica el Parquet.

        El ID debe permanecer asociado al mismo contenido. Lo utiliza el WAL
        para reintentar tras una caída entre la publicación y el ACK.
        """
        if not isinstance(lote_id, str) or not re.fullmatch(r"[0-9a-f]{32}", lote_id):
            raise ValueError("lote_id debe ser UUID hexadecimal de 32 caracteres")
        return self._guardar(filas, fuente, lote_id)

    def _guardar(self, filas, fuente, lote_id=None):
        if not isinstance(fuente, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", fuente):
            raise ValueError("nombre de fuente inválido para directorio y vista SQL")
        df = pd.DataFrame(filas)
        if df.empty:
            return []
        if "recibido_utc" not in df.columns:
            raise ValueError("falta recibido_utc")
        try:
            df["recibido_utc"] = pd.to_datetime(df["recibido_utc"], utc=True, errors="raise")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("recibido_utc inválido") from exc
        if df["recibido_utc"].isna().any():
            raise ValueError("recibido_utc no puede ser NaT ni nulo")
        rutas = []
        for fecha, grupo in df.groupby(df["recibido_utc"].dt.strftime("%Y-%m-%d")):
            carpeta = self.raiz / fuente / f"fecha={fecha}"
            carpeta.mkdir(parents=True, exist_ok=True)
            nombre = (f"lote_{lote_id}" if lote_id else
                      f"{grupo['recibido_utc'].min():%H%M%S_%f}_{len(grupo)}_{uuid.uuid4().hex[:8]}")
            ruta = carpeta / f"{nombre}.parquet"
            if lote_id and ruta.exists():
                import pyarrow.parquet as pq
                if pq.read_metadata(ruta).num_rows != len(grupo):
                    raise IOError(f"lote publicado con distinto número de filas: {ruta}")
                rutas.append(ruta)
                continue
            temporal = carpeta / f"{nombre}_{uuid.uuid4().hex[:8]}.tmp"
            try:
                grupo.to_parquet(temporal, index=False)
                os.replace(temporal, ruta)
            finally:
                temporal.unlink(missing_ok=True)
            rutas.append(ruta)
        return rutas

    def fuentes(self) -> list[str]:
        """Carpetas del lake que tienen al menos un fichero Parquet."""
        if not self.raiz.exists():
            return []
        return [c.name for c in sorted(self.raiz.iterdir()) if c.is_dir() and re.fullmatch(r"[a-z][a-z0-9_]*", c.name) and any(c.rglob("*.parquet"))]

    def _crear_vistas(self, con):
        for fuente in self.fuentes():
            patron = (self.raiz.resolve() / fuente / "**" / "*.parquet").as_posix().replace("'", "''")
            con.execute(f"CREATE OR REPLACE VIEW {fuente} AS SELECT * FROM "
                        f"read_parquet('{patron}', hive_partitioning = true, union_by_name = true)")

    def consultar(self, sql: str) -> pd.DataFrame:
        """SQL con DuckDB; cada fuente es una vista con su nombre (p. ej. `cotizaciones`). Horas en UTC."""
        with duckdb.connect() as con:
            con.execute("SET TimeZone = 'UTC'")
            self._crear_vistas(con)
            return con.execute(sql).df()

    def crear_catalogo(self, ruta: Path = CATALOGO) -> list[str]:
        """Fichero DuckDB con una vista por fuente, para abrirlo en un cliente SQL (DBeaver)."""
        with duckdb.connect(str(ruta)) as con:
            self._crear_vistas(con)
        return self.fuentes()
