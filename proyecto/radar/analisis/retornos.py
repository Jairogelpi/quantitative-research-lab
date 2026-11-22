"""Retornos y volatilidad de cualquier serie de velas en el formato común (propias o de Kraken) (Fase 4).

Conceptos:
- Cierre de análisis: el cierre de una vela que tiene trades (no vacía) y está completa. Las vacías, las de
  frontera y las tocadas por un hueco de captura no dan precio para retornos (docs/conceptos/series_temporales.md).
- Retorno simple P_t / P_{t−1} − 1 (se agrega multiplicando) y logarítmico ln(P_t / P_{t−1}) (se agrega sumando).
  Un retorno existe solo entre dos cierres de análisis CONSECUTIVOS: a través de una vela vacía, incompleta o sin
  fila (hueco) no hay retorno; rellenar con el último cierre inventaría retornos 0 y bajaría la volatilidad.
- Segmento: tramo de cierres de análisis consecutivos. Retorno acumulado: P_t / primer cierre del segmento − 1.
- Volatilidad móvil: desviación típica muestral (ddof = 1) de los últimos `ventana` retornos log del mismo
  segmento. Volatilidad realizada: √Σ ℓ² de esos mismos retornos (movimiento total de `ventana` velas).
- Anualización en un mercado 24/7: σ_anual = σ_vela · √(365 · velas por día). BTC/EUR cotiza todos los días del
  año; los 252 días de la bolsa descuentan fines de semana y festivos en los que una acción no cotiza, y aquí
  infravalorarían la volatilidad un √(365/252) − 1 ≈ 20 %. La regla √t supone retornos sin autocorrelación; con
  agrupamiento de volatilidad sigue valiendo para la varianza media, no para la de un periodo concreto.
- Retorno futuro (objetivo): ln(P_{t+k} / P_t), alineado en t, solo si t y t + k están en el mismo segmento. Se
  conoce al CERRAR la vela t + k (`objetivo_conocido_utc`); nunca es una entrada de una señal (look-ahead). Las
  columnas de `preparar_retornos` en t solo usan velas hasta t.
- Distribución: asimetría, curtosis en exceso (0 en una normal) y frecuencia de colas |z| > 3 frente al 0,27 % de
  una normal. Colas gruesas: curtosis en exceso > `UMBRAL_CURTOSIS` y colas al menos `RATIO_COLAS` veces la normal.
- Agrupamiento de volatilidad (volatility clustering): a movimientos grandes les siguen movimientos grandes; se ve
  como autocorrelación positiva de |r|. Se contrasta con Ljung-Box sobre |r| en `RETARDOS_LB` retardos:
  Q = n (n + 2) Σ ρ_k² / (n − k), χ² con L grados de libertad bajo la nula. Ljung-Box y no HAC porque aquí la
  dependencia ES la hipótesis alternativa: bajo la nula, |r| son independientes y Ljung-Box es exacto en ese
  supuesto; HAC sirve para contrastar una media cuando se admite dependencia en la nula. Las autocorrelaciones
  solo usan pares del mismo segmento: un par a través de un hueco no está separado k velas.
- Regímenes de volatilidad: la volatilidad móvil (ventana `VENTANA_REGIMEN`) frente a su mediana. Calma: menos de
  `UMBRAL_CALMA` veces la mediana; agitación: más de `UMBRAL_AGITACION` veces; normal en medio. Con 30 retornos
  normales la volatilidad estimada varía un ~13 %, así que 1,5 veces la mediana no sale por azar. Hacen falta al
  menos `MIN_VENTANAS_REGIMEN` ventanas de valores.

Estados:
- datos insuficientes: menos de `MIN_RETORNOS` retornos (todo el estudio), o de ventanas (regímenes).
- agrupamiento: agrupamiento de volatilidad (Ljung-Box p < `ALFA` y ρ₁(|r|) > 0) / sin agrupamiento detectable.
- colas: colas gruesas / colas compatibles con la normal.
- régimen: cambios de régimen (al menos `MIN_FRACCION_AGITACION` del tiempo en agitación) / régimen estable.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import chi2

from radar.analisis.velas import FUENTE_PROPIA, FUENTE_VELAS, leer_velas

FUENTE_RETORNOS = "estudios_retornos"
METODO = "retornos/v1"
SERIE = ["fuente", "exchange", "par", "intervalo_s"]
VENTANA_VOL = 20
VENTANA_REGIMEN = 30
MIN_RETORNOS = 100
MIN_VENTANAS_REGIMEN = 4
RETARDOS_LB = 10
ALFA = 0.05
Z_COLA = 3.0
COLA_NORMAL = math.erfc(Z_COLA / math.sqrt(2))   # P(|z| > 3) en una normal ≈ 0,27 %
UMBRAL_CURTOSIS = 1.0
RATIO_COLAS = 2.0
UMBRAL_CALMA, UMBRAL_AGITACION = 0.75, 1.5
MIN_FRACCION_AGITACION = 0.10
SEGUNDOS_ANO = 365 * 86400

INSUFICIENTE, ANALIZADA = "datos insuficientes", "analizada"
AGRUPAMIENTO, SIN_AGRUPAMIENTO = "agrupamiento de volatilidad", "sin agrupamiento detectable"
COLAS_GRUESAS, COLAS_NORMALES = "colas gruesas", "colas compatibles con la normal"
CAMBIOS_REGIMEN, REGIMEN_ESTABLE = "cambios de régimen", "régimen estable"
CALMA, NORMAL, AGITACION = "calma", "normal", "agitación"


def factor_anual(intervalo_s: float) -> float:
    """√(velas por año) en un mercado que cotiza 24 horas los 365 días."""
    return math.sqrt(SEGUNDOS_ANO / intervalo_s)


def _rejilla(g: pd.DataFrame) -> pd.DataFrame:
    """La serie en una rejilla regular de `intervalo_s`: las velas que faltan aparecen como filas sin cierre."""
    g = g.sort_values("inicio_utc").drop_duplicates("inicio_utc", keep="last")
    paso = pd.Timedelta(seconds=int(g.intervalo_s.iloc[0]))
    rejilla = pd.date_range(g.inicio_utc.iloc[0], g.inicio_utc.iloc[-1], freq=paso)
    completa = g.set_index("inicio_utc").reindex(rejilla)
    completa.index.name = "inicio_utc"
    for c in SERIE:
        completa[c] = g[c].iloc[0]
    completa["vacia"] = completa["vacia"].astype("boolean").fillna(True).astype(bool)
    completa["completa"] = completa["completa"].astype("boolean").fillna(False).astype(bool)
    return completa.reset_index()


def _por_segmento(serie: pd.Series, segmento: pd.Series, ventana: int, funcion) -> pd.Series:
    validos = serie.dropna()
    if validos.empty:
        return pd.Series(np.nan, index=serie.index)
    rodante = validos.groupby(segmento[validos.index]).rolling(ventana, min_periods=ventana)
    return funcion(rodante).reset_index(level=0, drop=True).reindex(serie.index)


def preparar_retornos(velas: pd.DataFrame, ventana: int = VENTANA_VOL) -> pd.DataFrame:
    """Por serie (fuente, exchange, par, intervalo_s), en rejilla regular: cierre de análisis, retornos simple y
    log, segmento, retorno acumulado y volatilidad móvil y realizada de `ventana` retornos. Todo en t usa solo
    velas hasta t."""
    partes = []
    for _, g in velas.groupby(SERIE, sort=True):
        g = _rejilla(g)
        valido = ~g.vacia & g.completa & g.cierre.notna()
        g["cierre_analisis"] = g.cierre.where(valido)
        nuevo = valido & ~valido.shift(1, fill_value=False)
        g["segmento"] = nuevo.cumsum().where(valido)
        anterior = g.cierre_analisis.shift(1)
        mismo = valido & valido.shift(1, fill_value=False)
        g["ret_simple"] = (g.cierre_analisis / anterior - 1).where(mismo)
        g["ret_log"] = np.log(g.cierre_analisis / anterior).where(mismo)
        primero = g.groupby("segmento").cierre_analisis.transform("first")
        g["ret_acumulado"] = g.cierre_analisis / primero - 1
        g["vol_movil"] = _por_segmento(g.ret_log, g.segmento, ventana, lambda r: r.std(ddof=1))
        g["vol_realizada"] = np.sqrt(_por_segmento(g.ret_log ** 2, g.segmento, ventana, lambda r: r.sum()))
        partes.append(g)
    if not partes:
        return pd.DataFrame(columns=[*SERIE, "inicio_utc", "cierre_analisis", "segmento", "ret_simple", "ret_log",
                                     "ret_acumulado", "vol_movil", "vol_realizada"])
    return pd.concat(partes, ignore_index=True)


def retorno_futuro(retornos: pd.DataFrame, k: int) -> pd.Series:
    """ln(P_{t+k} / P_t) alineado en t (objetivo, no señal); NaN si t + k no está en el mismo segmento que t."""
    if k < 1:
        raise ValueError("El horizonte del retorno futuro debe ser de al menos 1 vela")
    grupos = retornos.groupby(SERIE, sort=False)
    futuro = grupos.cierre_analisis.shift(-k)
    mismo = grupos.segmento.shift(-k) == retornos.segmento
    return np.log(futuro / retornos.cierre_analisis).where(mismo)


def objetivo_conocido_utc(retornos: pd.DataFrame, k: int) -> pd.Series:
    """Cuándo se conoce el retorno futuro de t: al cerrar la vela t + k."""
    inicio = retornos.groupby(SERIE, sort=False).inicio_utc.shift(-k)
    return inicio + pd.to_timedelta(retornos.intervalo_s.astype(float), unit="s")


def _autocorrelaciones(x: pd.Series, segmento: pd.Series, retardos: int) -> tuple[list, int]:
    """ρ_k de x (filas en rejilla) con pares del mismo segmento, y n (valores de x)."""
    validos = x.notna()
    n = int(validos.sum())
    m = x[validos].mean()
    d = (x - m).where(validos)
    denominador = float((d ** 2).sum())
    rho = []
    for k in range(1, retardos + 1):
        mismo = (segmento == segmento.shift(k)) & validos & validos.shift(k, fill_value=False)
        rho.append(float((d * d.shift(k))[mismo].sum() / denominador) if denominador > 0 else math.nan)
    return rho, n


def ljung_box(rho: list, n: int) -> tuple[float, float]:
    """(Q, p-valor) de Ljung-Box con las autocorrelaciones dadas."""
    if n <= len(rho) or any(math.isnan(r) for r in rho):
        return math.nan, math.nan
    q = n * (n + 2) * sum(r ** 2 / (n - k) for k, r in enumerate(rho, start=1))
    return float(q), float(chi2.sf(q, len(rho)))


@dataclass(frozen=True)
class ResultadoRetornos:
    fuente: str
    exchange: str
    par: str
    intervalo_s: int
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_velas: int
    n_vacias: int
    n_incompletas: int
    n_retornos: int
    n_segmentos: int
    minimo: int
    media_log: float
    vol_por_vela: float
    asimetria: float
    curtosis_exceso: float
    frecuencia_colas: float
    rho1_abs: float
    retardos_lb: int
    q_lb: float
    p_lb: float
    ventana_regimen: int
    n_vol_regimen: int
    vol_mediana_anual: float
    fraccion_calma: float
    fraccion_agitacion: float
    regimen_actual: str

    @property
    def vol_anual(self) -> float:
        return self.vol_por_vela * factor_anual(self.intervalo_s)

    @property
    def _segmentos(self) -> str:
        return "segmento" if self.n_segmentos == 1 else "segmentos"

    @property
    def ratio_colas(self) -> float:
        return self.frecuencia_colas / COLA_NORMAL

    @property
    def estado(self) -> str:
        return INSUFICIENTE if self.n_retornos < self.minimo else ANALIZADA

    @property
    def estado_agrupamiento(self) -> str:
        if self.estado == INSUFICIENTE or math.isnan(self.p_lb):
            return INSUFICIENTE
        return AGRUPAMIENTO if self.p_lb < ALFA and self.rho1_abs > 0 else SIN_AGRUPAMIENTO

    @property
    def estado_colas(self) -> str:
        if self.estado == INSUFICIENTE:
            return INSUFICIENTE
        gruesas = self.curtosis_exceso > UMBRAL_CURTOSIS and self.ratio_colas >= RATIO_COLAS
        return COLAS_GRUESAS if gruesas else COLAS_NORMALES

    @property
    def estado_regimen(self) -> str:
        if self.estado == INSUFICIENTE or self.n_vol_regimen < MIN_VENTANAS_REGIMEN * self.ventana_regimen:
            return INSUFICIENTE
        return CAMBIOS_REGIMEN if self.fraccion_agitacion >= MIN_FRACCION_AGITACION else REGIMEN_ESTABLE

    def conclusion(self) -> str:
        cabecera = f"{self.fuente}, {self.exchange}, velas de {self.intervalo_s} s"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_retornos} retornos válidos en {self.n_segmentos} "
                    f"{self._segmentos}; hacen falta {self.minimo}).")
        texto = (f"{cabecera}: volatilidad {self.vol_por_vela * 1e4:.1f} bps por vela, {self.vol_anual:.1%} anual "
                 f"(√(365 · velas por día)) con {self.n_retornos} retornos en {self.n_segmentos} {self._segmentos}. "
                 f"Distribución: asimetría {self.asimetria:+.2f}, curtosis en exceso {self.curtosis_exceso:.2f}, "
                 f"|z| > {Z_COLA:g} en el {self.frecuencia_colas:.2%} ({self.ratio_colas:.1f} veces la normal): "
                 f"{self.estado_colas}. Dependencia de |r|: {self.estado_agrupamiento} (ρ₁ {self.rho1_abs:+.3f}, "
                 f"Ljung-Box Q({self.retardos_lb}) {self.q_lb:.1f}, p {self.p_lb:.3g}).")
        if self.estado_regimen == INSUFICIENTE:
            texto += (f" Regímenes: datos insuficientes ({self.n_vol_regimen} valores de volatilidad móvil; hacen "
                      f"falta {MIN_VENTANAS_REGIMEN * self.ventana_regimen}).")
        else:
            texto += (f" Regímenes ({self.ventana_regimen} velas): {self.estado_regimen}; calma el "
                      f"{self.fraccion_calma:.0%} y agitación el {self.fraccion_agitacion:.0%} del tiempo frente a "
                      f"una mediana de {self.vol_mediana_anual:.1%} anual; ahora: {self.regimen_actual}.")
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "retornos", **asdict(self), "vol_anual": self.vol_anual, "ratio_colas": self.ratio_colas,
                "estado": self.estado, "estado_agrupamiento": self.estado_agrupamiento,
                "estado_colas": self.estado_colas, "estado_regimen": self.estado_regimen,
                "conclusion": self.conclusion()}


def _regimen(vol: float, mediana: float) -> str:
    if vol < UMBRAL_CALMA * mediana:
        return CALMA
    return AGITACION if vol > UMBRAL_AGITACION * mediana else NORMAL


def _estudiar_serie(g: pd.DataFrame, minimo: int, ventana_regimen: int, retardos: int) -> ResultadoRetornos:
    r = g.ret_log.dropna()
    n = len(r)
    sd = float(r.std(ddof=1)) if n > 1 else math.nan
    z = (r - r.mean()) / sd if n > 1 and sd > 0 else pd.Series(dtype=float)
    lags = max(1, min(retardos, n // 5))
    rho, n_abs = _autocorrelaciones(g.ret_log.abs(), g.segmento, lags)
    q, p = ljung_box(rho, n_abs) if n >= minimo else (math.nan, math.nan)
    vol = _por_segmento(g.ret_log, g.segmento, ventana_regimen, lambda x: x.std(ddof=1)).dropna()
    intervalo = int(g.intervalo_s.iloc[0])
    vol_anual = vol * factor_anual(intervalo)
    mediana = float(vol_anual.median()) if len(vol_anual) else math.nan
    estados = vol_anual.map(lambda v: _regimen(v, mediana)) if len(vol_anual) else pd.Series(dtype=str)
    return ResultadoRetornos(
        fuente=g.fuente.iloc[0], exchange=g.exchange.iloc[0], par=g.par.iloc[0], intervalo_s=intervalo,
        desde_utc=g.inicio_utc.iloc[0], hasta_utc=g.inicio_utc.iloc[-1] + pd.Timedelta(seconds=intervalo),
        n_velas=len(g), n_vacias=int(g.vacia.sum()), n_incompletas=int((~g.completa).sum()), n_retornos=n,
        n_segmentos=int(g.segmento.nunique()), minimo=minimo, media_log=float(r.mean()) if n else math.nan,
        vol_por_vela=sd, asimetria=float(r.skew()) if n > 2 else math.nan,
        curtosis_exceso=float(r.kurt()) if n > 3 else math.nan,
        frecuencia_colas=float((z.abs() > Z_COLA).mean()) if len(z) else math.nan,
        rho1_abs=rho[0], retardos_lb=lags, q_lb=q, p_lb=p, ventana_regimen=ventana_regimen,
        n_vol_regimen=len(vol_anual), vol_mediana_anual=mediana,
        fraccion_calma=float((estados == CALMA).mean()) if len(estados) else math.nan,
        fraccion_agitacion=float((estados == AGITACION).mean()) if len(estados) else math.nan,
        regimen_actual=estados.iloc[-1] if len(estados) else INSUFICIENTE)


def estudiar_retornos(velas: pd.DataFrame, minimo: int = MIN_RETORNOS, ventana_regimen: int = VENTANA_REGIMEN,
                      retardos: int = RETARDOS_LB) -> list[ResultadoRetornos]:
    """Un resultado por fuente, exchange, par e intervalo de las velas dadas (formato común)."""
    retornos = preparar_retornos(velas)
    return [_estudiar_serie(g.reset_index(drop=True), minimo, ventana_regimen, retardos)
            for _, g in retornos.groupby(SERIE, sort=True)]


def estudiar_retornos_lake(consultar: Callable[[str], pd.DataFrame], fuente: str = FUENTE_PROPIA,
                           intervalo_s: int | None = None, exchange: str | None = None, tabla: str = FUENTE_VELAS,
                           **opciones) -> list[ResultadoRetornos]:
    """El estudio sobre las velas guardadas (la versión más reciente de cada una) de `fuente` en `tabla`."""
    velas = leer_velas(consultar, fuente, exchange, intervalo_s, tabla=tabla)
    return estudiar_retornos(velas, **opciones) if len(velas) else []


def guardar_estudio_retornos(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_RETORNOS)
