# P03 · Análisis de operaciones ejecutadas · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P03_trades.ipynb`
**Datos de ejemplo:** cinco operaciones ficticias de BTC/EUR (`EXAMPLE_TRADES`) y trades públicos de Kraken

P01 miraba el mejor precio y P02 el libro de órdenes: lo que **podría** ejecutarse. P03 mira las operaciones que **ya se ejecutaron** y quién tomó la iniciativa en cada una.

## 1. Variables de entrada

Cada trade llega con estos campos:

| Variable | Qué es | Ejemplo (operación 4) |
|---|---|---|
| `price` | Precio al que se ejecutó | 60.010 € |
| `quantity` | Cantidad ejecutada | 0,8 BTC |
| `timestamp` | Instante del evento, en UTC | 2026-01-01 10:00:04 |
| `side` | Lado agresor (taker): `b` = compra agresiva, `s` = venta agresiva | `b` |
| `order_type` | Tipo de la orden agresora: `m` = mercado, `l` = limitada | `l` |
| `trade_id` | Identificador de la operación | 4 |
| `window` | Duración de las ventanas para agregar | 10 s |

Las cinco operaciones de ejemplo:

| # | Precio | Cantidad | Lado | Tipo |
|---|---|---|---|---|
| 1 | 60.000 € | 0,1 | b | m |
| 2 | 60.005 € | 0,5 | b | m |
| 3 | 60.003 € | 0,2 | s | l |
| 4 | 60.010 € | 0,8 | b | l |
| 5 | 60.008 € | 0,4 | s | m |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `trade_volume` | V = Σ q | 0,1 + 0,5 + 0,2 + 0,8 + 0,4 = **2 BTC** | ¿Cuántos BTC se negociaron? |
| `notional_volume` | N = Σ p × q | **120.014,30 €** | ¿Cuántos euros se negociaron? |
| `buy_volume` / `sell_volume` | Σ q de los trades `b` / `s` | **1,4 / 0,6 BTC** | ¿Cuánto movió cada lado agresor? |
| `signed_volume` | V_buy − V_sell | 1,4 − 0,6 = **+0,8 BTC** | Saldo agresor neto |
| `trade_imbalance` (TI) | (V_buy − V_sell) / (V_buy + V_sell) | 0,8 / 2 = **+0,40** | ¿Qué lado dominó, entre −1 y +1? |
| `count_imbalance` | (n_buy − n_sell) / n | (3 − 2) / 5 = **+0,20** | ¿Qué lado hizo más operaciones? |
| `vwap` | N / V | 120.014,30 / 2 = **60.007,15 €** | Precio medio por BTC negociado |
| `arithmetic_mean_price` | Σ p / n | 300.026 / 5 = **60.005,20 €** | Precio medio por operación |
| `cvd` | Suma acumulada de ±q | +0,1 → +0,6 → +0,4 → +1,2 → **+0,8 BTC** | Saldo agresor desde el inicio de la muestra |
| `cumulative_vwap` | Σ p × q / Σ q hasta cada trade | Al final: **60.007,15 €** | VWAP en cada momento de la muestra |
| `average_trade_size` | V / n | 2 / 5 = **0,4 BTC** | Tamaño típico de una operación |
| `trade_intensity` | trades de la ventana / segundos | 7 trades en 10 s = **0,7 trades/s** | ¿Cuánta actividad hubo? |
| `contemporaneous_return_bps` | (último precio / último precio de la ventana anterior − 1) × 10.000 | Kraken, 18:29:00: **+16,95 bps** | ¿Cuánto se movió el precio en esa ventana? |

### Por qué el VWAP es distinto de la media simple

| Operación | Precio | Peso en la media simple | Peso en el VWAP |
|---|---|---|---|
| 1 | 60.000 € | 20 % | 5 % |
| 2 | 60.005 € | 20 % | 25 % |
| 3 | 60.003 € | 20 % | 10 % |
| 4 | 60.010 € | 20 % | **40 %** |
| 5 | 60.008 € | 20 % | 20 % |

La operación 4 es la más grande y la más cara, y en el VWAP pesa el 40 %. Por eso lo sube a 60.007,15 €.

### Cómo se agrega por ventanas

- Ventanas no solapadas **[inicio, fin)**, etiquetadas con su **cierre**. Ejemplo: el trade de las 10:00:04 cae en la ventana [10:00:00, 10:00:10) y se etiqueta como 10:00:10.
- Una ventana **vacía** tiene volumen 0, pero VWAP, TI y tamaño medio **indefinidos** (`NaN`).
- La primera y la última ventana son de **frontera** (`boundary_window`): pueden estar incompletas y se excluyen de los estudios.

## 3. Reglas de validación (antes de calcular)

`normalize_trades` detiene el análisis con `ValueError` si:

- La respuesta está vacía o alguna fila no tiene 6 o 7 campos.
- Hay un precio o una cantidad ≤ 0, o no finitos.
- Hay un timestamp inválido o un lado distinto de `b`/`s`.
- Hay `trade_id` duplicados (captura solapada o repetida).

Además:

- Ordena por timestamp de forma **estable**: en un empate de hora se conserva el orden de llegada.
- Si la API de Kraken falla, se lanza el error. **Nunca** se sustituyen datos reales por ficticios.
- La agregación se comprueba: la suma de trades, volumen y volumen con signo de las ventanas es igual a la de los trades, y el TI queda entre −1 y +1.

## 4. Conclusiones que un programa puede sacar de forma determinista

Con los mismos trades y la misma ventana, el programa siempre llega a la misma conclusión.

| Si el programa observa... | Concluye siempre... |
|---|---|
| Los trades no superan `normalize_trades` | El dato no es válido: no se calcula nada. |
| `TI > 0` | En esa muestra o ventana, la compra agresiva movió más volumen que la venta agresiva. |
| `TI < 0` | La venta agresiva movió más volumen. |
| `TI = ±1` | Todo el volumen de la ventana fue de un solo lado. |
| TI por volumen > TI por número | Las compras agresivas fueron, de media, más grandes que las ventas. |
| VWAP > media simple | Las operaciones grandes se ejecutaron a precios más altos que las pequeñas. |
| CVD sube entre dos momentos | Entre ellos hubo más compra agresiva que venta agresiva. |
| Ventana sin trades | Volumen 0; VWAP e imbalance indefinidos. |
| Ventana de frontera | Puede estar incompleta: se excluye. |
| Ventana con pocas operaciones | Su TI tiende a ±1 por construcción: un extremo pesa poco como evidencia. |
| Ventana anterior vacía o no consecutiva | No hay retorno contemporáneo: queda indefinido. |

**Lo que NO puede concluir con los trades:**

- Si el precio va a subir o bajar. Un TI o un CVD positivo no es una señal demostrada: en Kraken, con TI +0,40, el precio **cayó** 37 bps.
- Cuántos compradores o vendedores hay. Cada trade tiene los dos; el lado solo dice quién cruzó el libro.
- Si hubo absorción. Los trades no muestran la liquidez pasiva del libro (eso requiere sincronizar con P02).
- Que el agresor usara una orden de mercado. Una orden limitada que cruza el libro también es agresora.
- Lo que pasó fuera de la muestra. Una consulta REST solo trae las últimas N operaciones, y un hueco no prueba que no se negociara.
- Que un retorno contemporáneo anticipe el siguiente. Para eso hacen falta retornos futuros, muchos datos y validación fuera de muestra.

## 5. Para qué sirve

- **Medir la presión real de compra y venta.** El libro (P02) muestra intenciones que se pueden cancelar; los trades muestran lo que sí se ejecutó y quién tomó la iniciativa.
- **Evaluar la calidad de una ejecución.** Comparar tu precio con el VWAP del periodo dice si compraste caro o barato respecto al mercado.
- **Detectar actividad anómala.** Ventanas con mucho volumen o intensidad, como la que concentró el 42 % de la hora, señalan momentos que merecen análisis.
- **Elegir la escala temporal con criterio.** Las ventanas cortas tienen más ruido y más extremos por pocas operaciones; las largas suavizan pero esconden detalle.
- **Preparar la investigación de señales.** El TI y el CVD son candidatos a señal. Para probarlos hacen falta captura continua, retornos futuros de mid price, sincronización con el libro y validación fuera de muestra descontando costes.

## Referencias

- Código: [`src/quantlab/p03/trades.py`](../../src/quantlab/p03/trades.py)
- Pruebas: [`tests/test_trades.py`](../../tests/test_trades.py)
- Conclusiones: [conclusiones/P03_trades.md](../conclusiones/P03_trades.md)
- Conceptos: [operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) · [libro de órdenes](../conceptos/libro_de_ordenes.md) · [validación de datos](../conceptos/validacion_de_datos.md)
- Aprendizaje anterior: [P02 · Análisis del libro de órdenes](P02_order_book.md)
