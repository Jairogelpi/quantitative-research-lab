# P11 · Eficiencia del mercado y detección de anomalías · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P11_market_efficiency.ipynb`
**Datos de ejemplo:** tres mercados sintéticos con una dependencia conocida, 500 señales sin información y velas reales de Kraken

P05, P09 y P10 terminaban una y otra vez en "evidencia insuficiente". P11 da las herramientas para decidir cuándo una señal **sí** es evidencia: cómo separar la información del azar, qué pasa al probar muchas ideas y por qué un efecto estadístico real puede no valer nada económicamente.

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `N` | Velas por mercado sintético | 2.400 |
| `phi` (φ) | Persistencia de los retornos | 0 · 0,35 · de 0,35 a 0 |
| `TRAIN_FRACTION` | Corte cronológico, fijado de antemano | 65 % |
| `LAGS` | Retardos de Ljung–Box | 10 |
| `ALPHA` (α) | Nivel de significación | 5 % |
| `N_SIGNALS` (m) | Señales nulas probadas | 500 |
| `N_SIMULATIONS` | Experimentos de Monte Carlo | 3.000 |
| `ROUND_TRIP_BPS` | Coste supuesto de ida y vuelta | 20 bps |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| Retorno log | ln(P_t / P_{t−1}) | — | ¿Cuánto se movió el precio? |
| ACF(k) | Corr(r_t, r_{t−k}) | Persistente, k = 1: **0,409** | ¿Se parece un retorno al anterior? |
| Error estándar de la ACF | ≈ 1 / √n | n = 1.559: **0,025** | ¿Cuánto varía la ACF por azar? |
| Ljung–Box | n(n + 2) · Σ ρ_k² / (n − k) | Persistente: p ≈ 0 | ¿Hay alguna dependencia lineal? |
| Falsos positivos esperados | m · α | 500 × 0,05 = **25** | ¿Cuántos "hallazgos" salen por azar? |
| P(≥ 1 falso positivo) | 1 − (1 − α)^m | m = 20: **64,2 %** | ¿Es probable equivocarse al menos una vez? |
| Umbral de Bonferroni | α / m | 0,05 / 500 = **0,0001** | ¿Qué p-valor hace falta con m pruebas? |
| IC de una señal | Corr(señal, retorno) | Mejor nula: **0,076** | ¿Cuánto se asocia la señal con el retorno? |
| IC máximo nulo | ≈ √(2 · ln m / n) | m = 1.000: **0,094** | ¿Qué IC sale por azar? |
| ACF móvil | ρ_1 en los últimos 200 retornos | En el corte: **0,33** | ¿Sigue vivo el patrón? |
| Retorno neto | P_{t+2} / P_{t+1} − 1 − c | Persistente: +0,19 − 20 = **−19,81 bps** | ¿Gana dinero el patrón? |

## 3. Reglas de validación (antes de calcular)

- El corte se fija **de antemano** (65 %) y los retornos se calculan **después** del corte: ninguno lo cruza.
- No se comprimen los huecos: se usa el tramo contiguo más largo, con al menos máx(60, 5 · lags + 1) retornos.
- El CSV de P04 se valida con las funciones de P05: rejilla regular, precios > 0 y finitos, sin rellenar huecos.
- La señal candidata (índice **y** signo) se elige solo en desarrollo, y se congela antes de mirar la validación.
- Cada experimento nuevo de data snooping usa su propia semilla.
- La autocorrelación móvil usa solo el pasado (sin `center=True`).
- El coste se resta una sola vez por operación (incluye las dos piernas).

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Ljung–Box con p < α | Rechaza que las primeras k autocorrelaciones sean cero (bajo sus supuestos). |
| Ljung–Box con p ≥ α | No detecta dependencia lineal, lo que no demuestra que no la haya. |
| m pruebas al nivel α | Espera m · α falsos positivos aunque no haya nada. |
| p ≥ α / m | La señal no sobrevive a Bonferroni. |
| La mejor de m señales en desarrollo | Su IC está sesgado al alza: hay que evaluarla fuera de muestra. |
| IC con signo distinto en validación | El patrón no persiste. |
| Retorno bruto por operación < coste | El patrón no es rentable, por real que sea. |
| Retornos sin autocorrelación pero \|r\| con autocorrelación | Hay dependencia en la volatilidad, no independencia. |

**Lo que NO puede concluir:**

- Que un mercado sea eficiente porque no se detecta autocorrelación.
- Que un p-valor bajo sea la probabilidad de que la señal funcione.
- Que una señal "significativa" sea rentable: el tamaño del efecto y los costes deciden.
- Nada sobre una señal elegida entre muchas sin corregir por el número de pruebas.
- Que una anomalía sea real con unas horas de datos: la conclusión correcta es **evidencia insuficiente**.

## 5. Para qué sirve

- **No engañarse con el azar.** Saber cuántos falsos positivos esperar evita perseguir señales que solo existen porque se probaron muchas.
- **Elegir bien qué medir.** Retornos y no precios; tamaño del efecto y no solo el p-valor; dependencia en la volatilidad, no solo en la dirección.
- **Diseñar investigaciones honestas.** Corte fijado de antemano, selección congelada, un periodo de validación intacto y corrección por pruebas múltiples.
- **Detectar el decaimiento de una señal.** Las señales desaparecen, y una ventana móvil lo detecta con retraso: hay que vigilarlas en continuo.
- **Unir estadística y economía.** Un patrón que no cubre los costes no es una ineficiencia explotable.
- **Base para P12.** Separar alpha, beta y factores es el siguiente paso para saber si un retorno es realmente propio de la estrategia.

## Referencias

- Código: [`src/quantlab/p11/efficiency.py`](../../src/quantlab/p11/efficiency.py)
- Pruebas: [`tests/test_efficiency.py`](../../tests/test_efficiency.py)
- Conclusiones: [conclusiones/P11_market_efficiency.md](../conclusiones/P11_market_efficiency.md)
- Conceptos: [eficiencia de mercado](../conceptos/eficiencia_de_mercado.md) · [momentum y reversión](../conceptos/momentum_y_reversion.md) · [costes de ejecución](../conceptos/costes_de_ejecucion.md)
- Aprendizaje anterior: [P10 · Valoración fundamental y macroeconomía](P10_fundamental_macro.md)
