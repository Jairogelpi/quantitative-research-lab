"""Order Flow Imbalance (OFI): cuánto cambió la cantidad en el bid y en el ask entre una foto y la siguiente (Fase 2).

Conceptos:
- OFI (Cont, Kukanov y Stoikov, 2014, "The Price Impact of Order Book Events"): entre las fotos t−1 y t, en el
  bid suma la cantidad nueva y resta la que se fue; en el ask, al revés:
    e_bid = Qb(t)·[Pb(t) ≥ Pb(t−1)] − Qb(t−1)·[Pb(t) ≤ Pb(t−1)]
    e_ask = −Qa(t)·[Pa(t) ≤ Pa(t−1)] + Qa(t−1)·[Pa(t) ≥ Pa(t−1)]
  OFI = e_bid + e_ask, en BTC. Positivo = llegó presión compradora (más bids o menos asks). A diferencia del
  imbalance de una foto (un ESTADO), el OFI mide un FLUJO: lo que pasó entre dos fotos.
- OFI multinivel: la misma cuenta en los primeros `niveles` niveles de cada lado, sumada (Xu, Gould y Howison,
  2019, "Multi-Level Order-Flow Imbalance in a Limit Order Book"). Usa la profundidad que el mejor nivel ignora.
- Impacto contemporáneo: regresión del cambio del mid entre t−1 y t sobre el OFI del mismo intervalo
  (Δmid = a + β · OFI). β son bps por BTC neto; el R² dice cuánto del movimiento explica el flujo. Es el resultado
  clásico del artículo: el OFI explica el precio en el MISMO intervalo, no necesariamente el siguiente.
- Poder predictivo: el OFI de AHORA frente al retorno FUTURO, con el mismo método que el imbalance (`imbalance.py`:
  errores HAC, Benjamini-Hochberg, descubrimiento/confirmación, ventanas, controles, IC y quintiles).
- Solo cuentan pares de fotos seguidas separadas como mucho `FACTOR_HUECO` × intervalo: si hubo un corte, la
  diferencia entre las fotos no es un flujo de un segundo.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm

from radar.configuracion import INTERVALO_S

from .calidad import FACTOR_HUECO
from .imbalance import HORIZONTES, MARGEN_S, MIN_POR_GRUPO, _retardos, estudiar_imbalance

FUENTE_ESTUDIOS_OFI = "estudios_ofi"
METODO_OFI = "ofi_retorno/v1"
NIVELES_OFI = (1, 5, 10)
MIN_PARES = 200


def ofi(bp: np.ndarray, bq: np.ndarray, ap: np.ndarray, aq: np.ndarray) -> np.ndarray:
    """OFI de cada intervalo (filas t−1 → t), sumado sobre las columnas (niveles). Matrices (fotos × niveles)."""
    sube_b, baja_b = bp[1:] >= bp[:-1], bp[1:] <= bp[:-1]
    baja_a, sube_a = ap[1:] <= ap[:-1], ap[1:] >= ap[:-1]
    e_bid = bq[1:] * sube_b - bq[:-1] * baja_b
    e_ask = -aq[1:] * baja_a + aq[:-1] * sube_a
    return (e_bid + e_ask).sum(axis=1)


def _matrices(g: pd.DataFrame, niveles: int):
    """Precios y cantidades de los primeros `niveles` de cada lado; None si alguna foto tiene menos niveles."""
    columnas = ("bid_precios", "bid_cantidades", "ask_precios", "ask_cantidades")
    if g[list(columnas)].map(len).min().min() < niveles:
        return None
    return tuple(np.array([list(x[:niveles]) for x in g[c]], dtype=float) for c in columnas)


def pares_ofi_retorno(consultar: Callable[[str], pd.DataFrame], horizontes=HORIZONTES, niveles=NIVELES_OFI,
                      intervalo_s: float = INTERVALO_S, fuente: str = "libros") -> pd.DataFrame:
    """Una fila por exchange, niveles, horizonte y foto: el OFI del intervalo que termina en la foto, el cambio
    del mid en ese intervalo (`ret_actual_bps`), el retorno futuro y el pasado a k fotos, y el spread.
    Columnas compatibles con `estudiar_imbalance` (OFI en `imbalance`, niveles en `banda_bps`)."""
    libros = consultar(f"""SELECT exchange, recibido_utc, bid_precios, bid_cantidades, ask_precios, ask_cantidades
                           FROM {fuente} ORDER BY exchange, recibido_utc""")
    partes = []
    for exchange, g in libros.groupby("exchange", sort=True):
        g = g.reset_index(drop=True)
        t = g["recibido_utc"].map(pd.Timestamp.timestamp).to_numpy()
        bid = np.array([x[0] for x in g["bid_precios"]], dtype=float)
        ask = np.array([x[0] for x in g["ask_precios"]], dtype=float)
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 1e4
        seguidas = np.diff(t) <= FACTOR_HUECO * intervalo_s
        ret_actual = np.r_[np.nan, np.where(seguidas, (mid[1:] / mid[:-1] - 1) * 1e4, np.nan)]
        for n in niveles:
            m = _matrices(g, n)
            if m is None:
                continue
            flujo = np.r_[np.nan, np.where(seguidas, ofi(*m), np.nan)]
            for k in horizontes:
                maximo = k * intervalo_s + MARGEN_S
                futuro, pasado = np.full(len(g), np.nan), np.full(len(g), np.nan)
                if len(g) > k:
                    ok_f = t[k:] - t[:-k] <= maximo
                    futuro[:-k] = np.where(ok_f, (mid[k:] / mid[:-k] - 1) * 1e4, np.nan)
                    pasado[k:] = np.where(ok_f, (mid[k:] / mid[:-k] - 1) * 1e4, np.nan)
                parte = pd.DataFrame({"exchange": exchange, "banda_bps": n, "horizonte_rondas": k,
                                      "recibido_utc": g["recibido_utc"], "imbalance": flujo, "ret_bps": futuro,
                                      "ret_pasado_bps": pasado, "spread_bps": spread_bps,
                                      "ret_actual_bps": ret_actual})
                partes.append(parte.dropna(subset=["imbalance", "ret_bps"]))
    columnas = ["exchange", "banda_bps", "horizonte_rondas", "recibido_utc", "imbalance", "ret_bps",
                "ret_pasado_bps", "spread_bps", "ret_actual_bps"]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=columnas)


@dataclass(frozen=True)
class ImpactoOFI:
    exchange: str
    niveles: int
    n: int
    beta_bps_por_btc: float
    t_hac: float
    r2: float
    minimo: int
    hasta_utc: pd.Timestamp = pd.NaT   # último intervalo que usó el estudio: la revalidación empieza después

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        return "explica el precio" if abs(self.t_hac) >= 2 else "sin evidencia"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, OFI {self.niveles} niveles"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} intervalos; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. Cada BTC de OFI neto mueve el mid {self.beta_bps_por_btc:+.4f} bps en el "
                f"mismo intervalo (t HAC {self.t_hac:.2f}); explica el {self.r2:.1%} de sus movimientos "
                f"({self.n} intervalos).")

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def impacto_contemporaneo(pares: pd.DataFrame, minimo: int = MIN_PARES) -> list[ImpactoOFI]:
    """Δmid = a + β · OFI del mismo intervalo, con errores Newey-West, por exchange y niveles."""
    resultados = []
    unicos = pares.drop_duplicates(["exchange", "banda_bps", "recibido_utc"]).dropna(subset=["ret_actual_bps"])
    for (exchange, niveles), g in unicos.groupby(["exchange", "banda_bps"], sort=True):
        g = g.sort_values("recibido_utc")
        hasta = g["recibido_utc"].iloc[-1]
        if len(g) < minimo or g["imbalance"].nunique() < 2:
            resultados.append(ImpactoOFI(exchange, int(niveles), len(g), math.nan, math.nan, math.nan, minimo, hasta))
            continue
        modelo = sm.OLS(g["ret_actual_bps"].to_numpy(), sm.add_constant(g["imbalance"].to_numpy())).fit(
            cov_type="HAC", cov_kwds={"maxlags": _retardos(len(g), 1)})
        resultados.append(ImpactoOFI(exchange, int(niveles), len(g), float(modelo.params[1]),
                                     float(modelo.tvalues[1]), float(modelo.rsquared), minimo, hasta))
    return resultados


def estudiar_ofi(pares: pd.DataFrame, min_por_grupo: int = MIN_POR_GRUPO, equilibrio_bps: dict | None = None,
                 calidad: dict | None = None):
    """¿Anticipa el OFI de ahora el retorno futuro? El mismo estudio que el del imbalance, con la señal "ofi"."""
    return estudiar_imbalance(pares, min_por_grupo, equilibrio_bps, calidad, senal="ofi")


def guardar_estudio_ofi(impactos, resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda en `estudios_ofi` (aparte de `estudios`, que consume la ejecución): impacto y poder predictivo."""
    filas = [{"estudio": "ofi_impacto", **i.a_fila()} for i in impactos]
    filas += [{"estudio": "ofi_retorno", **{("niveles" if k == "banda_bps" else k): v for k, v in r.a_fila().items()}}
              for r in resultados]
    return almacen.guardar([{"metodo": METODO_OFI, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **f} for f in filas], FUENTE_ESTUDIOS_OFI)
