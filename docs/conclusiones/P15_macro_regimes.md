# P15 · Regímenes macroeconómicos y diversificación · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P15_macro_regimes.ipynb`
**Datos:** retornos semanales sintéticos de 2020 a 2025 con un histórico macro ficticio (semilla 42), y retornos reales de P14 (Yahoo Finance, 2021–2025)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | La cartera 25/35/30/10 tiene una volatilidad del 15,1 % frente al 20,5 % de la media ponderada (simulación); con datos reales, 17,2 % frente a 24,0 %. | `portfolio_risk` · E7 | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 2 | BTC, con el 25 % del peso, aporta el 64 % del riesgo (simulación) y el 77 % (real). Con un 40 % de peso, el 81 %. | `portfolio_risk` · E2 | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 3 | Con datos reales, BTC tiene una beta de 0,98 frente a las acciones, pero estas explican solo el 5,5 % de su varianza. | `systematic_decomposition` · E7 | [Alpha, beta y factores](../conceptos/alpha_beta_factores.md) |
| 4 | La varianza de dos activos solo es 0 con ρ = −1 y pesos σ_b / (σ_a + σ_b) (27,3 % en el ejemplo). | E1 · `two_asset_variance` | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 5 | Con un factor común, la volatilidad de una cartera equiponderada converge al 2 % del factor por muchos activos que se añadan. | E3 · `diversification_curve` | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 6 | En las subidas de tipos, la correlación acciones–bonos se vuelve positiva (+0,55 en desarrollo, +0,80 en validación) y es negativa en el resto. | `regime_correlations` · E8 | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 7 | Los retornos medios por régimen no son estables entre periodos: la fase "Estable" gana en desarrollo y pierde en validación. | `regime_summary` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 8 | Una publicación retrasada, unida por la fecha de referencia, se usaría 7 semanas antes de existir. | E6 · `delayed_publication_demo` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 9 | Bajar la antigüedad máxima de 75 a 30 días deja sin régimen 8 semanas en lugar de 3. | E6 · `align_panel` | [Regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) |
| 10 | El histórico macro point-in-time no se pudo construir: la API de ALFRED requiere una clave y las horas de publicación deben verificarse en fuentes primarias. | E7 | [Validación](../conceptos/validacion_de_datos.md) |

## Por régimen (simulación)

| Periodo | Régimen | Semanas | Cartera (semanal) | Correlación acciones–bonos |
|---|---|---|---|---|
| Desarrollo | Subida | 74 | −0,055 % | +0,55 |
| Desarrollo | Estable | 74 | +0,174 % | −0,38 |
| Desarrollo | Bajada | 52 | +0,013 % | −0,25 |
| Validación | Subida | 27 | −0,414 % | +0,80 |
| Validación | Estable | 31 | −0,326 % | −0,44 |
| Validación | Bajada | 52 | +0,086 % | −0,52 |

## Bloqueo del E7

| Dato necesario | Fuente | Estado |
|---|---|---|
| Vintages de FEDFUNDS, CPIAUCSL, DGS2, DGS10 y WALCL | ALFRED (API de FRED) | Requiere una clave de API personal no configurada |
| Horas de publicación | BLS, Fed (H.4.1), Tesoro | A verificar en fuente primaria |
| Decisiones de tipos con hora | Comunicados del FOMC | Sin serie descargable |

## Limitaciones

- Los regímenes y los efectos sintéticos están programados: no son evidencia sobre los mercados reales.
- El intervalo de Fisher supone semanas independientes.
- No se modelan costes de rebalanceo, impuestos ni el retraso real de los datos.

## Código y pruebas

- Funciones: `src/quantlab/p15/regimes.py` → `synthetic_inputs`, `validate_returns`, `validate_macro`, `macro_indicators`, `align_panel`, `portfolio_risk`, `systematic_decomposition`, `regime_summary`, `regime_correlations`, `two_asset_variance`, `zero_variance_weight`, `diversification_curve`, `balance_vs_rates`, `delayed_publication_demo`, `correlation_difference`.
- Pruebas: `tests/test_regimes.py` (validación, indicadores, unión sin datos futuros, riesgo, OLS, regímenes y E1–E8).
