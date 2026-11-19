# QuantLab · Documentación

Apuntes de conceptos y conclusiones que vamos sacando en las prácticas, con el código que usamos para cada uno.

## Estructura

| Carpeta | Contenido |
|---|---|
| `conceptos/` | Definiciones agrupadas por tema, con fórmulas y código reutilizable. |
| `../src/quantlab/pNN/` | Código de cada práctica (`p01/`, `p02/`…), con sus pruebas en `../tests/`. |
| `conclusiones/` | Lo que aprendimos en cada práctica (una nota por cuaderno). |

## Conceptos

| Tema | Archivo | Visto en |
|---|---|---|
| Precios de una cotización (Bid, Ask, Last, Mid) | [conceptos/precios_de_cotizacion.md](conceptos/precios_de_cotizacion.md) | P01 |
| Spread, bps y coste de ejecución | [conceptos/spread_y_costes.md](conceptos/spread_y_costes.md) | P01 |
| Validación de datos de mercado | [conceptos/validacion_de_datos.md](conceptos/validacion_de_datos.md) | P01 |
| Libro de órdenes: profundidad, OBI, microprice y slippage | [conceptos/libro_de_ordenes.md](conceptos/libro_de_ordenes.md) | P02 |
| Condiciones de ejecución (monitor determinista) | [conceptos/condiciones_de_ejecucion.md](conceptos/condiciones_de_ejecucion.md) | P01 + P02 → `scripts/monitor_ejecucion.py` |

## Conclusiones por práctica

| Práctica | Archivo |
|---|---|
| P01 · Radiografía de un mercado financiero | [conclusiones/P01_market_snapshot.md](conclusiones/P01_market_snapshot.md) |
| P02 · Análisis del libro de órdenes | [conclusiones/P02_order_book.md](conclusiones/P02_order_book.md) |

## Convención de colores en los cuadernos

- 🔎 **Naranja:** fase de validación (comprobaciones `assert`).
- ✅ **Verde:** conclusión importante (resumida en esta carpeta).
