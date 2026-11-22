"""Markouts y llenado de órdenes limit, con los trades y el libro capturados por websocket (T7, Fases 3 y 8).

Conceptos:
- Markout de un trade: cuánto se movió el mid h segundos después, visto desde el que tomó liquidez (taker):
  lado · (mid(t + h) / precio − 1) · 10.000, con lado = +1 si compró y −1 si vendió. Positivo = el taker acertó;
  el market maker que le dio la contrapartida perdió eso mismo: es la SELECCIÓN ADVERSA, medida.
- Orden limit hipotética: cada `MUESTREO_S` segundos se "coloca" una compra en el mejor bid (y una venta en el
  mejor ask) del libro reconstruido y se mira si un trade la habría llenado en los `espera` segundos siguientes.
  · Llenado seguro: un vendedor agresor operó a un precio PEOR que nuestro bid (por debajo): pasó por nuestro
    nivel, así que nuestra orden se ejecutó sí o sí.
  · Llenado posible: operó justo a nuestro precio. Depende de la cola: las órdenes que ya estaban antes en ese
    nivel se ejecutan primero, y no sabemos cuántas había delante.
- Markout de una orden llenada: lado · (mid(t_llenado + h) / precio − 1) · 10.000. Negativo = nos llenaron justo
  antes de que el precio se moviera en contra (lo que predice la selección adversa).
- Por signo del imbalance al colocar: el razonamiento de las preguntas 65 y 66 de la sesión dice que una compra
  limit se llena más cuando el imbalance es negativo y menos cuando es positivo. Aquí se mide.
- La vista es la NUESTRA: se usa la hora de recepción, con nuestra latencia incluida.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from radar.mercado import Libro, desequilibrio

FUENTE_MARKOUTS = "estudios_markouts"
HORIZONTES_S = (1, 5, 10, 30, 60)
ESPERAS_S = (5, 30, 60)
MUESTREO_S = 10
HORIZONTE_LIMIT_S = 30
BANDA_BPS = 5
TOLERANCIA_S = 2.0
MIN_TRADES = 100
MIN_ORDENES = 50


def _segundos(serie: pd.Series) -> np.ndarray:
    return serie.map(pd.Timestamp.timestamp).to_numpy(dtype=float)


class _Mids:
    """Mid del primer libro en o después de un instante, si llega a menos de `TOLERANCIA_S`."""

    def __init__(self, t: np.ndarray, mid: np.ndarray):
        self.t, self.mid = t, mid

    def en(self, instantes: np.ndarray) -> np.ndarray:
        i = np.searchsorted(self.t, instantes, side="left")
        dentro = i < len(self.t)
        i = np.minimum(i, len(self.t) - 1)
        ok = dentro & (self.t[i] - instantes <= TOLERANCIA_S)
        return np.where(ok, self.mid[i], np.nan)


def _cargar(consultar: Callable[[str], pd.DataFrame], fuente_libros: str):
    libros = consultar(f"SELECT * FROM {fuente_libros} ORDER BY exchange, recibido_utc")
    trades = consultar("SELECT exchange, recibido_utc, precio, cantidad, lado_agresor FROM trades "
                       "ORDER BY exchange, recibido_utc")
    return libros, trades


def _mids(libros: pd.DataFrame) -> dict:
    salida = {}
    for exchange, g in libros.groupby("exchange"):
        mid = np.array([(b[0] + a[0]) / 2 for b, a in zip(g["bid_precios"], g["ask_precios"])], dtype=float)
        salida[exchange] = _Mids(_segundos(g["recibido_utc"]), mid)
    return salida


# Markouts de los trades.

@dataclass(frozen=True)
class Markout:
    exchange: str
    horizonte_s: int
    n: int
    media_bps: float
    error_bps: float
    minimo: int

    @property
    def t(self) -> float:
        return self.media_bps / self.error_bps if self.error_bps else math.nan

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        if abs(self.t) < 2:
            return "sin evidencia"
        return "los takers aciertan (selección adversa para el maker)" if self.media_bps > 0 else "los takers pierden"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, markout a {self.horizonte_s} s"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} trades; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. Media {self.media_bps:+.3f} bps desde el taker (error {self.error_bps:.3f}, "
                f"t {self.t:.2f}) en {self.n} trades.")

    def a_fila(self) -> dict:
        return {"estudio": "markout", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def markouts_trades(libros: pd.DataFrame, trades: pd.DataFrame, horizontes=HORIZONTES_S,
                    minimo: int = MIN_TRADES) -> list[Markout]:
    """Markout medio desde el taker por exchange y horizonte. Error estándar agrupando por segundo (los trades
    de un mismo segundo suelen ser la misma orden partida, no observaciones independientes)."""
    mids, resultados = _mids(libros), []
    for exchange, g in trades.groupby("exchange", sort=True):
        if exchange not in mids:
            continue
        t, precio = _segundos(g["recibido_utc"]), g["precio"].to_numpy(dtype=float)
        lado = np.where(g["lado_agresor"].to_numpy() == "buy", 1.0, -1.0)
        for h in horizontes:
            m = lado * (mids[exchange].en(t + h) / precio - 1) * 1e4
            por_segundo = pd.Series(m).groupby(np.floor(t)).mean().dropna()
            n = len(por_segundo)
            error = float(por_segundo.std(ddof=1) / math.sqrt(n)) if n > 1 else math.nan
            resultados.append(Markout(exchange, int(h), n, float(por_segundo.mean()) if n else math.nan, error, minimo))
    return resultados


# Llenado de órdenes limit hipotéticas.

@dataclass(frozen=True)
class LlenadoLimit:
    exchange: str
    espera_s: int
    imbalance: str            # "todos", "a favor" o "en contra" (respecto del lado de la orden)
    colocadas: int
    llenadas_seguro: int
    llenadas_posible: int
    markout_llenadas_bps: float
    minimo: int

    @property
    def tasa_seguro(self) -> float:
        return self.llenadas_seguro / self.colocadas if self.colocadas else math.nan

    @property
    def tasa_posible(self) -> float:
        return (self.llenadas_seguro + self.llenadas_posible) / self.colocadas if self.colocadas else math.nan

    @property
    def estado(self) -> str:
        return "datos insuficientes" if self.colocadas < self.minimo else "medido"

    def conclusion(self) -> str:
        filtro = "" if self.imbalance == "todos" else f", imbalance {self.imbalance}"
        cabecera = f"{self.exchange}, limit en el mejor precio, espera {self.espera_s} s{filtro}"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.colocadas} órdenes; hacen falta {self.minimo})."
        markout = ("" if math.isnan(self.markout_llenadas_bps) else
                   f"; las llenadas con seguridad tienen un markout a {HORIZONTE_LIMIT_S} s de "
                   f"{self.markout_llenadas_bps:+.3f} bps")
        return (f"{cabecera}: se llenan con seguridad el {self.tasa_seguro:.1%} y, contando las de cola, hasta el "
                f"{self.tasa_posible:.1%} de {self.colocadas} órdenes{markout}.")

    def a_fila(self) -> dict:
        return {"estudio": "llenado_limit", **asdict(self), "tasa_seguro": self.tasa_seguro,
                "tasa_posible": self.tasa_posible, "estado": self.estado, "conclusion": self.conclusion()}


def colocaciones(libros: pd.DataFrame, muestreo_s: float = MUESTREO_S, banda_bps: float = BANDA_BPS) -> pd.DataFrame:
    """Una compra en el mejor bid y una venta en el mejor ask cada `muestreo_s`, con el imbalance de ese libro
    (`desequilibrio`, banda `banda_bps`) y si va a favor (+1), en contra (−1) o no se sabe (0)."""
    filas = []
    for exchange, g in libros.groupby("exchange", sort=True):
        siguiente = -math.inf
        for _, fila in g.iterrows():
            t = fila["recibido_utc"].timestamp()
            if t < siguiente:
                continue
            siguiente = t + muestreo_s
            libro = Libro.desde_fila(fila)
            imbalance = desequilibrio(libro, banda_bps).imbalance
            signo = 0.0 if imbalance is None or imbalance == 0 else math.copysign(1.0, imbalance)
            # Para una compra, imbalance positivo = el precio tiende a subir = la orden se le escapa: "en contra".
            filas.append({"exchange": exchange, "t": t, "lado": 1.0, "precio": libro.bids[0].precio,
                          "favor": -signo})
            filas.append({"exchange": exchange, "t": t, "lado": -1.0, "precio": libro.asks[0].precio,
                          "favor": signo})
    return pd.DataFrame(filas, columns=["exchange", "t", "lado", "precio", "favor"])


def llenado_limit(libros: pd.DataFrame, trades: pd.DataFrame, esperas=ESPERAS_S, muestreo_s: float = MUESTREO_S,
                  minimo: int = MIN_ORDENES, banda_bps: float = BANDA_BPS) -> list[LlenadoLimit]:
    """Para cada exchange, espera y signo del imbalance: cuántas órdenes limit hipotéticas se habrían llenado y
    con qué markout. "A favor": el imbalance empuja el precio HACIA la orden (compra con imbalance negativo)."""
    mids, ordenes, resultados = _mids(libros), colocaciones(libros, muestreo_s, banda_bps), []
    for exchange, o in ordenes.groupby("exchange", sort=True):
        tr = trades[trades.exchange == exchange]
        tt, tp = _segundos(tr["recibido_utc"]), tr["precio"].to_numpy(dtype=float)
        vende = tr["lado_agresor"].to_numpy() == "sell"  # el agresor vendedor llena compras limit
        for espera in esperas:
            estado, t_llenado = [], []
            for _, orden in o.iterrows():
                i0, i1 = np.searchsorted(tt, orden.t, "right"), np.searchsorted(tt, orden.t + espera, "right")
                contraria = (vende[i0:i1] if orden.lado > 0 else ~vende[i0:i1])
                precios = tp[i0:i1]
                peor = contraria & ((precios < orden.precio) if orden.lado > 0 else (precios > orden.precio))
                igual = contraria & (precios == orden.precio)
                if peor.any():
                    estado.append("seguro")
                    t_llenado.append(tt[i0:i1][peor.argmax()])
                else:
                    estado.append("posible" if igual.any() else "no")
                    t_llenado.append(math.nan)
            o_e = o.assign(estado=estado, t_llenado=t_llenado)
            llenas = o_e[o_e.estado == "seguro"]
            markout = (llenas.lado * (mids[exchange].en(llenas.t_llenado.to_numpy() + HORIZONTE_LIMIT_S)
                                      / llenas.precio - 1) * 1e4) if exchange in mids else pd.Series(dtype=float)
            o_e = o_e.assign(markout=np.nan)
            o_e.loc[llenas.index, "markout"] = markout
            for nombre, filtro in (("todos", o_e.favor == o_e.favor), ("a favor", o_e.favor > 0),
                                   ("en contra", o_e.favor < 0)):
                s = o_e[filtro]
                resultados.append(LlenadoLimit(exchange, int(espera), nombre, len(s), int((s.estado == "seguro").sum()),
                                               int((s.estado == "posible").sum()),
                                               float(s.markout.mean()) if s.markout.notna().any() else math.nan, minimo))
    return resultados


def estudiar_markouts(consultar: Callable[[str], pd.DataFrame], fuente_libros: str = "libros_flujo"):
    libros, trades = _cargar(consultar, fuente_libros)
    return markouts_trades(libros, trades), llenado_limit(libros, trades)
