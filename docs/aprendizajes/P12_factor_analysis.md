# P12 · Alpha, Beta y factores financieros · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P12_factor_analysis.ipynb`
**Datos de ejemplo:** dos estrategias sintéticas con exposiciones conocidas, un universo ficticio de 6 activos y una regla real sobre BTC/EUR

P09 medía cuánto gana una estrategia; P12 pregunta **por qué** gana. ¿Es habilidad (alpha) o simplemente exposición al mercado y a factores conocidos (beta)? Es la última práctica de fundamentos y cierra el círculo: una "ventaja" solo cuenta si sobrevive a los factores, a la validación fuera de muestra y a los costes.

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `strategy` (r_s) | Retorno diario neto de la estrategia | A, B o la regla real |
| `benchmark_return` (r_m) | Retorno diario del mercado | BTC (sintético o real) |
| `risk_free_return` (r_f) | Tipo libre de riesgo diario | (1,02)^{1/365} − 1 |
| `momentum_factor`, `liquidity_factor` | Factores long-short (diferenciales de retorno) | Sintéticos |
| `TRAIN_FRACTION` | Corte cronológico | 65 % |
| `HAC_LAGS` | Retardos de Newey-West | 5 |
| `ROLLING_WINDOW` | Ventana de la beta móvil | 90 días |
| `PERIODS_PER_YEAR` | Días por año | 365 (cripto) |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Retorno activo | r_s − r_m | A: **6,03 bps/día** | ¿Cuánto le gana al benchmark? |
| Beta | Cov(r_m − r_f, r_s − r_f) / Var(r_m − r_f) | A: **0,84** | ¿Cuánto se mueve con el mercado? |
| Alpha | media(r_s − r_f) − β · media(r_m − r_f) | A, solo mercado: **6,29 bps/día** | ¿Qué parte no explica el mercado? |
| Alpha anual aritmético | α · 365 | 6,29 × 365 = **23,0 %** | El alpha en escala anual (no compuesta) |
| IC del alpha (HAC) | α ± 1,96 · error HAC | A, multifactor: **[−1,23; 3,42] bps** | ¿Es el alpha distinguible de 0? |
| R² | 1 − Var(ε) / Var(r_s − r_f) | A, multifactor: **0,97** | ¿Cuánta varianza explican los factores? |
| Atribución | r_f + α + Σ β_j · f_j + ε | A: 1,98 + 3,99 + 4,69 + 17,74 + 1,84 = **30,24 %** | ¿De dónde sale cada punto? |
| Tracking error | s(r_s − r_m) · √365 | **13,8 %** | ¿Cuánto se separa del benchmark? |
| Information ratio | media(r_s − r_m) · 365 / TE | B: **1,08** | ¿Retorno activo por unidad de desviación? |
| Factor long-short | media(k mejores) − media(k peores), ranking hasta ayer | Momentum: **+10,0 bps/día** (bruto) | ¿Qué rinde la apuesta relativa? |
| Factor neto | factor − 2 · rotación · coste por lado | 20 bps: **−1,7 bps/día** | ¿Sobrevive a los costes? |

## 3. Reglas de validación (antes de calcular)

- `validate_daily_factors` detiene el análisis con valores ausentes o no finitos, días que faltan, menos de 100 días o retornos ≤ −100 %. **No imputa ni rellena con cero.**
- La separación es cronológica, y cada ventana debe ser más larga que los retardos HAC y los parámetros.
- `fit_model` rechaza factores colineales o constantes.
- Los parámetros de desarrollo se **congelan** para la validación; la regresión de validación es solo un diagnóstico.
- La atribución reconcilia cada día exactamente; el residuo medio de desarrollo es 0.
- La beta móvil y los factores long-short solo usan datos pasados: cambiar el retorno de hoy no cambia la decisión de hoy.
- No se mezclan factores sintéticos con datos reales.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Los datos no superan `validate_daily_factors` | El dato no es válido: no se estima nada. |
| Alpha con IC que contiene el 0 | El alpha no es distinguible de cero con ese modelo. |
| Alpha significativo que desaparece al añadir un factor | Era exposición a ese factor, no habilidad. |
| β ≠ 1 | Retorno activo y alpha difieren en (β − 1) · media(r_m − r_f). |
| Alpha de signo distinto en validación | El alpha no es estable. |
| Beta móvil muy variable | Una beta única describe mal la estrategia. |
| Rotación × 2 × coste > retorno bruto del factor | El factor no es rentable neto. |
| Suma de la atribución ≠ retorno | Hay un error en el modelo o en los datos. |

**Lo que NO puede concluir:**

- Que un alpha positivo sea habilidad: puede ser un factor omitido, error de medición o azar.
- Que un R² alto signifique que el modelo es correcto.
- Que una estrategia con alpha positivo gane dinero: la beta puede dominar el resultado.
- Que los factores contemporáneos se pudieran conocer de antemano: la atribución explica, no predice.
- Nada sobre primas reales de cripto a partir de factores artificiales.

## 5. Para qué sirve

- **Separar habilidad de exposición.** Antes de pagar por una estrategia, o de dedicarle capital, hay que saber si su rentabilidad es replicable con factores baratos.
- **Elegir el modelo con criterio.** Ver cómo el alpha de A aparece y desaparece según los factores enseña a desconfiar de un alpha medido contra un único benchmark.
- **Atribuir resultados.** Saber qué parte del retorno viene de cada fuente permite gestionar el riesgo y explicar los resultados.
- **Evaluar fuera de muestra.** Congelar las exposiciones y medir el residuo es la forma honesta de comprobar si el modelo sigue valiendo.
- **Construir factores propios.** Un factor long-short bien construido (sin futuro, con costes) es la base de la investigación sistemática.
- **Cerrar el módulo de fundamentos.** Mercado, ejecución, costes, rentabilidad, eficiencia y factores: con P01–P12 se puede plantear una investigación reproducible de principio a fin.

## Referencias

- Código: [`src/quantlab/p12/factors.py`](../../src/quantlab/p12/factors.py)
- Pruebas: [`tests/test_factors.py`](../../tests/test_factors.py)
- Conclusiones: [conclusiones/P12_factor_analysis.md](../conclusiones/P12_factor_analysis.md)
- Conceptos: [alpha, beta y factores](../conceptos/alpha_beta_factores.md) · [rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) · [eficiencia de mercado](../conceptos/eficiencia_de_mercado.md)
- Aprendizaje anterior: [P11 · Eficiencia del mercado y detección de anomalías](P11_market_efficiency.md)
