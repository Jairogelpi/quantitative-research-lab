"""Simulador de ejecución sobre libros reales (Fase 8 · Economía de la ejecución).

Conceptos:
- Plan de ejecución: cuándo y cuánto se compra. Todo de golpe = un único trozo al empezar. TWAP (Time-Weighted
  Average Price) = trozos iguales repartidos a intervalos fijos durante `duracion_s`.
- Replay: cada trozo barre el libro GUARDADO más cercano a su momento (`libros` del lake). Supone, sin decirlo,
  que nuestras compras no cambian el libro: los asks que nos comimos vuelven a estar en la foto siguiente.
- Impacto permanente: el precio queda más arriba después de comprar. No se puede medir sin trades (Fase 3), así que
  es un PARÁMETRO (bps por cada 100.000 € ya ejecutados) y se estudia su sensibilidad, sin inventar un valor.
- Mid de decisión: el mid en el instante en que se decide comprar; la referencia de todo el coste.
- Implementation shortfall: lo pagado (con comisiones) − cantidad × mid de decisión. Se reparte en cuatro piezas:
  · temporal (spread + slippage): lo pagado de más frente al mid del libro en el que se ejecutó cada trozo;
  · impacto permanente: lo que el precio subió por nuestras propias compras anteriores (según el parámetro);
  · timing: lo que se movió el mercado entre la decisión y cada trozo (riesgo de esperar);
  · comisiones.
- Ejecución no simulable: si algún trozo no tiene una foto del libro a menos de `tolerancia_s`, no se simula
  (no se inventa el libro que faltaba).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

import pandas as pd

from radar.mercado import Ejecucion, Libro, Nivel, barrer_compra

TOLERANCIA_S = 5.0


def desplazar(libro: Libro, bps: float) -> Libro:
    """El mismo libro con todos los precios multiplicados por (1 + bps / 10.000): el efecto del impacto permanente."""
    factor = 1 + bps / 10_000
    return Libro(libro.exchange, libro.par, tuple(Nivel(n.precio * factor, n.cantidad) for n in libro.bids),
                 tuple(Nivel(n.precio * factor, n.cantidad) for n in libro.asks), libro.solicitado_utc,
                 libro.recibido_utc, libro.hora_exchange_utc)


def plan_todo_de_golpe(importe_eur: float) -> list[tuple[float, float]]:
    """[(segundos desde la decisión, importe)]: un único trozo al empezar."""
    return [(0.0, importe_eur)]


def plan_twap(importe_eur: float, trozos: int, duracion_s: float) -> list[tuple[float, float]]:
    """`trozos` iguales, uno cada `duracion_s / trozos` segundos, empezando en la decisión."""
    if trozos < 1 or duracion_s <= 0:
        raise ValueError("Hace falta al menos un trozo y una duración positiva")
    paso = duracion_s / trozos
    return [(i * paso, importe_eur / trozos) for i in range(trozos)]


@dataclass(frozen=True)
class Trozo:
    objetivo_utc: pd.Timestamp
    mid_capturado: float   # mid del libro guardado
    impacto_bps: float     # desplazamiento por nuestras compras anteriores
    ejecucion: Ejecucion

    @property
    def mid_ejecucion(self) -> float:
        return self.mid_capturado * (1 + self.impacto_bps / 10_000)


@dataclass(frozen=True)
class ResultadoEjecucion:
    estrategia: str
    exchange: str
    decision_utc: pd.Timestamp
    mid_decision: float
    comision: float
    trozos: tuple

    @property
    def cantidad_btc(self) -> float:
        return sum(t.ejecucion.cantidad_btc for t in self.trozos)

    @property
    def importe_eur(self) -> float:
        return sum(t.ejecucion.importe_eur for t in self.trozos)

    @property
    def completa(self) -> bool:
        return all(t.ejecucion.completa for t in self.trozos)

    @property
    def coste_temporal_eur(self) -> float:
        return sum(t.ejecucion.importe_eur - t.ejecucion.cantidad_btc * t.mid_ejecucion for t in self.trozos)

    @property
    def coste_impacto_eur(self) -> float:
        return sum(t.ejecucion.cantidad_btc * (t.mid_ejecucion - t.mid_capturado) for t in self.trozos)

    @property
    def coste_timing_eur(self) -> float:
        return sum(t.ejecucion.cantidad_btc * (t.mid_capturado - self.mid_decision) for t in self.trozos)

    @property
    def comisiones_eur(self) -> float:
        return self.importe_eur * self.comision

    @property
    def shortfall_eur(self) -> float:
        return self.importe_eur + self.comisiones_eur - self.cantidad_btc * self.mid_decision

    @property
    def shortfall_bps(self) -> float:
        return self.shortfall_eur / (self.cantidad_btc * self.mid_decision) * 10_000


def _libro_en(libros: list[Libro], momento: pd.Timestamp, tolerancia_s: float) -> Libro | None:
    """Primera foto en o después de `momento`, si llega a menos de `tolerancia_s` (búsqueda binaria)."""
    i = bisect.bisect_left(libros, momento, key=lambda l: l.recibido_utc)
    if i == len(libros) or (libros[i].recibido_utc - momento).total_seconds() > tolerancia_s:
        return None
    return libros[i]


def ejecutar_plan(libros: list[Libro], plan, decision_utc: pd.Timestamp, comision: float,
                  impacto_bps_por_100k: float = 0.0, estrategia: str = "", tolerancia_s: float = TOLERANCIA_S
                  ) -> ResultadoEjecucion | None:
    """Ejecuta `plan` (compra) sobre los libros guardados (ordenados en el tiempo). None si falta alguna foto."""
    return ejecutar_politica(libros, [s for s, _ in plan], lambda j, libro, pendiente: plan[j][1],
                             sum(i for _, i in plan), decision_utc, comision, impacto_bps_por_100k, estrategia,
                             tolerancia_s)


def ejecutar_politica(libros: list[Libro], segundos, politica, importe_eur: float, decision_utc: pd.Timestamp,
                      comision: float, impacto_bps_por_100k: float = 0.0, estrategia: str = "",
                      tolerancia_s: float = TOLERANCIA_S) -> ResultadoEjecucion | None:
    """Como `ejecutar_plan`, pero el importe del trozo j lo decide `politica(j, libro, pendiente_eur)` mirando el
    libro de ese momento (ejecución adaptativa). Un importe 0 no compra en ese trozo."""
    inicial = _libro_en(libros, decision_utc, tolerancia_s)
    if inicial is None:
        return None
    trozos, ejecutado = [], 0.0
    for j, s in enumerate(segundos):
        momento = decision_utc + pd.Timedelta(seconds=s)
        libro = _libro_en(libros, momento, tolerancia_s)
        if libro is None:
            return None
        importe = politica(j, libro, importe_eur - ejecutado)
        if importe <= importe_eur * 1e-12:
            continue
        impacto = impacto_bps_por_100k * ejecutado / 100_000
        trozos.append(Trozo(momento, libro.mejor_nivel().mid, impacto, barrer_compra(desplazar(libro, impacto), importe)))
        ejecutado += importe
    return ResultadoEjecucion(estrategia, inicial.exchange, decision_utc, inicial.mejor_nivel().mid, comision,
                              tuple(trozos))
