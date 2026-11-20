# P01 · Radiografía de un mercado financiero · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P01_market_snapshot.ipynb`
**Datos:** ejemplo ficticio de BTC/EUR (Bid 59.998 € · Ask 60.002 € · Last 59.999 €)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | El entorno funciona: el kernel QuantLab ejecuta el cuaderno de principio a fin. | Celda de versiones (`sys`, `pandas`, `numpy`, `requests`) | — |
| 2 | No existe "un" precio: hay uno para comprar (Ask), otro para vender (Bid) y una referencia (Mid) que **no es ejecutable**. | `quote_metrics()` → `mid_price` | [Precios](../conceptos/precios_de_cotizacion.md) |
| 3 | El Last price es historia, no una oferta actual. Aquí está 1 € por debajo del mid. | `quote_metrics()` → `last_price_deviation` | [Precios](../conceptos/precios_de_cotizacion.md) |
| 4 | Operar cuesta el spread: comprar y vender 0,01 BTC al instante cuesta **0,04 €** (≈ 0,67 bps), aunque el precio no se mueva. | Celda de coste de ida y vuelta | [Spread y costes](../conceptos/spread_y_costes.md) |
| 5 | Los bps permiten comparar: 4 € de spread en BTC son solo 0,67 bps. | `quote_metrics()` → `spread_bps` | [Spread y costes](../conceptos/spread_y_costes.md) |
| 6 | Hay que validar antes de calcular: un libro cruzado (Ask < Bid) o precios ≤ 0 deben detener el análisis. | Celdas `assert` (fase de validación) | [Validación](../conceptos/validacion_de_datos.md) |
| 7 | Con una sola observación no hay señal predictiva. Hacen falta series temporales. | — | — |
| 8 | El ejemplo ficticio es realista: el spread real de BTC/EUR en Kraken tiene el mismo orden de magnitud (< 1 bps). | Celda `COMPARE_LIVE` | [Spread y costes](../conceptos/spread_y_costes.md) |
| 9 | El spread real cambia mucho en minutos: pasó de 3,0 € a 0,9 € entre dos consultas. | Celda `COMPARE_LIVE` | [Spread y costes](../conceptos/spread_y_costes.md) |
| 10 | El last puede quedar por debajo o por encima del mid según la última operación fuera una venta o una compra agresiva. | Celda `COMPARE_LIVE` | [Precios](../conceptos/precios_de_cotizacion.md) |

## Comparación ficticio vs. Kraken en vivo (19-11-2026)

| | Bid | Ask | Last | Spread | Spread bps | Last − Mid | Coste 0,01 BTC |
|---|---|---|---|---|---|---|---|
| Ficticio | 59.998,0 € | 60.002,0 € | 59.999,0 € | 4,0 € | 0,667 | −1,00 € | 0,040 € |
| Kraken (1.ª consulta) | 57.967,8 € | 57.970,8 € | 57.967,1 € | 3,0 € | 0,518 | −2,20 € | 0,030 € |
| Kraken (2.ª, 09:01 UTC) | 57.960,3 € | 57.961,2 € | 57.961,2 € | 0,9 € | 0,155 | +0,45 € | 0,009 € |

En un mercado tan líquido las **comisiones** (no incluidas) pesan mucho más que el spread.

## Código en `src/` y pruebas

- Funciones: `src/quantlab/p01/quotes.py` → `quote_metrics`, `round_trip_cost`, `validate_quote`, `fetch_kraken_ticker`, `SYNTHETIC_QUOTE`.
- Pruebas: `tests/test_quotes.py` (12 sin conexión + 2 en vivo).

```powershell
.\.venv\Scripts\python.exe -m pytest           # pruebas sin conexión
.\.venv\Scripts\python.exe -m pytest -m live   # prueba contra Kraken (Internet)
```

## Pendiente

- Guardar varias consultas en el tiempo (serie de spread) para estudiar cómo varía.
- Añadir comisiones del exchange al coste de ida y vuelta.
