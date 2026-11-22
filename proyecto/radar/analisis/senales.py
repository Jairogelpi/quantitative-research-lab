"""Relaciones entre señales e interacciones (T5) y decaimiento de cada señal (T6), sobre una misma tabla.

Conceptos:
- Tabla de señales: una fila por exchange y ronda con las señales candidatas (imbalance de una banda, OFI
  multinivel y el retorno de los OTROS exchanges en la ronda anterior, la señal del lead-lag), el contexto
  (spread y volatilidad reciente) y el retorno futuro. Todo lo que es señal o contexto usa solo el pasado; la
  señal líder usa la ronda ANTERIOR porque las fotos de otro exchange en la misma ronda pueden llegar más tarde
  que la propia y contener su futuro (`senal_lider`).
- Correlación entre señales (Spearman): si dos señales están muy correlacionadas, miden casi lo mismo y
  sumarlas sería contar dos veces la misma información.
- Regresión conjunta: retorno futuro = a + Σ b_i · señal_i + controles (retorno pasado propio y spread). Una
  señal aporta información PROPIA si sigue siendo significativa con las demás dentro, en las dos mitades.
  Señales estandarizadas (z): los coeficientes son bps por desviación típica y se comparan entre sí.
- Interacción: retorno = a + b · s + c · s · [contexto alto] + d · [contexto alto]. c ≠ 0 significa que la
  señal funciona distinto cuando el spread es ancho o la volatilidad es alta. "Alto" = por encima de la mediana
  de la mitad de descubrimiento (no se mira la confirmación para fijar el umbral).
- Decaimiento: β(k) de retorno(t → t + k) sobre la señal estandarizada, para k creciente. β(k) acumula el
  efecto: crece mientras la señal sigue empujando y se aplana cuando ya se agotó. Tiempo a la mitad: el menor k
  con β(k) ≥ 50 % del pico. Persistencia: β(k máximo) / pico; cerca de 1 = el movimiento queda (información),
  cerca de 0 = se revierte (ruido o presión pasajera).
- Mismo rigor que el resto: errores Newey-West, descubrimiento/confirmación y Benjamini-Hochberg.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from radar.configuracion import INTERVALO_S

from .calidad import FACTOR_HUECO
from .imbalance import ALFA, MARGEN_S, _p_valor, _retardos
from .leadlag import TOLERANCIA_ALINEACION, mids_alineados, retornos
from .ofi import pares_ofi_retorno

FUENTE_SENALES = "estudios_senales"
SENALES = ("imbalance", "ofi", "lider")
CONTEXTOS = ("spread_bps", "volatilidad_bps")
HORIZONTE = 5
HORIZONTES_DECAIMIENTO = (1, 2, 3, 5, 10, 20, 30, 60)
VENTANA_VOL = 60
MIN_FILAS = 500


def tabla_senales(consultar: Callable[[str], pd.DataFrame], banda_bps: float = 5, niveles_ofi: int = 5,
                  horizontes=(HORIZONTE,), intervalo_s: float = INTERVALO_S) -> pd.DataFrame:
    """Una fila por exchange y ronda: imbalance, ofi, lider (retorno medio de los otros exchanges en la ronda
    anterior), spread_bps, volatilidad_bps (desviación de los retornos propios de las últimas `VENTANA_VOL`
    rondas), ret_pasado_bps y `ret_<k>` (retorno futuro a k rondas, bps)."""
    cot = consultar("""SELECT exchange, solicitado_utc, recibido_utc, mid, spread_bps FROM cotizaciones
                       ORDER BY exchange, recibido_utc""")
    imb = consultar(f"""SELECT exchange, recibido_utc, imbalance FROM desequilibrios
                        WHERE banda_bps = {float(banda_bps)} AND imbalance IS NOT NULL""")
    ofi = pares_ofi_retorno(consultar, horizontes=(1,), niveles=(niveles_ofi,), intervalo_s=intervalo_s)
    ofi = ofi[["exchange", "recibido_utc", "imbalance"]].rename(columns={"imbalance": "ofi"})
    r_todos = retornos(mids_alineados(consultar, intervalo_s), intervalo_s)
    partes = []
    for exchange, g in cot.groupby("exchange", sort=True):
        g = g.sort_values("recibido_utc").reset_index(drop=True)
        t = g["recibido_utc"].map(pd.Timestamp.timestamp).to_numpy()
        mid = g["mid"].to_numpy(dtype=float)
        seguidas = np.r_[False, np.diff(t) <= FACTOR_HUECO * intervalo_s]
        propio = np.where(seguidas, (mid / np.r_[np.nan, mid[:-1]] - 1) * 1e4, np.nan)
        g["ret_pasado_bps"] = propio
        g["volatilidad_bps"] = pd.Series(propio).rolling(VENTANA_VOL, min_periods=VENTANA_VOL // 2).std().to_numpy()
        for k in horizontes:
            futuro = np.full(len(g), np.nan)
            if len(g) > k:
                ok = t[k:] - t[:-k] <= k * intervalo_s + MARGEN_S
                futuro[:-k] = np.where(ok, (mid[k:] / mid[:-k] - 1) * 1e4, np.nan)
            g[f"ret_{k}"] = futuro
        lider = senal_lider(r_todos, exchange)
        g = pd.merge_asof(g.sort_values("solicitado_utc"), lider.dropna(), on="solicitado_utc", direction="nearest",
                          tolerance=pd.Timedelta(seconds=TOLERANCIA_ALINEACION * intervalo_s))
        partes.append(g.sort_values("recibido_utc"))
    tabla = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if tabla.empty:
        return tabla
    return (tabla.merge(imb, on=["exchange", "recibido_utc"], how="left")
            .merge(ofi, on=["exchange", "recibido_utc"], how="left")
            .sort_values(["exchange", "recibido_utc"]).reset_index(drop=True))


def senal_lider(r_todos: pd.DataFrame, exchange: str) -> pd.DataFrame:
    """(solicitado_utc, lider): retorno medio de los OTROS exchanges en la ronda ANTERIOR (t − 2 → t − 1).

    No la de la misma ronda: si los otros responden más tarde, su foto de la ronda t ya incluye parte del futuro
    de la foto propia de t (trampa de la latencia). Las fotos de la ronda anterior llegaron, con las latencias
    medidas (< 1 s), antes de que se pidiera la propia. Solo vale si las dos rondas anteriores son seguidas."""
    otros = [c for c in r_todos.columns if c.startswith("r_") and c != f"r_{exchange}"]
    media = r_todos[otros].mean(axis=1, skipna=False)
    seguida = r_todos[otros[0]].notna()  # la ronda t − 1 → t no cruzó un corte
    return r_todos[["solicitado_utc"]].assign(lider=media.shift(1).where(seguida))


def _ols(y: pd.Series, x: pd.DataFrame, horizonte: int):
    return sm.OLS(y, sm.add_constant(x)).fit(cov_type="HAC", cov_kwds={"maxlags": _retardos(len(y), horizonte)})


def _z(df: pd.DataFrame, columnas, referencia: pd.DataFrame) -> pd.DataFrame:
    """Estandariza con la media y la desviación de `referencia` (la mitad de descubrimiento)."""
    salida = df.copy()
    for c in columnas:
        sd = referencia[c].std()
        salida[c] = (df[c] - referencia[c].mean()) / sd if sd > 0 else np.nan
    return salida


# T5 · Correlaciones y regresión conjunta.

@dataclass(frozen=True)
class AporteSenal:
    exchange: str
    senal: str
    horizonte_rondas: int
    n: int
    coef_solo: float          # bps por desviación típica, sola (descubrimiento)
    t_solo: float
    coef_conjunto: float      # con las otras señales y los controles (descubrimiento)
    t_conjunto: float
    coef_conjunto_conf: float
    t_conjunto_conf: float
    correlacion_max: float    # mayor |Spearman| con otra señal
    con_cual: str
    minimo: int

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        propia = (abs(self.t_conjunto) >= 2 and abs(self.t_conjunto_conf) >= 2
                  and np.sign(self.t_conjunto) == np.sign(self.t_conjunto_conf))
        if propia:
            return "aporta información propia"
        if abs(self.t_solo) >= 2:
            return "redundante con las demás"
        return "sin evidencia"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, {self.senal}, horizonte {self.horizonte_rondas}"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} filas; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. Sola {self.coef_solo:+.3f} bps por desviación (t {self.t_solo:.2f}); con "
                f"las demás {self.coef_conjunto:+.3f} (t {self.t_conjunto:.2f}), confirmación {self.coef_conjunto_conf:+.3f} "
                f"(t {self.t_conjunto_conf:.2f}); correlación máxima {self.correlacion_max:+.2f} con {self.con_cual}.")

    def a_fila(self) -> dict:
        return {"estudio": "aporte", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def correlaciones(tabla: pd.DataFrame, exchange: str) -> pd.DataFrame:
    """Spearman entre las señales y el contexto de un exchange."""
    return tabla.loc[tabla.exchange == exchange, list(SENALES) + list(CONTEXTOS)].corr(method="spearman")


def aporte_senales(tabla: pd.DataFrame, horizonte: int = HORIZONTE, minimo: int = MIN_FILAS) -> list[AporteSenal]:
    y_col, resultados = f"ret_{horizonte}", []
    controles = ["ret_pasado_bps", "spread_bps"]
    for exchange, g in tabla.groupby("exchange", sort=True):
        g = g.dropna(subset=list(SENALES) + controles + [y_col]).reset_index(drop=True)
        mitad = len(g) // 2
        d, c = g.iloc[:mitad], g.iloc[mitad:]
        corr = g[list(SENALES)].corr(method="spearman")
        if min(len(d), len(c)) < minimo:
            for s in SENALES:
                resultados.append(AporteSenal(exchange, s, horizonte, min(len(d), len(c)), *[math.nan] * 6,
                                              math.nan, "", minimo))
            continue
        dz, cz = _z(d, SENALES, d), _z(c, SENALES, d)
        conj_d = _ols(dz[y_col], dz[list(SENALES) + controles], horizonte)
        conj_c = _ols(cz[y_col], cz[list(SENALES) + controles], horizonte)
        for s in SENALES:
            solo = _ols(dz[y_col], dz[[s] + controles], horizonte)
            otras = corr[s].drop(s).abs()
            resultados.append(AporteSenal(
                exchange, s, horizonte, min(len(d), len(c)), float(solo.params[s]), float(solo.tvalues[s]),
                float(conj_d.params[s]), float(conj_d.tvalues[s]), float(conj_c.params[s]), float(conj_c.tvalues[s]),
                float(corr.loc[s, otras.idxmax()]), str(otras.idxmax()), minimo))
    return resultados


# T5 · Interacciones con el contexto.

@dataclass(frozen=True)
class Interaccion:
    exchange: str
    senal: str
    contexto: str
    horizonte_rondas: int
    n: int
    umbral: float
    coef_bajo: float          # efecto de la señal con contexto bajo (descubrimiento)
    coef_interaccion: float   # cuánto cambia con contexto alto (descubrimiento)
    t_interaccion: float
    p_descubrimiento: float
    p_ajustado: float
    coef_interaccion_conf: float
    t_interaccion_conf: float
    minimo: int

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        if not self.p_ajustado < ALFA:
            return "sin evidencia"
        if np.sign(self.t_interaccion_conf) == np.sign(self.t_interaccion) and abs(self.t_interaccion_conf) >= 2:
            return "confirmada"
        return "no confirmada fuera de muestra"

    def conclusion(self) -> str:
        nombre, alto, bajo = {"spread_bps": ("el spread", "alto", "bajo"),
                              "volatilidad_bps": ("la volatilidad", "alta", "baja")}[self.contexto]
        cabecera = (f"{self.exchange}, {self.senal} × {nombre} {alto} (> {self.umbral:.3f} bps), "
                    f"horizonte {self.horizonte_rondas}")
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} filas; hacen falta {self.minimo})."
        alto_total = self.coef_bajo + self.coef_interaccion  # efecto de la señal con contexto alto
        bajo_ignorable = abs(self.coef_bajo) < 0.2 * abs(alto_total)  # sin efecto con contexto bajo
        if np.sign(alto_total) != np.sign(self.coef_bajo) and not bajo_ignorable:
            sentido = "de signo contrario"
        else:
            sentido = "más fuerte" if abs(alto_total) > abs(self.coef_bajo) else "más débil"
        texto = (f"{cabecera}: {self.estado}. Efecto con {nombre} {bajo} {self.coef_bajo:+.3f} bps por desviación; con "
                 f"{nombre} {alto} cambia {self.coef_interaccion:+.3f} (t {self.t_interaccion:.2f}, p ajustado "
                 f"{self.p_ajustado:.3f}); confirmación {self.coef_interaccion_conf:+.3f} (t {self.t_interaccion_conf:.2f}).")
        return texto + (f" La señal es {sentido} cuando {nombre} es {alto}." if self.estado == "confirmada" else "")

    def a_fila(self) -> dict:
        return {"estudio": "interaccion", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def interacciones(tabla: pd.DataFrame, horizonte: int = HORIZONTE, minimo: int = MIN_FILAS) -> list[Interaccion]:
    y_col, borradores = f"ret_{horizonte}", []
    for (exchange, g), s, ctx in ((eg, s, c) for eg in tabla.groupby("exchange", sort=True)
                                  for s, c in itertools.product(SENALES, CONTEXTOS)):
        g = g.dropna(subset=[s, ctx, y_col]).reset_index(drop=True)
        mitad = len(g) // 2
        d, c = g.iloc[:mitad], g.iloc[mitad:]
        n = min(len(d), len(c))
        fila = dict(exchange=exchange, senal=s, contexto=ctx, horizonte_rondas=horizonte, n=n, minimo=minimo)
        if n < minimo:
            borradores.append({**fila, "umbral": math.nan, "coef_bajo": math.nan, "coef_interaccion": math.nan,
                               "t_interaccion": math.nan, "p_descubrimiento": math.nan,
                               "coef_interaccion_conf": math.nan, "t_interaccion_conf": math.nan})
            continue
        umbral = float(d[ctx].median())
        estimados = []
        for parte in (d, c):
            z = _z(parte, [s], d)
            alto = (parte[ctx] > umbral).astype(float)
            x = pd.DataFrame({"s": z[s], "s_alto": z[s] * alto, "alto": alto})
            modelo = _ols(parte[y_col], x, horizonte)
            estimados.append((float(modelo.params["s"]), float(modelo.params["s_alto"]), float(modelo.tvalues["s_alto"])))
        (bajo, inter, t1), (_, inter2, t2) = estimados
        borradores.append({**fila, "umbral": umbral, "coef_bajo": bajo, "coef_interaccion": inter, "t_interaccion": t1,
                           "p_descubrimiento": _p_valor(t1), "coef_interaccion_conf": inter2, "t_interaccion_conf": t2})
    validos = [i for i, b in enumerate(borradores) if b["n"] >= minimo and not math.isnan(b["p_descubrimiento"])]
    ajustados = multipletests([borradores[i]["p_descubrimiento"] for i in validos], method="fdr_bh")[1] if validos else []
    p = dict(zip(validos, ajustados))
    return [Interaccion(**b, p_ajustado=float(p.get(i, math.nan))) for i, b in enumerate(borradores)]


# T6 · Decaimiento.

@dataclass(frozen=True)
class Decaimiento:
    exchange: str
    senal: str
    horizontes: tuple
    betas: tuple              # bps por desviación típica, retorno acumulado a cada horizonte
    ts: tuple
    n: int
    minimo: int

    @property
    def significativo(self) -> bool:
        return any(abs(t) >= 2 for t in self.ts if not math.isnan(t))

    @property
    def pico(self) -> tuple[int, float]:
        i = int(np.nanargmax(np.abs(self.betas)))
        return self.horizontes[i], self.betas[i]

    @property
    def tiempo_mitad(self) -> int:
        _, b = self.pico
        return next(h for h, x in zip(self.horizontes, self.betas) if np.sign(x) == np.sign(b) and abs(x) >= abs(b) / 2)

    @property
    def persistencia(self) -> float:
        return self.betas[-1] / self.pico[1] if self.pico[1] else math.nan

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return "datos insuficientes"
        return "con efecto" if self.significativo else "sin evidencia"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, {self.senal}"
        if self.estado == "datos insuficientes":
            return f"{cabecera}: datos insuficientes ({self.n} filas; hacen falta {self.minimo})."
        if self.estado == "sin evidencia":
            return f"{cabecera}: sin evidencia en ningún horizonte ({self.n} filas)."
        h, b = self.pico
        destino = ("el movimiento se queda (información)" if self.persistencia >= 0.75 else
                   "se revierte en parte" if self.persistencia >= 0.25 else "se revierte casi todo (presión pasajera)")
        curva = ", ".join(f"{hh}: {bb:+.3f}" for hh, bb in zip(self.horizontes, self.betas))
        return (f"{cabecera}: pico de {b:+.3f} bps por desviación a {h} rondas; la mitad del efecto llega a "
                f"{self.tiempo_mitad} rondas; a {self.horizontes[-1]} rondas queda el {self.persistencia:.0%}: {destino}. "
                f"Curva [{curva}]."
                + (" El pico está en el último horizonte: el efecto puede seguir creciendo más allá."
                   if h == self.horizontes[-1] else ""))

    def a_fila(self) -> dict:
        fila = {"estudio": "decaimiento", "exchange": self.exchange, "senal": self.senal, "n": self.n,
                "estado": self.estado, "conclusion": self.conclusion()}
        if self.estado == "con efecto":
            fila.update(pico_rondas=self.pico[0], pico_bps=self.pico[1], tiempo_mitad_rondas=self.tiempo_mitad,
                        persistencia=self.persistencia)
        return fila


def decaimiento(tabla: pd.DataFrame, horizontes=HORIZONTES_DECAIMIENTO, minimo: int = MIN_FILAS) -> list[Decaimiento]:
    resultados = []
    for (exchange, g), s in itertools.product(tabla.groupby("exchange", sort=True), SENALES):
        g = g.dropna(subset=[s] + [f"ret_{k}" for k in horizontes]).reset_index(drop=True)
        if len(g) < minimo or g[s].std() == 0:
            resultados.append(Decaimiento(exchange, s, tuple(horizontes), (), (), len(g), minimo))
            continue
        z = _z(g, [s], g)
        betas, ts = [], []
        for k in horizontes:
            m = _ols(g[f"ret_{k}"], z[[s]], k)
            betas.append(float(m.params[s]))
            ts.append(float(m.tvalues[s]))
        resultados.append(Decaimiento(exchange, s, tuple(horizontes), tuple(betas), tuple(ts), len(g), minimo))
    return resultados
