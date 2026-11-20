# Costes de ejecución: comisión, spread, profundidad, retraso, umbral y rotación

**Familia:** costes de ejecución · **Visto en:** P08 · **Código:** `src/quantlab/p08/costs.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Comisión | `fee` | q · p_exec · bps / 10.000 | Lo que cobra el exchange. 10 bps = 0,1 %. |
| Maker / taker | — | Maker aporta liquidez y se ejecuta; taker la consume | Una límite que cruza el libro es taker. Poner una maker no garantiza que se ejecute. |
| Coste de spread | `spread_cost` | s · q · (best − mid) | Cruzar del mid al mejor precio. |
| Coste de profundidad | `slippage_cost` | s · q · (p_exec − best) | Recorrer niveles peores que el mejor. |
| Coste de ejecución | `execution_cost` | spread + profundidad + comisión | Coste de llegar al libro y ejecutar. |
| Coste de retraso | `delay_cost` | s · q · (mid − mid_decisión) | Lo que se movió el mercado entre decidir y ejecutar. |
| Implementation shortfall | `implementation_shortfall` | ejecución + retraso | Coste total frente al precio de decisión. |
| PnL de ida y vuelta | `net_pnl` | q · [p_s · (1 − f_s) − p_b · (1 + f_b)] | Resultado exacto con precios ejecutados. |
| Umbral de equilibrio | `break_even_exec_price` | p_s* = p_b · (1 + f_b) / (1 − f_s) | Precio de venta ejecutado que deja el PnL en cero. |
| Markout | `markout` | s · q · (mid_{t+h} − p_fill) − comisión | Cómo evolucionó el precio tras el fill. No es un PnL cerrado. |
| Turnover | `turnover_two_sided` | 2 · nominal · operaciones / capital | Cuántas veces se rota el capital. |

## Ideas clave

- **Órdenes pequeñas: domina la comisión.** En Kraken, el 99,7 % del coste hasta 0,1 BTC.
- **Órdenes grandes: domina la profundidad.** En el libro sintético, 122 € de profundidad frente a 120 € de comisión con 2 BTC.
- **No inventar liquidez:** si la orden supera el libro, queda incompleta y una ida y vuelta se rechaza.
- **No duplicar costes:** con precios ejecutados, el PnL ya incluye spread y profundidad; solo se restan las comisiones.
- **Umbral exacto ≥ suma de bps:** la suma ignora los términos cruzados y siempre se queda un poco corta.
- **Maker condicionado al fill está sesgado:** la selección adversa y los casos sin fill no aparecen.
- **La rotación multiplica los costes:** con el mismo beneficio bruto, duplicar el coste por operación reduce a la mitad las operaciones posibles.

## Validación

- `fee_eur` se detiene con cantidad < 0, precio ≤ 0 o valores no finitos.
- `validate_book` se detiene con lados desconocidos, niveles ≤ 0 o no finitos, o un libro incompleto, bloqueado o cruzado.
- `walk_book` se detiene con lados o cantidades inválidos, o un mid de decisión no positivo.
- `round_trip` se detiene si alguna pierna no se ejecuta entera.
- `cost_attribution` comprueba la identidad del shortfall y marca cotizaciones obsoletas, cotizaciones posteriores a la decisión, fills anteriores a la decisión y fills duplicados.

## Ejemplo (libro sintético)

| Cálculo | Datos | Resultado |
|---|---|---|
| Compra de 0,1 BTC | 0,03 a 60.003 + 0,07 a 60.006 | Precio medio **60.005,10 €** |
| Desglose | spread 0,30 · profundidad 0,21 · comisión 6,00 | **6,51 €** (10,85 bps) |
| Ida y vuelta con mid +35 bps | bruto 21,00 − costes 13,01 | **+7,99 €** |
| Umbral con 10 bps por lado | — | mid **+21,67 bps** |

## Código

```python
from quantlab.p08.costs import (synthetic_book, fetch_kraken_book, walk_book, size_table,
                                round_trip, break_even, fee_move_grid, markout, cost_attribution)

book = synthetic_book()                         # o fetch_kraken_book() (reutiliza la descarga de P02)
walk_book(book, "buy", 0.1, fee_bps=10)         # precio medio y desglose del coste
round_trip(book, synthetic_book(60000 * 1.0035), 0.1, 10, 10)
break_even(synthetic_book, 0.1, 10, 10)         # umbral exacto en precio ejecutado y en mid
```

Relacionado: [spread_y_costes.md](spread_y_costes.md) · [libro_de_ordenes.md](libro_de_ordenes.md) · [condiciones_de_ejecucion.md](condiciones_de_ejecucion.md)
