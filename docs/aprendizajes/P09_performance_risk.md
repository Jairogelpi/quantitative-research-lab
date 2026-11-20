# P09 · Evaluación de rentabilidad y riesgo · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P09_performance_risk.ipynb`
**Datos de ejemplo:** 365 días sintéticos de una estrategia y un benchmark, y las operaciones reales de P05 sobre Kraken

P05 a P08 producían señales, operaciones y costes. P09 construye el **evaluador**: dada una serie de retornos o una lista de operaciones, ¿cuánto se ganó, cuánto se sufrió para ganarlo y qué probabilidad hay de perder la mitad del capital?

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `net_return` | Retorno diario neto de costes, en decimal | — |
| `gross_return` | Retorno diario antes de costes (opcional) | — |
| `benchmark_return` | Retorno diario de la referencia (opcional) | — |
| `net_pnl` | PnL neto de cada operación cerrada, en EUR | — |
| `INITIAL_CAPITAL` | Capital inicial | 1.000 € |
| `PERIODS_PER_YEAR` (A) | Periodos por año | 365 (cripto, días naturales) |
| `RISK_FREE_ANNUAL` (RF) | Tipo libre de riesgo supuesto | 2 % |
| `COST_BPS` | Coste diario supuesto | 20 bps |
| Ruina | Umbral, horizonte, bloque, trayectorias | 50 %, 180 días, 5, 3.000 |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `equity` | E_t = E_{t−1} · (1 + r_t) | 1.000 · 0,9 · 1,2 = **1.080 €** | ¿Cuánto capital hay? |
| `cumulative_return` | E_n / E_0 − 1 | **+8 %** (no +10 %) | ¿Cuánto se ganó en total? |
| `drawdown` | E_t / máx(E_0..E_t) − 1 | Día 1: 900 / 1.000 − 1 = **−10 %** | ¿Cuánto se cayó desde el máximo? |
| `max_drawdown` | −mín(drawdown) | Estrategia: **57,1 %** | ¿Cuál fue la peor caída? |
| `cagr` | (E_n / E_0)^{A/n} − 1 | 365 días: igual al acumulado, **−55,6 %** | ¿Cuánto rinde al año? |
| `annualized_volatility` | s(r) · √365 | **19,4 %** | ¿Cuánto varían los retornos? |
| `sharpe_ratio` | √365 · media(r − r_f) / s(r) | **−4,17** | ¿Cuánto exceso de retorno por unidad de riesgo? |
| `sortino_ratio` | √365 · media(r − r_f) / √media(mín(r − r_f, 0)²) | **−4,99** | Lo mismo, penalizando solo la parte mala |
| `calmar_ratio` | CAGR / MDD | −0,556 / 0,571 = **−0,97** | ¿Cuánto crecimiento por unidad de caída? |
| `win_rate` | ganadoras / total | [10, −5, 0, 15, −10]: **40 %** | ¿Con qué frecuencia se gana? |
| `payoff_ratio` | ganancia media / pérdida media | 12,5 / 7,5 = **1,67** | ¿Compensan las ganancias a las pérdidas? |
| `profit_factor` | Σ ganancias / \|Σ pérdidas\| | 25 / 15 = **1,67** | ¿Se gana más de lo que se pierde? |
| `expectancy` | media del PnL | 10 / 5 = **2 €** | ¿Cuánto se espera por operación? |
| `recovery_return` | 1 / (1 − L) − 1 | L = 50 %: **+100 %** | ¿Cuánto hay que ganar para recuperar? |
| `risk_of_ruin` | Fracción de trayectorias que tocan el umbral | Exposición 150 %: **40,2 %** | ¿Probabilidad de perder la mitad? |

## 3. Reglas de validación (antes de calcular)

`validate_daily` detiene el análisis con `ValueError` si:

- Hay menos de 2 días, o fechas duplicadas o desordenadas.
- Falta algún día: la frecuencia debe ser exactamente diaria, y **los huecos no se imputan**.
- Falta `net_return`, o hay retornos no finitos o ≤ −100 %.

Y además:

- `equity_curve` exige capital > 0 y retornos > −100 %, e incluye el capital inicial en el máximo histórico.
- Un denominador nulo (volatilidad, pérdidas o MDD igual a 0) da **NaN**, no infinito ni cero. La excepción es el profit factor sin pérdidas, que es infinito si hubo ganancias y NaN si todo fue cero.
- Las operaciones a cero cuentan en los denominadores de acierto y fallo.
- La suma del PnL de las operaciones debe coincidir con la variación del capital (reconciliación).

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| La serie no supera `validate_daily` | El dato no es válido: no se evalúa. |
| Retorno acumulado < 0 | La estrategia perdió dinero en la muestra. |
| Esperanza < 0 | Cada operación pierde de media; más operaciones o más exposición solo amplían la pérdida. |
| Profit factor < 1 | Las pérdidas totales superan a las ganancias totales. |
| Retorno bruto acumulado ≤ 0 | Ninguna reducción de costes la hace rentable. |
| Pérdida L | Hay que ganar 1 / (1 − L) − 1 para recuperarla. |
| Volatilidad 0 | El Sharpe no está definido. |
| Suma del PnL ≠ variación del capital | Los registros no cuadran: hay un error. |
| Más exposición con esperanza negativa | Mayor riesgo de ruina y menor capital mediano. |

**Lo que NO puede concluir:**

- Que una estrategia vaya a funcionar en el futuro: las métricas describen el pasado de la muestra.
- Que el riesgo de ruina sea nulo porque ninguna simulación tocó el umbral.
- Un Sharpe diario a partir de operaciones de duración irregular, sin la valoración diaria de la cartera.
- Que el Sharpe sea significativo: no hay intervalos de confianza ni ajuste por dependencia.
- Que unos parámetros sean robustos si se eligieron mirando el tramo de evaluación.

## 5. Para qué sirve

- **Decidir si una estrategia merece seguir investigándose.** El evaluador resume en pocas cifras cuánto se ganó, cuánto se sufrió y con qué consistencia.
- **No dejarse engañar por el acierto.** La esperanza y el profit factor muestran si se gana dinero, no solo cuántas veces.
- **Medir el peso del drawdown.** La asimetría de la recuperación explica por qué una gran caída puede arruinar años de beneficios.
- **Cuantificar el riesgo de apalancamiento.** El riesgo de ruina por bootstrap muestra cómo la exposición convierte una mala estrategia en una catastrófica.
- **Integrar todo el laboratorio.** Las operaciones de P05, con los costes de P08, se evalúan aquí con las mismas métricas.
- **Base para el resto del curso.** Cualquier estrategia futura pasará por este evaluador antes de considerarse.

## Referencias

- Código: [`src/quantlab/p09/performance.py`](../../src/quantlab/p09/performance.py)
- Pruebas: [`tests/test_performance.py`](../../tests/test_performance.py)
- Conclusiones: [conclusiones/P09_performance_risk.md](../conclusiones/P09_performance_risk.md)
- Conceptos: [rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) · [costes de ejecución](../conceptos/costes_de_ejecucion.md) · [momentum y reversión](../conceptos/momentum_y_reversion.md)
- Aprendizaje anterior: [P08 · Motor de costes operativos y ejecución](P08_transaction_costs.md)
