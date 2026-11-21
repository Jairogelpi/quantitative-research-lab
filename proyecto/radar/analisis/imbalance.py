"""¿Anticipa el desequilibrio del libro el movimiento del precio? (Fase 2; base de las fases 5 y 8).

Conceptos:
- Retorno futuro (forward return): (precio dentro de k rondas / precio ahora − 1) en bps. Es lo que el imbalance
  de AHORA pretende anticipar. Solo se usa el futuro para evaluar, nunca para calcular la señal.
- Precio de referencia: el mid o el microprice. Microprice = (bid · cantidad_ask + ask · cantidad_bid) /
  (cantidad_bid + cantidad_ask): se acerca al lado con MENOS cantidad, que es el que se agotará antes. Si el
  imbalance anticipa el mid pero no el microprice, la "señal" ya estaba en el precio justo de ese momento.
- Horizonte y decaimiento: el estudio se repite con varios k (1, 5, 10, 30 rondas). Cómo cambia la relación
  con k dice cuánto dura la señal. Si entre las dos fotos pasó mucho más tiempo del esperado (otra captura,
  un corte), el par se descarta.
- Media condicionada: retorno medio con imbalance positivo frente a negativo; su diferencia es la del estudio.
- Errores Newey-West (HAC): rondas seguidas tienen imbalances casi iguales y, con k > 1, retornos que se
  solapan; no son observaciones independientes y el error estándar ingenuo sale demasiado pequeño (t inflado).
- Intervalo de confianza del 95 %: diferencia ± 1,96 × error estándar (HAC). El t dice SI hay efecto; el
  intervalo dice CUÁN GRANDE puede ser, que es lo que necesita quien lo vaya a usar.
- Descubrimiento y confirmación (fuera de muestra): la primera mitad en el tiempo descubre, la segunda
  confirma. Walk-forward: además, los datos se parten en `VENTANAS` tramos y se cuenta en cuántos se repite
  el signo del descubrimiento; una relación estable aparece en casi todos.
- Pruebas múltiples y Benjamini-Hochberg: con muchas combinaciones (exchange × banda × horizonte), alguna
  sale "clara" por azar. BH ajusta los p-valores para controlar la proporción de falsos descubrimientos.
- Controles (regresión múltiple): retorno futuro = a + b · imbalance + c · retorno pasado + d · spread. Si el
  imbalance solo reflejaba la tendencia que ya traía el precio (momentum) o el spread, su b deja de ser
  significativo: la señal no aporta nada propio.
- Information Coefficient (IC): correlación de rangos (Spearman) entre imbalance y retorno futuro. Usa todo el
  imbalance, no solo su signo. Quintiles: retorno medio de cada quinto del imbalance; monótonos si suben (o
  bajan) de forma ordenada, lo que indica una relación consistente y no un efecto de unos pocos extremos.
- Significación económica: el movimiento anticipado frente al punto de equilibrio de un taker.
- Puerta de calidad (`calidad.py`): un exchange con la captura rota no concluye.

Estados de cada estudio:
- calidad de datos insuficiente: el exchange no pasa la puerta de calidad.
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

METODO = "imbalance_retorno/v3"
FUENTE_ESTUDIOS = "estudios"
HORIZONTES = (1, 5, 10, 30)
MIN_POR_GRUPO = 200
VENTANAS = 4
ALFA = 0.05          # tasa de falsos descubrimientos tolerada (Benjamini-Hochberg)
T_CONFIRMACION = 2.0
Z_95 = 1.96
MARGEN_S = 2.0       # tiempo extra tolerado sobre horizonte × intervalo
PRECIOS = {"mid": "mid",
           "microprice": "(bid * cantidad_ask + ask * cantidad_bid) / (cantidad_bid + cantidad_ask)"}
CONTROLES = ("ret_pasado_bps", "spread_bps")

CALIDAD_INSUFICIENTE, INSUFICIENTE = "calidad de datos insuficiente", "datos insuficientes"
SIN_EVIDENCIA, NO_CONFIRMADA, CONFIRMADA = "sin evidencia", "no confirmada fuera de muestra", "confirmada"


@dataclass(frozen=True)
class ResultadoImbalance:
    exchange: str
    banda_bps: float
    horizonte_rondas: int
    precio_referencia: str
    desde_utc: pd.Timestamp
    corte_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    min_por_grupo: int
    motivo_calidad: str
    n_minimo_positivo: int
    n_minimo_negativo: int
    diferencia_descubrimiento: float
    t_descubrimiento: float
    p_descubrimiento: float
    p_ajustado: float
    diferencia_confirmacion: float
    t_confirmacion: float
    error_confirmacion: float
    ret_positivo_confirmacion: float
    ret_negativo_confirmacion: float
    ventanas_mismo_signo: int
    ventanas_total: int
    coef_controlado: float
    t_controlado: float
    ic: float
    quintiles: list
    equilibrio_bps: float | None

    @property
    def suficiente(self) -> bool:
        return min(self.n_minimo_positivo, self.n_minimo_negativo) >= self.min_por_grupo

    @property
    def estado(self) -> str:
        if self.motivo_calidad:
            return CALIDAD_INSUFICIENTE
        if not self.suficiente:
            return INSUFICIENTE
        if not self.p_ajustado < ALFA:
            return SIN_EVIDENCIA
        mismo_signo = np.sign(self.diferencia_confirmacion) == np.sign(self.diferencia_descubrimiento)
        return CONFIRMADA if mismo_signo and abs(self.t_confirmacion) >= T_CONFIRMACION else NO_CONFIRMADA

    @property
    def int95_inferior(self) -> float:
        return self.diferencia_confirmacion - Z_95 * self.error_confirmacion

    @property
    def int95_superior(self) -> float:
        return self.diferencia_confirmacion + Z_95 * self.error_confirmacion

    @property
    def sobrevive_controles(self) -> bool:
        """El imbalance sigue significativo, con el mismo signo, tras controlar retorno pasado y spread."""
        return (math.isfinite(self.t_controlado) and abs(self.t_controlado) >= T_CONFIRMACION
                and np.sign(self.t_controlado) == np.sign(self.diferencia_descubrimiento))

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
        if self.precio_referencia != "mid":
            cabecera += f", {self.precio_referencia}"
        if self.estado == CALIDAD_INSUFICIENTE:
            return f"{cabecera}: calidad de datos insuficiente ({self.motivo_calidad}); no se concluye."
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes (hacen falta {self.min_por_grupo} rondas con imbalance positivo y "
                    f"{self.min_por_grupo} con negativo en cada mitad; hay {self.n_minimo_positivo} y "
                    f"{self.n_minimo_negativo} en la mitad menor).")
        controles = "sobrevive a los controles" if self.sobrevive_controles else "no sobrevive a los controles"
        texto = (f"{cabecera}: {self.estado}. IC {self.ic:+.3f}; descubrimiento: diferencia "
                 f"{self.diferencia_descubrimiento:+.3f} bps (t HAC {self.t_descubrimiento:.2f}, p ajustado "
                 f"{self.p_ajustado:.3f}); confirmación: diferencia {self.diferencia_confirmacion:+.3f} bps, intervalo "
                 f"95 % [{self.int95_inferior:+.3f}, {self.int95_superior:+.3f}] (t HAC {self.t_confirmacion:.2f}); "
                 f"mismo signo en {self.ventanas_mismo_signo}/{self.ventanas_total} ventanas; con retorno pasado y "
                 f"spread, t {self.t_controlado:.2f}: {controles}; quintiles "
                 f"{'monótonos' if self.monotona else 'no monótonos'}.")
        if self.rentable_taker is not None:
            veredicto = "rentable para un taker" if self.rentable_taker else "no rentable para un taker"
            texto += (f" Anticipa {self.movimiento_bps:.3f} bps frente a un equilibrio taker de "
                      f"{self.equilibrio_bps:.1f} bps: {veredicto}.")
        return texto

    def a_fila(self) -> dict:
        fila = {k: v for k, v in asdict(self).items() if k != "quintiles"}
        fila.update({f"q{i + 1}": (self.quintiles[i] if i < len(self.quintiles) else math.nan) for i in range(5)})
        fila.update({"estado": self.estado, "int95_inferior": self.int95_inferior,
                     "int95_superior": self.int95_superior, "sobrevive_controles": self.sobrevive_controles,
                     "monotona": self.monotona, "movimiento_bps": self.movimiento_bps,
                     "rentable_taker": self.rentable_taker, "conclusion": self.conclusion()})
        return fila


def _retardos(n: int, horizonte: int) -> int:
    """El mayor entre el horizonte (solapamiento de retornos) y la regla de Newey-West 4 · (n / 100)^(2/9)."""
    return max(horizonte, int(4 * (n / 100) ** (2 / 9)))


def _t(coeficiente: float, error: float) -> float:
    if error == 0 or not math.isfinite(error):  # sin ruido: o no hay efecto, o es infinitamente claro
        return 0.0 if coeficiente == 0 else math.copysign(math.inf, coeficiente)
    return coeficiente / error


def diferencia_hac(g: pd.DataFrame, horizonte: int) -> tuple[float, float, float, int, int]:
    """(diferencia de medias positivo − negativo, su error Newey-West, su t, n positivos, n negativos).

    Regresión ret = a + b · [imbalance > 0]: b es la diferencia de medias. Filas en orden temporal; las de
    imbalance exactamente 0 no cuentan.
    """
    g = g[g.imbalance != 0]
    positivo = (g.imbalance > 0).astype(float).to_numpy()
    n_pos, n_neg = int(positivo.sum()), int(len(g) - positivo.sum())
    if min(n_pos, n_neg) < 2:
        return math.nan, math.nan, math.nan, n_pos, n_neg
    ajuste = sm.OLS(g.ret_bps.to_numpy(), sm.add_constant(positivo)).fit(
        cov_type="HAC", cov_kwds={"maxlags": _retardos(len(g), horizonte)})
    diferencia, error = float(ajuste.params[1]), float(ajuste.bse[1])
    return diferencia, error, _t(diferencia, error), n_pos, n_neg


def _controlado(g: pd.DataFrame, horizonte: int) -> tuple[float, float]:
    """Coeficiente del imbalance y su t (HAC) en ret = a + b · imbalance + c · retorno pasado + d · spread."""
    if not set(CONTROLES) <= set(g.columns):
        return math.nan, math.nan
    d = g.dropna(subset=["ret_bps", "imbalance", *CONTROLES])
    if len(d) < 10:
        return math.nan, math.nan
    x = sm.add_constant(d[["imbalance", *CONTROLES]].to_numpy(dtype=float))
    ajuste = sm.OLS(d.ret_bps.to_numpy(dtype=float), x).fit(cov_type="HAC",
                                                             cov_kwds={"maxlags": _retardos(len(d), horizonte)})
    return float(ajuste.params[1]), _t(float(ajuste.params[1]), float(ajuste.bse[1]))


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


def _ventanas(g: pd.DataFrame, horizonte: int, signo: float) -> tuple[int, int]:
    """Walk-forward: en cuántos de los `VENTANAS` tramos temporales la diferencia tiene el signo dado."""
    tramos = [g.iloc[i] for i in np.array_split(np.arange(len(g)), VENTANAS)]
    diferencias = [diferencia_hac(tramo, horizonte)[0] for tramo in tramos]
    validas = [d for d in diferencias if not math.isnan(d)]
    return sum(1 for d in validas if np.sign(d) == signo), len(validas)


def estudiar_imbalance(pares: pd.DataFrame, min_por_grupo: int = MIN_POR_GRUPO, equilibrio_bps: dict | None = None,
                       calidad: dict | None = None, precio: str = "mid") -> list[ResultadoImbalance]:
    """Un resultado por exchange, banda y horizonte.

    `pares`: exchange, banda_bps, horizonte_rondas, recibido_utc, imbalance, ret_bps (y, para los controles,
    ret_pasado_bps y spread_bps). `calidad`: {exchange: Calidad}. Benjamini-Hochberg se aplica a todas las
    pruebas con datos suficientes y de calidad.
    """
    borradores = []
    for (exchange, banda, horizonte), g in pares.groupby(["exchange", "banda_bps", "horizonte_rondas"], sort=True):
        g = g.sort_values("recibido_utc")
        mitad = len(g) // 2
        descubrimiento, confirmacion = g.iloc[:mitad], g.iloc[mitad:]
        d1, _, t1, p1, n1 = diferencia_hac(descubrimiento, horizonte)
        d2, e2, t2, p2, n2 = diferencia_hac(confirmacion, horizonte)
        conf = confirmacion[confirmacion.imbalance != 0]
        mismo, total = _ventanas(g, horizonte, np.sign(d1)) if not math.isnan(d1) else (0, 0)
        coef, t_ctrl = _controlado(g, horizonte)
        nota = (calidad or {}).get(exchange)
        borradores.append(dict(
            exchange=exchange, banda_bps=banda, horizonte_rondas=int(horizonte), precio_referencia=precio,
            desde_utc=g.recibido_utc.iloc[0], hasta_utc=g.recibido_utc.iloc[-1],
            corte_utc=confirmacion.recibido_utc.iloc[0] if len(confirmacion) else pd.NaT,
            min_por_grupo=min_por_grupo, motivo_calidad=nota.motivo if nota else "",
            n_minimo_positivo=min(p1, p2), n_minimo_negativo=min(n1, n2),
            diferencia_descubrimiento=d1, t_descubrimiento=t1, p_descubrimiento=_p_valor(t1),
            diferencia_confirmacion=d2, t_confirmacion=t2, error_confirmacion=e2,
            ret_positivo_confirmacion=float(conf.ret_bps[conf.imbalance > 0].mean()) if len(conf) else math.nan,
            ret_negativo_confirmacion=float(conf.ret_bps[conf.imbalance < 0].mean()) if len(conf) else math.nan,
            ventanas_mismo_signo=mismo, ventanas_total=total, coef_controlado=coef, t_controlado=t_ctrl,
            ic=float(g.imbalance.corr(g.ret_bps, method="spearman")) if len(g) > 2 else math.nan,
            quintiles=_quintiles(g), equilibrio_bps=(equilibrio_bps or {}).get(exchange)))

    validos = [i for i, b in enumerate(borradores)
               if not b["motivo_calidad"] and min(b["n_minimo_positivo"], b["n_minimo_negativo"]) >= min_por_grupo
               and not math.isnan(b["p_descubrimiento"])]
    ajustados = multipletests([borradores[i]["p_descubrimiento"] for i in validos], method="fdr_bh")[1] if validos else []
    p_ajustado = dict(zip(validos, ajustados))
    return [ResultadoImbalance(**b, p_ajustado=float(p_ajustado.get(i, math.nan))) for i, b in enumerate(borradores)]


def guardar_estudio(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución del estudio en la fuente `estudios`: una fila por resultado, con método y parámetros."""
    return almacen.guardar([{"estudio": "imbalance_retorno", "metodo": METODO, "ejecutado_utc": ejecutado_utc,
                             "recibido_utc": ejecutado_utc, **r.a_fila()} for r in resultados], FUENTE_ESTUDIOS)


def leer_ultimo_estudio(consultar: Callable[[str], pd.DataFrame], metodo: str | None = METODO) -> pd.DataFrame:
    """La última ejecución guardada del estudio (de `metodo`, o de cualquier método si es None): lo que otras
    fases (señales, ejecución) deben reutilizar."""
    filtro = f"metodo = '{metodo}'" if metodo else "estudio = 'imbalance_retorno'"
    return consultar(f"""
        SELECT * FROM {FUENTE_ESTUDIOS}
        WHERE {filtro} AND ejecutado_utc = (SELECT max(ejecutado_utc) FROM {FUENTE_ESTUDIOS} WHERE {filtro})
        ORDER BY exchange, banda_bps, horizonte_rondas""")


def pares_imbalance_retorno(consultar: Callable[[str], pd.DataFrame], horizontes=HORIZONTES,
                            intervalo_s: float = INTERVALO_S, precio: str = "mid") -> pd.DataFrame:
    """Une cada imbalance con el retorno futuro y el retorno pasado del precio de referencia (k rondas) y el
    spread de ese momento, para cada k de `horizontes` (vía SQL)."""
    if not horizontes or min(horizontes) < 1:
        raise ValueError("Los horizontes deben ser de al menos 1 ronda")
    if precio not in PRECIOS:
        raise ValueError(f"precio de referencia desconocido: {precio!r}; disponibles: {sorted(PRECIOS)}")
    partes = []
    for k in horizontes:
        maximo_s = k * intervalo_s + MARGEN_S
        partes.append(consultar(f"""
            WITH c AS (SELECT exchange, recibido_utc, spread_bps, {PRECIOS[precio]} AS precio FROM cotizaciones),
            m AS (
                SELECT *, lead(precio, {k}) OVER w AS p_futuro, lead(recibido_utc, {k}) OVER w AS t_futuro,
                          lag(precio, {k}) OVER w AS p_pasado, lag(recibido_utc, {k}) OVER w AS t_pasado
                FROM c WINDOW w AS (PARTITION BY exchange ORDER BY recibido_utc))
            SELECT d.exchange, d.banda_bps, {k} AS horizonte_rondas, d.recibido_utc, d.imbalance,
                   (m.p_futuro / m.precio - 1) * 1e4 AS ret_bps,
                   CASE WHEN epoch(m.recibido_utc) - epoch(m.t_pasado) <= {maximo_s}
                        THEN (m.precio / m.p_pasado - 1) * 1e4 END AS ret_pasado_bps,
                   m.spread_bps
            FROM desequilibrios d JOIN m USING (exchange, recibido_utc)
            WHERE d.imbalance IS NOT NULL AND m.p_futuro IS NOT NULL
              AND epoch(m.t_futuro) - epoch(m.recibido_utc) <= {maximo_s}
            ORDER BY d.exchange, d.banda_bps, d.recibido_utc"""))
    return pd.concat(partes, ignore_index=True)
