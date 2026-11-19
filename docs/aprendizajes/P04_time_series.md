# P04 · Motor de series temporales financieras · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P04_time_series.ipynb`
**Datos de ejemplo:** cinco trades de la vela de las 10:01, 1.755 trades sintéticos y trades públicos de Kraken

P03 trabajaba con eventos sueltos: una fila por trade, a horas irregulares. P04 los convierte en una **serie temporal regular**: una fila por intervalo, con precios, retornos, volatilidad y el retorno futuro que querremos estudiar en P05.

## 1. Variables de entrada

| Variable | Qué es | Ejemplo |
|---|---|---|
| `timestamp` | Hora del trade, en UTC | 10:00:10 |
| `price` | Precio ejecutado | 105 € |
| `quantity` | Cantidad ejecutada | 0,5 BTC |
| `trade_id` | Identificador, si existe | 2 |
| `WINDOW` (Δ) | Duración de cada vela | 1 min |
| `VOL_WINDOW` (N) | Número de retornos para la volatilidad (no segundos) | 10 |
| `HORIZON` (h) | Número de velas hacia delante del objetivo | 3 |
| `DATA_MODE` | Origen de los datos: `synthetic`, `live` o `csv` (el `*_trades.csv` de P03) | `synthetic` |

## 2. Cómo se calcula cada métrica

### Velas

| Métrica | Fórmula | Ejemplo (vela de las 10:01) | Qué responde |
|---|---|---|---|
| `open` | Primer precio de [t − Δ, t) | **100** | ¿A qué precio empezó el intervalo? |
| `high` | Máximo | **105** | ¿Hasta dónde subió? |
| `low` | Mínimo | **98** | ¿Hasta dónde bajó? |
| `close` | Último precio | **104** | ¿A qué precio terminó? |
| `volume` | Σ q | 0,2 + 0,5 + 0,3 + 0,4 + 0,6 = **2 BTC** | ¿Cuánto se negoció? |
| `notional_volume` | Σ p × q | 20 + 52,5 + 29,4 + 41,2 + 62,4 = **205,5 €** | ¿Cuántos euros se negociaron? |
| `vwap` | Σ p × q / Σ q | 205,5 / 2 = **102,75 €** | Precio medio por BTC de la vela |
| `price_range` | high − low | 105 − 98 = **7 €** | Amplitud del movimiento |
| `trade_count` | Número de trades | **5** | Actividad |
| `is_empty` | trade_count = 0 | Vela de las 10:03: **sí** | ¿Hubo trades observados? |
| `boundary_window` | Primera y última vela | **sí** / no | ¿Puede estar incompleta? |

### Retornos

| Métrica | Fórmula | Ejemplo (100 → 110 → 100) | Qué responde |
|---|---|---|---|
| `simple_return` | P_t / P_{t−1} − 1 | **+10 %** y **−9,09 %** | Cambio porcentual real de cada intervalo |
| `log_return` | ln(P_t / P_{t−1}) | **+9,53 %** y **−9,53 %** | Lo mismo en escala logarítmica, sumable |
| Compuesto | ∏(1 + r) − 1 | 1,10 × 0,909 − 1 = **0** | Resultado real de varios intervalos |
| Suma de simples | Σ r | **+0,909 %** ❌ | Error típico: no representa el resultado |
| `cumulative_return` | P_t / primer cierre del segmento − 1 | De 100 a 110: **+10 %** | Resultado desde el inicio del segmento |

### Volatilidad (N retornos)

| Métrica | Fórmula | Ejemplo (ℓ = +1 %, −1 %, +1 %) | Qué responde |
|---|---|---|---|
| `rolling_volatility` | √(Σ (ℓ_i − ℓ̄)² / (N − 1)) | **1,155 %** por intervalo | ¿Cuánto varían los retornos alrededor de su media? |
| `realized_volatility` | √Σ ℓ_i² | √(3 × 0,01²) = **1,732 %** | Movimiento total del horizonte de N intervalos |

### Objetivo futuro (h velas)

| Métrica | Fórmula | Ejemplo (100, 110, 121, hueco, 100, 120; h = 2) | Qué responde |
|---|---|---|---|
| `forward_return` | P_{t+h} / P_t − 1, solo si los h cierres siguientes están en el mismo segmento | Fila 1: 121 / 100 − 1 = **+21 %**; el resto, **indefinido** | ¿Qué pasará con el precio en h velas? |
| `target_end_utc` | Hora de la vela t + h | Fila 1: 2 minutos después | ¿Desde cuándo se conoce el objetivo? |

## 3. Reglas de validación (antes de calcular)

`validate_trades` detiene el análisis con `ValueError` si:

- Faltan las columnas `timestamp`, `price` o `quantity`, o no hay filas.
- Hay timestamps vacíos, o precios o cantidades ≤ 0 o no finitos.
- Hay `trade_id` duplicados (capturas solapadas).

Y además:

- **No** elimina trades con el mismo precio u hora: pueden ser ejecuciones distintas.
- Las velas conservan el número de trades, el volumen y el nominal, y siempre cumplen high ≥ open, close ≥ low.
- Los cierres de velas **vacías** y de **frontera** no se usan para retornos.
- La volatilidad exige **N retornos consecutivos válidos**; si falta uno, queda vacía.
- El objetivo exige que los **h cierres siguientes** estén en el mismo segmento; los últimos h no tienen objetivo.
- `forward_return` **no puede estar** en la lista de features.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Los trades no superan `validate_trades` | El dato no es válido: no se construye la serie. |
| Una vela sin trades | OHLC = NaN y volumen 0: no hay precio para ese intervalo. |
| Un cierre vacío o de frontera | No se calcula ningún retorno desde ni hacia ese cierre. |
| Un hueco en la serie | La serie se corta en segmentos y el acumulado se reinicia. |
| Menos de N retornos consecutivos válidos | No hay volatilidad para esa vela. |
| Faltan cierres válidos en las h velas siguientes | No hay objetivo para esa vela. |
| `target_end_utc` | El objetivo de esa vela solo se puede usar a partir de esa hora. |
| Retornos simples de varios intervalos | El resultado se obtiene componiendo, no sumando. |
| Retornos logarítmicos de varios intervalos | El resultado se obtiene sumando. |
| Dos volatilidades de distinta frecuencia o N | No son comparables directamente. |
| Una ventana de volatilidad más corta | Reacciona antes a un cambio de régimen (N = 5 a las 5 velas, N = 20 a las 9). |

**Lo que NO puede concluir:**

- Si el precio va a subir o bajar. La volatilidad alta no indica dirección.
- Si una vela vacía fue un mercado sin trades o un fallo de captura, sin metadatos.
- El precio "real" de un hueco. Rellenarlo es un supuesto, no un dato.
- El P&L de una estrategia. El retorno close-to-close ignora bid/ask, comisiones, profundidad y latencia.
- La volatilidad anual. Anualizar exige supuestos sobre frecuencia, cobertura y dependencia temporal.
- Nada estadísticamente sólido con una sola consulta REST: en Kraken solo quedaron 46 filas de investigación.

## 5. Para qué sirve

- **Convertir eventos irregulares en datos analizables.** Los modelos y las estadísticas necesitan una fila por intervalo, no por trade.
- **Comparar movimientos de precio.** Los retornos son comparables entre precios distintos; los precios no.
- **Medir el riesgo reciente.** La volatilidad dice cuánto se mueve el precio, y la ventana N controla la rapidez de reacción frente al ruido.
- **Preparar investigaciones sin trampas.** Separar features y objetivo, y guardar cuándo se conoce cada dato, evita el *look-ahead*, el error que hace que un backtest parezca perfecto y falle en real.
- **Tratar los huecos con honestidad.** Marcar en lugar de rellenar evita inventar retornos y volatilidades que nunca existieron.
- **Base para P05.** Momentum y mean reversion usarán estas series para crear señales y medir su relación con el retorno futuro.

## Referencias

- Código: [`src/quantlab/p04/timeseries.py`](../../src/quantlab/p04/timeseries.py)
- Pruebas: [`tests/test_timeseries.py`](../../tests/test_timeseries.py)
- Conclusiones: [conclusiones/P04_time_series.md](../conclusiones/P04_time_series.md)
- Conceptos: [series temporales](../conceptos/series_temporales.md) · [operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) · [validación de datos](../conceptos/validacion_de_datos.md)
- Aprendizaje anterior: [P03 · Análisis de operaciones ejecutadas](P03_trades.md)
