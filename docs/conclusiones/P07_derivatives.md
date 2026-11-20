# P07 · Análisis de derivados financieros · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P07_derivatives.ipynb`
**Datos:** 720 horas sintéticas de un perpetuo lineal BTC/USDT (semilla 72) y una captura pública de OKX BTC-USDT-SWAP (19-11-2026, 20:33 UTC)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | La dirección del OI no dice nada sobre la del precio en la simulación: las cuatro combinaciones aparecen entre 163 y 187 horas. | `oi_regime` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 2 | En 235 de 719 horas el OI cambia de signo al pasar de BTC a USDT: el precio se movió más que las posiciones y en sentido contrario. | E2 · `oi_change_comparison` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 3 | El funding sintético está perfectamente correlacionado con el basis (1,00), pero por construcción: se define como el 15 % de la prima. | Sección 5 | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 4 | Los eventos de liquidación son muy pocos (4 a 12 por grupo) y su signo se invierte entre periodos: −20 bps tras liquidaciones de largos en desarrollo, +21 bps en validación. | `event_study` · E4 | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 5 | En una semana, la cobertura cobra 3,06 USDT de funding, pierde 1,54 por el basis y paga 4,72 de comisiones: −3,21 USDT (−0,18 % sobre el capital total). | `hedge_curve` · E5 | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 6 | Solo hay beneficio sin comisiones (+0,08 % en la semana); con el funding de signo invertido se pierde en todos los escenarios. | E5 · `carry_decomposition` | [Spread y costes](../conceptos/spread_y_costes.md) |
| 7 | Con 100 USDT de garantía (x12), basta una subida del mark del 7,7 % para cruzar el umbral; con 600 (x2), del 49,3 %. | E6 · `margin_breach_table` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 8 | Con un salto del +15 %, el short con 100 USDT cruza el umbral (patrimonio −34,5 USDT) mientras el spot gana 135,6 USDT y la cobertura va casi plana (−2,6). | E6 · `apply_price_shock` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 9 | En OKX, el funding anunciado (+0,69 bps) y el último liquidado (−0,18 bps) tenían signo contrario. | E7 · `okx_snapshot` | [Derivados perpetuos](../conceptos/derivados_perpetuos.md) |
| 10 | La captura de OKX es secuencial: el `ts` del funding era 33 s más antiguo que el del OI. No es una instantánea sincronizada. | E7 | [Validación](../conceptos/validacion_de_datos.md) |

## E5 · Carry de una semana (0,02 BTC, capital 1.796 USDT)

| Comisión por lado | Basis | Funding | Comisiones | Neto | Sobre el capital |
|---|---|---|---|---|---|
| 0 bps | −1,54 | +3,06 | 0,00 | +1,51 | +0,08 % |
| 10 bps | −1,54 | +3,06 | −4,72 | −3,21 | −0,18 % |
| 20 bps | −1,54 | +3,06 | −9,43 | −7,92 | −0,44 % |

Con el funding invertido: −4,60, −9,32 y −14,03 USDT.

## E7 · OKX BTC-USDT-SWAP (20:33:55 UTC)

| Campo | Valor |
|---|---|
| Spot / perpetuo / mark / índice | 61.968,0 / 61.936,5 / 61.953,4 / 61.990,2 USDT |
| Basis | −5,1 bps |
| OI | 3.306.060 contratos × 0,01 BTC = 33.060,6 BTC |
| Funding anunciado (pago de las 00:00 UTC) | +0,0000693 |
| Último funding liquidado (16:00 UTC) | −0,0000179 |
| Últimos 10 pagos | 5 positivos y 5 negativos, entre −0,18 y +0,63 bps |

## Limitaciones

- Los datos sintéticos prueban el procedimiento, no la existencia de Alpha.
- Las APIs públicas no dan un histórico completo de liquidaciones ni de OI: hace falta capturarlo de forma continua.
- La cobertura no modela spread, slippage, impuestos, reequilibrado, financiación del colateral ni riesgo de contraparte.
- La tasa de mantenimiento del 0,5 % es un supuesto docente: cada exchange tiene sus propios niveles de margen y reglas de liquidación.
- Los eventos pueden solaparse: sus resultados no son independientes.

## Código y pruebas

- Funciones: `src/quantlab/p07/derivatives.py` → `make_synthetic`, `normalize`, `add_features`, `oi_regime`, `split_for_horizon`, `event_summary`, `event_study`, `hedge_curve`, `margin_scenario`, `okx_get`, `okx_snapshot`, `basis_bps`, `oi_change_comparison`, `funding_payments`, `event_study_horizons`, `carry_decomposition`, `margin_breach_table`, `apply_price_shock`.
- Pruebas: `tests/test_derivatives.py` (normalización, indicadores, eventos sin fugas, cobertura con casos conocidos, margen, E1–E6, errores de OKX y 1 prueba en vivo).
