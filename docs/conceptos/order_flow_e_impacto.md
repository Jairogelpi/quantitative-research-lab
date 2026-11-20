# Order flow e impacto: reconstrucción L2, OFI, OBI, respuesta del precio y exposición

**Familia:** microestructura · **Visto en:** P13 · **Código:** `src/quantlab/p13/order_flow.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Snapshot L2 | `snapshot` | Cantidad agregada por precio y lado | Estado completo del libro en un instante. |
| Actualización absoluta | `updates` | (secuencia, lado, precio, cantidad total; 0 elimina el nivel) | Cambio de un nivel. Una secuencia perdida obliga a resincronizar. |
| OBI | `obi` | (q^b − q^a) / (q^b + q^a) | **Estado**: qué lado tiene más cantidad en el mejor nivel. |
| OFI de primer nivel | `ofi_event` | 1{b_t ≥ b_{t−1}}·q^b_t − 1{b_t ≤ b_{t−1}}·q^b_{t−1} − 1{a_t ≤ a_{t−1}}·q^a_t + 1{a_t ≥ a_{t−1}}·q^a_{t−1} | **Flujo**: cuánto cambió la presión compradora frente a la vendedora. |
| Segmento | `segment` | Tramo sin saltos mayores que `MAX_GAP_SECONDS` | El OFI y los cambios no se calculan a través de un hueco. |
| Relación contemporánea | `ofi_regressions` | Δmid_t sobre OFI_t | Explica el cambio; no es operable. |
| Relación predictiva | `add_future` | Δmid_{t→t+k} sobre OFI_t | Anticipa (o no) el cambio. |
| Respuesta a un trade | `impact_experiment` | signo del agresor · (mid_{t+h} − mid_{t−}) | Impacto inmediato y cuánto revierte. |
| Exposición | `exposure` | Nominal N = q · P; bruta Σ\|N\|; neta Σ N | Riesgo de dirección (neta) y capital en juego (bruta). |

## Ideas clave

- **OBI ≠ OFI:** uno es el estado del libro; el otro, su cambio. Una OBI positiva puede convivir con un OFI negativo.
- **La relación contemporánea es casi mecánica:** el OFI incorpora si el mejor bid/ask subió o bajó. En la simulación (tamaños aleatorios), su correlación con el signo del cambio de mid es 0,85.
- **La predicción es mínima:** R² de 0,01–0,02 a una actualización en la simulación; nada a 5 actualizaciones ni en Kraken.
- **El OFI de primer nivel no ve los niveles profundos:** eliminar 3 BTC de un nivel no óptimo deja el OFI en 0.
- **Entre snapshots REST no hay OFI exacto:** los cambios intermedios se compensan y no se ven (el 53–56 % de las cotizaciones de Kraken no cambiaba nada).
- **El impacto revierte:** ≈ 71–73 % a los 30 s en el laboratorio; el último punto medido no demuestra impacto permanente.
- **Neta cero ≠ riesgo cero:** una cobertura puede tener exposición bruta alta.

## Validación

- `replay` se detiene ante secuencias perdidas, lados o cantidades inválidos y libros cruzados.
- `prepare_quotes` filtra un único mercado y se detiene con columnas ausentes, menos de 60 cotizaciones, horas vacías o duplicadas, precios o tamaños ≤ 0 o ask ≤ bid. Corta en segmentos sin rellenar huecos.
- `add_future` no cruza segmentos ni el corte temporal.
- `exposure` exige un patrimonio positivo.

## Ejemplo (libro didáctico)

| Evento | OFI |
|---|---|
| Alta en el mejor bid (2 → 3) | +1 |
| Ejecución contra el mejor ask (2 → 1) | +1 |
| Cancelación en el mejor bid (3 → 1) | −2 |
| Desaparece el mejor ask (1 → 0) | +1 |
| Mejora del bid (nuevo nivel de 1,5) | +1,5 |
| Mejora del ask (nuevo nivel de 2) | −2 |

## Código

```python
from quantlab.p13.order_flow import (replay, features, simulate_quotes, prepare_quotes, add_future,
                                     ofi_regressions, sign_rule, impact_experiment, exposure)
from quantlab.p06.cross_exchange import collect_live

x = prepare_quotes(simulate_quotes())             # o prepare_quotes(collect_live(150, ("kraken",))[0])
cut = int(len(x) * .65)
x = add_future(x, 1, cut)
ofi_regressions(x, cut, {"contemporáneo": "mid_change_bps", "futuro": "future_bps"})
```

Relacionado: [libro_de_ordenes.md](libro_de_ordenes.md) · [operaciones_ejecutadas.md](operaciones_ejecutadas.md) · [derivados_perpetuos.md](derivados_perpetuos.md)
