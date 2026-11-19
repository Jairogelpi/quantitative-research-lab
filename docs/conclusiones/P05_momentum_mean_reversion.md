# P05 · Momentum y Mean Reversion · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P05_momentum_mean_reversion.ipynb`
**Datos:** 1.800 cierres sintéticos de 1 minuto (semilla 42; AR(1) con φ = +0,35 y luego −0,35, y un hueco de 3 velas) y 720 velas públicas de Kraken BTC/EUR (19-11-2026, de 07:08 a 19:07 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | Con N = 20 y h = 5, ninguna señal tiene una asociación positiva sólida: momentum tiene IC negativo (−0,089 en desarrollo, −0,045 en validación). | `information_table` | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 2 | La reversión cambia de signo entre periodos: +0,026 → −0,018 en la simulación y +0,045 → −0,080 en Kraken. | `information_table` · E6 | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 3 | La simulación tiene dependencia real (autocorrelación de retardo 1 de +0,40 y −0,36), pero el retraso de una vela en la entrada deja fuera justo ese retorno. | Sección 9 | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 4 | Todas las reglas pierden con 20 bps por ciclo en los dos periodos: de −2,6 % a −32,9 % en total. | `strategy_table` | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 5 | En la simulación, los seis costes de equilibrio son negativos (de −0,04 a −5,47 bps): ni con coste cero hay beneficio. | E5 · `breakeven_costs` | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 6 | Las exposiciones son muy distintas: `periodic_long` está invertido más del 80 % del tiempo; mean reversion, un 25–29 %. | E5 | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 7 | La mejor combinación del desarrollo (reversión, N = 60, h = 10, IC +0,114) cae a −0,004 en validación. | E4 · `development_grid` | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |
| 8 | En Kraken, las mejores operaciones brutas (mean reversion, +1,40 bps en validación) quedan muy lejos de 20 bps de coste. | E6 | [Spread y costes](../conceptos/spread_y_costes.md) |
| 9 | Con 12 horas de un día y objetivos solapados, la conclusión sobre BTC/EUR es **evidencia insuficiente**. | E6 | [Momentum y reversión](../conceptos/momentum_y_reversion.md) |

## Simulación (N = 20, h = 5, 20 bps)

| Periodo | Regla | Operaciones | Bruto medio | Neto medio | Total neto | Exposición |
|---|---|---|---|---|---|---|
| Desarrollo | Momentum | 95 | −0,33 bps | −20,33 bps | −17,6 % | 41,6 % |
| Desarrollo | Mean reversion | 56 | −0,04 bps | −20,04 bps | −10,6 % | 24,5 % |
| Desarrollo | Periodic long | 187 | −1,24 bps | −21,24 bps | −32,9 % | 81,8 % |
| Validación | Momentum | 51 | −1,66 bps | −21,66 bps | −10,5 % | 40,9 % |
| Validación | Mean reversion | 36 | −5,47 bps | −25,47 bps | −8,8 % | 28,9 % |
| Validación | Periodic long | 104 | −3,39 bps | −23,39 bps | −21,6 % | 83,5 % |

## E6 · Kraken BTC/EUR (recepción 19:07:14 UTC)

720 velas de 1 minuto, sin huecos. Precio: 58.139,10 → 57.110,20 € (−177 bps). Autocorrelación de retardo 1: +0,013. Desarrollo: 442 filas; validación: 246.

| Señal | IC desarrollo | IC validación |
|---|---|---|
| Momentum | −0,093 | −0,071 |
| Reversión | +0,045 | −0,080 |

| Regla | Neto medio desarrollo | Neto medio validación |
|---|---|---|
| Momentum | −21,11 bps | −18,90 bps |
| Mean reversion | −15,32 bps | −18,60 bps |
| Periodic long | −19,85 bps | −22,50 bps |

## Limitaciones

- La simulación no es un modelo calibrado de BTC: sus resultados no son evidencia sobre Bitcoin.
- 12 horas de un solo día no son un histórico suficiente.
- Los objetivos se solapan: no hay p-valores ni intervalos ajustados por dependencia.
- El coste de 20 bps es un supuesto fijo; no se modelan spread dinámico, llenados, slippage, impacto ni fiscalidad.
- Se probaron 9 combinaciones de parámetros, y la validación ya se había visto antes de congelarlos.

## Código y pruebas

- Funciones: `src/quantlab/p05/signals.py` → `synthetic_prices`, `fetch_kraken_ohlc`, `load_p04_series`, `regularize`, `build_features`, `add_target`, `split_train_test`, `information_table`, `simulate`, `strategy_table`, `cost_sensitivity`, `manual_momentum`, `manual_zscore`, `development_grid`, `breakeven_costs`.
- Pruebas: `tests/test_signals.py` (regularización, las 10 comprobaciones del cuaderno, separación sin fugas, IC, simulación, E1–E5 y 1 prueba en vivo).
