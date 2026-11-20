# Rentabilidad y riesgo: equity, drawdown, ratios, operaciones y ruina

**Familia:** evaluación de estrategias · **Visto en:** P09 · **Código:** `src/quantlab/p09/performance.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Curva de capital | `equity` | E_t = E_{t−1} · (1 + r_t), empezando en E_0 | Cuánto dinero hay en cada momento. |
| Drawdown | `drawdown` | E_t / máx_{s≤t} E_s − 1 | Caída desde el máximo histórico (incluye E_0). |
| Máximo drawdown | `max_drawdown` | −mín(drawdown) | La peor caída sufrida, en positivo. |
| CAGR | `cagr` | (E_n / E_0)^{A/n} − 1 | Crecimiento anual compuesto equivalente. |
| Volatilidad anualizada | `annualized_volatility` | s(r) · √A | Dispersión de los retornos, en escala anual. |
| Sharpe | `sharpe_ratio` | √A · media(r − r_f) / s(r) | Exceso de retorno por unidad de volatilidad total. |
| Sortino | `sortino_ratio` | √A · media(r − r_f) / √media(mín(r − r_f, 0)²) | Igual, pero penalizando solo los días por debajo de r_f. |
| Calmar | `calmar_ratio` | CAGR / MDD | Crecimiento por unidad de peor caída. |
| Acierto | `win_rate` | ganadoras / total (las neutras cuentan) | Con qué frecuencia se gana. |
| Payoff | `payoff_ratio` | ganancia media / pérdida media | Cuánto se gana cuando se gana, frente a lo que se pierde. |
| Profit factor | `profit_factor` | Σ ganancias / \|Σ pérdidas\| | > 1: se gana más de lo que se pierde. |
| Esperanza | `expectancy` | media del PnL por operación | Lo que se espera ganar o perder por operación. |
| Retorno de recuperación | `recovery_return` | 1 / (1 − L) − 1 | Cuánto hay que ganar para recuperar una pérdida L. |
| Riesgo de ruina | `simulate_ruin` | Fracción de trayectorias bootstrap que tocan el umbral | Probabilidad (según el modelo) de caer por debajo de un nivel. |

A = periodos por año (365 en cripto); r_f = (1 + RF)^{1/A} − 1.

## Ideas clave

- **Las pérdidas pesan más que las ganancias:** perder un 50 % exige ganar un 100 %.
- **Acierto ≠ esperanza:** un 90 % de acierto puede perder dinero si la pérdida media es grande.
- **Un denominador nulo da NaN:** con retornos constantes el Sharpe no existe; no se sustituye por un número enorme.
- **Un CAGR negativo da un Calmar negativo**, no positivo.
- **El coste compuesto destruye:** 20 bps diarios convierten un −7,7 % bruto en un −55,6 % neto.
- **0 de N simulaciones ≠ riesgo nulo:** el bootstrap solo recombina lo que ya ocurrió.
- **Operaciones cerradas ≠ valoración diaria:** el Sharpe diario exige el valor de la cartera cada día.
- **No ajustar mirando el tramo final:** cada ajuste convierte ese tramo en desarrollo.

## Validación (`validate_daily`)

Se detiene con `ValueError` en estos casos: menos de 2 días, fechas duplicadas o desordenadas, días que faltan (no se imputan), falta de `net_return`, y retornos no finitos o ≤ −100 %. `trade_metrics` rechaza registros vacíos o no finitos; `simulate_ruin`, parámetros fuera de rango.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Capital | 1.000 €, −10 %, +20 % | 1.000 → 900 → **1.080 €** |
| Drawdown máximo | — | **10 %** |
| Operaciones | 10, −5, 0, 15, −10 | Acierto 40 %, PF 25/15 = **1,67**, esperanza **2 €** |
| Recuperación | Pérdidas de 10, 25 y 50 % | +11,1 %, +33,3 %, **+100 %** |

## Código

```python
from quantlab.p09.performance import (synthetic_daily, validate_daily, equity_curve, drawdown,
                                      performance_metrics, trade_metrics, cost_sensitivity,
                                      ruin_table, trade_log_to_pnl, split_stability)

daily, trades = synthetic_daily()
daily = validate_daily(daily)
performance_metrics(daily.net_return, capital=1000, periods=365, rf_annual=.02)
trade_metrics(trades.net_pnl)
ruin_table(daily.net_return, (.25, .5, 1., 1.5))
trade_log_to_pnl(p05_log, 1000)                  # registro de P05 → PnL en EUR
```

Relacionado: [costes_de_ejecucion.md](costes_de_ejecucion.md) · [momentum_y_reversion.md](momentum_y_reversion.md) · [series_temporales.md](series_temporales.md)
