Objetivo: Fase 4 (comportamiento histórico) del radar: velas OHLCV propias y un histórico largo de Kraken, con retornos y volatilidad.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

- S1 · Velas OHLCV propias desde los trades del websocket (`trades`): "vela OHLCV · volumen monetario y VWAP de la vela · velas vacías y de frontera" (QUANTLAB.md, Fase 4).
- S2 · Histórico largo de Kraken (el plan: "Abierto: histórico largo y continuo"). Decisión del usuario: "si, vamos con la mezcla" → velas propias para lo que se opera e historial oficial de Kraken para el histórico largo.
- S3 · Retornos y volatilidad sobre las dos fuentes: "retorno simple, logarítmico y acumulado · segmentos sin huecos · volatilidad móvil y realizada · anualización · retorno futuro sin mirar el futuro".
- S4 · Comparar velas propias y de Kraken en los mismos días (propuesta aceptada con la mezcla: "las velas propias y las de Kraken se pueden comparar en los mismos días").

Formato común de vela (contrato entre W1 y W2): una fila por (fuente, exchange, par, intervalo_s, inicio_utc) con apertura, maximo, minimo, cierre (EUR; NaN si vacía), volumen_btc, volumen_eur, vwap (NaN si vacía), n_trades (NaN si la fuente no lo da), vacia (bool), completa (bool: la vela terminó y la captura cubrió todo su intervalo), recibido_utc (cuándo se calculó o descargó). `fuente` = "propia" o "kraken_historico". Horas en UTC; `inicio_utc` alineado al reloj (múltiplo de `intervalo_s`).

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1, S3 | delegada (W1, paralelo) | hecho: `velas.py`, `retornos.py`, 20 tests (RED observado) | — |
| T2 | S2, S4 | delegada (W2, paralelo) | hecho: `kraken_historico.py`, `historico_kraken.py`, `comparacion_velas.py`, 23 tests + 2 live (RED parcial: primera versión sin RED previo, dos arreglos posteriores con RED) | — |
| T3 | todas | inline | hecho: 4 comandos, ciclo de 21 pasos (prueba 6 min, 0 fallos; en modo prueba se saltan los que solo actualizan datos), histórico importado, 309 tests | — |

## Log

- L1 (2026-11-22) · Usuario: "sigamos con la fase 4". Propuesta: mezcla de velas propias e historial de Kraken. Usuario: "si, vamos con la mezcla".
- L2 · W1 entregado. Velas con hora del exchange; latido de captura = fotos de `libros_flujo` (hueco > 5 s). Desviación del contrato: `completa` exige cobertura ≥ 99 %, no el 100 % (la captura pierde 11–18 s en cada reinicio horario; con 100 % ninguna vela de 1 h o 1 día sería completa). El padre la acepta. Real: 1.449 velas propias (6,5 h); a 1 min, volatilidad anualizada 58–72 %, colas gruesas y agrupamiento de volatilidad en los tres; 1 h y 1 día: datos insuficientes.
- L3 · W2 entregado: el archivo de Kraken se lee por HTTP Range (no hace falta descarga manual). Padre: comandos `velas`, `historico-kraken`, `comparar-velas`, `retornos`; importado: 115.154 velas horarias y 4.822 diarias desde 2013 (hueco horario 1–23 oct 2026); propias = oficiales al 100 % en 1 y 5 min. Retornos 13 años: 69,9 % anual diario, 78,8 % horario, colas gruesas, agrupamiento, regímenes. Sin verificación independiente: la fase solo añade módulos y fuentes nuevas (no toca código compartido ni datos existentes).
