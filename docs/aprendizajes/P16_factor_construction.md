# P16 · Construcción de factores financieros · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P16_factor_construction.ipynb`
**Datos de ejemplo:** panel mensual sintético de 60 activos, factores oficiales de Ken French y 20 criptomonedas de Yahoo Finance

En P12 estimábamos **exposiciones** a factores con regresiones. P16 hace lo contrario: **construye** los factores. Se ordena a los activos por una característica conocida de antemano, se compran los mejores, se venden los peores y se mide si ese spread gana dinero después de costes y fuera de muestra.

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `month` | Primer día del mes de tenencia | 2015-01 a 2024-12 |
| `available_at` | Cuándo se conocían las características | día anterior a `month` |
| `market_cap`, `book_to_market`, `roa`… | Características contables | — |
| `asset_return`, `rf` | Retorno del mes y tipo libre de riesgo (decimal) | RF 0,2 % mensual |
| `QUANTILE` | Fracción comprada y vendida | 30 % |
| `COST_BPS` | Coste por lado y por unidad de nominal | 15 bps |
| `TRAIN_SHARE` | Corte cronológico | 65 % (julio de 2021) |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Momentum 12-2 | ∏(1 + r_{t−12..t−2}) − 1 | A000, jul-2017: **+9,37 %** | ¿Qué tendencia traía? |
| Low Vol | −σ(r_{t−6..t−1}) | — | ¿Es tranquilo? |
| k por lado | ⌊n · q⌋ | 60 · 0,30 = **18** | ¿Cuántos activos en cada extremo? |
| Pesos | ±1/k | ±1/18 | Neto 0, bruto 2 |
| Factor | Σ w_i r_i | 4 % − 1 % = **3 %** (E1) | ¿Cuánto rinde el spread? |
| Rotación | Σ\|w_t − w_{t−1}\| | Low Vol: **1,06** al mes | ¿Cuánto se negocia? |
| Coste | c · rotación | 15 bps · 1,06 = **15,9 bps** | ¿Cuánto se paga? |
| Coste de equilibrio | media bruta / rotación media | Value: **583 bps** | ¿Qué coste aguanta? |
| t HAC | media / error Newey-West | Value val.: **4,55** | ¿Es distinto de 0? |
| BH | p ordenados frente a α · i / m | Carry: **0,036** | ¿Sobrevive a muchas pruebas? |
| Alpha FF | constante de r − RF sobre los factores | SPY: **+0,6 bps** (p = 0,80) | ¿Hay rentabilidad no explicada? |
| Amihud | media(\|r_d\| / volumen USD_d) · 10⁹ | — | ¿Es ilíquido? |
| P&L de una call | max(S_T − K, 0) − p | S_T = 75.000: **+13.000 €** | ¿Cuánto gana la opción? |
| Swap | N · (r_var − r_fijo) · Δt | 1 M · (5 % − 4 %) = **+10.000 €** | ¿Qué paga el pagador fijo? |

## 3. Reglas de validación (antes de calcular)

- Las características deben conocerse **antes** del mes (`available_at < month`); si no, se detiene.
- Sin duplicados activo-mes, capitalización > 0, retornos ≥ −100 % y un RF por mes.
- El calendario se reindexa completo: un mes ausente no es un retorno 0.
- Si falta el retorno de un activo elegido, el mes del factor es **desconocido**.
- HAC solo con meses consecutivos; FF con al menos 24 meses comunes.
- El cuantil, los costes y la hipótesis se fijan **antes** de mirar la validación.
- En cripto, value, quality, carry, investment y size se **eliminan**: no se inventan.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Pesos ±1/k en los extremos | Exposición neta 0 y bruta 2. |
| Un score calculado con datos hasta t − 2 | No depende del retorno del mes t. |
| Rotación × coste mayor que la media bruta | La media neta es negativa. |
| Un score constante en el tiempo | La cartera no rota tras la apertura. |
| Un retorno elegido ausente | El factor de ese mes es desconocido. |
| Un factor añadido al modelo con exposición real | El alpha cambia. |
| p ajustado por BH < 0,05 | La prueba sobrevive a la multiplicidad (no que el factor sea causal). |

**Lo que NO puede concluir:**

- Que un factor tenga una prima real a partir de datos sintéticos con primas programadas.
- Que dos factores sean independientes porque sus retornos se correlacionan poco.
- Que BH elimine factores que imitan a otros (carry sobrevive).
- Que un factor cripto funcione con un universo elegido hoy (sesgo de supervivencia).

## 5. Para qué sirve

- **Construir señales sin trampas.** El score se fija antes de invertir y el mes ausente no se rellena.
- **Saber qué factores sobreviven a los costes.** La rotación decide, y Low Vol pierde ¾ de su retorno.
- **Detectar falsos factores.** Una característica casualmente correlacionada con otra con prima hereda esa prima.
- **Medir el alpha con los factores oficiales.** SPY con R² 0,996 confirma que el lector y la regresión funcionan.
- **Trasladar factores a cripto con honestidad.** Se quedan solo los que tienen sentido, y ninguno sobrevive a la validación.

## Referencias

- Código: [`src/quantlab/p16/factor_construction.py`](../../src/quantlab/p16/factor_construction.py)
- Pruebas: [`tests/test_factor_construction.py`](../../tests/test_factor_construction.py)
- Conclusiones: [conclusiones/P16_factor_construction.md](../conclusiones/P16_factor_construction.md)
- Conceptos: [construcción de factores](../conceptos/construccion_de_factores.md) · [alpha, beta y factores](../conceptos/alpha_beta_factores.md)
- Aprendizaje anterior: [P15 · Regímenes macroeconómicos y diversificación](P15_macro_regimes.md)
