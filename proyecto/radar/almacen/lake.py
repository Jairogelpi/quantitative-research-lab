"""Adaptador del almacén: data lake de ficheros Parquet, consultado con DuckDB.

Conceptos:
- Data lake: los datos se guardan como ficheros en carpetas, no dentro de un servidor de base de datos.
- Parquet: formato columnar, comprimido y tipado; estándar de la industria (pandas, DuckDB, Spark, Polars…).
- Particionado por fecha (estilo Hive): `<raíz>/<fuente>/fecha=AAAA-MM-DD/…parquet`; una consulta de un día
  solo abre los ficheros de ese día.
- Append-only: cada lote es un fichero NUEVO que no se modifica; el capturador escribe mientras otros leen.
- DuckDB: motor SQL analítico que consulta los Parquet sin servidor.
- Evolución del esquema: ficheros con columnas distintas se unen por nombre (`union_by_name`).
- Vista (view): consulta guardada con nombre, sin copiar datos; el catálogo `.duckdb` las expone a DBeaver.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from radar.configuracion import CATALOGO, RAIZ_LAKE


class LakeParquet:
    def __init__(self, raiz: Path = RAIZ_LAKE):
        self.raiz = Path(raiz)

    def guardar(self, filas, fuente):
        """Escribe el lote en ficheros Parquet nuevos, uno por día UTC de `recibido_utc`. Devuelve las rutas."""
        df = pd.DataFrame(filas)
        if df.empty:
            return []
        df["recibido_utc"] = pd.to_datetime(df["recibido_utc"], utc=True)
        rutas = []
        for fecha, grupo in df.groupby(df["recibido_utc"].dt.strftime("%Y-%m-%d")):
            carpeta = self.raiz / fuente / f"fecha={fecha}"
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"{grupo['recibido_utc'].min():%H%M%S_%f}_{len(grupo)}.parquet"
            grupo.to_parquet(ruta, index=False)
            rutas.append(ruta)
        return rutas

    def fuentes(self) -> list[str]:
        """Carpetas del lake que tienen al menos un fichero Parquet."""
        if not self.raiz.exists():
            return []
        return [c.name for c in sorted(self.raiz.iterdir()) if c.is_dir() and any(c.rglob("*.parquet"))]

    def _crear_vistas(self, con):
        for fuente in self.fuentes():
            patron = (self.raiz.resolve() / fuente / "**" / "*.parquet").as_posix()
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
