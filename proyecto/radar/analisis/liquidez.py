"""Medidas estándar de liquidez con los trades y el libro del websocket: spreads efectivo y realizado, impacto en
el precio y lambda de Kyle (S3).

Conceptos:
- D = +1 si el agresor compró y −1 si vendió (lo da el exchange, no hace falta estimarlo con Lee-Ready). M = mid
  del último libro ESTRICTAMENTE anterior al trade (hora de recepción, la nuestra), si llegó a menos de
  `TOLERANCIA_S`. P = precio del trade.
- Spread cotizado: (ask − bid) / M de ese mismo libro. Lo que se ve en pantalla.
- Spread efectivo: 2 · D · (P − M) / M. Lo que pagó de verdad el que tomó liquidez, ida y vuelta. Puede ser mayor
  que el cotizado (la orden se comió varios niveles, o el libro cambió entre la foto y el trade) o menor (mejora
  de precio dentro del spread).
- Spread realizado a h segundos: 2 · D · (P − M(t + h)) / M. Lo que ganó el market maker que dio la contrapartida
  si deshizo la posición al mid h segundos después.
- Impacto en el precio: 2 · D · (M(t + h) − M) / M. Lo que se movió el mid a favor del agresor: la información que
  llevaba el trade (selección adversa para el maker). Con el mismo denominador M, efectivo = realizado + impacto
  exactamente en cada trade.
- Lambda de Kyle: en intervalos fijos de Δ segundos, ΔM (bps) = a + λ · volumen firmado (BTC, compras positivas)
  + error; λ = cuántos bps mueve el precio cada BTC neto comprado. Errores Newey-West. También en bps por cada
  100.000 € (λ · 100.000 / precio medio).
- Mid exacto: si hay `eventos_libro`, M es el mid del último CAMBIO del libro reconstruido antes del trade
  (`mids_exactos`, la misma reconstrucción que usa Hayashi-Yoshida). Con `libros_flujo`, que guarda un libro por
  segundo, M podía tener hasta un segundo de antigüedad: si el mid se movió en ese segundo (justo lo que suele
  preceder a un trade), el efectivo y el impacto salían inflados y el realizado desplazado hacia abajo.
- Agregación: medias simples por trade y ponderadas por cantidad (BTC). Errores agrupados por segundo (los trades
  de un mismo segundo suelen ser la misma orden partida): error de la media con conglomerados por segundo.
- Fuentes verificadas: Holden y Jacobsen (2014), "Liquidity Measurement Problems in Fast, Competitive Markets",
  Journal of Finance 69, 1747-1785, y su código SAS en el Internet Appendix (doi 10.1111/jofi.12127):
  efectivo = 2 · |P − M|, realizado = 2 · D · (P − M5), impacto = efectivo − realizado, en porcentaje sobre el
  mid; ponderaciones por volumen. Aquí D es conocido, así que el efectivo va con signo, como en la Rule 605
  (Goyenko, Holden y Trzcinka, 2009, JFE 92, 153-181, que comparan ambos), y todo se divide por M para que la
  descomposición sea exacta (Holden y Jacobsen dividen realizado e impacto por M5: diferencia de segundo orden).
  Lambda: Kyle (1985), Econometrica 53, 1315-1335; Goyenko, Holden y Trzcinka (2009) usan como referencia la
  regresión del retorno sobre el volumen firmado en intervalos de 5 minutos (Hasbrouck, 2009, con la raíz
  cuadrada del volumen); aquí se usa la forma lineal de Kyle en intervalos de segundos.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .hayashi_yoshida import mids_flujo
from .imbalance import _retardos
from .markouts import TOLERANCIA_S, _cargar, _Mids, _segundos

FUENTE_LIQUIDEZ = "estudios_liquidez"
HORIZONTES_S = (5, 30, 60)
INTERVALOS_LAMBDA_S = (5, 60)
MIN_SEGUNDOS_TRADES = 100     # segundos distintos con trades para resumir los spreads
MIN_INTERVALOS = 100          # intervalos para estimar la lambda de Kyle
IMPORTE_REFERENCIA_EUR = 100_000
UMBRAL_IMPACTO = 0.5          # si el impacto es la mitad o más del spread efectivo, domina la selección adversa
# Con cambios del libro, el mid solo se emite cuando cambia: un mid quieto sigue valiendo. Solo un tramo sin ningún
# cambio de más de esto se toma como corte de la captura (mismo criterio que `presion.TOLERANCIA_LIBRO_S`).
TOLERANCIA_EXACTOS_S = 300.0


class _UltimoMid:
    """Mid vigente en cada instante: el del último cambio en o antes, si no tiene más de `tolerancia` segundos y
    el instante no cae después del último dato observado (ahí no se sabe si el mid cambió: NaN)."""

    def __init__(self, t: np.ndarray, mid: np.ndarray, tolerancia: float):
        self.t, self.mid, self.tolerancia = t, mid, tolerancia

    def en(self, instantes: np.ndarray) -> np.ndarray:
        i = np.searchsorted(self.t, instantes, side="right") - 1
        ok = (i >= 0) & (instantes - self.t[np.maximum(i, 0)] <= self.tolerancia) & (instantes <= self.t[-1])
        return np.where(ok, self.mid[np.maximum(i, 0)], np.nan)


class _Libros:
    """Mids y spreads cotizados de un exchange, por hora de recepción: de los cambios del libro (`mids_exactos`,
    columnas recibido_ns, mid, cotizado_bps) o de las fotos de `libros_flujo` (listas de niveles)."""

    def __init__(self, g: pd.DataFrame):
        if "recibido_ns" in g.columns:
            self.t = g["recibido_ns"].to_numpy(dtype=np.int64) / 1e9
            self.mid = g["mid"].to_numpy(dtype=float)
            self.cotizado = g["cotizado_bps"].to_numpy(dtype=float)
            self.tolerancia = TOLERANCIA_EXACTOS_S
            self.posterior = _UltimoMid(self.t, self.mid, TOLERANCIA_EXACTOS_S)
        else:
            self.t = _segundos(g["recibido_utc"])
            bid = np.array([b[0] for b in g["bid_precios"]], dtype=float)
            ask = np.array([a[0] for a in g["ask_precios"]], dtype=float)
            self.mid = (bid + ask) / 2
            self.cotizado = (ask - bid) / self.mid * 1e4
            self.tolerancia = TOLERANCIA_S
            self.posterior = _Mids(self.t, self.mid)  # fotos: la primera en o después de t + h

    def anterior(self, instantes: np.ndarray) -> np.ndarray:
        """Índice del último libro (o cambio del mid) estrictamente anterior a cada instante (−1 si no hay o es más
        viejo que la tolerancia: 2 s con fotos, 300 s con cambios del libro)."""
        i = np.searchsorted(self.t, instantes, side="left") - 1
        ok = (i >= 0) & (instantes - self.t[np.maximum(i, 0)] <= self.tolerancia)
        return np.where(ok, i, -1)


def _libros(libros: pd.DataFrame) -> dict:
    orden = "recibido_ns" if "recibido_ns" in libros.columns else "recibido_utc"
    return {ex: _Libros(g.sort_values(orden)) for ex, g in libros.groupby("exchange")}


def mids_exactos(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None) -> pd.DataFrame:
    """Cada cambio del mid reconstruido desde `eventos_libro` (exchange, recibido_ns, mid, cotizado_bps)."""
    return mids_flujo(consultar, desde_utc, hasta_utc)


def medidas_trades(libros: pd.DataFrame, trades: pd.DataFrame, horizontes=HORIZONTES_S) -> pd.DataFrame:
    """Una fila por trade con libro anterior: exchange, t, recibido_utc, precio, cantidad, lado, mid_antes,
    cotizado_bps, efectivo_bps y, por horizonte h, realizado_<h>_bps e impacto_<h>_bps (NaN si no hay mid en
    t + h)."""
    por_exchange, partes = _libros(libros), []
    for exchange, g in trades.groupby("exchange", sort=True):
        if exchange not in por_exchange:
            continue
        lb = por_exchange[exchange]
        g = g.sort_values("recibido_utc")
        t = _segundos(g["recibido_utc"])
        i = lb.anterior(t)
        ok = i >= 0
        g, t, i = g[ok], t[ok], i[ok]
        precio = g["precio"].to_numpy(dtype=float)
        lado = np.where(g["lado_agresor"].to_numpy() == "buy", 1.0, -1.0)
        m = lb.mid[i]
        fila = pd.DataFrame({"exchange": exchange, "t": t, "recibido_utc": g["recibido_utc"].to_numpy(),
                             "precio": precio, "cantidad": g["cantidad"].to_numpy(dtype=float), "lado": lado,
                             "mid_antes": m, "cotizado_bps": lb.cotizado[i],
                             "efectivo_bps": 2 * lado * (precio - m) / m * 1e4})
        for h in horizontes:
            futuro = lb.posterior.en(t + h)
            fila[f"realizado_{h}_bps"] = 2 * lado * (precio - futuro) / m * 1e4
            fila[f"impacto_{h}_bps"] = 2 * lado * (futuro - m) / m * 1e4
        partes.append(fila)
    columnas = ["exchange", "t", "recibido_utc", "precio", "cantidad", "lado", "mid_antes", "cotizado_bps",
                "efectivo_bps"]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=columnas)


def _media_agrupada(x: np.ndarray, grupos: np.ndarray) -> tuple[float, float]:
    """(media simple, error con conglomerados por grupo): sqrt(Σ_g (Σ_{i∈g} (x_i − x̄))²) / N."""
    if len(x) == 0:
        return math.nan, math.nan
    media = float(np.mean(x))
    sumas = pd.Series(x - media).groupby(grupos).sum().to_numpy()
    error = float(math.sqrt(np.sum(sumas ** 2)) / len(x)) if len(sumas) > 1 else math.nan
    return media, error


@dataclass(frozen=True)
class SpreadTrades:
    exchange: str
    horizonte_s: int
    n_trades: int
    n_segundos: int
    cotizado_bps: float
    efectivo_bps: float
    efectivo_vw_bps: float
    error_efectivo_bps: float
    realizado_bps: float
    realizado_vw_bps: float
    error_realizado_bps: float
    impacto_bps: float
    impacto_vw_bps: float
    error_impacto_bps: float
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def efectivo_sobre_cotizado(self) -> float:
        return self.efectivo_bps / self.cotizado_bps if self.cotizado_bps else math.nan

    @property
    def parte_impacto(self) -> float:
        return self.impacto_bps / self.efectivo_bps if self.efectivo_bps else math.nan

    @property
    def estado(self) -> str:
        return "datos insuficientes" if self.n_segundos < self.minimo else "medido"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, spreads con trades, horizonte {self.horizonte_s} s"
        if self.estado == "datos insuficientes":
            return (f"{cabecera}: datos insuficientes ({self.n_segundos} segundos con trades; hacen falta "
                    f"{self.minimo}).")
        relacion = ("por encima del cotizado (las órdenes se comen niveles o el libro se mueve antes del trade)"
                    if self.efectivo_sobre_cotizado > 1 else "por debajo del cotizado (mejora de precio)")
        if self.realizado_bps < 0:
            reparto = "el impacto supera al spread: el maker que da la contrapartida pierde"
        elif self.parte_impacto >= UMBRAL_IMPACTO:
            reparto = "domina la selección adversa: el maker pierde la mayor parte de lo que cobra"
        else:
            reparto = "el maker se queda con la mayor parte"
        return (f"{cabecera}: spread efectivo {self.efectivo_bps:.3f} bps (ponderado por volumen "
                f"{self.efectivo_vw_bps:.3f}, error {self.error_efectivo_bps:.3f}), {self.efectivo_sobre_cotizado:.2f} "
                f"veces el cotizado de {self.cotizado_bps:.3f} bps: {relacion}. Realizado {self.realizado_bps:+.3f} bps "
                f"(error {self.error_realizado_bps:.3f}) e impacto {self.impacto_bps:+.3f} bps (error "
                f"{self.error_impacto_bps:.3f}): el impacto es el {self.parte_impacto:.0%} del efectivo, {reparto}. "
                f"{self.n_trades} trades en {self.n_segundos} segundos.")

    def a_fila(self) -> dict:
        return {"estudio": "spread_trades", **asdict(self), "efectivo_sobre_cotizado": self.efectivo_sobre_cotizado,
                "parte_impacto": self.parte_impacto, "estado": self.estado, "conclusion": self.conclusion()}


def spreads_trades(libros: pd.DataFrame, trades: pd.DataFrame, horizontes=HORIZONTES_S,
                   minimo: int = MIN_SEGUNDOS_TRADES) -> list[SpreadTrades]:
    """Resumen por exchange y horizonte. Solo entran los trades con mid en t + h, para que efectivo, realizado e
    impacto se midan sobre los mismos trades y la suma cuadre."""
    medidas, resultados = medidas_trades(libros, trades, horizontes), []
    for exchange, g in medidas.groupby("exchange", sort=True):
        for h in horizontes:
            s = g.dropna(subset=[f"realizado_{h}_bps"])
            segundos = np.floor(s["t"].to_numpy())
            peso = s["cantidad"].to_numpy()
            valores = {}
            for nombre, columna in (("efectivo", "efectivo_bps"), ("realizado", f"realizado_{h}_bps"),
                                    ("impacto", f"impacto_{h}_bps")):
                x = s[columna].to_numpy(dtype=float)
                media, error = _media_agrupada(x, segundos)
                vw = float(np.sum(x * peso) / np.sum(peso)) if len(x) and np.sum(peso) > 0 else math.nan
                valores[nombre] = (media, vw, error)
            hasta = pd.Timestamp(s["recibido_utc"].max()) if len(s) else pd.NaT
            resultados.append(SpreadTrades(
                exchange, int(h), len(s), int(len(np.unique(segundos))),
                float(s["cotizado_bps"].mean()) if len(s) else math.nan,
                *valores["efectivo"], *valores["realizado"], *valores["impacto"], hasta, minimo))
    return resultados


@dataclass(frozen=True)
class LambdaKyle:
    exchange: str
    intervalo_s: int
    n: int
    lambda_bps_btc: float
    error_bps_btc: float
    r2: float
    precio_medio: float
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def t(self) -> float:
        return self.lambda_bps_btc / self.error_bps_btc if self.error_bps_btc else math.nan

    @property
    def lambda_bps_100k(self) -> float:
        return self.lambda_bps_btc * IMPORTE_REFERENCIA_EUR / self.precio_medio if self.precio_medio else math.nan

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        if not abs(self.t) >= 2:
            return "sin evidencia"
        return "impacto significativo" if self.lambda_bps_btc > 0 else "signo inesperado"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, lambda de Kyle en intervalos de {self.intervalo_s} s"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} intervalos; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. Lambda = {self.lambda_bps_btc:+.3f} bps por BTC neto comprado (error "
                f"{self.error_bps_btc:.3f}, t {self.t:.2f}, R² {self.r2:.3f}), {self.lambda_bps_100k:+.3f} bps por cada "
                f"100.000 € a un precio medio de {self.precio_medio:,.0f} €, en {self.n} intervalos.")

    def a_fila(self) -> dict:
        return {"estudio": "lambda_kyle", **asdict(self), "t": self.t, "lambda_bps_100k": self.lambda_bps_100k,
                "estado": self.estado, "conclusion": self.conclusion()}


def intervalos_flujo(libros: pd.DataFrame, trades: pd.DataFrame, intervalo_s: float) -> pd.DataFrame:
    """Por exchange e intervalo [k · Δ, (k + 1) · Δ): volumen firmado (BTC) y ΔM en bps entre el último libro
    anterior al inicio y el último anterior al final. Los intervalos sin trades cuentan con volumen 0; los que no
    tienen libro cerca de los dos extremos, no."""
    por_exchange, partes = _libros(libros), []
    for exchange, lb in por_exchange.items():
        if len(lb.t) < 2:
            continue
        k = np.arange(math.ceil(lb.t[0] / intervalo_s), math.floor(lb.t[-1] / intervalo_s))
        inicio, fin = k * intervalo_s, (k + 1) * intervalo_s
        i0, i1 = lb.anterior(inicio), lb.anterior(fin)
        tr = trades[trades.exchange == exchange]
        firmado = np.where(tr["lado_agresor"].to_numpy() == "buy", 1.0, -1.0) * tr["cantidad"].to_numpy(dtype=float)
        celda = np.floor(_segundos(tr["recibido_utc"]) / intervalo_s) if len(tr) else np.array([])
        volumen = pd.Series(firmado).groupby(celda).sum() if len(tr) else pd.Series(dtype=float)
        ok = (i0 >= 0) & (i1 >= 0)
        partes.append(pd.DataFrame({
            "exchange": exchange, "inicio_s": inicio[ok],
            "volumen_btc": volumen.reindex(k[ok].astype(float), fill_value=0.0).to_numpy(),
            "dmid_bps": (lb.mid[i1[ok]] / lb.mid[i0[ok]] - 1) * 1e4}))
    return (pd.concat(partes, ignore_index=True) if partes else
            pd.DataFrame(columns=["exchange", "inicio_s", "volumen_btc", "dmid_bps"]))


def lambda_kyle(libros: pd.DataFrame, trades: pd.DataFrame, intervalos_s=INTERVALOS_LAMBDA_S,
                minimo: int = MIN_INTERVALOS) -> list[LambdaKyle]:
    resultados = []
    for delta in intervalos_s:
        datos = intervalos_flujo(libros, trades, delta)
        for exchange in sorted(set(libros["exchange"])):
            g = datos[datos.exchange == exchange]
            tr = trades[trades.exchange == exchange]
            precio = float(tr["precio"].mean()) if len(tr) else math.nan
            hasta = pd.Timestamp(tr["recibido_utc"].max()) if len(tr) else pd.NaT
            if len(g) < minimo or g["volumen_btc"].std() == 0 or len(g) < 3:
                resultados.append(LambdaKyle(exchange, int(delta), len(g), math.nan, math.nan, math.nan, precio,
                                             hasta, minimo))
                continue
            modelo = sm.OLS(g["dmid_bps"].to_numpy(dtype=float),
                            sm.add_constant(g["volumen_btc"].to_numpy(dtype=float))).fit(
                cov_type="HAC", cov_kwds={"maxlags": _retardos(len(g), 1)})
            resultados.append(LambdaKyle(exchange, int(delta), len(g), float(modelo.params[1]),
                                         float(modelo.bse[1]), float(modelo.rsquared), precio, hasta, minimo))
    return resultados


def estudiar_liquidez(consultar: Callable[[str], pd.DataFrame], desde_utc=None, exactos: bool = True):
    """Spreads y lambda de Kyle desde `desde_utc`. Con `exactos`, el mid sale de los cambios del libro
    (`eventos_libro`); si no, o si no hay `eventos_libro`, de las fotos de cada segundo (`libros_flujo`), con
    hasta 1 s de antigüedad."""
    filtro = "" if desde_utc is None else f" WHERE recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}'"
    trades = consultar("SELECT exchange, recibido_utc, precio, cantidad, lado_agresor FROM trades"
                       f"{filtro} ORDER BY exchange, recibido_utc")
    vistas = set(consultar("SELECT table_name FROM information_schema.tables")["table_name"])
    if exactos and "eventos_libro" in vistas:
        # Unos segundos antes del primer trade, para tener el libro ya reconstruido cuando llega.
        inicio = None if desde_utc is None else pd.Timestamp(desde_utc) - pd.Timedelta(seconds=60)
        libros = mids_exactos(consultar, inicio)
    else:
        libros, _ = _cargar(consultar, "libros_flujo")
    return spreads_trades(libros, trades), lambda_kyle(libros, trades)


def guardar_estudio_liquidez(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in resultados], FUENTE_LIQUIDEZ)
