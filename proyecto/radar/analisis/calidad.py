"""Puerta de calidad de los datos: antes de concluir, comprobar que la captura es fiable.

Conceptos:
- Hueco: dos fotos seguidas de un exchange separadas más de `FACTOR_HUECO` × intervalo, dentro de una misma
  sesión de captura. Una separación de más de `SESION_S` es otra sesión (el capturador estaba parado), no un hueco.
- Tasa de errores: errores registrados / (rondas válidas + errores).
- Latencia p99: el 99 % de las respuestas tardó menos que esto. Latencias altas desfasan las fotos entre sí.
- Si un exchange no pasa la puerta, su estudio no concluye ("calidad de datos insuficiente"): mejor no decir
  nada que decir algo falso con datos rotos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from radar.configuracion import INTERVALO_S

FACTOR_HUECO = 3
SESION_S = 60
MAX_HUECOS = 0.05
MAX_ERRORES = 0.05
MAX_LATENCIA_P99_S = 3.0


@dataclass(frozen=True)
class Calidad:
    exchange: str
    rondas: int
    huecos: int
    errores: int
    latencia_p99_s: float

    @property
    def fraccion_huecos(self) -> float:
        return self.huecos / self.rondas if self.rondas else 1.0

    @property
    def fraccion_errores(self) -> float:
        total = self.rondas + self.errores
        return self.errores / total if total else 1.0

    @property
    def motivo(self) -> str:
        """Por qué no pasa (vacío si pasa)."""
        fallos = []
        if self.fraccion_huecos > MAX_HUECOS:
            fallos.append(f"huecos {self.fraccion_huecos * 100:.1f} %")
        if self.fraccion_errores > MAX_ERRORES:
            fallos.append(f"errores {self.fraccion_errores * 100:.1f} %")
        if self.latencia_p99_s > MAX_LATENCIA_P99_S:
            fallos.append(f"latencia p99 {self.latencia_p99_s:.2f} s")
        return ", ".join(fallos)

    @property
    def pasa(self) -> bool:
        return not self.motivo


def evaluar_calidad(consultar: Callable[[str], pd.DataFrame], fuentes, intervalo_s: float = INTERVALO_S) -> dict:
    """Calidad de cada exchange en todo el lake. `fuentes`: las que existen (puede no haber `errores_captura`)."""
    cotizaciones = consultar(f"""
        WITH s AS (
            SELECT exchange, latencia_s,
                   epoch(recibido_utc) - epoch(lag(recibido_utc) OVER (PARTITION BY exchange ORDER BY recibido_utc)) AS paso
            FROM cotizaciones)
        SELECT exchange, count(*) AS rondas,
               count(*) FILTER (WHERE paso > {FACTOR_HUECO * intervalo_s} AND paso <= {SESION_S}) AS huecos,
               quantile_cont(latencia_s, 0.99) AS latencia_p99_s
        FROM s GROUP BY exchange""")
    errores = {}
    if "errores_captura" in fuentes:
        errores = dict(consultar("SELECT exchange, count(*) AS n FROM errores_captura GROUP BY exchange")
                       .itertuples(index=False))
    return {f.exchange: Calidad(f.exchange, int(f.rondas), int(f.huecos), int(errores.get(f.exchange, 0)),
                                float(f.latencia_p99_s)) for f in cotizaciones.itertuples(index=False)}
