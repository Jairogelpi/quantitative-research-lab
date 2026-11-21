"""Radar · el sistema de QuantLab que observa el mercado (docs/proyecto/QUANTLAB.md).

Arquitectura hexagonal (puertos y adaptadores) con nombres de dominio:
- `mercado/`  DOMINIO puro: cotizaciones y costes. No sabe nada de HTTP ni de disco.
- `captura/`  CASO DE USO: rondas de captura. Habla con los exchanges a través del puerto `FuenteCotizaciones`.
- `almacen/`  Puerto `Almacen` y su adaptador: data lake de Parquet consultado con DuckDB.
- `configuracion.py`  valores del sistema en un único sitio.
- `__main__.py`  línea de comandos: `python -m radar …`.
"""
