# QuantLab — Operación de datos y calidad (propuesta noviembre 2026)

## Objetivo y situación

Este documento describe los cambios de la rama `feature/quantlab-reliability-history-20261123`.
No se despliegan automáticamente en el PC. Revisar pruebas y aprobar PR antes de usarla como producción.

El objetivo es **obtener datos comparables y auditables**, no afirmar que disponemos
de la totalidad histórica del mercado. Nunca convertir huecos desconocidos en velas
ficticias, ni interpretar un histórico de velas como un libro L2.

## Lo que ya estaba implementado

- REST spot BTC/EUR de Kraken, OKX y Bitvavo, por rondas de aproximadamente 1 s.
- WebSocket spot de libro y trades, sincronización de estados y reconexión.
- Lake Parquet append-only y consultas DuckDB.
- Histórico OHLCVT oficial de Kraken, derivados de OKX y Kraken Futures y fotos de opciones Deribit.
- Ciclo semanal con estudios/revalidaciones, iniciado a las 06:00 del lunes.

## Cambios de esta rama

### Histórico spot OKX y Bitvavo

```powershell
cd proyecto
python -m radar historico-spot
python -m radar historico-spot --desde 2026-11-15 --hasta 2026-11-23 --intervalos 60,3600,86400 --max-paginas 200
python -m radar retornos --fuente okx_historico --exchange okx
python -m radar retornos --fuente bitvavo_historico --exchange bitvavo
```

- OKX utiliza `/api/v5/market/history-candles`. Paginación hacia atrás con `after`; el límite se controla por número de páginas.
- Bitvavo utiliza `/{market}/candles`. Paginación por ventanas temporales alineadas.
- Las velas se guardan en `velas` con `fuente=okx_historico` o `bitvavo_historico`, junto al histórico Kraken y las velas propias.
- Se conservan los campos OHLC y el volumen base. OKX publica volumen cotizado en EUR, con el que se deriva el VWAP de la vela. Bitvavo no publica volumen EUR, VWAP ni número de trades: quedan nulos, nunca estimados.
- Un intervalo sin vela Bitvavo no se rellena artificialmente: puede ser un minuto sin operaciones o falta real de cobertura.
- El resumen indica `ventana_completa=False` al llegar al límite de páginas o agotarse el endpoint sin llegar al comienzo solicitado. En Bitvavo el indicador significa que **se consultó todo el rango solicitado**, no que hubiera negociaciones todos los minutos.
- El historial es **idempotente** en el lake: se añaden versiones solo cuando la información mejora o cambia, sin sobreescribir Parquet.

AVISO: `BTC-EUR` no es igual que `BTC-USDT` ni que un futuro. La investigación multiexchange debe preservar el identificador del mercado y la divisa de cotización.

### Captura WebSocket prolongada y escritura

```powershell
cd proyecto
python -m radar flujo --continuo --escritura-async
```

- `--continuo` quita el corte deliberado al cabo de 3.600 segundos.
- Si muere inesperadamente una tarea interna de captura, el proceso comunica el fallo para que el supervisor pueda reiniciarlo.
- `--escritura-async` traslada la escritura Parquet a un hilo con hasta 16 lotes en espera y aplica backpressure.
- Al cerrar ordenadamente, espera a que terminen las escrituras y propaga fallos persistentes.
- **No es un WAL ni un sistema exactly-once.** Ante apagón o terminación forzosa puede perderse lo no escrito; si una escritura falla en un punto ambiguo también podrían producirse duplicados. La captura REST permanece en tramos de una hora por compatibilidad.

`scripts/captura_permanente.ps1 -Modo flujo` utiliza estos parámetros. El modo REST sigue funcionando en tramos de 3600 s.

### Diagnóstico de salud

```powershell
cd proyecto
python -m radar salud --umbral-s 180
```

Comprueba la antigüedad de la última `cotizaciones` REST y `libros_flujo` por cada uno de los tres exchanges y cuenta errores recientes. Sale con código 2 cuando falta información o hay una fuente obsoleta. No deduce caída de conexión por silencio de trades.

La salud por frescura no certifica integridad L2, ausencia de gaps ni conservación 100 % de los eventos. Son controles separados que deberán añadirse.

### Ciclo diario independiente

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ciclo_diario.ps1 -Prueba
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\instalar_ciclo_diario.ps1
```

Programa el ciclo diario a las **03:00 (hora local)**, si el usuario ejecuta expresamente el instalador. Actualiza:
1. Velas públicas spot OKX y Bitvavo.
2. OHLC Kraken REST (sin releer ZIP completos).
3. Históricos de derivados recientes.
4. Velas propias derivadas del flujo.
5. Foto de opciones Deribit.
6. Diagnóstico de salud.

Cada paso genera registros de texto en `data/logs/diario_AAAA-MM-DD.log` y los errores de una etapa no impiden ejecutar las siguientes.

El ciclo semanal se conserva como respaldo; NO se desactiva automáticamente para no modificar un equipo sin supervisión.

## Validaciones

```powershell
$env:PYTHONPATH = "proyecto"
python -m pytest -q proyecto/tests -m "not live"
python -m radar historico-spot --desde 2026-11-22 --hasta 2026-11-23 --max-paginas 30
python -m radar salud
```

También hay un flujo GitHub Actions para ejecutar las pruebas offline en cada PR.

## Límites que siguen pendientes

- **WAL durable:** almacenamiento local de eventos/batches antes de confirmar recepción.
- **Integridad y cobertura por intervalos:** manifiestos por canal, epoch de conexión, lag, tamaño de cola, gaps y secuencias. `salud` solo mide frescura.
- **Backfill de trades spot individuales** y deduplicación transversal (exchange, trade_id).
- **Archivo histórico L2 de OKX:** confirmar disponibilidad exacta de BTC/EUR, formato, permisos, tamaños y costes antes de implementarlo.
- **Histórico de Bitvavo anterior al rango visible por API:** no presuponer acceso ilimitado.
- **Historias completas de opciones:** la captura actual solo obtiene fotos de Deribit; no constituye un histórico profundo anterior a nuestra observación.
- **Despliegue de alta disponibilidad:** las tareas Windows no funcionan si el PC está apagado o suspendido; se necesitaría infraestructura siempre encendida y supervisada.
- **Pruebas end-to-end de larga duración:** correr en un entorno de pruebas antes de actualizar las tareas reales, medir latencia, pérdidas, duplicados, recuperación y uso de recursos.

## Referencias de API

- OKX: https://www.okx.com/docs-v5/en/
- Bitvavo velas: https://docs.bitvavo.com/docs/rest-api/get-candlestick-data/
- Kraken OHLC: https://docs.kraken.com/api/docs/rest-api/get-ohlc-data

Cualquier conclusión estadística debe quedar asociada al código, parámetros,
muestra y advertencias sobre calidad y cobertura de los datos.
