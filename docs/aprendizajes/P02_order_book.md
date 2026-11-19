# P02 · Análisis del libro de órdenes · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P02_order_book.ipynb`
**Datos de ejemplo:** libro de referencia BTC/EUR de 5 niveles (`EXAMPLE_BOOK`) y snapshots públicos de Kraken

P01 trabajaba solo con el mejor Bid y el mejor Ask. P02 mira **todo el libro**: cuánta cantidad hay en cada precio y qué pasa cuando una orden es más grande que el primer nivel.

## 1. Variables de entrada

Un snapshot de nivel 2 es una lista de niveles por lado. Cada nivel tiene un precio y la cantidad agregada a ese precio.

| Variable | Qué es | Libro de referencia |
|---|---|---|
| `bids` | Niveles compradores, del mejor (más caro) al peor | 59.998 (0,2) · 59.995 (0,5) · 59.990 (0,8) · 59.980 (1,2) · 59.960 (2,0) |
| `asks` | Niveles vendedores, del mejor (más barato) al peor | 60.002 (0,1) · 60.005 (0,3) · 60.010 (0,6) · 60.020 (1,0) · 60.040 (1,5) |
| `n_levels` (N) | Cuántos niveles se tienen en cuenta para profundidad y OBI | 1 o 5 |
| `band_bps` (b) | Ancho de la banda alrededor del mid, en bps | 5 bps |
| `side` | Lado de la orden: `buy` o `sell` | `buy` |
| `quantity_btc` | Tamaño de la orden a simular | 0,5 BTC |
| `f` | Comisión por pata (por operación) | 0,80 % (taker, nivel 1 de Kraken Pro) |

Las cantidades se expresan en BTC (entre paréntesis en la tabla).

## 2. Cómo se calcula cada métrica

Los valores son los del libro de referencia.

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `bid_depth_btc` / `ask_depth_btc` | Σ cantidad de los N primeros niveles | N = 5: **4,7 BTC** bid / **3,5 BTC** ask | ¿Cuánto se puede ejecutar cerca del mejor precio? |
| `bid_notional_eur` / `ask_notional_eur` | Σ precio × cantidad de los N primeros niveles | N = 5: **281.885 €** bid / **210.088 €** ask | Lo mismo, en euros |
| `depth_within_bps` | Σ cantidad con precio dentro de mid × (1 ± b / 10.000) | ±5 bps (59.970 a 60.030 €): **2,7 BTC** bid / **2,0 BTC** ask | Profundidad comparable entre activos y momentos |
| `order_book_imbalance` (OBI) | (D_bid − D_ask) / (D_bid + D_ask) | N = 1: (0,2 − 0,1) / 0,3 = **+0,333** · N = 5: (4,7 − 3,5) / 8,2 = **+0,146** | ¿Qué lado tiene más cantidad en la ventana? (entre −1 y +1) |
| `microprice` | (Ask × Q_bid + Bid × Q_ask) / (Q_bid + Q_ask), con el primer nivel | (60.002 × 0,2 + 59.998 × 0,1) / 0,3 = **60.000,67 €** | Mid ponderado por las cantidades del primer nivel |
| `execution_price` (VWAP) | Σ (precio × cantidad tomada) / cantidad total | Compra 0,5 BTC: (0,1 × 60.002 + 0,3 × 60.005 + 0,1 × 60.010) / 0,5 = **60.005,40 €** | Precio medio real de una orden a mercado |
| `slippage_bps` (compra) | (VWAP / Ask − 1) × 10.000 | (60.005,40 / 60.002 − 1) × 10.000 = **0,57 bps** | Coste extra por recorrer niveles peores que el Ask |
| `slippage_bps` (venta) | (1 − VWAP / Bid) × 10.000 | Venta 0,5 BTC: VWAP 59.996,20 € → **0,30 bps** | Coste extra por recorrer niveles peores que el Bid |
| `levels_used` | Niveles que la orden necesita recorrer | Compra 0,5 BTC: **3** · venta 0,5 BTC: **2** | ¿Cuánto libro consume la orden? |
| `complete` | ¿El snapshot tiene cantidad suficiente para toda la orden? | Compra 4 BTC: solo hay 3,5 → **`False`** (faltan 0,5) | ¿Se puede confiar en el VWAP calculado? |

### Cómo recorre el libro una orden a mercado

Una compra de 0,5 BTC toma la cantidad de cada nivel de ask, del mejor al peor, hasta completar la orden:

| Nivel | Precio | Cantidad disponible | Cantidad tomada | Acumulado |
|---|---|---|---|---|
| 1 | 60.002 € | 0,1 | 0,1 | 0,1 |
| 2 | 60.005 € | 0,3 | 0,3 | 0,4 |
| 3 | 60.010 € | 0,6 | 0,1 | 0,5 ✔ |

El mejor precio (60.002 €) solo vale para los primeros 0,1 BTC. El resto se paga más caro, y por eso el precio medio sube a 60.005,40 €.

### Coste total de una ida y vuelta (P01 + P02 + comisiones)

| Componente | Fórmula | De dónde sale |
|---|---|---|
| Spread | qty × spread / 2 por pata | P01 |
| Slippage | Compra: qty × (VWAP − Ask) · Venta: qty × (Bid − VWAP) | P02 |
| Comisión | importe × f por pata | Exchange |
| **Ida y vuelta** | qty × (VWAP_compra − VWAP_venta) + qty × (VWAP_compra + VWAP_venta) × f | Todo junto |
| **Punto de equilibrio** (compra) | P_salida = P_entrada × (1 + f) / (1 − f) | Con f = 0,80 %: el precio tiene que subir **+1,61 %** solo para no perder |

> El slippage se mide frente al Ask (o el Bid), no frente al mid. Así no se cuenta el spread dos veces.

## 3. Reglas de validación (antes de calcular)

`normalize_book` detiene el análisis con `ValueError` si:

- Algún lado del libro está vacío.
- Hay un precio o una cantidad ≤ 0, o no finitos (`NaN`, infinito).
- Hay niveles de precio duplicados.
- El libro está cruzado o bloqueado: mejor Bid ≥ mejor Ask.

Además:

- Si la API de Kraken falla, se lanza el error. **Nunca** se sustituye por datos ficticios etiquetados como reales.
- Si la orden no cabe en el snapshot, `complete=False`. No se inventan precios para la parte que falta.
- Si la banda de `depth_within_bps` llega al último nivel recibido, la profundidad es solo un **mínimo** (`complete_bid` / `complete_ask` = `False`).

## 4. Conclusiones que un programa puede sacar de forma determinista

Con el mismo snapshot y los mismos parámetros, el programa siempre llega a la misma conclusión.

| Si el programa observa... | Concluye siempre... |
|---|---|
| El libro no supera `normalize_book` | El dato no es válido: no se calcula nada. |
| `quantity_btc` ≤ cantidad del mejor nivel | La orden se ejecuta entera al mejor precio, con slippage 0. |
| `quantity_btc` > cantidad del mejor nivel | La orden recorre varios niveles y su VWAP es peor que el mejor precio. |
| `complete=False` | El snapshot no cubre la orden: el coste real es **desconocido**; el calculado solo cubre la parte que cabe. |
| Dos tamaños de orden en el mismo snapshot | El mayor tiene un slippage igual o mayor, nunca menor. |
| Slippage de compra ≠ slippage de venta | La profundidad de los dos lados es distinta: los costes no son simétricos. |
| Se amplía la banda de `depth_within_bps` | La profundidad crece o se mantiene, nunca baja. |
| `OBI > 0` | En esa ventana hay más cantidad compradora que vendedora. |
| `OBI < 0` | En esa ventana hay más cantidad vendedora que compradora. |
| Spread de 1 tick | El microprice queda prácticamente en el mid. |
| Slippage + spread frente a la comisión | Para un particular, la comisión (0,80 % por pata) suele ser el coste dominante. |

El monitor de `scripts/monitor_ejecucion.py` aplica estas ideas con reglas fijas y en orden: `DATO_NO_VALIDO` → `PROFUNDIDAD_INSUFICIENTE` → `SIN_HISTORIAL` → `EJECUTAR` / `NORMAL` / `ESPERAR`, según el spread actual frente a la mediana y el percentil 90 de los últimos 5 minutos. Ver [condiciones de ejecución](../conceptos/condiciones_de_ejecucion.md).

**Lo que NO puede concluir con un snapshot:**

- Si el precio va a subir o bajar. Un OBI positivo **no** es una señal de compra demostrada.
- El valor "verdadero" del OBI: depende de N. En Kraken pasó de +0,98 con N = 1 a −0,06 con N = 10, y el OBI(1) cambió de −0,75 a +0,32 en 2 segundos.
- El coste real de una orden grande: el libro cambia mientras se ejecuta, y hay cancelaciones, reposición de liquidez, latencia y el impacto de nuestra propia orden.
- La liquidez oculta: órdenes ocultas, icebergs y la prioridad dentro de cada nivel no aparecen en el libro visible.
- Que un spread mínimo implique una ejecución barata: con 0,1 € de spread, 0,05 BTC ya llegó a recorrer 2 niveles.
- La hora exacta del evento: la hora guardada es la de recepción, no la del exchange.

## 5. Para qué sirve

- **Calcular el coste real de una orden de cualquier tamaño.** El mejor precio solo vale para el volumen del primer nivel. Para órdenes más grandes hay que usar el VWAP.
- **Decidir el tamaño de la orden.** Si una orden genera mucho slippage, conviene dividirla o esperar a que haya más profundidad.
- **Hacer backtests honestos.** Simular las órdenes recorriendo el libro, y no al mejor precio, evita sobrestimar la rentabilidad. Lo mismo vale para sumar comisiones y slippage además del spread.
- **Comparar la liquidez entre activos y momentos.** La profundidad en banda (±b bps) es comparable; contar niveles no lo es.
- **Preparar la investigación de señales.** El OBI y el microprice son candidatos a señal, pero antes hay que demostrarlo: hace falta una serie de snapshots con la misma N, los trades ejecutados (P03), los retornos futuros y una validación fuera de muestra después de descontar costes.
- **Alimentar el monitor de ejecución.** El monitor usa el VWAP como precio de ejecución y suma el slippage al coste de ida y vuelta.

## Referencias

- Código: [`src/quantlab/p02/orderbook.py`](../../src/quantlab/p02/orderbook.py) · monitor: [`scripts/monitor_ejecucion.py`](../../scripts/monitor_ejecucion.py)
- Pruebas: [`tests/test_orderbook.py`](../../tests/test_orderbook.py) · [`tests/test_execution.py`](../../tests/test_execution.py)
- Conclusiones: [conclusiones/P02_order_book.md](../conclusiones/P02_order_book.md)
- Conceptos: [libro de órdenes](../conceptos/libro_de_ordenes.md) · [condiciones de ejecución](../conceptos/condiciones_de_ejecucion.md) · [spread y costes](../conceptos/spread_y_costes.md) · [validación de datos](../conceptos/validacion_de_datos.md)
- Aprendizaje anterior: [P01 · Radiografía de un mercado financiero](P01_market_snapshot.md)
