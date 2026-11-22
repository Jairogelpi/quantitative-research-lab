"""Ejecución (Fase 8): simular cómo comprar una cantidad grande sobre los libros reales guardados y comparar
estrategias (todo de golpe, TWAP, Almgren-Chriss y Almgren-Chriss adaptativo con la señal de imbalance) por su
implementation shortfall."""

from .adaptativo import SenalImbalance, ejecutar_adaptativo, elegir_senal
from .almgren_chriss import aversion_implicita, estimar_impacto_temporal, estimar_volatilidad, plan_almgren_chriss
from .replay import (ADAPTATIVO, ALMGREN_CHRISS, FUENTE_SIMULACIONES, GOLPE, TWAP, ResumenEstrategia, cargar_libros,
                     comparar_estrategias, comparar_texto)
from .simulador import (ResultadoEjecucion, Trozo, desplazar, ejecutar_plan, ejecutar_politica, plan_todo_de_golpe,
                        plan_twap)

__all__ = ["ADAPTATIVO", "ALMGREN_CHRISS", "SenalImbalance", "ejecutar_adaptativo", "ejecutar_politica",
           "elegir_senal", "FUENTE_SIMULACIONES", "GOLPE", "TWAP", "ResultadoEjecucion", "ResumenEstrategia", "Trozo",
           "aversion_implicita", "cargar_libros", "comparar_estrategias", "comparar_texto", "desplazar",
           "ejecutar_plan", "estimar_impacto_temporal", "estimar_volatilidad", "plan_almgren_chriss",
           "plan_todo_de_golpe", "plan_twap"]
