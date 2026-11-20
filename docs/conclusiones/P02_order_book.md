# P02 · Análisis del libro de órdenes · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P02_order_book.ipynb`
**Datos:** libro de referencia (5 niveles) y snapshots públicos de Kraken BTC/EUR (19-11-2026, de 09:28 a 09:32 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | El mejor precio solo vale para el volumen del mejor nivel: comprar 0,5 BTC en la referencia cuesta de media 60.005,40 €, no 60.002 €. | `simulate_market_order` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 2 | El slippage crece con el tamaño: en Kraken, comprar 0,05, 0,5 y 2 BTC costó 0,24, 0,48 y 0,73 bps. | E2 · `slippage_table` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 3 | Los costes no son simétricos: comprar 2 BTC costó 0,73 bps y venderlos, 0,08 bps (7 frente a 3 niveles). | E3 · `slippage_table` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 4 | El OBI cambia de signo según N: +0,98 en 1 nivel y −0,06 en 10. Cuatro minutos después, −0,75 y +0,08. | E1 · `obi_table` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 5 | El OBI(1) es muy inestable: pasó de −0,75 a +0,32 en 2 segundos. | E1 y E5 | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 6 | Ampliar la banda nunca reduce la profundidad. Si la banda llega al borde del snapshot, la cifra es solo un mínimo. | E4 · `depth_within_bps` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 7 | Un spread mínimo (0,1 €) no garantiza una ejecución barata: el mejor nivel podía tener tan poco volumen que 0,05 BTC ya recorría 2 niveles. | E2 y E5 | [Spread y costes](../conceptos/spread_y_costes.md) |
| 8 | El microprice casi coincide con el mid cuando el spread es de 1 tick (+0,05 € en Kraken). | `book_features` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 9 | Aun con slippage, la comisión (0,80 % por pata) sigue dominando: comprar 0,5 BTC tuvo 1,40 € de slippage (0,48 bps) frente a 231,52 € de comisión (snapshot de las 09:28 UTC). | E5 | [Condiciones de ejecución](../conceptos/condiciones_de_ejecucion.md) |

## E5 · Kraken frente a la referencia (09:28 UTC, 50 niveles por lado)

| Métrica | Referencia | Kraken |
|---|---|---|
| Spread | 4,0 € (0,667 bps) | 0,1 € (0,017 bps) |
| OBI(1) / OBI(5) | +0,333 / +0,146 | +0,977 / +0,496 |
| Profundidad ±5 bps (bid / ask) | 2,7 / 2,0 BTC | 6,67 / 6,63 BTC |
| Slippage compra / venta de 0,5 BTC | 0,57 / 0,30 bps | 0,48 / 0,03 bps |

## Limitaciones para un backtest

- Un snapshot no modela latencia, cancelaciones, reposición de liquidez ni el impacto de nuestra propia orden.
- El libro visible no incluye órdenes ocultas ni icebergs, ni la prioridad dentro de cada nivel.
- La hora de recepción no es la hora del evento. Hay riesgo de *look-ahead* si se alinean mal los datos.

## Para evaluar si el OBI anticipa retornos haría falta

- Una serie de snapshots o eventos del libro, guardados con la misma N o banda (`data/raw/p02_snapshots.csv` es el comienzo).
- Los trades ejecutados (P03) y los retornos futuros en horizontes fijos.
- Validar fuera de muestra en orden temporal, compararlo con un modelo de referencia y descontar los costes: spread, slippage y comisiones.

## Código y pruebas

- Funciones: `src/quantlab/p02/orderbook.py` → `fetch_kraken_book`, `normalize_book`, `book_features`, `depth_within_bps`, `simulate_market_order`, `EXAMPLE_BOOK`.
- Pruebas: `tests/test_orderbook.py` (incluye las 9 comprobaciones del cuaderno y los ejercicios E1–E4).
