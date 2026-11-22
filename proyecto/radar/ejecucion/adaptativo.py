"""Almgren-Chriss adaptativo: el plan de Almgren-Chriss corregido trozo a trozo con la señal de imbalance que el
análisis confirmó y guardó en `estudios` (Fase 8, tercer escalón).

Conceptos:
- Primer consumidor de las conclusiones: la ejecución no inventa la señal. Usa un hallazgo en estado "confirmada"
  del mismo exchange, leído de la fuente `estudios`.
- Política: antes de cada trozo se mira el libro de ese momento. Si el estudio dice que un imbalance positivo
  anticipa subidas, con imbalance positivo conviene ADELANTAR compras (comprar antes de que suba) y con negativo
  RETRASARLAS. Fracción de lo pendiente que se compra ahora =
  fracción de Almgren-Chriss · (1 + intensidad · imbalance · signo del hallazgo), entre 0 y 1.
  El último trozo compra todo lo que quede. Intensidad 0 = Almgren-Chriss sin adaptar.
- Fuera de muestra: la señal sale de un estudio cuyos datos terminaron ANTES de las ventanas simuladas. Usar un
  estudio hecho con esos mismos libros sería mirar el futuro (sesgo de anticipación).
- Horizonte: se elige el hallazgo cuyo horizonte (rondas × intervalo) se parece más a la separación entre trozos.
- La intensidad es un parámetro de sensibilidad, no un valor ajustado a los datos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from radar.analisis import CONFIRMADA
from radar.configuracion import INTERVALO_S
from radar.mercado import Libro, desequilibrio

from .almgren_chriss import plan_almgren_chriss
from .simulador import TOLERANCIA_S, ResultadoEjecucion, ejecutar_politica


@dataclass(frozen=True)
class SenalImbalance:
    exchange: str
    banda_bps: float
    horizonte_rondas: int
    diferencia_bps: float      # retorno medio con imbalance positivo − con negativo (confirmación)
    hasta_utc: pd.Timestamp    # último dato que usó el estudio
    ejecutado_utc: pd.Timestamp

    @property
    def signo(self) -> float:
        return math.copysign(1.0, self.diferencia_bps)

    def descripcion(self) -> str:
        return (f"hallazgo confirmado del estudio del {self.ejecutado_utc:%Y-%m-%d %H:%M} UTC: banda {self.banda_bps:g} "
                f"bps, horizonte {self.horizonte_rondas} rondas, diferencia {self.diferencia_bps:+.3f} bps")


def elegir_senal(estudios: pd.DataFrame, exchange: str, paso_s: float, antes_de: pd.Timestamp,
                 intervalo_s: float = INTERVALO_S) -> SenalImbalance | None:
    """De la ejecución más reciente del estudio cuyos datos terminaron antes de `antes_de`, el hallazgo confirmado
    de `exchange` con el horizonte más parecido a `paso_s` (a igualdad, el de mayor efecto). None si no hay."""
    if estudios.empty:
        return None
    fin = estudios.groupby("ejecutado_utc")["hasta_utc"].max()
    validas = fin[fin < antes_de].index
    candidatos = estudios[estudios["ejecutado_utc"].isin(validas) & (estudios["exchange"] == exchange)
                          & (estudios["estado"] == CONFIRMADA)]
    if candidatos.empty:
        return None
    ultima = candidatos["ejecutado_utc"].max()
    candidatos = candidatos[candidatos["ejecutado_utc"] == ultima]
    fila = min(candidatos.itertuples(), key=lambda f: (abs(f.horizonte_rondas * intervalo_s - paso_s),
                                                        -abs(f.diferencia_confirmacion)))
    return SenalImbalance(exchange, float(fila.banda_bps), int(fila.horizonte_rondas),
                          float(fila.diferencia_confirmacion), pd.Timestamp(fin[ultima]), pd.Timestamp(ultima))


def ejecutar_adaptativo(libros: list[Libro], importe_eur: float, trozos: int, duracion_s: float, urgencia: float,
                        senal: SenalImbalance, intensidad: float, decision_utc: pd.Timestamp, comision: float,
                        impacto_bps_por_100k: float = 0.0, estrategia: str = "",
                        tolerancia_s: float = TOLERANCIA_S) -> ResultadoEjecucion | None:
    """Almgren-Chriss con urgencia `urgencia`, adelantando o retrasando cada trozo según el imbalance del libro de
    ese momento en la banda de `senal`. Sin imbalance calculable (banda no cubierta), sigue el plan base."""
    if intensidad < 0:
        raise ValueError("La intensidad no puede ser negativa")
    base = plan_almgren_chriss(importe_eur, trozos, duracion_s, urgencia)
    pendiente_base = [sum(i for _, i in base[j:]) for j in range(len(base))]

    def politica(j: int, libro: Libro, pendiente: float) -> float:
        if j == len(base) - 1:
            return pendiente
        fraccion = base[j][1] / pendiente_base[j]
        imbalance = desequilibrio(libro, senal.banda_bps).imbalance
        if imbalance is not None:
            fraccion *= 1 + intensidad * imbalance * senal.signo
        return pendiente * min(max(fraccion, 0.0), 1.0)

    return ejecutar_politica(libros, [s for s, _ in base], politica, importe_eur, decision_utc, comision,
                             impacto_bps_por_100k, estrategia, tolerancia_s)
