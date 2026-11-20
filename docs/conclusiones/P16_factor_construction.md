# P16 · Construcción de factores financieros · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P16_factor_construction.ipynb`
**Datos:** panel mensual sintético de 60 activos y 120 meses (semilla 42, primas programadas solo en value y size), ficheros oficiales de Ken French (CRSP 2026-09) y precios diarios de Yahoo Finance de 20 criptomonedas, SPY y GLD (descarga del 20-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | Value, con prima programada, es el único factor con t > 2 en los dos periodos (+119,0 y +127,9 bps al mes). | `period_summary` | [Construcción de factores](../conceptos/construccion_de_factores.md) |
| 2 | Size, también programado, cae de +74,3 a +23,9 bps (t = 0,95) en validación: una prima real puede no verse en 42 meses. | `period_summary` · E8 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 3 | Carry no tiene prima programada y sale negativo (−67,5 bps, t = −2,61): hereda −33 bps de su inclinación casual hacia value. | E5 · `spanning_alpha` | [Construcción de factores](../conceptos/construccion_de_factores.md) |
| 4 | La correlación de retornos carry–value es solo −0,13 y value/size explican el 2 % de su varianza: correlación baja no es independencia. | E5 | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 5 | Low Vol rota 1,06 veces su nominal al mes y los costes le quitan 15,9 de sus 20,8 bps brutos; su coste de equilibrio es 41 bps. | §8.2 · E4 | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 6 | Value aguantaría hasta 583 bps por lado: rota poco (0,209) y su spread es grande. | E4 · `breakeven_cost_bps` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 7 | Pasar de terciles a quintiles sube el spread (value 119 → 144 bps; size 68 → 99) y casi duplica la rotación de value, no la de size. | E3 · `quantile_comparison` | [Construcción de factores](../conceptos/construccion_de_factores.md) |
| 8 | Con 3 factores, una estrategia sin alpha muestra −28,3 bps (p = 0,09); con los 5, −10,9 (p = 0,23): el alpha depende del modelo. | §9 · `fit_model` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 9 | Con BH a 8 factores en validación sobreviven value y carry; carry es un falso descubrimiento que la corrección no puede detectar. | E8 · `multiple_testing` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 10 | SPY sobre FF oficial: alpha +0,6 bps (p = 0,80), R² 0,996. GLD: R² 0,03. | E7 | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 11 | En 20 criptomonedas (2018-12 a 2026-09), ni momentum, ni Low Vol, ni liquidity sobreviven: liquidity tiene p = 0,03 en desarrollo, BH 0,10, y t = 0,36 en validación. | E7 | [Construcción de factores](../conceptos/construccion_de_factores.md) |
| 12 | El score carry de un perpetuo solo usa fundings ya liquidados antes de la formación; el estimado se informa aparte. | E6 · `perp_carry_score` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |

## Validación (simulación, neto de 15 bps)

| Factor | Dev. (bps) | t | Val. (bps) | t | p BH (val.) |
|---|---|---|---|---|---|
| Size | +74,3 | 3,88 | +23,9 | 0,95 | 0,46 |
| Value | +119,0 | 5,42 | +127,9 | 4,55 | 0,00 |
| Quality | −11,3 | −0,54 | +23,3 | 0,60 | 0,62 |
| Momentum | +41,4 | 2,14 | +37,3 | 1,16 | 0,40 |
| Low Vol | +27,6 | 1,51 | +4,9 | 0,20 | 0,84 |
| Carry | −36,7 | −2,21 | −67,5 | −2,61 | 0,04 |
| Liquidity | +23,5 | 1,17 | +31,2 | 1,41 | 0,32 |
| Investment | +1,8 | 0,08 | +52,8 | 1,51 | 0,32 |

## E7 · Universo cripto (94 meses, corte en enero de 2024)

| Factor | Dev. (bps) | t | Val. (bps) | t | Rotación |
|---|---|---|---|---|---|
| Momentum 12-2 | +114,9 | 0,53 | +175,9 | 0,87 | 0,83 |
| Low Vol | −386,6 | −1,54 | −119,7 | −0,34 | 0,92 |
| Liquidity (Amihud) | +938,9 | 2,13 | +129,3 | 0,36 | 0,37 |

## Limitaciones

- Ordenaciones univariantes y equiponderadas; no replican SMB, HML, RMW ni CMA.
- Costes fijos de 15 bps por lado, sin préstamo de títulos, funding, impuestos ni capacidad.
- Universo cripto con sesgo de supervivencia (elegido hoy) y datos agregados de Yahoo, no ejecutables.
- La simulación tiene primas programadas: no es evidencia de primas reales.

## Código y pruebas

- Funciones: `src/quantlab/p16/factor_construction.py` → `synthetic_panel`, `validate_panel`, `add_scores`, `long_short_weights`, `build_factor`, `market_excess`, `factor_table`, `summarize`, `period_summary`, `multiple_testing`, `read_ff_monthly`, `download_ff`, `fit_model`, `model_summary`, `derivative_pnl`, `swap_net_flow`, `annualized_basis`, `monthly_returns`, `download_daily`, `crypto_monthly_panel`, `manual_long_short`, `momentum_12_2`, `quantile_comparison`, `breakeven_cost_bps`, `spanning_alpha`, `perp_carry_score`.
- Pruebas: `tests/test_factor_construction.py` (validación, scores sin futuro, pesos, costes, HAC, multiplicidad, lector FF, derivados, panel cripto y E1–E6).
