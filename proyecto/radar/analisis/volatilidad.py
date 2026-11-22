"""Volatilidad realizada robusta al ruido de microestructura: two-scale (TSRV) y signature plot (S6).

Conceptos:
- Precio observado = precio eficiente + ruido (rebote entre bid y ask, discreción del tick, fotos que llegan
  tarde). La varianza realizada (RV, suma de retornos al cuadrado) a la escala más fina suma también el ruido:
  E(RV) = varianza integrada + 2 · n · E(ruido²). Con n grande, el sesgo domina: medir cada segundo NO da una
  volatilidad más precisa, da otra cosa.
- Signature plot: RV (en tasa por unidad de tiempo) frente al intervalo de muestreo. Sin ruido sería plana; con
  ruido i.i.d. baja con el intervalo como σ² + 2 · E(ruido²) / k, y se aplana cuando el ruido ya no pesa. Sirve
  para ver el sesgo y elegir una frecuencia.
- RV promediada [Y, Y]^(avg) con K submallas: se muestrea cada K pasos empezando en cada uno de los K desfases y
  se promedian las K RV (ec. 13 de Zhang, Mykland y Aït-Sahalia, 2005). Con todos los desfases es
  (1/K) · Σ_i (y_i − y_{i−K})².
- TSRV (two-scale realized variance): [Y, Y]^(avg) − (n̄ / n) · [Y, Y]^(all), con n̄ = (1/K) · Σ_k n_k el número
  medio de retornos por submalla (ec. 15) y [Y, Y]^(all) la RV de la malla completa, que estima el sesgo del
  ruido (ec. 32-33). Con el ajuste de muestra pequeña (ec. 41): (1 − n̄ / n)^(−1) · TSRV. Varianza del ruido
  ajustada (ec. 42): (1/2) · (n − n̄)^(−1) · ([Y, Y]^(all) − [Y, Y]^(avg)). K óptimo = c · n^(2/3) (ec. 36);
  con c estimado de los datos queda K* = (12 · (E(ruido²) / σ²_paso)²)^(1/3).
  Fuente verificada: L. Zhang, P. A. Mykland e Y. Aït-Sahalia, "A Tale of Two Time Scales: Determining
  Integrated Volatility with Noisy High-Frequency Data", JASA 100 (2005) 1394-1411; NBER WP 10111,
  https://www.nber.org/papers/w10111 (ecuaciones 10, 13, 15, 32, 33, 36, 41 y 42 comprobadas en el texto).
- Huecos: los precios se colocan en una malla regular de `intervalo_s`; un retorno solo existe si sus dos extremos
  tienen foto. n y n̄ cuentan solo los retornos que existen (ec. 15 admite submallas de distinto tamaño).
- Contexto para las señales (`volatilidad_ts`): TSRV móvil con una ventana de `VENTANA_VOL_S` segundos que
  termina en la foto actual (solo pasado), K = `K_VOL` pasos, expresada como desviación típica de un retorno de
  una ronda (bps), la misma unidad que la volatilidad ingenua a la que sustituye.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from radar.configuracion import INTERVALO_S

FUENTE_VOLATILIDAD = "estudios_volatilidad"
INTERVALOS_FIRMA_S = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600)
VENTANA_VOL_S = 300        # ventana del contexto de las señales (segundos)
K_VOL = 10                 # submallas de la TSRV móvil (pasos de la malla)
MIN_OBS_VOL = 60           # retornos de un paso mínimos en la ventana para dar un valor
MIN_SEGUNDOS = 1800        # retornos de un paso mínimos para el signature plot (media hora)
TOLERANCIA_FIRMA = 0.10    # una frecuencia vale si su volatilidad está a menos del 10 % de la TSRV
UMBRAL_RUIDO = 0.20        # si la RV a 1 paso se aparta un 20 % o más de la TSRV, el ruido es apreciable
K_MINIMO = 2


def malla(t: np.ndarray, mid: np.ndarray, intervalo_s: float = INTERVALO_S) -> tuple[np.ndarray, np.ndarray]:
    """(log-precios en una malla regular con NaN donde no hay foto, índice de la malla de cada fila).

    Cada fila va a la celda más cercana desde la primera foto. Si dos filas caen en la misma celda se queda la
    PRIMERA: así la celda de una fila nunca contiene un precio posterior a ella (filas en orden temporal)."""
    t = np.asarray(t, dtype=float)
    if len(t) == 0:
        return np.array([]), np.array([], dtype=int)
    indice = np.rint((t - t[0]) / intervalo_s).astype(int)
    logp = np.full(indice[-1] + 1, np.nan)
    primera = np.r_[True, np.diff(indice) > 0]
    logp[indice[primera]] = np.log(np.asarray(mid, dtype=float)[primera])
    return logp, indice


def _cuadrados(logp: np.ndarray, k: int) -> np.ndarray:
    """(y_i − y_{i−k})² para cada i ≥ k; NaN si falta algún extremo."""
    salida = np.full(len(logp), np.nan)
    if len(logp) > k:
        salida[k:] = (logp[k:] - logp[:-k]) ** 2
    return salida


def rv_media(logp: np.ndarray, k: int) -> float:
    """[Y, Y]^(avg) con k submallas (ec. 13): (1/k) · Σ (y_i − y_{i−k})². Con k = 1 es la RV de la malla completa."""
    return float(np.nansum(_cuadrados(logp, k)) / k)


@dataclass(frozen=True)
class Tsrv:
    varianza: float      # varianza integrada en la muestra (log-retorno²), con el ajuste de muestra pequeña
    ruido: float         # desviación típica del ruido (log), ec. 42
    k: int
    n: int               # retornos de un paso
    n_medio: float       # n̄

    @property
    def varianza_por_paso(self) -> float:
        return self.varianza / self.n if self.n else math.nan


def _tsrv_sumas(suma1: float, n1: int, suma_k: float, n_k: int, k: int) -> tuple[float, float]:
    """(TSRV ajustada, varianza del ruido ajustada) a partir de las sumas de cuadrados y los recuentos."""
    n_medio = n_k / k
    if n1 == 0 or n_medio >= n1:
        return math.nan, math.nan
    todo, media = suma1, suma_k / k
    varianza = (media - n_medio / n1 * todo) / (1 - n_medio / n1)
    ruido2 = (todo - media) / (2 * (n1 - n_medio))
    return varianza, ruido2


def tsrv(logp: np.ndarray, k: int | None = None) -> Tsrv:
    """TSRV de Zhang, Mykland y Aït-Sahalia (2005) sobre una malla de log-precios (NaN = sin foto). Sin `k`, el K
    óptimo de la ec. 36 con c estimado de los datos, usando una TSRV piloto con K = n^(2/3)."""
    logp = np.asarray(logp, dtype=float)
    c1 = _cuadrados(logp, 1)
    n1, suma1 = int(np.sum(~np.isnan(c1))), float(np.nansum(c1))
    if k is None:
        piloto = max(K_MINIMO, int(round(n1 ** (2 / 3)))) if n1 else K_MINIMO
        k = _k_optimo(logp, n1, suma1, piloto)
    ck = _cuadrados(logp, k)
    n_k = int(np.sum(~np.isnan(ck)))
    varianza, ruido2 = _tsrv_sumas(suma1, n1, float(np.nansum(ck)), n_k, k)
    ruido = math.sqrt(ruido2) if ruido2 >= 0 else math.nan
    return Tsrv(varianza, ruido, int(k), n1, n_k / k)


def _k_optimo(logp, n1, suma1, piloto) -> int:
    ck = _cuadrados(logp, piloto)
    varianza, ruido2 = _tsrv_sumas(suma1, n1, float(np.nansum(ck)), int(np.sum(~np.isnan(ck))), piloto)
    if not (n1 and varianza > 0 and ruido2 > 0):
        return piloto
    k = math.ceil((12 * (ruido2 / (varianza / n1)) ** 2) ** (1 / 3))
    return int(min(max(k, K_MINIMO), max(K_MINIMO, n1 // 10)))


def volatilidad_ts(t: np.ndarray, mid: np.ndarray, ventana_s: float = VENTANA_VOL_S, k: int = K_VOL,
                   intervalo_s: float = INTERVALO_S, minimo: int = MIN_OBS_VOL) -> np.ndarray:
    """Para cada fila (en orden temporal), la volatilidad robusta al ruido de los últimos `ventana_s` segundos
    hasta ella incluida: desviación típica de un retorno de `intervalo_s` en bps, por TSRV con `k` submallas.

    Solo pasado: un retorno entra si sus dos extremos están en (t − ventana, t]. NaN si hay menos de `minimo`
    retornos de un paso, o si la TSRV sale negativa (ventana demasiado corta para corregir el ruido)."""
    logp, indice = malla(t, mid, intervalo_s)
    if len(indice) == 0:
        return np.array([])
    w = max(int(round(ventana_s / intervalo_s)), k + 1)
    acumulados = []
    for paso in (1, k):
        c = _cuadrados(logp, paso)
        acumulados.append((np.r_[0.0, np.cumsum(np.nan_to_num(c))], np.r_[0, np.cumsum(~np.isnan(c))]))
    (s1, n1), (sk, nk) = acumulados

    def ventana(acum, paso):
        # Retornos que terminan en (g − w + paso, g]: empiezan dentro de la ventana.
        fin = indice + 1
        inicio = np.clip(indice - w + paso + 1, 0, None)
        return acum[fin] - acum[np.minimum(inicio, fin)]

    suma1, cuenta1 = ventana(s1, 1), ventana(n1, 1)
    suma_k, cuenta_k = ventana(sk, k), ventana(nk, k)
    salida = np.full(len(indice), np.nan)
    for i in range(len(indice)):
        if cuenta1[i] < minimo:
            continue
        varianza, _ = _tsrv_sumas(float(suma1[i]), int(cuenta1[i]), float(suma_k[i]), int(cuenta_k[i]), k)
        if varianza >= 0:
            salida[i] = math.sqrt(varianza / cuenta1[i]) * 1e4
    return salida


@dataclass(frozen=True)
class FirmaVolatilidad:
    exchange: str
    intervalos_s: tuple
    vol_bps_hora: tuple          # sqrt(RV promediada por segundo · 3600) · 10.000, para cada intervalo
    tsrv_bps_hora: float
    ruido_bps: float             # desviación típica del ruido, bps
    k_tsrv: int
    n_segundos: int              # retornos de un paso
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def sobreestimacion_1s(self) -> float:
        """Cuánto se aparta la volatilidad del intervalo más fino de la TSRV (0,5 = un 50 % más)."""
        if not self.vol_bps_hora or not self.tsrv_bps_hora or math.isnan(self.tsrv_bps_hora):
            return math.nan
        return self.vol_bps_hora[0] / self.tsrv_bps_hora - 1

    @property
    def frecuencia_recomendada_s(self) -> int | None:
        """El intervalo más fino cuya volatilidad está a menos de `TOLERANCIA_FIRMA` de la TSRV."""
        for s, v in zip(self.intervalos_s, self.vol_bps_hora):
            if not math.isnan(v) and abs(v / self.tsrv_bps_hora - 1) <= TOLERANCIA_FIRMA:
                return int(s)
        return None

    @property
    def estado(self) -> str:
        if self.n_segundos < self.minimo or math.isnan(self.sobreestimacion_1s):
            return "datos insuficientes"
        return "ruido apreciable" if abs(self.sobreestimacion_1s) >= UMBRAL_RUIDO else "ruido despreciable"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, signature plot"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n_segundos} retornos de 1 paso; hacen falta {self.minimo})."
        sentido = "sobreestima" if self.sobreestimacion_1s > 0 else "subestima"
        frecuencia = self.frecuencia_recomendada_s
        recomendacion = (f"frecuencia recomendada: {frecuencia} s (la primera a menos del {TOLERANCIA_FIRMA:.0%} de "
                         f"la TSRV)" if frecuencia is not None else
                         f"ninguna frecuencia queda a menos del {TOLERANCIA_FIRMA:.0%} de la TSRV: usar la TSRV")
        ruido = ("ruido no detectable (la RV fina no supera a la de K pasos)" if math.isnan(self.ruido_bps)
                 else f"ruido {self.ruido_bps:.2f} bps")
        curva = ", ".join(f"{s} s: {v:.1f}" for s, v in zip(self.intervalos_s, self.vol_bps_hora))
        return (f"{cabecera}: {self.estado}. La RV a {self.intervalos_s[0]} s {sentido} la volatilidad un "
                f"{abs(self.sobreestimacion_1s):.0%} ({self.vol_bps_hora[0]:.1f} frente a {self.tsrv_bps_hora:.1f} bps "
                f"por hora de la TSRV con K = {self.k_tsrv}); {ruido}; {recomendacion}. "
                f"Curva [{curva}] en {self.n_segundos} segundos.")

    def a_fila(self) -> dict:
        return {"estudio": "signature_plot", "exchange": self.exchange,
                "intervalos_s": list(self.intervalos_s), "vol_bps_hora": list(self.vol_bps_hora),
                "tsrv_bps_hora": self.tsrv_bps_hora, "ruido_bps": self.ruido_bps, "k_tsrv": self.k_tsrv,
                "n_segundos": self.n_segundos, "hasta_utc": self.hasta_utc, "minimo": self.minimo,
                "sobreestimacion_1s": self.sobreestimacion_1s,
                "frecuencia_recomendada_s": self.frecuencia_recomendada_s, "estado": self.estado,
                "conclusion": self.conclusion()}


def _bps_hora(varianza_por_paso: float, intervalo_s: float) -> float:
    if not varianza_por_paso >= 0:
        return math.nan
    return math.sqrt(varianza_por_paso / intervalo_s * 3600) * 1e4


def signature_plot(mids: pd.DataFrame, intervalos_s=INTERVALOS_FIRMA_S, intervalo_s: float = INTERVALO_S,
                   minimo: int = MIN_SEGUNDOS, k: int | None = None) -> list[FirmaVolatilidad]:
    """Por exchange (`exchange`, `recibido_utc`, `mid`): volatilidad (bps por hora) de la RV promediada a cada
    intervalo, frente a la TSRV. Los intervalos se redondean a pasos de la malla."""
    resultados = []
    for exchange, g in mids.sort_values(["exchange", "recibido_utc"]).groupby("exchange", sort=True):
        t = g["recibido_utc"].map(pd.Timestamp.timestamp).to_numpy()
        logp, _ = malla(t, g["mid"].to_numpy(dtype=float), intervalo_s)
        vols = []
        for s in intervalos_s:
            paso = max(1, int(round(s / intervalo_s)))
            c = _cuadrados(logp, paso)
            n = int(np.sum(~np.isnan(c)))
            vols.append(_bps_hora(float(np.nansum(c)) / (paso * n), intervalo_s) if n else math.nan)
        estimada = tsrv(logp, k)
        n1 = estimada.n
        hasta = g["recibido_utc"].iloc[-1]
        if n1 < minimo:
            resultados.append(FirmaVolatilidad(exchange, tuple(intervalos_s), tuple(vols), math.nan, math.nan,
                                               estimada.k, n1, hasta, minimo))
            continue
        resultados.append(FirmaVolatilidad(exchange, tuple(intervalos_s), tuple(vols),
                                           _bps_hora(estimada.varianza_por_paso, intervalo_s),
                                           estimada.ruido * 1e4, estimada.k, n1, hasta, minimo))
    return resultados


def estudiar_volatilidad(consultar: Callable[[str], pd.DataFrame], intervalos_s=INTERVALOS_FIRMA_S,
                         minimo: int = MIN_SEGUNDOS) -> list[FirmaVolatilidad]:
    """Signature plot y TSRV de los mids de las cotizaciones (una ronda por `INTERVALO_S`)."""
    mids = consultar("SELECT exchange, recibido_utc, mid FROM cotizaciones ORDER BY exchange, recibido_utc")
    return signature_plot(mids, intervalos_s, minimo=minimo)


def guardar_estudio_volatilidad(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in resultados], FUENTE_VOLATILIDAD)
