# Construcción de factores: scores, carteras long-short, costes y Fama-French

**Familia:** factores y carteras · **Visto en:** P16 · **Código:** `src/quantlab/p16/factor_construction.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Score | `size`, `value`, `momentum`… | Característica conocida antes de invertir | Por qué se ordena a los activos. |
| Momentum 12-2 | `momentum` | ∏(1 + r) − 1 de t−12 a t−2 | Tendencia pasada, sin el último mes. |
| Low Vol | `low_vol` | −σ(r) de t−6 a t−1 | Activos tranquilos frente a nerviosos. |
| Iliquidez de Amihud | `illiquidity` | media(\|r_d\| / volumen en USD_d) del mes anterior | Cuánto mueve el precio cada dólar negociado. |
| Pesos long-short | `long_short_weights` | +1/k al k superior, −1/k al inferior; k = ⌊n · q⌋ | Neto 0, bruto 2. |
| Retorno del factor | `gross` | F_t = Σ w_i r_i | Spread entre extremos. |
| Rotación | `turnover` | Σ\|w_t − w_{t−1}\| | Cuánto nominal se negocia al rebalancear. |
| Coste | `cost` | c · rotación | Lo que se paga por rebalancear (c por lado). |
| Coste de equilibrio | `breakeven_cost_bps` | media bruta / rotación media | Coste máximo con media neta ≥ 0. |
| t HAC | `t_hac` | Media / error Newey-West (3 retardos) | Significancia con autocorrelación. |
| Bonferroni / BH | `multiple_testing` | p · m / control de la FDR | Corrección por muchas pruebas. |
| Modelo FF | `fit_model` | r − RF = α + Σ β_k f_k + ε | Alpha respecto a factores oficiales. |
| Carry de perpetuo | `perp_carry_score` | −media(funding observado) · 3 · 365 | Lo que cobra o paga el lado largo. |

## Ideas clave

- **Un score solo vale si se conocía al decidir:** `available_at < month`, y momentum salta el mes t − 1.
- **Neto 0 no es riesgo 0:** el long-short tiene exposición bruta 2x, préstamo y garantías.
- **Un mes con un retorno elegido desconocido es desconocido**, no cero.
- **La rotación decide el coste:** Low Vol rota ~1 vez su nominal al mes y pierde ¾ de su retorno con 15 bps.
- **Scores constantes = cartera fija:** no rota, pero tampoco responde a información nueva.
- **Correlación baja ≠ independencia:** carry, con correlación −0,13 con value, hereda toda su media por una inclinación casual hacia value.
- **La corrección por multiplicidad no detecta factores que imitan a otros:** BH "descubre" carry.
- **Un alpha depende del modelo:** omitir factores crea alpha; añadirlos lo elimina.
- **En cripto no hay value ni quality:** se eliminan en lugar de inventarlos.

## Validación

- `validate_panel`: meses en el día 1, `available_at < month`, sin duplicados, capitalización > 0, retornos ≥ −100 %, un RF por mes.
- `summarize` no calcula HAC si hay huecos entre meses; `fit_model` exige ≥ 24 meses consecutivos.
- `read_ff_monthly` solo lee filas YYYYMM y trata −99,99 como ausente.
- `crypto_monthly_panel` deja NaN el retorno si falta el cierre del último día del mes.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Pesos | scores 1, 2, 3, 4; q = 30 % | k = 1: −1 en A, +1 en D; factor 4 % − 1 % = **3 %** |
| Coste de equilibrio | Value: 122,1 bps brutos, rotación 0,209 | **583 bps** por lado |
| Swap | 1.000.000 €, fijo 4 %, variable 5 % | Pagador fijo cobra **10.000 €** |
| Basis | futuro 61.500, spot 60.000, 90 días | **10,14 %** anual |

## Código

```python
from quantlab.p16.factor_construction import synthetic_panel, validate_panel, add_scores, factor_table, period_summary

panel, mom, lowvol, months = add_scores(validate_panel(synthetic_panel(42)))
details, net, gross = factor_table(panel, cost_bps=15, fraction=.30)
dev, val = period_summary(net, months[int(len(months) * .65)])
```

Relacionado: [alpha_beta_factores.md](alpha_beta_factores.md) · [costes_de_ejecucion.md](costes_de_ejecucion.md) · [eficiencia_de_mercado.md](eficiencia_de_mercado.md) · [derivados_perpetuos.md](derivados_perpetuos.md)
