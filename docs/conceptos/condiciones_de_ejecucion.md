# Condiciones de ejecución

**Familia:** costes de ejecución · **Usa conceptos de:** P01 y P02 · **Código:** `src/quantlab/p01/execution.py` y `scripts/monitor_ejecucion.py`

## Qué responde y qué no

| Pregunta | ¿La responde? |
|---|---|
| Si quiero comprar o vender X BTC **ahora**, ¿a qué precio y con qué coste? | ✅ Sí, de forma exacta |
| ¿Es buen momento para **ejecutar**, o el spread está anormalmente caro? | ✅ Sí, con reglas fijas |
| ¿Cuánto tiene que moverse el precio para **no perder** dinero? | ✅ Sí (punto de equilibrio) |
| ¿Va a **subir o bajar**? ¿Compro o vendo? | ❌ No. P01 no da ninguna señal de dirección |

**Determinista:** con los mismos datos y parámetros, siempre da el mismo resultado. Las reglas son explícitas y no hay aleatoriedad.

## Reglas (en orden)

| # | Regla | Veredicto |
|---|---|---|
| 1 | La cotización no supera la validación (libro cruzado, precio ≤ 0, fallo de red) | ⛔ `DATO_NO_VALIDO` |
| 2 | El snapshot del libro no cubre la orden completa (entrada o salida) | ⚠️ `PROFUNDIDAD_INSUFICIENTE` |
| 3 | Hay menos de 10 observaciones de historia | ⏳ `SIN_HISTORIAL` (calcula el coste, pero no juzga el spread) |
| 4 | Spread actual ≤ mediana de la ventana (5 min) | ✅ `EJECUTAR` |
| 5 | Mediana < spread ≤ percentil 90 | 🟡 `NORMAL` |
| 6 | Spread > percentil 90 | 🔴 `ESPERAR` (spread anormalmente caro) |

En las reglas 4 a 6, las diferencias menores de 0,001 bps se consideran iguales. Así, un mismo spread de 0,1 € no da bps distintos solo porque el mid ha cambiado un poco.

## Fórmulas

| Concepto | Compra | Venta |
|---|---|---|
| Precio de ejecución | VWAP recorriendo los asks (sin libro: Ask) | VWAP recorriendo los bids (sin libro: Bid) |
| Importe | qty × Ask | qty × Bid |
| Comisión | importe × f | importe × f |
| Coste del spread frente al mid | qty × spread / 2 | qty × spread / 2 |
| Slippage (P02) | qty × (VWAP − Ask) | qty × (Bid − VWAP) |
| Ida y vuelta | qty × (VWAP_compra − VWAP_venta) + qty × (VWAP_compra + VWAP_venta) × f | ídem |
| **Punto de equilibrio** | P_salida = P_entrada × (1 + f) / (1 − f) | P_salida = P_entrada × (1 − f) / (1 + f) |

`f` es la comisión por pata (por cada operación). El punto de equilibrio es el precio al que habría que cerrar la posición para que, después de pagar el spread y las dos comisiones, el resultado sea cero.

## Conclusiones (19-11-2026, Kraken BTC/EUR, compra de 0,01 BTC)

| Concepto | Valor | Lectura |
|---|---|---|
| Spread | 0,10 € (0,017 bps) | Es el tick mínimo. BTC/EUR es muy líquido. |
| Coste del spread en ida y vuelta | 0,001 € | Despreciable. |
| Comisiones en ida y vuelta (0,80 % por pata) | 9,28 € | **Unas 9.000 veces más que el spread.** |
| Punto de equilibrio | +936 € (+1,61 %) | El precio tiene que subir un 1,61 % solo para no perder. |
| Volumen al mejor precio | entre 0,001 y 0,25 BTC | Varía mucho; una venta de 0,5 BTC ya no cabe en el primer nivel. |

1. **Para un particular, la comisión es el coste dominante, no el spread.** Con el nivel 1 de Kraken Pro (0,80 % taker), cualquier estrategia necesita movimientos de más del 1,6 % para cubrir costes.
2. **El spread mínimo no garantiza que tu orden se ejecute a ese precio.** Puede haber muy poco volumen en el mejor nivel (se llegó a ver 0,001 BTC).
3. **⚠️ El volumen del ticker de Kraken no es fiable:** el campo de volumen de `a`/`b` vale siempre 1. Por eso el Bid, el Ask y sus volúmenes salen del endpoint `Depth` (libro de órdenes, mejor nivel).

## Comisiones de Kraken Pro (spot, consultado el 19-11-2026)

| Nivel | Volumen en 30 días | Maker | Taker |
|---|---|---|---|
| 1 | 0 $ + | 0,40 % | **0,80 %** ← valor por defecto |
| 2 | 2.500 $ + | 0,30 % | 0,60 % |
| 3 | 10.000 $ + | 0,22 % | 0,38 % |
| 6 | 100.000 $ + | 0,12 % | 0,25 % |

Una orden que se ejecuta al instante es **taker**. Fuente: [kraken.com/pro/fees](https://www.kraken.com/pro/fees). Las comisiones cambian, así que compruébalas antes de usar el script.

## Uso

```powershell
# Monitor continuo (Ctrl+C para salir), compra de 0,01 BTC con la comisión por defecto
.\.venv\Scripts\python.exe scripts\monitor_ejecucion.py --side buy --qty 0.01

# Venta de 0,05 BTC, comisión 0,38 % (nivel 3), consulta cada 10 s
.\.venv\Scripts\python.exe scripts\monitor_ejecucion.py --side sell --qty 0.05 --fee-pct 0.38 --interval 10

# Una sola consulta
.\.venv\Scripts\python.exe scripts\monitor_ejecucion.py --side buy --qty 0.01 --iterations 1
```

Cada consulta se guarda en `data/raw/kraken_btceur_quotes.csv` (Git no la sube). Es la serie temporal que usaremos en las siguientes prácticas.

## Limitaciones

- Recorre los `--levels` niveles descargados (100 por defecto, hasta 500). Si la orden no cabe en ellos, no inventa precios: avisa con `PROFUNDIDAD_INSUFICIENTE`.
- El slippage es el del snapshot: no modela que el libro cambie mientras se ejecuta la orden.
- La hora es la de **recepción**, no la del evento en el exchange.
- La mediana y el percentil 90 de 5 minutos son una propuesta inicial, no parámetros optimizados.
- **No envía órdenes.** Solo consulta APIs públicas.

Relacionado: [spread_y_costes.md](spread_y_costes.md) · [validacion_de_datos.md](validacion_de_datos.md) · [precios_de_cotizacion.md](precios_de_cotizacion.md)
