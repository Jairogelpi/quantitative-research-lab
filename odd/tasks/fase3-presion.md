Objetivo: completar la Fase 3 (presión compradora y vendedora) del radar con los datos propios del websocket.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

Lista aprobada por el usuario ("haz los 6 seguidos"):

- S1 · "OFI exacto evento a evento. Es el punto que el plan deja abierto. Hoy el OFI se calcula entre fotos de 1 s, y con eventos_libro se puede calcular con cada cambio del libro, que es la versión original del artículo de Cont, Kukanov y Stoikov."
- S2 · "Trade imbalance y CVD: volumen comprador menos vendedor, por volumen y por número de trades, y su acumulado."
- S3 · "Intensidad: trades por segundo, y si la presión pesa más cuando el mercado está activo."
- S4 · "VWAP: el precio medio ponderado por volumen frente al mid."
- S5 · "Respuesta del precio a un trade: cuánto del movimiento que provoca un trade se queda (impacto permanente) y cuánto se revierte (transitorio). Es la función de respuesta de Bouchaud."
- S6 · "Exposición neta y bruta."

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | delegada (W1, paralelo) | hecho: `ofi_eventos.py`, reconstrucción refactorizada en `hayashi_yoshida.py` (diferencial idéntico en 108.151 filas), 20 tests | — |
| T2 | S2, S3, S4, S6 | delegada (W2, paralelo) | hecho: `presion.py`, 8 tests (RED observado) | — |
| T3 | S5 | delegada (W3, paralelo) | hecho: `respuesta.py`, 9 tests (RED observado) | — |
| T4 | todas | inline | hecho: comandos, ciclo semanal de 16 pasos (prueba: 6 min 17 s, 0 fallos); verificación independiente: 2 bloqueantes corregidos; 262 tests | — |

Ruta: writers en paralelo (3 unidades independientes de varios ficheros) y disparador de contexto (sesión muy larga). Superficies disjuntas; `__main__.py`, `analisis/__init__.py`, `scripts/` y la documentación los edita solo el padre.

## Log

- L1 (2026-11-22) · Usuario: "si, y luego seguimos con la fase 3" → lista de 6 puntos pendientes de la Fase 3. Usuario: "haz los 6 seguidos".
- L2 · Pendiente sin commit: `scripts/ciclo_semanal.ps1` (probado con `-Prueba`: 13 pasos, 0 fallos) e `instalar_ciclo_semanal.ps1` (registrar la tarea fue denegado por el clasificador: lo corre el usuario).
- L3 · El usuario registró la tarea "QuantLab ciclo semanal" (lunes 06:00) con `instalar_ciclo_semanal.ps1`.
- L4 · W2 entregado. Real (6 h): el trade imbalance mueve el mid en el mismo intervalo en los tres exchanges, pero no predice el siguiente; con intensidad alta el efecto es mayor (confirmado a 1 s); el lado neto paga por encima del mid ponderado en el tiempo (OKX +0,75 a +1,1 bps); la exposición neta/bruta no añade nada con el tamaño controlado. Hallazgo de W2 corregido por el padre (RED → GREEN): `liquidez` con mids exactos usaba la tolerancia de 2 s de las fotos y descartaba 7–28 % de los trades con el mid quieto; ahora vale el último cambio en o antes, con 300 s de tolerancia, también para el mid en t + h. Hay un corte de captura de ~873 s (el reinicio de las capturas, 13:14–13:28 UTC).
- L5 · W1 y W3 entregados. Padre: cotejo de la reconstrucción con `libros_flujo` validado por checksum: 100 % idéntica en los tres exchanges (Kraken: el R² menor del OFI por eventos es real, no un error; su mejor precio cambia 2,5 veces por segundo). Hallado (y también por W3): una ventana a mitad de tramo no tenía libro hasta el snapshot siguiente → `eventos_flujo` arranca en el último snapshot anterior y `_dentro` filtra a la ventana (RED → GREEN). Comandos y ciclo semanal conectados; estudios corridos y guardados.
- L6 · Verificación independiente: S1–S6 PASS en el código; reconstrucción idéntica a 97370ab (67.949 filas) y sin filas fuera de ventana. Bloqueantes corregidos con RED → GREEN: B1 el registro fusionaba las pruebas de presión (faltaban `medida` y `relacion` como parámetros), no reconocía los hallazgos de VWAP ni de la respuesta de Bouchaud y dejaba fuera la respuesta (t en `t_r1`); B2 `_UltimoMid` daba un mid futuro después del último dato observado (ahora NaN). Se corrigió además un test propio que asumía lo mismo. Registro real: 225 pruebas de 15 estudios, 80/82 hallazgos sobreviven BH global, 58 Bonferroni. Aviso: con una semana de datos, los pasos que reconstruyen el libro cargarán ~25 veces más eventos; revisar memoria en el log del primer lunes.
