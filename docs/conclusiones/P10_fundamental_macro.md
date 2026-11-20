# P10 · Valoración fundamental y macroeconomía · Conclusiones

**Cuaderno:** `notebooks/01_financial_foundations/P10_fundamental_macro.ipynb`
**Datos:** bonos y DCF hipotéticos, 48 meses de indicadores macro sintéticos, 48 publicaciones sintéticas de IPC con precios horarios de BTC/USD, y seis series reales de FRED de 2022 a 2025 (descargadas el 19-11-2026)

## Conclusiones

| # | Conclusión | Código que la respalda | Concepto |
|---|---|---|---|
| 1 | Ante una subida de rendimiento del 4 % al 5 %, el bono a 2 años pierde un 1,86 %; a 5 años, un 4,33 %; a 10 años, un 7,72 %. | E2 · `bond_shock` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 2 | El valor terminal es el 75,9 % del valor de empresa del DCF. | `dcf` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 3 | Con los mismos flujos, el valor por acción va de 6,40 € a 47,00 € según r y g; pasar de r = 8 % a 10 % lo baja un 30 %. | `dcf_sensitivity` · E3 | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 4 | Con un 15 % nominal y un 10 % de inflación, la aproximación da un 5 % real y la fórmula exacta, un 4,55 %. | E4 · `fisher_comparison` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 5 | El estudio de eventos detecta el efecto programado: +45,6 bps tras sorpresas inferiores y −44,6 bps tras sorpresas superiores a 1 h (desarrollo). | `align_events` · `surprise_groups` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 6 | En validación, el grupo "Inferior" mantiene el signo (+39,3 bps, 3 eventos) y no hay ningún evento "Superior". | `development_horizons` · E6 | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 7 | El efecto se ve mejor a 1 hora: la correlación sorpresa–retorno es −0,82 a 1 h y −0,39 a 24 h, porque el ruido posterior lo tapa. | E6 | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 8 | FRED no tiene IPC ni paro de octubre de 2025. Calculando por posición, la inflación de noviembre sale 2,99 %; por fecha, 2,70 %. | E7 · `yoy_by_date` | [Series temporales](../conceptos/series_temporales.md) |
| 9 | La curva real 10 − 2 años estuvo invertida el 54,2 % de los días de 2022–2025, con un mínimo de −108 bps (3 de julio de 2023). | E7 · `fred_indicators` | [Valoración y macro](../conceptos/valoracion_y_macro.md) |
| 10 | Sin consenso archivado ni hora de publicación (100 % ausentes en FRED), el estudio real no se puede hacer: evidencia insuficiente. | E8 · `availability_report` | [Validación](../conceptos/validacion_de_datos.md) |

## Estudio de eventos sintético (umbral ±0,15 pp)

| Periodo | Grupo | n | 1 h | 6 h | 24 h |
|---|---|---|---|---|---|
| Desarrollo | Inferior | 6 | +45,6 | +42,8 | +74,9 |
| Desarrollo | En línea | 19 | −0,3 | −4,1 | +3,2 |
| Desarrollo | Superior | 6 | −44,6 | −51,5 | −43,4 |
| Validación | Inferior | 3 | +39,3 | +26,4 | +24,9 |
| Validación | En línea | 14 | +15,7 | +21,2 | +29,2 |

## E7 · FRED (2022–2025)

| Indicador | Valor |
|---|---|
| Inflación interanual máxima / mínima / final | 6,33 % (ene-2023) / 2,33 % (abr-2025) / 2,65 % (dic-2025) |
| Curva invertida | 54,2 % de los días; mínimo −108 bps |
| Última inversión | 5 de septiembre de 2024; final de 2025: +71 bps |
| Meses sin IPC ni paro | octubre de 2025 |

## Limitaciones

- El efecto de los eventos sintéticos está programado: detectarlo verifica el método, no el mercado.
- Los grupos tienen 0 a 19 eventos: las medias son muy inestables y no se afirma significación.
- La serie de FRED es la revisada de hoy, no la que se conocía en cada fecha.
- La reacción medida incluye el movimiento de la noticia: no es un retorno ejecutable después de conocerla.
- El DCF no es un modelo de valoración de BTC, que no genera flujos de caja por poseerlo.

## Código y pruebas

- Funciones: `src/quantlab/p10/valuation_macro.py` → `present_value`, `bond_price`, `dcf`, `value_per_share`, `dcf_sensitivity`, `yoy_by_date`, `macro_features`, `real_return`, `synthetic_macro`, `fetch_fred`, `synthetic_events_and_prices`, `validate_events_prices`, `align_events`, `split_events`, `surprise_groups`, `manual_pv`, `bond_shock`, `fisher_comparison`, `inverted_curve`, `development_horizons`, `fred_indicators`, `availability_report`.
- Pruebas: `tests/test_valuation_macro.py` (valor temporal, bonos, DCF, inflación por fecha con un mes ausente, validación de eventos, alineación causal, E1–E8 y 1 prueba en vivo).
