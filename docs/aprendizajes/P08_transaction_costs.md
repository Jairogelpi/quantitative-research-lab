# P08 · Motor de costes operativos y ejecución · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P08_transaction_costs.ipynb`
**Datos de ejemplo:** un libro sintético de 6 niveles por lado y un snapshot real del libro de Kraken

P01 medía el spread, P02 el slippage y P05–P07 se encontraban una y otra vez con que los costes se comían el resultado. P08 junta todos los costes en un **motor de ejecución** y responde a una pregunta concreta: ¿cuánto tiene que moverse el precio para que una operación gane dinero?

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `book` | Libro L2 en formato largo: `side` (bid/ask), `price` (EUR/BTC), `quantity` (BTC) | Sintético |
| `side` | `buy` (consume asks) o `sell` (consume bids) | — |
| `quantity` (q) | Cantidad a ejecutar | 0,10 BTC |
| `MAKER_FEE_BPS` | Comisión maker supuesta | 5 bps |
| `TAKER_FEE_BPS` | Comisión taker supuesta | 10 bps |
| `decision_mid` | Mid en el momento de decidir (para el coste de retraso) | El mid actual |
| `capital`, `nominal`, `cost_bps` | Escenario de rotación | 10.000 €, 1.000 €, 25 bps |

Libro sintético: asks a 60.003 (0,03), 60.006 (0,07), 60.012 (0,15), 60.024 (0,25), 60.048 (0,5) y 60.096 (1); bids simétricos a 59.997 (0,04), 59.994 (0,06), 59.988 (0,12), 59.976 (0,28), 59.952 (0,5) y 59.904 (1).

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo (compra de 0,1 BTC, 10 bps) | Qué responde |
|---|---|---|---|
| `execution_price` | Σ (precio × cantidad tomada) / cantidad ejecutada | (0,03 × 60.003 + 0,07 × 60.006) / 0,1 = **60.005,10 €** | ¿A qué precio medio se ejecutó? |
| `fee` | q · p_exec · bps / 10.000 | 6.000,51 × 0,001 = **6,0005 €** | ¿Cuánto cobra el exchange? |
| `spread_cost` | s · q · (best − mid) | 0,1 × (60.003 − 60.000) = **0,30 €** | ¿Cuánto cuesta cruzar al mejor precio? |
| `slippage_cost` | s · q · (p_exec − best) | 0,1 × (60.005,10 − 60.003) = **0,21 €** | ¿Cuánto cuesta recorrer niveles peores? |
| `execution_cost` | spread + profundidad + comisión | **6,51 €** | Coste total de ejecutar |
| `execution_cost_bps` | coste / (q · mid) × 10.000 | 6,51 / 6.000 × 10.000 = **10,85 bps** | El mismo coste en bps |
| `delay_cost` | s · q · (mid − mid_decisión) | Decisión a 59.990: **+1,00 €** | ¿Cuánto se movió el mercado al esperar? |
| `net_pnl` (ida y vuelta) | nominal de venta − nominal de compra − comisiones | Mid +35 bps: **+7,99 €** | ¿Cuánto se gana de verdad? |
| `gross_pnl` | q · (mid_salida − mid_entrada) | **+21,00 €** | ¿Cuánto se movió el precio a favor? |
| `break_even_exec_price` | p_b · (1 + f_b) / (1 − f_s) | 60.005,10 × 1,001 / 0,999 = **60.125,23 €** | ¿A qué precio hay que vender para empatar? |
| `break_even_move_bps` | Umbral en mid frente al mid de entrada | **+21,67 bps** | ¿Cuánto tiene que subir el mid? |
| `markout` | s · q · (mid_{t+h} − p_fill) − comisión | Maker a 59.997, mid futuro 60.030: **+0,30 €** | ¿Qué pasó con el precio después del fill? |
| Operaciones máximas | bruto / (nominal · coste / 10.000) | 100 / 2,50 = **40** | ¿Cuántas operaciones se pueden pagar? |

**Conciliación:** bruto − (spread + profundidad + comisiones) = neto → 21,00 − (0,60 + 0,39 + 12,02) = **7,99 €**.

## 3. Reglas de validación (antes de calcular)

- `fee_eur` se detiene con cantidad < 0, precio ≤ 0 o valores no finitos.
- `validate_book` se detiene con lados distintos de bid/ask, niveles ≤ 0 o no finitos, o un libro incompleto, bloqueado o cruzado. Suma los niveles con el mismo precio.
- `walk_book` nunca inventa liquidez: si la orden supera el libro, ejecuta lo que hay y lo informa en `fill_ratio`.
- `round_trip` **rechaza** una ida y vuelta si alguna pierna no se ejecuta entera: no se presume cerrada una posición que no existe.
- El PnL se calcula con precios **ejecutados**: el spread y la profundidad ya están dentro, no se restan otra vez.
- `cost_attribution` exige que el shortfall cuadre con s · q · (fill − decisión) + comisión, y marca cotizaciones obsoletas o futuras, fills anteriores a la decisión y fills duplicados.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| El libro no supera `validate_book` | El dato no es válido: no se simula nada. |
| q ≤ cantidad del mejor nivel | Se ejecuta al mejor precio, sin coste de profundidad. |
| q > cantidad total del lado | La orden queda incompleta; no hay ida y vuelta válida. |
| Precio de venta ejecutado < p_b · (1 + f_b) / (1 − f_s) | La ida y vuelta pierde dinero. |
| Mayor comisión con los mismos precios | Menor PnL neto. |
| Beneficio bruto / coste por operación | Número máximo de operaciones rentables. |
| Shortfall ≠ s · q · (fill − decisión) + comisión | Algún coste se contó dos veces o falta. |
| Cotización con más de 2 s al decidir | La decisión se basó en un precio obsoleto. |
| Cotización posterior a la decisión | Hay *look-ahead*. |

**Lo que NO puede concluir:**

- El coste real de una orden: el libro cambia mientras viaja la orden, y hay latencia, cola y reposición de liquidez.
- Que una orden maker sea mejor: sin probabilidad de fill y sin los casos no rellenados, la comparación está sesgada.
- El impacto de la propia orden en el precio de salida: la ida y vuelta usa el mismo libro desplazado.
- Que un resultado positivo sea alpha: el movimiento del mid de la simulación está fijado de antemano.
- El coste real de un particular: las comisiones son supuestos (la taker real de Kraken Pro, nivel 1, es del 0,80 %).

## 5. Para qué sirve

- **Saber cuánto tiene que funcionar una estrategia.** El umbral de equilibrio dice el movimiento mínimo que una señal debe anticipar para no perder: con 10 bps por lado, más de 21,7 bps por operación.
- **Elegir el tamaño de las órdenes.** Las pequeñas pagan sobre todo comisión; las grandes, profundidad, y pueden no ejecutarse enteras.
- **Comparar maker y taker con honestidad.** La comisión maker más baja solo compensa si se tiene en cuenta la probabilidad de fill y la selección adversa.
- **Controlar la rotación.** Más operaciones con el mismo beneficio bruto pueden convertir una estrategia rentable en perdedora.
- **Auditar backtests.** Una interfaz que reparte el coste en tramos y comprueba la conciliación detecta costes duplicados y datos con problemas de tiempo.
- **Base para P09.** Con el PnL neto de cada operación se podrán calcular esperanza, Sharpe, drawdown y profit factor.

## Referencias

- Código: [`src/quantlab/p08/costs.py`](../../src/quantlab/p08/costs.py)
- Pruebas: [`tests/test_costs.py`](../../tests/test_costs.py)
- Conclusiones: [conclusiones/P08_transaction_costs.md](../conclusiones/P08_transaction_costs.md)
- Conceptos: [costes de ejecución](../conceptos/costes_de_ejecucion.md) · [spread y costes](../conceptos/spread_y_costes.md) · [libro de órdenes](../conceptos/libro_de_ordenes.md)
- Aprendizaje anterior: [P07 · Análisis de derivados financieros](P07_derivatives.md)
