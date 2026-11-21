"""Almacén: puerto `Almacen` y su adaptador, el data lake de Parquet consultado con DuckDB."""

from .lake import LakeParquet

__all__ = ["LakeParquet"]
