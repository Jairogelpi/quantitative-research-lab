# P03 · Análisis de operaciones ejecutadas · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P03_trades.ipynb`
**Datos:** cinco operaciones de ejemplo, 240 trades sintéticos (semilla 31) y 1.000 trades públicos de Kraken BTC/EUR (19-11-2026, de 17:43 a 18:42 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | El VWAP pondera por cantidad: en el ejemplo es 60.007,15 € frente a una media simple de 60.005,20 €, porque la operación más grande se ejecutó al precio más alto. | E1 · `trade_metrics` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 2 | Contar operaciones no es sumar volumen: TI +0,20 por número frente a +0,40 por volumen en el ejemplo, y +0,46 frente a +0,52 en Kraken. | E2 · `count_imbalance` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 3 | Cuanto más corta la ventana, más TI extremos: en Kraken, el 90 % de las ventanas de 5 s tenía \|TI\| ≥ 0,8, frente al 58 % en 30 s. | E3 · `compare_windows` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 4 | Los extremos se deben en gran parte a las pocas operaciones: las ventanas extremas de 5 s tenían 2,2 trades de media, frente a 4,6 en el resto. | E3 · `compare_windows` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 5 | Las ventanas vacías son muchas en escalas cortas (311 de 711 en 5 s) y deben quedar indefinidas, no con TI = 0. | E3 · `aggregate_trades` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 6 | Una sola ventana de 10 s concentró el 42 % del volumen de la hora (16,65 BTC, TI +0,58) y el precio apenas se movió (+0,18 bps). | E4 · `top_volume_windows` | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 7 | Hubo presión compradora agresiva (TI +0,52) y el precio subió 19,6 bps en la hora, pero antes de las 18:02 el TI era +0,40 y el precio cayó 37 bps. | E5 | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 8 | El lado agresor no equivale a orden de mercado: 595 de 1.000 trades fueron órdenes limitadas que cruzaron el libro. | E5 | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |
| 9 | Los tamaños están muy concentrados: la mediana de un trade fue 0,0024 BTC y el máximo 3,68 BTC. | E2 y E5 | [Operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) |

## E5 · Muestra real de Kraken (recepción 18:42:42 UTC)

| Métrica | Valor |
|---|---|
| Cobertura | 17:43:21 → 18:42:40 UTC (59 min, 1.000 trades) |
| Volumen | 39,19 BTC (2,24 M€) |
| Compras / ventas agresivas | 29,73 / 9,46 BTC |
| Trade Imbalance | +0,52 (por número: +0,46) |
| CVD final | +20,27 BTC |
| VWAP / media simple | 57.201,19 € / 57.277,77 € |
| Precio | 57.329,10 → 57.441,60 € (+19,6 bps); mín. 57.033 €, máx. 57.628,10 € |

## Limitaciones

- Una consulta REST trae solo las últimas N operaciones (1.000 cubrieron 59 minutos), no un intervalo elegido.
- Las ventanas de los extremos pueden estar incompletas, y un hueco en la muestra no demuestra que el exchange no negociara.
- La hora de recepción es local, no la de los trades.
- Los trades no muestran la liquidez pasiva: no permiten demostrar absorción ni calcular el OFI del libro.
- Los retornos de E4 son contemporáneos: no dicen nada sobre la ventana siguiente.

## Para evaluar si el desequilibrio anticipa retornos haría falta

- Captura continua (WebSocket) durante muchos días, con deduplicación por `trade_id`.
- Retornos futuros de mid price (no del último trade, para evitar el rebote bid-ask), sincronizados con el libro (P02).
- Validación fuera de muestra en orden temporal y descontar costes: spread, slippage y comisiones.

## Código y pruebas

- Funciones: `src/quantlab/p03/trades.py` → `normalize_trades`, `add_trade_features`, `summarize_trades`, `aggregate_trades`, `fetch_recent_trades`, `synthetic_trades`, `trade_metrics`, `count_imbalance`, `compare_windows`, `top_volume_windows`, `EXAMPLE_TRADES`.
- Pruebas: `tests/test_trades.py` (las 12 comprobaciones del ejemplo, las 4 de agregación, validación, E1–E4 y 1 prueba en vivo).
