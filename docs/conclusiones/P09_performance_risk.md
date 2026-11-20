# P09 · Evaluación de rentabilidad y riesgo · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P09_performance_risk.ipynb`
**Datos:** 365 días sintéticos (semilla 42; beta 0,35 a un mercado sintético, 20 bps de coste diario y un episodio adverso de 10 días) y el registro de operaciones de P05 sobre 720 velas reales de Kraken (19-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | La estrategia neta pierde un 55,6 % (MDD 57,1 %, Sharpe −4,17) mientras el benchmark gana un 13,4 % (Sharpe 0,49). | `performance_metrics` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 2 | Ni sin costes gana: −7,7 % bruto. El episodio adverso de 10 días cuesta en torno a un 13 %. | `performance_metrics` · E5 | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 3 | 20 bps diarios compuestos restan casi 48 puntos de retorno anual (−7,7 % → −55,6 %). | `cost_sensitivity` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 4 | Por operación: 42,5 % de acierto, payoff 0,79, profit factor 0,58 y esperanza −1,52 €. La suma cuadra con la caída del capital. | `trade_metrics` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 5 | Recuperar una pérdida del 50 % exige un +100 %; recuperar el MDD de la estrategia (57,1 %), un +133 %. | E2 · `recovery_return` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 6 | Un 90 % de acierto puede perder dinero (esperanza −1,10 €) y un 30 % ganarlo (+1,60 €). | E3 · `trade_metrics` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 7 | Con retornos constantes el Sharpe queda indefinido; el Sortino también, salvo si el retorno es inferior a r_f (−√365). | E4 · `risk_free_comparison` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 8 | Con una esperanza negativa, la ruina depende sobre todo del umbral y el horizonte: del 3 % (50 %, 180 días) al 99 % (70 %, 365 días). | E6 · `ruin_grid` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 9 | En las operaciones reales de P05, mean reversion tiene un profit factor bruto de 1,43 que cae a 0,15 con 20 bps por operación. | E7 · `trade_log_to_pnl` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 10 | La estrategia neta pierde en las dos mitades (Sharpe −4,62 y −3,74): consistentemente mala, y no se ajustó nada mirando el segundo tramo. | E8 · `split_stability` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |

## Métricas principales

| Métrica | Neta | Bruta | Benchmark |
|---|---|---|---|
| Capital final | 444,47 € | 923,17 € | 1.134,36 € |
| CAGR | −55,6 % | −7,7 % | +13,4 % |
| Volatilidad | 19,4 % | 19,4 % | 32,4 % |
| Máximo drawdown | 57,1 % | 18,9 % | 24,7 % |
| Sharpe / Sortino / Calmar | −4,17 / −4,99 / −0,97 | −0,42 / −0,58 / −0,41 | 0,49 / 0,72 / 0,54 |

## Riesgo de ruina (50 % del capital en 180 días, bloques de 5)

| Exposición | 25 % | 50 % | 100 % | 150 % |
|---|---|---|---|---|
| Riesgo de ruina | 0 % | 0 % | 3,1 % | 40,2 % |
| Capital final mediano | 906,53 € | 820,77 € | 670,51 € | 544,70 € |

## E7 · Operaciones reales de P05 (validación, 20 bps)

| Regla | Operaciones | Profit factor bruto | Profit factor neto | PnL neto |
|---|---|---|---|---|
| Momentum | 15 | 0,57 | 0,16 | −41,30 € |
| Mean reversion | 18 | 1,43 | 0,15 | −31,03 € |
| Periodic long | 41 | 0,61 | 0,09 | −93,72 € |

Con 4 horas de un día no se puede construir una valoración diaria: el Sharpe diario no es calculable.

## Limitaciones

- Datos sintéticos: no representan Bitcoin ni una estrategia validada.
- El coste se modela como un porcentaje fijo del capital diario, no con los fills de P08.
- Las anualizaciones son convenciones; la dependencia temporal y las colas pesadas pueden distorsionarlas.
- El bootstrap solo recombina la muestra: no genera eventos peores que los observados.
- No hay impuestos, financiación, margen real ni riesgo de contraparte.

## Código y pruebas

- Funciones: `src/quantlab/p09/performance.py` → `synthetic_daily`, `validate_daily`, `load_daily_csv`, `equity_curve`, `drawdown`, `performance_metrics`, `trade_metrics`, `cost_sensitivity`, `simulate_ruin`, `ruin_table`, `manual_equity_drawdown`, `recovery_return`, `risk_free_comparison`, `break_even_daily_cost`, `ruin_grid`, `trade_log_to_pnl`, `split_stability`.
- Pruebas: `tests/test_performance.py` (validación, las 12 comprobaciones del cuaderno, reconciliación, costes, ruina y E1–E8).
