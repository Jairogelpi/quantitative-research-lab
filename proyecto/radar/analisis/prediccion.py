"""¿Predicen los cierres pasados el retorno futuro? Momentum y reversión sobre velas, con muestra guardada (Fase 5).

Conceptos:
- Momentum: ln(P_t / P_{t−L}), el retorno de las últimas L velas (exige L + 1 cierres del mismo segmento). Espera
  que lo que subió siga subiendo (docs/conceptos/momentum_y_reversion.md).
- Media simple (SMA_L): media de los L últimos cierres; media exponencial (EMA_L): EWM con span L, reiniciada al
  empezar cada segmento (tras un hueco no se arrastra la media de antes). Precio frente a su media: ln(P_t / SMA_L)
  y ln(P_t / EMA_L), positivos si el precio está por encima (momentum).
- Cruce de medias: ln(SMA_corta / SMA_larga), positivo cuando la media corta está por encima de la larga (la regla
  de medias móviles de Brock, Lakonishok y LeBaron, 1992).
- Z-score: (P_t − SMA_L) / s_L, con s_L la desviación típica muestral de los mismos L cierres. La señal de reversión
  es −z: positiva cuando el precio está por debajo de su media y se espera que vuelva. Reversión a corto plazo:
  −r_t, lo contrario del último retorno. Un z bajo no es infravaloración: solo compara con el pasado reciente.
- Convención de signo: todas las señales se definen para que un valor positivo espere un retorno positivo. Aun así,
  la dirección (±1) se estima con los datos: en cada tramo del walk-forward, con el entrenamiento; para la muestra
  guardada, con todo el desarrollo. Nunca con los datos en los que se evalúa.
- Solo el pasado: la señal en t usa cierres hasta t. Calcularla con la serie cortada en t da el mismo valor.
- Objetivo con entrada en t + 1: la señal se observa al CERRAR la vela t; se entra al cierre de t + 1 y se sale al
  cierre de t + 1 + H: objetivo = ln(P_{t+1+H} / P_{t+1}), solo si t, t + 1 y t + 1 + H están en el mismo segmento
  (`retornos.retorno_futuro`). Entrar en t supondría ejecutar al precio que generó la señal. Entrar a la apertura
  de t + 1 es casi lo mismo (en un mercado 24/7 la apertura de t + 1 es ≈ el cierre de t) y además mete en el
  objetivo el rebote bid-ask del último trade de t, que crea una reversión falsa de un periodo. Con el cierre de
  t + 1 se deja una vela entera para decidir y ejecutar: es conservador y es la convención de P05. Se conoce al
  cerrar la vela t + 1 + H (`objetivo_conocido`).
- IC (information coefficient): correlación de Pearson (lineal) y de Spearman (rangos, robusta a las colas gruesas
  de BTC) entre señal y objetivo. Su t se obtiene de la regresión objetivo ~ señal estandarizada (o de sus rangos)
  con errores Newey-West (HAC). Con H > 1 los objetivos de velas seguidas comparten H − 1 retornos y las señales
  de ventana larga apenas cambian de una vela a otra: el t ingenuo sale inflado. Retardos HAC: el mayor entre H y
  la regla 4 · (n / 100)^(2/9) (`imbalance._retardos`). El p del estudio es el del IC de Spearman (aproximación
  normal, `imbalance._p_valor`).
- Separación cronológica con purga y embargo (López de Prado, Advances in Financial Machine Learning, 2018,
  cap. 7): el desarrollo se parte en `TRAMOS` bloques; cada bloque desde el segundo se prueba con la dirección
  estimada en todo lo anterior (walk-forward anclado). Purga: se quitan del entrenamiento las filas cuyo objetivo
  termina después de que empiece la prueba (su resultado se solapa con el periodo de prueba). Embargo: además se
  deja un hueco de `EMBARGO_FRACCION` del desarrollo antes de cada prueba (López de Prado sugiere ≈ 1 %). Como aquí
  el entrenamiento siempre va antes de la prueba, el embargo hace de margen extra contra la dependencia serial.
- Autocorrelación y Ljung-Box de los retornos (contexto): ρ_k = Corr(r_t, r_{t−k}) con pares del mismo segmento y
  Q de Ljung-Box en `RETARDOS_LB` retardos (`retornos.ljung_box`). Rechazar dice que hay dependencia lineal; no
  dice que sea explotable tras el retraso de una vela y los costes (docs/conceptos/eficiencia_de_mercado.md).
- Regla y costes: cada H velas se decide al cierre de t, se entra al cierre de t + 1 y se mantiene H velas
  (periodos que no se solapan). Largo/fuera: posición 1 si dirección · señal > 0 y 0 si no; largo/corto: el signo
  de dirección · señal. Cada cambio de posición paga la comisión por lado sobre el importe cambiado (de 1 a −1
  son dos lados); se cierra al final de cada tramo continuo y en cada hueco. Rotación = lados operados. Kraken
  cobra 0,80 % por lado al taker y 0,40 % al maker en el primer nivel (`configuracion.COMISIONES_TAKER`).
  Neto = bruto − comisión · lados. Coste de equilibrio por lado = bruto / lados: la comisión máxima que la regla
  soporta sin perder. En el desarrollo, la regla se evalúa solo en los bloques de prueba del walk-forward. Se
  compara con comprar y mantener en los mismos periodos: un bruto positivo puede ser solo la deriva del precio.
- Data snooping y pruebas múltiples: la familia (señales × ventanas × horizontes × intervalos) se declara ANTES de
  mirar los datos (`SENALES`, `HORIZONTES`) y es pequeña a propósito: con m pruebas sobre n observaciones, el IC
  máximo que sale por azar crece como √(2 · ln m / n) (P11). Benjamini-Hochberg (proporción de falsos
  descubrimientos) y Bonferroni (al menos un falso positivo, p · m) se aplican sobre TODA la familia evaluada.
- Muestra guardada (bajo llave): el desarrollo solo ve velas con inicio antes de `FIN_DESARROLLO` (01-01-2025); el
  código lo impone al leer y lo comprueba al estudiar. Las señales confirmadas en el desarrollo se evalúan UNA
  sola vez en las velas desde esa fecha, con la dirección del desarrollo y Bonferroni sobre las señales evaluadas.
  La apertura se registra (`aperturas_muestra_guardada`: hora, huella de la familia y señales) ANTES de calcular,
  y una segunda apertura de la misma familia se rechaza: mirar la muestra guardada y luego volver a ajustar la
  familia la convertiría en otra muestra de desarrollo. La huella (`huella_familia`) es el SHA-256 del método y de
  todo lo declarado; si cambia algo, es otra familia y necesita su propio desarrollo.

Estados del desarrollo:
- datos insuficientes: menos de `MIN_OBSERVACIONES` pares señal-objetivo, o p no calculable.
- sin evidencia: p ajustado por BH sobre la familia ≥ `ALFA`.
- no confirmada fuera de muestra: significativa, pero la dirección del pasado acierta (IC de Spearman de prueba con
  el mismo signo) en menos de `MIN_TRAMOS_A_FAVOR` bloques, o el IC medio fuera de muestra no es positivo.
- confirmada: significativa tras BH y repetida en el walk-forward purgado. Sobrevive al desarrollo.
Estados de la muestra guardada: datos insuficientes / confirmada en la muestra guardada (IC con la dirección del
desarrollo y p de Bonferroni sobre las señales evaluadas < `ALFA`) / no confirmada en la muestra guardada.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from radar.analisis.imbalance import _p_valor, _retardos, _t
from radar.analisis.retornos import (SERIE, _autocorrelaciones, _por_segmento, ljung_box, objetivo_conocido_utc,
                                     preparar_retornos, retorno_futuro)
from radar.analisis.velas import leer_velas
from radar.configuracion import COMISIONES_TAKER

METODO = "prediccion/v1"
FUENTE_PREDICCION = "estudios_prediccion"
FUENTE_APERTURAS = "aperturas_muestra_guardada"
FUENTE_POR_DEFECTO = "kraken_historico"
INTERVALOS_POR_DEFECTO = (86400, 3600)
FIN_DESARROLLO = pd.Timestamp("2025-01-01", tz="UTC")   # inicio de la muestra guardada (excluido del desarrollo)
DESARROLLO, GUARDADA = "desarrollo", "guardada"

# Familia declarada antes de mirar los datos. Ventanas en velas (5, 20 y 60 días u horas): corta, un mes de
# cotización y un trimestre en diario. Tres horizontes de la misma escala. 15 señales × 3 horizontes = 45 pruebas
# por intervalo, 90 con los dos intervalos por defecto.
VENTANAS = (5, 20, 60)
CRUCES = ((5, 20), (20, 60))
HORIZONTES = (1, 5, 20)
SENALES = (tuple(("momentum", v, None) for v in VENTANAS) + tuple(("precio_sma", v, None) for v in VENTANAS)
           + tuple(("precio_ema", v, None) for v in VENTANAS) + tuple(("reversion_z", v, None) for v in VENTANAS)
           + tuple(("cruce_medias", c, l) for c, l in CRUCES) + (("reversion_corta", 1, None),))

TRAMOS = 5                  # bloques del walk-forward: 4 pruebas
MIN_TRAMOS_A_FAVOR = 3      # de 4
EMBARGO_FRACCION = 0.01
MIN_OBSERVACIONES = 300
RETARDOS_LB = 10
ALFA = 0.05
CALENTAMIENTO = 10 * max(VENTANAS)   # velas previas a la muestra guardada para calcular sus señales (la EMA
                                     # de span 60 olvida su arranque en un factor (59/61)^600 ≈ 2e-9)
COMISION_TAKER = COMISIONES_TAKER["kraken"][0]   # 0,80 % por lado
COMISION_MAKER = 0.0040                           # kraken.com/pro/fees, primer nivel (misma fuente que el taker)

INSUFICIENTE, SIN_EVIDENCIA = "datos insuficientes", "sin evidencia"
NO_CONFIRMADA, CONFIRMADA = "no confirmada fuera de muestra", "confirmada"
CONFIRMADA_GUARDADA, NO_CONFIRMADA_GUARDADA = "confirmada en la muestra guardada", "no confirmada en la muestra guardada"


class MuestraGuardadaYaAbierta(RuntimeError):
    """La muestra guardada de esta familia ya se abrió: no se puede evaluar dos veces."""


# Filtro económico para entrar en la muestra guardada (decisión del usuario, 22-11-2026): además de "confirmada",
# la mejor de sus dos reglas (solo comprado, o comprado y vendido) tiene que ganar con comisión maker y ganarle a
# comprar y mantener en los mismos periodos. Sin esto, la muestra limpia se gastaría en confirmar señales que ya
# se sabe que no sirven (significativas pero inexplotables, o deriva alcista con menos exposición).
FILTRO_ECONOMICO = "neto maker de la mejor regla > max(0, comprar y mantener)"


def viable_economicamente(filas: pd.DataFrame) -> pd.Series:
    """Por fila: el neto con comisión maker de la mejor regla supera a 0 y a comprar y mantener."""
    mejor = filas[["neto_maker_largo", "neto_maker_largo_corto"]].max(axis=1)
    return mejor > filas["bruto_mantener"].clip(lower=0)


def nombre_senal(senal: str, ventana: int, larga: int | None = None) -> str:
    return f"{senal}_{ventana}" + (f"_{larga}" if larga else "")


def huella_familia(fuente: str, intervalos, senales=SENALES, horizontes=HORIZONTES) -> str:
    """SHA-256 de todo lo declarado: método, fuente, intervalos, señales, horizontes, corte y reglas de decisión."""
    declarado = {"metodo": METODO, "fuente": fuente, "intervalos": sorted(int(i) for i in intervalos),
                 "senales": [list(s) for s in senales], "horizontes": list(horizontes),
                 "fin_desarrollo": FIN_DESARROLLO.isoformat(), "tramos": TRAMOS, "a_favor": MIN_TRAMOS_A_FAVOR,
                 "embargo": EMBARGO_FRACCION, "minimo": MIN_OBSERVACIONES, "alfa": ALFA,
                 "filtro_economico": FILTRO_ECONOMICO}
    return hashlib.sha256(json.dumps(declarado, sort_keys=True).encode()).hexdigest()


# --- Señales y objetivo -----------------------------------------------------------------------------------


def _ema(precio: pd.Series, segmento: pd.Series, span: int) -> pd.Series:
    validos = precio.dropna()
    if validos.empty:
        return pd.Series(np.nan, index=precio.index)
    ema = validos.groupby(segmento[validos.index]).transform(
        lambda s: s.ewm(span=span, adjust=False, min_periods=span).mean())
    return ema.reindex(precio.index)


def _senales_serie(g: pd.DataFrame, senales) -> pd.DataFrame:
    p, seg = g.cierre_analisis, g.segmento
    sma = {v: _por_segmento(p, seg, v, lambda x: x.mean()) for v in {s[1] for s in senales} | {s[2] for s in senales}
           if v}
    salida = {}
    for senal, v, larga in senales:
        if senal == "momentum":
            x = _por_segmento(g.ret_log, seg, v, lambda r: r.sum())
        elif senal == "precio_sma":
            x = np.log(p / sma[v])
        elif senal == "precio_ema":
            x = np.log(p / _ema(p, seg, v))
        elif senal == "reversion_z":
            x = -(p - sma[v]) / _por_segmento(p, seg, v, lambda r: r.std(ddof=1))
        elif senal == "cruce_medias":
            x = np.log(sma[v] / sma[larga])
        elif senal == "reversion_corta":
            x = -_por_segmento(g.ret_log, seg, v, lambda r: r.sum())
        else:
            raise ValueError(f"señal desconocida: {senal!r}")
        salida[nombre_senal(senal, v, larga)] = x.replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame(salida, index=g.index)


def calcular_senales(retornos: pd.DataFrame, senales=SENALES) -> pd.DataFrame:
    """Una columna por señal declarada (`nombre_senal`), alineada con `retornos` (de `preparar_retornos`). La
    señal en t solo usa cierres de análisis hasta t y del mismo segmento."""
    partes = [_senales_serie(g, senales) for _, g in retornos.groupby(SERIE, sort=False)]
    if not partes:
        return pd.DataFrame(columns=[nombre_senal(*s) for s in senales])
    return pd.concat(partes).reindex(retornos.index)


def objetivo(retornos: pd.DataFrame, horizonte: int) -> pd.Series:
    """ln(P_{t+1+H} / P_{t+1}) alineado en t: se entra al cierre de t + 1; NaN si t, t + 1 y t + 1 + H no están
    en el mismo segmento."""
    futuro = retorno_futuro(retornos, horizonte)            # ln(P_{t+H} / P_t), ya dentro de un segmento
    claves = [retornos[c] for c in SERIE]
    siguiente = futuro.groupby(claves, sort=False).shift(-1)
    mismo = retornos.segmento.groupby(claves, sort=False).shift(-1) == retornos.segmento
    return siguiente.where(mismo)


def objetivo_conocido(retornos: pd.DataFrame, horizonte: int) -> pd.Series:
    """Cuándo se conoce el objetivo de t: al cerrar la vela t + 1 + H."""
    return objetivo_conocido_utc(retornos, horizonte + 1)


# --- Estadística ------------------------------------------------------------------------------------------


def ic_hac(senal: pd.Series, objetivo_: pd.Series, horizonte: int, rangos: bool = False) -> tuple[float, float]:
    """(IC, t HAC): correlación de Pearson (o de Spearman, con `rangos`) y el t Newey-West de la pendiente de
    objetivo ~ señal estandarizada. Filas en orden temporal."""
    d = pd.DataFrame({"x": np.asarray(senal, dtype=float), "y": np.asarray(objetivo_, dtype=float)}).dropna()
    if len(d) < 10 or d.x.nunique() < 2 or d.y.nunique() < 2:
        return math.nan, math.nan
    if rangos:
        d = d.rank()
    ic = float(d.x.corr(d.y))
    x = ((d.x - d.x.mean()) / d.x.std()).to_numpy()
    ajuste = sm.OLS(d.y.to_numpy(), sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": _retardos(len(d), horizonte)})
    return ic, _t(float(ajuste.params[1]), float(ajuste.bse[1]))


def particiones_purgadas(observado: pd.Series, conocido: pd.Series, tramos: int = TRAMOS,
                         embargo: pd.Timedelta = pd.Timedelta(0)) -> list[tuple[np.ndarray, np.ndarray]]:
    """Walk-forward anclado con purga: [(posiciones de entrenamiento, posiciones de prueba)] por cada bloque desde
    el segundo. `observado`: cuándo se conoce la señal (orden temporal); `conocido`: cuándo termina su objetivo.
    Se entrena con las filas anteriores cuyo objetivo terminó antes de `observado` del primer día de prueba −
    `embargo`."""
    obs = pd.DatetimeIndex(observado)
    fin = pd.DatetimeIndex(conocido)
    bloques = np.array_split(np.arange(len(obs)), tramos)
    particiones = []
    for bloque in bloques[1:]:
        if len(bloque) == 0:
            continue
        previas = np.arange(bloque[0])
        particiones.append((previas[np.asarray(fin[previas] <= obs[bloque[0]] - embargo)], bloque))
    return particiones


@dataclass(frozen=True)
class Operacion:
    """Resultado de una regla: periodos, retorno bruto (suma de retornos simples por periodo), lados operados
    (rotación, en importes de la posición completa) y periodos con posición."""
    periodos: int = 0
    bruto: float = 0.0
    lados: float = 0.0
    en_mercado: int = 0

    def __add__(self, otra: "Operacion") -> "Operacion":
        return Operacion(self.periodos + otra.periodos, self.bruto + otra.bruto, self.lados + otra.lados,
                         self.en_mercado + otra.en_mercado)

    def neto(self, comision_lado: float) -> float:
        return self.bruto - comision_lado * self.lados

    @property
    def equilibrio_bps(self) -> float:
        return self.bruto / self.lados * 1e4 if self.lados else math.nan

    @property
    def exposicion(self) -> float:
        return self.en_mercado / self.periodos if self.periodos else math.nan


def operar(posiciones, retornos_simples) -> Operacion:
    """Una racha continua: se parte de 0, se mantiene cada posición un periodo y se cierra al final."""
    p = np.asarray(posiciones, dtype=float)
    r = np.asarray(retornos_simples, dtype=float)
    if len(p) == 0:
        return Operacion()
    lados = float(np.abs(np.diff(np.concatenate([[0.0], p, [0.0]]))).sum())
    return Operacion(len(p), float((p * r).sum()), lados, int((p != 0).sum()))


def _reglas(d: pd.DataFrame, direccion, horizonte: int, intervalo_s: int) -> tuple[Operacion, Operacion, Operacion]:
    """(largo/fuera, largo/corto, comprar y mantener) con decisiones cada H velas; `direccion` escalar o por
    fila. Un salto en la rejilla (hueco u objetivo sin dato) cierra la racha. Comprar y mantener en los mismos
    periodos separa lo que aporta la señal de la deriva del precio (BTC subió mucho en 2013-2024)."""
    if d.empty:
        return Operacion(), Operacion(), Operacion()
    paso = ((d.inicio_utc - d.inicio_utc.iloc[0]) / pd.Timedelta(seconds=intervalo_s)).round().astype(int)
    elegidas = (paso % horizonte == 0).to_numpy()
    d, paso = d[elegidas], paso[elegidas].to_numpy()
    direccion = np.broadcast_to(np.asarray(direccion, dtype=float), (len(elegidas),))[elegidas]
    corto = np.sign(direccion * d.senal.to_numpy())
    largo = np.clip(corto, 0, None)
    ret = np.expm1(d.objetivo.to_numpy())
    cortes = np.flatnonzero(np.diff(paso) != horizonte) + 1
    lf, ls, mantener = Operacion(), Operacion(), Operacion()
    for tramo in np.split(np.arange(len(paso)), cortes):
        lf += operar(largo[tramo], ret[tramo])
        ls += operar(corto[tramo], ret[tramo])
        mantener += operar(np.ones(len(tramo)), ret[tramo])
    return lf, ls, mantener


# --- Resultados -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoPrediccion:
    fuente: str
    exchange: str
    par: str
    intervalo_s: int
    senal: str
    ventana_velas: int
    ventana_larga_velas: int | None
    horizonte_velas: int
    muestra: str
    familia_hash: str
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_observaciones: int
    minimo: int
    direccion: int
    ic_pearson: float
    t_pearson: float
    ic_spearman: float
    t_spearman: float
    p_valor: float
    p_bh: float
    p_bonferroni: float
    familia: int
    tramos_total: int
    tramos_a_favor: int
    ic_fuera_media: float
    rho1_ret: float
    q_lb: float
    p_lb: float
    retardos_lb: int
    largo: Operacion = field(default_factory=Operacion)
    largo_corto: Operacion = field(default_factory=Operacion)
    mantener: Operacion = field(default_factory=Operacion)

    @property
    def suficiente(self) -> bool:
        return self.n_observaciones >= self.minimo and math.isfinite(self.p_valor)

    @property
    def estado(self) -> str:
        if not self.suficiente:
            return INSUFICIENTE
        if self.muestra == GUARDADA:
            a_favor = self.direccion != 0 and np.sign(self.t_spearman) == self.direccion
            return CONFIRMADA_GUARDADA if a_favor and self.p_bonferroni < ALFA else NO_CONFIRMADA_GUARDADA
        if not self.p_bh < ALFA:
            return SIN_EVIDENCIA
        repetida = self.tramos_a_favor >= MIN_TRAMOS_A_FAVOR and self.ic_fuera_media > 0
        return CONFIRMADA if repetida else NO_CONFIRMADA

    @property
    def nombre(self) -> str:
        return nombre_senal(self.senal, self.ventana_velas, self.ventana_larga_velas)

    def _regla(self, nombre: str, op: Operacion) -> str:
        if not op.periodos:
            return f"{nombre}: sin periodos"
        if not op.lados:
            return f"{nombre}: {op.periodos} periodos sin operar"
        return (f"{nombre}: {op.periodos} periodos, exposición {op.exposicion:.0%}, bruto {op.bruto:+.1%} con "
                f"{op.lados:g} lados; equilibrio {op.equilibrio_bps:+.1f} bps por lado frente a "
                f"{COMISION_TAKER * 1e4:.0f} (taker) y {COMISION_MAKER * 1e4:.0f} (maker): neto "
                f"{op.neto(COMISION_TAKER):+.1%} con taker y {op.neto(COMISION_MAKER):+.1%} con maker")

    def conclusion(self) -> str:
        cabecera = (f"{self.fuente}, {self.exchange}, velas de {self.intervalo_s} s, {self.nombre}, horizonte "
                    f"{self.horizonte_velas} velas ({'muestra guardada' if self.muestra == GUARDADA else 'desarrollo'})")
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_observaciones} pares señal-objetivo; hacen falta "
                    f"{self.minimo}).")
        if self.muestra == GUARDADA:
            texto = (f"{cabecera}: {self.estado}. Con la dirección del desarrollo ({self.direccion:+d}), IC Spearman "
                     f"{self.ic_spearman:+.3f} (t HAC {self.t_spearman:.2f}, p {self.p_valor:.2g}, Bonferroni "
                     f"{self.p_bonferroni:.3f} sobre {self.familia} señales), IC Pearson {self.ic_pearson:+.3f} "
                     f"(t HAC {self.t_pearson:.2f}), {self.n_observaciones} pares.")
        else:
            texto = (f"{cabecera}: {self.estado}. IC Spearman {self.ic_spearman:+.3f} (t HAC {self.t_spearman:.2f}, "
                     f"p {self.p_valor:.2g}; BH {self.p_bh:.3f} y Bonferroni {self.p_bonferroni:.3f} sobre "
                     f"{self.familia} pruebas), IC Pearson {self.ic_pearson:+.3f} (t HAC {self.t_pearson:.2f}), "
                     f"{self.n_observaciones} pares; walk-forward con purga: la dirección del pasado acierta en "
                     f"{self.tramos_a_favor}/{self.tramos_total} bloques (IC medio fuera {self.ic_fuera_media:+.3f}).")
        texto += (f" {self._regla('Largo/fuera', self.largo)}. {self._regla('Largo/corto', self.largo_corto)}. "
                  f"Comprar y mantener en los mismos periodos: bruto {self.mantener.bruto:+.1%}. "
                  f"Retornos: ρ₁ {self.rho1_ret:+.3f}, Ljung-Box Q({self.retardos_lb}) {self.q_lb:.1f}, "
                  f"p {self.p_lb:.3g}.")
        return texto

    def a_fila(self) -> dict:
        fila = {k: v for k, v in asdict(self).items()
                if k not in ("largo", "largo_corto", "mantener", "p_valor", "p_bh", "p_bonferroni", "t_spearman")}
        # En el desarrollo, los nombres que lee el registro de pruebas (p_descubrimiento con su t_hac). En la
        # muestra guardada, otros nombres: es una confirmación, no un descubrimiento nuevo (no entra en la familia).
        if self.muestra == GUARDADA:
            fila.update({"t_guardada": self.t_spearman, "p_guardada": self.p_valor,
                         "p_guardada_bonferroni": self.p_bonferroni})
        else:
            fila.update({"t_hac": self.t_spearman, "p_descubrimiento": self.p_valor, "p_ajustado": self.p_bh,
                         "p_bonferroni": self.p_bonferroni})
        for nombre, op in (("largo", self.largo), ("largo_corto", self.largo_corto)):
            fila.update({f"periodos_{nombre}": op.periodos, f"bruto_{nombre}": op.bruto, f"lados_{nombre}": op.lados,
                         f"exposicion_{nombre}": op.exposicion, f"equilibrio_{nombre}_bps": op.equilibrio_bps,
                         f"neto_taker_{nombre}": op.neto(COMISION_TAKER),
                         f"neto_maker_{nombre}": op.neto(COMISION_MAKER)})
        fila.update({"periodos_mantener": self.mantener.periodos, "bruto_mantener": self.mantener.bruto})
        return {"estudio": "prediccion", **fila, "comision_taker": COMISION_TAKER, "comision_maker": COMISION_MAKER,
                "estado": self.estado, "conclusion": self.conclusion()}


# --- Estudio ----------------------------------------------------------------------------------------------


def _contexto(g: pd.DataFrame) -> dict:
    rho, n = _autocorrelaciones(g.ret_log, g.segmento, RETARDOS_LB)
    q, p = ljung_box(rho, n)
    return dict(rho1_ret=rho[0], q_lb=q, p_lb=p, retardos_lb=RETARDOS_LB)


def _pares(g: pd.DataFrame, senales: pd.DataFrame, columna: str, horizonte: int, desde=None) -> pd.DataFrame:
    d = pd.DataFrame({"inicio_utc": g.inicio_utc, "senal": senales[columna], "objetivo": objetivo(g, horizonte),
                      "conocido": objetivo_conocido(g, horizonte)})
    if desde is not None:
        d = d[d.inicio_utc >= desde]
    return d.dropna(subset=["senal", "objetivo"]).reset_index(drop=True)


def _base(g, senal, v, larga, horizonte, muestra, huella, d, minimo) -> dict:
    intervalo = int(g.intervalo_s.iloc[0])
    ic_p, t_p = ic_hac(d.senal, d.objetivo, horizonte)
    ic_s, t_s = ic_hac(d.senal, d.objetivo, horizonte, rangos=True)
    return dict(fuente=g.fuente.iloc[0], exchange=g.exchange.iloc[0], par=g.par.iloc[0], intervalo_s=intervalo,
                senal=senal, ventana_velas=int(v), ventana_larga_velas=int(larga) if larga else None,
                horizonte_velas=int(horizonte), muestra=muestra, familia_hash=huella,
                desde_utc=d.inicio_utc.iloc[0] if len(d) else pd.NaT,
                hasta_utc=d.conocido.max() if len(d) else pd.NaT, n_observaciones=len(d), minimo=minimo,
                ic_pearson=ic_p, t_pearson=t_p, ic_spearman=ic_s, t_spearman=t_s,
                p_valor=_p_valor(t_s) if len(d) >= minimo else math.nan)


def _walk_forward(d: pd.DataFrame, horizonte: int, intervalo_s: int, tramos: int):
    observado = d.inicio_utc + pd.Timedelta(seconds=intervalo_s)
    embargo = pd.Timedelta(seconds=intervalo_s) * math.ceil(EMBARGO_FRACCION * len(d))
    favor, total, ics = 0, 0, []
    lf, ls, mantener = Operacion(), Operacion(), Operacion()
    for entrena, prueba in particiones_purgadas(observado, d.conocido, tramos, embargo):
        e, p = d.iloc[entrena], d.iloc[prueba]
        ic_e, _ = ic_hac(e.senal, e.objetivo, horizonte, rangos=True)
        ic_p = float(p.senal.corr(p.objetivo, method="spearman")) if len(p) > 2 else math.nan
        if not (math.isfinite(ic_e) and ic_e != 0 and math.isfinite(ic_p)):
            continue
        direccion = math.copysign(1, ic_e)
        total += 1
        favor += int(direccion * ic_p > 0)
        ics.append(direccion * ic_p)
        a, b, c = _reglas(p, direccion, horizonte, intervalo_s)
        lf, ls, mantener = lf + a, ls + b, mantener + c
    return favor, total, (float(np.mean(ics)) if ics else math.nan), lf, ls, mantener


def _con_familia(borradores: list[dict]) -> list[ResultadoPrediccion]:
    validos = [i for i, b in enumerate(borradores) if b["n_observaciones"] >= b["minimo"]
               and math.isfinite(b["p_valor"])]
    p = [borradores[i]["p_valor"] for i in validos]
    bh = dict(zip(validos, multipletests(p, method="fdr_bh")[1])) if p else {}
    bonf = dict(zip(validos, multipletests(p, method="bonferroni")[1])) if p else {}
    return [ResultadoPrediccion(**b, p_bh=float(bh.get(i, math.nan)), p_bonferroni=float(bonf.get(i, math.nan)),
                                familia=len(validos)) for i, b in enumerate(borradores)]


def estudiar_prediccion(velas: pd.DataFrame, senales=SENALES, horizontes=HORIZONTES, minimo: int = MIN_OBSERVACIONES,
                        tramos: int = TRAMOS, huella: str | None = None) -> list[ResultadoPrediccion]:
    """Desarrollo: un resultado por serie (fuente, exchange, par, intervalo), señal y horizonte, con BH y
    Bonferroni sobre todos. Rechaza velas de la muestra guardada (inicio ≥ `FIN_DESARROLLO`)."""
    if len(velas) and (pd.to_datetime(velas.inicio_utc, utc=True) >= FIN_DESARROLLO).any():
        raise ValueError(f"El desarrollo no puede ver la muestra guardada: hay velas desde {FIN_DESARROLLO:%Y-%m-%d}")
    if not len(velas):
        return []
    if huella is None:
        huella = huella_familia(velas.fuente.iloc[0], velas.intervalo_s.unique(), senales, horizontes)
    retornos = preparar_retornos(velas)
    borradores = []
    for _, g in retornos.groupby(SERIE, sort=True):
        g = g.reset_index(drop=True)
        intervalo = int(g.intervalo_s.iloc[0])
        tabla = calcular_senales(g, senales)
        contexto = _contexto(g)
        for senal, v, larga in senales:
            for h in horizontes:
                d = _pares(g, tabla, nombre_senal(senal, v, larga), h)
                b = _base(g, senal, v, larga, h, DESARROLLO, huella, d, minimo)
                favor, total, ic_fuera, lf, ls, bh = (_walk_forward(d, h, intervalo, tramos) if len(d) >= minimo
                                                      else (0, 0, math.nan, Operacion(), Operacion(), Operacion()))
                direccion = int(np.sign(b["ic_spearman"])) if math.isfinite(b["ic_spearman"]) else 0
                borradores.append(dict(**b, **contexto, direccion=direccion, tramos_total=total,
                                       tramos_a_favor=favor, ic_fuera_media=ic_fuera, largo=lf, largo_corto=ls,
                                       mantener=bh))
    return _con_familia(borradores)


def estudiar_prediccion_lake(consultar: Callable[[str], pd.DataFrame], fuente: str = FUENTE_POR_DEFECTO,
                             intervalos=INTERVALOS_POR_DEFECTO, exchange: str | None = None,
                             **opciones) -> list[ResultadoPrediccion]:
    """El desarrollo sobre las velas guardadas: solo lee velas con inicio antes de `FIN_DESARROLLO`."""
    partes = [leer_velas(consultar, fuente, exchange, intervalo, hasta=FIN_DESARROLLO) for intervalo in intervalos]
    partes = [p for p in partes if len(p)]
    if not partes:
        return []
    huella = huella_familia(fuente, intervalos, opciones.get("senales", SENALES), opciones.get("horizontes", HORIZONTES))
    return estudiar_prediccion(pd.concat(partes, ignore_index=True), huella=huella, **opciones)


def guardar_estudio_prediccion(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_PREDICCION)


# --- Muestra guardada -------------------------------------------------------------------------------------


def _ya_abierta(consultar, fuentes, huella: str) -> bool:
    if FUENTE_APERTURAS in fuentes and len(consultar(
            f"SELECT 1 FROM {FUENTE_APERTURAS} WHERE familia_hash = '{huella}' LIMIT 1")):
        return True
    return FUENTE_PREDICCION in fuentes and len(consultar(
        f"SELECT 1 FROM {FUENTE_PREDICCION} WHERE familia_hash = '{huella}' AND muestra = '{GUARDADA}' LIMIT 1")) > 0


def supervivientes_desarrollo(consultar, fuentes, huella: str) -> pd.DataFrame | None:
    """Las filas confirmadas Y viables económicamente (`FILTRO_ECONOMICO`) de la última ejecución del desarrollo de
    esa familia; None si no hay desarrollo."""
    if FUENTE_PREDICCION not in fuentes:
        return None
    filtro = f"familia_hash = '{huella}' AND muestra = '{DESARROLLO}'"
    ultima = consultar(f"""SELECT * FROM {FUENTE_PREDICCION} WHERE {filtro}
                           AND ejecutado_utc = (SELECT max(ejecutado_utc) FROM {FUENTE_PREDICCION} WHERE {filtro})""")
    if ultima.empty:
        return None
    confirmadas = ultima[ultima.estado == CONFIRMADA]
    return confirmadas[viable_economicamente(confirmadas)].reset_index(drop=True)


def evaluar_muestra_guardada(velas: pd.DataFrame, supervivientes: pd.DataFrame, huella: str,
                             minimo: int = MIN_OBSERVACIONES) -> list[ResultadoPrediccion]:
    """Evalúa las señales supervivientes, con la dirección del desarrollo, en los pares con inicio ≥
    `FIN_DESARROLLO` (las velas anteriores solo sirven para calcular las señales). Bonferroni y BH sobre ellas."""
    if not len(velas):
        return []
    retornos = preparar_retornos(velas)
    borradores = []
    for clave, g in retornos.groupby(SERIE, sort=True):
        g = g.reset_index(drop=True)
        propias = supervivientes[(supervivientes[SERIE].astype(str) == pd.Series(clave, index=SERIE).astype(str)
                                  ).all(axis=1)]
        if propias.empty:
            continue
        intervalo = int(g.intervalo_s.iloc[0])
        contexto = _contexto(g[g.inicio_utc >= FIN_DESARROLLO].reset_index(drop=True))
        declaradas = [(s.senal, int(s.ventana_velas), int(s.ventana_larga_velas) if pd.notna(s.ventana_larga_velas)
                       else None) for s in propias.itertuples()]
        tabla = calcular_senales(g, list(dict.fromkeys(declaradas)))
        for s, (senal, v, larga) in zip(propias.itertuples(), declaradas):
            h, direccion = int(s.horizonte_velas), int(s.direccion)
            d = _pares(g, tabla, nombre_senal(senal, v, larga), h, desde=FIN_DESARROLLO)
            d = d.assign(senal=d.senal * direccion)                # la señal con la dirección del desarrollo
            b = _base(g, senal, v, larga, h, GUARDADA, huella, d, minimo)
            lf, ls, bh = _reglas(d, 1.0, h, intervalo)
            borradores.append(dict(**b, **contexto, direccion=direccion, tramos_total=0, tramos_a_favor=0,
                                   ic_fuera_media=math.nan, largo=lf, largo_corto=ls, mantener=bh))
    return _con_familia(borradores)


def abrir_muestra_guardada(lake, ejecutado_utc: pd.Timestamp, fuente: str = FUENTE_POR_DEFECTO,
                           intervalos=INTERVALOS_POR_DEFECTO, exchange: str | None = None) -> list[ResultadoPrediccion]:
    """Abre la muestra guardada UNA vez para la familia declarada: comprueba que no se abrió antes, registra la
    apertura, evalúa las señales confirmadas en el desarrollo y guarda el resultado (muestra = "guardada").
    Sin supervivientes no se abre (no se registra nada) y devuelve []."""
    huella = huella_familia(fuente, intervalos)
    fuentes = lake.fuentes()
    if _ya_abierta(lake.consultar, fuentes, huella):
        raise MuestraGuardadaYaAbierta(f"La muestra guardada de la familia {huella[:12]} ya se abrió: no se evalúa "
                                       "dos veces. Una familia nueva necesita su propio desarrollo.")
    supervivientes = supervivientes_desarrollo(lake.consultar, fuentes, huella)
    if supervivientes is None:
        raise ValueError(f"No hay un desarrollo guardado de la familia {huella[:12]}: ejecuta antes el desarrollo.")
    if supervivientes.empty:
        return []
    senales = [nombre_senal(s.senal, int(s.ventana_velas),
                            int(s.ventana_larga_velas) if pd.notna(s.ventana_larga_velas) else None)
               + f"@{int(s.intervalo_s)}s/h{int(s.horizonte_velas)}" for s in supervivientes.itertuples()]
    lake.guardar([{"abierta_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, "familia_hash": huella,
                   "metodo": METODO, "fuente": fuente, "intervalos": ",".join(str(int(i)) for i in intervalos),
                   "desde_utc": FIN_DESARROLLO, "n_senales": len(senales), "senales": ";".join(senales)}],
                 FUENTE_APERTURAS)
    partes = [leer_velas(lake.consultar, fuente, exchange, intervalo,
                         desde=FIN_DESARROLLO - pd.Timedelta(seconds=int(intervalo)) * CALENTAMIENTO)
              for intervalo in intervalos]
    partes = [p for p in partes if len(p)]
    velas = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    resultados = evaluar_muestra_guardada(velas, supervivientes, huella)
    guardar_estudio_prediccion(resultados, lake, ejecutado_utc)
    return resultados
