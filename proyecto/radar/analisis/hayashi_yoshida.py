"""Lead-lag en milisegundos con el estimador de Hayashi-Yoshida sobre el flujo del websocket (Fase 2).

Conceptos:
- Datos asíncronos: cada exchange publica cuando cambia SU libro, no a la vez que los demás. Remuestrear a rondas
  de 1 s (como `leadlag.py`) tira toda la información por debajo del segundo e introduce el efecto Epps (la
  correlación medida cae al acortar el intervalo porque los relojes de observación no coinciden).
- Mid desde los eventos: los eventos guardados son cambios de nivel (no hay un evento "mejor nivel"), así que el
  libro se reconstruye mensaje a mensaje (snapshot + actualizaciones, cantidad 0 = borrar) y se anota el mid
  cada vez que cambia, con la hora de recepción y la del exchange del mensaje que lo cambió. No se usa
  `libros_flujo` (una foto por segundo): eso volvería a ser remuestrear.
- Covarianza de Hayashi-Yoshida (Hayashi y Yoshida, 2005, "On covariance estimation of non-synchronously observed
  diffusion processes", Bernoulli 11(2), 359-379): con los intervalos entre observaciones de cada serie,
  I = (t_{i-1}, t_i] para X y J = (s_{j-1}, s_j] para Y,
      U = Σ_I Σ_J ΔX(I) · ΔY(J) · 1{I ∩ J ≠ ∅}.
  Solo multiplica incrementos cuyos intervalos se solapan; los que no se solapan no aportan nada. No necesita
  remuestrear ni rellenar precios, y sin ruido es insesgado para la covariación.
- Correlación HY: U / √(Σ ΔX(I)² · Σ ΔY(J)²).
- Lead-lag de Hoffmann, Rosenbaum y Yoshida (2013, "Estimation of the lead-lag parameter from non-synchronous
  data", Bernoulli 19(2), 426-461; arXiv:1303.4871): X lidera a Y en θ > 0 si (X_t, Y_{t+θ}) es una
  semimartingala. Se desplazan los intervalos de Y, J_{−θ} = (s_{j-1} − θ, s_j − θ], y
      U(θ) = Σ_I Σ_J ΔX(I) · ΔY(J) · 1{I ∩ J_{−θ} ≠ ∅};   θ̂ = argmax_{θ ∈ rejilla} |U(θ)|.
  Aquí θ > 0 significa que el primer exchange del par (orden alfabético) lidera al segundo.
- Cálculo exacto en toda la rejilla de una vez: el par (I, J) cuenta para los θ del intervalo abierto
  (s_{j-1} − t_i, s_j − t_{i-1}); se suma su producto en esos puntos con un array de diferencias. Horas en
  nanosegundos enteros, sin errores de redondeo en los bordes.
- Curva, rejilla y refinamiento: θ en ±`RANGO_S` con paso `PASO_S`; alrededor del máximo se afina a
  `PASO_FINO_S`. Retornos en bps del logaritmo del mid.
- Significación por sustitutos (rotación circular): se rota la serie del segundo exchange al menos
  `MIN_ROTACION_S` (mucho más que cualquier adelanto de la rejilla). Cada serie conserva su ritmo, su
  volatilidad y su autocorrelación, pero se rompe la relación entre las dos. p = (1 + #{max|ρ| sustituto ≥
  observado}) / (1 + N). Con `N_SUSTITUTOS` = 199 el p mínimo (0,005) puede superar Benjamini-Hochberg con las
  6 pruebas (3 pares × 2 bases: 0,05 / 6 ≈ 0,0083), que con 99 (0,01) no podría.
- Robustez: descubrimiento en la primera mitad y confirmación en la segunda (deben dar el mismo signo de θ),
  walk-forward en `VENTANAS` tramos y el lead-lag ratio de Huth y Abergel (2014) sobre la curva:
  Σ ρ²(θ > 0) / Σ ρ²(θ < 0).
- Dos bases de tiempo: horas de RECEPCIÓN (todas en nuestro reloj; contaminadas por diferencias de latencia) y
  horas del EXCHANGE (sin latencia de red; contaminadas por el desfase relativo de sus relojes). La
  incertidumbre de cada base sale de `relojes.py`; un adelanto menor que ella no se distingue de un artefacto.

Estados de cada par y base:
- datos insuficientes: menos de `minimo` cambios de mid de algún exchange en alguna mitad.
- sin evidencia: el máximo de |ρ| no supera a los sustitutos tras Benjamini-Hochberg.
- simultáneo: correlados, pero θ̂ está a menos de un paso de 0.
- no confirmada fuera de muestra: las dos mitades no dan el mismo signo de θ que la muestra entera.
- confirmada: el mismo signo en la muestra entera y en las dos mitades.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from radar.captura.flujo.parametros import PROFUNDIDAD_KRAKEN

from .imbalance import ALFA, CONFIRMADA, INSUFICIENTE, NO_CONFIRMADA, SIN_EVIDENCIA, T_CONFIRMACION, VENTANAS
from .relojes import EXCHANGE, RECEPCION, incertidumbre_lead_lag

METODO = "hayashi_yoshida/v1"
FUENTE_HY = "estudios_hayashi_yoshida"
NS = 1_000_000_000
RANGO_S = 5.0
PASO_S = 0.01
PASO_FINO_S = 0.001
N_SUSTITUTOS = 199
MIN_CAMBIOS = 500
MIN_ROTACION_S = 60.0
BLOQUES_VENTAJA = 10           # tramos de la segunda mitad para el t de la ventaja de θ̂ sobre θ = 0
LIMITE_PARES = 2_000_000       # pares (I, J) por bloque: acota la memoria (~100 MB)
MAX_BUFFER = 5000              # mensajes de Bitvavo guardados a la espera del snapshot (como la captura)
SIN_HORA = np.iinfo(np.int64).min  # NaT en nanosegundos
SIMULTANEO = "simultáneo"
BASES = (RECEPCION, EXCHANGE)
PARAMETROS_LIBRO = {"bitvavo": {"con_buffer": True}, "kraken": {"profundidad": PROFUNDIDAD_KRAKEN}}


# --- mid desde los eventos ------------------------------------------------------------------------------------------

def _ns(serie: pd.Series) -> np.ndarray:
    return pd.to_datetime(serie, utc=True).dt.tz_convert(None).to_numpy().astype("datetime64[ns]").astype(np.int64)


def _recorrer_libro(eventos: pd.DataFrame, con_buffer: bool = False, profundidad: int | None = None):
    """Reconstruye el libro de UN exchange mensaje a mensaje. Tras cada mensaje que deja un libro válido y sin
    cruzar, produce (recibido_ns, exchange_ns, mejor bid, su cantidad, mejor ask, su cantidad, tramo); `tramo`
    cuenta los snapshots aplicados, así que cambia cada vez que el libro se reconstruye desde cero.

    `eventos`: recibido_utc, hora_exchange_utc, tipo, lado, precio, cantidad, secuencia (una fila por nivel, como
    `eventos_libro`). Un mensaje = filas seguidas con la misma hora de recepción y tipo. Reglas de `sincronizacion`:
    antes del primer snapshot no hay libro; con `con_buffer` (Bitvavo) las actualizaciones que llegan sin libro se
    guardan y, al llegar el snapshot, se aplican las de secuencia mayor; un hueco de secuencia invalida el libro
    hasta el siguiente snapshot. Con `profundidad` (Kraken) el libro se trunca tras cada mensaje. Un libro cruzado
    no publica nada.
    """
    if eventos.empty:
        return
    eventos = eventos.sort_values("recibido_utc", kind="stable")
    rec, hora = _ns(eventos["recibido_utc"]), _ns(eventos["hora_exchange_utc"])
    snap = (eventos["tipo"] == "snapshot").to_numpy()
    bid = (eventos["lado"] == "bid").to_numpy()
    precio, cantidad = eventos["precio"].to_numpy(float), eventos["cantidad"].to_numpy(float)
    secuencia = eventos["secuencia"].to_numpy(float)
    cortes = np.flatnonzero((np.diff(rec) != 0) | (np.diff(snap.astype(np.int8)) != 0)) + 1
    inicios, finales = np.r_[0, cortes].tolist(), np.r_[cortes, len(rec)].tolist()
    rec_l, hora_l, snap_l, bid_l = rec.tolist(), hora.tolist(), snap.tolist(), bid.tolist()
    precio_l, cantidad_l, sec_l = precio.tolist(), cantidad.tolist(), secuencia.tolist()

    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    estado = {"bb": -math.inf, "ba": math.inf, "sucio_b": False, "sucio_a": False}
    valido, ultima, tramo = False, math.nan, 0
    buffer: deque[tuple[float, int, int]] = deque(maxlen=MAX_BUFFER)

    def aplicar(i0: int, i1: int):
        for k in range(i0, i1):
            p, c = precio_l[k], cantidad_l[k]
            if bid_l[k]:
                if c > 0:
                    bids[p] = c
                    if p > estado["bb"]:
                        estado["bb"] = p
                elif bids.pop(p, None) is not None and p >= estado["bb"]:
                    estado["sucio_b"] = True
            else:
                if c > 0:
                    asks[p] = c
                    if p < estado["ba"]:
                        estado["ba"] = p
                elif asks.pop(p, None) is not None and p <= estado["ba"]:
                    estado["sucio_a"] = True

    for i0, i1 in zip(inicios, finales):
        seq = sec_l[i0]
        if snap_l[i0]:
            bids.clear()
            asks.clear()
            aplicar(i0, i1)
            estado.update(sucio_b=True, sucio_a=True)
            valido, ultima, tramo = True, seq, tramo + 1
            if con_buffer:
                for s, j0, j1 in sorted(b for b in buffer if not (b[0] <= seq)):
                    if not math.isnan(ultima) and s != ultima + 1:
                        valido = False
                        break
                    aplicar(j0, j1)
                    ultima = s
                buffer.clear()
        else:
            if not valido:
                if con_buffer:
                    buffer.append((seq, i0, i1))
                continue
            if con_buffer and not math.isnan(seq):
                if seq <= ultima:
                    continue
                if seq != ultima + 1:   # hueco: el libro deja de ser fiable hasta el próximo snapshot
                    valido = False
                    buffer.clear()
                    buffer.append((seq, i0, i1))
                    continue
                ultima = seq
            aplicar(i0, i1)
        if profundidad:
            for lado, mas_alejados in ((bids, heapq.nsmallest), (asks, heapq.nlargest)):
                sobran = len(lado) - profundidad
                if sobran > 0:
                    for p in mas_alejados(sobran, lado):
                        del lado[p]
        if estado["sucio_b"]:
            estado.update(bb=max(bids) if bids else -math.inf, sucio_b=False)
        if estado["sucio_a"]:
            estado.update(ba=min(asks) if asks else math.inf, sucio_a=False)
        if not valido or not bids or not asks or estado["bb"] >= estado["ba"]:
            continue
        bb, ba = estado["bb"], estado["ba"]
        yield rec_l[i0], hora_l[i0], bb, bids[bb], ba, asks[ba], tramo


def mids_desde_eventos(eventos: pd.DataFrame, con_buffer: bool = False, profundidad: int | None = None) -> pd.DataFrame:
    """Cada cambio del mid del libro reconstruido por `_recorrer_libro` (mismas reglas y parámetros).

    Salida: recibido_ns, exchange_ns (SIN_HORA si falta), mid y cotizado_bps (spread en ese momento; solo se emite
    cuando cambia el mid, así que un cambio de spread con el mismo mid no añade fila).
    """
    salida_r, salida_h, salida_m, salida_s, ultimo_mid = [], [], [], [], math.nan
    for rec, hora, bb, _, ba, _, _ in _recorrer_libro(eventos, con_buffer, profundidad):
        mid = (bb + ba) / 2
        if mid != ultimo_mid:
            salida_r.append(rec)
            salida_h.append(hora)
            salida_m.append(mid)
            salida_s.append((ba - bb) / mid * 1e4)  # spread cotizado en ese momento (bps)
            ultimo_mid = mid
    return pd.DataFrame({"recibido_ns": np.array(salida_r, np.int64), "exchange_ns": np.array(salida_h, np.int64),
                         "mid": np.array(salida_m, float), "cotizado_bps": np.array(salida_s, float)})


COLUMNAS_MEJORES = ["recibido_ns", "exchange_ns", "bid", "bid_cantidad", "ask", "ask_cantidad", "tramo"]


def mejores_desde_eventos(eventos: pd.DataFrame, con_buffer: bool = False,
                          profundidad: int | None = None) -> pd.DataFrame:
    """El mejor nivel tras CADA mensaje con libro válido (aunque no cambie): base del OFI evento a evento.
    Columnas `COLUMNAS_MEJORES`; `tramo` cambia con cada snapshot (el libro se reconstruyó desde cero)."""
    filas = list(_recorrer_libro(eventos, con_buffer, profundidad))
    columnas = list(zip(*filas)) if filas else [[]] * len(COLUMNAS_MEJORES)
    tipos = (np.int64, np.int64, float, float, float, float, np.int64)
    return pd.DataFrame({c: np.array(v, t) for c, v, t in zip(COLUMNAS_MEJORES, columnas, tipos)})


def eventos_flujo(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None, exchanges=None):
    """(exchange, eventos de `eventos_libro` de ese exchange, ordenados por recepción), uno a uno: el filtro va en
    DuckDB para no cargar todo el lake.

    Con `desde_utc`, los eventos empiezan en el último SNAPSHOT anterior a `desde_utc`, no en `desde_utc`: la captura
    solo recibe un snapshot al conectar (cada tramo de una hora) y sin él no hay libro. Quien reconstruye devuelve
    después solo lo que cae dentro de la ventana (`_dentro`)."""
    hasta = "" if hasta_utc is None else f" AND recibido_utc <= TIMESTAMPTZ '{pd.Timestamp(hasta_utc).isoformat()}'"
    nombres = exchanges or consultar("SELECT DISTINCT exchange FROM eventos_libro ORDER BY 1")["exchange"].tolist()
    for ex in nombres:
        desde = ""
        if desde_utc is not None:
            inicio = pd.Timestamp(desde_utc)
            previo = consultar(f"""SELECT max(recibido_utc) AS t FROM eventos_libro WHERE exchange = '{ex}'
                                   AND tipo = 'snapshot' AND recibido_utc <= TIMESTAMPTZ '{inicio.isoformat()}'""")
            if not previo.empty and pd.notna(previo["t"].iloc[0]):
                inicio = pd.Timestamp(previo["t"].iloc[0])
            desde = f" AND recibido_utc >= TIMESTAMPTZ '{inicio.isoformat()}'"
        yield ex, consultar(f"""SELECT recibido_utc, hora_exchange_utc, tipo, lado, precio, cantidad, secuencia
                                FROM eventos_libro WHERE exchange = '{ex}'{desde}{hasta} ORDER BY recibido_utc""")


def _dentro(filas: pd.DataFrame, desde_utc) -> pd.DataFrame:
    """Solo las filas (con `recibido_ns`) desde `desde_utc`: lo anterior sirvió para reconstruir el libro."""
    if desde_utc is None or filas.empty:
        return filas
    return filas[filas["recibido_ns"] >= pd.Timestamp(desde_utc).value].reset_index(drop=True)


def mids_flujo(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None,
               exchanges=None) -> pd.DataFrame:
    """Cambios del mid de cada exchange reconstruidos desde `eventos_libro` (filtrado en DuckDB por exchange y
    ventana). Columnas: exchange, recibido_ns, exchange_ns, mid, cotizado_bps."""
    partes = []
    for ex, eventos in eventos_flujo(consultar, desde_utc, hasta_utc, exchanges):
        mids = _dentro(mids_desde_eventos(eventos, **PARAMETROS_LIBRO.get(ex, {})), desde_utc)
        partes.append(mids.assign(exchange=ex))
    if not partes:
        return pd.DataFrame(columns=["exchange", "recibido_ns", "exchange_ns", "mid", "cotizado_bps"])
    return pd.concat(partes, ignore_index=True)[["exchange", "recibido_ns", "exchange_ns", "mid", "cotizado_bps"]]


# --- Hayashi-Yoshida ------------------------------------------------------------------------------------------------

def covarianza_hy(ta, xa, tb, xb, theta: int = 0) -> float:
    """Σ_I Σ_J ΔX(I) ΔY(J) 1{I ∩ J_{−θ} ≠ ∅} para un θ (ns). Horas crecientes (ns enteros)."""
    s = np.asarray(tb, np.int64) - theta
    ta, xa, xb = np.asarray(ta, np.int64), np.asarray(xa, float), np.asarray(xb, float)
    m = len(s) - 1
    if len(ta) < 2 or m < 1:
        return 0.0
    jlo = np.maximum(np.searchsorted(s, ta[:-1], side="right"), 1)
    jhi = np.minimum(np.searchsorted(s, ta[1:], side="left"), m)
    ok = jhi >= jlo
    return float(np.sum(np.diff(xa)[ok] * (xb[jhi[ok]] - xb[jlo[ok] - 1])))


def _norma(xa, xb) -> float:
    return math.sqrt(float(np.sum(np.diff(xa) ** 2)) * float(np.sum(np.diff(xb) ** 2)))


def correlacion_hy(ta, xa, tb, xb, theta: int = 0) -> float:
    norma = _norma(xa, xb)
    return covarianza_hy(ta, xa, tb, xb, theta) / norma if norma > 0 else math.nan


def curva_hy(ta, xa, tb, xb, theta0: int, paso: int, puntos: int, limite_pares: int = LIMITE_PARES) -> np.ndarray:
    """U(θ) exacto en la rejilla θ_k = theta0 + k · paso (ns), k = 0..puntos−1.

    El par (I_i, J_j) cuenta para θ ∈ (s_{j-1} − t_i, s_j − t_{i-1}); se enumeran solo los pares que caen en la
    rejilla y su producto se suma en un array de diferencias (en bloques de `limite_pares`)."""
    ta, tb = np.asarray(ta, np.int64), np.asarray(tb, np.int64)
    dx, dy = np.diff(np.asarray(xa, float)), np.diff(np.asarray(xb, float))
    a0, a1, m = ta[:-1], ta[1:], len(tb) - 1
    diferencias = np.zeros(puntos + 1)
    if len(dx) == 0 or m < 1:
        return diferencias[:puntos]
    theta_max = theta0 + (puntos - 1) * paso
    jlo = np.maximum(np.searchsorted(tb, a0 + theta0, side="right"), 1)
    jhi = np.minimum(np.searchsorted(tb, a1 + theta_max, side="left"), m)
    cuenta = np.maximum(jhi - jlo + 1, 0)
    acumulada = np.cumsum(cuenta)
    inicio = 0
    while inicio < len(cuenta):
        base = acumulada[inicio - 1] if inicio else 0
        fin = max(int(np.searchsorted(acumulada, base + limite_pares, side="right")), inicio + 1)
        c = cuenta[inicio:fin]
        total = int(c.sum())
        if total:
            ii = np.repeat(np.arange(inicio, fin), c)
            jj = np.repeat(jlo[inicio:fin], c) + (np.arange(total) - np.repeat(np.cumsum(c) - c, c))
            izquierda, derecha = tb[jj - 1] - a1[ii], tb[jj] - a0[ii]
            k_izq = np.maximum((izquierda - theta0) // paso + 1, 0)
            k_der = np.minimum(-((theta0 - derecha) // paso) - 1, puntos - 1)
            ok = k_izq <= k_der
            peso = dx[ii[ok]] * dy[jj[ok] - 1]
            diferencias += np.bincount(k_izq[ok], peso, puntos + 1)
            diferencias -= np.bincount(k_der[ok] + 1, peso, puntos + 1)
        inicio = fin
    return np.cumsum(diferencias)[:puntos]


def rotar(t, x, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Rotación circular de una serie en la observación k: el tramo desde k pasa al principio y el anterior va
    detrás, unidos por un intervalo de 1 ns sin cambio. Conserva todos los incrementos y la hora inicial."""
    t, x = np.asarray(t, np.int64), np.asarray(x, float)
    t2, x2 = t[k:] - t[k] + t[0], x[k:] - x[k] + x[0]
    t1, x1 = t[:k + 1] - t[0] + t2[-1] + 1, x[:k + 1] - x[0] + x2[-1]
    return np.concatenate([t2, t1]), np.concatenate([x2, x1])


# --- estudio --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultadoHY:
    exchange_a: str
    exchange_b: str
    base: str
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_a: int
    n_b: int
    n_minimo_mitad: int
    rango_s: float
    paso_s: float
    theta_s: float                 # > 0: exchange_a lidera a exchange_b
    rho_max: float
    rho_0: float
    theta_descubrimiento_s: float
    rho_descubrimiento: float
    theta_confirmacion_s: float
    rho_confirmacion: float
    t_ventaja_confirmacion: float  # |ρ(θ̂ descubierto)| − |ρ(0)| en la segunda mitad, t sobre sus tramos
    ventanas_mismo_signo: int
    ventanas_total: int
    lead_lag_ratio: float
    n_sustitutos: int
    p_sustitutos: float
    p_ajustado: float
    incertidumbre_s: float
    minimo: int
    curva_theta_s: list
    curva_rho: list

    @property
    def lider(self) -> str:
        return self.exchange_a if self.theta_s > 0 else self.exchange_b

    @property
    def seguidor(self) -> str:
        return self.exchange_b if self.theta_s > 0 else self.exchange_a

    @property
    def retardo_ms(self) -> float:
        return abs(self.theta_s) * 1e3

    @property
    def estado(self) -> str:
        if self.n_minimo_mitad < self.minimo:
            return INSUFICIENTE
        if not self.p_ajustado < ALFA:
            return SIN_EVIDENCIA
        if abs(self.theta_s) < self.paso_s:
            return SIMULTANEO
        signo = np.sign(self.theta_s)
        if not (np.sign(self.theta_descubrimiento_s) == signo and np.sign(self.theta_confirmacion_s) == signo):
            return NO_CONFIRMADA
        if not self.t_ventaja_confirmacion >= T_CONFIRMACION:
            return SIMULTANEO   # el adelanto descubierto no correlaciona mejor que θ = 0 fuera de muestra
        return CONFIRMADA

    @property
    def supera_incertidumbre(self) -> bool | None:
        """¿El adelanto es mayor que el sesgo que relojes y latencias pueden meter? None si no se conoce."""
        if not math.isfinite(self.incertidumbre_s):
            return None
        return abs(self.theta_s) > self.incertidumbre_s

    def conclusion(self) -> str:
        base = "horas de recepción" if self.base == RECEPCION else "horas del exchange"
        cabecera = f"Hayashi-Yoshida {self.exchange_a}–{self.exchange_b} ({base}):"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera} datos insuficientes ({self.n_minimo_mitad} cambios de mid en la mitad más pobre; "
                    f"hacen falta {self.minimo}).")
        if self.estado == SIN_EVIDENCIA:
            return (f"{cabecera} sin evidencia: max |ρ| {abs(self.rho_max):.2f} no supera a los sustitutos "
                    f"(p {self.p_sustitutos:.3f}, ajustado {self.p_ajustado:.3f}).")
        detalle = (f"ρ máxima {self.rho_max:+.2f} frente a {self.rho_0:+.2f} en θ = 0; mitades "
                   f"{self.theta_descubrimiento_s * 1e3:+.0f} y {self.theta_confirmacion_s * 1e3:+.0f} ms "
                   f"(ventaja sobre θ = 0 fuera de muestra: t "
                   f"{self.t_ventaja_confirmacion:.1f}); {self.ventanas_mismo_signo}/{self.ventanas_total} "
                   f"tramos con el mismo signo; lead-lag ratio {self.lead_lag_ratio:.2f}; p ajustado "
                   f"{self.p_ajustado:.3f}.")
        if self.estado == SIMULTANEO:
            texto = (f"{cabecera} simultáneo (θ̂ {self.theta_s * 1e3:+.0f} ms no se distingue de 0: menos de un paso "
                     f"o sin ventaja fuera de muestra). {detalle}")
        else:
            texto = (f"{cabecera} ¿{self.lider} anticipa a {self.seguidor}? {self.estado}: θ̂ = "
                     f"{self.retardo_ms:.0f} ms. {detalle}")
        if self.supera_incertidumbre is None:
            texto += (" Sin medida de relojes para este par: no se sabe si el adelanto supera la incertidumbre de "
                      "las horas.")
        elif self.supera_incertidumbre:
            texto += f" El adelanto supera la incertidumbre de las horas ({self.incertidumbre_s * 1e3:.0f} ms)."
        elif self.estado != SIMULTANEO:
            texto += (f" Ojo: el adelanto no supera la incertidumbre de las horas "
                      f"({self.incertidumbre_s * 1e3:.0f} ms): puede ser solo reloj o latencia.")
        return texto

    def a_fila(self) -> dict:
        return {**asdict(self), "lider": self.lider, "seguidor": self.seguidor, "retardo_ms": self.retardo_ms,
                "estado": self.estado, "supera_incertidumbre": self.supera_incertidumbre,
                "conclusion": self.conclusion()}


def _serie(mids: pd.DataFrame, exchange: str, base: str) -> tuple[np.ndarray, np.ndarray]:
    """Horas (ns, crecientes, sin repetir: la última gana) y log-mid en bps de un exchange en una base."""
    g = mids[mids.exchange == exchange]
    t = g["recibido_ns" if base == RECEPCION else "exchange_ns"].to_numpy(np.int64)
    x = np.log(g["mid"].to_numpy(float)) * 1e4
    validos = t != SIN_HORA
    t, x = t[validos], x[validos]
    orden = np.argsort(t, kind="stable")
    t, x = t[orden], x[orden]
    ultimos = np.r_[t[1:] != t[:-1], True]
    return t[ultimos], x[ultimos]


def _recortar(t, x, ini, fin):
    dentro = (t >= ini) & (t <= fin)
    return t[dentro], x[dentro]


def _argmax(ta, xa, tb, xb, theta0, paso, puntos) -> tuple[float, float, np.ndarray]:
    """(θ̂ en s, ρ en θ̂, curva ρ) en una rejilla gruesa."""
    norma = _norma(xa, xb)
    if len(ta) < 3 or len(tb) < 3 or norma == 0:
        return math.nan, math.nan, np.full(puntos, math.nan)
    rho = curva_hy(ta, xa, tb, xb, theta0, paso, puntos) / norma
    k = int(np.argmax(np.abs(rho)))
    return (theta0 + k * paso) / NS, float(rho[k]), rho


def _ventaja(ta, xa, tb, xb, theta_s, ini, fin, bloques: int = BLOQUES_VENTAJA) -> float:
    """t de la media de |ρ(θ)| − |ρ(0)| en `bloques` tramos: ¿el adelanto correlaciona mejor que la simultaneidad?
    Se evalúa en la confirmación con el θ de la DESCUBRIMIENTO: fuera de muestra, sin elegir θ con estos datos.
    La curva de HY es ancha (del orden del intervalo entre observaciones) y su máximo se mueve con el ruido;
    sin esta prueba, un máximo a 10 ms de 0 por azar se leería como liderazgo."""
    if not math.isfinite(theta_s):
        return math.nan
    theta = int(round(theta_s * NS))
    diferencias = []
    for v0, v1 in itertools.pairwise(np.linspace(ini, fin, bloques + 1).astype(np.int64)):
        a, b = _recortar(ta, xa, v0, v1), _recortar(tb, xb, v0, v1)
        if len(a[0]) < 3 or len(b[0]) < 3:
            continue
        rho_theta, rho_0 = correlacion_hy(*a, *b, theta), correlacion_hy(*a, *b, 0)
        if math.isfinite(rho_theta) and math.isfinite(rho_0):
            diferencias.append(abs(rho_theta) - abs(rho_0))
    if len(diferencias) < 3:
        return math.nan
    d = np.array(diferencias)
    error = d.std(ddof=1) / math.sqrt(len(d))
    return float(d.mean() / error) if error > 0 else (0.0 if d.mean() == 0 else math.copysign(math.inf, d.mean()))


def _analizar_par(ta, xa, tb, xb, rango_s, paso_s, n_sustitutos, minimo, rng) -> dict:
    ini, fin = max(ta[0], tb[0]), min(ta[-1], tb[-1])
    ta, xa = _recortar(ta, xa, ini, fin)
    tb, xb = _recortar(tb, xb, ini, fin)
    mitad = (ini + fin) // 2
    mitades = [(_recortar(ta, xa, ini, mitad), _recortar(tb, xb, ini, mitad)),
               (_recortar(ta, xa, mitad, fin), _recortar(tb, xb, mitad, fin))]
    n_mitad = min(len(s[0]) for par in mitades for s in par) - 1
    pasos = int(round(rango_s / paso_s))
    paso, puntos = int(round(paso_s * NS)), 2 * pasos + 1
    theta0 = -pasos * paso
    rejilla = (theta0 + np.arange(puntos) * paso) / NS
    fila = dict(desde_utc=pd.Timestamp(int(ini), tz="UTC"), hasta_utc=pd.Timestamp(int(fin), tz="UTC"),
                n_a=len(ta) - 1, n_b=len(tb) - 1, n_minimo_mitad=max(n_mitad, 0), rango_s=rango_s, paso_s=paso_s,
                theta_s=math.nan, rho_max=math.nan, rho_0=math.nan, theta_descubrimiento_s=math.nan,
                rho_descubrimiento=math.nan, theta_confirmacion_s=math.nan, rho_confirmacion=math.nan,
                t_ventaja_confirmacion=math.nan, ventanas_mismo_signo=0, ventanas_total=0, lead_lag_ratio=math.nan,
                n_sustitutos=n_sustitutos,
                p_sustitutos=math.nan, minimo=minimo, curva_theta_s=rejilla.tolist(), curva_rho=[])
    if n_mitad < minimo:
        return fila
    theta, _, rho = _argmax(ta, xa, tb, xb, theta0, paso, puntos)
    norma = _norma(xa, xb)
    fino = int(round(PASO_FINO_S * NS))
    if paso > fino:   # afinar alrededor del máximo grueso
        centro = int(round(theta * NS))
        theta, rho_max, _ = _argmax(ta, xa, tb, xb, centro - paso, fino, 2 * paso // fino + 1)
    else:
        rho_max = float(rho[np.argmax(np.abs(rho))])
    (d_a, d_b), (c_a, c_b) = mitades
    theta_d, rho_d, _ = _argmax(*d_a, *d_b, theta0, paso, puntos)
    theta_c, rho_c, _ = _argmax(*c_a, *c_b, theta0, paso, puntos)
    t_ventaja = _ventaja(*c_a, *c_b, theta_d, mitad, fin)
    tramos = np.linspace(ini, fin, VENTANAS + 1).astype(np.int64)
    signos = []
    for v0, v1 in zip(tramos[:-1], tramos[1:]):
        th, _, _ = _argmax(*_recortar(ta, xa, v0, v1), *_recortar(tb, xb, v0, v1), theta0, paso, puntos)
        if math.isfinite(th):
            signos.append(np.sign(th))
    observado = float(np.max(np.abs(rho)))
    rotacion = max(MIN_ROTACION_S, 10 * rango_s) * NS
    p = math.nan
    if n_sustitutos > 0 and fin - ini > 2 * rotacion and len(tb) > 3:
        mayores = 0
        for _ in range(n_sustitutos):
            desplazamiento = int(rng.integers(int(rotacion), int(fin - ini - rotacion)))
            k = int(np.clip(np.searchsorted(tb, tb[0] + desplazamiento), 1, len(tb) - 2))
            tr, xr = rotar(tb, xb, k)
            nulo = curva_hy(ta, xa, tr, xr, theta0, paso, puntos) / norma
            mayores += float(np.max(np.abs(nulo))) >= observado
        p = (1 + mayores) / (1 + n_sustitutos)
    positivos, negativos = float(np.sum(rho[rejilla > 0] ** 2)), float(np.sum(rho[rejilla < 0] ** 2))
    fila.update(theta_s=float(theta), rho_max=float(rho_max), rho_0=covarianza_hy(ta, xa, tb, xb, 0) / norma,
                theta_descubrimiento_s=theta_d, rho_descubrimiento=rho_d, theta_confirmacion_s=theta_c,
                rho_confirmacion=rho_c, t_ventaja_confirmacion=t_ventaja,
                ventanas_mismo_signo=int(sum(s == np.sign(theta) != 0 for s in signos)),
                ventanas_total=len(signos), lead_lag_ratio=positivos / negativos if negativos > 0 else math.inf,
                p_sustitutos=p, curva_rho=rho.tolist())
    return fila


def estudiar_hayashi_yoshida(mids: pd.DataFrame, rango_s: float = RANGO_S, paso_s: float = PASO_S,
                             n_sustitutos: int = N_SUSTITUTOS, minimo: int = MIN_CAMBIOS,
                             incertidumbres: dict | None = None, bases=BASES, semilla: int = 0) -> list[ResultadoHY]:
    """Cada par de exchanges (orden alfabético) y cada base de tiempo. `mids` como `mids_flujo`.
    `incertidumbres`: {(a, b, base): segundos}, p. ej. de `incertidumbres_desde_relojes`. Benjamini-Hochberg sobre
    los p de los sustitutos de todas las pruebas con datos suficientes."""
    rng = np.random.default_rng(semilla)
    exchanges = sorted(mids["exchange"].unique()) if not mids.empty else []
    borradores = []
    for base in bases:
        series = {ex: _serie(mids, ex, base) for ex in exchanges}
        for a, b in itertools.combinations(exchanges, 2):
            (ta, xa), (tb, xb) = series[a], series[b]
            if len(ta) < 3 or len(tb) < 3 or min(ta[-1], tb[-1]) <= max(ta[0], tb[0]):
                continue
            fila = _analizar_par(ta, xa, tb, xb, rango_s, paso_s, n_sustitutos, minimo, rng)
            u = (incertidumbres or {}).get((a, b, base), math.nan)
            borradores.append(dict(exchange_a=a, exchange_b=b, base=base, incertidumbre_s=float(u), **fila))
    validos = [i for i, d in enumerate(borradores)
               if d["n_minimo_mitad"] >= minimo and not math.isnan(d["p_sustitutos"])]
    ajustados = multipletests([borradores[i]["p_sustitutos"] for i in validos], method="fdr_bh")[1] if validos else []
    p = dict(zip(validos, ajustados))
    return [ResultadoHY(**d, p_ajustado=float(p.get(i, math.nan))) for i, d in enumerate(borradores)]


def incertidumbres_desde_relojes(relojes, exchanges, bases=BASES) -> dict:
    """{(a, b, base): incertidumbre} para cada par ordenado alfabéticamente, desde `relojes.medir_relojes`."""
    return {(a, b, base): incertidumbre_lead_lag(relojes, a, b, base)
            for a, b in itertools.combinations(sorted(exchanges), 2) for base in bases}


def guardar_hayashi_yoshida(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución en `estudios_hayashi_yoshida`; `hasta_utc` dice hasta dónde llegaban los datos."""
    return almacen.guardar([{"estudio": "hayashi_yoshida", "metodo": METODO, "ejecutado_utc": ejecutado_utc,
                             "recibido_utc": ejecutado_utc, **r.a_fila()} for r in resultados], FUENTE_HY)
