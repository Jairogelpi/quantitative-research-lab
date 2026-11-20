# Multiactivo y capitalización: divisa, calendarios, CAGR, drawdown y retorno total

**Familia:** comparación de inversiones · **Visto en:** P14 · **Código:** `src/quantlab/p14/multi_asset.py`

## Conceptos

| Concepto | Campo | Fórmula | Qué nos dice |
|---|---|---|---|
| Valor futuro / actual | `future_value`, `present_value` | FV = C₀(1 + r)^n; PV = FV / (1 + r)^n | Cuánto vale el dinero en otro momento. |
| Retorno compuesto | `compound_return` | ∏(1 + r_t) − 1 | Resultado real de una secuencia de retornos. |
| Tipo equivalente | `equivalent_rate` | (1 + r_anual)^{1/m} − 1 | Tipo por periodo con el mismo efecto anual. |
| CAGR | `cagr_pct` | (V_final / V_inicial)^{1/años} − 1 | Crecimiento anual compuesto. |
| Volatilidad anualizada | `volatility_pct` | s(r_semanal) · √52 | Dispersión de los retornos. |
| Drawdown | `max_drawdown_pct` | E_t / máx E_s − 1 | Peor caída desde un máximo. |
| Drag | `drag_pp` | 52 · (media aritmética − media geométrica semanal) | Lo que la volatilidad resta a la composición. |
| Conversión a EUR | `prepare_weekly` | Precio en USD / EURUSD (USD por EUR) | Precio para un inversor en euros. |
| Retorno en EUR | `eur_return` | (1 + r_USD) / (1 + r_EURUSD) − 1 | Efecto combinado del activo y la divisa. |
| Retorno total | `total_return` | (P_final + dividendo) / P_inicial − 1 | Precio más rentas cobradas. |

## Ideas clave

- **Componer, no sumar:** +50 % y −50 % dan −25 %, no 0.
- **Volatilidad alta, drag alto:** en BTC, el retorno aritmético supera al geométrico en 14–16 puntos al año.
- **Calendario común:** solo días en que todas las series tienen dato; un hueco interior se rechaza, no se rellena.
- **Cierres no simultáneos:** BTC cotiza 24/7; el cierre "del mismo día" de otros mercados no es el mismo instante.
- **USD por EUR:** con EURUSD = 1,20, 120 USD = 100 EUR. Un euro que se aprecia reduce el retorno en EUR de un activo en USD.
- **Cierres ajustados = retorno total:** no sumar los dividendos otra vez.
- **Rankings inestables:** con datos reales, BTC pasó de ser el peor de la primera mitad de 2021–2025 al mejor de la segunda.

## Validación (`prepare_weekly`)

Se detiene con `ValueError` en estos casos: fechas duplicadas, precios o FX ≤ 0 o infinitos, sin sesiones comunes, menos de 53 semanas o una semana interior sin datos. Descarta la primera y la última semana.

## Ejemplo

| Cálculo | Datos | Resultado |
|---|---|---|
| Capital | 1.000 € con +20 %, −10 %, +15 %, −5 % | **1.179,90 €** |
| Tipo mensual equivalente | 12 % anual | **0,9489 %** |
| Retorno en EUR | +10 % en USD, EURUSD +5 % | **+4,7619 %** |
| Retorno total | 100 → 98 con 4 € de dividendo | **+2 %** (precio: −2 %) |

## Código

```python
from quantlab.p14.multi_asset import download_prices, prepare_weekly, performance, fx_decomposition, split_halves

usd, eur, sessions = prepare_weekly(download_prices("2021-01-01", "2026-01-01"))   # requiere yfinance
performance(eur)                                     # retorno, CAGR, volatilidad, MDD, drag
eur.pct_change(fill_method=None).iloc[1:].corr()     # correlaciones semanales en EUR
```

Relacionado: [rentabilidad_y_riesgo.md](rentabilidad_y_riesgo.md) · [valoracion_y_macro.md](valoracion_y_macro.md) · [regimenes_y_diversificacion.md](regimenes_y_diversificacion.md)
