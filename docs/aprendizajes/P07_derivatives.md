# P07 · Análisis de derivados financieros · Resumen de lo aprendido

**Cuaderno:** `notebooks/01_financial_foundations/P07_derivatives.ipynb`
**Datos de ejemplo:** 720 horas sintéticas de un perpetuo BTC/USDT y una captura pública de OKX

Hasta P06 trabajábamos con el mercado spot. P07 añade los **perpetuos**: contratos que replican el precio de BTC sin comprarlo, con información propia (basis, open interest, funding, liquidaciones) y riesgos propios (margen y apalancamiento).

## 1. Variables de entrada

| Variable | Qué es | Unidad |
|---|---|---|
| `spot_price`, `perp_price` | Último precio del spot y del perpetuo | USDT/BTC |
| `mark_price`, `index_price` | Precio de valoración del perpetuo y referencia del subyacente | USDT/BTC |
| `open_interest_btc` | Contratos abiertos, en BTC equivalentes | BTC |
| `funding_rate` | Tasa **realizada** por pago (0 = sin pago; NaN = desconocido) | decimal por pago |
| `long_liquidation_usdt`, `short_liquidation_usdt` | Nominal liquidado durante la hora | USDT |
| `HORIZON` | Horas del estudio de eventos | 3 h |
| `FEE_BPS` | Comisión por ejecución (supuesta) | 10 bps |
| `QTY_BTC`, `MARGIN_USDT` | Tamaño de la cobertura y garantía del short | 0,02 BTC · 600 USDT |
| `MAINTENANCE_RATE` | Tasa de mantenimiento (supuesto docente) | 0,5 % |

## 2. Cómo se calcula cada métrica

| Métrica | Fórmula | Ejemplo | Qué responde |
|---|---|---|---|
| `basis_bps` | 10⁴ · (perp − spot) / spot | 60.000 → 60.300: **+50 bps** | ¿El perpetuo cotiza con prima o descuento? |
| `mark_index_bps` | 10⁴ · (mark / index − 1) | OKX: **−5,9 bps** | ¿Cuánto se separa el precio de valoración del subyacente? |
| `oi_change_pct` | Variación del OI en BTC | — | ¿Se abrieron o cerraron contratos? |
| `oi_notional_usdt` | OI en BTC × mark | 33.060,6 × 61.953 ≈ **2.048 M USDT** | Valor de los contratos abiertos |
| Pago de funding | q · mark · tasa | 0,1 × 60.000 × 0,0001 = **0,60 USDT** | ¿Cuánto paga o cobra cada lado? |
| `liquidation_imbalance` | (L_long − L_short) / (L_long + L_short) | (90 − 10) / 100 = **+0,8** | ¿Qué lado se está liquidando? |
| `forward_return_bps` | 10⁴ · (S_{t+h} / S_t − 1) | — | ¿Qué hizo el precio tras el evento? |
| `price_pnl` | q · ((S_t − S_0) − (P_t − P_0)) | Semana: **−1,54 USDT** | ¿Cuánto costó la variación del basis? |
| `funding_pnl` | Σ q · mark · tasa, sin el pago de la hora de entrada | Semana: **+3,06 USDT** | ¿Cuánto funding se cobró? |
| `fees` | q · f · (S_0 + P_0 + S_t + P_t) | Semana: **4,72 USDT** | Coste de las 4 ejecuciones |
| `net_pnl` | price_pnl + funding_pnl − fees | **−3,21 USDT** | Resultado de la cobertura |
| Rentabilidad sobre el capital | net_pnl / (q · S_0 + garantía) | −3,21 / 1.796 = **−0,18 %** | ¿Compensa inmovilizar el capital? |
| `margin_equity` | garantía + q · (P_0 − mark) + funding − comisión de apertura | Estrés: **−34,5 USDT** | ¿Cuánto queda en la cuenta del short? |
| `margin_breach` | margin_equity ≤ q · mark · mantenimiento | −34,5 ≤ 6,7: **sí** | ¿Se puede liquidar el short? |
| Subida que cruza el umbral | (garantía + q · P_0 · (1 − f)) / (q · (1 + m)) / mark_0 − 1 | 100 USDT: **+7,7 %** | ¿Cuánto aguanta cada garantía? |

## 3. Reglas de validación (antes de calcular)

`normalize` detiene el análisis con `ValueError` si:

- Faltan columnas, o hay timestamps nulos o duplicados.
- Algún timestamp no es un cierre horario exacto en UTC.
- Hay datos vacíos o infinitos, precios ≤ 0, o OI o liquidaciones negativos.

Y además:

- La serie se reindexa a una rejilla horaria completa **sin rellenar**: `shift(3)` siempre significa tres horas.
- El umbral de eventos se fija **solo con el desarrollo**, y se descartan los objetivos de desarrollo que cruzan la frontera.
- La cobertura excluye el funding de la hora de entrada, y un funding desconocido (`NaN`) deja indefinido todo el PnL posterior.
- `hedge_curve` rechaza tamaños o garantías ≤ 0 y comisiones negativas; `basis_bps`, un spot ≤ 0.
- Un fallo de OKX lanza el error: nunca se sustituye por datos ficticios.

## 4. Conclusiones que un programa puede sacar de forma determinista

| Si el programa observa... | Concluye siempre... |
|---|---|
| La serie no supera `normalize` | El dato no es válido: no se analiza. |
| Basis > 0 | El perpetuo cotiza por encima del spot en ese instante. |
| Funding > 0 en un pago | Los largos pagan y los cortos cobran q · mark · tasa. |
| El OI en BTC sube | Se abrieron contratos netos (con un largo y un corto cada uno). |
| El OI en USDT y en BTC tienen signo distinto | El precio se movió más que las posiciones. |
| Funding cobrado < comisiones + pérdida de basis | La cobertura pierde dinero en ese periodo. |
| margin_equity ≤ mantenimiento | La cuenta del short está en riesgo de liquidación, gane lo que gane el spot. |
| Funding desconocido en una hora | El PnL a partir de esa hora es desconocido. |
| Un evento con objetivo más allá de la frontera | No entra en el desarrollo. |

**Lo que NO puede concluir:**

- Cuántos participantes son alcistas o bajistas a partir del OI.
- Que el funding anunciado sea el que se cobrará: en OKX tenían signo contrario.
- Que el carry sea rentable a futuro porque lo fue en una semana: el funding cambia de signo.
- Que las liquidaciones anticipen el precio: 4 a 12 eventos con signo inestable no son evidencia.
- Que la cobertura no tenga riesgo: quedan el basis, el funding, el margen, la contraparte, la ejecución y la paridad de USDT.
- Un precio de liquidación real: cada exchange aplica sus propias reglas de margen.

## 5. Para qué sirve

- **Leer el mercado de derivados.** Basis, OI y funding muestran cuánta prima pagan los largos, cuántos contratos hay abiertos y quién paga a quién.
- **Evaluar estrategias de carry con honestidad.** Separar basis, funding y comisiones, y medir sobre el capital total, muestra que el funding rara vez cubre los costes.
- **Entender el riesgo de margen.** Una posición neutral en conjunto puede liquidarse por una de sus piernas: el apalancamiento y las cuentas separadas importan tanto como la dirección.
- **Construir históricos fiables.** Distinguir funding anunciado de liquidado, convertir contratos a BTC con `ctVal` y guardar la hora de recepción de cada endpoint.
- **Base para P08.** Las comisiones, el spread y el slippage deciden si una estrategia sobrevive: es el tema de la siguiente práctica.

## Referencias

- Código: [`src/quantlab/p07/derivatives.py`](../../src/quantlab/p07/derivatives.py)
- Pruebas: [`tests/test_derivatives.py`](../../tests/test_derivatives.py)
- Conclusiones: [conclusiones/P07_derivatives.md](../conclusiones/P07_derivatives.md)
- Conceptos: [derivados perpetuos](../conceptos/derivados_perpetuos.md) · [spread y costes](../conceptos/spread_y_costes.md) · [validación de datos](../conceptos/validacion_de_datos.md)
- Aprendizaje anterior: [P06 · Comparación entre exchanges](P06_cross_exchange.md)
