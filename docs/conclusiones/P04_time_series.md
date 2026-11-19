# P04 · Motor de series temporales financieras · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P04_time_series.ipynb`
**Datos:** 1.755 trades sintéticos (semilla 42, con un hueco de 2 minutos y un tramo de alta volatilidad) y 1.000 trades públicos de Kraken BTC/EUR (19-11-2026, de 17:53 a 18:53 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | Una vela solo se conoce al cerrar su intervalo: la de las 10:01 contiene [10:00, 10:01). En el ejemplo: O 100 · H 105 · L 98 · C 104 · 2 BTC. | `build_ohlcv` · E1 `manual_ohlcv` | [Series temporales](../conceptos/series_temporales.md) |
| 2 | Los retornos simples no se suman: 100 → 110 → 100 suma +0,909 %, pero el compuesto es 0. Los logarítmicos sí se suman. | E2 · `return_decomposition` | [Series temporales](../conceptos/series_temporales.md) |
| 3 | La volatilidad con ventana corta reacciona antes al cambio de régimen: N = 5 alerta 5 velas después del inicio; N = 10, 7; N = 20, 9. | E3 · `volatility_reaction` | [Series temporales](../conceptos/series_temporales.md) |
| 4 | La ventana corta es más ruidosa, y la larga pierde más valores: 76 valores válidos con N = 5 frente a 46 con N = 20. | E3 | [Series temporales](../conceptos/series_temporales.md) |
| 5 | Rellenar huecos con el último cierre crea 3 retornos que no son hechos de mercado (2 exactamente 0) y baja la volatilidad de 3,10 a 3,05 bps. | E4 · `forward_fill_comparison` | [Series temporales](../conceptos/series_temporales.md) |
| 6 | El objetivo futuro siempre es posterior, mide exactamente h velas y nunca cruza huecos. Se conocen 84, 80 y 76 objetivos para h = 1, 3 y 5. | E5 · `target_alignment` | [Series temporales](../conceptos/series_temporales.md) |
| 7 | La escala de la volatilidad depende de la frecuencia: 0,91 bps por vela de 5 s frente a 5,62 bps por vela de 5 min (simulación). | `compare_frequencies` | [Series temporales](../conceptos/series_temporales.md) |
| 8 | En Kraken, 1 minuto es la resolución razonable: con 5 s, el 43 % de las velas estaba vacío; con 5 min solo había 10 retornos. | E6 | [Series temporales](../conceptos/series_temporales.md) |
| 9 | El mercado real fue unas 4 veces más volátil que la simulación en reposo: 8,24 frente a 1,88 bps por minuto (mediana, N = 10). | E6 | [Series temporales](../conceptos/series_temporales.md) |
| 10 | Una consulta REST da muy pocos datos: 46 filas completas de investigación. Hace falta una captura continua y más larga. | E6 | [Series temporales](../conceptos/series_temporales.md) |

## E6 · Kraken frente a la simulación (recepción 18:53:47 UTC)

| | Sintética | Kraken |
|---|---|---|
| Trades | 1.755 | 1.000 |
| Cobertura | 90 min | 60 min |
| Velas de 1 min / vacías | 90 / 2 | 61 / 0 |
| Retornos válidos | 84 | 58 |
| Desv. típica de retornos de 1 min | 3,10 bps | 8,64 bps |
| Volatilidad móvil mediana (N = 10) | 1,88 bps | 8,24 bps |
| Filas completas de investigación | 60 | 46 |

| Frecuencia (Kraken) | Velas | Vacías | Retornos válidos | Desv. típica por vela |
|---|---|---|---|---|
| 5 s | 722 | 314 | 235 | 2,57 bps |
| 15 s | 242 | 23 | 197 | 4,41 bps |
| 1 min | 61 | 0 | 58 | 8,64 bps |
| 5 min | 13 | 0 | 10 | 21,96 bps |

## Limitaciones

- Una consulta REST trae solo las últimas 1.000 operaciones: la cobertura la decide la actividad del mercado, no nosotros.
- Sin metadatos de captura, una vela vacía puede ser un mercado sin trades o un fallo de captura.
- El retorno close-to-close es una etiqueta de investigación, no un P&L: no incluye bid/ask, comisiones, profundidad ni latencia.
- La volatilidad no está anualizada: hacerlo exigiría supuestos sobre frecuencia, cobertura y dependencia temporal.
- Los floats sirven para el análisis; un motor de ejecución necesitaría precisión decimal.

## Código y pruebas

- Funciones: `src/quantlab/p04/timeseries.py` → `validate_trades`, `fetch_trades` (reutiliza la descarga de P03), `load_trades_csv`, `synthetic_trades`, `build_ohlcv`, `add_returns`, `add_volatility`, `add_target`, `compare_frequencies`, `manual_ohlcv`, `return_decomposition`, `volatility_reaction`, `forward_fill_comparison`, `target_alignment`.
- Pruebas: `tests/test_timeseries.py` (validación, las 9 comprobaciones OHLCV, retornos, volatilidad, alineación temporal, E1–E5 y 1 prueba en vivo).
