# Eficiencia de mercado: autocorrelación, pruebas múltiples, data snooping y costes

**Familia:** validación de señales · **Visto en:** P11 · **Código:** `src/quantlab/p11/efficiency.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Eficiencia débil | — | Los precios pasados no permiten beneficios anormales sistemáticos tras riesgo y costes | Hipótesis económica, no solo estadística. |
| Paseo aleatorio | `make_market` | log P_t = log P_{t−1} + r_t, con r_t = φ · r_{t−1} + ε_t | φ = 0 es el modelo nulo simplificado. |
| Autocorrelación | `manual_autocorrelation` | ρ_k = Corr(r_t, r_{t−k}) | > 0: persistencia; < 0: reversión. |
| Ljung–Box | `ljung_box_table` | Contraste conjunto de ρ_1 = … = ρ_k = 0 | Rechazar: hay dependencia lineal. No rechazar: no se detecta. |
| Falsos positivos esperados | — | E[V] = m · α | Con 500 pruebas al 5 %, 25 falsos de media. |
| P(≥ 1 falso positivo) | — | 1 − (1 − α)^m | Con 100 pruebas, un 99,4 %. |
| Bonferroni | `bonferroni_manual` | Rechazar si p < α / m | Controla el FWER (al menos un falso positivo). |
| Benjamini–Hochberg | `multipletests(method="fdr_bh")` | Umbrales crecientes por rango | Controla el FDR (proporción de falsos entre los descubrimientos). |
| IC máximo nulo | `max_ic_by_count` | ≈ √(2 · ln m / n) | Lo que se espera encontrar por azar al probar m señales. |
| Autocorrelación móvil | `rolling_autocorr` | ρ_1 en una ventana hacia atrás de N retornos | Detecta cambios de régimen con retraso. |
| Retorno neto por operación | `trade_experiment` | P_{t+2} / P_{t+1} − 1 − c | ¿Sobrevive el patrón a los costes? |

## Ideas clave

- **Niveles ≠ retornos:** los precios de un paseo aleatorio tienen autocorrelación ≈ 0,995; sus retornos, ≈ 0.
- **Un retardo "significativo" puede ser azar:** el control nulo tuvo ACF(1) = 0,071 (≈ 3 errores estándar), y Ljung–Box no lo rechazó.
- **Con más datos, todo es significativo:** con φ = 0,05, Ljung–Box rechaza el 11,5 % de las veces con 500 datos y el 98 % con 10.000. El p-valor no mide el tamaño del efecto.
- **Probar mucho garantiza falsos hallazgos:** 20 de 500 señales nulas con p < 0,05; ninguna sobrevive a Bonferroni ni a BH.
- **El IC máximo crece con el número de pruebas:** 0,069, 0,078 y 0,092 con 100, 500 y 1.000 señales nulas, y ≈ 0 en validación.
- **Las señales decaen y se detectan tarde:** la autocorrelación móvil tardó 84–101 velas en reflejar el fin de la dependencia.
- **Estadísticamente real ≠ rentable:** el control persistente (p ≈ 0) gana 0,19 bps brutos por operación; con 5 bps ya pierde.
- **Sin autocorrelación ≠ independencia:** en Kraken, los retornos no tienen dependencia lineal, pero |r| tiene ACF(1) = 0,24.

## Validación

- `load_p04` reutiliza la validación de P05: rejilla regular, precios > 0 y finitos, huecos como NaN.
- `split_returns` calcula los retornos **después** del corte: ningún retorno cruza la frontera.
- `diagnostics` usa el tramo contiguo más largo sin huecos y exige al menos máx(60, 5 · lags + 1) retornos.
- El candidato de las pruebas múltiples se elige (índice y signo) **solo en desarrollo**, antes de evaluarlo.
- `rolling_autocorr` usa ventanas hacia atrás: calcularla con la serie truncada da el mismo resultado.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Falsos positivos esperados | 500 señales nulas, α = 5 % | **25** (observados: 20) |
| Umbral de Bonferroni | 500 señales, α = 5 % | **0,0001** |
| P(≥ 1 falso positivo) | 20 pruebas | 1 − 0,95²⁰ = **64,2 %** |
| Decaimiento | φ de 0,35 a 0 | ACF(1): 0,409 → −0,011 |

## Código

```python
from quantlab.p11.efficiency import (make_markets, diagnostics, split_returns, null_signal_experiment,
                                     monte_carlo_false_positives, trade_experiment, rolling_autocorr)

markets = make_markets(n=2400, seed=42)
diag, acf = diagnostics(markets, lags=10)
r = split_returns(markets["Aleatorio"])
table, best, direction = null_signal_experiment(r["Desarrollo"].dropna().to_numpy(),
                                                r["Validación"].dropna().to_numpy(), 500)
trade_experiment(markets["Persistente"], cost_bps=20)
```

Relacionado: [momentum_y_reversion.md](momentum_y_reversion.md) · [rentabilidad_y_riesgo.md](rentabilidad_y_riesgo.md) · [costes_de_ejecucion.md](costes_de_ejecucion.md)
