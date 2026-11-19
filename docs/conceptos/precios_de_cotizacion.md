# Precios de una cotización

**Familia:** datos de mercado · **Visto en:** P01

## Conceptos

| Concepto | Qué es | Tipo | ¿Se puede operar a ese precio? |
|---|---|---|---|
| **Bid** | Mejor precio al que alguien está dispuesto a **comprar**. | Original (exchange) | Sí: es el precio al que tú **vendes** al instante. |
| **Ask** | Mejor precio al que alguien está dispuesto a **vender**. | Original (exchange) | Sí: es el precio al que tú **compras** al instante. |
| **Last price** | Precio de la **última operación** ejecutada. | Original (exchange) | No: es historia y puede estar desactualizado. |
| **Mid price** | Punto medio entre Bid y Ask. | Derivado | No: es una referencia calculada, no una oferta. |

```
Mid = (Ask + Bid) / 2
```

## Ideas clave

- **No existe "el precio" de un activo.** Hay uno para comprar, otro para vender y referencias calculadas.
- Una compra inmediata **cruza el Ask** y una venta inmediata **cruza el Bid**, siempre que haya profundidad suficiente en ese nivel.
- La **hora de recepción** del dato no es la hora del evento en el exchange.
- ⚠️ El campo de volumen del ticker de Kraken (`a`/`b`) vale siempre 1 y no es real. Para saber cuánto volumen hay en el mejor nivel se usa el libro de órdenes: `fetch_kraken_quote()`, endpoint `Depth`.
- El Last price puede quedar por encima o por debajo del mid. En el ejemplo de P01 está 1 € por debajo.

## Ejemplo (P01, datos ficticios)

| Bid | Ask | Last | Mid |
|---|---|---|---|
| 59.998 € | 60.002 € | 59.999 € | 60.000 € |

## Código

En el proyecto: `from quantlab.p01.quotes import fetch_kraken_ticker` → `market = fetch_kraken_ticker()`.

Qué hace por dentro (consulta el ticker público de Kraken para BTC/EUR):

```python
import requests
from datetime import datetime, timezone

response = requests.get(
    "https://api.kraken.com/0/public/Ticker",
    params={"pair": "XBTEUR"}, timeout=15,
)
response.raise_for_status()
payload = response.json()
if payload["error"]:
    raise RuntimeError(payload["error"])
ticker = next(iter(payload["result"].values()))

market = {
    "source": "kraken_public_ticker",
    "received_at": datetime.now(timezone.utc).isoformat(),  # hora de recepción, no del evento
    "symbol": "BTC/EUR",
    "best_bid": float(ticker["b"][0]),
    "best_ask": float(ticker["a"][0]),
    "last_price": float(ticker["c"][0]),
}
```

Relacionado: [spread_y_costes.md](spread_y_costes.md) · [validacion_de_datos.md](validacion_de_datos.md)
