# QuantLab · Integridad entre módulos 1, 2 y análisis/calidad

**Rama:** `feature/quantlab-integridad-123-20261123`  
**Dependencia:** PR #2 (captura continua, históricos spot, controles de frescura).  
**Estado:** propuesta con pruebas automáticas, **no desplegada** en el ordenador de captura.

## Flujo continuo entre módulos

```text
REST / WS / históricos
    -> capturador.py / flujo/captura.py (captura_id; conexion_id WebSocket)
    -> filas_evento / fila_trade / filas_de_ronda
    -> AlmacenDurable.guardar() [OPCIONAL en WebSocket]
         -> SQLite journal_mode=WAL; synchronous=FULL; INSERT de lote con UUID
         -> worker y LakeParquet.guardar_lote(..., lote_id)
         -> Parquet data/lake/<fuente>/fecha=AAAA-MM-DD/lote_UUID.parquet
         -> DELETE de la cola después de publicar todas las particiones
    -> LakeParquet.consultar() y vistas DuckDB
    -> continuidad.py / auditoria.py / calidad.py
    -> estudios estadísticos
         -> trazabilidad.registrar_estudio(): run_id, commit y huellas de archivos
         -> LakeParquet.guardar(): añade run_id a la salida
```

## Módulo 1 · Identidad de la captura

**REST:** `capturador.capturar()` asigna una `captura_id` diferente a cada ejecución. Los números de ronda por sí solos no son globalmente únicos porque vuelven a empezar tras reiniciar el proceso.

**WebSocket:** `_Captura` asigna una `captura_id` por proceso y `_sesion()` una `conexion_id` nueva al reconectar. Los registros de `eventos_libro` conservan, además del modelo previo, `secuencia_previa`, `checksum`, `precio_decimal` y `cantidad_decimal` (como texto), cuando el protocolo aporta esos campos. Las fotos y los trades también guardan `conexion_id`.

**Limitación:** estos campos no prueban por sí solos que no existan pérdidas. Las actualizaciones ya normalizadas no constituyen un archivo literal de todos los mensajes de red; sigue pendiente una capa de conservación cruda opcional y su evaluación de coste.

## Módulo 2 · Parquet, WAL y auditoría

`LakeParquet.guardar()` valida `recibido_utc`, rechazando `NaT`, fechas imposibles, columnas ausentes y fuentes con nombres no seguros. Una fecha nula ya no puede quedar descartada silenciosamente por `groupby`.

`LakeParquet.guardar_lote(filas, fuente, lote_id)` utiliza nombres estables en cada partición UTC; una recuperación con el mismo ID no vuelve a escribir automáticamente el archivo ya publicado. Comprueba su número de filas, **no su hash íntegro**.

`AlmacenDurable` introduce un registro de lotes con SQLite:

1. Serializa las filas y confirma la inserción en SQLite (modo WAL, `synchronous=FULL`).
2. Agenda la publicación Parquet en un hilo con cola limitada.
3. Elimina el lote de SQLite solo después de completar `guardar_lote`.
4. En la siguiente apertura con la misma ruta recupera pendientes. Si un archivo ya existe, no lo duplica.

Uso de prueba, **sin sustituir todavía las tareas programadas**:

```powershell
cd proyecto
python -m radar flujo 60 --wal-durable
```

La ruta predeterminada del registro es `data/wal/flujo.sqlite`. **No lanzar dos procesos WS independientes sobre ese mismo WAL** sin adaptar su coordinación; el diseño y pruebas actuales son para un escritor único.

Comprobar archivos sin modificarlos:

```powershell
python -m radar auditar-lake
python -m radar auditar-lake --profundo
```

La inspección profunda lee fechas de todas las filas de cada archivo; puede consumir recursos y generar falsos avisos por temporales que estén siendo escritos justo en ese momento. Mejor ejecutar sobre una captura detenida o una copia.

**Lo que no garantiza:** no recupera un mensaje que nunca recibió el proceso, ni un evento que esté en la memoria antes de registrar un lote; tampoco ofrece una transacción única y visible para lotes que cruzan dos particiones diarias. El WAL tampoco convierte las fuentes WebSocket en sistemas de entrega exactly-once de extremo a extremo.

## Calidad temporal y análisis

`diagnosticar_continuidad()` compara `cotizaciones` y `libros_flujo` por exchange. Registra:

- Ventanas sin fuente o sin datos.
- Tramos vacíos iniciales/finales.
- Cortes internos de más de `umbral_s`, **incluso si superan 60 segundos**.

```powershell
python -m radar continuidad --horas 24 --umbral-s 5
```

Un corte es evidencia de falta de *fotografías observadas*, no necesariamente prueba de que el mercado se detuviera o perdiera cada mensaje individual.

Para los comandos analíticos o de actualización, `registrar_estudio()` genera un JSON en `data/ejecuciones/` con:

- `run_id`, comando y parámetros.
- Versión del repositorio (`git rev-parse HEAD`, si disponible).
- Momento de inicio/fin, estado, error.
- Listado, tamaño y fecha de modificación de los Parquet antes/después, y SHA256 **de ese inventario**.
- Indicación de si cambió el inventario durante el proceso.

Las salidas `LakeParquet.guardar()` generadas dentro del contexto se etiquetan con el mismo `run_id` para relacionarlas con el manifiesto. Las ejecuciones `--no-guardar` no generan este registro automático.

**Límite de reproducibilidad:** no se calculan automáticamente SHA256 de todos los bytes, ni se congela una instantánea transaccional de DuckDB. Si cambia un fichero o se compacta, un inventario de metadatos por sí solo no sirve para reproducir un estudio de manera bit a bit.

## Validación y puesta en producción

```powershell
$env:PYTHONPATH = "proyecto"
python -m pytest -q proyecto/tests -m "not live"
python -m radar auditar-lake
python -m radar continuidad --horas 1
```

Antes de habilitar `--wal-durable` en la captura real: verificar la suite de GitHub, probar los tres exchanges mediante conexiones reales, simular cierre ordenado y abrupto, comparar filas/huellas antes y después, medir latencia y espacio del WAL durante 24–72 horas y comprobar que solo hay **un proceso** utilizando el registro.

Las mejoras más amplias —compactación segura con catálogo transaccional, reconstrucción a partir de mensajes crudos, hashes de contenido, snapshots de lectura inmutables, control universal de calidad en todos los estudios y disponibilidad 24/7— siguen pendientes de implementación y validación. No deben presentarse como completadas.
