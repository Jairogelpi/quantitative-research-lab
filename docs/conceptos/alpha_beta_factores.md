# Alpha, beta y factores: Jensen, multifactor, atribución y factores long-short

**Familia:** atribución de rentabilidad · **Visto en:** P12 · **Código:** `src/quantlab/p12/factors.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Retorno activo | `active_bps` | r_s − r_m | Cuánto le gana la estrategia al benchmark, sin ajustar por exposición. |
| Retorno excedente | — | r_s − r_f | Lo que rinde por encima del activo sin riesgo. |
| Modelo de Jensen | `fit_model` | r_s − r_f = α + β · (r_m − r_f) + ε | Separa exposición al mercado (β) y componente propio (α). |
| Beta | `beta` | Cov(r_m − r_f, r_s − r_f) / Var(r_m − r_f) | Sensibilidad al exceso de retorno del mercado. |
| Alpha | `alpha_daily_bps` | media(r_s − r_f) − β · media(r_m − r_f) | Intercepto medio que el modelo no atribuye a los factores. |
| Errores HAC | `cov_type="HAC"` | Newey-West con `HAC_LAGS` retardos | Inferencia robusta a heterocedasticidad y autocorrelación. |
| Multifactor | `model_table` | r_s − r_f = α + Σ β_j · f_j + ε | Añade momentum, liquidez u otros factores. |
| Atribución | `attribution` | r_s = r_f + α + Σ β_j · f_j + ε, término a término | De dónde sale cada punto básico (suma aritmética exacta). |
| Validación congelada | `frozen_validation` | Parámetros de desarrollo aplicados a la validación | Qué parte no explica el modelo fuera de muestra. |
| Tracking error | `tracking_error_annual_pct` | s(r_s − r_m) · √A | Dispersión del retorno activo. |
| Information ratio | `information_ratio` | media(r_s − r_m) · A / tracking error | Retorno activo por unidad de tracking error. |
| Beta móvil | `rolling_beta` | Beta con las últimas N observaciones | ¿Es estable la exposición? |
| Factor long-short | `long_short_factor` | Media de los k mejores − media de los k peores (ranking hasta ayer) | Un diferencial de retornos, no una cartera financiada. |

## Ideas clave

- **Omitir un factor fabrica alpha:** A (alpha 0) mostró 6,29 bps diarios (p = 0,035) con solo el mercado, y 1,09 bps (p = 0,36) con momentum y liquidez.
- **Retorno activo = α + (β − 1) · media(r_m − r_f):** solo coinciden si β = 1.
- **Un R² alto no valida el modelo:** añadir factores siempre lo sube; lo que importa es el intercepto fuera de muestra.
- **Alpha positivo y pérdidas pueden convivir:** B mantuvo su alpha (5,5 bps) y perdió un 16 % porque el mercado cayó.
- **La atribución es aritmética:** suma exacta de medias diarias, no retorno compuesto.
- **La beta móvil con ventana corta es ruidosa:** con 30 días varía de 0,66 a 1,03 aunque la exposición verdadera sea constante.
- **Factores sin futuro:** la cartera de hoy se elige con el retorno acumulado hasta ayer.
- **La rotación cuesta:** con 20 bps por lado, un factor que rota un 29 % al día pierde unos 12 bps diarios.

## Validación

- `validate_daily_factors` se detiene con valores no finitos, días que faltan, menos de 100 días o retornos ≤ −100 %. No imputa ni rellena.
- `chronological_split` exige ventanas más largas que los retardos HAC y los parámetros.
- `fit_model` rechaza factores colineales o constantes.
- La atribución reconcilia exactamente cada día; en desarrollo, el residuo medio es 0.
- `long_short_factor` usa `shift(1)`: cambiar el retorno de hoy no cambia la cartera de hoy.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Jensen | Serie de juguete: 0,001 + 1,5 · x | α = **0,001**, β = **1,5** |
| Tipo diario | 2 % anual, 365 días | (1,02)^{1/365} − 1 ≈ **0,54 bps** |
| Atribución A (anual aritmética) | rf 1,98 + α 3,99 + mercado 4,69 + momentum 17,74 + liquidez 1,84 | **30,24 %** |

## Código

```python
from quantlab.p12.factors import (synthetic_factor_data, validate_daily_factors, chronological_split,
                                  model_table, attribution, frozen_validation, rolling_beta,
                                  long_short_factor, factor_after_costs, daily_rule_returns)

daily = validate_daily_factors(synthetic_factor_data(), ["A", "B"])
train, test = chronological_split(daily, .65, hac_lags=5, n_factors=3)
specs = {"Mercado": ["market_excess"], "Multifactor": ["market_excess", "momentum_factor", "liquidity_factor"]}
table, models = model_table(train, ["A", "B"], specs)
validation, parts = frozen_validation(test, ["A", "B"], models, "Multifactor", specs["Multifactor"])
```

Relacionado: [rentabilidad_y_riesgo.md](rentabilidad_y_riesgo.md) · [eficiencia_de_mercado.md](eficiencia_de_mercado.md) · [momentum_y_reversion.md](momentum_y_reversion.md)
