Objetivo: Fase 7 (derivados) del radar: histórico de perpetuos (basis, funding, open interest, liquidaciones) y valoración de opciones.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

- S1 · Conceptos (QUANTLAB.md, Fase 7): "perpetuo lineal · basis · mark e índice · open interest · funding y su pago · liquidaciones · margen y umbral de mantenimiento · cobertura con perpetuos · carry de un perpetuo con funding solo observado · basis anualizado" y el abierto "histórico horario de basis, funding, OI y liquidaciones". Fuentes públicas de derivados (nuestros exchanges spot no los tienen): OKX y Kraken Futures. Solo investigación.
- S2 · "payoffs de futuro, call y put" y el abierto "valoración de opciones (Black-Scholes, paridad put-call, griegas)", con la cadena pública de opciones de BTC de Deribit. Solo investigación.

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | delegada (W1, paralelo) | hecho: `derivados.py` (adaptador, caso de uso, estudio), 31 tests + 2 live (RED observado); descriptivo | — |
| T2 | S2 | delegada (W2, paralelo) | hecho: `deribit.py`, `opciones.py` (captura y estudio), 53 tests + 1 live (RED observado); descriptivo | — |
| T3 | todas | inline | hecho: comandos `historico-derivados`, `derivados`, `opciones`; ciclo semanal (+4 pasos; el modo prueba salta la captura de opciones); 442 tests | — |

## Log

- L1 (2026-11-22) · Usuario: "sigamos con la fase 7". Propuesta: datos públicos de OKX y Kraken Futures (perpetuos) y Deribit (opciones), solo para investigar.
- L2 · W1 entregado. Kraken PF_XBTUSD (1 año): basis +0,46 bps (+5 % anual), funding +3,6 % anual (positivo el 68 %), carry neto de la cobertura +1,3 % anual con taker spot 0,80 %; liquidaciones agrupadas 13,6 veces más cerca de movimientos grandes. OKX BTC-USDT-SWAP: índice ~4,6 bps por encima del perpetuo todo el año, funding +5,6 % anual; carry +3,9 % anual. Ojo: la comisión spot de OKX usada es 0,10 % (cuenta con derivados), no el 0,20 % de solo spot del usuario; la del perpetuo (0,05 %) es un supuesto sin verificar.
- L3 · W2 entregado. Black-76 reproduce el mark de Deribit; paridad sin violaciones (447 pares); sesgo bajista; estructura invertida; IV 30 d ≈ realizada. Deribit da 429 tras ~240 tickers: por defecto 120 cercanos al dinero. Padre: comandos y ciclo semanal; en modo prueba la captura de opciones se salta (no respeta --no-guardar).
