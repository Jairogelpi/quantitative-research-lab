# P11 · Eficiencia del mercado y detección de anomalías · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P11_market_efficiency.ipynb`
**Datos:** tres mercados sintéticos de 2.400 velas con el mismo ruido (aleatorio, persistente con φ = 0,35 y decaimiento de 0,35 a 0), 500 señales nulas y 720 velas reales de 1 minuto de Kraken BTC/EUR (19-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | El control persistente tiene ACF(1) de 0,409 y 0,340 en los dos periodos (Ljung–Box p ≈ 0); el aleatorio, 0,071 y −0,011 (p = 0,13 y 0,64). | `diagnostics` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 2 | En el mercado con decaimiento, la ACF(1) pasa de 0,409 en desarrollo a −0,011 en validación: el patrón no sobrevive. | `diagnostics` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 3 | 20 de 500 señales nulas tienen p < 0,05; ninguna sobrevive a Bonferroni ni a Benjamini–Hochberg. | `null_signal_experiment` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 4 | La mejor señal nula pasa de un IC de 0,076 (p = 0,003) en desarrollo a 0,021 (p = 0,55) en validación. | `null_signal_experiment` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 5 | Con 500 pruebas, el 100 % de los experimentos tiene al menos un falso positivo; con Bonferroni, el 4,7 %. | `monte_carlo_false_positives` · E4 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 6 | Los precios de un paseo aleatorio tienen ACF(1) ≈ 0,995; sus retornos, ≈ 0,001. | E2 · `random_walk_acf` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 7 | Con φ = 0,05, Ljung–Box rechaza el 11,5 %, el 29,5 % y el 98 % de las veces con 500, 2.000 y 10.000 datos. | E3 · `ljung_box_power` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 8 | El IC máximo nulo crece con el número de señales probadas (0,069 → 0,092) y cae a ≈ 0 en validación. | E5 · `max_ic_by_count` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |
| 9 | La autocorrelación móvil tarda 84 velas en bajar de 0,2 y 101 en bajar de 0,1 tras el fin de la dependencia. | E6 · `rolling_autocorr` | [Series temporales](../conceptos/series_temporales.md) |
| 10 | El control persistente gana +0,19 bps brutos por operación en validación; con 5 bps de coste ya pierde. | E7 · `trade_experiment` | [Costes de ejecución](../conceptos/costes_de_ejecucion.md) |
| 11 | En Kraken no hay dependencia lineal detectable (Ljung–Box p = 0,29 y 0,52), pero \|r\| tiene ACF(1) = 0,24 (p ≈ 0): agrupamiento de volatilidad. | E8 | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |

## Controles sintéticos

| Mercado | ACF(1) desarrollo | ACF(1) validación | Bruto en validación | Neto (20 bps) |
|---|---|---|---|---|
| Aleatorio | +0,071 | −0,011 | −0,41 bps | −20,41 bps |
| Persistente | +0,409 | +0,340 | +0,19 bps | −19,81 bps |
| Decaimiento | +0,409 | −0,011 | −0,41 bps | −20,41 bps |

## E8 · Kraken BTC/EUR (09:06–21:05 UTC, 720 velas, 0 huecos)

| | n | ACF(1) | Ljung–Box (10) | Bruto | Neto (20 bps) |
|---|---|---|---|---|---|
| Desarrollo | 467 | −0,025 | p = 0,29 | −0,36 bps | −20,36 bps |
| Validación | 251 | +0,046 | p = 0,52 | −1,10 bps | −21,10 bps |

**Conclusión: evidencia insuficiente.** 12 horas de un día no permiten afirmar ni negar una ineficiencia.

## Limitaciones

- Ninguna simulación demuestra una ineficiencia de BTC.
- Con heterocedasticidad (visible en |r|), los p-valores clásicos de Ljung–Box no están bien calibrados.
- El coste de 20 bps es hipotético; un coste medido con P08 varía con cada operación.
- Las 500 señales nulas son independientes; con indicadores reales solapados, el contraste ingenuo no sería válido.

## Código y pruebas

- Funciones: `src/quantlab/p11/efficiency.py` → `make_market`, `make_markets`, `load_p04` (reutiliza P05), `longest_valid_run`, `split_returns`, `diagnostics`, `pearson_many`, `null_signal_experiment`, `monte_carlo_false_positives`, `trade_experiment`, `manual_autocorrelation`, `random_walk_acf`, `ljung_box_table`, `ljung_box_power`, `bonferroni_manual`, `false_positive_table`, `max_ic_by_count`, `rolling_autocorr`, `regime_detection_delay`.
- Pruebas: `tests/test_efficiency.py` (controles, carga del CSV de P04, autocorrelación, Ljung–Box, Pearson frente a SciPy, señales nulas, Monte Carlo, costes y E1–E7).
