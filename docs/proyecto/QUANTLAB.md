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

**Actualización (20-11-2026):** las dos lecciones sin aplicación completa ya tienen práctica: 1.22 en P10 (DCF y sensibilidad) y 1.30 en P16 (laboratorio de payoffs, swap y basis, E6).

## Fases del módulo 1 · Fundamentos financieros

| Fase | Pregunta real que queremos resolver | Prácticas |
|---|---|---|
| 1. Observación del mercado | ¿Qué está sucediendo exactamente en el mercado? | P01 |
| 2. Liquidez | ¿Cuánto dinero puedo negociar y a qué precio? | P02 |
| 3. Presión compradora y vendedora | ¿Qué información aportan las órdenes y las operaciones? | P03, P13 |
| 4. Comportamiento histórico | ¿Cómo se comportan los precios a lo largo del tiempo? | P04 |
| 5. Predicción | ¿Existe información en los datos pasados sobre movimientos futuros? | P05 |
| 6. Mercados interconectados | ¿Qué exchange incorpora antes la información? ¿Hay discrepancias aprovechables? | P06, P17 |
| 7. Derivados | ¿Qué información adicional proporcionan y cómo podemos utilizarlos? | P07, P16 (§10 y E6) |
| 8. Economía de la ejecución | ¿Cuánto cuesta convertir una señal en una operación? | P08 |
| 9. Rentabilidad y riesgo | ¿Cuánto podemos ganar y cuánto podemos perder? | P09 |
| 10. Economía y valoración | ¿Qué factores económicos explican el comportamiento de los activos? | P10, P14 |
| 11. Anomalías y factores | ¿Existe una ventaja real o simplemente estamos expuestos al mercado? | P11, P12, P16 |
| 12. Gestión del capital | ¿Cómo combinamos activos y estrategias para gestionar el riesgo? | P15 |

P17 se usa también al final, como **investigación integradora** de todas las fases.

Los huecos de la auditoría inicial ya tienen ejercicios explícitos:

| Lección | Fase | Dónde se trabaja |
|---|---|---|
| **Capitalización** (1.28) | 10 | P14 (E1–E3: composición, tipos equivalentes y CAGR) |
| **Valoración fundamental** (1.22) | 10 | P10 (DCF, valor terminal y sensibilidad) |
| **Opciones, futuros y swaps** (1.30) | 7 | P16 (§10: payoffs, swap y basis; E6) |
| **Long, short y exposición** (1.27) | 3, 7, 11 y 12 | P07 (posiciones en perpetuos), P13 (exposición neta y bruta), P16 (carteras long-short) |

## Mapa completo por fase

Reúne todo lo documentado en `docs/`: los conceptos de cada fase, dónde están explicados, lo que **ya sabemos con datos reales** y lo que queda abierto. Las cifras vienen de los documentos de conclusiones, con su fecha de captura. Una fase no está terminada hasta que sus conceptos lleguen a **Evaluado** en el registro.

### Fase 1 · Observación del mercado

- **Lecciones:** 1.1 Funcionamiento del mercado · 1.2 Bid, Ask y Spread.
- **Conceptos:** bid, ask, last price y mid · spread absoluto, relativo y en bps · coste implícito de cruzar el spread · comisión por lado (maker/taker) · punto de equilibrio · régimen del spread (ejecutar, normal, esperar) · validación de una cotización (precios finitos, bid > 0, ask > bid).
- **Documentos:** [precios de cotización](../conceptos/precios_de_cotizacion.md) · [spread y costes](../conceptos/spread_y_costes.md) · [condiciones de ejecución](../conceptos/condiciones_de_ejecucion.md) · [validación de datos](../conceptos/validacion_de_datos.md) · [conclusiones P01](../conclusiones/P01_market_snapshot.md) · [aprendizajes P01](../aprendizajes/P01_market_snapshot.md).
- **Ya sabemos:** en Kraken BTC/EUR el spread suele ser de un tick, y la comisión taker del primer nivel (0,80 % por pata, verificada en la web de Kraken Pro) pesa mucho más que el spread.
- **Abierto:** cómo cambia el spread por hora del día y entre exchanges a lo largo de varias sesiones. `python -m radar estacionalidad` ya lo mide (medianas por día y hora, Kruskal-Wallis con los días como repeticiones), pero no concluye hasta tener al menos 5 días por hora; la captura propia los va juntando.

### Fase 2 · Liquidez

- **Lecciones:** 1.3 Order Book · 1.4 Liquidez · 1.10 Microprice.
- **Conceptos:** snapshot de nivel 2 · profundidad por niveles, monetaria y en banda de bps · OBI (desequilibrio del libro) · microprice · VWAP de ejecución · slippage · orden incompleta.
- **Documentos:** [libro de órdenes](../conceptos/libro_de_ordenes.md) · [conclusiones P02](../conclusiones/P02_order_book.md) · [aprendizajes P02](../aprendizajes/P02_order_book.md).
- **Ya sabemos:** en un snapshot real de Kraken (19-11-2026), el spread era de 0,1 € (0,017 bps), pero el mejor nivel tenía tan poco volumen que comprar 0,05 BTC ya recorría dos niveles. Un spread pequeño no garantiza una ejecución barata.
- **Ya sabemos (captura propia, 21–22-11-2026, ~3,3 h por exchange; un solo régimen):**
  - **OFI** (`python -m radar ofi`; Cont, Kukanov y Stoikov, 2014): el flujo de órdenes de un segundo explica el movimiento del mid en ese mismo segundo, con R² del 19–33 % en el mejor nivel y del 33–40 % con 10 niveles (el multinivel mejora, como en Xu, Gould y Howison, 2019). Predecir el FUTURO es mucho más débil: 7 de 36 pruebas confirmadas, casi todas en Bitvavo.
  - **Lead-lag** (`python -m radar leadlag`): Kraken sigue a OKX y a Bitvavo. El retorno de OKX anticipa el de Kraken con 1, 2 y 3 s de retardo (lead-lag ratio 128), más allá de la diferencia de latencia medida. OKX y Bitvavo se mueven casi juntos (correlación 0,78); Kraken apenas se correlaciona con ellos en el mismo segundo (0,10–0,14).
  - **Señales juntas** (`python -m radar senales`): en Kraken, el retorno de los otros exchanges en la ronda ANTERIOR es la señal más fuerte (+0,32 bps por desviación a 5 s, t 11) y aporta información propia; el imbalance también, y el OFI es redundante. Las señales casi no se correlacionan entre sí (|ρ| ≤ 0,21). Ninguna interacción con el spread o la volatilidad se confirma. La mitad del efecto de la señal líder llega en 1 s y no se revierte en 60 s (información, no ruido).
  - **Corrección (22-11-2026):** una primera versión tomaba el retorno de los otros exchanges en la MISMA ronda y daba +0,51 bps (t 18,6), con efecto también en Bitvavo y OKX. Era en parte la trampa de la latencia: las fotos de OKX y Bitvavo llegan ~0,25 s después que la de Kraken y ya traían parte de su futuro. Con la ronda anterior, el efecto se achica en Kraken y desaparece en los otros dos.
- **Captura profesional del flujo** (`python -m radar flujo`): websocket de Kraken (checksum CRC32 de los 10 mejores niveles), OKX (`seqId`/`prevSeqId`; su checksum está obsoleto y siempre vale 0) y Bitvavo (`nonce` consecutivo). Guarda cada cambio del libro (`eventos_libro`), cada trade (`trades`) y un libro reconstruido por segundo (`libros_flujo`); ante un hueco de secuencia o un checksum que no cuadra, registra la incidencia y resincroniza, nunca sigue con un libro roto. Unos 0,8 GB por día.
- **Captura permanente:** `scripts\instalar_captura_permanente.ps1` registra dos tareas programadas de Windows ("QuantLab captura REST" y "QuantLab captura flujo") que arrancan al iniciar sesión, corren ocultas en tramos de una hora y se reinician si fallan. Lo que hacen queda en `data\logs\`. Se quitan con `-Desinstalar`. Con la PC apagada o suspendida no se captura: esos huecos los detecta la puerta de calidad.
- **Markouts y órdenes limit** (`python -m radar markouts`): markout de cada trade desde el taker (selección adversa medida) y llenado de órdenes limit hipotéticas en el mejor precio, separando el llenado seguro (el precio pasó por nuestro nivel) del que depende de la cola, y por signo del imbalance al colocarlas. Necesita horas de captura del websocket para concluir.
- **Abierto:** cómo varía la profundidad en el tiempo; repetir todo en varios días y regímenes.

### Fase 3 · Presión compradora y vendedora

- **Lecciones:** 1.5 Trades y volumen · 1.6 OBI · 1.7 Order Flow (OFI) · 1.8 Market Impact · 1.9 VWAP.
- **Conceptos:** trade y lado agresor · volumen base y nominal · VWAP · volumen con signo · Trade Imbalance (por volumen y por número) · CVD · intensidad · reconstrucción L2 por actualizaciones · OFI de primer nivel · relación contemporánea frente a predictiva · respuesta del precio a un trade (impacto transitorio y permanente) · exposición neta y bruta.
- **Documentos:** [operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md) · [order flow e impacto](../conceptos/order_flow_e_impacto.md) · [conclusiones P03](../conclusiones/P03_trades.md) · [conclusiones P13](../conclusiones/P13_order_flow_market_impact.md) · [aprendizajes P03](../aprendizajes/P03_trades.md) · [aprendizajes P13](../aprendizajes/P13_order_flow_market_impact.md).
- **Ya sabemos:** en Kraken, el OFI entre snapshots explica el 50–56 % del cambio del mid del mismo segundo, pero no predice el siguiente. Esa relación es en buena parte mecánica.
- **Abierto:** OFI exacto evento a evento con WebSocket (secuencias, checksum, `exchange_ts` y `received_ts`), según el contrato de datos de P13.

### Fase 4 · Comportamiento histórico

- **Lecciones:** 1.11 OHLCV · 1.12 Retornos · 1.13 Volatilidad.
- **Conceptos:** vela OHLCV · volumen monetario y VWAP de la vela · velas vacías y de frontera · retorno simple, logarítmico y acumulado · segmentos sin huecos · volatilidad móvil y realizada · anualización · retorno futuro sin mirar el futuro.
- **Documentos:** [series temporales](../conceptos/series_temporales.md) · [conclusiones P04](../conclusiones/P04_time_series.md) · [aprendizajes P04](../aprendizajes/P04_time_series.md).
- **Ya sabemos:** el mercado real fue unas 4 veces más volátil por minuto que la simulación (8,24 frente a 2,02 bps). Una consulta REST de 1.000 trades cubre solo minutos u horas.
- **Abierto:** histórico largo y continuo (Ingeniería de datos).

### Fase 5 · Predicción

- **Lecciones:** 1.14 Momentum · 1.15 Mean Reversion.
- **Conceptos:** momentum · media simple y exponencial · z-score · señales de momentum y reversión · objetivo con entrada en t + 1 · IC de Pearson y Spearman · separación cronológica con purga · retorno neto y coste de equilibrio · autocorrelación y Ljung-Box · falsos positivos y pruebas múltiples (Bonferroni, BH) · data snooping.
- **Documentos:** [momentum y reversión](../conceptos/momentum_y_reversion.md) · [eficiencia de mercado](../conceptos/eficiencia_de_mercado.md) · [conclusiones P05](../conclusiones/P05_momentum_mean_reversion.md) · [conclusiones P11](../conclusiones/P11_market_efficiency.md) · [aprendizajes P05](../aprendizajes/P05_momentum_mean_reversion.md) · [aprendizajes P11](../aprendizajes/P11_market_efficiency.md).
- **Ya sabemos:** una dependencia estadística real (autocorrelación de +0,40 y −0,36 en la simulación) no es explotable si la entrada se retrasa una vela y hay costes. De 500 señales nulas, 20 salieron con p < 0,05 por azar, y ninguna sobrevivió a Bonferroni ni a BH.
- **Abierto:** cualquier señal nueva se contrasta en una muestra nueva, no en la ya usada.

### Fase 6 · Mercados interconectados

- **Lecciones:** 1.16 Correlación · 1.17 Arbitraje · 1.31 Price Discovery.
- **Conceptos:** cotización L1 con hora de solicitud, recepción y evento · latencia y desajuste de relojes · alineación causal y antigüedad · lead-lag · arbitraje entre exchanges con comisiones · episodios de oportunidad · protocolo previo · R² fuera de muestra · bootstrap por bloques · null circular · decisión estadística frente a económica.
- **Documentos:** [comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) · [investigación integral](../conceptos/investigacion_integral.md) · [conclusiones P06](../conclusiones/P06_cross_exchange.md) · [conclusiones P17](../conclusiones/P17_integrated_research.md) · [aprendizajes P06](../aprendizajes/P06_cross_exchange.md) · [aprendizajes P17](../aprendizajes/P17_integrated_research.md).
- **Ya sabemos:** en 30 minutos reales (20-11-2026), Kraken no anticipa a OKX: la correlación máxima es en el mismo segundo (0,38) y Bitvavo va por delante de Kraken. La mitad de las señales no tenía profundidad en OKX, y cada operación perdía unos 25 bps. El reloj del equipo no estaba sincronizado con el de OKX.
- **Abierto:** varias sesiones con WebSocket y reloj NTP; el protocolo alternativo E1 de P17, en una captura nueva.

### Fase 7 · Derivados

- **Lecciones:** 1.18 Spot y derivados · 1.27 Long, Short y exposición · 1.30 Opciones, futuros y swaps.
- **Conceptos:** perpetuo lineal · basis · mark e índice · open interest · funding y su pago · liquidaciones · margen y umbral de mantenimiento · cobertura con perpetuos · carry de un perpetuo con funding solo observado · payoffs de futuro, call y put · swap de tipos · basis anualizado.
- **Documentos:** [derivados perpetuos](../conceptos/derivados_perpetuos.md) · [construcción de factores](../conceptos/construccion_de_factores.md) (§ derivados) · [conclusiones P07](../conclusiones/P07_derivatives.md) · [conclusiones P16](../conclusiones/P16_factor_construction.md) · [aprendizajes P07](../aprendizajes/P07_derivatives.md).
- **Ya sabemos:** en una captura de OKX (BTC-USDT), el basis era de −5,1 bps y el open interest, de 33.061 BTC. Una sola captura no sirve para estudiar el funding ni las liquidaciones a lo largo del tiempo.
- **Abierto:** histórico horario de basis, funding, OI y liquidaciones; valoración de opciones (Black-Scholes, paridad put-call, griegas).

### Fase 8 · Economía de la ejecución

- **Lecciones:** 1.8 Market Impact · 1.19 Costes operativos.
- **Conceptos:** comisión maker y taker · coste de spread, de profundidad y de retraso · implementation shortfall · ida y vuelta · umbral de equilibrio exacto · markout · rotación · coste de equilibrio de una estrategia · atribución de costes por tramos · dilema impacto frente a riesgo de timing · algoritmos de ejecución.
- **Algoritmos de ejecución (escalera, cada uno comparado con el anterior sobre los mismos datos):**
  1. **TWAP:** la orden se reparte en trozos iguales a intervalos fijos. Referencia simple.
  2. **Almgren-Chriss (2001):** trayectoria óptima que equilibra el impacto de mercado y la varianza del precio durante la ejecución, según la aversión al riesgo. Sigue siendo el modelo de referencia de la ejecución óptima.
  3. **Almgren-Chriss adaptativo con señales:** la velocidad de ejecución se ajusta con el desequilibrio del libro de la Fase 2 (acelerar cuando el precio tiende a moverse en contra, frenar cuando tiende a favor). Es la línea que sigue la investigación actual: estrategias que mejoran Almgren-Chriss explotando señales del mercado.
  - Medida común: implementation shortfall frente al mid de decisión, con su media y su dispersión.
  - Datos: la captura guarda 50 niveles por lado del libro en la fuente `libros`; `python -m radar simular` hace el replay de los tres escalones.
  - El adaptativo es el primer consumidor de las conclusiones del análisis: lee de `estudios` un hallazgo **confirmado** de un estudio que terminó antes de las ventanas simuladas (fuera de muestra) y adelanta o retrasa cada trozo según el imbalance del libro de ese momento, con una intensidad que se estudia como sensibilidad.
- **Documentos:** [costes de ejecución](../conceptos/costes_de_ejecucion.md) · [conclusiones P08](../conclusiones/P08_transaction_costs.md) · [aprendizajes P08](../aprendizajes/P08_transaction_costs.md).
- **Ya sabemos:** con 10 bps por lado, el mid tiene que subir 21,67 bps solo para empatar una ida y vuelta. En Kraken, una ida y vuelta de 0,01 BTC costaría unos 20 bps, casi todo comisión. Comisiones taker verificadas el 21-11-2026 en sus webs oficiales: Kraken 0,80 %, OKX 0,20 % con cuenta solo spot (0,10 % con spot y derivados), Bitvavo 0,25 %. Slippage de una compra a mercado en Kraken (21-11-2026): 0,87 € con 50.000 € y 11,44 € con 100.000 €; crece más rápido que el importe. Replay en Kraken (21-11-2026, unas 2 h, 119 ventanas de 60 s, 100.000 € en 10 trozos, comisiones incluidas): sin impacto permanente, TWAP y Almgren-Chriss κT=1 cuestan unos 1,1 bps menos que todo de golpe, con más dispersión; con 5 bps de impacto permanente por 100.000 €, todo de golpe es lo más barato. El adaptativo (señal de Kraken, banda 5 bps, horizonte 5 rondas) no mejora a Almgren-Chriss: ahorra 0,01 bps y añade dispersión, porque lo que gana en timing lo pierde en slippage al comprar trozos más grandes. Un solo régimen de mercado: falta repetirlo en días distintos.
- **Abierto:** órdenes maker y su riesgo de no ejecutarse; ejecución con reinforcement learning (investigación activa en 2025–2026, con mejoras sobre Almgren-Chriss cuando sus supuestos no se cumplen, pero sin un ganador claro y con mucho riesgo de sobreajuste).
- **Fuentes de los algoritmos:** Almgren y Chriss (2001), *Optimal execution of portfolio transactions* · [RL para ejecución óptima en tiempo continuo dentro del modelo Almgren-Chriss (Finance and Stochastics, 2026)](https://link.springer.com/content/pdf/10.1007/s00780-026-00589-5.pdf) · [Ejecución óptima con RL y movimiento browniano fraccional (arXiv 2611.11373)](https://arxiv.org/abs/2611.11373) · [Optimal Execution Using Reinforcement Learning (arXiv 2306.17178)](https://arxiv.org/pdf/2306.17178).

### Fase 9 · Rentabilidad y riesgo

- **Lecciones:** 1.20 Rentabilidad y riesgo.
- **Conceptos:** curva de capital · drawdown y máximo drawdown · CAGR · volatilidad anualizada · Sharpe, Sortino y Calmar · acierto, payoff, profit factor y esperanza · retorno de recuperación · riesgo de ruina · estabilidad entre periodos.
- **Documentos:** [rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) · [conclusiones P09](../conclusiones/P09_performance_risk.md) · [aprendizajes P09](../aprendizajes/P09_performance_risk.md).
- **Ya sabemos:** una caída exige una subida mayor para recuperarse, y una esperanza negativa lleva a la ruina con el tiempo. Las métricas solo valen con datos diarios consecutivos y sin anualizar capturas cortas.
- **Abierto:** aplicarlas a una estrategia real con su histórico de operaciones.

### Fase 10 · Economía y valoración

- **Lecciones:** 1.21 Clases de activos · 1.22 Valoración fundamental · 1.23 Macroeconomía · 1.28 Capitalización.
- **Conceptos:** valor temporal del dinero · precio de un bono · DCF, valor terminal y valor por acción · inflación interanual y rentabilidad real (Fisher) · pendiente de la curva · sorpresa macro y disponibilidad (point-in-time) · composición, tipos equivalentes y CAGR · conversión a EUR y riesgo de divisa · retorno de precio, total y real · drag de volatilidad.
- **Documentos:** [valoración y macro](../conceptos/valoracion_y_macro.md) · [multiactivo y capitalización](../conceptos/multiactivo_y_capitalizacion.md) · [conclusiones P10](../conclusiones/P10_fundamental_macro.md) · [conclusiones P14](../conclusiones/P14_multi_asset_analysis.md) · [aprendizajes P10](../aprendizajes/P10_fundamental_macro.md) · [aprendizajes P14](../aprendizajes/P14_multi_asset_analysis.md).
- **Ya sabemos:** en 2021–2025, medido en EUR, el oro tuvo el mayor CAGR (20,5 %) con una caída máxima del 9 %, y BTC rindió parecido (19,8 %) con un 57 % de volatilidad. SPY ganó 6 puntos más en EUR que en USD por la depreciación del euro. El ranking cambia por completo entre las dos mitades del periodo. La inflación de EE. UU. tocó su máximo (6,33 %) en enero de 2023.
- **Abierto:** datos macro point-in-time (vintages de ALFRED); otras clases de activos (materias primas, divisas, crédito).

### Fase 11 · Anomalías y factores

- **Lecciones:** 1.24 Eficiencia del mercado · 1.25 Alpha y Beta · 1.26 Factores financieros.
- **Conceptos:** eficiencia débil y paseo aleatorio · retorno activo y excedente · alpha y beta de Jensen · errores HAC · modelos multifactor y atribución · validación con exposiciones congeladas · tracking error e information ratio · beta móvil · scores conocidos antes de invertir · carteras long-short por cuantiles · rotación y coste de equilibrio · Fama-French 3 y 5 factores · falsos factores y correlación frente a independencia.
- **Documentos:** [eficiencia de mercado](../conceptos/eficiencia_de_mercado.md) · [alpha, beta y factores](../conceptos/alpha_beta_factores.md) · [construcción de factores](../conceptos/construccion_de_factores.md) · [conclusiones P12](../conclusiones/P12_factor_analysis.md) · [conclusiones P16](../conclusiones/P16_factor_construction.md) · [aprendizajes P12](../aprendizajes/P12_factor_analysis.md) · [aprendizajes P16](../aprendizajes/P16_factor_construction.md).
- **Ya sabemos:** una regla real de momentum sobre BTC/EUR perdió menos que BTC por estar menos expuesta (beta 0,27), no por alpha. Con los factores oficiales de Fama-French, SPY tiene alpha 0 y R² de 0,996. En un universo de 20 criptomonedas, ni momentum, ni baja volatilidad, ni iliquidez sobreviven a la validación. Un factor sin prima puede heredar la de otro con el que está correlacionado por azar.
- **Abierto:** un universo cripto sin sesgo de supervivencia; ordenaciones dobles para separar factores.

### Fase 12 · Gestión del capital

- **Lecciones:** 1.27 Long, Short y exposición · 1.29 Diversificación.
- **Conceptos:** retorno y volatilidad de una cartera · contribución al riesgo · varianza de dos activos y peso de varianza cero · riesgo sistemático frente a idiosincrático · curva de diversificación · regímenes de tipos y de balance · correlaciones condicionales · unión point-in-time con antigüedad máxima.
- **Documentos:** [regímenes y diversificación](../conceptos/regimenes_y_diversificacion.md) · [conclusiones P15](../conclusiones/P15_macro_regimes.md) · [aprendizajes P15](../aprendizajes/P15_macro_regimes.md).
- **Ya sabemos:** en una cartera 25/35/30/10 en EUR (2021–2025), BTC aportaba el 77 % del riesgo con el 25 % del peso, y la volatilidad de la cartera (17,2 %) era muy inferior a la media ponderada (24,0 %). La diversificación no elimina el riesgo del factor común.
- **Abierto:** el análisis por régimen con datos reales está bloqueado hasta tener el histórico macro point-in-time.

### Investigación integradora · P17

P17 recorre el ciclo completo: protocolo fijado antes de mirar, captura auditada, prueba estadística, ejecución con costes y profundidad, incertidumbre y decisión. Su resultado (no se aprueba la hipótesis, por razones que se pueden explicar) es el modelo de cómo cerrar cada investigación de QuantLab. Ver [investigación integral](../conceptos/investigacion_integral.md).

### Huecos de profundidad

Todas las lecciones tienen práctica, pero algunas solo se tratan en lo básico:

| Lección | Qué falta |
|---|---|
| 1.30 Opciones, futuros y swaps | Valoración de opciones (Black-Scholes, paridad put-call, griegas) y swaps de varios periodos |
| 1.21 Clases de activos | Materias primas, divisas como activo y crédito |
| 1.17 Arbitraje | Cash-and-carry con perpetuos como estrategia completa |
| 1.23 y 1.29 con datos reales | Análisis por régimen: falta el histórico macro point-in-time |

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
| 1.27 | Long, Short y exposición | 3, 7, 11, 12 | — | — | — | — | — |
| 1.28 | Capitalización | 10 | — | — | — | — | — |
| 1.29 | Diversificación | 12 | — | — | — | — | — |
| 1.30 | Opciones, futuros y swaps | 7 | — | — | — | — | — |
| 1.31 | Price Discovery | 6 | — | — | — | — | — |

### Conceptos transversales

No son lecciones del módulo 1, pero aparecen en las prácticas y sin ellos los resultados no se pueden interpretar. Siguen el mismo registro.

| Código | Concepto | Dónde se trabaja | Comprendido | Programado | Investigado con datos reales | Aplicado | Evaluado |
|---|---|---|---|---|---|---|---|
| T1 | Validación de datos, point-in-time, look-ahead y vintages | P01–P04, P10, P15, P17 | — | — | — | — | — |
| T2 | Perpetuos: funding, basis, open interest, margen y liquidaciones | P07 | — | — | — | — | — |
| T3 | Bonos, curva de tipos, inflación y eventos macro | P10, P15 | — | — | — | — | — |
| T4 | Riesgo de divisa | P14 | — | — | — | — | — |
| T5 | Regímenes y correlaciones condicionales | P15 | — | — | — | — | — |
| T6 | Rotación, coste de equilibrio y capacidad | P08, P16 | — | — | — | — | — |
| T7 | Inferencia: IC, errores HAC, Ljung-Box, pruebas múltiples (Bonferroni, BH), Fisher z, bootstrap por bloques y null circular | P05, P11–P17 | — | — | — | — | — |
| T8 | Método de investigación: protocolo previo, corte cronológico, R² fuera de muestra y decisión estadística frente a económica | P05, P11, P16, P17 | — | — | — | — | — |

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
