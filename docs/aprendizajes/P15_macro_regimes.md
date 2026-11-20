# P15 · Regímenes macroeconómicos y diversificación · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P15_macro_regimes.ipynb`
**Datos de ejemplo:** retornos semanales sintéticos con un histórico macro ficticio, y retornos reales de P14

P14 comparaba activos uno a uno. P15 los junta en una **cartera**: cuánto riesgo reduce la diversificación, qué riesgo queda y si las relaciones entre activos cambian según el entorno de tipos de interés. Y añade una regla clave para cualquier dato macro: unirlo por cuándo **se supo**, no por el mes al que se refiere.

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `returns` | Retornos semanales en EUR (viernes) | BTC, Acciones, Bonos, Oro |
| `WEIGHTS` | Pesos fijos, elegidos a priori | 25 / 35 / 30 / 10 % |
| `available_at` | Hora en que se conoció cada estado macro (UTC) | día 11 de cada mes, 13:00 |
| `policy_rate_pct`, `inflation_yoy_pct` | Tipo oficial e inflación interanual | % |
| `yield_2y_pct`, `yield_10y_pct` | Rendimientos a 2 y 10 años | % |
| `balance_usd_bn` | Balance del banco central | miles de millones USD |
| `MAX_AGE_DAYS` | Antigüedad máxima del estado macro | 75 días |
| `SPLIT` | Corte cronológico | 65 % |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Retorno de cartera | wᵀr | — | ¿Cuánto rindió la cartera? |
| Volatilidad de cartera | √(wᵀΣw) · √52 | **15,1 %** (simulación) | ¿Cuánto riesgo tiene? |
| Contribución al riesgo | w_i · (Σw)_i / σ_p | BTC: **9,69 pp de 15,1** | ¿Quién aporta el riesgo? |
| Varianza de 2 activos | w²σ²_a + (1−w)²σ²_b + 2w(1−w)ρσ_aσ_b | 50/50, ρ = 0: **0,0456** | ¿Cuánto diversifican dos activos? |
| Beta y varianza explicada | OLS de BTC sobre acciones | Real: β **0,98**, R² **5,5 %** | ¿Cuánto riesgo es común? |
| Curva de diversificación | √(β²σ²_f + σ²_ε / N) | N → ∞: **2 %** | ¿Qué riesgo no desaparece? |
| Tipo real aproximado | tipo − inflación interanual | de **−0,3 a 2,8 pp** | ¿Tipos restrictivos o no? |
| Pendiente | 100 · (y₁₀ − y₂) | Subidas: **−40 bps** | ¿Curva invertida? |
| Régimen | cambio del tipo > / < ±0,01 pp | Subida / Estable / Bajada | ¿En qué fase está la política? |
| Correlación por régimen | Corr(acciones, bonos) dentro de cada régimen | Subida: **+0,80** (validación) | ¿Protegen los bonos? |
| Diferencia de correlaciones | z(r₁) − z(r₂) ± 1,96 · √(1/(n₁−3) + 1/(n₂−3)) | **[1,16; 2,07]** | ¿Es la diferencia distinta de 0? |

## 3. Reglas de validación (antes de calcular)

- Retornos: al menos 80 viernes consecutivos y únicos, finitos y > −100 %.
- Macro: `available_at` en UTC, sin duplicados, valores finitos y al menos 2 actualizaciones.
- **Unión point-in-time:** cada retorno usa el último estado con `available_at` ≤ lunes de la semana anterior, y con una antigüedad ≤ 75 días; si no hay, el régimen queda desconocido (no se rellena).
- Separación cronológica; los pesos y los umbrales se fijan antes de mirar la validación.
- Grupos con menos de 12 semanas no se comparan.
- Sin vintages verificados no se construye un histórico macro: se registra el bloqueo.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Correlaciones < 1 entre activos | La volatilidad de la cartera es menor que la media ponderada. |
| ρ = −1 y w_A = σ_B / (σ_A + σ_B) | La varianza de la cartera es 0. |
| Contribución de un activo ≫ su peso | El riesgo está concentrado en ese activo. |
| N activos con un factor común | La volatilidad converge a β · σ_f, no a 0. |
| `available_at` posterior a la decisión | Ese estado no se puede usar todavía. |
| Estado con más antigüedad que el máximo | El régimen se considera desconocido. |
| Rendimiento a 10 años < a 2 años | La curva está invertida. |

**Lo que NO puede concluir:**

- Que una curva invertida anuncie una recesión.
- Que el balance identifique QE/QT por sí solo.
- Que un régimen cause los retornos: puede coincidir con otros factores.
- Que la diversificación funcione igual en todos los entornos.
- Nada sobre mercados reales a partir de regímenes programados, ni con una serie macro revisada en lugar de point-in-time.

## 5. Para qué sirve

- **Construir carteras con criterio.** Saber cuánto riesgo aporta cada activo evita carteras que parecen diversificadas pero dependen de uno solo.
- **Distinguir el riesgo que se puede diversificar del que no.** El riesgo del factor común solo se reduce con activos que no dependan de él.
- **Prepararse para los cambios de régimen.** Las correlaciones cambian, y lo hacen cuando más importa.
- **Trabajar con datos macro sin trampas.** Unir por disponibilidad y con vintages es la única forma honesta de usar datos que se publican tarde y se revisan.
- **Saber cuándo parar.** Sin datos point-in-time, la respuesta correcta es registrar el bloqueo, no inventar fechas.

## Referencias

- Código: [`src/quantlab/p15/regimes.py`](../../src/quantlab/p15/regimes.py)
- Pruebas: [`tests/test_regimes.py`](../../tests/test_regimes.py)
- Conclusiones: [conclusiones/P15_macro_regimes.md](../conclusiones/P15_macro_regimes.md)
- Conceptos: [regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) · [multiactivo y capitalización](../conceptos/multiactivo_y_capitalizacion.md) · [valoración y macro](../conceptos/valoracion_y_macro.md)
- Aprendizaje anterior: [P14 · Laboratorio multiactivo y capitalización](P14_multi_asset_analysis.md)
