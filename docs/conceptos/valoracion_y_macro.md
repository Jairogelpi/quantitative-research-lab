# Valoración y macroeconomía: valor temporal, bonos, DCF, inflación, curva y eventos

**Familia:** valoración fundamental y macro · **Visto en:** P10 · **Código:** `src/quantlab/p10/valuation_macro.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Valor actual | `present_value` | Σ CF_t / (1 + r)^t | Cuánto vale hoy un flujo futuro. |
| Precio de un bono | `bond_price` | Cupones + nominal descontados al rendimiento exigido | Sube cuando bajan los tipos y al revés. |
| Valor de empresa (DCF) | `dcf` | Σ FCFF_t / (1 + r)^t + FCFF_N · (1 + g) / ((r − g)(1 + r)^N) | Valor de los flujos futuros. Exige r > g. |
| Valor por acción | `value_per_share` | (EV − deuda neta) / acciones | Lo que valdría cada acción según el modelo. |
| Inflación interanual | `yoy_by_date` | IPC_t / IPC_{mismo mes del año anterior} − 1 | Subida de precios en 12 meses. |
| Rentabilidad real | `real_return` | (1 + nominal) / (1 + inflación) − 1 | Ganancia en poder adquisitivo. |
| Pendiente de la curva | `yield_curve_bps` | (10 años − 2 años) × 100 | Negativa = curva invertida. |
| Sorpresa | `surprise_pp` | dato − consenso | Lo que el mercado no esperaba. |
| Disponibilidad | `available_at` | Hora real de publicación | Desde cuándo se conoce el dato. |
| Reacción | `return_{h}h_bps` | Precio a t + h / último precio estrictamente antes de t − 1 | Etiqueta de evaluación, no feature. |

## Ideas clave

- **Duración:** a más vencimiento, más sensibilidad a los tipos. Un punto de subida: −1,9 % a 2 años, −7,7 % a 10.
- **El valor terminal domina el DCF:** el 75,9 % del EV en el ejemplo. El valor por acción va de 6,40 a 47,00 € según r y g.
- **Fisher exacto:** con un 15 % nominal y un 10 % de inflación, la rentabilidad real es 4,55 %, no 5 %.
- **Comparar por fecha, no por posición:** si falta un mes, `pct_change(12)` compara con el mes equivocado (FRED no tiene IPC de octubre de 2025).
- **Mes de referencia ≠ disponibilidad:** el IPC de enero se publica en febrero; unirlo por mes de referencia es *look-ahead*.
- **La serie de hoy está revisada:** un backtest necesita el primer valor publicado (vintage de ALFRED).
- **Sin consenso no hay sorpresa:** no se inventa; la conclusión es evidencia insuficiente.
- **Curva invertida ≠ recesión automática.**

## Validación

- `present_value`: tasa > −100 % y flujos finitos. `dcf`: flujos válidos, último flujo positivo y r > g > −1.
- `validate_events_prices` se detiene con IDs u horas duplicadas, consenso ausente o posterior a la publicación, datos no finitos, precios duplicados o ≤ 0 y, en CSV, timestamps sin zona horaria.
- `align_events`: precio previo **estrictamente** anterior a la publicación, antigüedad ≤ 60 min, y precio posterior nunca anterior a la publicación.
- `split_events`: separación cronológica 65/35, sin solapes y sin eventos de desarrollo cuyo horizonte toque la frontera.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Valor actual | 110 € a 1 año al 10 % | **100 €** |
| Bono | Nominal 1.000, cupón 4 %, 5 años, rendimiento 5 % | **956,71 €** |
| DCF | Flujos 100 · 1,04^t, r = 8 %, g = 2 %, deuda neta 300, 100 acciones | **14,83 €/acción** |
| Fisher | Nominal 5 %, inflación 3 % | **1,94 %** real |

## Código

```python
from quantlab.p10.valuation_macro import (present_value, bond_price, dcf, value_per_share, yoy_by_date,
                                          real_return, fetch_fred, fred_indicators,
                                          synthetic_events_and_prices, validate_events_prices,
                                          align_events, split_events, surprise_groups)

value_per_share(100 * 1.04 ** np.arange(5), .08, .02, net_debt=300, shares=100)
monthly, curve = fred_indicators({s: fetch_fred(s, "2022-01-01", "2025-12-31") for s in FRED_SERIES})
events, prices = validate_events_prices(*synthetic_events_and_prices())
results, cutoff = split_events(align_events(events, prices, (1, 6, 24)))
```

Relacionado: [series_temporales.md](series_temporales.md) · [rentabilidad_y_riesgo.md](rentabilidad_y_riesgo.md) · [validacion_de_datos.md](validacion_de_datos.md)
