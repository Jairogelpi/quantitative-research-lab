Objetivo: Fase 6 (mercados interconectados) del radar: arbitraje entre exchanges y un estudio integral con protocolo registrado antes de mirar.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

- S1 · "arbitraje entre exchanges con comisiones · episodios de oportunidad" (QUANTLAB.md, Fase 6), con la profundidad real y nuestra latencia.
- S2 · "protocolo previo · R² fuera de muestra · bootstrap por bloques · null circular · decisión estadística frente a económica" y el abierto "el protocolo alternativo E1 de P17, en una captura nueva": hipótesis "Kraken sigue a OKX y Bitvavo" (hallazgos de `leadlag` y `senales`), protocolo registrado ANTES de analizar y evaluado solo con datos capturados después del registro.

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | delegada (W1, paralelo) | hecho: `arbitraje.py`, 7 tests (RED observado) | — |
| T2 | S2 | delegada (W2, paralelo) | hecho: `protocolo_leadlag.py`, 17 tests (RED observado); protocolo SIN registrar | — |
| T3 | todas | inline | hecho: comandos `arbitraje` y `protocolo`, arbitraje en el ciclo semanal, `estudios_protocolo` excluido del registro (RED → GREEN); 356 tests | — |

## Log

- L1 (2026-11-22) · Usuario: "sigamos con la fase 6". Propuesta: (1) arbitraje entre exchanges; (2) estudio integral con protocolo registrado antes de mirar, evaluado en la captura posterior al registro.
- L2 · W2 entregado. Protocolo por defecto: señal = retorno medio de OKX y Bitvavo en los 2 s previos; objetivo = mid de Kraken desde t + 0,5 s (0,25 latencia + 0,25 decisión) a 5 s; umbral 1 bps; taker 0,80 %; mínimo 2.000 decisiones y 200 operaciones. Comprobación de desarrollo (3 h, antes del registro): IC 0,000 con 0,5 s de retraso; el IC cae de 0,03–0,08 sin retraso a 0,00–0,03 con 0,5 s. Pendiente decisión del usuario sobre el retraso antes de registrar. Pendiente del padre: excluir `estudios_protocolo` del registro global.
- L3 · W1 entregado. Real (6 h): libros cruzados el 84 % del tiempo por 1–20 bps; con comisiones, 0 episodios rentables. Padre: comandos y documentación. Pendiente: respuesta del usuario sobre el retraso del protocolo (propuesta 0,3 s según la latencia medida) y su registro.
- L4 · Usuario: "si, fíjalo en 0,3 s y haz commit y push". Retraso = 0,29 s de latencia (la ida y vuelta más lenta medida, OKX) + 0,01 s de decisión; huella 472cde2e…; 17 tests del protocolo en verde. El registro lo hace el usuario.
