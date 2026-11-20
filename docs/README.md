# QuantLab · Documentación

Apuntes de conceptos y conclusiones que vamos sacando en las prácticas, con el código que usamos para cada uno.

## Estructura

| Carpeta | Contenido |
|---|---|
| `conceptos/` | Definiciones agrupadas por tema, con fórmulas y código reutilizable. |
| `../src/quantlab/pNN/` | Código de cada práctica (`p01/`, `p02/`…), con sus pruebas en `../tests/`. |
| `conclusiones/` | Lo que aprendimos en cada práctica (una nota por cuaderno). |
| `aprendizajes/` | Resumen didáctico por práctica: variables, cómo se calcula cada métrica, conclusiones deterministas y para qué sirve. |

## Conceptos

| Tema | Archivo | Visto en |
|---|---|---|
| Precios de una cotización (Bid, Ask, Last, Mid) | [conceptos/precios_de_cotizacion.md](conceptos/precios_de_cotizacion.md) | P01 |
| Spread, bps y coste de ejecución | [conceptos/spread_y_costes.md](conceptos/spread_y_costes.md) | P01 |
| Validación de datos de mercado | [conceptos/validacion_de_datos.md](conceptos/validacion_de_datos.md) | P01 |
| Libro de órdenes: profundidad, OBI, microprice y slippage | [conceptos/libro_de_ordenes.md](conceptos/libro_de_ordenes.md) | P02 |
| Operaciones ejecutadas: volumen, VWAP, Trade Imbalance, CVD e intensidad | [conceptos/operaciones_ejecutadas.md](conceptos/operaciones_ejecutadas.md) | P03 |
| Series temporales: velas OHLCV, retornos, volatilidad y objetivo futuro | [conceptos/series_temporales.md](conceptos/series_temporales.md) | P04 |
| Momentum y mean reversion: señales, IC y simulación con costes | [conceptos/momentum_y_reversion.md](conceptos/momentum_y_reversion.md) | P05 |
| Comparación entre exchanges: alineación causal, lead-lag y arbitraje | [conceptos/comparacion_entre_exchanges.md](conceptos/comparacion_entre_exchanges.md) | P06 |
| Derivados perpetuos: basis, open interest, funding, liquidaciones y margen | [conceptos/derivados_perpetuos.md](conceptos/derivados_perpetuos.md) | P07 |
| Costes de ejecución: comisión, spread, profundidad, retraso, umbral y rotación | [conceptos/costes_de_ejecucion.md](conceptos/costes_de_ejecucion.md) | P08 |
| Rentabilidad y riesgo: equity, drawdown, ratios, operaciones y ruina | [conceptos/rentabilidad_y_riesgo.md](conceptos/rentabilidad_y_riesgo.md) | P09 |
| Valoración y macroeconomía: valor temporal, bonos, DCF, inflación, curva y eventos | [conceptos/valoracion_y_macro.md](conceptos/valoracion_y_macro.md) | P10 |
| Eficiencia de mercado: autocorrelación, pruebas múltiples, data snooping y costes | [conceptos/eficiencia_de_mercado.md](conceptos/eficiencia_de_mercado.md) | P11 |
| Alpha, beta y factores: Jensen, multifactor, atribución y factores long-short | [conceptos/alpha_beta_factores.md](conceptos/alpha_beta_factores.md) | P12 |
| Order flow e impacto: reconstrucción L2, OFI, OBI, respuesta del precio y exposición | [conceptos/order_flow_e_impacto.md](conceptos/order_flow_e_impacto.md) | P13 |
| Multiactivo y capitalización: divisa, calendarios, CAGR, drawdown y retorno total | [conceptos/multiactivo_y_capitalizacion.md](conceptos/multiactivo_y_capitalizacion.md) | P14 |
| Regímenes y diversificación: riesgo de cartera, beta y unión point-in-time | [conceptos/regimenes_y_diversificacion.md](conceptos/regimenes_y_diversificacion.md) | P15 |
| Condiciones de ejecución (monitor determinista) | [conceptos/condiciones_de_ejecucion.md](conceptos/condiciones_de_ejecucion.md) | P01 + P02 → `scripts/monitor_ejecucion.py` |

## Conclusiones por práctica

| Práctica | Archivo |
|---|---|
| P01 · Radiografía de un mercado financiero | [conclusiones/P01_market_snapshot.md](conclusiones/P01_market_snapshot.md) |
| P02 · Análisis del libro de órdenes | [conclusiones/P02_order_book.md](conclusiones/P02_order_book.md) |
| P03 · Análisis de operaciones ejecutadas | [conclusiones/P03_trades.md](conclusiones/P03_trades.md) |
| P04 · Motor de series temporales financieras | [conclusiones/P04_time_series.md](conclusiones/P04_time_series.md) |
| P05 · Momentum y Mean Reversion | [conclusiones/P05_momentum_mean_reversion.md](conclusiones/P05_momentum_mean_reversion.md) |
| P06 · Comparación entre exchanges | [conclusiones/P06_cross_exchange.md](conclusiones/P06_cross_exchange.md) |
| P07 · Análisis de derivados financieros | [conclusiones/P07_derivatives.md](conclusiones/P07_derivatives.md) |
| P08 · Motor de costes operativos y ejecución | [conclusiones/P08_transaction_costs.md](conclusiones/P08_transaction_costs.md) |
| P09 · Evaluación de rentabilidad y riesgo | [conclusiones/P09_performance_risk.md](conclusiones/P09_performance_risk.md) |
| P10 · Valoración fundamental y macroeconomía | [conclusiones/P10_fundamental_macro.md](conclusiones/P10_fundamental_macro.md) |
| P11 · Eficiencia del mercado y detección de anomalías | [conclusiones/P11_market_efficiency.md](conclusiones/P11_market_efficiency.md) |
| P12 · Alpha, Beta y factores financieros | [conclusiones/P12_factor_analysis.md](conclusiones/P12_factor_analysis.md) |
| P13 · Order Flow, Market Impact y exposición | [conclusiones/P13_order_flow_market_impact.md](conclusiones/P13_order_flow_market_impact.md) |
| P14 · Laboratorio multiactivo y capitalización | [conclusiones/P14_multi_asset_analysis.md](conclusiones/P14_multi_asset_analysis.md) |
| P15 · Regímenes macroeconómicos y diversificación | [conclusiones/P15_macro_regimes.md](conclusiones/P15_macro_regimes.md) |

## Resumen de lo aprendido por práctica

| Práctica | Archivo |
|---|---|
| P01 · Radiografía de un mercado financiero | [aprendizajes/P01_market_snapshot.md](aprendizajes/P01_market_snapshot.md) |
| P02 · Análisis del libro de órdenes | [aprendizajes/P02_order_book.md](aprendizajes/P02_order_book.md) |
| P03 · Análisis de operaciones ejecutadas | [aprendizajes/P03_trades.md](aprendizajes/P03_trades.md) |
| P04 · Motor de series temporales financieras | [aprendizajes/P04_time_series.md](aprendizajes/P04_time_series.md) |
| P05 · Momentum y Mean Reversion | [aprendizajes/P05_momentum_mean_reversion.md](aprendizajes/P05_momentum_mean_reversion.md) |
| P06 · Comparación entre exchanges | [aprendizajes/P06_cross_exchange.md](aprendizajes/P06_cross_exchange.md) |
| P07 · Análisis de derivados financieros | [aprendizajes/P07_derivatives.md](aprendizajes/P07_derivatives.md) |
| P08 · Motor de costes operativos y ejecución | [aprendizajes/P08_transaction_costs.md](aprendizajes/P08_transaction_costs.md) |
| P09 · Evaluación de rentabilidad y riesgo | [aprendizajes/P09_performance_risk.md](aprendizajes/P09_performance_risk.md) |
| P10 · Valoración fundamental y macroeconomía | [aprendizajes/P10_fundamental_macro.md](aprendizajes/P10_fundamental_macro.md) |
| P11 · Eficiencia del mercado y detección de anomalías | [aprendizajes/P11_market_efficiency.md](aprendizajes/P11_market_efficiency.md) |
| P12 · Alpha, Beta y factores financieros | [aprendizajes/P12_factor_analysis.md](aprendizajes/P12_factor_analysis.md) |
| P13 · Order Flow, Market Impact y exposición | [aprendizajes/P13_order_flow_market_impact.md](aprendizajes/P13_order_flow_market_impact.md) |
| P14 · Laboratorio multiactivo y capitalización | [aprendizajes/P14_multi_asset_analysis.md](aprendizajes/P14_multi_asset_analysis.md) |
| P15 · Regímenes macroeconómicos y diversificación | [aprendizajes/P15_macro_regimes.md](aprendizajes/P15_macro_regimes.md) |

## Convención de colores en los cuadernos

- 🔎 **Naranja:** fase de validación (comprobaciones `assert`).
- ✅ **Verde:** conclusión importante (resumida en esta carpeta).
