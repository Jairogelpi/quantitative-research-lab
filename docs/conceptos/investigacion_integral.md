# Investigación integral: protocolo, rejilla causal, predictibilidad, ejecución y decisión

**Familia:** método de investigación · **Visto en:** P17 · **Código:** `src/quantlab/p17/integrated_research.py`

## Conceptos

| Concepto | Campo | Fórmula / regla | Qué nos dice |
|---|---|---|---|
| Protocolo registrado | `register_protocol` | SHA-256 del JSON ordenado | Hipótesis y criterios fijados antes de mirar. |
| Rejilla causal | `synchronize` | Última cotización con `received_at` ≤ t y edad ≤ 1,5 s | Qué se conocía en cada segundo. |
| Lead-lag | `lead_lag` | Corr(r_Kraken,t, r_OKX,t+k) | Si un mercado precede a otro (no causalidad). |
| Señal | `signal_bps` | Retorno del mid de Kraken en 3 s | Lo que se usa para decidir en t. |
| Objetivo | `target_bps` | Retorno del mid de OKX de t+1 a t+5 | Lo que se intenta anticipar. |
| R² fuera de muestra | `predictability` | 1 − SSE(modelo congelado) / SSE(media de desarrollo) | Si el modelo de desarrollo funciona en validación. |
| PnL neto | `evaluate` | q · (bid · (1 − e) − ask · (1 + e)) − comisiones | Resultado al ejecutar contra el libro. |
| PnL condicionado | `net_eur_conditional` | Suma solo de las señales con profundidad | Sesgado si hay señales sin profundidad. |
| Bootstrap por bloques | `block_ci` | Medias de bloques circulares de 10 oportunidades | Incertidumbre con dependencia temporal. |
| Null circular | `circular_shift_null` | Corr con el objetivo desplazado circularmente | Significancia sin destruir la autocorrelación. |
| Ejecución parcial | `partial_fill_engine` | min(q, tamaño L1) al entrar y al salir, con espera | Qué pasa con las señales sin profundidad. |
| Decisión | `decision` | Estadística: pendiente > 0 y p < 0,05. Económica: IC > 0, sin fallos ni huecos | Aprobar o no la hipótesis. |

## Ideas clave

- **El protocolo va primero:** señal, umbral, corte, costes y criterios se fijan antes de ver la validación.
- **La hora que manda es la de recepción:** `exchange_at` depende de un reloj ajeno; en la captura real, el de OKX iba hasta 0,42 s por delante del local.
- **Predecir no es ganar:** en la simulación, R² fuera de muestra del 32,9 % y todas las operaciones pierden.
- **Excluir por profundidad futura es una selección ex post:** el PnL de esas señales es desconocido, no cero.
- **Una pendiente negativa en la atribución puede ser selección:** las ventanas que activan la señal son las que más se mueven, y en ellas se paga el coste.
- **Barajar destruye la dependencia temporal:** dos paseos aleatorios independientes con correlación 0,63 son "significativos" con un null barajado.
- **Una señal nueva necesita una muestra nueva:** el OBI de OKX, ruido puro, sale con p = 0,04 en desarrollo.
- **Un resultado negativo reproducible es una investigación válida.**

## Validación

- `validate`: columnas, todos los exchanges, sin duplicados por exchange, precios y tamaños > 0, sin libros cruzados.
- `synchronize`: tramo común ≥ 500 s, sin interpolar ni rellenar.
- `opportunities`: las ventanas que cruzan el corte se purgan; las incompletas se cuentan y se descartan.
- `run_study`: se detiene con menos de 60 oportunidades observadas por segmento.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Ida y vuelta | compra 100, venta 101, mids 99,5 → 101,5, 1 BTC, 10 bps | bruto +2 €, spread 1 €, comisión 0,201 €, neto **+0,799 €** |
| Coste por operación | 10 bps por lado + 1 bp de reserva + spread | ~22 bps (simulación), ~25 bps (real) |
| Señal frente a coste | bruto medio ~1,2 bps por operación (simulación) | el coste es ~19 veces mayor |

## Código

```python
from quantlab.p17.integrated_research import run_study, synthetic_quotes
import pandas as pd

out = run_study(synthetic_quotes())                                     # simulación de referencia
real = run_study(pd.read_csv("data/raw/p17_quotes_20261120.csv"))      # captura de P06 (no versionada)
real["stats"], real["summary"], real["decision"]
```

Relacionado: [comparacion_entre_exchanges.md](comparacion_entre_exchanges.md) · [costes_de_ejecucion.md](costes_de_ejecucion.md) · [eficiencia_de_mercado.md](eficiencia_de_mercado.md) · [order_flow_e_impacto.md](order_flow_e_impacto.md)
