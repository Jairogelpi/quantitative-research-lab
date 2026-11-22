"""Revalidación de hallazgos: ¿se sostiene lo confirmado con datos que el estudio todavía no había visto?

Conceptos:
- Hallazgo: una relación en estado "confirmada" en el último estudio guardado.
- Fuera de muestra de verdad: la confirmación del estudio usa la segunda mitad de los MISMOS datos. Aquí solo
  se usan rondas capturadas DESPUÉS del final (`hasta_utc`) de ese estudio: datos que nadie usó para encontrarlo.
- Estados:
  · se mantiene: mismo signo que al descubrirlo y |t HAC| ≥ 2 con los datos nuevos.
  · se debilita: mismo signo, pero |t| < 2 (puede faltar datos o el efecto ser menor).
  · se cae: signo contrario con los datos nuevos.
  · pendiente: todavía no hay `min_por_grupo` rondas nuevas con imbalance positivo y con negativo.
- Cada revalidación se guarda en la fuente `revalidaciones`: el historial de cada hallazgo a lo largo del tiempo.
- `clasificar` es la regla común: la usan también las revalidaciones del OFI, el lead-lag y las señales
  (`revalidacion.py`), cada una con su efecto y su mínimo de datos.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .imbalance import CONFIRMADA, MIN_POR_GRUPO, T_CONFIRMACION, diferencia_hac

FUENTE_REVALIDACIONES = "revalidaciones"
SE_MANTIENE, SE_DEBILITA, SE_CAE, PENDIENTE = "se mantiene", "se debilita", "se cae", "pendiente"


def clasificar(suficiente: bool, anterior: float, ahora: float, t: float) -> str:
    """Estado de un hallazgo revalidado: pendiente sin datos suficientes; se cae si el efecto cambió de signo;
    se mantiene si conserva el signo con |t| ≥ 2; si no, se debilita."""
    if not suficiente:
        return PENDIENTE
    if np.sign(ahora) != np.sign(anterior):
        return SE_CAE
    return SE_MANTIENE if abs(t) >= T_CONFIRMACION else SE_DEBILITA


@dataclass(frozen=True)
class Revalidacion:
    exchange: str
    banda_bps: float
    horizonte_rondas: int
    desde_utc: pd.Timestamp
    n_positivo: int
    n_negativo: int
    diferencia_anterior: float
    diferencia: float
    t: float
    min_por_grupo: int

    @property
    def estado(self) -> str:
        return clasificar(min(self.n_positivo, self.n_negativo) >= self.min_por_grupo, self.diferencia_anterior,
                          self.diferencia, self.t)

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, banda {self.banda_bps:g} bps, horizonte {self.horizonte_rondas}"
        if self.estado == PENDIENTE:
            return (f"{cabecera}: pendiente (con datos posteriores al estudio hay {self.n_positivo} rondas con "
                    f"imbalance positivo y {self.n_negativo} con negativo; hacen falta {self.min_por_grupo} en cada grupo).")
        return (f"{cabecera}: {self.estado} con datos posteriores al estudio (desde {self.desde_utc:%Y-%m-%d %H:%M:%S} "
                f"UTC): diferencia {self.diferencia_anterior:+.3f} bps al descubrirlo y {self.diferencia:+.3f} bps "
                f"ahora (t HAC {self.t:.2f}).")

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def revalidar(pares: pd.DataFrame, anterior: pd.DataFrame, min_por_grupo: int = MIN_POR_GRUPO) -> list[Revalidacion]:
    """Vuelve a probar cada hallazgo confirmado de `anterior` (filas de un estudio guardado) solo con los pares
    posteriores a su `hasta_utc`."""
    revalidaciones = []
    for h in anterior[anterior.estado == CONFIRMADA].itertuples(index=False):
        g = pares[(pares.exchange == h.exchange) & (pares.banda_bps == h.banda_bps)
                  & (pares.horizonte_rondas == h.horizonte_rondas) & (pares.recibido_utc > h.hasta_utc)]
        g = g.sort_values("recibido_utc")
        diferencia, _, t, n_pos, n_neg = diferencia_hac(g, h.horizonte_rondas)
        revalidaciones.append(Revalidacion(h.exchange, h.banda_bps, int(h.horizonte_rondas),
                                           g.recibido_utc.iloc[0] if len(g) else pd.NaT, n_pos, n_neg,
                                           float(h.diferencia_descubrimiento), diferencia, t, min_por_grupo))
    return revalidaciones


def guardar_revalidaciones(revalidaciones, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in revalidaciones], FUENTE_REVALIDACIONES)
