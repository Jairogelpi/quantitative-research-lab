"""Presión compradora y vendedora con los trades del websocket (Fase 3): trade imbalance y CVD (S2), intensidad
(S3), VWAP frente al mid (S4) y exposición neta y bruta del flujo (S6).

Conceptos:
- Intervalo: ventanas fijas [k · Δ, (k + 1) · Δ) por hora de recepción (la nuestra), con Δ de `INTERVALOS_S`.
  Por exchange e intervalo: compras y ventas agresivas en BTC, en € y en número de trades (el lado lo da el
  exchange). Definiciones de `docs/conceptos/operaciones_ejecutadas.md`: volumen con signo = +q si compra el
  agresor, −q si vende; trade imbalance = (V_compra − V_venta) / (V_compra + V_venta), entre −1 y +1; por número,
  (n_compra − n_venta) / n; intensidad = trades / segundos de la ventana; VWAP = Σ p · q / Σ q. CVD = suma
  acumulada del volumen con signo desde el INICIO DE LA MUESTRA (`desde_utc`), no del mercado. Una ventana vacía
  tiene volumen 0, pero imbalance y VWAP indefinidos (NaN), no 0: no entra en los estudios que los usan.
- Mid exacto: el del último cambio del libro reconstruido desde `eventos_libro` (`liquidez.mids_exactos`)
  estrictamente anterior a cada extremo del intervalo. `mids_exactos` solo emite una fila cuando CAMBIA el mid,
  así que un mid quieto varios segundos es normal y sigue vigente; solo se descarta un intervalo si en él hay un
  tramo sin ningún cambio de más de `TOLERANCIA_LIBRO_S` (señal de corte de la captura, no de calma).
  ΔM = (mid al final / mid al inicio − 1) · 10.000 bps; ΔM siguiente = el del intervalo k + 1.
- S2 · Relación contemporánea: ΔM_k = a + b · imbalance_k. Es casi mecánica (los trades agresivos consumen el
  nivel y mueven el mid) y no es operable. Relación predictiva: ΔM_{k+1} = a + b · imbalance_k + c · ΔM_k: si el
  imbalance de ahora anticipa el intervalo siguiente más allá de lo que ya se movió el precio. b en bps por
  unidad de imbalance (de equilibrio, 0, a solo compras, +1). Por volumen (BTC) y por número de trades.
- S3 · Intensidad e interacción: ΔM = a + b · imbalance + c · imbalance · [intensidad alta] + d · [intensidad
  alta] (+ ΔM_k en la predictiva). "Alta" = trades por segundo por encima de la mediana de la mitad de
  descubrimiento (como `senales.interacciones`); c ≠ 0 significa que la presión pesa distinto con el mercado
  activo. Aquí el imbalance va en sus unidades (no estandarizado): ya está acotado entre −1 y +1.
- S4 · VWAP frente al mid: referencia = mid ponderado por el tiempo del intervalo (TWAP del mid exacto, la
  integral del mid escalonado entre cambios / Δ). Se elige frente al mid al final porque este ya incluye el
  impacto de los propios trades (sobrestimaría el coste de la presión) y frente al del inicio porque no depende
  de en qué momento del intervalo se concentraron los trades. Desvío = lado neto · (VWAP / TWAP − 1) · 10.000,
  con lado neto = signo del volumen con signo: positivo = el lado dominante pagó peor que el mid medio (cruza el
  spread y empuja el precio). Brecha compra-venta = (VWAP de compras − VWAP de ventas) / TWAP · 10.000 en los
  intervalos con los dos lados; con trades agresivos a bid y ask debería rondar el spread cotizado.
- S6 · Exposición neta y bruta del FLUJO de cada intervalo, con la definición de
  `docs/conceptos/order_flow_e_impacto.md` (nominal N = q · P con signo; bruta Σ |N|, neta Σ N) aplicada a los
  trades agresivos en lugar de a una cartera: bruta = € comprados + € vendidos (capital en juego), neta = |€
  comprados − € vendidos| (en valor absoluto: interesa cuánto va en una sola dirección, no hacia cuál).
  Neta / bruta = |trade imbalance en €|: 0 = flujo equilibrado, 1 = todo de un lado. Pregunta: ¿se mueve más el
  precio cuando el flujo va de un solo lado? |ΔM| = a + b · neta/bruta + c · log(bruta) + d · log(n trades). Los
  controles importan: con pocos trades el cociente tiende a 1 por construcción, y pocos trades suele ser mercado
  tranquilo (|ΔM| pequeño), lo que sesgaría b hacia abajo.
- Mismo rigor que el resto (`imbalance.py`, `senales.py`): errores Newey-West (`_retardos`), mitades de
  descubrimiento y confirmación en orden temporal, Benjamini-Hochberg dentro de cada familia de pruebas.

Estados (relación, interacción, exposición): datos insuficientes (menos de `minimo` intervalos en la mitad
menor), sin evidencia (no significativo tras Benjamini-Hochberg), no confirmada fuera de muestra, confirmada.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

from .imbalance import ALFA, T_CONFIRMACION, _p_valor, _retardos, _t
from .liquidez import _libros, mids_exactos
from .markouts import _segundos
from .senales import _ols

FUENTE_PRESION = "estudios_presion"
METODO = "presion/v1"
INTERVALOS_S = (1, 10, 60)
MIN_INTERVALOS = 100          # intervalos en la mitad menor
TOLERANCIA_LIBRO_S = 300.0    # tramo sin cambios del mid que se toma como corte de la captura
RATIO_EQUILIBRADO = 1 / 3     # neta/bruta: el lado mayor no pasa de 2/3 del flujo
RATIO_UN_LADO = 0.9
MARGEN_LIBRO_S = 60           # segundos de eventos antes de `desde_utc`, para tener el libro ya reconstruido

INSUFICIENTE, SIN_EVIDENCIA = "datos insuficientes", "sin evidencia"
NO_CONFIRMADA, CONFIRMADA = "no confirmada fuera de muestra", "confirmada"
MEDIDAS = {"volumen": "imbalance_btc", "numero": "imbalance_n"}
RELACIONES = {"contemporanea": "dmid_bps", "predictiva": "dmid_sig_bps"}

COLUMNAS = ["exchange", "intervalo_s", "inicio_s", "n_compras", "n_ventas", "n_trades", "compra_btc", "venta_btc",
            "compra_eur", "venta_eur", "firmado_btc", "firmado_eur", "imbalance_btc", "imbalance_n", "cvd_btc",
            "cvd_eur", "intensidad", "vwap", "vwap_compra", "vwap_venta", "neta_eur", "bruta_eur", "neta_bruta",
            "mid_inicio", "mid_fin", "mid_twap", "cotizado_bps", "dmid_bps", "dmid_sig_bps"]


# Agregación por intervalo.

def _division(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1.0), np.nan)


def intervalos_presion(mids: pd.DataFrame, trades: pd.DataFrame, intervalo_s: float, desde_utc=None) -> pd.DataFrame:
    """Una fila por exchange e intervalo [k · Δ, (k + 1) · Δ) entre el primer cambio del mid (o `desde_utc`) y el
    último dato (cambio del mid o trade). `mids`: exchange, recibido_ns, mid, cotizado_bps (`mids_exactos`).
    Columnas en `COLUMNAS`; las del mid son NaN si el intervalo cruza un corte de la captura (sin cambios en más
    de `TOLERANCIA_LIBRO_S`). El CVD acumula todos los intervalos, también los de mid inválido."""
    desde_s = None if desde_utc is None else pd.Timestamp(desde_utc).timestamp()
    partes = []
    for exchange, lb in _libros(mids).items():
        if len(lb.t) == 0:
            continue
        tr = trades[trades.exchange == exchange]
        t_tr = _segundos(tr["recibido_utc"]) if len(tr) else np.array([], dtype=float)
        primero = lb.t[0] if desde_s is None else max(lb.t[0], desde_s)
        ultimo = max(lb.t[-1], t_tr.max() if len(t_tr) else -math.inf)
        k = np.arange(math.ceil(primero / intervalo_s), math.floor(ultimo / intervalo_s))
        if len(k) == 0:
            continue
        inicio, fin = k * intervalo_s, (k + 1) * intervalo_s

        # Trades de cada intervalo (los de fuera del rango no cuentan).
        celda = np.floor(t_tr / intervalo_s).astype(np.int64) - int(k[0])
        dentro = (celda >= 0) & (celda < len(k))
        celda = celda[dentro]
        compra = (tr["lado_agresor"].to_numpy() == "buy")[dentro]
        q = tr["cantidad"].to_numpy(dtype=float)[dentro]
        nominal = q * tr["precio"].to_numpy(dtype=float)[dentro]

        def suma(pesos):
            return np.bincount(celda, weights=pesos, minlength=len(k)).astype(float)

        n_c, n_v = suma(compra.astype(float)), suma((~compra).astype(float))
        c_btc, v_btc = suma(q * compra), suma(q * ~compra)
        c_eur, v_eur = suma(nominal * compra), suma(nominal * ~compra)
        n = n_c + n_v

        # Mid exacto en los extremos, TWAP y cortes de la captura.
        i0 = np.searchsorted(lb.t, inicio, side="left") - 1
        i1 = np.searchsorted(lb.t, fin, side="left") - 1
        cortes = np.r_[0, np.cumsum(np.diff(lb.t) > TOLERANCIA_LIBRO_S)]
        j0, j1 = np.maximum(i0, 0), np.maximum(i1, 0)
        valido = ((i0 >= 0) & (inicio - lb.t[j0] <= TOLERANCIA_LIBRO_S) & (fin - lb.t[j1] <= TOLERANCIA_LIBRO_S)
                  & (cortes[j1] == cortes[j0]))
        integral = np.r_[0.0, np.cumsum(lb.mid[:-1] * np.diff(lb.t))]   # ∫ mid desde el primer cambio
        twap = ((integral[j1] + lb.mid[j1] * (fin - lb.t[j1])) - (integral[j0] + lb.mid[j0] * (inicio - lb.t[j0]))
                ) / intervalo_s
        m0, m1 = np.where(valido, lb.mid[j0], np.nan), np.where(valido, lb.mid[j1], np.nan)
        dmid = (m1 / m0 - 1) * 1e4

        partes.append(pd.DataFrame({
            "exchange": exchange, "intervalo_s": intervalo_s, "inicio_s": inicio.astype(float),
            "n_compras": n_c.astype(int), "n_ventas": n_v.astype(int), "n_trades": n.astype(int),
            "compra_btc": c_btc, "venta_btc": v_btc, "compra_eur": c_eur, "venta_eur": v_eur,
            "firmado_btc": c_btc - v_btc, "firmado_eur": c_eur - v_eur,
            "imbalance_btc": _division(c_btc - v_btc, c_btc + v_btc), "imbalance_n": _division(n_c - n_v, n),
            "cvd_btc": np.cumsum(c_btc - v_btc), "cvd_eur": np.cumsum(c_eur - v_eur),
            "intensidad": n / intervalo_s, "vwap": _division(c_eur + v_eur, c_btc + v_btc),
            "vwap_compra": _division(c_eur, c_btc), "vwap_venta": _division(v_eur, v_btc),
            "neta_eur": np.abs(c_eur - v_eur), "bruta_eur": c_eur + v_eur,
            "neta_bruta": _division(np.abs(c_eur - v_eur), c_eur + v_eur),
            "mid_inicio": m0, "mid_fin": m1, "mid_twap": np.where(valido, twap, np.nan),
            "cotizado_bps": np.where(valido, lb.cotizado[j0], np.nan), "dmid_bps": dmid,
            "dmid_sig_bps": np.r_[dmid[1:], np.nan]}))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUMNAS)


# Utilidades de las regresiones.

def _hasta(g: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(float(g["inicio_s"].max() + g["intervalo_s"].iloc[0]), unit="s", tz="UTC")


def _mitades(g: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = g.sort_values("inicio_s").reset_index(drop=True)
    mitad = len(g) // 2
    return g.iloc[:mitad], g.iloc[mitad:]


def _con_variacion(parte: pd.DataFrame, controles) -> list:
    """Los controles que varían en esta parte (uno constante sería colineal con la constante)."""
    return [c for c in controles if parte[c].std() > 0]


def _estado(n: int, minimo: int, p_ajustado: float, t: float, t_conf: float) -> str:
    if n < minimo:
        return INSUFICIENTE
    if not p_ajustado < ALFA:
        return SIN_EVIDENCIA
    return CONFIRMADA if np.sign(t_conf) == np.sign(t) and abs(t_conf) >= T_CONFIRMACION else NO_CONFIRMADA


def _bh(borradores: list, minimo: int) -> dict:
    validos = [i for i, b in enumerate(borradores) if b["n"] >= minimo and not math.isnan(b["p_descubrimiento"])]
    ajustados = multipletests([borradores[i]["p_descubrimiento"] for i in validos], method="fdr_bh")[1] if validos else []
    return dict(zip(validos, ajustados))


# S2 · Trade imbalance frente al cambio del mid.

@dataclass(frozen=True)
class RelacionPresion:
    exchange: str
    intervalo_s: float
    medida: str               # volumen (BTC) o numero (de trades)
    relacion: str             # contemporanea o predictiva
    n: int                    # intervalos en la mitad menor
    coef: float               # bps por unidad de imbalance (descubrimiento)
    t: float
    p_descubrimiento: float
    p_ajustado: float
    coef_conf: float
    t_conf: float
    r2: float
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def estado(self) -> str:
        return _estado(self.n, self.minimo, self.p_ajustado, self.t, self.t_conf)

    def conclusion(self) -> str:
        medida = "por volumen" if self.medida == "volumen" else "por número de trades"
        cuando = ("en el mismo intervalo" if self.relacion == "contemporanea"
                  else "en el intervalo siguiente (con el cambio del propio intervalo como control)")
        cabecera = f"{self.exchange}, trade imbalance {medida}, intervalos de {self.intervalo_s:g} s, {self.relacion}"
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n} intervalos con trades; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. Pasar de un flujo equilibrado a solo compras (imbalance +1) va con "
                f"{self.coef:+.3f} bps de mid {cuando} (t HAC {self.t:.2f}, p ajustado {self.p_ajustado:.3f}, R² "
                f"{self.r2:.3f}); confirmación {self.coef_conf:+.3f} bps (t {self.t_conf:.2f}); {self.n} intervalos "
                f"por mitad.")

    def a_fila(self) -> dict:
        return {"estudio": "presion_relacion", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def relaciones_presion(tabla: pd.DataFrame, minimo: int = MIN_INTERVALOS) -> list[RelacionPresion]:
    borradores = []
    for (exchange, delta), g in tabla.groupby(["exchange", "intervalo_s"], sort=True):
        for medida, x_col in MEDIDAS.items():
            for relacion, y_col in RELACIONES.items():
                controles = ["dmid_bps"] if relacion == "predictiva" else []
                d, c = _mitades(g.dropna(subset=[x_col, y_col, *controles]))
                fila = dict(exchange=exchange, intervalo_s=delta, medida=medida, relacion=relacion,
                            n=min(len(d), len(c)), hasta_utc=_hasta(g), minimo=minimo)
                if fila["n"] < minimo or d[x_col].std() == 0 or c[x_col].std() == 0:
                    borradores.append({**fila, "coef": math.nan, "t": math.nan, "p_descubrimiento": math.nan,
                                       "coef_conf": math.nan, "t_conf": math.nan, "r2": math.nan})
                    continue
                m1 = _ols(d[y_col], d[[x_col, *_con_variacion(d, controles)]], 1)
                m2 = _ols(c[y_col], c[[x_col, *_con_variacion(c, controles)]], 1)
                t1 = _t(float(m1.params[x_col]), float(m1.bse[x_col]))
                borradores.append({**fila, "coef": float(m1.params[x_col]), "t": t1, "p_descubrimiento": _p_valor(t1),
                                   "coef_conf": float(m2.params[x_col]),
                                   "t_conf": _t(float(m2.params[x_col]), float(m2.bse[x_col])),
                                   "r2": float(m1.rsquared)})
    p = _bh(borradores, minimo)
    return [RelacionPresion(**b, p_ajustado=float(p.get(i, math.nan))) for i, b in enumerate(borradores)]


# S3 · Intensidad: ¿pesa más la presión con el mercado activo?

@dataclass(frozen=True)
class InteraccionIntensidad:
    exchange: str
    intervalo_s: float
    relacion: str
    n: int
    umbral: float             # trades por segundo: mediana de la mitad de descubrimiento
    intensidad_media: float
    coef_bajo: float          # bps por unidad de imbalance con intensidad baja (descubrimiento)
    coef_interaccion: float   # cuánto cambia con intensidad alta (descubrimiento)
    t_interaccion: float
    p_descubrimiento: float
    p_ajustado: float
    coef_interaccion_conf: float
    t_interaccion_conf: float
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def estado(self) -> str:
        return _estado(self.n, self.minimo, self.p_ajustado, self.t_interaccion, self.t_interaccion_conf)

    def conclusion(self) -> str:
        cabecera = (f"{self.exchange}, trade imbalance × intensidad alta (> {self.umbral:.3f} trades/s), intervalos de "
                    f"{self.intervalo_s:g} s, {self.relacion}")
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n} intervalos con trades; hacen falta {self.minimo})."
        if math.isnan(self.coef_interaccion):
            return (f"{cabecera}: sin evidencia (la intensidad no varía lo suficiente para separar mercado activo y "
                    f"tranquilo; media {self.intensidad_media:.3f} trades/s).")
        alto = self.coef_bajo + self.coef_interaccion
        if np.sign(alto) != np.sign(self.coef_bajo) and not abs(self.coef_bajo) < 0.2 * abs(alto):
            sentido = "de signo contrario"
        else:
            sentido = "más fuerte" if abs(alto) > abs(self.coef_bajo) else "más débil"
        texto = (f"{cabecera}: {self.estado}. Con intensidad baja, {self.coef_bajo:+.3f} bps por unidad de imbalance; "
                 f"con intensidad alta cambia {self.coef_interaccion:+.3f} (t HAC {self.t_interaccion:.2f}, p ajustado "
                 f"{self.p_ajustado:.3f}); confirmación {self.coef_interaccion_conf:+.3f} (t {self.t_interaccion_conf:.2f}).")
        return texto + (f" La presión es {sentido} cuando el mercado está activo." if self.estado == CONFIRMADA else "")

    def a_fila(self) -> dict:
        return {"estudio": "presion_intensidad", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def interacciones_intensidad(tabla: pd.DataFrame, minimo: int = MIN_INTERVALOS) -> list[InteraccionIntensidad]:
    borradores, x_col = [], "imbalance_btc"
    for (exchange, delta), g in tabla.groupby(["exchange", "intervalo_s"], sort=True):
        for relacion, y_col in RELACIONES.items():
            controles = ["dmid_bps"] if relacion == "predictiva" else []
            d, c = _mitades(g.dropna(subset=[x_col, y_col, "intensidad", *controles]))
            fila = dict(exchange=exchange, intervalo_s=delta, relacion=relacion, n=min(len(d), len(c)),
                        intensidad_media=float(g["intensidad"].mean()), hasta_utc=_hasta(g), minimo=minimo)
            vacio = {"umbral": math.nan, "coef_bajo": math.nan, "coef_interaccion": math.nan,
                     "t_interaccion": math.nan, "p_descubrimiento": math.nan, "coef_interaccion_conf": math.nan,
                     "t_interaccion_conf": math.nan}
            if fila["n"] < minimo:
                borradores.append({**fila, **vacio})
                continue
            umbral = float(d["intensidad"].median())
            estimados = []
            for parte in (d, c):
                alto = (parte["intensidad"] > umbral).astype(float)
                if alto.std() == 0 or parte[x_col].std() == 0:
                    break
                x = pd.DataFrame({"s": parte[x_col], "s_alto": parte[x_col] * alto, "alto": alto})
                for control in _con_variacion(parte, controles):
                    x[control] = parte[control]
                m = _ols(parte[y_col], x, 1)
                estimados.append((float(m.params["s"]), float(m.params["s_alto"]),
                                  _t(float(m.params["s_alto"]), float(m.bse["s_alto"]))))
            if len(estimados) < 2:
                borradores.append({**fila, **vacio, "umbral": umbral})
                continue
            (bajo, inter, t1), (_, inter2, t2) = estimados
            borradores.append({**fila, "umbral": umbral, "coef_bajo": bajo, "coef_interaccion": inter,
                               "t_interaccion": t1, "p_descubrimiento": _p_valor(t1), "coef_interaccion_conf": inter2,
                               "t_interaccion_conf": t2})
    p = _bh(borradores, minimo)
    return [InteraccionIntensidad(**b, p_ajustado=float(p.get(i, math.nan))) for i, b in enumerate(borradores)]


# S4 · VWAP frente al mid.

def _media_hac(x: np.ndarray) -> tuple[float, float]:
    """(media, error Newey-West de la media)."""
    if len(x) < 3:
        return (float(np.mean(x)) if len(x) else math.nan), math.nan
    m = sm.OLS(x, np.ones(len(x))).fit(cov_type="HAC", cov_kwds={"maxlags": _retardos(len(x), 1)})
    return float(m.params[0]), float(m.bse[0])


@dataclass(frozen=True)
class VwapMid:
    exchange: str
    intervalo_s: float
    n: int                        # intervalos con trades y lado neto
    desvio_neto_bps: float        # lado neto · (VWAP / TWAP del mid − 1)
    error_desvio_bps: float
    n_ambos: int                  # intervalos con compras y ventas
    brecha_compra_venta_bps: float
    error_brecha_bps: float
    compra_sobre_mid_bps: float   # (VWAP compras / TWAP − 1)
    venta_bajo_mid_bps: float     # (1 − VWAP ventas / TWAP)
    cotizado_bps: float           # spread cotizado medio al inicio de los intervalos
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def t(self) -> float:
        return _t(self.desvio_neto_bps, self.error_desvio_bps)

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return INSUFICIENTE
        if not abs(self.t) >= T_CONFIRMACION:
            return SIN_EVIDENCIA
        return "el lado neto paga sobre el mid" if self.desvio_neto_bps > 0 else "el lado neto mejora el mid"

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, VWAP frente al mid medio del intervalo, intervalos de {self.intervalo_s:g} s"
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n} intervalos con trades; hacen falta {self.minimo})."
        return (f"{cabecera}: {self.estado}. El lado dominante operó a {self.desvio_neto_bps:+.3f} bps del mid "
                f"ponderado por el tiempo (error HAC {self.error_desvio_bps:.3f}, t {self.t:.2f}) en {self.n} intervalos. "
                f"Las compras, a {self.compra_sobre_mid_bps:+.3f} bps por encima; las ventas, a "
                f"{self.venta_bajo_mid_bps:+.3f} bps por debajo; brecha compra-venta {self.brecha_compra_venta_bps:+.3f} "
                f"bps (error {self.error_brecha_bps:.3f}, {self.n_ambos} intervalos con los dos lados) frente a un "
                f"spread cotizado medio de {self.cotizado_bps:.3f} bps.")

    def a_fila(self) -> dict:
        return {"estudio": "presion_vwap", **asdict(self), "t": self.t, "estado": self.estado,
                "conclusion": self.conclusion()}


def vwap_mid(tabla: pd.DataFrame, minimo: int = MIN_INTERVALOS) -> list[VwapMid]:
    resultados = []
    for (exchange, delta), g in tabla.groupby(["exchange", "intervalo_s"], sort=True):
        g = g.sort_values("inicio_s")
        s = g[(g["n_trades"] > 0) & g["mid_twap"].notna() & g["vwap"].notna() & (g["firmado_btc"] != 0)]
        desvio = np.sign(s["firmado_btc"].to_numpy()) * (s["vwap"] / s["mid_twap"] - 1).to_numpy() * 1e4
        ambos = g[g["vwap_compra"].notna() & g["vwap_venta"].notna() & g["mid_twap"].notna()]
        brecha = ((ambos["vwap_compra"] - ambos["vwap_venta"]) / ambos["mid_twap"]).to_numpy() * 1e4
        media, error = _media_hac(desvio)
        media_b, error_b = _media_hac(brecha)
        compras = g[g["vwap_compra"].notna() & g["mid_twap"].notna()]
        ventas = g[g["vwap_venta"].notna() & g["mid_twap"].notna()]
        resultados.append(VwapMid(
            exchange, delta, len(s), media, error, len(ambos), media_b, error_b,
            float(((compras["vwap_compra"] / compras["mid_twap"] - 1) * 1e4).mean()) if len(compras) else math.nan,
            float(((1 - ventas["vwap_venta"] / ventas["mid_twap"]) * 1e4).mean()) if len(ventas) else math.nan,
            float(s["cotizado_bps"].mean()) if len(s) else math.nan, _hasta(g), minimo))
    return resultados


# S6 · Exposición neta y bruta del flujo.

@dataclass(frozen=True)
class ExposicionFlujo:
    exchange: str
    intervalo_s: float
    n: int                    # intervalos en la mitad menor
    neta_media_eur: float
    bruta_media_eur: float
    ratio_p10: float          # distribución de neta / bruta
    ratio_p50: float
    ratio_p90: float
    solo_un_lado: float       # fracción de intervalos con trades de un solo lado (neta/bruta = 1)
    dmid_abs_equilibrado_bps: float   # |ΔM| medio con neta/bruta ≤ `RATIO_EQUILIBRADO`
    dmid_abs_un_lado_bps: float       # y con neta/bruta ≥ `RATIO_UN_LADO`
    coef: float               # bps de |ΔM| por unidad de neta/bruta, con log(bruta) y log(n) (descubrimiento)
    t: float
    p_descubrimiento: float
    p_ajustado: float
    coef_conf: float
    t_conf: float
    hasta_utc: pd.Timestamp
    minimo: int

    @property
    def estado(self) -> str:
        return _estado(self.n, self.minimo, self.p_ajustado, self.t, self.t_conf)

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, exposición neta y bruta del flujo, intervalos de {self.intervalo_s:g} s"
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n} intervalos con trades; hacen falta {self.minimo})."
        texto = (f"{cabecera}: neta media {self.neta_media_eur:,.0f} € de una bruta media de {self.bruta_media_eur:,.0f} €; "
                 f"neta/bruta p10 {self.ratio_p10:.2f}, mediana {self.ratio_p50:.2f}, p90 {self.ratio_p90:.2f}. "
                 f"El {self.solo_un_lado:.0%} de los intervalos tiene trades de un solo lado (con pocos trades por "
                 f"intervalo el cociente tiende a 1 por construcción). |ΔM| medio {self.dmid_abs_equilibrado_bps:.3f} bps "
                 f"con flujo equilibrado (neta/bruta ≤ {RATIO_EQUILIBRADO:.2f}) y {self.dmid_abs_un_lado_bps:.3f} con "
                 f"flujo casi de un solo lado (≥ {RATIO_UN_LADO:.2f}), sin controles. {self.estado.capitalize()}: con el "
                 f"tamaño (log de la bruta y del número de trades) como control, pasar de flujo equilibrado a uno de un "
                 f"solo lado cambia |ΔM| en {self.coef:+.3f} bps (t HAC {self.t:.2f}, p ajustado {self.p_ajustado:.3f}); "
                 f"confirmación {self.coef_conf:+.3f} (t {self.t_conf:.2f}).")
        if self.estado == CONFIRMADA:
            texto += (" El precio se mueve más cuando el flujo va de un solo lado." if self.coef > 0 else
                      " El precio se mueve menos cuando el flujo va de un solo lado.")
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "presion_exposicion", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def _extremos(ratio: pd.Series, y: pd.Series) -> tuple[float, float]:
    """|ΔM| medio con flujo equilibrado y con flujo casi de un lado. Umbrales fijos y no cuartiles: en intervalos
    cortos la mayoría tiene un solo lado (cociente 1) y los cuartiles no se pueden separar."""
    bajo, alto = y[ratio <= RATIO_EQUILIBRADO], y[ratio >= RATIO_UN_LADO]
    return (float(bajo.mean()) if len(bajo) else math.nan), (float(alto.mean()) if len(alto) else math.nan)


def exposicion_flujo(tabla: pd.DataFrame, minimo: int = MIN_INTERVALOS) -> list[ExposicionFlujo]:
    borradores = []
    for (exchange, delta), g in tabla.groupby(["exchange", "intervalo_s"], sort=True):
        s = g[(g["n_trades"] > 0) & (g["bruta_eur"] > 0)].dropna(subset=["neta_bruta", "dmid_bps"]).copy()
        s["dmid_abs"] = s["dmid_bps"].abs()
        s["log_bruta"], s["log_n"] = np.log(s["bruta_eur"]), np.log(s["n_trades"].astype(float))
        d, c = _mitades(s)
        equilibrado, un_lado = _extremos(s["neta_bruta"], s["dmid_abs"])
        cuantiles = s["neta_bruta"].quantile([0.1, 0.5, 0.9]).tolist() if len(s) else [math.nan] * 3
        fila = dict(exchange=exchange, intervalo_s=delta, n=min(len(d), len(c)),
                    neta_media_eur=float(s["neta_eur"].mean()) if len(s) else math.nan,
                    bruta_media_eur=float(s["bruta_eur"].mean()) if len(s) else math.nan,
                    ratio_p10=cuantiles[0], ratio_p50=cuantiles[1], ratio_p90=cuantiles[2],
                    solo_un_lado=float((s["neta_bruta"] >= 1 - 1e-12).mean()) if len(s) else math.nan,
                    dmid_abs_equilibrado_bps=equilibrado, dmid_abs_un_lado_bps=un_lado, hasta_utc=_hasta(g), minimo=minimo)
        if fila["n"] < minimo or d["neta_bruta"].std() == 0 or c["neta_bruta"].std() == 0:
            borradores.append({**fila, "coef": math.nan, "t": math.nan, "p_descubrimiento": math.nan,
                               "coef_conf": math.nan, "t_conf": math.nan})
            continue
        estimados = []
        for parte in (d, c):
            m = _ols(parte["dmid_abs"], parte[["neta_bruta", *_con_variacion(parte, ["log_bruta", "log_n"])]], 1)
            estimados.append((float(m.params["neta_bruta"]), _t(float(m.params["neta_bruta"]),
                                                                 float(m.bse["neta_bruta"]))))
        (b1, t1), (b2, t2) = estimados
        borradores.append({**fila, "coef": b1, "t": t1, "p_descubrimiento": _p_valor(t1), "coef_conf": b2, "t_conf": t2})
    p = _bh(borradores, minimo)
    return [ExposicionFlujo(**b, p_ajustado=float(p.get(i, math.nan))) for i, b in enumerate(borradores)]


# Estudio completo y guardado.

def tabla_presion(consultar: Callable[[str], pd.DataFrame], desde_utc=None, intervalos_s=INTERVALOS_S) -> pd.DataFrame:
    """Intervalos de todos los Δ con los trades y el mid exacto (`eventos_libro`) desde `desde_utc`."""
    filtro = "" if desde_utc is None else f" WHERE recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}'"
    trades = consultar("SELECT exchange, recibido_utc, precio, cantidad, lado_agresor FROM trades"
                       f"{filtro} ORDER BY exchange, recibido_utc")
    inicio = None if desde_utc is None else pd.Timestamp(desde_utc) - pd.Timedelta(seconds=MARGEN_LIBRO_S)
    mids = mids_exactos(consultar, inicio)
    partes = [intervalos_presion(mids, trades, delta, desde_utc) for delta in intervalos_s]
    partes = [p for p in partes if len(p)]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUMNAS)


def estudiar_presion(consultar: Callable[[str], pd.DataFrame], desde_utc=None, intervalos_s=INTERVALOS_S,
                     minimo: int = MIN_INTERVALOS) -> list:
    """Relaciones del trade imbalance (S2), interacción con la intensidad (S3), VWAP frente al mid (S4) y exposición
    neta y bruta (S6). Necesita `trades` y `eventos_libro`; reconstruir el libro es lento: usar `desde_utc`."""
    tabla = tabla_presion(consultar, desde_utc, intervalos_s)
    if tabla.empty:
        return []
    return (relaciones_presion(tabla, minimo) + interacciones_intensidad(tabla, minimo) + vwap_mid(tabla, minimo)
            + exposicion_flujo(tabla, minimo))


def guardar_estudio_presion(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_PRESION)
