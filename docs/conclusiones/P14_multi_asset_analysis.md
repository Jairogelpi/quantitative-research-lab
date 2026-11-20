# P14 · Laboratorio multiactivo y capitalización · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P14_multi_asset_analysis.ipynb`
**Datos:** precios sintéticos de 2021 a 2025 (semilla 42) y cierres ajustados reales de Yahoo Finance (BTC-USD, SPY, IEF, GLD, VT y EURUSD=X; descarga del 19-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | +50 % y −50 % tienen una media aritmética de 0 pero dejan un −25 %. | `compound_return` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 2 | El tipo mensual equivalente al 12 % anual es 0,9489 %, no 1 %: 12 meses al 1 % dan un 12,68 %. | E2 · `equivalent_rate` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 3 | Duplicar en 3, 10 o 20 años exige un CAGR del 26,0 %, 7,2 % y 3,5 %, por debajo del "promedio" del 33 %, 10 % y 5 %. | E3 · `cagr` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 4 | Una semana interior sin datos detiene el análisis; rellenarla inventaría precios o retornos de dos semanas. | E4 · `prepare_weekly` | [Validación](../conceptos/validacion_de_datos.md) |
| 5 | Un +10 % en USD con el euro subiendo un 5 % es un +4,76 % en EUR. | E5 · `eur_return` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 6 | En un ejemplo de 3 años, el retorno de precio (+10 %) omite 9 puntos del total (+19 %); reinvertir llega al +19,8 %. | E6 · `dividend_paths` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 7 | Con datos reales, el oro tuvo el mayor CAGR (20,5 %) con una caída máxima del 9 %; BTC, un 19,8 % con un 57 % de volatilidad y una caída del 72 %. | E7 | [Rentabilidad y riesgo](../conceptos/rentabilidad_y_riesgo.md) |
| 8 | SPY ganó un 96,8 % en USD y un 102,9 % en EUR, porque el euro se depreció un 3 %. | E7 · `fx_decomposition` | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 9 | Con datos reales, BTC tiene una correlación semanal de solo 0,25 con las acciones; SPY y VT, de 0,97. | E7 | [Multiactivo](../conceptos/multiactivo_y_capitalizacion.md) |
| 10 | El ranking cambia entre mitades: BTC pasa de −3,4 % a +48,5 % de CAGR, y el oro de +6,4 % a +36,4 %. | E8 · `split_halves` | [Eficiencia](../conceptos/eficiencia_de_mercado.md) |

## E7 · Datos reales (semanas del 15-01-2021 al 26-12-2025, en EUR)

| Activo | Retorno | CAGR | Volatilidad | Caída máxima |
|---|---|---|---|---|
| BTC | +144,4 % | +19,8 % | 57,4 % | 72,2 % |
| Acciones (SPY) | +102,9 % | +15,4 % | 15,8 % | 21,4 % |
| Bonos (IEF) | −4,4 % | −0,9 % | 9,1 % | 15,4 % |
| Oro (GLD) | +151,1 % | +20,5 % | 14,0 % | 9,0 % |
| Global (VT) | +72,6 % | +11,7 % | 14,4 % | 18,7 % |
| USD efectivo | +3,1 % | +0,6 % | 7,5 % | 17,4 % |

## Limitaciones

- Yahoo Finance no es un feed oficial ni point-in-time; los ajustes por dividendos pueden revisarse.
- Los cierres diarios de mercados distintos no son simultáneos.
- No se incluyen impuestos, costes de negociación ni comisiones de los ETF más allá de lo ya reflejado en su precio.
- Cinco años divididos en dos ya cambian el ranking: no hay base para elegir un "ganador".

## Código y pruebas

- Funciones: `src/quantlab/p14/multi_asset.py` → `future_value`, `present_value`, `compound_return`, `synthetic_prices`, `download_prices`, `prepare_weekly`, `performance`, `fx_decomposition`, `total_return`, `manual_compound`, `equivalent_rate`, `cagr`, `eur_return`, `dividend_paths`, `split_halves`.
- Pruebas: `tests/test_multi_asset.py` (capitalización, calendario, conversión a EUR, validación, métricas y E1–E8).
- Dependencia nueva: `yfinance` (añadida a `requirements.txt`).
