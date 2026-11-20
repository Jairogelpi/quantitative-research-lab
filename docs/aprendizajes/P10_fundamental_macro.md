# P10 · Valoración fundamental y macroeconomía · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P10_fundamental_macro.ipynb`
**Datos de ejemplo:** un bono y una empresa hipotéticos, indicadores macro sintéticos, publicaciones sintéticas de IPC y series reales de FRED

Hasta P09 todo giraba alrededor del precio y sus movimientos. P10 se pregunta qué hay **detrás** del precio: cuánto valen los flujos futuros, cómo influyen los tipos y la inflación, y cómo medir la reacción del mercado a un dato macro sin hacer trampas con el tiempo.

## 1. Variables de entrada

| Variable | Qué es | Ejemplo |
|---|---|---|
| `cashflows` | Flujos futuros por año | 100, 104, 108,2, 112,5, 117 M€ |
| `rate` (r) | Tasa de descuento anual | 8 % |
| `terminal_growth` (g) | Crecimiento perpetuo tras el último año | 2 % |
| `net_debt`, `shares` | Deuda financiera neta y número de acciones | 300 M€, 100 M |
| `face`, `coupon_rate`, `yield_rate`, `years` | Nominal, cupón, rendimiento exigido y vencimiento del bono | 1.000 €, 4 %, 5 %, 5 años |
| `cpi` | Índice de precios mensual | CPIAUCSL (FRED) |
| `yield_2y_pct`, `yield_10y_pct` | Rendimientos del Tesoro | DGS2, DGS10 (FRED) |
| `available_at` | Hora real de publicación del dato, en UTC | IPC de EE. UU.: 8:30 de Nueva York = 13:30 UTC en invierno y 12:30 UTC en horario de verano |
| `consensus_pct`, `actual_pct` | Previsión y dato publicado | 3,1 % y 3,26 % |
| `THRESHOLD_PP` | Umbral de sorpresa, fijado antes de mirar | 0,15 pp |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Valor actual | CF / (1 + r)^t | 110 / 1,10 = **100 €** | ¿Cuánto vale hoy un cobro futuro? |
| Precio del bono | Σ cupón / (1 + y)^t + nominal / (1 + y)^N | Al 5 %: **956,71 €** | ¿Cuánto pagar por el bono? |
| Sensibilidad del bono | precio(y₁) / precio(y₀) − 1 | 10 años, 4 % → 5 %: **−7,72 %** | ¿Cuánto pierde si suben los tipos? |
| Valor terminal | FCFF_N · (1 + g) / (r − g) | 117 · 1,02 / 0,06 = 1.989 M€ (1.353,5 M€ hoy) | ¿Cuánto vale lo que viene después? |
| Valor de empresa | Flujos descontados + valor terminal descontado | **1.783,43 M€** | ¿Cuánto vale el negocio? |
| Valor por acción | (EV − deuda neta) / acciones | (1.783,43 − 300) / 100 = **14,83 €** | ¿Cuánto vale cada acción? |
| Inflación interanual | IPC_t / IPC_{mismo mes, año anterior} − 1 | Enero de 2023: **6,33 %** | ¿Cuánto subieron los precios en un año? |
| Rentabilidad real | (1 + n) / (1 + π) − 1 | 1,15 / 1,10 − 1 = **4,55 %** | ¿Cuánto se gana de verdad? |
| Pendiente de la curva | (10 años − 2 años) × 100 | Mínimo real: **−108 bps** | ¿Está invertida la curva? |
| Sorpresa | dato − consenso | 3,256 − 3,107 = **+0,149 pp** (bajo el umbral de 0,15: «En línea») | ¿Qué no esperaba el mercado? |
| Reacción | precio(t + h) / precio(antes de t) − 1 | "Inferior" a 1 h: **+45,6 bps** | ¿Cómo reaccionó el precio? |

## 3. Reglas de validación (antes de calcular)

- `present_value` exige una tasa > −100 % y flujos finitos; `dcf`, un último flujo positivo y r > g > −1 (si g ≥ r, el valor terminal es infinito o negativo).
- La inflación se calcula **por fecha**: si falta un mes, queda como hueco y nunca se compara con el mes equivocado.
- No se mezclan frecuencias: el IPC es mensual y la curva, diaria.
- `validate_events_prices` rechaza IDs u horas duplicadas, un consenso ausente o **posterior** a la publicación, datos no finitos, precios duplicados o ≤ 0 y, en CSV, timestamps sin zona horaria.
- El precio previo es **estrictamente anterior** a la publicación, con 60 minutos de antigüedad máxima; el posterior nunca puede ser anterior a la publicación.
- La separación es cronológica, sin solapes y sin eventos de desarrollo cuyo horizonte toque la frontera. El umbral de sorpresa se fija antes de mirar.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Rendimiento exigido > cupón | El bono cotiza por debajo del nominal. |
| Mayor vencimiento, mismo cambio de tipos | Mayor variación porcentual del precio. |
| Mayor tasa de descuento, mismos flujos | Menor valor de empresa y por acción. |
| g ≥ r | El DCF no está definido. |
| Rendimiento a 10 años < rendimiento a 2 años | La curva está invertida. |
| Consenso posterior a la publicación | El evento no es válido: sería información futura. |
| Sin precio previo en los 60 minutos anteriores | No se mide la reacción de ese evento. |
| Sin consenso | No hay sorpresa que calcular. |
| Un mes ausente en el IPC | La inflación de ese mes, y la de 12 meses después, no se calcula. |

**Lo que NO puede concluir:**

- Que una acción esté cara o barata por una diferencia pequeña con el DCF: los supuestos mueven el valor mucho más.
- Que una curva invertida anuncie una recesión.
- Que la reacción del mercado sea un retorno que se podría haber capturado: incluye el movimiento de la propia noticia.
- Nada sobre el mercado real a partir del efecto sintético, que está programado.
- Qué se sabía en una fecha pasada a partir de la serie revisada de FRED.

## 5. Para qué sirve

- **Valorar con criterio.** El valor temporal, los bonos y el DCF muestran cómo el tipo de interés y el crecimiento esperado determinan el valor, y lo frágil que es una valoración.
- **Entender el entorno macro.** Inflación, tipos y curva explican por qué cambian las valoraciones y el apetito por el riesgo.
- **Medir reacciones a noticias sin trampas.** El estudio de eventos enseña a separar lo que se sabía antes de lo que se supo después.
- **Detectar problemas en datos reales.** Un mes que falta, una serie revisada o una publicación sin hora pueden invalidar un backtest entero.
- **Saber cuándo no hay datos.** Sin consenso archivado, la respuesta honesta es "evidencia insuficiente", no inventarlo.
- **Base para P11.** La hipótesis del E8 se contrastará frente al azar con tests de permutación.

## Referencias

- Código: [`src/quantlab/p10/valuation_macro.py`](../../src/quantlab/p10/valuation_macro.py)
- Pruebas: [`tests/test_valuation_macro.py`](../../tests/test_valuation_macro.py)
- Conclusiones: [conclusiones/P10_fundamental_macro.md](../conclusiones/P10_fundamental_macro.md)
- Conceptos: [valoración y macro](../conceptos/valoracion_y_macro.md) · [series temporales](../conceptos/series_temporales.md) · [validación de datos](../conceptos/validacion_de_datos.md)
- Aprendizaje anterior: [P09 · Evaluación de rentabilidad y riesgo](P09_performance_risk.md)
