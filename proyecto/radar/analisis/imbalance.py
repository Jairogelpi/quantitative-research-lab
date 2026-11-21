"""¿Anticipa el desequilibrio del libro el movimiento del precio? (Fase 2; base de las fases 5 y 8).

Conceptos:
- Retorno futuro (forward return): (mid dentro de k rondas / mid ahora − 1) en bps. Es lo que el imbalance de
  AHORA pretende anticipar. Solo se usa el futuro para evaluar, nunca para calcular la señal.
- Horizonte y decaimiento: el estudio se repite con varios k (1, 5, 10, 30 rondas). Cómo cambia la relación
  con k dice cuánto dura la señal. Si entre las dos fotos pasó mucho más tiempo del esperado (otra captura,
  un corte), el par se descarta.
- Media condicionada: retorno medio con imbalance positivo frente a negativo; su diferencia es la del estudio.
- Errores Newey-West (HAC): rondas seguidas tienen imbalances casi iguales y, con k > 1, retornos que se
  solapan; no son observaciones independientes y el error estándar ingenuo sale demasiado pequeño (t inflado).
  Newey-West corrige el error estándar por esa autocorrelación.
- Descubrimiento y confirmación (fuera de muestra): la primera mitad en el tiempo descubre, la segunda
  confirma. Una relación que no se repite en datos que no se usaron para encontrarla no vale.
- Pruebas múltiples y Benjamini-Hochberg: con muchas combinaciones (exchange × banda × horizonte), alguna
  sale "clara" por azar. BH ajusta los p-valores para controlar la proporción de falsos descubrimientos.
- Information Coefficient (IC): correlación de rangos (Spearman) entre imbalance y retorno futuro. Usa todo el
  imbalance, no solo su signo. Quintiles: retorno medio de cada quinto del imbalance; monótonos si suben (o
  bajan) de forma ordenada, lo que indica una relación consistente y no un efecto de unos pocos extremos.
- Significación económica: el movimiento anticipado frente al punto de equilibrio de un taker. Una relación
  confirmada puede ser demasiado pequeña para ganar dinero tomando liquidez.

Estados de cada estudio:
- datos insuficientes: menos de `min_por_grupo` rondas con imbalance positivo o negativo en alguna mitad.
- sin evidencia: la diferencia del descubrimiento no es significativa tras Benjamini-Hochberg.
- no confirmada fuera de muestra: significativa al descubrirla, pero en la confirmación no tiene el mismo
  signo con |t| ≥ 2.
- confirmada: significativa al descubrirla y repetida en la confirmación.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from radar.configuracion import INTERVALO_S

METODO = "imbalance_retorno/v2"
FUENTE_ESTUDIOS = "estudios"
HORIZONTES = (1, 5, 10, 30)
MIN_POR_GRUPO = 200
ALFA = 0.05          # tasa de falsos descubrimientos tolerada (Benjamini-Hochberg)
T_CONFIRMACION = 2.0
MARGEN_S = 2.0       # tiempo extra tolerado sobre horizonte × intervalo

INSUFICIENTE, SIN_EVIDENCIA = "datos insuficientes", "sin evidencia"
NO_CONFIRMADA, CONFIRMADA = "no confirmada fuera de muestra", "confirmada"


@dataclass(frozen=True)
class ResultadoImbalance:
    exchange: str
    banda_bps: float
    horizonte_rondas: int
    desde_utc: pd.Timestamp
    corte_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    min_por_grupo: int
    n_minimo_positivo: int
    n_minimo_negativo: int
    diferencia_descubrimiento: float
    t_descubrimiento: float
    p_descubrimiento: float
    p_ajustado: float
    diferencia_confirmacion: float
    t_confirmacion: float
    ret_positivo_confirmacion: float
    ret_negativo_confirmacion: float
    ic: float
    quintiles: list
    equilibrio_bps: float | None

    @property
    def suficiente(self) -> bool:
        return min(self.n_minimo_positivo, self.n_minimo_negativo) >= self.min_por_grupo

    @property
    def estado(self) -> str:
        if not self.suficiente:
            return INSUFICIENTE
        if not self.p_ajustado < ALFA:
            return SIN_EVIDENCIA
        mismo_signo = np.sign(self.diferencia_confirmacion) == np.sign(self.diferencia_descubrimiento)
        return CONFIRMADA if mismo_signo and abs(self.t_confirmacion) >= T_CONFIRMACION else NO_CONFIRMADA

    @property
    def monotona(self) -> bool:
        pasos = np.diff(self.quintiles)
        return len(self.quintiles) == 5 and (bool(np.all(pasos > 0)) or bool(np.all(pasos < 0)))

    @property
    def movimiento_bps(self) -> float:
        """Lo que se anticipa a favor: el mayor de los dos retornos medios condicionados, en la confirmación."""
        return max(abs(self.ret_positivo_confirmacion), abs(self.ret_negativo_confirmacion))

    @property
    def rentable_taker(self) -> bool | None:
        """None si no se dio el equilibrio o la relación no está confirmada."""
        if self.equilibrio_bps is None or self.estado != CONFIRMADA:
            return None
        return self.movimiento_bps > self.equilibrio_bps

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, banda {self.banda_bps:g} bps, horizonte {self.horizonte_rondas}"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes (hacen falta {self.min_por_grupo} rondas con imbalance positivo y "
                    f"{self.min_por_grupo} con negativo en cada mitad; hay {self.n_minimo_positivo} y "
                    f"{self.n_minimo_negativo} en la mitad menor).")
        texto = (f"{cabecera}: {self.estado}. IC {self.ic:+.3f}; descubrimiento: diferencia "
                 f"{self.diferencia_descubrimiento:+.3f} bps (t HAC {self.t_descubrimiento:.2f}, p ajustado "
                 f"{self.p_ajustado:.3f}); confirmación: diferencia {self.diferencia_confirmacion:+.3f} bps "
                 f"(t HAC {self.t_confirmacion:.2f}); quintiles {'monótonos' if self.monotona else 'no monótonos'}.")
        if self.rentable_taker is not None:
            veredicto = "rentable para un taker" if self.rentable_taker else "no rentable para un taker"
            texto += (f" Anticipa {self.movimiento_bps:.3f} bps frente a un equilibrio taker de "
                      f"{self.equilibrio_bps:.1f} bps: {veredicto}.")
        return texto

    def a_fila(self) -> dict:
        fila = {k: v for k, v in asdict(self).items() if k != "quintiles"}
        fila.update({f"q{i + 1}": (self.quintiles[i] if i < len(self.quintiles) else math.nan) for i in range(5)})
        fila.update({"estado": self.estado, "monotona": self.monotona, "movimiento_bps": self.movimiento_bps,
                     "rentable_taker": self.rentable_taker, "conclusion": self.conclusion()})
        return fila


def _diferencia_hac(g: pd.DataFrame, horizonte: int) -> tuple[float, float, int, int]:
    """Diferencia de medias (positivo − negativo) y su t con errores Newey-West. Filas en orden temporal.

    Regresión ret = a + b · [imbalance > 0]: b es la diferencia de medias. Retardos: el mayor entre el
    horizonte (solapamiento de retornos) y la regla de Newey-West 4 · (n / 100)^(2/9).
    """
    g = g[g.imbalance != 0]
    positivo = (g.imbalance > 0).astype(float).to_numpy()
    n_pos, n_neg = int(positivo.sum()), int(len(g) - positivo.sum())
    if min(n_pos, n_neg) < 2:
        return math.nan, math.nan, n_pos, n_neg
    retardos = max(horizonte, int(4 * (len(g) / 100) ** (2 / 9)))
    ajuste = sm.OLS(g.ret_bps.to_numpy(), sm.add_constant(positivo)).fit(cov_type="HAC", cov_kwds={"maxlags": retardos})
    diferencia, error = float(ajuste.params[1]), float(ajuste.bse[1])
    if error == 0 or not math.isfinite(error):  # sin ruido: o no hay diferencia, o es infinitamente clara
        return diferencia, (0.0 if diferencia == 0 else math.copysign(math.inf, diferencia)), n_pos, n_neg
    return diferencia, diferencia / error, n_pos, n_neg


def _p_valor(t: float) -> float:
    """p-valor bilateral de un t con la aproximación normal (válida con cientos de observaciones)."""
    if math.isnan(t):
        return math.nan
    return math.erfc(abs(t) / math.sqrt(2))  # erfc(∞) = 0


def _quintiles(g: pd.DataFrame) -> list:
    try:
        grupo = pd.qcut(g.imbalance, 5, labels=False)
    except ValueError:  # pocos valores distintos: no hay cinco quintiles
        return []
    return [float(m) for m in g.ret_bps.groupby(grupo).mean().sort_index()]


def estudiar_imbalance(pares: pd.DataFrame, min_por_grupo: int = MIN_POR_GRUPO,
                       equilibrio_bps: dict | None = None) -> list[ResultadoImbalance]:
    """Un resultado por exchange, banda y horizonte. `pares`: exchange, banda_bps, horizonte_rondas,
    recibido_utc, imbalance, ret_bps. Benjamini-Hochberg se aplica a todas las pruebas con datos suficientes."""
    borradores = []
    for (exchange, banda, horizonte), g in pares.groupby(["exchange", "banda_bps", "horizonte_rondas"], sort=True):
        g = g.sort_values("recibido_utc")
        mitad = len(g) // 2
        descubrimiento, confirmacion = g.iloc[:mitad], g.iloc[mitad:]
        d1, t1, p1, n1 = _diferencia_hac(descubrimiento, horizonte)
        d2, t2, p2, n2 = _diferencia_hac(confirmacion, horizonte)
        conf = confirmacion[confirmacion.imbalance != 0]
        borradores.append(dict(
            exchange=exchange, banda_bps=banda, horizonte_rondas=int(horizonte),
            desde_utc=g.recibido_utc.iloc[0], corte_utc=confirmacion.recibido_utc.iloc[0] if len(confirmacion) else pd.NaT,
            hasta_utc=g.recibido_utc.iloc[-1], min_por_grupo=min_por_grupo,
            n_minimo_positivo=min(p1, p2), n_minimo_negativo=min(n1, n2),
            diferencia_descubrimiento=d1, t_descubrimiento=t1,
            p_descubrimiento=_p_valor(t1),
            diferencia_confirmacion=d2, t_confirmacion=t2,
            ret_positivo_confirmacion=float(conf.ret_bps[conf.imbalance > 0].mean()) if len(conf) else math.nan,
            ret_negativo_confirmacion=float(conf.ret_bps[conf.imbalance < 0].mean()) if len(conf) else math.nan,
            ic=float(g.imbalance.corr(g.ret_bps, method="spearman")) if len(g) > 2 else math.nan,
            quintiles=_quintiles(g), equilibrio_bps=(equilibrio_bps or {}).get(exchange)))

    validos = [i for i, b in enumerate(borradores)
               if min(b["n_minimo_positivo"], b["n_minimo_negativo"]) >= min_por_grupo and not math.isnan(b["p_descubrimiento"])]
    ajustados = multipletests([borradores[i]["p_descubrimiento"] for i in validos], method="fdr_bh")[1] if validos else []
    p_ajustado = dict(zip(validos, ajustados))
    return [ResultadoImbalance(**b, p_ajustado=float(p_ajustado.get(i, math.nan))) for i, b in enumerate(borradores)]


def guardar_estudio(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución del estudio en la fuente `estudios`: una fila por resultado, con método y parámetros."""
    return almacen.guardar([{"estudio": "imbalance_retorno", "metodo": METODO, "ejecutado_utc": ejecutado_utc,
                             "recibido_utc": ejecutado_utc, **r.a_fila()} for r in resultados], FUENTE_ESTUDIOS)


def leer_ultimo_estudio(consultar: Callable[[str], pd.DataFrame], metodo: str = METODO) -> pd.DataFrame:
    """La última ejecución guardada del estudio: lo que otras fases (señales, ejecución) deben reutilizar."""
    return consultar(f"""
        SELECT * FROM {FUENTE_ESTUDIOS}
        WHERE metodo = '{metodo}'
          AND ejecutado_utc = (SELECT max(ejecutado_utc) FROM {FUENTE_ESTUDIOS} WHERE metodo = '{metodo}')
        ORDER BY exchange, banda_bps, horizonte_rondas""")


def pares_imbalance_retorno(consultar: Callable[[str], pd.DataFrame], horizontes=HORIZONTES,
                            intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Une cada imbalance con el retorno del mid k rondas después, para cada k de `horizontes` (vía SQL)."""
    if not horizontes or min(horizontes) < 1:
        raise ValueError("Los horizontes deben ser de al menos 1 ronda")
    partes = []
    for k in horizontes:
        partes.append(consultar(f"""
            WITH m AS (
                SELECT exchange, recibido_utc, mid,
                       lead(mid, {k}) OVER w AS mid_futuro, lead(recibido_utc, {k}) OVER w AS t_futuro
                FROM cotizaciones WINDOW w AS (PARTITION BY exchange ORDER BY recibido_utc))
            SELECT d.exchange, d.banda_bps, {k} AS horizonte_rondas, d.recibido_utc, d.imbalance,
                   (m.mid_futuro / m.mid - 1) * 1e4 AS ret_bps
            FROM desequilibrios d JOIN m USING (exchange, recibido_utc)
            WHERE d.imbalance IS NOT NULL AND m.mid_futuro IS NOT NULL
              AND epoch(m.t_futuro) - epoch(m.recibido_utc) <= {k * intervalo_s + MARGEN_S}
            ORDER BY d.exchange, d.banda_bps, d.recibido_utc"""))
    return pd.concat(partes, ignore_index=True)
