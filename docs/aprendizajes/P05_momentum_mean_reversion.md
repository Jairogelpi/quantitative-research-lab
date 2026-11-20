# P05 · Momentum y Mean Reversion · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P05_momentum_mean_reversion.ipynb`
**Datos de ejemplo:** precios cortos calculables a mano, 1.800 cierres sintéticos y 720 velas públicas de Kraken

P04 construía series fiables con un objetivo futuro. P05 hace la primera **investigación de señales**: ¿el pasado del precio dice algo sobre su futuro? Y, si lo dice, ¿alcanza para ganar dinero después de costes?

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `close` | Cierre de cada vela, indexado por su fin en UTC (huecos = NaN) | — |
| `WINDOW` | Frecuencia de las velas | 1 min |
| `LOOKBACK` (N) | Velas hacia atrás para momentum, SMA, z-score y EMA | 20 |
| `HORIZON` (h) | Velas que dura cada operación | 5 |
| `Z_THRESHOLD` | Umbral de z-score para la regla de mean reversion | 1,5 |
| `TRAIN_FRACTION` | Fracción cronológica para el desarrollo | 65 % |
| `ROUND_TRIP_BPS` | Coste supuesto por ciclo de compra y venta | 20 bps |
| `DATA_MODE` | `synthetic`, `live` (OHLC de Kraken) o `csv` (`*_series.csv` de P04) | `synthetic` |

## 2. Cómo se calcula cada métrica

### Indicadores (solo con datos hasta t)

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `momentum` | P_t / P_{t−N} − 1 | [100, 102, 104], N = 2: 104/100 − 1 = **+4 %** | ¿Cuánto se movió el precio en N velas? |
| `sma` | Media de los últimos N precios | [100, 102, 104]: **102** | ¿Cuál es el nivel reciente? |
| `rolling_std` | √(Σ (P − SMA)² / (N − 1)) | √((4 + 0 + 4) / 2) = **2** | ¿Cuánto se dispersa el precio? |
| `price_deviation` | P_t − SMA_t | 104 − 102 = **+2 €** | ¿A qué distancia está de su media? |
| `z_score` | (P_t − SMA_t) / s_t | 2 / 2 = **+1** | Esa distancia, en desviaciones típicas |
| `ema` | Media exponencial con span N, reiniciada tras huecos | — | Nivel reciente, pesando más lo último |
| `momentum_signal` | momentum | +4 % | Espera subida si es alto |
| `reversion_signal` | −z_score | −1 | Espera subida si es alto (precio bajo su media) |

### Objetivo y diagnóstico

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `entry_time` / `exit_time` | t + 1 vela / t + 1 + h velas | Señal 10:01, h = 2 → entrada **10:02**, salida **10:04** | ¿Cuándo se entra y se sale? |
| `forward_return` | P_{t+1+h} / P_{t+1} − 1 | 106 / 102 − 1 = **+3,92 %** | ¿Qué retorno siguió a la señal? |
| `ic_pearson` | Correlación lineal señal–objetivo | Momentum, simulación: **−0,089** | ¿Se mueven juntos señal y retorno? |
| `ic_spearman` | Correlación por rangos | **−0,082** | Lo mismo, sin suponer relación lineal |
| `high_minus_low_bps` | Retorno medio del 20 % más alto − del 20 % más bajo (cuantiles del desarrollo) | **−6,57 bps** | ¿Rinde más la señal alta que la baja? |

### Simulación long/cash

| Métrica | Fórmula | Ejemplo (validación, momentum) | Qué responde |
|---|---|---|---|
| `gross_return` | forward_return de cada operación | Media: **−1,66 bps** | ¿Cuánto movió el precio? |
| `net_return` | gross − coste / 10.000 | −1,66 − 20 = **−21,66 bps** | ¿Cuánto queda después de costes? |
| `equity` | ∏ (1 + net_return) | Total: **−10,5 %** | ¿Cómo evoluciona el capital? |
| `win_rate_pct` | % de operaciones con neto > 0 | **11,8 %** | ¿Cuántas ganan? |
| `breakeven_cost_bps` | Retorno bruto medio | **−1,66 bps** | ¿Qué coste soporta sin perder? |
| `exposure_pct` | Σ (salida − entrada) / duración del periodo | **40,9 %** | ¿Cuánto tiempo está invertida? |

## 3. Reglas de validación (antes de calcular)

- `regularize` detiene el análisis con `ValueError` si el índice está vacío, duplicado o con NaT, si algún timestamp no encaja en la rejilla de `WINDOW` o si hay precios ≤ 0 o no finitos.
- Los huecos quedan como **NaN**: nunca se rellenan.
- El momentum exige N + 1 cierres sin huecos; la EMA se reinicia tras cada hueco; el objetivo exige precio en **todas** las velas de t a t + 1 + h.
- **Causalidad:** las features calculadas con la mitad de la serie deben ser idénticas a las de la serie completa.
- **Fechas:** entrada > señal y salida > entrada, siempre.
- **Separación:** ninguna salida del desarrollo llega a la frontera; la validación empieza en la frontera.
- **Simulación:** sin posiciones solapadas, coste exacto en cada operación y retorno neto > −1.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| La serie no supera `regularize` | El dato no es válido: no se calcula nada. |
| Menos de N + 1 cierres válidos seguidos | No hay momentum en esa vela. |
| Desviación típica 0 | El z-score queda indefinido. |
| Falta un precio entre t y t + 1 + h | No hay objetivo para esa señal. |
| `forward_return`, `entry_price` o `exit_price` entre las features | Hay *look-ahead*: el análisis no es válido. |
| IC con signos distintos en desarrollo y validación | La asociación no persiste. |
| Retorno bruto medio ≤ coste | La regla pierde dinero en ese periodo. |
| Retorno bruto medio < 0 | Ni con coste cero hay beneficio. |
| Más operaciones con el mismo coste por ciclo | Más coste total. |
| Exposiciones distintas | Los totales no son comparables directamente. |
| Parámetros elegidos mirando la validación | Esa validación ya no sirve para evaluarlos. |

**Lo que NO puede concluir:**

- Que una señal "funcione" en BTC/EUR con 12 horas de datos: la conclusión correcta es **evidencia insuficiente**.
- La significancia estadística de un IC: los objetivos se solapan y no son independientes.
- Que un z-score bajo signifique un precio barato: solo compara el precio con su propio pasado.
- Que una dependencia estadística sea explotable: la simulación tiene autocorrelación de +0,40 y −0,36 y ninguna señal la aprovecha, por el retraso de entrada.
- El resultado real de operar: no se modelan spread dinámico, llenados, slippage, impacto ni fiscalidad.
- Que unos resultados sintéticos digan algo sobre Bitcoin.

## 5. Para qué sirve

- **Investigar señales con método.** Hipótesis, features sin futuro, objetivo con retraso, separación cronológica y una única validación. Es el mismo esqueleto que se usará con cualquier señal.
- **No engañarse con el backtest.** Fijar parámetros y cuantiles en el desarrollo, no rellenar huecos y no mirar la validación evita resultados que solo existen en papel.
- **Pasar de asociación a economía.** Un IC distinto de cero no basta: hay que comparar el retorno bruto con los costes y la exposición.
- **Saber cuándo decir "no sé".** Con pocos datos, la respuesta honesta es "evidencia insuficiente", no ajustar hasta encontrar beneficios.
- **Diseñar la siguiente investigación.** E7 propone combinar momentum con el microprice de P02, con datos simultáneos sincronizados por tiempo y un criterio de rechazo definido de antemano.

## Referencias

- Código: [`src/quantlab/p05/signals.py`](../../src/quantlab/p05/signals.py)
- Pruebas: [`tests/test_signals.py`](../../tests/test_signals.py)
- Conclusiones: [conclusiones/P05_momentum_mean_reversion.md](../conclusiones/P05_momentum_mean_reversion.md)
- Conceptos: [momentum y reversión](../conceptos/momentum_y_reversion.md) · [series temporales](../conceptos/series_temporales.md) · [spread y costes](../conceptos/spread_y_costes.md)
- Aprendizaje anterior: [P04 · Motor de series temporales financieras](P04_time_series.md)
