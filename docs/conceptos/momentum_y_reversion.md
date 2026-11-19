# Momentum y mean reversion: señales, IC y simulación con costes

**Familia:** investigación de señales · **Visto en:** P05 · **Código:** `src/quantlab/p05/signals.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Momentum | `momentum` | P_t / P_{t−N} − 1 (exige N + 1 cierres sin huecos) | Cuánto ha subido o bajado el precio en N velas. |
| Media simple | `sma` | (1/N) Σ P_{t−j}, j = 0..N−1 | Nivel medio reciente. |
| Desviación típica | `rolling_std` | Desv. típica muestral (n − 1) de los N precios | Dispersión reciente del precio. |
| Media exponencial | `ema` | EWM con span = N, reiniciada tras cada hueco | Media que pesa más lo reciente. |
| Desviación | `price_deviation` | P_t − SMA_t | Distancia a la media, en euros. |
| Z-score | `z_score` | (P_t − SMA_t) / s_t | Distancia a la media en desviaciones típicas. |
| Señal de momentum | `momentum_signal` | momentum | Espera retornos positivos si sube. |
| Señal de reversión | `reversion_signal` | −z_score | Espera retornos positivos si sube (precio bajo su media). |
| Objetivo | `forward_return` | P_{t+1+h} / P_{t+1} − 1 | Retorno desde una vela **después** de la señal. |
| IC | `ic_pearson`, `ic_spearman` | Correlación señal–objetivo (lineal / por rangos) | Asociación descriptiva, no significancia. |
| Extremos | `low_mean_bps`, `high_mean_bps` | Retorno medio bajo el quintil 20 % y sobre el 80 % **del desarrollo** | ¿Rinde más el extremo alto que el bajo? |
| Retorno neto | `net_return` | gross_return − coste / 10.000 | Aproximación con coste fijo por ciclo. |
| Coste de equilibrio | `breakeven_cost_bps` | Retorno bruto medio por operación | Coste máximo que la regla soporta sin perder. |
| Exposición | `exposure_pct` | Σ (salida − entrada) / duración del periodo | Tiempo invertido en el mercado. |

## Ideas clave

- **Las features solo miran al pasado:** calcular con la mitad de la serie da el mismo resultado que con la serie completa.
- **Entrada retrasada:** la señal se observa en t, se entra en t + 1 y se sale en t + 1 + h. Así no se supone una ejecución instantánea.
- **Una dependencia real no es una señal explotable:** en la simulación, la autocorrelación de retardo 1 es ±0,40, pero el retraso de una vela deja fuera justo ese retorno.
- **Separación cronológica:** desarrollo (primer 65 %) y validación (resto). Las filas de desarrollo cuya salida toca la frontera se eliminan.
- **Los cuantiles se fijan en el desarrollo**, y los parámetros también. Elegir mirando la validación la contamina.
- **IC solapado:** los objetivos de filas consecutivas comparten retornos, así que no son observaciones independientes. No hay p-valores ingenuos.
- **Un IC positivo no implica beneficio neto:** los costes (20 bps supuestos) superan con mucho los retornos brutos de unos pocos bps.
- **Exposiciones distintas:** comparar totales entre reglas mezcla la calidad de la señal con el tiempo invertido.
- **Z-score bajo ≠ infravaloración:** solo compara el precio con su pasado reciente, no con un valor fundamental.

## Validación

- `regularize` se detiene con `ValueError` en estos casos: índice vacío, duplicado o con NaT, timestamps fuera de la rejilla de `WINDOW`, y precios ≤ 0 o no finitos. Los huecos quedan como NaN, sin rellenar.
- `build_features` exige N ≥ 2; `add_target`, h ≥ 1; `split_train_test`, 0 < fracción < 1.
- `simulate`: sin solapamiento (cada entrada es posterior a la salida anterior), retorno neto > −1 y reglas conocidas.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Momentum (N = 2) | 100, 102, 104, 106 | —, —, **+4,00 %**, +3,92 % |
| SMA / s / z | 100, 102, 104 | 102 / 2 / **+1** |
| Objetivo (h = 2) | Señal 10:01 | Entrada 10:02, salida 10:04 |

## Código

```python
from quantlab.p05.signals import (synthetic_prices, fetch_kraken_ohlc, regularize, build_features,
                                  add_target, split_train_test, information_table, strategy_table,
                                  cost_sensitivity, development_grid, breakeven_costs)

close, provenance = fetch_kraken_ohlc("XBTEUR", 1, "1min")   # hasta 720 velas, sin la última abierta
close = regularize(close, "1min")
dataset = add_target(build_features(close, 20), 5)
train, test, split_time = split_train_test(dataset, .65)
information_table(train, test)                                # IC y extremos
table, logs = strategy_table({"desarrollo": train, "validación": test}, cost_bps=20)
```

Relacionado: [series_temporales.md](series_temporales.md) · [libro_de_ordenes.md](libro_de_ordenes.md) · [spread_y_costes.md](spread_y_costes.md)
