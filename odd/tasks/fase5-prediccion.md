Objetivo: Fase 5 (predicción: momentum y reversión) sobre las velas del radar, con protocolo de muestra guardada bajo llave.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

- S1 · Conceptos de la Fase 5 (QUANTLAB.md): "momentum · media simple y exponencial · z-score · señales de momentum y reversión · objetivo con entrada en t + 1 · IC de Pearson y Spearman · separación cronológica con purga · retorno neto y coste de equilibrio · autocorrelación y Ljung-Box · falsos positivos y pruebas múltiples (Bonferroni, BH) · data snooping".
- S2 · "Abierto: cualquier señal nueva se contrasta en una muestra nueva, no en la ya usada." Protocolo (decisión del padre, comunicada al usuario): desarrollo con velas hasta el 31-12-2024; muestra guardada bajo llave desde el 01-01-2025, que se evalúa una sola vez, para las señales que sobrevivan en desarrollo, y cuya apertura queda registrada.
- S3 · Costes reales: comisión taker de Kraken 0,80 % por lado (`radar/configuracion.py`); reportar el neto con taker y con maker (0,40 %) y el coste de equilibrio de cada señal.

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1, S2, S3 | delegada (W1: disparador de contexto, sesión muy larga) | hecho: `prediccion.py`, 17 tests (RED observado) | — |
| T2 | todas | inline | hecho: comando `prediccion` (y `--abrir-muestra-guardada`, fuera del ciclo semanal: los datos de desarrollo no cambian), `fuente` como parámetro del registro (RED → GREEN), 328 tests | — |

## Log

- L1 (2026-11-22) · Usuario: "sigamos con la fase 5".
- L2 · W1 entregado. Desarrollo real: horario 15 confirmadas (reversión; equilibrio 2–9 bps por lado), diario 19 confirmadas (tendencia; ganan tras comisiones pero no a comprar y mantener). 34 sobreviven el filtro estadístico. Muestra guardada sin abrir. Pendiente decisión del usuario: criterio para entrar en la muestra guardada (estadístico solo, o también económico).
- L3 · Usuario: "si, cambia el criterio y haz commit y push". Filtro económico añadido a `supervivientes_desarrollo` y a la huella de la familia (RED → GREEN). Desarrollo re-corrido con la nueva familia (5d59bf9125ba): 0 señales confirmadas y rentables; la muestra guardada no se abrió. Suite 329.
