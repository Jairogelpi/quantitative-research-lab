# P13 · Order Flow, Market Impact y exposición · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P13_order_flow_market_impact.ipynb`
**Datos:** un libro L2 didáctico, 2.400 cotizaciones sintéticas (semilla 73), un experimento de impacto artificial (600 trades, semilla 83) y 150 cotizaciones reales de Kraken BTC/EUR (19-11-2026, 21:24–21:27 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | La reconstrucción del libro reproduce el OFI esperado: +1, +1, −2, +1, +1,5, −2. | `replay` · `features` | [Order flow](../conceptos/order_flow_e_impacto.md) |
| 2 | Eliminar 3 BTC de un nivel no óptimo deja el OFI en 0, aunque la profundidad del bid caiga de 5,5 a 2,5 BTC. | E1 | [Order flow](../conceptos/order_flow_e_impacto.md) |
| 3 | La relación contemporánea OFI–precio tiene R² ≈ 0,61 en la simulación aunque los tamaños sean aleatorios: el OFI tiene una correlación de 0,85 con el signo del cambio de mid. | `ofi_regressions` | [Order flow](../conceptos/order_flow_e_impacto.md) |
| 4 | La relación predictiva a 1 actualización es diminuta (R² 0,01–0,02) y desaparece a 5 (p = 0,96 en validación). | `add_future` · E4 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 5 | La regla de signo acierta el 55,7 % de las veces pero gana 0,04 bps frente a 20 de coste: −19,96 bps por operación. | `sign_rule` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 6 | Agregar el OFI en ventanas de 5 y 15 s mantiene la relación contemporánea (R² 0,70 y 0,66), que se conoce al mismo tiempo que el cambio. | E3 · `window_ofi` | [Order flow](../conceptos/order_flow_e_impacto.md) |
| 7 | En el laboratorio de impacto, el efecto crece con el tamaño y revierte un 71–73 % a los 30 s. | E5 · `impact_by_quartile` | [Order flow](../conceptos/order_flow_e_impacto.md) |
| 8 | Una cobertura spot + perpetuo tiene exposición neta de −10 € y bruta de 12.610 € (apalancamiento bruto 1,8). | `exposure` · E6 | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 9 | En Kraken, el 56 % de las cotizaciones REST tiene OFI nulo (el mejor nivel no cambia entre consultas): el OFI entre snapshots es solo una aproximación. | E7 | [Validación](../conceptos/validacion_de_datos.md) |
| 10 | En Kraken hay relación contemporánea (R² 0,50–0,56) y ninguna predictiva (p = 0,76 y 0,32): evidencia insuficiente. | E7 | [Order flow](../conceptos/order_flow_e_impacto.md) |

## Regresiones (simulación)

| Objetivo | Periodo | Pendiente (bps/BTC) | p-valor | R² |
|---|---|---|---|---|
| Contemporáneo | Desarrollo | 0,251 | ≈ 0 | 0,612 |
| Contemporáneo | Validación | 0,248 | ≈ 0 | 0,607 |
| Futuro (1) | Desarrollo | 0,047 | ≈ 0 | 0,021 |
| Futuro (1) | Validación | 0,038 | 0,001 | 0,014 |
| Futuro (5) | Validación | 0,002 | 0,96 | 0,000 |

## E7 · Kraken BTC/EUR (REST `Depth`, una cotización por segundo)

| Objetivo | Periodo | n | Pendiente (bps/BTC) | p-valor | R² |
|---|---|---|---|---|---|
| Contemporáneo | Desarrollo | 96 | 4,02 | ≈ 0 | 0,50 |
| Contemporáneo | Validación | 53 | 5,27 | ≈ 0 | 0,56 |
| Futuro (1) | Desarrollo | 95 | −0,04 | 0,76 | 0,00 |
| Futuro (1) | Validación | 52 | 0,10 | 0,32 | 0,00 |

## Limitaciones

- La simulación no reproduce un matching engine: sus relaciones están programadas.
- El experimento de impacto usa parámetros inventados; con cotizaciones REST no se puede medir la respuesta a trades reales.
- Entre snapshots de un segundo se pierden los eventos intermedios: no es OFI exacto.
- 2,5 minutos de datos reales no permiten ninguna conclusión estadística.

## Código y pruebas

- Funciones: `src/quantlab/p13/order_flow.py` → `replay`, `features`, `simulate_quotes`, `prepare_quotes`, `add_future`, `ofi_regressions`, `sign_rule`, `impact_experiment`, `exposure`, `manual_ofi`, `manual_ofi_series`, `window_ofi`, `impact_by_quartile`. La captura en vivo reutiliza `collect_live` de P06.
- Pruebas: `tests/test_order_flow.py` (reconstrucción, OFI conocido, validación de mensajes y cotizaciones, segmentos, frontera, regresiones, regla, impacto, exposición y E1–E6).
