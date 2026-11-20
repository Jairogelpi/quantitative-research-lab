# P08 · Motor de costes operativos y ejecución · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P08_transaction_costs.ipynb`
**Datos:** libro sintético de 6 niveles por lado (2 BTC por lado) y un snapshot público del libro de Kraken BTC/EUR (19-11-2026, 20:41 UTC, 50 niveles)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | En órdenes pequeñas domina la comisión: el 95 % del coste de 0,01 BTC en el libro sintético y el 99,7 % hasta 0,1 BTC en Kraken. | `walk_book` · E7 | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 2 | En órdenes grandes domina la profundidad: de 0,21 € con 0,1 BTC a 122 € con 2 BTC, más que la comisión (120 €). | `size_table` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 3 | El mejor nivel se agota con 0,03 BTC (ask) y 0,04 BTC (bid); una orden de 3 BTC queda incompleta (67 %). | E3 | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 4 | Con un movimiento del mid de 35 bps, la ida y vuelta de 0,1 BTC gana 7,99 €: 21,00 de bruto menos 13,01 de costes, de los que 12,02 son comisiones. | `round_trip` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 5 | Con 10 bps por lado, el mid tiene que subir 21,67 bps solo para empatar; con 25 bps, 51,78 bps. | `break_even` · E4 | [Spread y costes](../conceptos/spread_y_costes.md) |
| 6 | Sumar bps subestima siempre el umbral exacto, y más cuanto mayor es la comisión (de 0,006 a 0,13 bps). | E4 · `break_even_comparison` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 7 | Condicionada al fill, la compra maker gana siempre 3,81 € a la taker; la comparación ignora la selección adversa y los casos sin fill. | E5 · `maker_vs_taker` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 8 | Un beneficio bruto de 100 € soporta 99, 39 o 19 operaciones con 10, 25 o 50 bps de coste. | E6 · `max_round_trips` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 9 | En Kraken, una ida y vuelta de 0,01 BTC sobre un mismo snapshot costaría 20,05 bps: casi exactamente dos comisiones. | E7 | [Spread y costes](../conceptos/spread_y_costes.md) |
| 10 | Una interfaz de costes por tramos (retraso, spread, profundidad, comisión) permite comprobar que no se duplica ningún coste y detectar cotizaciones obsoletas o posteriores a la decisión. | E8 · `cost_attribution` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |

## Libro sintético · compras con 10 bps

| Tamaño | Ejecutado | Comisión | Spread | Profundidad | Coste |
|---|---|---|---|---|---|
| 0,01 BTC | 100 % | 0,60 € | 0,03 € | 0,00 € | 10,50 bps |
| 0,10 BTC | 100 % | 6,00 € | 0,30 € | 0,21 € | 10,85 bps |
| 0,50 BTC | 100 % | 30,01 € | 1,50 € | 6,81 € | 12,77 bps |
| 1,00 BTC | 100 % | 60,03 € | 3,00 € | 29,31 € | 15,39 bps |
| 3,00 BTC | 67 % | 120,13 € | 6,00 € | 122,31 € | 20,70 bps |

## E7 · Kraken BTC/EUR (20:41:18 UTC)

Mejor bid 56.566,0 € · mejor ask 56.566,3 € · spread 0,30 € (0,053 bps) · 0,242 BTC en cada mejor nivel.

| Tamaño | Coste de compra | Coste de venta |
|---|---|---|
| 0,001–0,1 BTC | 10,03 bps | 10,03 bps |
| 0,5 BTC | 10,24 bps | 10,23 bps |
| 1 BTC | 10,36 bps | 10,62 bps |

## Limitaciones

- El libro es una foto congelada: sin latencia, sin cola, sin reposición de liquidez ni reacción de otros participantes.
- La orden maker se supone rellenada: no se modela la probabilidad de fill.
- La ida y vuelta usa el mismo libro desplazado, no un mercado real ni el impacto de la propia compra.
- Las comisiones son supuestos fijos (la taker real de Kraken Pro para un particular es del 0,80 %).
- La rotación usa un coste aproximado sobre el nominal, no fills reales.

## Código y pruebas

- Funciones: `src/quantlab/p08/costs.py` → `fee_eur`, `validate_book`, `synthetic_book`, `fetch_kraken_book` (reutiliza la descarga de P02), `walk_book`, `size_table`, `round_trip`, `break_even`, `fee_move_grid`, `markout`, `turnover_table`, `manual_fee`, `break_even_comparison`, `maker_vs_taker`, `max_round_trips`, `cost_attribution`.
- Pruebas: `tests/test_costs.py` (comisión, validación del libro, motor de ejecución, coherencia con el motor de P02, ida y vuelta, umbral, markout, rotación, E1–E8 y 1 prueba en vivo).
