# Spread, bps y coste de ejecución

**Familia:** liquidez y costes de ejecución · **Visto en:** P01 (lecciones 1.1 y 1.2)

## Fórmulas

| Métrica | Campo | Fórmula | Unidad |
|---|---|---|---|
| Mid price | `mid_price` | (Ask + Bid) / 2 | € |
| Spread | `spread` | Ask − Bid | € |
| Spread relativo | `relative_spread` | Spread / Mid | fracción |
| Spread en bps | `spread_bps` | Spread / Mid × 10.000 | bps |
| Desviación del último precio | `last_price_deviation` | Last − Mid | € (y bps del mid) |

> **1 bps = 0,01 %.** Los bps permiten comparar activos de precios muy distintos.
>
> `last_price_deviation` no está definida en las lecciones. Aquí la tomamos como la distancia del último precio al mid; si es positiva, la última operación quedó por encima del mid.

## Ideas clave

- **Operar cuesta el spread.** Comprar y vender al instante pierde el spread completo aunque el precio no se mueva.
- **Cada pata cuesta medio spread** frente al mid: la compra paga mid + spread/2 y la venta recibe mid − spread/2.
- **Coste de ida y vuelta** = cantidad × spread (sin comisiones y con profundidad suficiente en el primer nivel).
- Un mismo spread en euros es un coste relativo distinto según el precio del activo. Por eso se compara en bps.
- Las comisiones se suman aparte. Si la orden es grande y no cabe en el primer nivel, aparece además **slippage** (lección 1.3).

## Ejemplo (P01, datos ficticios)

| Métrica | Valor |
|---|---|
| Mid | 60.000 € |
| Spread | 4 € |
| Spread relativo | 0,0000667 |
| Spread bps | 0,667 bps |
| Last − Mid | −1 € (−0,167 bps) |

Compra y venta inmediata de **0,01 BTC**:

| Operación | Precio | Importe |
|---|---|---|
| Compra (cruza el Ask) | 60.002 € | pagas 600,02 € |
| Venta (cruza el Bid) | 59.998 € | recibes 599,98 € |
| **Coste implícito** | | **0,04 € ≈ 0,67 bps** |

### Spread real (Kraken, BTC/EUR, 19-11-2026)

Dos consultas con minutos de diferencia dieron **3,0 € (0,52 bps)** y **0,9 € (0,16 bps)**. El spread real tiene el mismo orden de magnitud que el ficticio, pero **varía mucho en poco tiempo**.

## Código

Está en `src/quantlab/quotes.py`; se importa con `from quantlab.quotes import quote_metrics, round_trip_cost`. Versión simplificada:

```python
def quote_metrics(best_bid: float, best_ask: float, last_price: float) -> dict:
    """Métricas básicas de una cotización Bid/Ask y del último precio."""
    if best_bid <= 0 or best_ask < best_bid:
        raise ValueError("Cotización no válida: se necesita 0 < bid <= ask")
    mid_price = (best_ask + best_bid) / 2
    spread = best_ask - best_bid
    relative_spread = spread / mid_price
    spread_bps = relative_spread * 10_000
    last_price_deviation = last_price - mid_price
    return {
        "mid_price": mid_price,
        "spread": spread,
        "relative_spread": relative_spread,
        "spread_bps": spread_bps,
        "last_price_deviation": last_price_deviation,
        "last_price_deviation_bps": last_price_deviation / mid_price * 10_000,
    }


def round_trip_cost(best_bid: float, best_ask: float, qty: float) -> float:
    """Coste en € de comprar y vender `qty` al instante (sin comisiones)."""
    return qty * best_ask - qty * best_bid   # = qty * spread
```

Relacionado: [precios_de_cotizacion.md](precios_de_cotizacion.md) · [validacion_de_datos.md](validacion_de_datos.md)
