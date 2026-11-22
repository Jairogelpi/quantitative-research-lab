"""Parámetros de la captura por websocket, con su origen (candidatos a mudarse a `radar.configuracion`)."""

# Instrumento BTC/EUR con el nombre que usa cada API de websocket.
SIMBOLO_KRAKEN = "BTC/EUR"      # Kraken WS v2 usa BTC (no XBT): docs.kraken.com/api/docs/websocket-v2/book
INSTRUMENTO_OKX = "BTC-EUR"
MERCADO_BITVAVO = "BTC-EUR"

# Profundidad pedida al exchange (niveles por lado).
PROFUNDIDAD_KRAKEN = 100        # valores válidos: 10, 25, 100, 500, 1000; ≥ NIVELES_GUARDADOS (50)
PROFUNDIDAD_BITVAVO = 1000      # máximo de getBook (≥ 1 y ≤ 1000)
# OKX `books`: 400 niveles en el snapshot inicial y cambios cada 100 ms (no se elige).

# Precisión de BTC/EUR en Kraken para el checksum: `pair_decimals` = 1 y `lot_decimals` = 8
# (api.kraken.com/0/public/AssetPairs?pair=XBTEUR, consultado el 22-11-2026).
DECIMALES_PRECIO_KRAKEN, DECIMALES_CANTIDAD_KRAKEN = 1, 8

INTERVALO_LIBROS_S = 1.0        # cada cuánto se guarda una foto del libro reconstruido (`libros_flujo`)
TAM_LOTE_FLUJO = 5000           # filas por fichero Parquet y fuente
INTERVALO_VOLCADO_S = 60.0      # además, se vuelca todo lo acumulado al menos cada minuto
ESPERA_MENSAJE_S = 20.0         # sin mensajes en este tiempo se manda un ping; el doble sin nada, se reconecta
                                # (OKX corta a los 30 s sin tráfico y pide un 'ping' antes: N < 30)
ESPERA_RECONEXION_S = 1.0       # primera espera tras un fallo; se duplica en cada fallo seguido
ESPERA_MAX_RECONEXION_S = 60.0
MAX_BUFFER_BITVAVO = 10_000     # cambios guardados mientras llega el snapshot; si se desborda, el hueco se detecta
