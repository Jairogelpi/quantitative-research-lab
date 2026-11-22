"""Respuesta del precio a un trade: cuánto del movimiento que provoca se queda (impacto permanente) y cuánto se
revierte (transitorio). Función de respuesta y modelo del propagador de Bouchaud (S5).

Conceptos:
- Evento: un trade, o varios seguidos del mismo exchange con la MISMA hora de recepción y el mismo signo (una
  orden de mercado que se come varios niveles se publica como varias ejecuciones; contarlas por separado infla
  la correlación de signos a retardo 1). ε_n = +1 si el agresor compró y −1 si vendió. m_n = mid del último
  cambio del libro ESTRICTAMENTE anterior al evento n (`mids_exactos`, desde `eventos_libro`), como el p_n del
  modelo, que suma solo los trades n' < n.
- Función de respuesta en tiempo de eventos: R(ℓ) = ⟨ε_n · (m_{n+ℓ} − m_n)⟩, en bps sobre m_n y en medios
  spreads (R en bps entre el medio spread cotizado medio de los mismos eventos; dividir trade a trade lo dominan
  los instantes con el spread casi cerrado). Es cuánto se mueve el mid, a favor del agresor, ℓ trades después.
- En tiempo físico: R(τ) = ⟨ε_n · (m(t_n + τ) − m_n)⟩, con m(t) el mid del último cambio antes de t.
- Correlación de signos: C(ℓ) = ⟨ε_n ε_{n+ℓ}⟩ − ⟨ε⟩². En los mercados de órdenes decae como C(ℓ) ≈ C₀ / ℓ^γ con
  γ < 1 (memoria larga: las órdenes grandes se parten en muchas pequeñas del mismo signo). γ sale de una recta en
  escala log-log sobre los retardos con C(ℓ) significativamente positiva (C > 2 errores); con menos de
  `MIN_PUNTOS_GAMMA`, "datos insuficientes".
- Modelo del propagador: m_n = Σ_{n'<n} G(n − n') ε_n' + ruido. G(ℓ) es el impacto de UN trade aislado ℓ trades
  después. De ahí, con C sin centrar (C(0) = 1): R(ℓ) = Σ_{0≤k<ℓ} G(ℓ − k) C(k) + Σ_{k>0} [G(ℓ + k) − G(k)] C(k).
  R mezcla el impacto de un trade con el de los siguientes, que por la memoria de signos suelen ir en la misma
  dirección. Suponiendo G constante desde `retardo_max` L, el segundo sumatorio se corta en L sin error y las L
  ecuaciones con R(1..L) y C(1..L) medidos forman un sistema lineal que da G(1..L).
- Permanente frente a transitorio: R_pico = el máximo de R en la rejilla hasta L/2 (antes de la meseta, para no
  elegir el ruido de los retardos largos); R_largo = la media de R en [L/2, L] (la meseta). Persistencia =
  R_largo / R_pico: la parte del movimiento que se queda; 1 − persistencia, la que se revierte. Lo mismo con G:
  G_largo / G(1) es la parte del impacto de un trade aislado que se queda (meseta en [L/2, L), sin G(L), que
  absorbe el corte del sistema). Clasificación con el intervalo persistencia ± 2 errores: entero por encima de
  `UMBRAL_PERMANENTE`, impacto permanente; entero por debajo de `UMBRAL_TRANSITORIO`, mayormente transitorio;
  entero entre los dos, mixto; si cruza un umbral, persistencia sin determinar (faltan datos para decidirlo).
- Errores por bloques (jackknife con `BLOQUES` tramos contiguos): cada par (n, n + ℓ) cuenta en el bloque de n y
  se repite el cálculo quitando un bloque cada vez. Los signos tienen memoria larga, así que un Newey-West con el
  ancho de banda habitual (unas decenas de retardos) corta la autocorrelación demasiado pronto y subestima el
  error; los bloques contiguos, de miles de trades, la recogen casi entera. El mismo jackknife da los errores de
  cocientes (persistencia), de γ y de G sin fórmulas aparte.
- Mitades: la persistencia se calcula también en la primera y la segunda mitad de los eventos (en el tiempo); si
  la clasificación cambia entre ellas, la conclusión lo dice.
- Ventana `desde_utc`: el libro se reconstruye desde el último snapshot anterior (la captura solo recibe uno al
  conectar, cada hora); empezar un minuto antes, sin snapshot, dejaría sin mid todo hasta el siguiente.
- Un par cuyo trade posterior está tras un hueco de captura (más de `HUECO_S` sin trades) no cuenta, y un mid con
  más de `ANTIGUEDAD_MAX_S` de antigüedad tampoco.
- Fuentes verificadas: Bouchaud, Gefen, Potters y Wyart (2004), "Fluctuations and response in financial markets:
  the subtle nature of 'random' price changes", Quantitative Finance 4, 176-190 (arXiv cond-mat/0307332): R(ℓ) es
  su ec. (3), C₀(ℓ) la (6) y su ley de potencia la (7) (γ ≈ 1/5 en France Telecom, 2/3 en Total; Lillo y Farmer,
  ≈ 1/2 en Vodafone), el modelo es la (12) y la relación R-G-C la (17); aquí sin el factor ln V (volumen) de sus
  ecuaciones, es decir, con el modelo en signos solamente. Marco general: Bouchaud, Bonart, Donier y Gould (2018),
  "Trades, Quotes and Prices", Cambridge University Press.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .liquidez import _libros, mids_exactos
from .markouts import _segundos

FUENTE_RESPUESTA = "estudios_respuesta"
RETARDO_MAX = 200                       # L, en trades
TAUS_S = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300)
BLOQUES = 20
MIN_EVENTOS = 1000
MIN_PUNTOS_GAMMA = 5
UMBRAL_PERMANENTE = 0.8
UMBRAL_TRANSITORIO = 0.5
HUECO_S = 300.0
ANTIGUEDAD_MAX_S = 60.0
MARGEN_LIBRO_S = 60                     # libro reconstruido desde un minuto antes del primer trade


def _rejilla(retardo_max: int) -> list[int]:
    base = [1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 100, 150, 200, 300, 500, 700, 1000]
    return sorted({r for r in base if r <= retardo_max} | {retardo_max})


def eventos_trades(libros: pd.DataFrame, trades: pd.DataFrame, agrupar: bool = True) -> pd.DataFrame:
    """Un evento por trade (o por grupo de trades seguidos con la misma hora de recepción y signo, si `agrupar`) con
    mid estrictamente anterior: exchange, t, recibido_utc, signo, cantidad, n_trades, mid_antes, cotizado_bps."""
    columnas = ["exchange", "t", "recibido_utc", "signo", "cantidad", "n_trades", "mid_antes", "cotizado_bps"]
    por_exchange, partes = _libros(libros), []
    for exchange, g in trades.groupby("exchange", sort=True):
        if exchange not in por_exchange:
            continue
        lb = por_exchange[exchange]
        g = g.sort_values("recibido_utc", kind="stable")
        t = _segundos(g["recibido_utc"])
        signo = np.where(g["lado_agresor"].to_numpy() == "buy", 1.0, -1.0)
        cantidad = g["cantidad"].to_numpy(dtype=float)
        if agrupar and len(t):
            nuevo = np.r_[True, (np.diff(t) != 0) | (np.diff(signo) != 0)]
            grupo = np.cumsum(nuevo) - 1
            primero = np.flatnonzero(nuevo)
            cantidad = np.bincount(grupo, weights=cantidad)
            n_trades = np.bincount(grupo)
            t, signo, recibido = t[primero], signo[primero], g["recibido_utc"].to_numpy()[primero]
        else:
            n_trades, recibido = np.ones(len(t), dtype=int), g["recibido_utc"].to_numpy()
        i = np.searchsorted(lb.t, t, side="left") - 1
        ok = (i >= 0) & (t - lb.t[np.maximum(i, 0)] <= ANTIGUEDAD_MAX_S)
        partes.append(pd.DataFrame({"exchange": exchange, "t": t[ok], "recibido_utc": recibido[ok],
                                    "signo": signo[ok], "cantidad": cantidad[ok], "n_trades": n_trades[ok],
                                    "mid_antes": lb.mid[i[ok]], "cotizado_bps": lb.cotizado[i[ok]]}))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=columnas)


class _Sumas:
    """Sumas por bloque de una media (Σ x y número de pares): la media total y las que quitan un bloque."""

    def __init__(self, bloques: int):
        self.b = bloques
        self.s: list[np.ndarray] = []
        self.c: list[np.ndarray] = []

    def anadir(self, x: np.ndarray, bloque: np.ndarray):
        ok = np.isfinite(x)
        self.s.append(np.bincount(bloque[ok], weights=x[ok], minlength=self.b))
        self.c.append(np.bincount(bloque[ok], minlength=self.b).astype(float))

    def medias(self, cuales=None) -> tuple[np.ndarray, np.ndarray]:
        """(media total por fila, matriz filas × bloques de medias sin ese bloque). `cuales`: bloques a usar."""
        s, c = np.array(self.s), np.array(self.c)
        if cuales is not None:
            s, c = s[:, cuales], c[:, cuales]
        with np.errstate(invalid="ignore", divide="ignore"):
            total = s.sum(1) / c.sum(1)
            sin = (s.sum(1, keepdims=True) - s) / (c.sum(1, keepdims=True) - c)
        return total, sin


def _jackknife(replicas: np.ndarray) -> np.ndarray:
    """Error jackknife por columnas de una matriz réplicas × estadísticos (ignora réplicas no finitas)."""
    replicas = np.atleast_2d(replicas)
    salida = np.full(replicas.shape[1], math.nan)
    for j in range(replicas.shape[1]):
        r = replicas[:, j][np.isfinite(replicas[:, j])]
        if len(r) >= 2:
            salida[j] = math.sqrt((len(r) - 1) / len(r) * np.sum((r - r.mean()) ** 2))
    return salida


def propagador_desde_respuesta(r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """G(1..L) del sistema R(ℓ) = Σ_{0≤k<ℓ} G(ℓ − k) C(k) + Σ_{0<k≤L} [G(min(ℓ + k, L)) − G(k)] C(k), ℓ = 1..L,
    con C(0) = 1 y `r`, `c` los valores en 1..L (C sin centrar)."""
    L = len(r)
    if L == 0 or not (np.all(np.isfinite(r)) and np.all(np.isfinite(c))):
        return np.full(L, math.nan)
    cc = np.r_[1.0, c]
    a = np.zeros((L, L))
    for ell in range(1, L + 1):
        for k in range(ell):
            a[ell - 1, ell - k - 1] += cc[k]
        for k in range(1, L + 1):
            a[ell - 1, min(ell + k, L) - 1] += cc[k]
            a[ell - 1, k - 1] -= cc[k]
    try:
        return np.linalg.solve(a, r)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(a, r, rcond=None)[0]


def _persistencia(curva: np.ndarray, rejilla_idx: np.ndarray, largo_idx: np.ndarray) -> float:
    pico = np.nanmax(curva[rejilla_idx]) if np.any(np.isfinite(curva[rejilla_idx])) else math.nan
    largo = float(np.nanmean(curva[largo_idx])) if np.any(np.isfinite(curva[largo_idx])) else math.nan
    return largo / pico if pico and pico > 0 else math.nan


def _clase(p: float, error: float = 0.0) -> str:
    """Clase de la persistencia con su intervalo p ± 2 · error (error 0: solo el valor)."""
    if not math.isfinite(p):
        return "sin evidencia"
    if not math.isfinite(error):
        return "persistencia sin determinar"
    bajo, alto = p - 2 * error, p + 2 * error
    if bajo >= UMBRAL_PERMANENTE:
        return "impacto permanente"
    if alto < UMBRAL_TRANSITORIO:
        return "impacto mayormente transitorio"
    if bajo >= UMBRAL_TRANSITORIO and alto < UMBRAL_PERMANENTE:
        return "impacto mixto"
    return "persistencia sin determinar"


def _gamma(retardos: np.ndarray, c: np.ndarray) -> float:
    ok = np.isfinite(c) & (c > 0)
    if ok.sum() < 2:
        return math.nan
    pendiente = np.polyfit(np.log(retardos[ok]), np.log(c[ok]), 1)[0]
    return float(-pendiente)


def _pc(x: float) -> str:
    return f"{x * 100:.0f} %" if math.isfinite(x) else "n/d"


@dataclass(frozen=True)
class Respuesta:
    exchange: str
    n_eventos: int
    n_trades: int
    retardos: list
    r_bps: list
    error_r_bps: list
    r_medio_spread: list
    error_r_medio_spread: list
    c: list
    error_c: list
    propagador_bps: list
    error_propagador_bps: list
    taus_s: list
    r_tiempo_bps: list
    error_r_tiempo_bps: list
    r_tiempo_medio_spread: list
    r1_bps: float
    error_r1_bps: float
    r_pico_bps: float
    retardo_pico: int
    r_largo_bps: float
    error_r_largo_bps: float
    persistencia: float
    error_persistencia: float
    persistencia_mitades: list
    persistencia_propagador: float
    error_persistencia_propagador: float
    gamma: float
    error_gamma: float
    n_puntos_gamma: int
    medio_spread_bps: float
    hasta_utc: pd.Timestamp
    minimo: int
    retardo_max: int = field(default=RETARDO_MAX)

    @property
    def t_r1(self) -> float:
        return self.r1_bps / self.error_r1_bps if self.error_r1_bps else math.nan

    @property
    def estado(self) -> str:
        if self.n_eventos < self.minimo:
            return "datos insuficientes"
        if not (abs(self.t_r1) >= 2 and self.r1_bps > 0):
            return "sin evidencia"
        return _clase(self.persistencia, self.error_persistencia)

    @property
    def estado_gamma(self) -> str:
        if self.n_puntos_gamma < MIN_PUNTOS_GAMMA or not math.isfinite(self.gamma):
            return "datos insuficientes"
        return "medido"

    @property
    def estable_mitades(self) -> bool:
        return len({_clase(p) for p in self.persistencia_mitades}) == 1

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, respuesta del precio a un trade (Bouchaud)"
        if self.estado == "datos insuficientes":
            return (f"{cabecera}: datos insuficientes ({self.n_eventos} eventos; hacen falta {self.minimo}).")
        if self.estado == "sin evidencia":
            return (f"{cabecera}: sin evidencia. R(1) = {self.r1_bps:+.3f} bps (error {self.error_r1_bps:.3f}): "
                    f"el mid no se mueve de forma medible a favor del agresor. {self.n_eventos} eventos.")
        queda = self.persistencia
        texto = (f"{cabecera}: {self.estado}. R(1) = {self.r1_bps:+.3f} bps (error {self.error_r1_bps:.3f}, "
                 f"{self.r1_bps / self.medio_spread_bps:.2f} medios spreads de {self.medio_spread_bps:.3f} bps); "
                 f"pico {self.r_pico_bps:+.3f} bps a {self.retardo_pico} trades; entre {self.retardo_max // 2} y "
                 f"{self.retardo_max} trades queda {self.r_largo_bps:+.3f} bps (error {self.error_r_largo_bps:.3f}): "
                 + (f"el {_pc(queda)} del impacto se queda (error {_pc(self.error_persistencia)}) y el "
                    f"{_pc(1 - queda)} se revierte." if queda < 1 else
                    f"no se revierte nada: a largo plazo el movimiento es el {_pc(queda)} del pico (error "
                    f"{_pc(self.error_persistencia)}); los trades siguientes, del mismo signo, siguen empujando."))
        if math.isfinite(self.persistencia_propagador):
            texto += (f" Propagador (impacto de un trade aislado, sin el de los que le siguen): se queda el "
                      f"{_pc(self.persistencia_propagador)} (error {_pc(self.error_persistencia_propagador)}).")
        if not self.estable_mitades:
            p1, p2 = self.persistencia_mitades
            texto += f" Inestable entre mitades: {_pc(p1)} en la primera y {_pc(p2)} en la segunda."
        if self.estado_gamma == "medido":
            texto += (f" Signos: C(1) = {self.c[0]:.3f}; decae como ℓ^−γ con γ = {self.gamma:.2f} (error "
                      f"{self.error_gamma:.2f}, {self.n_puntos_gamma} retardos).")
        else:
            texto += f" Signos: C(1) = {self.c[0]:.3f}; ley de potencia: datos insuficientes."
        return texto + f" {self.n_eventos} eventos ({self.n_trades} trades)."

    def a_fila(self) -> dict:
        return {"estudio": "respuesta_precio", **asdict(self), "t_r1": self.t_r1, "estado": self.estado,
                "estado_gamma": self.estado_gamma, "estable_mitades": self.estable_mitades,
                "conclusion": self.conclusion()}


def _respuesta_exchange(exchange: str, ev: pd.DataFrame, lb, retardo_max: int, taus_s, bloques: int,
                        minimo: int) -> Respuesta:
    n = len(ev)
    t, eps = ev["t"].to_numpy(float), ev["signo"].to_numpy(float)
    m, hs = ev["mid_antes"].to_numpy(float), ev["cotizado_bps"].to_numpy(float) / 2
    medio = float(np.nanmean(np.where(hs > 0, hs, np.nan))) if n and np.any(hs > 0) else math.nan
    tramo = np.cumsum(np.r_[0, np.diff(t) > HUECO_S]) if n else np.array([], int)
    bloque = (np.arange(n) * bloques // max(n, 1)).astype(np.intp)
    L = int(retardo_max)
    rejilla = _rejilla(L)
    idx = np.array(rejilla) - 1
    largo_idx = np.arange(L // 2 - 1 if L >= 2 else 0, L)
    pico_idx = idx[idx <= max(L // 2 - 1, 0)]
    largo_g = largo_idx[:-1] if len(largo_idx) > 1 else largo_idx
    hasta = pd.Timestamp(ev["recibido_utc"].max()) if n else pd.NaT

    r, cs = _Sumas(bloques), _Sumas(bloques)
    for ell in range(1, L + 1):
        if ell >= n:
            vacio = np.zeros(0)
            for s in (r, cs):
                s.anadir(vacio, np.zeros(0, np.intp))
            continue
        ok = tramo[ell:] == tramo[:-ell]
        dm = (m[ell:] / m[:-ell] - 1) * 1e4 * eps[:-ell]
        x = np.where(ok, dm, np.nan)
        r.anadir(x, bloque[:-ell])
        cs.anadir(np.where(ok, eps[ell:] * eps[:-ell], np.nan), bloque[:-ell])
    media_eps = _Sumas(bloques)
    media_eps.anadir(eps, bloque)
    eps_tot, eps_sin = media_eps.medias()

    rt, rt_sin = r.medias()
    ct, ct_sin = cs.medias()                          # sin centrar
    cc, cc_sin = ct - eps_tot[0] ** 2, ct_sin - eps_sin[0] ** 2

    # Tiempo físico.
    rf = _Sumas(bloques)
    for tau in taus_s:
        objetivo = t + tau
        j = np.searchsorted(lb.t, objetivo, side="left") - 1
        ok = (j >= 0) & (objetivo <= lb.t[-1]) & (objetivo - lb.t[np.maximum(j, 0)] <= ANTIGUEDAD_MAX_S)
        x = np.where(ok, (lb.mid[np.maximum(j, 0)] / m - 1) * 1e4 * eps, np.nan)
        rf.anadir(x, bloque)
    rft, rft_sin = rf.medias() if len(taus_s) else (np.array([]), np.zeros((0, bloques)))

    # Propagador, persistencias y γ, en el total y en cada réplica.
    def estadisticos(rr, cc_sin_centrar, ccentrada):
        g = propagador_desde_respuesta(rr, cc_sin_centrar) if n > L else np.full(L, math.nan)
        p = _persistencia(rr, pico_idx, largo_idx)
        largo = float(np.nanmean(rr[largo_idx])) if np.any(np.isfinite(rr[largo_idx])) else math.nan
        pg = (float(np.nanmean(g[largo_g])) / g[0]) if np.isfinite(g[0]) and g[0] > 0 else math.nan
        return g, p, largo, pg, ccentrada

    g, p, largo, pg, _ = estadisticos(rt, ct, cc)
    err_c_full = _jackknife(cc_sin.T)
    puntos = [i for i in idx if np.isfinite(cc[i]) and cc[i] > 2 * err_c_full[i]]
    puntos = np.array(puntos, dtype=int)
    gamma = _gamma(puntos + 1.0, cc[puntos]) if len(puntos) >= 2 else math.nan
    replicas = []
    for b in range(bloques):
        gb, pb, lb_, pgb, _ = estadisticos(rt_sin[:, b], ct_sin[:, b], cc_sin[:, b])
        gam_b = _gamma(puntos + 1.0, cc_sin[puntos, b]) if len(puntos) >= 2 else math.nan
        replicas.append(np.r_[pb, lb_, pgb, gam_b, gb[idx]])
    errores = _jackknife(np.array(replicas))
    err_p, err_largo, err_pg, err_gamma, err_g = errores[0], errores[1], errores[2], errores[3], errores[4:]

    mitad = bloques // 2
    mitades = []
    for cuales in (np.arange(mitad), np.arange(mitad, bloques)):
        rm, _ = r.medias(cuales)
        mitades.append(_persistencia(rm, pico_idx, largo_idx))

    err_r = _jackknife(rt_sin.T)
    pico_i = int(pico_idx[np.nanargmax(rt[pico_idx])]) if np.any(np.isfinite(rt[pico_idx])) else 0
    lista = lambda a: [float(v) for v in a]
    return Respuesta(
        exchange=exchange, n_eventos=n, n_trades=int(ev["n_trades"].sum()) if n else 0, retardos=rejilla,
        r_bps=lista(rt[idx]), error_r_bps=lista(err_r[idx]), r_medio_spread=lista(rt[idx] / medio),
        error_r_medio_spread=lista(err_r[idx] / medio), c=lista(cc[idx]), error_c=lista(err_c_full[idx]),
        propagador_bps=lista(g[idx]), error_propagador_bps=lista(err_g), taus_s=[float(x) for x in taus_s],
        r_tiempo_bps=lista(rft), error_r_tiempo_bps=lista(_jackknife(rft_sin.T)) if len(taus_s) else [],
        r_tiempo_medio_spread=lista(rft / medio), r1_bps=float(rt[0]), error_r1_bps=float(err_r[0]),
        r_pico_bps=float(rt[pico_i]), retardo_pico=pico_i + 1, r_largo_bps=largo, error_r_largo_bps=float(err_largo),
        persistencia=float(p), error_persistencia=float(err_p), persistencia_mitades=lista(mitades),
        persistencia_propagador=float(pg), error_persistencia_propagador=float(err_pg), gamma=float(gamma),
        error_gamma=float(err_gamma), n_puntos_gamma=int(len(puntos)),
        medio_spread_bps=medio, hasta_utc=hasta, minimo=minimo, retardo_max=L)


def respuesta_precio(libros: pd.DataFrame, trades: pd.DataFrame, retardo_max: int = RETARDO_MAX, taus_s=TAUS_S,
                     bloques: int = BLOQUES, minimo: int = MIN_EVENTOS, agrupar: bool = True) -> list[Respuesta]:
    """Función de respuesta, correlación de signos y propagador por exchange. `libros`: cambios del mid
    (`mids_exactos`: exchange, recibido_ns, mid, cotizado_bps) o fotos de `libros_flujo`."""
    ev, por_exchange = eventos_trades(libros, trades, agrupar), _libros(libros)
    return [_respuesta_exchange(ex, g.reset_index(drop=True), por_exchange[ex], retardo_max, taus_s, bloques, minimo)
            for ex, g in ev.groupby("exchange", sort=True)]


def _inicio_libro(consultar: Callable[[str], pd.DataFrame], desde_utc):
    """Desde dónde reconstruir el libro: el último snapshot anterior a `desde_utc` (el más antiguo de entre los
    exchanges), porque sin snapshot no hay libro y la captura solo los recibe al conectar (cada hora). Sin snapshot
    previo, `MARGEN_LIBRO_S` antes."""
    if desde_utc is None:
        return None
    desde = pd.Timestamp(desde_utc)
    previos = consultar("SELECT exchange, max(recibido_utc) AS ultimo FROM eventos_libro WHERE tipo = 'snapshot' "
                        f"AND recibido_utc <= TIMESTAMPTZ '{desde.isoformat()}' GROUP BY exchange")
    if previos.empty or previos["ultimo"].isna().all():
        return desde - pd.Timedelta(seconds=MARGEN_LIBRO_S)
    return min(pd.Timestamp(previos["ultimo"].min()), desde - pd.Timedelta(seconds=MARGEN_LIBRO_S))


def estudiar_respuesta(consultar: Callable[[str], pd.DataFrame], desde_utc=None, retardo_max: int = RETARDO_MAX,
                       taus_s=TAUS_S, minimo: int = MIN_EVENTOS) -> list[Respuesta]:
    """Respuesta del precio con los trades desde `desde_utc` y el mid exacto de `eventos_libro` (si no hay, las
    fotos de `libros_flujo`, con hasta 1 s de antigüedad)."""
    filtro = "" if desde_utc is None else f" WHERE recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}'"
    trades = consultar("SELECT exchange, recibido_utc, precio, cantidad, lado_agresor FROM trades"
                       f"{filtro} ORDER BY exchange, recibido_utc")
    vistas = set(consultar("SELECT table_name FROM information_schema.tables")["table_name"])
    if "eventos_libro" in vistas:
        libros = mids_exactos(consultar, _inicio_libro(consultar, desde_utc))
    else:
        libros = consultar("SELECT * FROM libros_flujo ORDER BY exchange, recibido_utc")
    return respuesta_precio(libros, trades, retardo_max, taus_s, minimo=minimo)


def guardar_estudio_respuesta(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in resultados], FUENTE_RESPUESTA)
