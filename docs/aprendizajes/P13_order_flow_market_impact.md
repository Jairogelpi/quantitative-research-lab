# P13 · Order Flow, Market Impact y exposición · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P13_order_flow_market_impact.ipynb`
**Datos de ejemplo:** un libro didáctico, cotizaciones sintéticas, un experimento de impacto artificial y cotizaciones reales de Kraken

P02 miraba una foto del libro; P03, los trades. P13 mira cómo **cambia** el libro de un instante a otro (order flow), cómo responde el precio a las operaciones (impacto) y cómo se mide lo que una cartera tiene en juego (exposición).

## 1. Variables de entrada

| Variable | Qué es | Ejemplo |
|---|---|---|
| `snapshot` | Libro completo inicial: precio → cantidad por lado | bid {99: 2, 98: 3}, ask {101: 2, 102: 4} |
| `updates` | (secuencia, lado, precio, cantidad absoluta, etiqueta) | (1, bid, 99, 3, "alta bid") |
| `bid`, `ask`, `bid_size`, `ask_size` | Mejor nivel de cada cotización | 59.996,8 / 59.998,8 € |
| `received_at` | Hora de recepción de cada cotización (UTC) | una por segundo |
| `MAX_GAP_SECONDS` | Hueco máximo antes de abrir un segmento nuevo | 2 s |
| `qty`, `side` | Tamaño y lado agresor de cada trade (impacto) | 0,25 BTC, compra |
| `quantity`, `entry_price`, `current_price` | Posiciones de la cartera | 0,1 BTC a 60.000 → 63.000 |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `mid` | (bid + ask) / 2 | (99 + 101) / 2 = **100** | Precio de referencia |
| `obi` | (q^b − q^a) / (q^b + q^a) | (3 − 2) / 5 = **+0,2** | ¿Qué lado tiene más cantidad ahora? |
| `ofi_event` (mismo precio) | Δq^b − Δq^a | bid 2 → 3: **+1** | ¿Aumentó la presión compradora? |
| `ofi_event` (cambia el precio) | Nivel que aparece (+) o desaparece (−) | Mejora del ask con 2 BTC: **−2** | ¿Y si cambia el mejor precio? |
| `mid_change_bps` | 10.000 · (mid_t / mid_{t−1} − 1) | 100 → 100,5: **+50 bps** | ¿Cuánto se movió el mid? |
| `future_bps` | 10.000 · (mid_{t+k} / mid_t − 1), mismo segmento | — | ¿Qué hizo el mid después? |
| Pendiente OFI | OLS de Δmid sobre OFI (HAC) | Sintético: **0,25 bps/BTC** | ¿Cuánto mueve el precio 1 BTC de flujo? |
| Respuesta firmada | signo · (mid_{t+h} − mid_{t−}) | Q4 a 0 s: **4,6 bps** | ¿Cuánto impacta un trade? |
| Parte transitoria | 1 − respuesta(30 s) / respuesta(0 s) | **≈ 71 %** | ¿Cuánto revierte? |
| Nominal / PnL | N = q · P; PnL = q · (P_t − P_0) | 0,1 · 63.000 = **6.300 €**; PnL **+300 €** | ¿Cuánto vale y cuánto gana? |
| Exposición bruta / neta | Σ\|N\| / Σ N | **12.610 €** / **−10 €** | ¿Cuánto en juego y en qué dirección? |
| Apalancamiento bruto | bruta / patrimonio | 12.610 / 7.000 = **1,8** | ¿Cuántas veces el patrimonio? |

## 3. Reglas de validación (antes de calcular)

- `replay` exige secuencias consecutivas: si falta una, **se resincroniza** desde un snapshot, nunca se sigue con un libro incompleto. Rechaza lados o cantidades inválidos y libros cruzados.
- `prepare_quotes` filtra **un solo** exchange y par, exige al menos 60 cotizaciones con hora única y válida, precios y tamaños > 0 y ask > bid.
- Un salto mayor que `MAX_GAP_SECONDS` abre un segmento: la primera fila de cada segmento no tiene OFI ni cambio de mid.
- El retorno futuro no cruza segmentos ni el corte cronológico 65/35.
- La regla de signo usa la pendiente de **desarrollo**; no se reestima en validación.
- `future_bps` es una etiqueta: nunca se usa como feature.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| Un salto en la secuencia de mensajes | El libro reconstruido no es fiable: hay que resincronizar. |
| Cambio de cantidad fuera del mejor nivel | El OFI de primer nivel es 0. |
| Sube el mejor bid | Contribución OFI positiva (+ q^b nuevo). |
| Mejora el ask | Contribución OFI negativa (− q^a nuevo). |
| Hueco mayor que el límite | No se calcula OFI ni cambio de mid a través de él. |
| Rendimiento bruto de la regla < coste | La regla pierde dinero, por mucho que acierte. |
| Exposición neta 0 y bruta > 0 | No hay riesgo de dirección común, pero sí capital en juego. |

**Lo que NO puede concluir:**

- Que una relación contemporánea sea una señal: se conoce a la vez que el cambio que explica.
- Que el OFI entre snapshots REST sea el OFI real: se pierden los eventos intermedios.
- Qué fue una cancelación y qué una ejecución a partir de cotizaciones aisladas.
- Que la respuesta a 30 s sea impacto permanente.
- Nada sobre el mercado real a partir de relaciones sintéticas programadas.

## 5. Para qué sirve

- **Entender cómo se forma el precio.** El precio se mueve cuando cambia la liquidez del mejor nivel; el OFI lo cuantifica.
- **Distinguir explicar de anticipar.** Un R² alto contemporáneo no es una ventaja; lo que importa es lo que se conoce antes.
- **Estimar el coste de las órdenes grandes.** El impacto crece con el tamaño y revierte: dividir y espaciar las órdenes puede reducirlo.
- **Medir el riesgo de una cartera.** La exposición bruta y neta, junto al patrimonio, dicen cuánto se arriesga y en qué dirección.
- **Diseñar la captura de datos.** El contrato del E7 (secuencia, timestamps, trades sincronizados) es lo que hace falta para pasar del OFI aproximado al exacto.

## Referencias

- Código: [`src/quantlab/p13/order_flow.py`](../../src/quantlab/p13/order_flow.py)
- Pruebas: [`tests/test_order_flow.py`](../../tests/test_order_flow.py)
- Conclusiones: [conclusiones/P13_order_flow_market_impact.md](../conclusiones/P13_order_flow_market_impact.md)
- Conceptos: [order flow e impacto](../conceptos/order_flow_e_impacto.md) · [libro de órdenes](../conceptos/libro_de_ordenes.md) · [operaciones ejecutadas](../conceptos/operaciones_ejecutadas.md)
- Aprendizaje anterior: [P12 · Alpha, Beta y factores financieros](P12_factor_analysis.md)
