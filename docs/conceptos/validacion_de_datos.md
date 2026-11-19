# Validación de datos de mercado

**Familia:** calidad de datos · **Visto en:** P01

## Para qué sirve

Antes de calcular métricas comprobamos que el dato tiene sentido. Si una comprobación falla, el cuaderno **se detiene con un error** en lugar de seguir calculando con datos malos.

## Comprobaciones mínimas de una cotización

| Comprobación | Por qué | Si falla, probablemente… |
|---|---|---|
| `best_bid > 0` | Un precio ≤ 0 no existe en un activo como BTC. | Dato corrupto o campo vacío. |
| `last_price > 0` | Ídem. | Dato corrupto o campo vacío. |
| `best_ask >= best_bid` | Si Ask < Bid, el libro está **cruzado**: comprador y vendedor ya se habrían cruzado y la operación se habría ejecutado. | Datos desincronizados, mezcla de fuentes o error de lectura. |

## Ideas clave

- **Validar antes de calcular.** Así un error salta en la celda de datos y no en una conclusión equivocada.
- Pasar las comprobaciones **no garantiza** que el dato sea correcto o reciente; solo descarta errores evidentes.
- **Comprueba la función con un caso conocido.** En el ejemplo ficticio el mid debe ser 60.000 € y el spread 4 €.
- Pendiente para más adelante: comprobar la antigüedad del dato (timestamp), los huecos y los valores atípicos.

## Código

Comprobaciones de la cotización:

```python
assert market["best_bid"] > 0
assert market["best_ask"] >= market["best_bid"]
assert market["last_price"] > 0
print("Comprobaciones básicas superadas.")
```

Verificar la función con el ejemplo ficticio:

```python
if market["source"] == "synthetic_example":
    assert metrics["mid_price"] == 60_000.0
    assert metrics["spread"] == 4.0
    assert abs(metrics["spread_bps"] - 0.6667) < 1e-3
    assert metrics["last_price_deviation"] == -1.0
```

## En `src/` y `tests/`

Las comprobaciones viven en `validate_quote()` (`src/quantlab/p01/quotes.py`). Tanto `quote_metrics()` como `fetch_kraken_ticker()` la llaman, así que un dato inválido lanza `ValueError` automáticamente.

Las pruebas de `tests/test_quotes.py` verifican los casos conocidos y también que los datos inválidos se rechazan:

```python
@pytest.mark.parametrize("bid, ask, last", [
    (0.0, 1.0, 1.0),      # bid = 0
    (-5.0, 1.0, 1.0),     # bid negativo
    (101.0, 100.0, 100),  # libro cruzado
    (100.0, 101.0, 0.0),  # last = 0
])
def test_cotizaciones_invalidas(bid, ask, last):
    with pytest.raises(ValueError):
        quote_metrics(bid, ask, last)
```

Ejecutar: `.\.venv\Scripts\python.exe -m pytest` (añade `-m live` para la prueba contra Kraken).

Relacionado: [precios_de_cotizacion.md](precios_de_cotizacion.md) · [spread_y_costes.md](spread_y_costes.md)
