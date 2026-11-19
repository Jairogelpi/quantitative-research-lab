# QuantLab · Documentación

Apuntes de conceptos y conclusiones que vamos sacando en las prácticas, con el código que usamos para cada uno.

## Estructura

| Carpeta | Contenido |
|---|---|
| `conceptos/` | Definiciones agrupadas por tema, con fórmulas y código reutilizable. |
| `../src/quantlab/pNN/` | Código de cada práctica (`p01/`, `p02/`…), con sus pruebas en `../tests/`. |
| `conclusiones/` | Lo que aprendimos en cada práctica (una nota por cuaderno). |
| `aprendizajes/` | Resumen didáctico por práctica: variables, cómo se calcula cada métrica, conclusiones deterministas y para qué sirve. |

## Conceptos

| Tema | Archivo | Visto en |
|---|---|---|
| Precios de una cotización (Bid, Ask, Last, Mid) | [conceptos/precios_de_cotizacion.md](conceptos/precios_de_cotizacion.md) | P01 |
| Spread, bps y coste de ejecución | [conceptos/spread_y_costes.md](conceptos/spread_y_costes.md) | P01 |
| Validación de datos de mercado | [conceptos/validacion_de_datos.md](conceptos/validacion_de_datos.md) | P01 |
| Libro de órdenes: profundidad, OBI, microprice y slippage | [conceptos/libro_de_ordenes.md](conceptos/libro_de_ordenes.md) | P02 |
| Operaciones ejecutadas: volumen, VWAP, Trade Imbalance, CVD e intensidad | [conceptos/operaciones_ejecutadas.md](conceptos/operaciones_ejecutadas.md) | P03 |
| Series temporales: velas OHLCV, retornos, volatilidad y objetivo futuro | [conceptos/series_temporales.md](conceptos/series_temporales.md) | P04 |
| Momentum y mean reversion: señales, IC y simulación con costes | [conceptos/momentum_y_reversion.md](conceptos/momentum_y_reversion.md) | P05 |
| Condiciones de ejecución (monitor determinista) | [conceptos/condiciones_de_ejecucion.md](conceptos/condiciones_de_ejecucion.md) | P01 + P02 → `scripts/monitor_ejecucion.py` |

## Conclusiones por práctica

| Práctica | Archivo |
|---|---|
| P01 · Radiografía de un mercado financiero | [conclusiones/P01_market_snapshot.md](conclusiones/P01_market_snapshot.md) |
| P02 · Análisis del libro de órdenes | [conclusiones/P02_order_book.md](conclusiones/P02_order_book.md) |
| P03 · Análisis de operaciones ejecutadas | [conclusiones/P03_trades.md](conclusiones/P03_trades.md) |
| P04 · Motor de series temporales financieras | [conclusiones/P04_time_series.md](conclusiones/P04_time_series.md) |
| P05 · Momentum y Mean Reversion | [conclusiones/P05_momentum_mean_reversion.md](conclusiones/P05_momentum_mean_reversion.md) |

## Resumen de lo aprendido por práctica

| Práctica | Archivo |
|---|---|
| P01 · Radiografía de un mercado financiero | [aprendizajes/P01_market_snapshot.md](aprendizajes/P01_market_snapshot.md) |
| P02 · Análisis del libro de órdenes | [aprendizajes/P02_order_book.md](aprendizajes/P02_order_book.md) |
| P03 · Análisis de operaciones ejecutadas | [aprendizajes/P03_trades.md](aprendizajes/P03_trades.md) |
| P04 · Motor de series temporales financieras | [aprendizajes/P04_time_series.md](aprendizajes/P04_time_series.md) |
| P05 · Momentum y Mean Reversion | [aprendizajes/P05_momentum_mean_reversion.md](aprendizajes/P05_momentum_mean_reversion.md) |

## Convención de colores en los cuadernos

- 🔎 **Naranja:** fase de validación (comprobaciones `assert`).
- ✅ **Verde:** conclusión importante (resumida en esta carpeta).
