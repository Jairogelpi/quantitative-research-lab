"""¿Anticipa el desequilibrio del libro el movimiento del precio? (Fase 2; base de las fases de señales).

Conceptos:
- Retorno futuro (forward return): (mid dentro de k rondas / mid ahora − 1) en bps. Es lo que el imbalance de
  AHORA pretende anticipar. Solo se usa el futuro para evaluar, nunca para calcular la señal.
- Horizonte: cuántas rondas hacia delante se mira. Si entre las dos fotos pasó mucho más tiempo del esperado
  (otra captura, un corte), el par se descarta: no sería el horizonte pedido.
- Media condicionada: retorno medio de las rondas con imbalance positivo frente al de las de imbalance
  negativo. Si el imbalance no anticipa nada, las dos medias se parecen.
- Estadístico t (de Welch): diferencia de medias / su error estándar. Mide cuántas veces la diferencia es
  mayor que lo que movería el azar con esa cantidad de datos y ese ruido. Regla práctica: |t| ≥ 2 → la
  diferencia es clara; |t| < 2 → no se distingue del azar.
- Mínimo de datos por grupo: con pocas rondas no se concluye nada, ni siquiera se calcula el veredicto.

Cautela: rondas seguidas tienen imbalances parecidos (no son independientes) y eso infla el t; un t
algo mayor que 2 no es una prueba definitiva. Y una relación clara no implica beneficio: hay que compararla
con los costes (punto de equilibrio).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from radar.configuracion import INTERVALO_S

MIN_POR_GRUPO = 200
T_CLARO = 2.0
MARGEN_S = 2.0  # tiempo extra tolerado sobre horizonte × intervalo


@dataclass(frozen=True)
class ResultadoImbalance:
    exchange: str
    banda_bps: float
    n_positivo: int
    n_negativo: int
    ret_positivo_bps: float
    ret_negativo_bps: float
    t: float
    min_por_grupo: int

    @property
    def diferencia_bps(self) -> float:
        return self.ret_positivo_bps - self.ret_negativo_bps

    @property
    def suficiente(self) -> bool:
        return min(self.n_positivo, self.n_negativo) >= self.min_por_grupo

    @property
    def distinguible(self) -> bool:
        return self.suficiente and abs(self.t) >= T_CLARO

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, banda {self.banda_bps:g} bps"
        if not self.suficiente:
            return (f"{cabecera}: datos insuficientes ({self.n_positivo} rondas con imbalance positivo y "
                    f"{self.n_negativo} con negativo; hacen falta {self.min_por_grupo} en cada grupo).")
        veredicto = "la diferencia es clara" if self.distinguible else "no se distingue del azar"
        return (f"{cabecera}: con imbalance positivo el mid se movió {self.ret_positivo_bps:+.3f} bps de media y con "
                f"negativo {self.ret_negativo_bps:+.3f} bps (diferencia {self.diferencia_bps:+.3f} bps, "
                f"t = {self.t:.2f}): {veredicto}.")


def _t_welch(a: pd.Series, b: pd.Series) -> float:
    diferencia = a.mean() - b.mean()
    error = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) if min(len(a), len(b)) > 1 else math.nan
    if error == 0:  # sin ruido: o no hay diferencia, o es infinitamente clara
        return 0.0 if diferencia == 0 else math.copysign(math.inf, diferencia)
    return diferencia / error


def estudiar_imbalance(pares: pd.DataFrame, min_por_grupo: int = MIN_POR_GRUPO) -> list[ResultadoImbalance]:
    """Un resultado por exchange y banda. `pares`: columnas exchange, banda_bps, imbalance, ret_bps.
    Las rondas con imbalance exactamente 0 no entran en ningún grupo."""
    resultados = []
    for (exchange, banda), g in pares.groupby(["exchange", "banda_bps"], sort=True):
        pos, neg = g.ret_bps[g.imbalance > 0], g.ret_bps[g.imbalance < 0]
        resultados.append(ResultadoImbalance(
            exchange, banda, len(pos), len(neg), pos.mean() if len(pos) else math.nan,
            neg.mean() if len(neg) else math.nan, _t_welch(pos, neg), min_por_grupo))
    return resultados


def pares_imbalance_retorno(consultar: Callable[[str], pd.DataFrame], horizonte_rondas: int = 1,
                            intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Une cada imbalance con el retorno del mid `horizonte_rondas` después, usando el lake (vía SQL)."""
    if horizonte_rondas < 1:
        raise ValueError("El horizonte debe ser de al menos 1 ronda")
    maximo_s = horizonte_rondas * intervalo_s + MARGEN_S
    return consultar(f"""
        WITH m AS (
            SELECT exchange, recibido_utc, mid,
                   lead(mid, {horizonte_rondas}) OVER w AS mid_futuro,
                   lead(recibido_utc, {horizonte_rondas}) OVER w AS t_futuro
            FROM cotizaciones WINDOW w AS (PARTITION BY exchange ORDER BY recibido_utc))
        SELECT d.exchange, d.banda_bps, d.recibido_utc, d.imbalance, (m.mid_futuro / m.mid - 1) * 1e4 AS ret_bps
        FROM desequilibrios d JOIN m USING (exchange, recibido_utc)
        WHERE d.imbalance IS NOT NULL AND m.mid_futuro IS NOT NULL
          AND epoch(m.t_futuro) - epoch(m.recibido_utc) <= {maximo_s}
        ORDER BY d.exchange, d.banda_bps, d.recibido_utc""")
