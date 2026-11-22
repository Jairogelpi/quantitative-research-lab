"""Estacionalidad intradía: cómo cambian el spread y la profundidad según la hora del día (Fases 1 y 2).

Conceptos:
- Perfil horario: para cada exchange y hora UTC (0–23), la mediana y el percentil 90 del spread en bps y la
  mediana de la profundidad (BTC en bids + asks dentro de una banda de bps alrededor del mid).
- La unidad es el DÍA, no la ronda: dentro de una misma hora las rondas seguidas se parecen mucho (no son
  independientes). Se resume cada (día, hora) con su mediana y se comparan las horas usando los días como
  repeticiones. Así el efecto de la hora no se confunde con lo que pasó un día concreto.
- Prueba de Kruskal-Wallis: ¿las medianas diarias de las distintas horas vienen de la misma distribución? No
  supone normalidad (los spreads son muy asimétricos).
- Mínimo de días: con menos de `MIN_DIAS` días distintos por hora no se concluye nada sobre la hora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd
from scipy.stats import kruskal

FUENTE_PERFILES = "perfiles_horarios"
MIN_DIAS = 5
MIN_HORAS = 2
ALFA = 0.05
BANDA_BPS = 10


def perfil_horario(consultar: Callable[[str], pd.DataFrame], banda_bps: float = BANDA_BPS) -> pd.DataFrame:
    """Una fila por (exchange, hora UTC): días y rondas observados, spread (mediana y p90, bps) y profundidad
    mediana en la banda (BTC). Las medianas son de las medianas diarias (cada día pesa lo mismo)."""
    diario = medianas_diarias(consultar, banda_bps)
    if diario.empty:
        return diario
    return (diario.groupby(["exchange", "hora_utc"], as_index=False)
            .agg(dias=("fecha", "nunique"), rondas=("rondas", "sum"), spread_mediana_bps=("spread_bps", "median"),
                 spread_p90_bps=("spread_p90_bps", "median"), profundidad_btc=("profundidad_btc", "median"))
            .assign(banda_bps=banda_bps))


def medianas_diarias(consultar: Callable[[str], pd.DataFrame], banda_bps: float = BANDA_BPS) -> pd.DataFrame:
    """Una fila por (exchange, fecha, hora UTC) con la mediana del spread, su p90 y la profundidad mediana."""
    return consultar(f"""
        WITH c AS (
            SELECT exchange, recibido_utc, spread_bps FROM cotizaciones),
        d AS (
            SELECT exchange, recibido_utc, cantidad_bids + cantidad_asks AS profundidad_btc
            FROM desequilibrios WHERE banda_bps = {float(banda_bps)} AND cubierta)
        SELECT c.exchange, CAST(timezone('UTC', c.recibido_utc) AS DATE) AS fecha,
               hour(timezone('UTC', c.recibido_utc)) AS hora_utc, count(*) AS rondas,
               median(c.spread_bps) AS spread_bps, quantile_cont(c.spread_bps, 0.9) AS spread_p90_bps,
               median(d.profundidad_btc) AS profundidad_btc
        FROM c LEFT JOIN d USING (exchange, recibido_utc)  -- la ronda se reinicia en cada captura
        GROUP BY ALL ORDER BY exchange, fecha, hora_utc""")


@dataclass(frozen=True)
class EfectoHora:
    exchange: str
    variable: str            # "spread_bps" o "profundidad_btc"
    horas_validas: int       # horas con al menos `MIN_DIAS` días
    dias: int                # días distintos observados
    estadistico: float | None
    p_valor: float | None
    hora_maxima: int | None
    hora_minima: int | None
    valor_maximo: float | None
    valor_minimo: float | None

    @property
    def estado(self) -> str:
        if self.p_valor is None:
            return "datos insuficientes"
        return "depende de la hora" if self.p_valor < ALFA else "sin evidencia"

    def conclusion(self) -> str:
        nombre = "el spread" if self.variable == "spread_bps" else "la profundidad"
        unidad = "bps" if self.variable == "spread_bps" else "BTC"
        if self.p_valor is None:
            return (f"{self.exchange}: datos insuficientes para saber si {nombre} depende de la hora "
                    f"({self.dias} días; hacen falta al menos {MIN_DIAS} días en {MIN_HORAS} horas distintas).")
        extremos = (f"máxima a las {self.hora_maxima} h UTC ({self.valor_maximo:.3f} {unidad}), mínima a las "
                    f"{self.hora_minima} h ({self.valor_minimo:.3f} {unidad})")
        if self.estado == "depende de la hora":
            return f"{self.exchange}: {nombre} depende de la hora (Kruskal-Wallis p = {self.p_valor:.4f}); {extremos}."
        return (f"{self.exchange}: sin evidencia de que {nombre} dependa de la hora (p = {self.p_valor:.3f}, "
                f"{self.horas_validas} horas con {MIN_DIAS}+ días).")

    def a_fila(self) -> dict:
        return {**self.__dict__, "estado": self.estado, "conclusion": self.conclusion()}


def efecto_hora(diario: pd.DataFrame, variable: str, min_dias: int = MIN_DIAS) -> list[EfectoHora]:
    """Para cada exchange, Kruskal-Wallis de las medianas diarias de `variable` entre horas con `min_dias`+ días."""
    efectos = []
    for exchange, g in diario.dropna(subset=[variable]).groupby("exchange"):
        dias_por_hora = g.groupby("hora_utc")["fecha"].nunique()
        validas = dias_por_hora[dias_por_hora >= min_dias].index
        grupos = [g.loc[g["hora_utc"] == h, variable].to_numpy() for h in validas]
        dias = int(g["fecha"].nunique())
        if len(grupos) < MIN_HORAS or g.loc[g["hora_utc"].isin(validas), variable].nunique() < 2:
            efectos.append(EfectoHora(exchange, variable, len(validas), dias, None, None, None, None, None, None))
            continue
        estadistico, p = kruskal(*grupos)
        medianas = g[g["hora_utc"].isin(validas)].groupby("hora_utc")[variable].median()
        efectos.append(EfectoHora(exchange, variable, len(validas), dias, float(estadistico), float(p),
                                  int(medianas.idxmax()), int(medianas.idxmin()), float(medianas.max()),
                                  float(medianas.min())))
    return efectos
