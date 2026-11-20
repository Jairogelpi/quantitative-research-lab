# P17 · Primera investigación cuantitativa integral · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P17_integrated_research.ipynb`
**Datos de ejemplo:** simulación con un retraso programado y una captura real de 30 minutos de Kraken, OKX y Bitvavo

P17 junta todo el módulo en una sola investigación: una hipótesis concreta (¿Kraken anticipa a OKX?), un protocolo fijado antes de mirar, datos auditados, una prueba estadística, un motor de ejecución con costes, la incertidumbre y una decisión. La respuesta es **no**, y es reproducible: eso también es una investigación válida.

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `received_at` | Hora a la que **recibimos** la cotización (UTC) | — |
| `bid`, `ask`, `bid_size`, `ask_size` | Mejor nivel del libro (EUR/BTC y BTC) | — |
| `QTY` | Cantidad por operación | 0,01 BTC |
| `FEE_BPS`, `EXTRA_BPS` | Comisión y reserva adversa por lado | 10 bps y 1 bp |
| `MAX_AGE_S` | Antigüedad máxima de una cotización en la rejilla | 1,5 s |
| `LOOKBACK`, `DELAY`, `HOLD` | Señal en 3 s, entrada 1 s después, salida 4 s después | 3 / 1 / 4 |
| Corte | Desarrollo / validación | 60 % / 40 % |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Edad | t − `received_at` | Real: 0,43 s de media en Kraken | ¿Está fresca la cotización? |
| Lead-lag | Corr(r_Kraken,t, r_OKX,t+k) | Sim.: máximo en k = 3; real: k = 0 | ¿Quién va por delante? |
| Señal | (mid_t / mid_{t−3} − 1) · 10⁴ | Umbral p70: 0,85 bps | ¿Cuándo comprar? |
| R² fuera de muestra | 1 − SSE(modelo) / SSE(media) | Sim.: **32,9 %**; real: **−0,02 %** | ¿Predice en validación? |
| PnL neto | q · (venta − compra) − comisiones | −21,3 bps por operación (sim.) | ¿Gana al ejecutar? |
| Coste de ida y vuelta | 2 · (10 + 1) bps + spread | ~22 bps | ¿Cuánto hay que superar? |
| IC por bloques | Percentiles de medias de bloques de 10 | [−0,373; −0,299] € | ¿Es robusta la pérdida? |
| Null circular | Corr con el objetivo desplazado | p = 0,001 (sim.), 0,55 (real) | ¿Es significativa la señal? |
| Atribución | net_bps = α + β · target_bps | Solo ejecuciones: β = 1,00, α = −22,5 bps | ¿Ventaja o exposición? |

## 3. Reglas de validación (antes de calcular)

- El protocolo (hipótesis, señal, umbral, corte, costes y criterios) se fija antes de ver la validación, y su huella SHA-256 lo demuestra.
- Se usa la hora de **recepción**, no la del exchange: los relojes no están sincronizados.
- La rejilla solo usa cotizaciones recibidas antes o en cada segundo, con edad ≤ 1,5 s. Nada se interpola.
- Las ventanas que cruzan el corte se purgan; las incompletas se cuentan y se descartan.
- Una señal sin profundidad tiene PnL **desconocido**: excluirla sin más sería selección ex post.
- Con menos de 60 oportunidades por segmento, el análisis se detiene.
- Cualquier señal nueva se prueba en una muestra nueva.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Edad negativa o `received_at` posterior al segundo | La rejilla usa datos futuros: error. |
| `exchange_at` posterior a `received_at` | Los relojes no están sincronizados. |
| Movimiento bruto medio < coste de ida y vuelta | La media neta es negativa. |
| Comisión mayor con la misma regla | El PnL no mejora. |
| Señales sin profundidad > 0 | El PnL de validación es condicionado: no se aprueba. |
| Límite inferior del IC ≤ 0 | No se cumple el criterio económico. |
| Pendiente ≤ 0 o p ≥ 0,05 en validación | No se cumple el criterio estadístico. |

**Lo que NO puede concluir:**

- Que un mercado cause los movimientos de otro porque los preceda.
- Que una señal con p < 0,05 en desarrollo funcione en otra muestra.
- Que la regla sea viable en otros horarios o días a partir de una sesión de 30 minutos.
- Que las comisiones de OKX sean las supuestas: su tabla oficial no se pudo verificar.

## 5. Para qué sirve

- **Investigar con método.** Protocolo, datos auditados, prueba, ejecución, incertidumbre y decisión, en ese orden.
- **Distinguir predecir de ganar.** Una señal con un R² del 33 % puede perder en todas las operaciones.
- **Detectar falsos descubrimientos.** El null circular y una muestra nueva desmontaron una señal OBI que parecía significativa.
- **Cuantificar lo que falta.** Ventanas sin datos, señales sin profundidad y relojes desajustados se cuentan, no se esconden.
- **Cerrar el módulo.** Integra cotizaciones, libros, retornos, desfases, costes, riesgo, validación y microestructura de P01–P13.

## Referencias

- Código: [`src/quantlab/p17/integrated_research.py`](../../src/quantlab/p17/integrated_research.py)
- Pruebas: [`tests/test_integrated_research.py`](../../tests/test_integrated_research.py)
- Conclusiones: [conclusiones/P17_integrated_research.md](../conclusiones/P17_integrated_research.md)
- Conceptos: [investigación integral](../conceptos/investigacion_integral.md) · [comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) · [costes de ejecución](../conceptos/costes_de_ejecucion.md)
- Aprendizaje anterior: [P16 · Construcción de factores financieros](P16_factor_construction.md)
