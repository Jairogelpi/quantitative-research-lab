# P01 · Radiografía de un mercado financiero · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P01_market_snapshot.ipynb` (sección 7)
**Datos de ejemplo:** BTC/EUR ficticio (Bid 59.998 € · Ask 60.002 € · Last 59.999 €)

## 1. Variables de entrada
Todo parte de tres datos que entrega el exchange (o el ejemplo ficticio):

| Variable | Qué es | Ejemplo ficticio |
|---|---|---|
| `best_bid` | Mejor precio al que alguien **compra** ahora. Es lo que recibes si vendes de inmediato. | 59.998 € |
| `best_ask` | Mejor precio al que alguien **vende** ahora. Es lo que pagas si compras de inmediato. | 60.002 € |
| `last_price` | Precio de la **última operación ejecutada**. Es un dato del pasado, no una oferta actual. | 59.999 € |
| `qty` | Cantidad que queremos operar. | 0,01 BTC |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo ficticio | Qué responde |
|---|---|---|---|
| `mid_price` | `(best_ask + best_bid) / 2` | (60.002 + 59.998) / 2 = **60.000 €** | ¿Cuál es el precio de referencia "justo"? (no ejecutable) |
| `spread` | `best_ask − best_bid` | 60.002 − 59.998 = **4 €** | ¿Cuánto separa la compra de la venta? |
| `relative_spread` | `spread / mid_price` | 4 / 60.000 = **0,0000667** | ¿Qué fracción del precio es el spread? |
| `spread_bps` | `relative_spread × 10.000` | 0,0000667 × 10.000 = **0,67 bps** | El mismo coste en puntos básicos, comparable entre activos |
| `last_price_deviation` | `last_price − mid_price` | 59.999 − 60.000 = **−1 €** | ¿La última operación quedó por encima o por debajo del mid? |
| `last_price_deviation_bps` | `last_price_deviation / mid_price × 10.000` | −1 / 60.000 × 10.000 = **−0,17 bps** | La misma desviación en bps |
| `buy_cost` | `qty × best_ask` | 0,01 × 60.002 = **600,02 €** | ¿Cuánto pago si compro ya? |
| `sell_income` | `qty × best_bid` | 0,01 × 59.998 = **599,98 €** | ¿Cuánto recibo si vendo ya? |
| `rt_cost` (ida y vuelta) | `buy_cost − sell_income = qty × spread` | 0,01 × 4 = **0,04 €** | ¿Cuánto pierdo al comprar y vender al instante? |

> 1 bps (punto básico) = 0,01 % = 1/10.000. Los bps sirven para comparar: 4 € de spread son casi nada en BTC (0,67 bps), pero serían enormes en una acción de 10 €.

## 3. Reglas de validación (antes de calcular)
- `best_bid > 0` y `last_price > 0`: un precio nulo o negativo es un dato corrupto.
- `best_ask >= best_bid`: si no se cumple, el libro está **cruzado** y el dato no es fiable.
- `qty > 0`: una cantidad nula o negativa no tiene sentido.

Si alguna falla, el programa **se detiene** (`assert` / `ValueError`) en lugar de calcular con datos malos.

## 4. Conclusiones que un programa puede sacar de forma determinista
Con las mismas entradas, el programa siempre llega a la misma conclusión. No hay opinión ni predicción: son reglas fijas.

| Si el programa observa... | Concluye siempre... |
|---|---|
| `best_bid <= 0`, `last_price <= 0` o `best_ask < best_bid` | El dato no es válido: no se calcula nada. |
| Quiere comprar de inmediato | El precio de ejecución es `best_ask` (con profundidad suficiente en el primer nivel). |
| Quiere vender de inmediato | El precio de ejecución es `best_bid`. |
| Compra y vende `qty` al instante | Pierde exactamente `qty × spread` (sin comisiones y con precios constantes). |
| Cada pata frente al mid | Paga **medio spread** al comprar y otro medio al vender. |
| `spread_bps` de dos activos o dos momentos | El de menor `spread_bps` es más barato de operar en ese instante. |
| `last_price_deviation > 0` | La última operación se ejecutó por encima del mid. |
| `last_price_deviation < 0` | La última operación se ejecutó por debajo del mid. |
| `spread_bps` por debajo de un umbral fijado (p. ej. 1 bps) | El coste del spread es aceptable según esa regla. |

**Lo que NO puede concluir con una sola observación:**
- Si el precio va a subir o bajar: no hay señal predictiva en una foto.
- Si el spread se va a mantener: en las consultas reales pasó de 3,0 € a 0,9 € en minutos.
- Si el dato es reciente o exacto: la validación solo descarta errores evidentes.
- El coste de una orden grande: si supera el volumen del primer nivel, se ejecuta a peores precios (slippage, ver P02).
- Con certeza, quién inició la última operación: que el last esté cerca del Bid o del Ask es solo un indicio.

## 5. Para qué sirve
- **Medir el coste real de operar.** Cada operación paga el spread. Una estrategia que opera mucho puede ser rentable en papel y perder dinero en la realidad.
- **Hacer backtests honestos.** Hay que simular las compras al Ask y las ventas al Bid, no al last ni al mid.
- **Comparar mercados y momentos.** Los bps indican dónde y cuándo es más barato operar.
- **Proteger el análisis.** Validar primero evita que un dato corrupto contamine todos los cálculos posteriores.
- **Construir la base de lo que sigue.** El monitor de ejecución y el libro de órdenes de P02 parten de estas mismas métricas.

## Referencias

- Código: [`src/quantlab/p01/quotes.py`](../../src/quantlab/p01/quotes.py)
- Pruebas: [`tests/test_quotes.py`](../../tests/test_quotes.py)
- Conclusiones: [conclusiones/P01_market_snapshot.md](../conclusiones/P01_market_snapshot.md)
- Conceptos: [precios de cotización](../conceptos/precios_de_cotizacion.md) · [spread y costes](../conceptos/spread_y_costes.md) · [validación de datos](../conceptos/validacion_de_datos.md)
