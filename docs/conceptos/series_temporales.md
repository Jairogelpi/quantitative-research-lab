# Series temporales: velas OHLCV, retornos, volatilidad y objetivo futuro

**Familia:** preparación de datos · **Visto en:** P04 · **Código:** `src/quantlab/p04/timeseries.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Vela OHLCV | `open`, `high`, `low`, `close`, `volume` | Primer, máximo, mínimo y último precio, y Σ q, en [t − Δ, t) | Resumen de los trades de un intervalo. Se conoce al **cerrar** el intervalo. |
| Volumen monetario | `notional_volume` | Σ p · q | Euros negociados en la vela. |
| VWAP de la vela | `vwap` | Σ p · q / Σ q | Precio medio por BTC de la vela. |
| Rango | `price_range` | high − low | Amplitud del movimiento dentro de la vela. |
| Vela vacía | `is_empty` | trade_count = 0 | OHLC = NaN y volumen 0. No se inventa precio. |
| Vela de frontera | `boundary_window` | Primera y última | Puede estar incompleta: se excluye de los retornos. |
| Cierre de análisis | `analysis_close` | close salvo vacías y fronteras | Precios válidos para calcular retornos. |
| Retorno simple | `simple_return` | P_t / P_{t−1} − 1 | Cambio porcentual real. Se agrega **multiplicando**. |
| Retorno logarítmico | `log_return` | ln(P_t / P_{t−1}) | Se agrega **sumando**. Simétrico. |
| Segmento | `segment_id` | Tramo de cierres válidos consecutivos | Un hueco corta la serie en segmentos. |
| Retorno acumulado | `cumulative_return` | P_t / primer cierre del segmento − 1 | Resultado desde el inicio del segmento. |
| Volatilidad móvil | `rolling_volatility` | Desv. típica muestral (ddof = 1) de los últimos N retornos log | Cuánto se mueve el precio por intervalo. Sin dirección. |
| Volatilidad realizada | `realized_volatility` | √Σ ℓ² de los últimos N retornos | Movimiento total de un horizonte de N intervalos. |
| Retorno futuro | `forward_return` | P_{t+h} / P_t − 1, si los h cierres siguientes están en el mismo segmento | **Objetivo** de investigación. Nunca es una feature. |
| Fecha del objetivo | `target_end_utc` | Índice de la vela t + h | Momento a partir del cual el objetivo es conocido. |

## Ideas clave

- **Una vela solo se conoce al cerrarse.** La vela etiquetada 10:01 contiene [10:00, 10:01) y está disponible a partir de las 10:01, más la latencia.
- **No se inventan precios.** Una vela vacía tiene OHLC = NaN. Sin metadatos, no se distingue un mercado sin trades de un fallo de captura.
- **No se rellenan huecos.** Rellenar con el último cierre crea retornos 0 falsos, alarga retornos a varios intervalos y baja la volatilidad.
- **Simple frente a logarítmico:** 100 → 110 → 100 suma +0,909 % en simples, pero el compuesto es 0 y la suma de logarítmicos también.
- **La escala depende de la frecuencia:** la desviación típica se mide "por vela", así que solo es comparable entre series de la misma frecuencia.
- **Ventana corta frente a larga:** con N pequeño la volatilidad reacciona antes a un cambio de régimen, pero es más ruidosa y no tiene valor hasta reunir N retornos.
- **La volatilidad no indica dirección:** eleva las desviaciones al cuadrado.
- **El objetivo no es una feature.** Usarlo como entrada es *look-ahead*: el backtest parece perfecto y falla en tiempo real.
- **El retorno close-to-close no es un P&L:** no incluye bid/ask, comisiones, profundidad ni latencia.

## Validación

- `validate_trades` se detiene con `ValueError` en estos casos: faltan columnas o no hay filas, timestamps vacíos, precio o cantidad ≤ 0 o no finitos, e IDs duplicados. No elimina trades con el mismo precio u hora.
- `build_ohlcv`: ventana positiva. Las velas conservan el número de trades, el volumen y el nominal, y high ≥ max(open, close) y low ≤ min(open, close).
- `add_volatility` exige N ≥ 2 entero, y `add_target` h ≥ 1 entero.

## Ejemplo (vela de las 10:01)

| Trade | Hora | Precio | Cantidad |
|---|---|---|---|
| 1 | 10:00:01 | 100 | 0,2 |
| 2 | 10:00:10 | 105 | 0,5 |
| 3 | 10:00:20 | 98 | 0,3 |
| 4 | 10:00:40 | 103 | 0,4 |
| 5 | 10:00:55 | 104 | 0,6 |
| **Vela** | **[10:00, 10:01)** | **O 100 · H 105 · L 98 · C 104** | **2 BTC** |

## Código

```python
from quantlab.p04.timeseries import (synthetic_trades, fetch_trades, load_trades_csv,
                                     build_ohlcv, add_returns, add_volatility, add_target,
                                     compare_frequencies)

trades, provenance = fetch_trades("XBTEUR")          # o synthetic_trades() / load_trades_csv(path)
bars = build_ohlcv(trades, "1min")                   # velas [t − Δ, t)
series = add_target(add_volatility(add_returns(bars), 10), 3)
features = ["simple_return", "log_return", "rolling_volatility", "realized_volatility",
            "price_range", "volume", "trade_count"]   # forward_return NO está aquí
research_table = series[features + ["forward_return", "target_end_utc"]].dropna()
```

Relacionado: [operaciones_ejecutadas.md](operaciones_ejecutadas.md) · [validacion_de_datos.md](validacion_de_datos.md)
