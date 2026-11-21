"""Caso de uso: comparar estrategias de ejecución sobre muchas ventanas de libros reales.

Conceptos:
- Ventanas sin solaparse: la captura se parte en tramos de `duracion_s`; en cada uno se decide comprar al empezar
  y se simula cada estrategia. Muchas ventanas dan una DISTRIBUCIÓN del coste, no un solo número.
- Media y dispersión del shortfall: la media mide el coste esperado (lo que ahorra repartir la orden); la
  desviación típica mide el riesgo (lo que añade esperar). Es el dilema impacto frente a riesgo de timing, medido.
- Mismas ventanas para todas las estrategias: solo cuentan las ventanas en las que todas se pueden simular.
- Mínimo de ventanas: con pocas, no se concluye.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from radar.mercado import Libro

from .almgren_chriss import plan_almgren_chriss
from .simulador import ejecutar_plan, plan_todo_de_golpe, plan_twap

FUENTE_LIBROS, FUENTE_SIMULACIONES = "libros", "simulaciones_ejecucion"
GOLPE, TWAP, ALMGREN_CHRISS = "todo de golpe", "twap", "almgren-chriss"
MIN_VENTANAS = 10


def cargar_libros(consultar: Callable[[str], pd.DataFrame], exchange: str) -> list[Libro]:
    """Los libros guardados de un exchange, reconstruidos y ordenados en el tiempo."""
    filas = consultar(f"SELECT * FROM {FUENTE_LIBROS} WHERE exchange = '{exchange}' ORDER BY recibido_utc")
    return [Libro.desde_fila(f) for _, f in filas.iterrows()]


@dataclass(frozen=True)
class ResumenEstrategia:
    exchange: str
    estrategia: str
    importe_eur: float
    trozos: int
    duracion_s: float
    impacto_bps_por_100k: float
    shortfalls_bps: tuple
    temporal_bps: float
    impacto_bps: float
    timing_bps: float
    minimo: int

    @property
    def n(self) -> int:
        return len(self.shortfalls_bps)

    @property
    def media_bps(self) -> float:
        return statistics.fmean(self.shortfalls_bps) if self.n else math.nan

    @property
    def desviacion_bps(self) -> float:
        return statistics.stdev(self.shortfalls_bps) if self.n > 1 else math.nan

    def conclusion(self) -> str:
        importe = f"{self.importe_eur:,.0f}".replace(",", ".")
        cabecera = (f"{self.exchange}, {self.estrategia}, {importe} €"
                    + (f" en {self.trozos} trozos durante {self.duracion_s:g} s" if self.estrategia != GOLPE else "")
                    + f", impacto permanente {self.impacto_bps_por_100k:g} bps por 100.000 €")
        if self.n < self.minimo:
            return f"{cabecera}: datos insuficientes ({self.n} ventanas simulables; hacen falta {self.minimo})."
        return (f"{cabecera}: shortfall medio {self.media_bps:.2f} bps (desviación {self.desviacion_bps:.2f} bps) en "
                f"{self.n} ventanas, comisiones incluidas; desglose medio sin comisiones: temporal {self.temporal_bps:.2f}, "
                f"impacto {self.impacto_bps:.2f} y timing {self.timing_bps:+.2f} bps.")

    def a_fila(self) -> dict:
        return {"exchange": self.exchange, "estrategia": self.estrategia, "importe_eur": self.importe_eur,
                "trozos": self.trozos, "duracion_s": self.duracion_s, "impacto_bps_por_100k": self.impacto_bps_por_100k,
                "ventanas": self.n, "media_bps": self.media_bps, "desviacion_bps": self.desviacion_bps,
                "temporal_bps": self.temporal_bps, "impacto_bps": self.impacto_bps, "timing_bps": self.timing_bps,
                "conclusion": self.conclusion()}


def comparar_estrategias(libros: list[Libro], importe_eur: float, trozos: int, duracion_s: float, comision: float,
                         impactos=(0.0, 1.0, 5.0), minimo: int = MIN_VENTANAS, urgencias=()) -> list[ResumenEstrategia]:
    """Todo de golpe frente a TWAP en cada ventana de `duracion_s` que cabe entera en la captura, para cada
    valor de impacto permanente; con `urgencias`, también Almgren-Chriss con cada urgencia κT."""
    if not libros:
        return []
    ultimo, inicio = libros[-1].recibido_utc, libros[0].recibido_utc
    decisiones = []
    while inicio + pd.Timedelta(seconds=duracion_s) <= ultimo:
        decisiones.append(inicio)
        inicio += pd.Timedelta(seconds=duracion_s)
    planes = {GOLPE: plan_todo_de_golpe(importe_eur), TWAP: plan_twap(importe_eur, trozos, duracion_s)}
    for urgencia in urgencias:
        planes[f"{ALMGREN_CHRISS} κT={urgencia:g}"] = plan_almgren_chriss(importe_eur, trozos, duracion_s, urgencia)
    resumenes = []
    for impacto in impactos:
        # Solo cuentan las ventanas en las que TODAS las estrategias se pueden simular completas: compararlas en
        # ventanas distintas mezclaría la diferencia entre estrategias con la diferencia entre momentos.
        por_ventana = [{e: ejecutar_plan(libros, plan, d, comision, impacto, e) for e, plan in planes.items()}
                       for d in decisiones]
        comunes = [v for v in por_ventana if all(r is not None and r.completa for r in v.values())]
        for estrategia in planes:
            resultados = [v[estrategia] for v in comunes]

            def media(f):
                return statistics.fmean(f(r) / (r.cantidad_btc * r.mid_decision) * 10_000 for r in resultados) \
                    if resultados else math.nan

            resumenes.append(ResumenEstrategia(
                libros[0].exchange, estrategia, importe_eur, trozos, duracion_s, impacto,
                tuple(r.shortfall_bps for r in resultados), media(lambda r: r.coste_temporal_eur),
                media(lambda r: r.coste_impacto_eur), media(lambda r: r.coste_timing_eur), minimo))
    return resumenes


def comparar_texto(resumenes: list[ResumenEstrategia]) -> list[str]:
    """Una frase por impacto y estrategia: cuánto ahorra de media frente a todo de golpe y cuánto riesgo añade."""
    frases = []
    por_impacto = {}
    for r in resumenes:
        por_impacto.setdefault(r.impacto_bps_por_100k, {})[r.estrategia] = r
    for impacto, por_estrategia in por_impacto.items():
        golpe = por_estrategia.get(GOLPE)
        for estrategia, otra in por_estrategia.items():
            if estrategia == GOLPE:
                continue
            nombre = "TWAP" if estrategia == TWAP else estrategia
            if not golpe or min(golpe.n, otra.n) < golpe.minimo:
                frases.append(f"Impacto {impacto:g} bps por 100.000 €: datos insuficientes para comparar {nombre}.")
                continue
            ahorro, riesgo = golpe.media_bps - otra.media_bps, otra.desviacion_bps - golpe.desviacion_bps
            mejor = nombre if ahorro > 0 else "todo de golpe"
            frases.append(f"Impacto {impacto:g} bps por 100.000 €: {nombre} cuesta {abs(ahorro):.2f} bps "
                          f"{'menos' if ahorro > 0 else 'más'} de media que todo de golpe, con una desviación "
                          f"{abs(riesgo):.2f} bps {'mayor' if riesgo > 0 else 'menor'}; más barato de media: {mejor}.")
    return frases
