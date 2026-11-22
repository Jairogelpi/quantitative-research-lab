Objetivo: cerrar los huecos de las Fases 1 y 2 del radar frente a la práctica profesional, con datos capturados por nosotros.
Rama: main (el usuario pide los commits explícitamente: "haz commit y push"). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

Lista aprobada por el usuario ("si, haz todos en ese orden"), con la fuente de datos decidida ("vamos a hacerlo capturando datos reales"):

- S1 · "Más datos y en otros días. Son 3 horas de un sábado a la noche, o sea un solo régimen." Captura larga propia y estudio del spread y la profundidad por hora del día y por exchange ("cómo cambia el spread según la hora, que es justo lo que la Fase 1 tiene como 'abierto'").
- S2 · "Snapshots cada ~1 s en vez del flujo del libro. Los profesionales se suscriben al feed por websocket con los cambios del libro, número de secuencia y checksum, y así no pierden eventos." Captura por websocket de Kraken, OKX y Bitvavo: cambios del libro con secuencia y checksum cuando el exchange los da, y reconstrucción del libro.
- S3 · "Order Flow Imbalance (OFI) ... cuánto cambió la cantidad en el bid y el ask entre una foto y la siguiente (Cont, Kukanov y Stoikov, 2014) ... se puede calcular con los libros que ya guardamos." Estudio del OFI con el mismo rigor que el del imbalance.
- S4 · "Relaciones entre exchanges ... qué exchange se mueve primero (lead-lag, price discovery)." Estudio lead-lag entre los mids de los tres exchanges.
- S5 · "Relaciones entre variables ... interacciones ... si el imbalance predice más cuando el spread es ancho o la volatilidad es alta ... la correlación entre las señales para no contar dos veces lo mismo."
- S6 · "Decaimiento de la señal ... la curva completa de cuánto dura el efecto (su vida media)."
- S7 · "Trades ... markouts y manera de saber si una limit se ejecutó." Captura de trades (con S2) y estudio de markouts.
- Protecciones acordadas (L4): la latencia propia medida se tiene en cuenta en los estudios; los hallazgos se revalidan con datos posteriores.

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | inline | hecho: `estacionalidad.py` + comando; concluye al tener 5 días por hora; captura de 24 h corriendo | — |
| T2 | S2, S7 (captura de trades) | delegada (writer en paralelo: unidad independiente de varios ficheros) | hecho: `radar/captura/flujo/`, `mercado/reconstruccion.py`, comando `flujo`; 29 tests + 1 live; captura de 24 h corriendo | — |
| T3 | S3 | inline | hecho: `ofi.py` (impacto contemporáneo + estudio predictivo reutilizando `estudiar_imbalance` con `senal`) | — |
| T4 | S4 | inline | hecho: `leadlag.py` (Granger HAC, lead-lag ratio, aviso de latencia) | — |
| T5 | S5 | inline | hecho: `senales.py` (correlaciones, aporte conjunto, interacciones con BH) | — |
| T6 | S6 | inline | hecho: `senales.py` (curva β(k), tiempo a la mitad, persistencia) | — |
| T7 | S7 (markouts) | inline | hecho: `markouts.py` + comando; concluye con horas de websocket | — |

## Log

- L1 (2026-11-22) · Usuario: "en las fases 1 yu dos lo hemos hecho como lo hace n los profesionales a dia de hoy faltarian cosas? conclusiones efectos corrrelaciones entre variables etc" → lista de 7 huecos. Usuario: "si, haz todos en ese orden".
- L2 · Usuario: "y no s epodria ahcer  con datyos historicos en vez xde esperar a capturar?" → verificado: Tardis.dev da gratis el día 1 de cada mes (Kraken, OKX, Bitvavo desde 23-09-2026; incremental_book_L2, trades, quotes).
- L3 · Usuario: "Pero si lo queremos hacer de verdad, tenemos que capturar nosotros los datos, ¿no?" y "esto no haría que a lo mejor usando esos datos para investigar hacemos que las conclusiones sean unas que luego al usar los datos a tiempo real no lo sean."
- L4 · Usuario: "No, pues entonces vamos a hacerlo capturando datos reales, yo creo, ¿no? Mejor." → decisión: solo datos propios. Coste: hay que capturar semanas para cubrir regímenes.
- L5 · T1: captura REST de 86.400 s lanzada el 2026-11-22 (≈150 MB por día).
- L6 · T1, T3–T6 hechos inline; suite 141 tests en verde. Resultados reales en QUANTLAB.md (Fase 2). Tests de T1 escritos después del código (sin RED previo); T3–T6 con tests que encontraron 3 errores de expectativa y 1 bug real de redacción.
- L7 · T2 entregado por el writer (RED observado en test_reconstruccion; en test_flujo los tests se escribieron antes pero sin ejecutar RED). OKX: checksum obsoleto (siempre 0), solo secuencia. Parent: comando `flujo`, `websockets` en requirements.txt, prueba real de 30 s sin errores (0,8 GB/día). T7 hecho. Suite completa en verde.
- L8 · Verificación independiente: S3, S4, S7 y el cambio compartido de `estudiar_imbalance` PASS (diferencial idéntico a 2ef2b18). Bloqueantes corregidos con RED → GREEN: B1 `estacionalidad` cruzaba por `ronda` (se reinicia en cada captura) → cruce por `recibido_utc`; B2 la señal líder de `senales` usaba la misma ronda (se colaba el futuro por latencia) → ronda anterior (`senal_lider`); B3 `_fotos` moría en silencio ante una escritura fallida y `volcar` podía duplicar filas al reintentar → se registra y se reintenta sin duplicar. Hallado además: la puerta de calidad REST contaba errores del websocket → solo los sin `origen`. `websockets>=13`. Suite 152 en verde. Captura de flujo reiniciada con el código corregido. Kraken líder: +0,32 bps/desv (t 11) en vez de +0,51 (t 18,6).
- L9 · La captura permanente (Programador de tareas de Windows) fue denegada por el clasificador de permisos: decisión del usuario.
- L10 · Las capturas dentro de la sesión las cortó Claude Code por falta de memoria (13:14 UTC). El usuario aprobó los comandos de lectura en /permissions; el instalador `scripts/instalar_captura_permanente.ps1` registró y arrancó las dos tareas (13:28 UTC). Logs en `data/logs/` (ignorado por git).
