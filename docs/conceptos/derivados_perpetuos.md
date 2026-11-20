# Derivados perpetuos: basis, open interest, funding, liquidaciones y margen

**Familia:** derivados · **Visto en:** P07 · **Código:** `src/quantlab/p07/derivatives.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Perpetuo lineal | — | Contrato sin vencimiento, liquidado en USDT | Exposición a BTC sin comprar BTC. |
| Basis | `basis_bps` | 10⁴ · (P_perp − P_spot) / P_spot | Prima (+) o descuento (−) del perpetuo. No es una ganancia asegurada. |
| Mark e índice | `mark_index_bps` | 10⁴ · (mark / index − 1) | El mark valora posiciones y liquidaciones; el índice es la referencia del subyacente. |
| Open interest | `open_interest_btc` | Contratos abiertos × valor del contrato | Contratos vivos. Cada uno tiene un largo y un corto. |
| OI nominal | `oi_notional_usdt` | OI en BTC × mark | Cambia con el precio aunque no se abra nada. |
| Funding | `funding_rate` | Tasa por pago (0,0001 = 1 bp) | Pago entre largos y cortos para acercar el perpetuo al spot. |
| Pago de funding | `short_funding_usdt` | q · mark · tasa | Tasa positiva: los largos pagan y los cortos cobran. |
| Desequilibrio de liquidaciones | `liquidation_imbalance` | (L_long − L_short) / (L_long + L_short) | Positivo: predominan las liquidaciones de largos. |
| Cobertura (PnL de precio) | `price_pnl` | q · ((S_t − S_0) − (P_t − P_0)) | Es exactamente −q · variación del basis en USDT. |
| Comisiones de la cobertura | `fees` | q · f · (S_0 + P_0 + S_t + P_t) | Cuatro ejecuciones: abrir y cerrar las dos piernas. |
| Patrimonio del margen | `margin_equity` | garantía + q · (P_0 − mark) + funding − comisión de apertura | Lo que queda en la cuenta del short, valorado con el mark. |
| Umbral de mantenimiento | `margin_breach` | margin_equity ≤ q · mark · tasa de mantenimiento | Cruzarlo puede provocar la liquidación. |

## Ideas clave

- **El OI no cuenta compradores ni vendedores:** cada contrato tiene ambos lados. Se mide en BTC, porque en USDT mezcla posiciones y precio.
- **El funding anunciado no es el liquidado:** en OKX, el anunciado era +0,69 bps y el último liquidado −0,18 bps, de signo contrario.
- **El funding cambia de signo:** en los últimos 10 pagos de OKX hubo 5 positivos y 5 negativos.
- **La cobertura neutraliza la dirección, no el basis:** su PnL de precio es la variación del basis.
- **Capital total = spot + garantía:** la rentabilidad del carry se mide sobre los dos.
- **Las cuentas están separadas:** el beneficio del spot no protege la garantía del short. Con un salto del +15 %, el short se liquida aunque el conjunto vaya plano.
- **Pocos eventos, ninguna conclusión:** 4 a 12 eventos de liquidación por grupo, con signo inestable entre periodos.

## Validación (`normalize`)

Se detiene con `ValueError` en estos casos: faltan columnas, timestamps nulos o duplicados, timestamps que no son cierres horarios UTC, datos vacíos o infinitos, precios ≤ 0, y OI o liquidaciones negativos. Reindexa a una rejilla horaria completa sin rellenar huecos, para que `shift(3)` signifique tres horas.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Basis | spot 60.000 · perp 60.300 | **+50 bps** |
| Funding de un short | 0,1 BTC · mark 60.000 · tasa ±0,0001 | **±0,60 USDT** |
| Comisiones de la cobertura | 0,1 BTC · precios 60.000 · 10 bps | 4 × 6 = **24 USDT** |
| Margen | short de 1.000 USDT con 100 de garantía, +10 % | Garantía 0 ≤ 5,5 de mantenimiento: **umbral superado** |

## Código

```python
from quantlab.p07.derivatives import (make_synthetic, normalize, add_features, event_study,
                                      hedge_curve, carry_decomposition, margin_breach_table,
                                      apply_price_shock, okx_snapshot)

d = add_features(normalize(make_synthetic()), qty_btc=0.02)
results, threshold, train, test = event_study(d, horizon=3)    # umbral solo con el desarrollo
week = d.iloc[:168]
hedge_curve(week, q=0.02, margin=600, fee_bps=10)
carry_decomposition(week, 0.02, 600, (0, 10, 20))
margin_breach_table(apply_price_shock(week, week.index[100], .15), 0.02, (100, 300, 600))
rows, funding_history, _ = okx_snapshot()                      # captura pública, secuencial
```

Relacionado: [spread_y_costes.md](spread_y_costes.md) · [series_temporales.md](series_temporales.md) · [validacion_de_datos.md](validacion_de_datos.md)
