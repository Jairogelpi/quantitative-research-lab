# P12 · Alpha, Beta y factores financieros · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P12_factor_analysis.ipynb`
**Datos:** 900 días sintéticos (semilla 42) con mercado, momentum, liquidez y dos estrategias (A sin alpha, B con 4,5 bps diarios), un universo ficticio de 6 activos, y una regla real de momentum sobre 720 velas diarias de Kraken BTC/EUR (19-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | A (alpha verdadero 0) muestra 6,29 bps diarios de alpha (p = 0,035) con el modelo de mercado y 1,09 bps (p = 0,36) con tres factores. | `model_table` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 2 | B (alpha verdadero 4,5 bps) estima 5,59 bps en desarrollo y 5,50 bps (p = 0,002) en la regresión diagnóstica de validación. | `frozen_validation` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 3 | Las dos estrategias pierden en validación (A −27,2 %, B −16,1 %) porque el mercado cayó un 26,8 % y su beta es 0,75. | `frozen_validation` | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 4 | El retorno activo medio difiere del alpha exactamente en (β − 1) · media(r_m − r_f): −0,27 bps diarios en desarrollo. | E2 · `active_vs_alpha` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 5 | Quitar el factor momentum fabrica un alpha "significativo" en A (5,74 bps, p = 0,037) y baja el R² de 0,97 a 0,85. | E3 · `omitted_factor_table` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 6 | En A, el momentum aporta 17,7 de los 30,2 puntos de retorno anual aritmético; la atribución reconcilia exactamente. | E4 · `annualized_attribution` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 7 | Con una exposición constante, la beta móvil de 30 días oscila entre 0,66 y 1,03; la de 180 días, entre 0,81 y 0,89. | E5 · `rolling_beta` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 8 | El factor de reversión es el momentum con el signo cambiado, pero paga la misma rotación (29 % diario): con 20 bps por lado, ninguno de los dos es positivo. | E6 · `long_short_factor` · `factor_after_costs` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 9 | La regla real de momentum sobre BTC/EUR perdió un 27,7 % frente al −38,8 % de BTC por estar invertida el 43 % del tiempo (beta 0,27), no por alpha. | E7 · `daily_rule_returns` | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 10 | Su alpha cambia de signo entre desarrollo (−5,6 bps, p = 0,23) y validación (+2,1 bps, p = 0,78), y su beta móvil va de 0,11 a 0,82. | E7 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |

## Modelos en desarrollo

| Estrategia | Modelo | Alpha diario | p-valor | Beta | R² |
|---|---|---|---|---|---|
| A | Mercado | 6,29 bps | 0,035 | 0,84 | 0,83 |
| A | Multifactor | 1,09 bps | 0,356 | 0,75 | 0,97 |
| B | Mercado | 10,79 bps | 0,0003 | 0,84 | 0,83 |
| B | Multifactor | 5,59 bps | < 0,0001 | 0,75 | 0,97 |

## E7 · Regla real sobre Kraken BTC/EUR (velas diarias)

| | Desarrollo (453 días) | Validación (245 días) |
|---|---|---|
| Retorno de la regla (neto, 20 bps) | −29,3 % | +2,2 % |
| Retorno de BTC/EUR | −33,7 % | −7,6 % |
| Alpha diario | −5,64 bps (p = 0,23) | +2,08 bps (p = 0,78) |
| Beta / R² | 0,27 / 0,27 | — |

## Limitaciones

- Los factores son artificiales; no representan primas empíricas de cripto.
- No hay factores reales disponibles: la regla real solo se evalúa contra el mercado.
- El tipo libre de riesgo del 2 % es un supuesto.
- La atribución es aritmética; el alpha anualizado es una extrapolación lineal.
- Los errores HAC no corrigen factores omitidos, selección de modelos ni muestras pequeñas.

## Código y pruebas

- Funciones: `src/quantlab/p12/factors.py` → `daily_risk_free`, `synthetic_factor_data`, `read_daily`, `validate_daily_factors`, `chronological_split`, `fit_model`, `model_table`, `attribution`, `frozen_validation`, `rolling_beta`, `synthetic_universe`, `long_short_factor`, `factor_after_costs`, `manual_alpha_beta`, `active_vs_alpha`, `omitted_factor_table`, `annualized_attribution`, `daily_rule_returns`.
- Pruebas: `tests/test_factors.py` (validación, Jensen con parámetros conocidos, colinealidad, referencia sintética, reconciliación, validación congelada, beta móvil sin futuro, factor sin futuro y E1–E7).
