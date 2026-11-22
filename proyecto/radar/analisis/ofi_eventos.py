"""OFI evento a evento: el Order Flow Imbalance original, calculado con cada mensaje del libro del websocket (Fase 3).

Conceptos:
- Fuente: Cont, Kukanov y Stoikov (2014), "The Price Impact of Order Book Events", Journal of Financial
  Econometrics 12(1), 47-88 (arXiv:1011.6402). Para cada evento n del libro, con P y q el precio y la cantidad
  del mejor bid (B) y del mejor ask (A) justo después del evento (n) y justo antes (n−1):
      e_n = q^B_n·1[P^B_n ≥ P^B_{n−1}] − q^B_{n−1}·1[P^B_n ≤ P^B_{n−1}]
            − q^A_n·1[P^A_n ≤ P^A_{n−1}] + q^A_{n−1}·1[P^A_n ≥ P^A_{n−1}]
  Bid igual: e = q^B_n − q^B_{n−1} (cantidad que llegó o se fue). Bid que sube: e = q^B_n (orden que mejora el
  precio). Bid que baja: e = −q^B_{n−1} (la cola entera se fue, por trades o cancelaciones). En el ask, al revés.
- Evento = mensaje del websocket: el libro se reconstruye con `hayashi_yoshida._recorrer_libro` (snapshot +
  actualizaciones, buffer y continuidad de secuencia en Bitvavo, truncado en Kraken; un libro cruzado no publica)
  y e_n se calcula tras cada mensaje. Un mensaje que cambia varios niveles cuenta como un solo evento: lo que
  importa es el mejor nivel antes y después del mensaje.
- OFI de un intervalo: OFI_k = Σ e_n de los eventos de [t_{k−1}, t_k) (rejilla de Δ segundos sobre la hora de
  recepción). ΔP_k = (mid al final de k − mid al final de k−1) / tick, como en el artículo (y también en bps).
  Un intervalo sin eventos tiene OFI 0 y ΔP 0. La diferencia con `ofi.py`: allí el OFI sale de comparar dos fotos
  de 1 s y se pierde todo lo que pasó entre ellas (una orden que llega y se va no cuenta).
- Tramos: el OFI solo se suma dentro de un libro reconstruido de forma continua. Un snapshot nuevo (el libro se
  rehízo desde cero) o un hueco de más de `HUECO_S` segundos sin mensajes empieza un tramo; el primer intervalo
  de cada tramo se descarta porque no hay mid anterior fiable.
- Impacto contemporáneo: ΔP_k = α + β·OFI_k, con errores Newey-West (HAC) y R², por exchange y Δ. El artículo
  usa Δ = 10 s y encuentra R² altos (≈ 65 % de media): el OFI explica el movimiento del MISMO intervalo.
- Profundidad: el artículo define AD_i = media de (q^B_n + q^A_n) / 2 en cada media hora y propone
  β_i = c / AD_i^λ (λ = 1 en su modelo estilizado: con más cantidad en el mejor nivel, cada BTC mueve menos el
  precio). Aquí β_i se estima en cada ventana de `VENTANA_PROFUNDIDAD_S` y se ajusta log β_i = log c − λ log AD_i.
- Comparación: el R² del OFI de las fotos de 1 s (`ofi.impacto_contemporaneo`, mejor nivel) en la misma ventana.
- Predicción: el OFI del intervalo k frente a ΔP del intervalo k+1 (mismo tramo), con descubrimiento en la
  primera mitad, confirmación en la segunda y Benjamini-Hochberg sobre todas las pruebas.

Estados del impacto: datos insuficientes (menos de `minimo` intervalos), explica el precio (|t HAC| ≥ 2) y sin
evidencia. Estados de la predicción: datos insuficientes, sin evidencia (no significativa tras BH), no confirmada
fuera de muestra (la segunda mitad no repite el signo con |t| ≥ 2) y confirmada.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from .hayashi_yoshida import NS, PARAMETROS_LIBRO, _dentro, eventos_flujo, mejores_desde_eventos
from .imbalance import (ALFA, CONFIRMADA, INSUFICIENTE, NO_CONFIRMADA, SIN_EVIDENCIA, T_CONFIRMACION, _p_valor,
                        _retardos, _t)
from .ofi import impacto_contemporaneo, ofi, pares_ofi_retorno

METODO = "ofi_eventos/v1"
FUENTE_OFI_EVENTOS = "estudios_ofi_eventos"
INTERVALOS_S = (1.0, 10.0)
TICKS = {"kraken": 0.1, "okx": 0.1, "bitvavo": 1.0}   # tick de BTC/EUR (`captura/exchanges/__init__.py`)
HUECO_S = 30.0
MIN_INTERVALOS = 200
VENTANA_PROFUNDIDAD_S = 1800.0                         # media hora, como en el artículo
MIN_POR_VENTANA = 30
MIN_VENTANAS = 3
EXPLICA = "explica el precio"


def contribuciones(bp, bq, ap, aq) -> np.ndarray:
    """e_n de cada evento n ≥ 1 a partir del mejor nivel tras cada evento (vectores de la misma longitud).
    Es la fórmula de `ofi.ofi` con un solo nivel."""
    columna = lambda x: np.asarray(x, float)[:, None]
    return ofi(columna(bp), columna(bq), columna(ap), columna(aq))


def _tick(g: pd.DataFrame, exchange: str, ticks: dict) -> float:
    """Tick conocido o, si no, el menor salto positivo observado entre precios del mejor bid."""
    if exchange in ticks:
        return float(ticks[exchange])
    saltos = np.diff(np.unique(g["bid"].to_numpy(float)))
    return float(np.round(saltos.min(), 10)) if len(saltos) else math.nan


COLUMNAS_INTERVALOS = ["exchange", "intervalo_s", "intervalo", "inicio_ns", "fin_ns", "tramo", "n_eventos", "ofi",
                       "dp_ticks", "dp_bps", "dp_siguiente_ticks", "dp_siguiente_bps", "profundidad"]


def intervalos_ofi(mejores: pd.DataFrame, intervalos_s=INTERVALOS_S, ticks: dict | None = None,
                   hueco_s: float = HUECO_S) -> pd.DataFrame:
    """Una fila por exchange, Δ e intervalo: OFI_k, ΔP_k (ticks y bps), el ΔP del intervalo siguiente del mismo
    tramo, número de eventos y profundidad media (q^B + q^A) / 2 de sus eventos.

    `mejores`: exchange y las columnas de `hayashi_yoshida.mejores_desde_eventos`. La rejilla de cada Δ está
    alineada con el reloj (múltiplos de Δ desde 1970) y `intervalo` se numera desde el primero del exchange."""
    ticks = TICKS if ticks is None else ticks
    partes = []
    for exchange, g in mejores.groupby("exchange", sort=True):
        g = g.sort_values("recibido_ns", kind="stable").reset_index(drop=True)
        t = g["recibido_ns"].to_numpy(np.int64)
        tramo_libro = g["tramo"].to_numpy()
        nuevo = np.r_[True, (tramo_libro[1:] != tramo_libro[:-1]) | (np.diff(t) > hueco_s * NS)]
        tramo = np.cumsum(nuevo)
        e = np.r_[math.nan, contribuciones(g["bid"], g["bid_cantidad"], g["ask"], g["ask_cantidad"])]
        e[nuevo] = math.nan                                  # el primer evento de un tramo no tiene anterior
        mid = ((g["bid"] + g["ask"]) / 2).to_numpy(float)
        profundidad = ((g["bid_cantidad"] + g["ask_cantidad"]) / 2).to_numpy(float)
        tick = _tick(g, exchange, ticks)
        for intervalo_s in intervalos_s:
            dns = int(round(intervalo_s * NS))
            celda = t // dns
            agregado = (pd.DataFrame({"tramo": tramo, "celda": celda, "e": e, "mid": mid, "prof": profundidad})
                        .groupby(["tramo", "celda"], sort=True)
                        .agg(ofi=("e", "sum"), mid=("mid", "last"), n_eventos=("e", "size"),
                             profundidad=("prof", "mean")))
            for numero, a in agregado.groupby(level="tramo", sort=True):
                a = a.droplevel("tramo")
                rejilla = a.reindex(np.arange(a.index.min(), a.index.max() + 1))
                rejilla["ofi"] = rejilla["ofi"].fillna(0.0)
                rejilla["n_eventos"] = rejilla["n_eventos"].fillna(0).astype(int)
                rejilla["mid"] = rejilla["mid"].ffill()
                previo = rejilla["mid"].shift()
                dp = rejilla["mid"] - previo
                parte = pd.DataFrame({
                    "exchange": exchange, "intervalo_s": float(intervalo_s),
                    "intervalo": rejilla.index - celda[0], "inicio_ns": rejilla.index * dns,
                    "fin_ns": (rejilla.index + 1) * dns, "tramo": int(numero), "n_eventos": rejilla["n_eventos"],
                    "ofi": rejilla["ofi"], "dp_ticks": dp / tick, "dp_bps": dp / previo * 1e4,
                    "profundidad": rejilla["profundidad"]})
                parte["dp_siguiente_ticks"] = parte["dp_ticks"].shift(-1)
                parte["dp_siguiente_bps"] = parte["dp_bps"].shift(-1)
                partes.append(parte.iloc[1:])
    if not partes:
        return pd.DataFrame(columns=COLUMNAS_INTERVALOS)
    return pd.concat(partes, ignore_index=True)[COLUMNAS_INTERVALOS]


# --- estudio --------------------------------------------------------------------------------------------------------

def _hora(ns) -> pd.Timestamp:
    return pd.Timestamp(int(ns), tz="UTC")


@dataclass(frozen=True)
class ImpactoEventos:
    exchange: str
    intervalo_s: float
    n: int
    n_eventos: int
    beta_ticks_por_btc: float
    beta_bps_por_btc: float
    t_hac: float
    r2: float
    profundidad_media_btc: float
    c_profundidad: float          # β_i ≈ c / AD_i^λ entre ventanas de media hora
    lambda_profundidad: float
    t_lambda: float
    ventanas_profundidad: int
    r2_fotos: float               # R² del OFI de las fotos de 1 s (mejor nivel) en la misma ventana
    minimo: int
    desde_utc: pd.Timestamp = pd.NaT
    hasta_utc: pd.Timestamp = pd.NaT   # fin del último intervalo usado: la revalidación empieza después

    @property
    def estado(self) -> str:
        if self.n < self.minimo or not math.isfinite(self.t_hac):
            return INSUFICIENTE
        return EXPLICA if abs(self.t_hac) >= 2 else SIN_EVIDENCIA

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, OFI por eventos cada {self.intervalo_s:g} s"
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n} intervalos; hacen falta {self.minimo})."
        texto = (f"{cabecera}: {self.estado}. Cada BTC de OFI neto mueve el mid {self.beta_ticks_por_btc:+.3f} ticks "
                 f"({self.beta_bps_por_btc:+.4f} bps) en el mismo intervalo (t HAC {self.t_hac:.1f}); R² "
                 f"{self.r2:.1%} ({self.n} intervalos, {self.n_eventos} mensajes del libro).")
        if math.isfinite(self.lambda_profundidad):
            texto += (f" Profundidad media {self.profundidad_media_btc:.3f} BTC; entre {self.ventanas_profundidad} "
                      f"ventanas de media hora, β ≈ c / AD^λ con λ {self.lambda_profundidad:.2f} (t "
                      f"{self.t_lambda:.1f}; el modelo del artículo predice 1) y c {self.c_profundidad:.3f}.")
        else:
            texto += (f" Profundidad media {self.profundidad_media_btc:.3f} BTC; sin ventanas suficientes para "
                      f"relacionar β con la profundidad.")
        if math.isfinite(self.r2_fotos):
            texto += f" Con el OFI de las fotos de 1 s, en la misma ventana, el R² es {self.r2_fotos:.1%}."
        return texto

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


@dataclass(frozen=True)
class PrediccionEventos:
    exchange: str
    intervalo_s: float
    n_descubrimiento: int
    n_confirmacion: int
    beta_descubrimiento: float    # ticks del intervalo siguiente por BTC de OFI
    t_descubrimiento: float
    r2_descubrimiento: float
    p_valor: float
    p_ajustado: float
    beta_confirmacion: float
    t_confirmacion: float
    minimo: int
    desde_utc: pd.Timestamp = pd.NaT
    hasta_utc: pd.Timestamp = pd.NaT

    @property
    def estado(self) -> str:
        if min(self.n_descubrimiento, self.n_confirmacion) < self.minimo:
            return INSUFICIENTE
        if not self.p_ajustado < ALFA:
            return SIN_EVIDENCIA
        if np.sign(self.t_confirmacion) == np.sign(self.t_descubrimiento) and abs(self.t_confirmacion) >= T_CONFIRMACION:
            return CONFIRMADA
        return NO_CONFIRMADA

    def conclusion(self) -> str:
        cabecera = (f"{self.exchange}, ¿anticipa el OFI de un intervalo de {self.intervalo_s:g} s el movimiento del "
                    f"siguiente?")
        if self.estado == INSUFICIENTE:
            return (f"{cabecera} datos insuficientes ({min(self.n_descubrimiento, self.n_confirmacion)} intervalos "
                    f"en la mitad más pobre; hacen falta {self.minimo}).")
        return (f"{cabecera} {self.estado}: {self.beta_descubrimiento:+.4f} ticks por BTC en la primera "
                f"mitad (t {self.t_descubrimiento:.1f}, R² {self.r2_descubrimiento:.2%}, p ajustado "
                f"{self.p_ajustado:.3f}); en la segunda, {self.beta_confirmacion:+.4f} (t {self.t_confirmacion:.1f}).")

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def _ajuste(y: np.ndarray, x: np.ndarray, hac: bool = True) -> tuple[float, float, float]:
    """(β, t, R²) de y = α + β·x; t con errores Newey-West si `hac`."""
    modelo = sm.OLS(y, sm.add_constant(x, has_constant="add"))
    ajuste = modelo.fit(cov_type="HAC", cov_kwds={"maxlags": _retardos(len(y), 1)}) if hac else modelo.fit()
    return float(ajuste.params[1]), _t(float(ajuste.params[1]), float(ajuste.bse[1])), float(ajuste.rsquared)


def _media_ponderada(valores, pesos) -> float:
    v, w = np.asarray(valores, float), np.asarray(pesos, float)
    ok = np.isfinite(v) & (w > 0)
    return float(np.average(v[ok], weights=w[ok])) if ok.any() else math.nan


def _profundidad(g: pd.DataFrame) -> tuple[float, float, float, int]:
    """(c, λ, t de λ, ventanas) de log β_i = log c − λ log AD_i, con β_i y AD_i de cada ventana de media hora."""
    betas, profundidades = [], []
    for _, v in g.groupby(g["inicio_ns"] // int(VENTANA_PROFUNDIDAD_S * NS), sort=True):
        if len(v) < MIN_POR_VENTANA or v["ofi"].nunique() < 2:
            continue
        beta = _ajuste(v["dp_ticks"].to_numpy(float), v["ofi"].to_numpy(float), hac=False)[0]
        ad = _media_ponderada(v["profundidad"], v["n_eventos"])   # media por evento, como AD_i del artículo
        if beta > 0 and ad > 0:
            betas.append(beta)
            profundidades.append(ad)
    if len(betas) < MIN_VENTANAS or len(set(profundidades)) < 2:
        return math.nan, math.nan, math.nan, len(betas)
    ajuste = sm.OLS(np.log(betas), sm.add_constant(np.log(profundidades))).fit()
    return (float(math.exp(ajuste.params[0])), float(-ajuste.params[1]), float(-ajuste.tvalues[1]), len(betas))


def estudiar_ofi_eventos(intervalos: pd.DataFrame, minimo: int = MIN_INTERVALOS, r2_fotos: dict | None = None
                         ) -> tuple[list[ImpactoEventos], list[PrediccionEventos]]:
    """Impacto contemporáneo (con la relación con la profundidad) y predicción, por exchange y Δ.
    `intervalos` como `intervalos_ofi`; `r2_fotos`: {exchange: R² del OFI de las fotos}, p. ej. de `r2_fotos`."""
    impactos, borradores = [], []
    for (exchange, intervalo_s), g in intervalos.groupby(["exchange", "intervalo_s"], sort=True):
        g = g.dropna(subset=["dp_ticks", "ofi"]).sort_values("inicio_ns")
        if g.empty:
            continue
        horas = dict(desde_utc=_hora(g["inicio_ns"].iloc[0]), hasta_utc=_hora(g["fin_ns"].iloc[-1]))
        n = len(g)
        beta = beta_bps = t = r2 = math.nan
        if n >= minimo and g["ofi"].nunique() >= 2:
            x = g["ofi"].to_numpy(float)
            beta, t, r2 = _ajuste(g["dp_ticks"].to_numpy(float), x)
            beta_bps = _ajuste(g["dp_bps"].to_numpy(float), x)[0]
        c, lam, t_lam, ventanas = _profundidad(g)
        impactos.append(ImpactoEventos(
            exchange, float(intervalo_s), n, int(g["n_eventos"].sum()), beta, beta_bps, t, r2,
            _media_ponderada(g["profundidad"], g["n_eventos"]), c, lam, t_lam, ventanas,
            float((r2_fotos or {}).get(exchange, math.nan)), minimo, **horas))

        d = g.dropna(subset=["dp_siguiente_ticks"])
        mitad = len(d) // 2
        partes = (d.iloc[:mitad], d.iloc[mitad:])
        fila = dict(exchange=exchange, intervalo_s=float(intervalo_s), n_descubrimiento=len(partes[0]),
                    n_confirmacion=len(partes[1]), beta_descubrimiento=math.nan, t_descubrimiento=math.nan,
                    r2_descubrimiento=math.nan, p_valor=math.nan, beta_confirmacion=math.nan,
                    t_confirmacion=math.nan, minimo=minimo, **horas)
        if min(len(p) for p in partes) >= minimo and all(p["ofi"].nunique() >= 2 for p in partes):
            (b_d, t_d, r2_d), (b_c, t_c, _) = (_ajuste(p["dp_siguiente_ticks"].to_numpy(float),
                                                        p["ofi"].to_numpy(float)) for p in partes)
            fila.update(beta_descubrimiento=b_d, t_descubrimiento=t_d, r2_descubrimiento=r2_d, p_valor=_p_valor(t_d),
                        beta_confirmacion=b_c, t_confirmacion=t_c)
        borradores.append(fila)
    validos = [i for i, f in enumerate(borradores) if math.isfinite(f["p_valor"])]
    ajustados = multipletests([borradores[i]["p_valor"] for i in validos], method="fdr_bh")[1] if validos else []
    p = dict(zip(validos, ajustados))
    predicciones = [PrediccionEventos(**f, p_ajustado=float(p.get(i, math.nan))) for i, f in enumerate(borradores)]
    return impactos, predicciones


def mejores_flujo(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None,
                  exchanges=None) -> pd.DataFrame:
    """El mejor nivel tras cada mensaje de cada exchange, reconstruido desde `eventos_libro` con los parámetros de
    `PARAMETROS_LIBRO`. Reconstruir es lento (unos segundos por hora de flujo): acotar con `desde_utc`."""
    partes = [_dentro(mejores_desde_eventos(eventos, **PARAMETROS_LIBRO.get(ex, {})), desde_utc).assign(exchange=ex)
              for ex, eventos in eventos_flujo(consultar, desde_utc, hasta_utc, exchanges)]
    partes = [p for p in partes if not p.empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def r2_fotos(consultar: Callable[[str], pd.DataFrame], desde_utc, hasta_utc, minimo: int = MIN_INTERVALOS) -> dict:
    """{exchange: R²} del OFI del mejor nivel entre las fotos de 1 s de `libros` en la ventana dada."""
    ventana = (f"(SELECT * FROM libros WHERE recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}' "
               f"AND recibido_utc <= TIMESTAMPTZ '{pd.Timestamp(hasta_utc).isoformat()}')")
    pares = pares_ofi_retorno(consultar, horizontes=(1,), niveles=(1,), fuente=ventana)
    return {i.exchange: i.r2 for i in impacto_contemporaneo(pares, minimo)}


def estudio_ofi_eventos(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None,
                        intervalos_s=INTERVALOS_S, ticks: dict | None = None, minimo: int = MIN_INTERVALOS,
                        con_fotos: bool = True, exchanges=None, hueco_s: float = HUECO_S):
    """De `eventos_libro` al estudio completo en la ventana; con `con_fotos`, compara con el OFI de `libros`."""
    mejores = mejores_flujo(consultar, desde_utc, hasta_utc, exchanges)
    if mejores.empty:
        return [], []
    intervalos = intervalos_ofi(mejores, intervalos_s, ticks, hueco_s)
    comparacion = {}
    if con_fotos and not intervalos.empty:
        comparacion = r2_fotos(consultar, _hora(intervalos["inicio_ns"].min()), _hora(intervalos["fin_ns"].max()),
                               minimo)
    return estudiar_ofi_eventos(intervalos, minimo, comparacion)


def guardar_ofi_eventos(impactos, predicciones, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución en `estudios_ofi_eventos`; `hasta_utc` dice hasta dónde llegaban los datos."""
    filas = [{"estudio": "ofi_eventos_impacto", **i.a_fila()} for i in impactos]
    filas += [{"estudio": "ofi_eventos_prediccion", **p.a_fila()} for p in predicciones]
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **f}
                            for f in filas], FUENTE_OFI_EVENTOS)
