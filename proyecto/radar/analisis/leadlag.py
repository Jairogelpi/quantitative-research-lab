"""Lead-lag entre exchanges: ¿cuál se mueve primero? (Fase 2; descubrimiento de precio).

Conceptos:
- Descubrimiento de precio (price discovery): el mismo activo cotiza en varios mercados, pero la información
  nueva suele aparecer primero en uno y los demás lo siguen. El que se mueve antes LIDERA.
- Alineación por ronda: las tres fotos de una ronda se piden a la vez; se emparejan por la hora de solicitud
  (la más cercana, con tolerancia), no por número de ronda, que se reinicia en cada captura.
- Retorno por ronda: cambio del mid entre rondas seguidas, en bps. Si entre dos rondas hubo un corte, no cuenta.
- Correlación cruzada: corr(r_A(t), r_B(t + ℓ)). Con ℓ = 0 mide cuánto se mueven juntos; con ℓ > 0, si el
  movimiento de A anticipa el de B.
- Causalidad de Granger: r_B(t + ℓ) = a + b · r_A(t) + c · r_B(t). Si b es significativo, el pasado de A
  predice a B más allá de lo que B ya dice de sí mismo. Errores Newey-West (HAC).
- Lead-lag ratio (Huth y Abergel, 2014): Σ ρ²(A → B, ℓ) / Σ ρ²(B → A, ℓ), ℓ = 1..`RETARDO_LLR`. Mayor que 1:
  A lidera más de lo que sigue.
- Trampa de la latencia: si las fotos de A llegan, de media, más tarde que las de B dentro de una ronda, la de A
  ya contiene parte del futuro de B y A PARECE liderar. Por eso se reporta la latencia mediana de cada uno y se
  prueban retardos de 2 y 3 rondas, mayores que cualquier desfase de latencia medido.
- Final de los datos (`hasta_utc`): la última hora de solicitud que vio el estudio. La revalidación
  (`revalidacion.py`) solo usa rondas posteriores.
- Mismo rigor que el imbalance: descubrimiento en la primera mitad, confirmación en la segunda y
  Benjamini-Hochberg sobre todas las pruebas.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from radar.configuracion import INTERVALO_S

from .calidad import FACTOR_HUECO
from .imbalance import ALFA, _p_valor, _retardos

FUENTE_LEAD_LAG = "estudios_lead_lag"
RETARDOS = (1, 2, 3)
RETARDO_LLR = 5
MIN_RONDAS = 500
TOLERANCIA_ALINEACION = 0.3  # fracción del intervalo


def mids_alineados(consultar: Callable[[str], pd.DataFrame], intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Una fila por ronda con `mid_<exchange>` y `latencia_<exchange>` de cada exchange, emparejados por hora de
    solicitud. Columna `t` (segundos epoch de la solicitud del exchange de referencia)."""
    df = consultar("SELECT exchange, solicitado_utc, latencia_s, mid FROM cotizaciones ORDER BY solicitado_utc")
    if df.empty:
        return pd.DataFrame()
    exchanges = df["exchange"].value_counts().index.tolist()  # el de más rondas es la referencia
    base = None
    for ex in exchanges:
        g = (df[df.exchange == ex].drop(columns="exchange").sort_values("solicitado_utc")
             .rename(columns={"mid": f"mid_{ex}", "latencia_s": f"latencia_{ex}"}))
        base = g if base is None else pd.merge_asof(
            base, g, on="solicitado_utc", direction="nearest",
            tolerance=pd.Timedelta(seconds=TOLERANCIA_ALINEACION * intervalo_s))
    base = base.dropna().reset_index(drop=True)
    base["t"] = base["solicitado_utc"].map(pd.Timestamp.timestamp)
    return base


def retornos(alineados: pd.DataFrame, intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Retorno del mid (bps) de cada exchange entre rondas seguidas; NaN si hubo un corte entre ellas."""
    seguidas = alineados["t"].diff() <= FACTOR_HUECO * intervalo_s
    salida = pd.DataFrame({"solicitado_utc": alineados["solicitado_utc"]})
    for c in [c for c in alineados.columns if c.startswith("mid_")]:
        salida[f"r_{c[4:]}"] = np.where(seguidas, (alineados[c] / alineados[c].shift() - 1) * 1e4, np.nan)
    return salida


def correlacion_cruzada(r: pd.DataFrame, a: str, b: str, retardo: int) -> float:
    """corr(r_a(t), r_b(t + retardo)) usando solo filas donde los dos retornos existen."""
    x, y = r[f"r_{a}"], r[f"r_{b}"].shift(-retardo)
    validos = x.notna() & y.notna()
    return float(np.corrcoef(x[validos], y[validos])[0, 1]) if validos.sum() > 2 else math.nan


def lead_lag_ratio(r: pd.DataFrame, a: str, b: str, retardo_max: int = RETARDO_LLR) -> float:
    adelante = sum(correlacion_cruzada(r, a, b, l) ** 2 for l in range(1, retardo_max + 1))
    atras = sum(correlacion_cruzada(r, b, a, l) ** 2 for l in range(1, retardo_max + 1))
    return adelante / atras if atras > 0 else math.inf


def _granger(r: pd.DataFrame, a: str, b: str, retardo: int) -> tuple[float, float, int]:
    """(b, t HAC, n) de r_b(t + retardo) = c0 + b · r_a(t) + c1 · r_b(t)."""
    datos = pd.DataFrame({"y": r[f"r_{b}"].shift(-retardo), "x": r[f"r_{a}"], "propio": r[f"r_{b}"]}).dropna()
    if len(datos) < 10 or datos["x"].nunique() < 2:
        return math.nan, math.nan, len(datos)
    modelo = sm.OLS(datos["y"], sm.add_constant(datos[["x", "propio"]])).fit(
        cov_type="HAC", cov_kwds={"maxlags": _retardos(len(datos), retardo)})
    return float(modelo.params["x"]), float(modelo.tvalues["x"]), len(datos)


@dataclass(frozen=True)
class LeadLag:
    lider: str
    seguidor: str
    retardo_rondas: int
    n: int
    correlacion_0: float
    coef_descubrimiento: float
    t_descubrimiento: float
    p_descubrimiento: float
    p_ajustado: float
    coef_confirmacion: float
    t_confirmacion: float
    lead_lag_ratio: float
    latencia_lider_s: float
    latencia_seguidor_s: float
    minimo: int
    hasta_utc: pd.Timestamp = pd.NaT

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        if not self.p_ajustado < ALFA:
            return "sin evidencia"
        if np.sign(self.t_confirmacion) == np.sign(self.t_descubrimiento) and abs(self.t_confirmacion) >= 2:
            return "confirmada"
        return "no confirmada fuera de muestra"

    @property
    def sospecha_latencia(self) -> bool:
        """Con retardo de 1 ronda y un líder que responde más tarde, el adelanto puede ser solo latencia."""
        return self.retardo_rondas == 1 and self.latencia_lider_s > self.latencia_seguidor_s + 0.05

    def conclusion(self) -> str:
        cabecera = f"¿{self.lider} anticipa a {self.seguidor} a {self.retardo_rondas} ronda(s)?"
        if self.estado == "datos insuficientes":
            return f"{cabecera} datos insuficientes ({self.n} rondas; hacen falta {self.minimo})."
        texto = (f"{cabecera} {self.estado}. Coeficiente {self.coef_descubrimiento:+.3f} (t HAC "
                 f"{self.t_descubrimiento:.2f}, p ajustado {self.p_ajustado:.3f}); confirmación {self.coef_confirmacion:+.3f} "
                 f"(t {self.t_confirmacion:.2f}); lead-lag ratio {self.lead_lag_ratio:.2f}; correlación simultánea "
                 f"{self.correlacion_0:+.2f}.")
        if self.sospecha_latencia:
            texto += (f" Ojo: {self.lider} responde más tarde (latencia mediana {self.latencia_lider_s:.2f} s frente a "
                      f"{self.latencia_seguidor_s:.2f} s); a 1 ronda el adelanto puede ser solo latencia.")
        return texto

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "sospecha_latencia": self.sospecha_latencia,
                "conclusion": self.conclusion()}


def estudiar_lead_lag(alineados: pd.DataFrame, retardos=RETARDOS, minimo: int = MIN_RONDAS,
                      intervalo_s: float = INTERVALO_S) -> list[LeadLag]:
    """Cada par ordenado de exchanges y retardo: Granger en la primera mitad (descubre) y en la segunda
    (confirma), Benjamini-Hochberg sobre todos los descubrimientos."""
    if alineados.empty:
        return []
    r = retornos(alineados, intervalo_s)
    mitad = len(r) // 2
    primera, segunda = r.iloc[:mitad].reset_index(drop=True), r.iloc[mitad:].reset_index(drop=True)
    exchanges = sorted(c[2:] for c in r.columns if c.startswith("r_"))
    borradores = []
    for a, b in itertools.permutations(exchanges, 2):
        llr, c0 = lead_lag_ratio(r, a, b), correlacion_cruzada(r, a, b, 0)
        lat_a, lat_b = float(alineados[f"latencia_{a}"].median()), float(alineados[f"latencia_{b}"].median())
        for retardo in retardos:
            coef1, t1, n1 = _granger(primera, a, b, retardo)
            coef2, t2, n2 = _granger(segunda, a, b, retardo)
            borradores.append(dict(lider=a, seguidor=b, retardo_rondas=retardo, n=min(n1, n2), correlacion_0=c0,
                                   coef_descubrimiento=coef1, t_descubrimiento=t1, p_descubrimiento=_p_valor(t1),
                                   coef_confirmacion=coef2, t_confirmacion=t2, lead_lag_ratio=llr,
                                   latencia_lider_s=lat_a, latencia_seguidor_s=lat_b, minimo=minimo))
    validos = [i for i, d in enumerate(borradores) if d["n"] >= minimo and not math.isnan(d["p_descubrimiento"])]
    ajustados = multipletests([borradores[i]["p_descubrimiento"] for i in validos], method="fdr_bh")[1] if validos else []
    p = dict(zip(validos, ajustados))
    hasta = alineados["solicitado_utc"].max()
    return [LeadLag(**d, p_ajustado=float(p.get(i, math.nan)), hasta_utc=hasta) for i, d in enumerate(borradores)]


def matriz_correlaciones(alineados: pd.DataFrame, intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Correlación simultánea de los retornos por ronda entre exchanges."""
    r = retornos(alineados, intervalo_s).drop(columns="solicitado_utc")
    r.columns = [c[2:] for c in r.columns]
    return r.corr()
