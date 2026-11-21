"""Ejecución (Fase 8): simular cómo comprar una cantidad grande sobre los libros reales guardados y comparar
estrategias (todo de golpe, TWAP, Almgren-Chriss) por su implementation shortfall."""

from .almgren_chriss import aversion_implicita, estimar_impacto_temporal, estimar_volatilidad, plan_almgren_chriss
from .replay import (ALMGREN_CHRISS, FUENTE_SIMULACIONES, GOLPE, TWAP, ResumenEstrategia, cargar_libros,
                     comparar_estrategias, comparar_texto)
from .simulador import ResultadoEjecucion, Trozo, desplazar, ejecutar_plan, plan_todo_de_golpe, plan_twap

__all__ = ["ALMGREN_CHRISS", "FUENTE_SIMULACIONES", "GOLPE", "TWAP", "ResultadoEjecucion", "ResumenEstrategia", "Trozo",
           "aversion_implicita", "cargar_libros", "comparar_estrategias", "comparar_texto", "desplazar",
           "ejecutar_plan", "estimar_impacto_temporal", "estimar_volatilidad", "plan_almgren_chriss",
           "plan_todo_de_golpe", "plan_twap"]
