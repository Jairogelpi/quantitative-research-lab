# P17 · Primera investigación cuantitativa integral · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P17_integrated_research.ipynb`
**Datos:** simulación de 2 h con OKX retrasado 3 s (semilla 1701) y una captura real de Kraken, OKX y Bitvavo BTC/EUR con `collect_live` de P06 (20-11-2026, de 10:00:47 a 10:30:47 UTC, 5.400 cotizaciones, 0 errores; `data/raw/p17_quotes_20261120.csv`, SHA-256 `8dbc1d0814297a5ba939051674e7d88b54ffc676dc6abfdd704e79122f1865be`, no versionado)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | En la simulación, el lead-lag recupera el retraso programado (OKX +3 s, Bitvavo +2 s) y la señal tiene un R² fuera de muestra del 32,9 %. | `lead_lag` · `predictability` | [Investigación integral](../conceptos/investigacion_integral.md) |
| 2 | Aun así, las 143 operaciones de validación pierden: +9,95 € brutos y −183,55 € netos (−21,3 bps por operación); el IC del PnL medio es [−0,373; −0,299] €. | `evaluate` · `block_ci` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 3 | Sin comisiones, la regla sigue perdiendo (−11,54 €): el spread y la reserva adversa superan lo que anticipa la señal. | `fee_sensitivity` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 4 | La pendiente −2,30 de la atribución es un efecto de selección; solo con ejecuciones, beta 1,00 y alpha −22,5 bps. | §9 · `manual_alpha_beta` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 5 | Con datos reales, Kraken no anticipa a OKX: correlación máxima en el mismo segundo (0,38), IC de validación 0,004 (p = 0,95) y R² fuera de muestra −0,02 %. | E2 · `run_study` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 6 | Bitvavo va por delante de Kraken (lag −1 y −2 s) en las dos sesiones de desarrollo reales. | E4 · `session_lead_lag` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 7 | En la captura real, el 50 % de las señales (15 de 30) no tiene 0,01 BTC en el mejor nivel de OKX; su spread mediano es 2,38 bps, 13 veces el de Bitvavo. | E3 · `audit_capture` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 8 | El reloj local no está sincronizado con OKX: su hora del evento es posterior a la recepción en el 37 % de las filas (hasta 0,42 s). | E3 | [Validación](../conceptos/validacion_de_datos.md) |
| 9 | El OBI de OKX, ruido puro en la simulación, sale con p = 0,04 en desarrollo; en una muestra nueva, p = 0,07, y en 20 semillas su correlación media es 0,000. | E4 · E5 · `circular_shift_null` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 10 | Dos paseos aleatorios independientes (correlación 0,63) parecen significativos con un null barajado (desviación 0,05), no con uno circular (0,42). | E5 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 11 | Ejecutar parcialmente las señales sin profundidad empeora el resultado: −195,74 € frente a −183,55 € (simulación) y −24,60 € frente a −20,94 € (real). | E6 · `partial_fill_engine` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 12 | Decisión: no se aprueba la hipótesis económica. Simulación: evidencia estadística sí, económica no. Real: ni una ni otra. | `decision` · E8 | [Investigación integral](../conceptos/investigacion_integral.md) |

## Simulación frente a captura real (validación)

| | Simulación | Real |
|---|---|---|
| Oportunidades observadas | 561 de 575 | 143 de 143 |
| Señales / ejecuciones / sin profundidad | 158 / 143 / 15 | 30 / 15 / 15 |
| PnL bruto / neto condicionado | +9,95 / −183,55 € | −0,11 / −20,94 € |
| Neto medio por ejecución | −21,34 bps | −24,77 bps |
| IC 95 % del PnL medio | [−0,373; −0,299] € | [−0,234; −0,096] € |
| Siempre long: neto | −699,10 € | −97,37 € |

## Limitaciones

- Una sola sesión real de 30 minutos; snapshots REST de 1 s con 0,4–0,6 s de latencia.
- Profundidad solo del mejor nivel; sin colas, sin latencia de órdenes.
- La tabla oficial de comisiones de OKX no se pudo leer (página con JavaScript); se evaluaron 10 y 20 bps por lado.
- El protocolo alternativo del E1 queda registrado para una captura nueva.

## Código y pruebas

- Funciones: `src/quantlab/p17/integrated_research.py` → `synthetic_quotes`, `validate`, `synchronize`, `returns_bps`, `lead_lag`, `opportunities`, `fit_hac`, `predictability`, `evaluate`, `summarize_pnl`, `block_ci`, `fee_sensitivity`, `decision`, `run_study`, `register_protocol`, `audit_capture`, `session_lead_lag`, `circular_shift_null`, `partial_fill_engine`, `opportunity_metrics`.
- Pruebas: `tests/test_integrated_research.py` (resultado de referencia, validación, rejilla causal, corte, motor de ejecución, bootstrap, decisión, auditoría, null circular, ejecución parcial y métricas).
