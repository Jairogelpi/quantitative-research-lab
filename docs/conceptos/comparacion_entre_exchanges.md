# Comparación entre exchanges: alineación causal, lead-lag y arbitraje

**Familia:** microestructura entre mercados · **Visto en:** P06 · **Código:** `src/quantlab/p06/cross_exchange.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Cotización L1 | `bid`, `ask`, `bid_size`, `ask_size` | Mejor precio y cantidad visible de cada lado | Lo mejor disponible en un instante. No es el libro completo. |
| Hora de solicitud | `request_at` | Antes de pedir la cotización | Inicio de la medición de latencia. |
| Hora de recepción | `received_at` | Al recibir la respuesta | Cuándo **nosotros** conocimos el dato. |
| Hora del evento | `exchange_at` | Timestamp del proveedor, si existe (OKX `ts`) | Cuándo ocurrió en el exchange. No se inventa si falta. |
| RTT | `rtt_ms` | received_at − request_at | Tiempo de ida y vuelta de la solicitud. |
| Alineación causal | `align_quotes` | `merge_asof(direction="backward")`, antigüedad ≤ 2 s | Para cada segundo t, la última cotización recibida en o antes de t. |
| Antigüedad | `age_ms` | decision_at − received_at | Cuánto lleva el dato sin actualizarse. |
| Retorno nuevo | `fresh_returns` | log(M_t / M_{t−1}) solo entre dos recepciones nuevas consecutivas | Evita contar precios arrastrados como retornos 0. |
| Lead-lag | `lag_profile` | ρ(k) = Corr(r^A_t, r^B_{t+k}) | k > 0: A se adelanta a B. |
| Coste de compra | `scan_pair` | C = q · Ask_A · (1 + s) · (1 + f_A) | Lo que se paga comprando en A. |
| Ingreso de venta | `scan_pair` | V = q · Bid_B · (1 − s) · (1 − f_B) | Lo que se cobra vendiendo en B. |
| PnL y margen | `net_eur`, `net_bps` | V − C · 10⁴ (V − C) / C | Candidato si es > 0. |
| Desfase entre mercados | `skew_ms` | \|received_at_A − received_at_B\| ≤ 750 ms | Las dos cotizaciones deben ser casi simultáneas. |
| Episodio | `episodes` | Segundos consecutivos en que la misma ruta es candidata | Una oportunidad repetida no son varias. |

## Ideas clave

- **Nunca `nearest`:** podría elegir una cotización recibida después de t, es decir, del futuro.
- **Correlación simultánea baja ≠ independencia:** si un mercado va 2 s por detrás, la relación está en el desplazamiento, no en el mismo segundo.
- **Pearson es frágil ante outliers:** un desajuste de 37 bps hundió la correlación de 0,97 a 0,40. Spearman (rangos) se mantuvo en ≈ 0,97.
- **El lead-lag mide la recepción, no el liderazgo:** retrasar 1 s la recepción de un exchange, sin tocar precios, desplaza el lag estimado 1 s.
- **El spread no se resta dos veces:** ya está dentro del ask de A y del bid de B.
- **Cada ruta paga dos comisiones** más la reserva adversa: con 10 bps por lado y 1 bp de reserva, el umbral es de unos 22 bps.
- **Más tamaño, menos candidatos:** la orden tiene que caber en el tamaño visible de los dos lados.
- **Capital:** hace falta EUR en A **y** BTC en B; el margen sobre la compra no es la rentabilidad del capital.
- **Kraken:** el tamaño del endpoint `Ticker` vale siempre 1; se usa `Depth` (count = 1).

## Validación (`validate_quotes`)

Se detiene con `ValueError` en estos casos: faltan columnas, falta un exchange o hay otro par, precios o tamaños ≤ 0 o no finitos, libro cruzado, recepción vacía o duplicada por exchange, y solicitud posterior a su recepción. `align_quotes` descarta además las recepciones con más de 2 s y, si hay `exchange_at`, los eventos con más de 2 s o futuros en más de 250 ms.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Mid y spread | bid 59.990 · ask 60.010 | 60.000 € · 3,333 bps |
| PnL de 1 BTC (10 bps por lado, sin reserva) | Comprar a 60.000, vender a 60.150 | 60.150 × 0,999 − 60.000 × 1,001 = **+29,85 €** |
| Lead-lag sintético | OKX retrasado 2 s | Máximo de ρ(k) en k = **+2** |

## Código

```python
from quantlab.p06.cross_exchange import (collect_live, synthetic_quotes, validate_quotes, align_quotes,
                                         fresh_returns, leadlag_summary, scan_routes, route_summary,
                                         episodes, fee_sensitivity)

raw, errors = collect_live(60)                       # o synthetic_quotes()
quotes = validate_quotes(raw)
aligned = align_quotes(quotes, "1s")                 # causal: backward, antigüedad <= 2 s
returns = fresh_returns(aligned)
leadlag, _ = leadlag_summary(returns, method="spearman")
scans = scan_routes(aligned, qty=0.01, fees={"kraken": 10, "okx": 10, "bitvavo": 10})
route_summary(scans), episodes(scans)
```

Relacionado: [libro_de_ordenes.md](libro_de_ordenes.md) · [spread_y_costes.md](spread_y_costes.md) · [validacion_de_datos.md](validacion_de_datos.md)
