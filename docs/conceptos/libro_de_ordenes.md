# Libro de órdenes: profundidad, OBI, microprice y slippage

**Familia:** liquidez y costes de ejecución · **Visto en:** P02 · **Código:** `src/quantlab/p02/orderbook.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Snapshot de nivel 2 | `bids`, `asks` | Precio y cantidad agregada por nivel | Foto de la liquidez visible. No muestra identidades ni órdenes individuales. |
| Profundidad (N niveles) | `bid_depth_btc`, `ask_depth_btc` | Σ cantidad de los N primeros niveles | Cuánto se puede ejecutar cerca del mejor precio. |
| Profundidad monetaria | `bid_notional_eur` | Σ precio × cantidad | Lo mismo en euros. |
| Profundidad en banda | `depth_within_bps` | Σ cantidad con precio dentro de mid × (1 ± b/10.000) | Comparable entre activos y momentos, a diferencia de contar niveles. |
| OBI (desequilibrio) | `order_book_imbalance` | (D_bid − D_ask) / (D_bid + D_ask) | Entre −1 y +1. Positivo: más cantidad compradora en la ventana. |
| Microprice | `microprice` | (Ask·Q_bid + Bid·Q_ask) / (Q_bid + Q_ask) | Mid ponderado por las cantidades del primer nivel. |
| VWAP de ejecución | `execution_price` | Σ (precio × cantidad tomada) / cantidad total | Precio medio real de una orden a mercado. |
| Slippage | `slippage_bps` | Compra: (VWAP/Ask − 1)·10.000 · Venta: (1 − VWAP/Bid)·10.000 | Coste adicional por recorrer niveles más allá del mejor. |

## Ideas clave

- **El mejor precio solo vale para el volumen del mejor nivel.** Una orden mayor recorre niveles cada vez peores.
- **El slippage crece con el tamaño y no es simétrico:** depende de la profundidad de cada lado.
- **El OBI depende de la ventana** (N niveles o banda). Siempre hay que guardar N junto al valor. Puede cambiar de signo entre ventanas y de un segundo a otro.
- **Microprice ≠ precio ejecutable ≠ predicción.** Es una referencia.
- **El snapshot es parcial:** si la banda llega al último nivel recibido, la profundidad es solo un **mínimo** (`complete=False`).
- **Sin sustitución silenciosa:** si la API falla, se lanza el error. Nunca se etiquetan datos ficticios como reales.
- **Separar costes:** spread (P01), slippage (P02) y comisiones se calculan por separado. Sumar el spread completo al slippage frente al ask contaría parte del coste dos veces.

## Validación (`normalize_book`)

Se detiene con `ValueError` en estos casos: lado vacío, precio o cantidad ≤ 0 o no finitos, niveles duplicados, libro cruzado o bloqueado (bid ≥ ask).

## Ejemplo (libro de referencia)

| | Valor |
|---|---|
| Mid | 60.000 € |
| Profundidad 5 niveles | 4,7 BTC bid / 3,5 BTC ask |
| OBI(5) | +0,1463 |
| Microprice | 60.000,67 € |
| Compra de 0,5 BTC | 0,1 a 60.002 € + 0,3 a 60.005 € + 0,1 a 60.010 € → VWAP **60.005,40 €** (0,57 bps) |
| Compra de 4 BTC | Solo hay 3,5 BTC → `complete=False` |

## Código

```python
from quantlab.p02.orderbook import (fetch_kraken_book, normalize_book, book_features,
                                    depth_within_bps, simulate_market_order)

raw, received_at = fetch_kraken_book(levels=100)    # endpoint público Depth
bids, asks = normalize_book(raw)                    # valida y ordena
f = book_features(bids, asks, n_levels=5)           # profundidad, OBI, microprice
d = depth_within_bps(bids, asks, band_bps=5)        # E4: profundidad ±5 bps
r, fills = simulate_market_order(bids, asks, "buy", 0.5)   # VWAP, slippage, complete
```

## Integración con el monitor

`scripts/monitor_ejecucion.py` descarga el libro (`--levels`, 100 por defecto) y simula la orden en los dos lados. El precio de ejecución pasa a ser el **VWAP** y el coste de ida y vuelta incluye el slippage. Ver [condiciones_de_ejecucion.md](condiciones_de_ejecucion.md).

Relacionado: [spread_y_costes.md](spread_y_costes.md) · [validacion_de_datos.md](validacion_de_datos.md)
