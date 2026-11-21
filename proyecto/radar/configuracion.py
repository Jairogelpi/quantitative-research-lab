"""Configuración del sistema: todo valor ajustable vive aquí, con su origen."""

from pathlib import Path

PAR = "BTC/EUR"
EXCHANGES = ("kraken", "okx", "bitvavo")

# Captura
INTERVALO_S = 1.0       # segundos entre rondas
TAM_LOTE = 180          # filas por fichero Parquet (60 rondas × 3 exchanges)
TIMEOUT_HTTP_S = 10     # espera máxima por respuesta
NIVELES_LIBRO = 100     # niveles por lado (21-11-2026: 50 niveles cubrían solo 8,7 bps de bids en Kraken)
BANDAS_BPS = (1, 5, 10)  # bandas alrededor del mid para el desequilibrio del libro
NIVELES_GUARDADOS = 50  # niveles por lado que se guardan en `libros` (200.000 € barrían 25 en Kraken)

# Comisiones taker por pata (fracción del importe) del nivel más bajo, con su fuente oficial.
# Verificadas el 21-11-2026 en las webs oficiales (renderizadas en un navegador).
# OKX distingue el tipo de cuenta: se usa la de solo spot (la de un usuario que no opera derivados);
# con una cuenta de spot y derivados sería 0,10 % (cambiar aquí si es tu caso).
COMISIONES_TAKER = {
    "kraken": (0.0080, "verificada: kraken.com/pro/fees, primer nivel (maker 0,40 %)"),
    "okx": (0.0020, "verificada: okx.com/en-eu/fees, usuario regular, cuenta solo spot (maker 0,10 %); "
                    "con spot y derivados, 0,10 %"),
    "bitvavo": (0.0025, "verificada: bitvavo.com/en/fees, pares cripto/EUR, volumen ≥ 0 € (maker 0,15 %)"),
}


def comisiones_taker() -> dict:
    """Solo las comisiones por exchange (sin el estado de verificación), para el dominio."""
    return {ex: comision for ex, (comision, _) in COMISIONES_TAKER.items()}


IMPORTE_COMPARACION = 1000.0  # EUR de la ida y vuelta que se compara en cada ronda

# Almacenamiento
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RAIZ_LAKE = RAIZ_PROYECTO / "data" / "lake"
CATALOGO = RAIZ_PROYECTO / "data" / "quantlab.duckdb"
