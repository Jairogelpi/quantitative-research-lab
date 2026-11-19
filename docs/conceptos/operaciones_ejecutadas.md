# Operaciones ejecutadas: volumen, VWAP, Trade Imbalance, CVD e intensidad

**Familia:** flujo de órdenes · **Visto en:** P03 · **Código:** `src/quantlab/p03/trades.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Trade | fila de `trades` | Precio, cantidad, hora, lado agresor, tipo de orden, ID | Una ejecución que **ya ocurrió**. Tiene un comprador y un vendedor. |
| Lado agresor | `side` | `b` = compra agresiva · `s` = venta agresiva | Quién cruzó el libro (taker). No es "quién hay en el mercado". |
| Volumen base | `trade_volume` | V = Σ q | BTC negociados. |
| Volumen nominal | `notional_volume` | N = Σ p · q | Euros negociados. |
| VWAP | `vwap` | N / V | Precio medio **por BTC** negociado. |
| Volumen con signo | `signed_volume` | +q si `b`, −q si `s` | Saldo agresor de cada trade. |
| Trade Imbalance | `trade_imbalance` | (V_buy − V_sell) / (V_buy + V_sell) | Entre −1 y +1. Positivo: dominó la compra agresiva. |
| Desequilibrio por número | `count_imbalance` | (n_buy − n_sell) / n | Igual, pero contando operaciones en lugar de volumen. |
| CVD | `cvd` | Suma acumulada del volumen con signo | Saldo agresor desde el **inicio de la muestra**, no del mercado. |
| Intensidad | `trade_intensity` | Trades por ventana / segundos de la ventana | Actividad: trades por segundo. |
| Tamaño medio | `average_trade_size` | V / número de trades | BTC por operación. |

## Ideas clave

- **El lado agresor no es una orden de mercado.** Una orden limitada que cruza el libro también es taker. En Kraken, 595 de 1.000 trades fueron limitadas.
- **VWAP ≠ media simple.** La media simple pesa igual cada operación; el VWAP pesa cada BTC.
- **TI por volumen ≠ TI por número.** Si discrepan, el tamaño de las operaciones está desequilibrado entre lados.
- **El TI depende de la ventana.** Con pocas operaciones tiende a ±1 por construcción. Hay que mirar cuántos trades lo sostienen.
- **CVD creciente no garantiza que el precio suba.** La liquidez pasiva puede absorber la presión agresiva.
- **Una ventana vacía** tiene volumen 0, pero VWAP e imbalance **indefinidos** (`NaN`), no 0.
- **Ventanas de frontera:** la primera y la última de una muestra REST pueden estar incompletas. Se marcan (`boundary_window`) y se excluyen.
- **Retorno contemporáneo ≠ retorno futuro.** Lo que pasa dentro de una ventana no anticipa la siguiente.

## Ventanas temporales (`aggregate_trades`)

- No solapadas, convención **[inicio, fin)** y etiquetadas con su **cierre**.
- Comprobaciones: la suma de trades, volumen y volumen con signo de las ventanas coincide con la de los trades, y el TI queda entre −1 y +1.

## Validación (`normalize_trades`)

Se detiene con `ValueError` en estos casos: respuesta vacía o filas sin 6 o 7 campos, precio o cantidad ≤ 0 o no finitos, timestamp inválido, lado distinto de `b`/`s` e IDs duplicados. Ordena por timestamp de forma estable, para conservar el orden de llegada en empates.

## Ejemplo (cinco operaciones)

| | Valor |
|---|---|
| Compras / ventas agresivas | 1,4 / 0,6 BTC |
| Volumen | 2 BTC · 120.014,30 € |
| TI por volumen / por número | +0,40 / +0,20 |
| CVD final | +0,8 BTC |
| VWAP / media simple | 60.007,15 € / 60.005,20 € |

## Código

```python
from quantlab.p03.trades import (fetch_recent_trades, normalize_trades, add_trade_features,
                                 summarize_trades, aggregate_trades, trade_metrics,
                                 count_imbalance, compare_windows, top_volume_windows)

trades, provenance = fetch_recent_trades("XBTEUR", 1000)   # endpoint público Trades
features = add_trade_features(trades)                       # nocional, volumen con signo, CVD, VWAP acumulado
summary = summarize_trades(trades)                          # volumen, TI, VWAP, tamaño medio
bars = aggregate_trades(trades, "10s")                      # ventanas [inicio, fin)
compare_windows(trades, ("5s", "10s", "30s"))               # E3
top_volume_windows(bars, 5)                                 # E4
```

Relacionado: [libro_de_ordenes.md](libro_de_ordenes.md) · [validacion_de_datos.md](validacion_de_datos.md) · [precios_de_cotizacion.md](precios_de_cotizacion.md)
