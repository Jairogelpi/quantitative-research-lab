# QuantLab · Laboratorio personal de investigación financiera

## Objetivo

Construir desde cero un sistema capaz de **observar** los mercados financieros, **comprender** su funcionamiento, **descubrir** patrones, **investigar** oportunidades, **evaluar** su rentabilidad y **gestionar** el riesgo asociado.

No es una herramienta para decidir dónde invertir cada mes: es nuestra propia **infraestructura de investigación cuantitativa**. Una mesa de inversión personal sería solo una de sus aplicaciones.

La meta es convertirnos en investigadores cuantitativos capaces de **descubrir, validar y explotar** posibles ineficiencias de los mercados. Si encontramos ventajas reales, tendremos las herramientas para validarlas; si no las encontramos, también sabremos demostrarlo.

Primero aprendemos a entender el mercado; después investigamos cómo ganar dinero en él.

## Por qué no basta con la "mesa de inversión personal"

La primera propuesta (un informe mensual de inversión en 7 fases) se contrastó con las 31 lecciones del módulo 1. Es una valoración del diseño del proyecto, no del código implementado ni de las competencias adquiridas.

| Cobertura | Nº de conceptos |
|---|---|
| Bien contemplados | 17 |
| Parciales u opcionales | 12 |
| Sin aplicación completa | 2 (1.22 Valoración fundamental, 1.30 Opciones, futuros y swaps) |

El problema no es que no se puedan incorporar, sino que **generar un informe mensual no obliga a usarlos todos**. Por eso el proyecto se organiza alrededor de preguntas de investigación, no de una aplicación concreta.

## Fases del módulo 1 · Fundamentos financieros

| Fase | Pregunta real que queremos resolver | Prácticas |
|---|---|---|
| 1. Observación del mercado | ¿Qué está sucediendo exactamente en el mercado? | P01 |
| 2. Liquidez | ¿Cuánto dinero puedo negociar y a qué precio? | P02 |
| 3. Presión compradora y vendedora | ¿Qué información aportan las órdenes y las operaciones? | P03, P13 |
| 4. Comportamiento histórico | ¿Cómo se comportan los precios a lo largo del tiempo? | P04 |
| 5. Predicción | ¿Existe información en los datos pasados sobre movimientos futuros? | P05 |
| 6. Mercados interconectados | ¿Qué exchange incorpora antes la información? ¿Hay discrepancias aprovechables? | P06, P17 |
| 7. Derivados | ¿Qué información adicional proporcionan y cómo podemos utilizarlos? | P07 |
| 8. Economía de la ejecución | ¿Cuánto cuesta convertir una señal en una operación? | P08 |
| 9. Rentabilidad y riesgo | ¿Cuánto podemos ganar y cuánto podemos perder? | P09 |
| 10. Economía y valoración | ¿Qué factores económicos explican el comportamiento de los activos? | P10, P14 |
| 11. Anomalías y factores | ¿Existe una ventaja real o simplemente estamos expuestos al mercado? | P11, P12, P16 |
| 12. Gestión del capital | ¿Cómo combinamos activos y estrategias para gestionar el riesgo? | P15 |

P17 se usa también al final, como **investigación integradora** de todas las fases.

Para cerrar los huecos de la auditoría se añaden ejercicios explícitos en su fase:

- **Capitalización** (1.28) → fase 10.
- **Valoración fundamental** (1.22) → fase 10.
- **Opciones, futuros y swaps** (1.30) → fase 7.
- **Long, short y exposición** (1.27) → fases 7 y 12.

## Método: cómo aprendemos cada concepto

No construimos un sistema gigantesco con agentes de IA para luego no saber interpretar sus resultados. **Cada concepto es una investigación individual**, con nueve pasos. Ejemplo con el spread:

| # | Paso | Qué hacemos (ejemplo: spread) |
|---|---|---|
| 1 | Comprensión | Qué es el spread, por qué existe y quién se beneficia de él. |
| 2 | Obtención | De qué datos originales podemos calcularlo en nuestros tres exchanges. |
| 3 | Implementación | Programar nosotros mismos su cálculo. |
| 4 | Exploración | Estudiar su distribución por activo, exchange y hora del día. |
| 5 | Relaciones | Investigar su relación con la liquidez, el volumen y la volatilidad. |
| 6 | Hipótesis | Investigar si contiene información sobre movimientos futuros. |
| 7 | Aplicación económica | Determinar cuánto afecta a nuestra capacidad de ganar dinero. |
| 8 | Conclusiones | Documentar qué hemos descubierto, sus limitaciones y para qué nos sirve. |
| 9 | Evaluación | Resolver un problema nuevo **sin ayuda de la IA**. |

**Regla:** no se pasa al siguiente concepto solo porque su fórmula esté bien programada.

## Registro de competencias

Cada concepto tiene cinco estados independientes, para no confundir haber leído una lección con dominarla.

- **Comprendido:** sé explicarlo con mis palabras y con un ejemplo hecho a mano.
- **Programado:** lo he implementado yo, con tests.
- **Investigado con datos reales:** lo he estudiado con datos de nuestros exchanges.
- **Aplicado:** lo he usado para tomar o rechazar una decisión económica.
- **Evaluado:** he resuelto un problema nuevo sin ayuda.

Leyenda: `—` pendiente · `🟡` en curso · `✅` conseguido.

| Lección | Concepto | Fase | Comprendido | Programado | Investigado con datos reales | Aplicado | Evaluado |
|---|---|---|---|---|---|---|---|
| 1.1 | Funcionamiento del mercado | 1 | — | — | — | — | — |
| 1.2 | Bid, Ask y Spread | 1 | — | — | — | — | — |
| 1.3 | Order Book | 2 | — | — | — | — | — |
| 1.4 | Liquidez | 2 | — | — | — | — | — |
| 1.5 | Trades y volumen | 3 | — | — | — | — | — |
| 1.6 | Order Book Imbalance (OBI) | 3 | — | — | — | — | — |
| 1.7 | Order Flow (OFI) | 3 | — | — | — | — | — |
| 1.8 | Market Impact | 3, 8 | — | — | — | — | — |
| 1.9 | VWAP | 3 | — | — | — | — | — |
| 1.10 | Microprice | 2 | — | — | — | — | — |
| 1.11 | OHLCV | 4 | — | — | — | — | — |
| 1.12 | Retornos | 4 | — | — | — | — | — |
| 1.13 | Volatilidad | 4 | — | — | — | — | — |
| 1.14 | Momentum | 5 | — | — | — | — | — |
| 1.15 | Mean Reversion | 5 | — | — | — | — | — |
| 1.16 | Correlación | 6 | — | — | — | — | — |
| 1.17 | Arbitraje | 6 | — | — | — | — | — |
| 1.18 | Spot y derivados | 7 | — | — | — | — | — |
| 1.19 | Costes operativos | 8 | — | — | — | — | — |
| 1.20 | Rentabilidad y riesgo | 9 | — | — | — | — | — |
| 1.21 | Clases de activos | 10 | — | — | — | — | — |
| 1.22 | Valoración fundamental | 10 | — | — | — | — | — |
| 1.23 | Macroeconomía | 10 | — | — | — | — | — |
| 1.24 | Eficiencia del mercado | 11 | — | — | — | — | — |
| 1.25 | Alpha y Beta | 11 | — | — | — | — | — |
| 1.26 | Factores financieros | 11 | — | — | — | — | — |
| 1.27 | Long, Short y exposición | 7, 12 | — | — | — | — | — |
| 1.28 | Capitalización | 10 | — | — | — | — | — |
| 1.29 | Diversificación | 12 | — | — | — | — | — |
| 1.30 | Opciones, futuros y swaps | 7 | — | — | — | — | — |
| 1.31 | Price Discovery | 6 | — | — | — | — | — |

## QuantLab a largo plazo

El mismo proyecto continúa durante los doce módulos de la formación.

| Módulo formativo | Qué añadiremos a QuantLab |
|---|---|
| Fundamentos financieros | Motor de análisis financiero. |
| Microestructura avanzada | Análisis detallado del comportamiento del mercado. |
| Ingeniería de datos | Infraestructura histórica y en tiempo real. |
| Matemáticas y estadística | Motor de cálculo y contrastes estadísticos. |
| Econometría | Modelización de series financieras. |
| Metodología de investigación | Sistema reproducible de experimentación. |
| Alpha Research | Descubrimiento y validación de señales. |
| Financial ML e IA | Modelos predictivos avanzados. |
| Backtesting | Simulación histórica rigurosa. |
| Carteras y riesgo | Asignación y protección del capital. |
| Ejecución algorítmica | Simulación y eventual ejecución controlada de estrategias. |
| Investigación independiente | Investigaciones originales con metodología profesional. |

## Por dónde empezamos

Aprovechamos la infraestructura de captura que ya tenemos para Kraken, OKX y Bitvavo (`src/quantlab/p01`, `p02`, `p03`, `p06`).

### Investigación 001 · Radiografía del mercado de Bitcoin

Primero estudiamos **qué es cada dato que recibimos**:

- cómo se genera,
- qué representa,
- cómo podemos verificarlo,
- qué información económica contiene.

Después avanzamos variable por variable, y solo construimos o ampliamos el sistema cuando entendamos por qué hace falta cada componente.

Todavía **no** decidimos cuánto dinero invertir, qué cartera construir ni qué estrategia operar.

Relacionado: [README de la documentación](../README.md)
