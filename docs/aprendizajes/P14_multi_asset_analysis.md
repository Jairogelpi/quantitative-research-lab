# P14 · Laboratorio multiactivo y capitalización · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P14_multi_asset_analysis.ipynb`
**Datos de ejemplo:** precios sintéticos y cierres reales de BTC, acciones, bonos, oro, renta variable global y EURUSD

Hasta P13 solo mirábamos BTC. P14 lo compara con otras clases de activos desde el punto de vista de un inversor en **euros**, y repasa las bases de la capitalización: componer, descontar y anualizar.

## 1. Variables de entrada

| Variable | Qué es | Ejemplo |
|---|---|---|
| `BTC`, `Acciones`, `Bonos`, `Oro`, `Global` | Precios en USD (cierres ajustados) | BTC-USD, SPY, IEF, GLD, VT |
| `EURUSD` | Dólares por euro | 1,22 |
| `START`, `END` | Periodo (END exclusivo) | 2021-01-01 a 2026-01-01 |
| `INITIAL_CAPITAL` | Capital de referencia | 1.000 € |
| `rate`, `periods` | Tipo por periodo y número de periodos | 5 %, 5 años |
| `dividend` | Renta cobrada en el periodo | 4 € |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Valor futuro | C₀ · (1 + r)^n | 1.000 · 1,1² = **1.210 €** | ¿Cuánto tendré? |
| Valor actual | FV / (1 + r)^n | 10.000 / 1,05⁵ = **7.835,26 €** | ¿Cuánto vale hoy un cobro futuro? |
| Retorno compuesto | ∏(1 + r_t) − 1 | (1,5 · 0,5) − 1 = **−25 %** | ¿Qué gané de verdad? |
| Media geométrica | (1 + R)^{1/n} − 1 | 0,75^{1/2} − 1 = **−13,4 %** | Retorno constante equivalente |
| Tipo equivalente | (1 + r)^{1/12} − 1 | 1,12^{1/12} − 1 = **0,9489 %** | Tipo mensual del 12 % anual |
| CAGR | (V_final / V_inicial)^{1/años} − 1 | 2^{1/10} − 1 = **7,18 %** | Crecimiento anual compuesto |
| Precio en EUR | precio USD / EURUSD | 120 / 1,20 = **100 €** | ¿Cuánto vale en euros? |
| Retorno en EUR | (1 + r_USD) / (1 + r_EURUSD) − 1 | 1,10 / 1,05 − 1 = **4,76 %** | Efecto activo + divisa |
| Volatilidad | s(r_semanal) · √52 | BTC real: **57,4 %** | Dispersión anual |
| Drawdown | E_t / máx E − 1 | BTC real: **−72,2 %** | Peor caída |
| Drag | 52 · (media aritmética − geométrica) | BTC real: **16,3 pp** | Lo que la volatilidad resta |
| Retorno total | (P_final + D) / P_inicial − 1 | (98 + 4) / 100 − 1 = **+2 %** | Precio más rentas |
| Retorno real | (1 + n) / (1 + π) − 1 | 1,08 / 1,05 − 1 = **2,86 %** | Ganancia en poder adquisitivo |

## 3. Reglas de validación (antes de calcular)

- `prepare_weekly` rechaza fechas duplicadas, precios o FX ≤ 0 o infinitos, la ausencia de sesiones comunes, menos de 53 semanas o **una semana interior sin datos**.
- Solo se usan días de lunes a viernes con dato en **todas** las series; se descartan la primera y la última semana.
- No se rellenan precios ni con ceros ni hacia atrás.
- La reconstrucción (1 + r_USD) / (1 + r_EURUSD) − 1 debe coincidir con el retorno en EUR.
- Con cierres ajustados, los dividendos no se suman otra vez.
- Si falla la descarga, se lanza el error: nunca se sustituye por datos simulados.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Retornos que suman 0 con volatilidad > 0 | El retorno compuesto es negativo. |
| EURUSD sube | El retorno en EUR de un activo en USD es menor que en USD. |
| Una semana interior sin dato común | No hay serie semanal válida: se detiene. |
| Mayor volatilidad con la misma media aritmética | Mayor drag y menor crecimiento compuesto. |
| Precio de cierre ajustado | El retorno ya incluye los dividendos reinvertidos. |
| CAGR frente a 100 % / años | El CAGR siempre es menor (salvo en 1 año). |

**Lo que NO puede concluir:**

- Qué activo rendirá más en el futuro: el ranking cambia entre las dos mitades de solo cinco años.
- Que los cierres "del mismo día" sean simultáneos.
- Que Yahoo Finance sea un dato point-in-time.
- Nada sobre activos reales a partir de los parámetros sintéticos.

## 5. Para qué sirve

- **Comparar inversiones con honestidad.** Moneda común, calendario común y métricas compuestas: sin eso, las comparaciones engañan.
- **Entender el coste de la volatilidad.** El drag explica por qué un activo muy volátil puede crecer menos que su media aritmética.
- **Medir el riesgo de divisa.** Para un inversor en euros, el dólar es un activo más (con su propia volatilidad del 7,5 %).
- **No confundir retornos.** Precio, total y real responden a preguntas distintas.
- **Base para P15.** Los retornos semanales en EUR de P14 alimentan el análisis de diversificación y regímenes.

## Referencias

- Código: [`src/quantlab/p14/multi_asset.py`](../../src/quantlab/p14/multi_asset.py)
- Pruebas: [`tests/test_multi_asset.py`](../../tests/test_multi_asset.py)
- Conclusiones: [conclusiones/P14_multi_asset_analysis.md](../conclusiones/P14_multi_asset_analysis.md)
- Conceptos: [multiactivo y capitalización](../conceptos/multiactivo_y_capitalizacion.md) · [rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md)
- Aprendizaje anterior: [P13 · Order Flow, Market Impact y exposición](P13_order_flow_market_impact.md)
