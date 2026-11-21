"""Almgren-Chriss (2001): el plan óptimo entre impacto temporal y riesgo de timing (Fase 8).

Conceptos:
- Lo pendiente de comprar en t es x(t) = X · sinh(κ(T − t)) / sinh(κT), con κ = √(λ · σ² / η).
- σ²: varianza del precio por segundo (€²/s): el riesgo de esperar (`estimar_volatilidad`).
- η: impacto temporal (€ · s / BTC²): cuánto encarece comprar más deprisa; η = k · τ, con k la pendiente de la
  curva de slippage (`estimar_impacto_temporal`) y τ la duración de cada trozo.
- λ: aversión al riesgo (1/€). λ = 0 → κ = 0 → x(t) es una recta: TWAP. λ → ∞ → todo al principio.
- Urgencia κT: el plan solo depende de κ · T, adimensional e intuitivo (0 = TWAP; 1 = algo cargado al inicio;
  3 = bastante cargado). `aversion_implicita` traduce cada urgencia a la λ que supone con los σ² y k medidos.
- Supuestos del modelo: impacto temporal lineal en la velocidad y precio como paseo aleatorio sin tendencia.
"""

from __future__ import annotations

import math
import statistics

from radar.mercado import Libro, barrer_compra

from .simulador import TOLERANCIA_S, plan_twap


def _fraccion_pendiente(urgencia: float, fraccion_restante: float) -> float:
    """sinh(κT · f) / sinh(κT), escrito para no desbordar con urgencias grandes."""
    a, b = urgencia * fraccion_restante, urgencia
    return math.exp(a - b) * (1 - math.exp(-2 * a)) / (1 - math.exp(-2 * b))


def plan_almgren_chriss(importe_eur: float, trozos: int, duracion_s: float, urgencia: float) -> list[tuple[float, float]]:
    """Trozo j al empezar su tramo (j · τ): lo que baja lo pendiente entre j y j + 1. Urgencia 0 = TWAP."""
    if urgencia < 0:
        raise ValueError("La urgencia no puede ser negativa")
    if urgencia == 0:
        return plan_twap(importe_eur, trozos, duracion_s)
    if trozos < 1 or duracion_s <= 0:
        raise ValueError("Hace falta al menos un trozo y una duración positiva")
    paso = duracion_s / trozos
    pendiente = [_fraccion_pendiente(urgencia, 1 - j / trozos) for j in range(trozos)] + [0.0]
    return [(j * paso, importe_eur * (pendiente[j] - pendiente[j + 1])) for j in range(trozos)]


def estimar_volatilidad(libros: list[Libro], max_paso_s: float = TOLERANCIA_S) -> float:
    """σ² en €²/s: media de (Δmid)² / Δt entre fotos seguidas separadas como mucho `max_paso_s`."""
    muestras = []
    for a, b in zip(libros, libros[1:]):
        dt = (b.recibido_utc - a.recibido_utc).total_seconds()
        if 0 < dt <= max_paso_s:
            muestras.append((b.mejor_nivel().mid - a.mejor_nivel().mid) ** 2 / dt)
    return statistics.fmean(muestras) if muestras else math.nan


def estimar_impacto_temporal(libros: list[Libro], cantidades_btc=(0.5, 1, 2)) -> float:
    """k en € por BTC y por BTC comprado de golpe: (precio medio − mejor ask) ≈ k · cantidad. Recta por el origen
    en cada libro y mediana entre libros (robusta a fotos raras)."""
    pendientes = []
    for libro in libros:
        ask = libro.asks[0].precio
        puntos = [barrer_compra(libro, q * ask) for q in cantidades_btc]
        puntos = [(e.cantidad_btc, e.precio_medio - ask) for e in puntos if e.completa]
        denominador = sum(q * q for q, _ in puntos)
        if denominador:
            pendientes.append(sum(q * c for q, c in puntos) / denominador)
    return statistics.median(pendientes) if pendientes else math.nan


def aversion_implicita(urgencia: float, duracion_s: float, trozos: int, sigma2: float, k: float) -> float:
    """λ = κ² · η / σ², con κ = urgencia / T y η = k · τ. En 1/€."""
    kappa, eta = urgencia / duracion_s, k * duracion_s / trozos
    return kappa ** 2 * eta / sigma2 if sigma2 > 0 else math.nan
