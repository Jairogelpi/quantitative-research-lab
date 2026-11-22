"""Adaptador del histórico oficial de Kraken (BTC/EUR): REST `OHLC` y `Trades`, y los ZIP de OHLCVT descargables.

Conceptos:
- REST OHLC (https://docs.kraken.com/api/docs/rest-api/get-ohlc-data): `GET /0/public/OHLC?pair=XBTEUR&interval=m`
  con m en minutos (1, 5, 15, 30, 60, 240, 1440, 10080, 21600). Cada barra es `[time, open, high, low, close, vwap,
  volume, count]` (hora Unix en s del INICIO de la barra; precios y volumen en texto). "Returns up to 720 of the
  most recent entries (older data cannot be retrieved, regardless of the value of `since`)": 720 barras de 1 min =
  12 h; de 60 min = 30 días; de 1440 min ≈ 2 años. "The last entry in the OHLC array is for the current,
  not-yet-committed timeframe": la última barra está abierta. Comprobado con una respuesta real (22-11-2026): la
  REST NO omite los intervalos sin trades; los devuelve con `count` = 0, `vwap` = "0.0", volumen 0 y los cuatro
  precios iguales al cierre anterior (son de relleno, no precios negociados).
- REST Trades (https://docs.kraken.com/api/docs/rest-api/get-recent-trades): `GET /0/public/Trades?pair=XBTEUR&since=
  t&count=1000`; cada trade `[price, volume, time, b/s, m/l, misc, trade_id]` y `last` = cursor para la página
  siguiente (nanosegundos, https://docs.kraken.com/exchange/guides/general/historical-data). Pagina hacia delante
  desde cualquier fecha: sirve para cubrir el hueco entre el último ZIP trimestral y la ventana de 720 barras.
- Límite de peticiones públicas (https://support.kraken.com/articles/206548367-What-are-the-API-rate-limits-): una
  por segundo o menos se mantiene dentro; Kraken los limita por IP y par en Trades y OHLC. `PAUSA_S` respeta eso.
- OHLCVT descargable (https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-
  close-volume-trades-data): un CSV por par e intervalo, `XBTEUR_<m>.csv` (m = 1, 5, 15, 60, 240, 720, 1440; el
  ZIP trimestral 2026Q3 no trae 30), SIN cabecera, filas `timestamp, open, high, low, close, volume, trades`
  (hora Unix en s del inicio; sin VWAP). "Only intervals with actual trades are included": un intervalo que falta
  dentro del periodo cubierto es una vela vacía. Se distribuye en `https://assets.kraken.com/marketing/
  institutions/`: historia completa `Kraken_OHLCVT_Full.zip.part00`…`part04` (4 × 2 097 152 000 B + 1 157 945 626
  B ≈ 9,5 GB; las partes concatenadas forman UN ZIP) y actualizaciones trimestrales `Kraken_OHLCVT_2026Q1.zip`,
  `…2026Q2.zip` (538 MB), `…2026Q3.zip` (576 MB). Comprobado leyendo el ZIP 2026Q3: `XBTEUR_1440.csv` va del
  01-07-2026 al 30-09-2026 (92 filas).
- Lectura parcial de un ZIP remoto: el índice de un ZIP (directorio central) está al final y dice en qué byte empieza
  cada fichero. Con peticiones HTTP `Range` (las sirve `assets.kraken.com`) `zipfile` lee solo el índice y los
  ficheros de XBTEUR (2-3 MB comprimidos por intervalo en un trimestre) sin bajar los gigas del ZIP completo.
- Time & Sales descargable (https://support.kraken.com/articles/360047543791-downloadable-historical-market-data-
  time-and-sales-): todos los trades, `Kraken_Trades_Full.zip.part00`…`part13` (~2 GB cada una) y trimestrales
  `Kraken_Trades_2026Q<n>.zip`; columnas `timestamp, price, volume, type, order_type, misc, trade_id`, con cabecera.
  No se usa aquí: para velas basta el OHLCVT, y los trades recientes se piden por REST.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from radar.configuracion import TIMEOUT_HTTP_S

from .http import pedir_json

URL_OHLC = "https://api.kraken.com/0/public/OHLC"
URL_TRADES = "https://api.kraken.com/0/public/Trades"
URL_ARCHIVOS = "https://assets.kraken.com/marketing/institutions/"
PARTES_COMPLETO = tuple(f"{URL_ARCHIVOS}Kraken_OHLCVT_Full.zip.part{i:02d}" for i in range(5))
PAR_REST = "XBTEUR"
PAR_ARCHIVO = "XBTEUR"          # nombre en los CSV (`XBTEUR_60.csv`); `XBTEURC_…` es otro mercado
INTERVALOS_REST_MIN = (1, 5, 15, 30, 60, 240, 1440, 10080, 21600)
INTERVALOS_ARCHIVO_MIN = (1, 5, 15, 60, 240, 720, 1440)
MAX_BARRAS_REST = 720
PAUSA_S = 1.0                   # una petición pública por segundo como máximo
BARRA = ["inicio_utc", "apertura", "maximo", "minimo", "cierre", "vwap", "volumen_btc", "n_trades"]
TRADE = ["hora_exchange_utc", "precio", "cantidad", "lado_agresor", "trade_id"]


def url_trimestre(trimestre: str) -> str:
    """URL del ZIP trimestral, p. ej. `url_trimestre("2026Q3")`."""
    return f"{URL_ARCHIVOS}Kraken_OHLCVT_{trimestre}.zip"


def _error(datos):
    if datos.get("error"):
        raise ValueError(f"Kraken devolvió un error: {datos['error']}")


def interpretar_ohlc(datos) -> tuple[pd.DataFrame, int]:
    """Respuesta JSON de `/0/public/OHLC` → (barras con columnas `BARRA`, cursor `last`). Sin rellenar nada."""
    _error(datos)
    resultado = datos["result"]
    filas = next(v for k, v in resultado.items() if k != "last")
    barras = pd.DataFrame(filas, columns=["t", "o", "h", "l", "c", "vwap", "v", "n"])
    salida = pd.DataFrame({"inicio_utc": pd.to_datetime(barras["t"].astype("int64"), unit="s", utc=True)})
    for destino, origen in zip(BARRA[1:], ["o", "h", "l", "c", "vwap", "v", "n"]):
        salida[destino] = barras[origen].astype(float)
    return salida, int(resultado["last"])


def interpretar_csv_ohlcvt(texto: str) -> pd.DataFrame:
    """CSV oficial OHLCVT (sin cabecera: timestamp, open, high, low, close, volume, trades) → barras `BARRA`.

    El CSV no trae VWAP: queda NaN."""
    crudo = pd.read_csv(io.StringIO(texto), header=None, names=["t", "o", "h", "l", "c", "v", "n"])
    salida = pd.DataFrame({"inicio_utc": pd.to_datetime(crudo["t"].astype("int64"), unit="s", utc=True)})
    for destino, origen in zip(["apertura", "maximo", "minimo", "cierre"], ["o", "h", "l", "c"]):
        salida[destino] = crudo[origen].astype(float)
    salida["vwap"] = np.nan
    salida["volumen_btc"] = crudo["v"].astype(float)
    salida["n_trades"] = crudo["n"].astype(float)
    return salida[BARRA]


def interpretar_trades(datos) -> tuple[pd.DataFrame, int]:
    """Respuesta de `/0/public/Trades` → (trades con columnas `TRADE`, cursor `last` en ns)."""
    _error(datos)
    resultado = datos["result"]
    filas = next(v for k, v in resultado.items() if k != "last")
    crudo = pd.DataFrame(filas, columns=["p", "q", "t", "lado", "tipo", "misc", "id"])
    trades = pd.DataFrame({"hora_exchange_utc": pd.to_datetime(crudo["t"].astype(float), unit="s", utc=True),
                           "precio": crudo["p"].astype(float), "cantidad": crudo["q"].astype(float),
                           "lado_agresor": crudo["lado"].map({"b": "buy", "s": "sell"}),
                           "trade_id": crudo["id"]})
    return trades[TRADE], int(resultado["last"])


def leer_ohlc(intervalo_min: int, since: int | None = None) -> tuple[pd.DataFrame, int]:
    """Últimas 720 barras (como mucho) de BTC/EUR; la última está abierta."""
    if intervalo_min not in INTERVALOS_REST_MIN:
        raise ValueError(f"intervalo {intervalo_min} min no admitido por la REST de Kraken: {INTERVALOS_REST_MIN}")
    params = {"pair": PAR_REST, "interval": intervalo_min}
    if since is not None:
        params["since"] = since
    return interpretar_ohlc(pedir_json(URL_OHLC, params))


def leer_trades(since_ns: int, pedir=pedir_json) -> tuple[pd.DataFrame, int]:
    """Hasta 1000 trades de BTC/EUR posteriores a `since_ns` (nanosegundos Unix)."""
    return interpretar_trades(pedir(URL_TRADES, {"pair": PAR_REST, "since": since_ns, "count": 1000}))


def paginar_trades(desde_utc: pd.Timestamp, hasta_utc: pd.Timestamp, pedir=pedir_json, dormir=time.sleep,
                   pausa_s: float = PAUSA_S):
    """Genera páginas de trades desde `desde_utc` hasta pasar `hasta_utc`, con `pausa_s` entre peticiones.

    La última página va entera (con trades posteriores a `hasta_utc`): es la prueba de que se llegó hasta ahí."""
    cursor = int(pd.Timestamp(desde_utc).value)
    while True:
        trades, siguiente = leer_trades(cursor, pedir)
        if trades.empty or siguiente <= cursor:
            return
        yield trades
        if trades["hora_exchange_utc"].iloc[-1] >= hasta_utc:
            return
        cursor = siguiente
        dormir(pausa_s)


class ArchivoPorPartes(io.RawIOBase):
    """Fichero de solo lectura y con `seek` formado por varias partes concatenadas, locales o URLs (HTTP Range).

    `zipfile.ZipFile` lo abre como un ZIP normal y solo pide los bytes que necesita."""

    def __init__(self, partes, sesion=None):
        self._sesion = sesion or requests.Session()
        self._partes = [str(p) for p in partes]
        self._tamanos = [self._tamano(p) for p in self._partes]
        self._inicios = np.cumsum([0, *self._tamanos[:-1]]).tolist()
        self._total = sum(self._tamanos)
        self._pos = 0

    @staticmethod
    def _remota(parte: str) -> bool:
        return parte.startswith(("http://", "https://"))

    def _tamano(self, parte: str) -> int:
        if not self._remota(parte):
            return Path(parte).stat().st_size
        respuesta = self._sesion.head(parte, timeout=TIMEOUT_HTTP_S, allow_redirects=True)
        respuesta.raise_for_status()
        return int(respuesta.headers["Content-Length"])

    def _leer_parte(self, i: int, desde: int, n: int) -> bytes:
        parte = self._partes[i]
        if not self._remota(parte):
            with open(parte, "rb") as f:
                f.seek(desde)
                return f.read(n)
        respuesta = self._sesion.get(parte, headers={"Range": f"bytes={desde}-{desde + n - 1}"},
                                     timeout=TIMEOUT_HTTP_S * 6)
        respuesta.raise_for_status()
        if respuesta.status_code != 206:
            raise IOError(f"{parte} no admite peticiones Range (HTTP {respuesta.status_code})")
        return respuesta.content

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, desplazamiento, desde=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._total}[desde]
        self._pos = max(0, base + desplazamiento)
        return self._pos

    def readinto(self, destino) -> int:
        n = min(len(destino), self._total - self._pos)
        if n <= 0:
            return 0
        trozos, pos, falta = [], self._pos, n
        while falta > 0:
            i = max(j for j, inicio in enumerate(self._inicios) if inicio <= pos)
            desde = pos - self._inicios[i]
            cuanto = min(falta, self._tamanos[i] - desde)
            trozos.append(self._leer_parte(i, desde, cuanto))
            pos, falta = pos + cuanto, falta - cuanto
        datos = b"".join(trozos)
        destino[:len(datos)] = datos
        self._pos += len(datos)
        return len(datos)


def abrir_zip(partes, sesion=None) -> zipfile.ZipFile:
    """ZIP de Kraken desde una ruta/URL o una lista de partes (`PARTES_COMPLETO`)."""
    if isinstance(partes, (str, Path)):
        partes = [partes]
    return zipfile.ZipFile(io.BufferedReader(ArchivoPorPartes(partes, sesion), buffer_size=1 << 20))


def nombre_csv(intervalo_min: int, par: str = PAR_ARCHIVO) -> str:
    return f"{par}_{intervalo_min}.csv"


def leer_csv_de_zip(archivo: zipfile.ZipFile, intervalo_min: int, par: str = PAR_ARCHIVO) -> pd.DataFrame | None:
    """Barras de `XBTEUR_<m>.csv` dentro del ZIP (en la raíz o en una carpeta); None si el ZIP no lo trae."""
    buscado = nombre_csv(intervalo_min, par)
    for nombre in archivo.namelist():
        if nombre.rsplit("/", 1)[-1] == buscado:
            return interpretar_csv_ohlcvt(archivo.read(nombre).decode("utf-8"))
    return None
