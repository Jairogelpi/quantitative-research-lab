# P06 · Comparación entre exchanges · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P06_cross_exchange.ipynb`
**Datos:** cotizaciones L1 sintéticas de 1.800 s (semilla 61; OKX retrasado 2 s y Bitvavo 1 s, con dos desajustes extremos) y dos capturas reales de Kraken, OKX y Bitvavo BTC/EUR (19-11-2026, 20:23 UTC con 60 rondas y 20:28 UTC con 25)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | La correlación simultánea es casi nula (0,03 y −0,02) aunque los tres mercados siguen la misma trayectoria: está desplazada en el tiempo. | `fresh_returns` · `corr` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 2 | El lead-lag recupera los retrasos introducidos: +2 s en OKX y +1 s en Bitvavo (Kraken se adelanta). | `leadlag_summary` · E2 | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 3 | Pearson se deja arrastrar por los desajustes extremos (OKX 0,40 → 0,97; Bitvavo 0,98 → 0,29); Spearman se mantiene en ≈ 0,97. | `leadlag_summary(method="spearman")` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 4 | Retrasar 1 s la recepción de un exchange, sin tocar precios, desplaza el lag estimado 1 s: el lead-lag mide la recepción, no el liderazgo. | E5 · `delay_receipt` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 5 | Con 10 bps por lado hay 16 segundos-ruta candidatos en 6 episodios, pero son solo 2 eventos: los desajustes inventados. | `scan_routes` · `episodes` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 6 | Con 20 bps por lado o más no queda ningún candidato; con 0 bps aparecen 30 episodios de ruido. | `fee_sensitivity` · E4 | [Spread y costes](../conceptos/spread_y_costes.md) |
| 7 | Más tamaño nunca da más candidatos: 16, 14 y 4 segundos-ruta con 0,01, 0,05 y 0,1 BTC. | E3 · `size_comparison` | [Libro de órdenes](../conceptos/libro_de_ordenes.md) |
| 8 | El tamaño del `Ticker` de Kraken vale siempre 1; el libro `Depth` daba 0,006 y 0,273 BTC en el mismo instante. | `parse_quote` · `fetch_quote` | [Validación](../conceptos/validacion_de_datos.md) |
| 9 | En las capturas reales no hubo ningún candidato con comisiones: los tres precios están a 1–2 € entre sí, frente a unos 125 € por BTC de costes por ruta. | E6 | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |
| 10 | Con un minuto de captura no hay pares suficientes para el lead-lag, y la cobertura de OKX y las correlaciones cambian de una captura a otra. | E6 · `capture_report` | [Comparación entre exchanges](../conceptos/comparacion_entre_exchanges.md) |

## Simulación · rutas con 0,01 BTC y 10 bps por lado

| Ruta | Segundos elegibles | Segundos candidatos | Mejor margen neto |
|---|---|---|---|
| Kraken → OKX | 1.611 | 5 | +14,3 bps |
| Kraken → Bitvavo | 1.627 | 0 | −19,7 bps |
| OKX → Kraken | 1.635 | 0 | −18,7 bps |
| OKX → Bitvavo | 1.638 | 0 | −20,3 bps |
| Bitvavo → Kraken | 1.638 | 3 | +16,2 bps |
| Bitvavo → OKX | 1.626 | 8 | +16,9 bps |

## E6 · Captura real (20:23:36 – 20:24:35 UTC, 60 rondas, 0 errores)

| | Kraken | OKX | Bitvavo |
|---|---|---|---|
| Cobertura válida | 100 % | 50,8 % | 100 % |
| RTT mediano | 381 ms | 599 ms | 399 ms |
| Spread mediano | 0,02 bps | 2,70 bps | 0,18 bps |
| Retornos nuevos | 34 | 18 | 58 |

- OKX perdió la mitad de la cobertura porque sus cotizaciones llegaban entre 0,8 y 1,8 s después de su propio `ts`. En la segunda captura (20:28 UTC) su cobertura fue del 100 %.
- Arbitraje: 177 segundos-ruta elegibles y 0 candidatos; mejor margen neto, −19,3 bps.

## Limitaciones

- REST no da simultaneidad real: las solicitudes son concurrentes, pero cada exchange responde con su latencia y puede servir datos en caché.
- Sin relojes sincronizados no se distingue entre desfase de reloj, latencia de red y datos retrasados.
- El escáner usa L1: no estima profundidad L2, slippage, latencia de ejecución, inventario, reequilibrado, mínimos de orden ni fallos de una pierna.
- Las comisiones son supuestos didácticos, no tarifas vigentes.
- Las capturas reales duran un minuto: no permiten concluir nada sobre liderazgo ni oportunidades.

## Código y pruebas

- Funciones: `src/quantlab/p06/cross_exchange.py` → `parse_quote`, `fetch_quote`, `collect_live`, `synthetic_quotes`, `validate_quotes`, `align_quotes`, `fresh_returns`, `lag_profile`, `leadlag_summary`, `scan_pair`, `scan_routes`, `route_summary`, `episodes`, `fee_sensitivity`, `mid_and_spread`, `manual_cross_correlation`, `size_comparison`, `delay_receipt`, `capture_report`.
- Pruebas: `tests/test_cross_exchange.py` (adaptadores, validación, alineación causal, retornos nuevos, lead-lag, aritmética de costes, E1–E6 y 1 prueba en vivo).
