# Regímenes y diversificación: riesgo de cartera, beta y unión point-in-time

**Familia:** gestión de carteras y macro · **Visto en:** P15 · **Código:** `src/quantlab/p15/regimes.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Retorno de cartera | `portfolio_return` | r_p = wᵀr | Retorno con pesos fijos rebalanceados cada semana. |
| Volatilidad de cartera | `portfolio_risk` | σ_p = √(wᵀΣw) | Riesgo conjunto, con correlaciones. |
| Contribución al riesgo | `contribution` | w_i · (Σw)_i / σ_p | Cuánto aporta cada activo; suman σ_p. |
| Varianza de dos activos | `two_asset_variance` | w²σ²_a + (1 − w)²σ²_b + 2w(1 − w)ρσ_aσ_b | Solo es 0 con ρ = −1 y pesos σ_b / (σ_a + σ_b). |
| Riesgo sistemático / residual | `systematic_decomposition` | Var(α + βx) + Var(ε) = Var(y) | Parte explicada por un factor y parte propia. |
| Curva de diversificación | `diversification_curve` | σ²_p = β²σ²_f + σ²_ε / N | El riesgo del factor común no desaparece. |
| Tipo real aproximado | `real_policy_proxy_pct` | tipo oficial − inflación interanual | Ex post, no expectativa. |
| Régimen de tipos | `regime` | Subida / Bajada / Estable según el cambio (±0,01 pp) | Estado monetario simplificado. |
| Régimen de balance | `balance_regime` | Expansión / Contracción / Estable (±0,1 %) | Proxy, no identifica QE/QT. |
| Unión point-in-time | `align_panel` | `merge_asof` hacia atrás con `available_at` ≤ decisión y antigüedad máxima | Sin datos futuros. |

## Ideas clave

- **Peso ≠ riesgo:** BTC con un 25 % del peso aporta el 64 % (simulación) o el 77 % (real) del riesgo de la cartera.
- **Diversificar reduce el riesgo idiosincrático, no el sistemático:** la volatilidad converge al riesgo del factor común.
- **Las correlaciones cambian por régimen:** acciones–bonos pasa de negativa a positiva durante las subidas de tipos (simulación), justo cuando más se necesita la protección.
- **Unir por disponibilidad, no por referencia:** un dato de marzo publicado el 15 de abril, unido por referencia, se "conoce" 7 semanas antes de existir.
- **Antigüedad máxima:** un umbral demasiado estricto descarta estados válidos (de 3 a 8 semanas sin régimen con 30 días).
- **La serie revisada no es point-in-time:** hacen falta vintages (ALFRED) y horas de publicación verificadas.
- **Curva invertida y balance son señales, no pruebas** de recesión ni de QE/QT.

## Validación

- `validate_returns`: al menos 80 viernes consecutivos y únicos, retornos finitos y > −100 %.
- `validate_macro`: `available_at` en UTC sin duplicados, al menos 2 actualizaciones y valores finitos.
- `align_panel`: `available_at` ≤ `decision_at` (lunes de la semana anterior) y antigüedad ≤ 75 días; sin estado conocido, el régimen queda desconocido.
- Grupos con menos de 12 semanas no se comparan.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Dos activos, 50/50 | σ = 40 % y 15 %, ρ = +1 / 0 / −1 | 27,5 % / 21,4 % / 12,5 % |
| Peso de varianza cero | σ_a = 40 %, σ_b = 15 %, ρ = −1 | **27,3 %** en A |
| Cartera 25/35/30/10 (simulación) | — | 15,1 % frente a 20,5 % de media ponderada |

## Código

```python
from quantlab.p15.regimes import (synthetic_inputs, validate_returns, validate_macro, macro_indicators,
                                  align_panel, portfolio_risk, regime_correlations, correlation_difference)

returns, macro = synthetic_inputs()
macro = macro_indicators(validate_macro(macro))
panel, cutoff = align_panel(validate_returns(returns), macro, weights, max_age_days=75)
regime_correlations(panel, "Acciones", "Bonos")
```

Relacionado: [multiactivo_y_capitalizacion.md](multiactivo_y_capitalizacion.md) · [valoracion_y_macro.md](valoracion_y_macro.md) · [alpha_beta_factores.md](alpha_beta_factores.md)
