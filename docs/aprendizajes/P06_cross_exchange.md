# P06 · Comparación entre exchanges · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P06_cross_exchange.ipynb`
**Datos de ejemplo:** cotizaciones sintéticas de tres exchanges con retrasos conocidos y capturas reales de Kraken, OKX y Bitvavo

Hasta P05 mirábamos un solo mercado. P06 compara **tres mercados del mismo activo**: ¿se mueven juntos?, ¿alguno se adelanta?, ¿hay diferencias de precio que se puedan aprovechar después de costes?

## 1. Variables de entrada

| Variable | Qué es | Valor por defecto |
|---|---|---|
| `bid`, `ask` | Mejor precio comprador y vendedor de cada exchange | — |
| `bid_size`, `ask_size` | Cantidad visible a esos precios (BTC) | — |
| `request_at`, `received_at` | Hora antes de pedir y al recibir la cotización (UTC) | — |
| `exchange_at` | Hora del evento según el exchange, si la informa | Solo OKX |
| `GRID` | Rejilla temporal de decisión | 1 s |
| `MAX_AGE` | Antigüedad máxima de una cotización | 2 s |
| `MAX_SKEW` | Desfase máximo de recepción entre los dos mercados de una ruta | 750 ms |
| `FEE_BPS` | Comisión supuesta por lado y exchange | 10 bps |
| `EXTRA_BPS` | Reserva adversa por lado | 1 bp |
| `QTY` | Tamaño de la operación | 0,01 BTC |
| `MAX_LAG` | Desplazamiento máximo del lead-lag | 5 s |

## 2. Cómo se calcula cada métrica

### Calidad y alineación

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `mid` | (bid + ask) / 2 | (59.990 + 60.010) / 2 = **60.000 €** | Precio de referencia |
| `spread_bps` | (ask − bid) / mid × 10.000 | 20 / 60.000 × 10.000 = **3,333 bps** | Coste de cruzar el libro |
| `rtt_ms` | received_at − request_at | Kraken real: **381 ms** | ¿Cuánto tarda en llegar la respuesta? |
| Alineación | Última cotización recibida en o antes de t (`backward`) | En t = 10:00:01, la recibida a las 10:00:00,1 | ¿Qué sabíamos en el instante t? |
| `age_ms` | t − received_at | ≤ **2.000 ms** | ¿Está el dato demasiado viejo? |
| Retorno nuevo | log(M_t / M_{t−1}), solo si t y t − 1 tienen recepciones nuevas | — | ¿Cuánto se movió el precio, sin contar arrastres? |

### Correlación y lead-lag

| Métrica | Fórmula | Ejemplo (simulación) | Qué responde |
|---|---|---|---|
| Correlación simultánea | Corr(r^A_t, r^B_t) | Kraken–OKX: **0,03** | ¿Se mueven a la vez? |
| ρ(k) | Corr(r^Kraken_t, r^OKX_{t+k}) | k = +2: **0,97** (Spearman) | ¿OKX repite a Kraken k segundos después? |
| Lag elegido | k con mayor ρ en desarrollo | OKX **+2 s**, Bitvavo **+1 s** | ¿Quién parece adelantarse y cuánto? |

### Arbitraje al mejor nivel

| Métrica | Fórmula | Ejemplo (1 BTC, 10 bps, sin reserva) | Qué responde |
|---|---|---|---|
| Coste C | q · Ask_A · (1 + s) · (1 + f_A) | 60.000 × 1,001 = **60.060 €** | ¿Cuánto pago al comprar en A? |
| Ingreso V | q · Bid_B · (1 − s) · (1 − f_B) | 60.150 × 0,999 = **60.089,85 €** | ¿Cuánto cobro al vender en B? |
| `net_eur` | V − C | **+29,85 €** | ¿Gano o pierdo? |
| `net_bps` | 10.000 × (V − C) / C | **+4,97 bps** | Margen sobre la compra |
| `max_visible_btc` | min(ask_size_A, bid_size_B) | — | ¿Cabe mi orden? |
| `skew_ms` | \|received_at_A − received_at_B\| | ≤ **750 ms** | ¿Son casi simultáneas las dos cotizaciones? |
| Episodio | Segundos consecutivos candidatos de una ruta | 16 segundos → **6 episodios** | ¿Cuántas oportunidades distintas hay? |

## 3. Reglas de validación (antes de calcular)

`validate_quotes` detiene el análisis con `ValueError` si:

- Faltan columnas, falta alguno de los tres exchanges o aparece otro par distinto de BTC/EUR.
- Hay precios o tamaños ≤ 0 o no finitos, o un libro cruzado (ask < bid).
- Falta una hora de recepción, o se repite para un mismo exchange.
- Una solicitud es posterior a su recepción.

Y además:

- `align_quotes` nunca usa `nearest`: solo cotizaciones recibidas en o antes de t.
- Se descartan las cotizaciones con más de 2 s y, si hay `exchange_at`, los eventos con más de 2 s o con más de 250 ms en el futuro.
- Una ruta solo es elegible si las dos cotizaciones son válidas, su desfase es ≤ 750 ms y la orden cabe en los dos tamaños visibles.
- Los adaptadores rechazan errores de la API y otros pares (por ejemplo BTC/USDT). Un fallo en vivo se registra; nunca se sustituye por datos ficticios.
- Kraken se lee del libro `Depth`, porque el tamaño del `Ticker` vale siempre 1.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Las cotizaciones no superan `validate_quotes` | El dato no es válido: no se analiza. |
| No hay cotización recibida en los últimos 2 s | No hay precio válido para ese mercado en t. |
| El máximo de ρ(k) está en k > 0 | Los retornos del primer mercado **se reciben** antes que los del segundo. |
| Retrasar la recepción de un mercado desplaza el lag | El lag depende de cuándo llegan los datos. |
| Menos de 20 pares para un desplazamiento | Ese ρ(k) no se calcula. |
| La orden no cabe en el tamaño visible | La ruta no es elegible en ese segundo. |
| V − C > 0 en una ruta elegible | Es un **candidato**, no un beneficio realizado. |
| Aumenta el tamaño con los mismos precios | Los candidatos se mantienen o bajan; nunca suben. |
| Aumentan las comisiones | Los candidatos se mantienen o bajan; nunca suben. |
| Segundos candidatos consecutivos en una ruta | Son un solo episodio. |

**Lo que NO puede concluir:**

- Que un exchange **lidere** el precio: el lag se mide con la recepción, y la latencia o la caché lo crean (E5).
- Que dos mercados sean independientes porque su correlación simultánea es baja.
- Que una correlación sea estable si cambia entre periodos sin mirar antes los outliers.
- Que un candidato sea rentable: faltan profundidad L2, slippage, latencia de ejecución, inventario, reequilibrado, mínimos de orden y riesgo de que falle una pierna.
- La rentabilidad sobre el capital: hace falta EUR en un exchange y BTC en el otro.
- Nada sobre los mercados reales con un minuto de captura.

## 5. Para qué sirve

- **Comparar mercados sin trampas temporales.** La alineación `backward` con límite de antigüedad es la base de cualquier estudio entre exchanges, y de cualquier unión de datos de fuentes distintas.
- **Detectar relaciones desplazadas.** El lead-lag muestra que dos series pueden estar muy relacionadas aunque no lo parezca en el mismo instante.
- **Desconfiar de las correlaciones frágiles.** Comparar Pearson con Spearman revela cuándo unos pocos outliers fabrican o destruyen una relación.
- **Entender por qué el arbitraje "fácil" no existe.** Las diferencias normales entre mercados (1–2 €) están muy por debajo de los costes (unos 125 € por BTC y ruta con 10 bps por lado).
- **Diseñar la siguiente investigación.** E7 deja definido el experimento serio: WebSocket L2, relojes sincronizados, latencia de ejecución medida, inventario y validación independiente.

## Referencias

- Código: [`src/quantlab/p06/cross_exchange.py`](../../src/quantlab/p06/cross_exchange.py)
- Pruebas: [`tests/test_cross_exchange.py`](../../tests/test_cross_exchange.py)
- Conclusiones: [conclusiones/P06_cross_exchange.md](../conclusiones/P06_cross_exchange.md)
- Conceptos: [comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) · [libro de órdenes](../conceptos/libro_de_ordenes.md) · [spread y costes](../conceptos/spread_y_costes.md)
- Aprendizaje anterior: [P05 · Momentum y Mean Reversion](P05_momentum_mean_reversion.md)
