"""Valoración de opciones sobre la cadena BTC de Deribit: payoffs, Black-76, griegas, volatilidad implícita,
paridad put-call, sonrisa, estructura temporal y volatilidad realizada (Fase 7, S2). Estudio descriptivo.

Conceptos:
- Payoff al vencimiento (en USD por 1 BTC): futuro comprado S − K; call max(S − K, 0); put max(K − S, 0);
  straddle = call + put (gana con movimientos grandes en cualquier sentido); put protectora = spot + put
  (= max(S, K): el put fija un suelo). Beneficio = payoff − prima pagada. Opción inversa (Deribit): el mismo
  payoff se paga en BTC al precio de liquidación, payoff_usd / S.
- Black-76 sobre el forward: c = e^{−rT} [F N(d1) − K N(d2)], p = e^{−rT} [K N(−d2) − F N(−d1)], con
  d1 = [ln(F/K) + σ²T/2] / (σ√T), d2 = d1 − σ√T. Por qué Black-76 y no Black-Scholes sobre el spot: Deribit
  calcula la IV de cada vencimiento contra su propio subyacente (`underlying_price`: el futuro de ese vencimiento
  o un forward sintético), no contra el índice spot. Con el forward no hace falta conocer el "dividendo" de BTC
  (tipo de interés en BTC, funding): ya está dentro de F. Con S·e^{rT} = F, Black-76 y Black-Scholes coinciden.
  https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency
- Convención BTC/USD de Deribit (comprobada con datos reales, 22-11-2026): mark en BTC = Black-76 en USD con
  F = `underlying_price`, r = `interest_rate` = 0 y T en años de 365 días hasta las 08:00 UTC del vencimiento,
  dividido por F. P. ej. BTC-26MAR27-40000-C: F 61 591,56, IV 64 % → 0,368657 BTC frente a un mark de
  0,36862541. Valor en USD = precio en BTC × F (no × índice spot: con un basis del 1,6 % la diferencia es real).
- Griegas: Black-76 por unidad (delta ∂V/∂F, gamma ∂²V/∂F², vega ∂V/∂σ, theta ∂V/∂t por año, rho ∂V/∂r =
  −T·V). Las que publica Deribit en `public/ticker` (https://docs.deribit.com/api-reference/market-data/public-ticker)
  siguen otra convención, reproducida aquí y comprobada con cuatro tickers reales (calls y puts, a 0,5 y 124
  días): delta N(d1) (put N(d1) − 1), sin ajuste por prima; vega en USD por punto de volatilidad (/100); theta en
  USD por día de 365, salvo a menos de un día del vencimiento, donde es la de la vida restante (theta anual × T);
  rho la de Black-Scholes sobre el spot, en USD por punto: K·T·N(d2)/100 (put −K·T·N(−d2)/100).
- Volatilidad implícita: el σ que iguala el precio del modelo al de mercado. Solo existe dentro de las cotas de
  no arbitraje: call en (e^{−rT}·max(F − K, 0), e^{−rT}·F), put en (e^{−rT}·max(K − F, 0), e^{−rT}·K). Fuera de ellas
  (o con T ≤ 0) se devuelve NaN. Resolución robusta: horquilla [σ_min, σ_max] (el precio crece con σ) y Newton
  dentro de ella; si un paso de Newton sale de la horquilla, se bisecciona.
- Paridad put-call con el forward: c − p = e^{−rT}(F − K). En BTC con la convención de Deribit, c − p = 1 − K/F.
  Para opciones inversas es además una identidad sin modelo con el precio del futuro inverso: un futuro inverso
  paga 1/F₀ − 1/S_T BTC por USD de nocional y cuesta 0, así que E^{BTC}[1/S_T] = 1/F₀ y la cartera call − put paga
  1 − K/S_T. Desviación = (c_mid − p_mid) − (1 − K/F), en bps del forward (precio en BTC por 1 BTC de nocional
  × 10⁴). Violación más allá del spread: la parte teórica cae fuera de [c_bid − p_ask, c_ask − p_bid]; con dos
  comisiones taker (0,0003 BTC = 3 bps por pierna, sin el tope por precio de la opción) es una cota prudente.
  Ojo: si el vencimiento no tiene futuro listado, F es un forward sintético que Deribit deduce de las propias
  opciones; la paridad entonces es casi circular, y no hay futuro con el que cubrir la tercera pierna.
- Validación frente a Deribit: la IV se recalcula desde el mark (resumen, sin redondear al tick) solo en opciones
  fuera del dinero. Dentro del dinero el precio es casi todo valor intrínseco y la vega es diminuta: un error
  de 1e-8 BTC en el mark mueve la IV decenas de puntos (en la foto real, hasta 44 puntos en puts muy dentro del
  dinero), así que esa diferencia no dice nada del modelo. Las griegas se comparan todas, con F, IV y hora del
  propio ticker.
- Forward implícito: F = K / (1 − (c_mid − p_mid)), mediana de los strikes más cercanos al dinero.
- Sonrisa y skew: IV frente a la moneyness logarítmica k = ln(K/F), con opciones fuera del dinero (puts con K < F,
  calls con K ≥ F). IV ATM: interpolada en k = 0. Risk reversal 25Δ (convención de mercado) = σ(call 25Δ) −
  σ(put −25Δ): negativo si las puts son más caras (protección contra caídas); mariposa 25Δ = media de ambas − ATM
  (curvatura de la sonrisa). Deltas de Black-76 al mark IV.
- Estructura temporal: IV ATM frente al plazo. Interpolación en varianza total w = σ²T, lineal en T (la varianza
  total no puede bajar con el plazo sin arbitraje de calendario); sin extrapolar.
- Volatilidad realizada: desviación típica de los retornos log horarios de las velas `kraken_historico` BTC/EUR
  (`retornos.py`), anualizada con √(365 · 24). Comparación con la IV ATM al mismo plazo: la realizada mira atrás
  y la implícita adelante (su diferencia es la prima de varianza más el cambio de régimen). EUR frente a USD:
  σ²(BTC/EUR) = σ²(BTC/USD) + σ²(EUR/USD) − 2ρσσ; con EUR/USD en torno al 7-8 % anual frente al ~50 % de BTC,
  la diferencia es de un punto o dos, pequeña frente a las que aquí se comparan, pero no nula.

Estados:
- paridad: datos insuficientes (< `MIN_PARES` pares con las cuatro cotizaciones) / paridad dentro del spread /
  violaciones aisladas (≤ `FRACCION_AISLADAS` de los pares) / violaciones frecuentes.
- validación: datos insuficientes / coincide con Deribit / discrepa de Deribit (umbrales `TOL_*`).
- sonrisa: datos insuficientes / skew de puts (RR25 < −`UMBRAL_RR`) / skew de calls / sonrisa simétrica.
- estructura: datos insuficientes / creciente / invertida / plana (diferencia largo − corto frente a `UMBRAL_RR`).
- realizada: datos insuficientes / implícita por encima de la realizada / implícita por debajo de la realizada.
Sin p-valores ni t: no se contrasta ninguna hipótesis y el registro de pruebas no cuenta estas filas.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.special import ndtr

from radar.analisis.retornos import factor_anual, preparar_retornos

FUENTE_OPCIONES = "estudios_opciones"
FUENTE_CADENA = "opciones_cadena"   # la escribe `radar.captura.opciones`
METODO = "opciones/v1"
SEGUNDOS_ANO = 365 * 86400
SIGMA_MIN, SIGMA_MAX = 1e-4, 10.0
MIN_PARES = 5
FRACCION_AISLADAS = 0.05
N_ATM_FORWARD = 6
MIN_POR_LADO = 3
UMBRAL_RR = 0.01           # 1 punto de volatilidad
MIN_DIAS_ESTRUCTURA = 2.0
DIAS_ESTRUCTURA = (7, 30, 90)
VENTANAS_REALIZADA = (7, 30, 90)
COBERTURA_MINIMA = 0.8     # fracción de retornos horarios esperados
MIN_OPCIONES_VALIDACION = 10
TOL_IV_PUNTOS, TOL_DELTA, TOL_RELATIVA = 0.05, 1e-3, 0.01
PISO_GRIEGA = 0.01

INSUFICIENTE = "datos insuficientes"
DENTRO, AISLADAS, FRECUENTES = "paridad dentro del spread", "violaciones aisladas", "violaciones frecuentes"
COINCIDE, DISCREPA = "coincide con Deribit", "discrepa de Deribit"
SKEW_PUTS, SKEW_CALLS, SIMETRICA = "skew de puts", "skew de calls", "sonrisa simétrica"
CRECIENTE, INVERTIDA, PLANA = "creciente", "invertida", "plana"
IMPLICITA_MAYOR, IMPLICITA_MENOR = "implícita por encima de la realizada", "implícita por debajo de la realizada"

# --- payoffs ----------------------------------------------------------------------------------------------------


def payoff_futuro(s, k, posicion: int = 1):
    """Futuro al vencimiento: posicion · (S − K); posicion = −1 es el vendido."""
    return posicion * (np.asarray(s, dtype=float) - k)


def payoff_call(s, k):
    return np.maximum(np.asarray(s, dtype=float) - k, 0.0)


def payoff_put(s, k):
    return np.maximum(k - np.asarray(s, dtype=float), 0.0)


def payoff_straddle(s, k):
    return payoff_call(s, k) + payoff_put(s, k)


def payoff_put_protectora(s, k):
    """1 BTC de spot más un put de strike K."""
    return np.asarray(s, dtype=float) + payoff_put(s, k)


def payoff_inverso_btc(payoff_usd, s):
    """Payoff de una opción inversa: el importe en USD pagado en BTC al precio de liquidación S."""
    return np.asarray(payoff_usd, dtype=float) / np.asarray(s, dtype=float)


def beneficio(payoff, prima: float):
    return np.asarray(payoff, dtype=float) - prima


# --- Black-76 ---------------------------------------------------------------------------------------------------


def anos_hasta(vencimiento, ahora) -> float:
    """Años de 365 días (con segundos) hasta el vencimiento, la convención de Deribit."""
    return (pd.Timestamp(vencimiento) - pd.Timestamp(ahora)).total_seconds() / SEGUNDOS_ANO


def _phi(x):
    return np.exp(-0.5 * np.square(x)) / math.sqrt(2 * math.pi)


def _d1_d2(f, k, t, sigma):
    raiz = sigma * np.sqrt(t)
    d1 = (np.log(f / k) + 0.5 * sigma * sigma * t) / raiz
    return d1, d1 - raiz


def _es_call(tipo: str) -> bool:
    if tipo not in ("call", "put"):
        raise ValueError(f"tipo de opción desconocido: {tipo}")
    return tipo == "call"


def black76(f, k, t, sigma, tipo: str, r: float = 0.0):
    """Precio de Black-76 (en la moneda de F y K) de una call o put europea sobre el forward F."""
    d1, d2 = _d1_d2(f, k, t, sigma)
    df = np.exp(-r * t)
    if _es_call(tipo):
        return df * (f * ndtr(d1) - k * ndtr(d2))
    return df * (k * ndtr(-d2) - f * ndtr(-d1))


def precio_btc(f, k, t, sigma, tipo: str):
    """Precio en BTC con la convención de Deribit: Black-76 en USD (r = 0) dividido por el forward."""
    return black76(f, k, t, sigma, tipo) / f


def griegas(f, k, t, sigma, tipo: str, r: float = 0.0) -> dict:
    """Griegas de Black-76 por unidad: delta y gamma respecto a F, vega por unidad de σ, theta ∂V/∂t por año,
    rho ∂V/∂r con F fijo (= −T·V)."""
    d1, _ = _d1_d2(f, k, t, sigma)
    df = math.exp(-r * t)
    v = black76(f, k, t, sigma, tipo, r)
    delta = df * (ndtr(d1) if _es_call(tipo) else ndtr(d1) - 1)
    gamma = df * _phi(d1) / (f * sigma * math.sqrt(t))
    vega = df * f * _phi(d1) * math.sqrt(t)
    theta = r * v - df * f * _phi(d1) * sigma / (2 * math.sqrt(t))
    return {"delta": float(delta), "gamma": float(gamma), "vega": float(vega), "theta": float(theta),
            "rho": float(-t * v)}


def griegas_deribit(f, k, t, sigma, tipo: str) -> dict:
    """Griegas en la convención de `public/ticker` (USD; vega y rho por punto, theta por día; r = 0)."""
    g = griegas(f, k, t, sigma, tipo)
    _, d2 = _d1_d2(f, k, t, sigma)
    rho = k * t * (ndtr(d2) if _es_call(tipo) else -ndtr(-d2)) / 100
    return {"delta": g["delta"], "gamma": g["gamma"], "vega": g["vega"] / 100,
            "theta": g["theta"] * min(1 / 365, t), "rho": float(rho)}


# --- volatilidad implícita --------------------------------------------------------------------------------------


def cotas_sin_arbitraje(f, k, t, tipo: str, r: float = 0.0) -> tuple[float, float]:
    """(valor intrínseco descontado, máximo): el precio de mercado debe quedar estrictamente dentro."""
    df = math.exp(-r * t)
    if _es_call(tipo):
        return df * max(f - k, 0.0), df * f
    return df * max(k - f, 0.0), df * k


def volatilidad_implicita(precio, f, k, t, tipo: str, r: float = 0.0, sigma_min: float = SIGMA_MIN,
                          sigma_max: float = SIGMA_MAX, max_iter: int = 200) -> float:
    """σ de Black-76 que reproduce `precio`; NaN si no existe (fuera de cotas, T ≤ 0, fuera de [σ_min, σ_max])."""
    valores = (precio, f, k, t)
    if not all(isinstance(x, (int, float, np.floating)) and math.isfinite(x) for x in valores):
        return math.nan
    if t <= 0 or f <= 0 or k <= 0:
        return math.nan
    inferior, superior = cotas_sin_arbitraje(f, k, t, tipo, r)
    if not inferior < precio < superior:
        return math.nan
    error = lambda s: float(black76(f, k, t, s, tipo, r)) - precio
    a, b = sigma_min, sigma_max
    if error(a) > 0 or error(b) < 0:
        return math.nan
    sigma = min(max(math.sqrt(2 * math.pi / t) * precio / (math.exp(-r * t) * f), a), b)  # Brenner-Subrahmanyam
    for _ in range(max_iter):
        e = error(sigma)
        if e == 0:
            return sigma
        if e > 0:
            b = sigma
        else:
            a = sigma
        vega = griegas(f, k, t, sigma, tipo, r)["vega"]
        nuevo = sigma - e / vega if vega > 0 else math.nan
        if not (a < nuevo < b):
            nuevo = 0.5 * (a + b)
        if abs(nuevo - sigma) < 1e-14 * max(1.0, sigma) or b - a < 1e-15:
            return nuevo
        sigma = nuevo
    return sigma


# --- tablas sobre la cadena -------------------------------------------------------------------------------------


def _con_plazo(cadena: pd.DataFrame) -> pd.DataFrame:
    c = cadena.copy()
    c["forward"] = c.groupby("vencimiento_utc").subyacente_usd.transform("median")
    c["anos"] = (c.vencimiento_utc - c.instantanea_utc).dt.total_seconds() / SEGUNDOS_ANO
    c["mid_btc"] = ((c.bid_btc + c.ask_btc) / 2).where(c.bid_btc.notna() & c.ask_btc.notna(), c.mark_btc)
    return c


def paridad(cadena: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (vencimiento, strike) con call y put: desviación de la paridad y violación fuera del spread."""
    c = _con_plazo(cadena)
    clave = ["indice_subyacente", "vencimiento_utc", "strike"]
    comunes = [*clave, "forward", "anos", "subyacente_es_futuro"]
    columnas = ["bid_btc", "ask_btc", "mid_btc", "comision_taker"]
    t = c[c.tipo_opcion == "call"][comunes + columnas].merge(
        c[c.tipo_opcion == "put"][clave + columnas], on=clave, suffixes=("_c", "_p"))
    t["teorico_btc"] = 1 - t.strike / t.forward
    t["desviacion_bps"] = ((t.mid_btc_c - t.mid_btc_p) - t.teorico_btc) * 1e4
    t["inferior_btc"] = t.bid_btc_c - t.ask_btc_p
    t["superior_btc"] = t.ask_btc_c - t.bid_btc_p
    t["con_cotizaciones"] = t[["bid_btc_c", "ask_btc_c", "bid_btc_p", "ask_btc_p"]].notna().all(axis=1)
    exceso = np.maximum(np.maximum(t.inferior_btc - t.teorico_btc, t.teorico_btc - t.superior_btc), 0.0) * 1e4
    t["exceso_bps"] = exceso.where(t.con_cotizaciones)
    t["ancho_banda_bps"] = ((t.superior_btc - t.inferior_btc) * 1e4).where(t.con_cotizaciones)
    t["violacion"] = t.con_cotizaciones & (t.exceso_bps > 1e-9)
    t["comisiones_bps"] = (t.comision_taker_c.fillna(0) + t.comision_taker_p.fillna(0)) * 1e4
    t["violacion_tras_comisiones"] = t.violacion & (t.exceso_bps > t.comisiones_bps)
    return t.sort_values(clave).reset_index(drop=True)


def forward_implicito(tabla: pd.DataFrame, n: int = N_ATM_FORWARD) -> dict:
    """{subyacente: F implícito por la paridad}, mediana de los `n` strikes más cercanos al forward."""
    salida = {}
    for sub, g in tabla.groupby("indice_subyacente"):
        g = g[g.mid_btc_c.notna() & g.mid_btc_p.notna()]
        g = g.assign(distancia=np.abs(np.log(g.strike / g.forward))).nsmallest(n, "distancia")
        f = g.strike / (1 - (g.mid_btc_c - g.mid_btc_p))
        salida[sub] = float(f[f > 0].median()) if len(f) else math.nan
    return salida


def _plazo_dias(anos: float) -> str:
    return f"{anos * 365:.1f} días"


# --- paridad ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoParidad:
    indice_subyacente: str            # "todos" para el agregado de la cadena
    vencimiento_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    dias: float
    subyacente_es_futuro: bool | None
    forward_usd: float
    forward_implicito_usd: float
    dif_forward_bps: float
    n_pares: int
    n_con_cotizaciones: int
    n_violaciones: int
    n_violaciones_tras_comisiones: int
    mediana_desviacion_bps: float
    mediana_abs_desviacion_bps: float
    mediana_ancho_banda_bps: float
    max_exceso_bps: float

    @property
    def fraccion_violaciones(self) -> float:
        return self.n_violaciones / self.n_con_cotizaciones if self.n_con_cotizaciones else math.nan

    @property
    def estado(self) -> str:
        if self.n_con_cotizaciones < MIN_PARES:
            return INSUFICIENTE
        if self.n_violaciones == 0:
            return DENTRO
        return AISLADAS if self.fraccion_violaciones <= FRACCION_AISLADAS else FRECUENTES

    def conclusion(self) -> str:
        if self.indice_subyacente == "todos":
            cabecera = "Paridad put-call, toda la cadena"
        else:
            tipo = "futuro listado" if self.subyacente_es_futuro else "forward sintético"
            cabecera = (f"Paridad put-call, {self.indice_subyacente} ({_plazo_dias(self.dias / 365)}, {tipo} "
                        f"{self.forward_usd:,.0f} USD)")
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_con_cotizaciones} pares con bid y ask en call y put; "
                    f"hacen falta {MIN_PARES}).")
        texto = (f"{cabecera}: {self.estado}. {self.n_violaciones} de {self.n_con_cotizaciones} pares fuera de "
                 f"[c_bid − p_ask, c_ask − p_bid] ({self.fraccion_violaciones:.1%}), {self.n_violaciones_tras_comisiones} "
                 f"también tras dos comisiones taker; desviación mediana con los mid "
                 f"{self.mediana_desviacion_bps:+.1f} bps del forward (|·| {self.mediana_abs_desviacion_bps:.1f}) "
                 f"frente a una banda mediana de {self.mediana_ancho_banda_bps:.1f} bps; mayor exceso "
                 f"{self.max_exceso_bps:.1f} bps.")
        if self.indice_subyacente != "todos" and math.isfinite(self.dif_forward_bps):
            texto += (f" Forward implícito {self.forward_implicito_usd:,.0f} USD ({self.dif_forward_bps:+.1f} bps "
                      f"frente al subyacente de Deribit).")
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "paridad", **asdict(self), "fraccion_violaciones": self.fraccion_violaciones,
                "estado": self.estado, "conclusion": self.conclusion()}


def _resultado_paridad(nombre, g: pd.DataFrame, hasta, vencimiento, forward_impl: float) -> ResultadoParidad:
    con = g[g.con_cotizaciones]
    forward = float(g.forward.median()) if len(g) else math.nan
    es_futuro = None if nombre == "todos" or g.empty else bool(g.subyacente_es_futuro.iloc[0])
    return ResultadoParidad(
        indice_subyacente=nombre, vencimiento_utc=vencimiento, hasta_utc=hasta,
        dias=float(g.anos.iloc[0] * 365) if nombre != "todos" and len(g) else math.nan,
        subyacente_es_futuro=es_futuro, forward_usd=forward if nombre != "todos" else math.nan,
        forward_implicito_usd=forward_impl,
        dif_forward_bps=(forward_impl / forward - 1) * 1e4 if nombre != "todos" else math.nan,
        n_pares=len(g), n_con_cotizaciones=len(con), n_violaciones=int(con.violacion.sum()),
        n_violaciones_tras_comisiones=int(con.violacion_tras_comisiones.sum()),
        mediana_desviacion_bps=float(con.desviacion_bps.median()) if len(con) else math.nan,
        mediana_abs_desviacion_bps=float(con.desviacion_bps.abs().median()) if len(con) else math.nan,
        mediana_ancho_banda_bps=float(con.ancho_banda_bps.median()) if len(con) else math.nan,
        max_exceso_bps=float(con.exceso_bps.max()) if len(con) else math.nan)


def estudiar_paridad(cadena: pd.DataFrame) -> list[ResultadoParidad]:
    """Un resultado por vencimiento y otro de toda la cadena."""
    tabla = paridad(cadena)
    hasta = pd.Timestamp(cadena.instantanea_utc.max())
    fwd = forward_implicito(tabla)
    resultados = [_resultado_paridad(sub, g, hasta, pd.Timestamp(g.vencimiento_utc.iloc[0]), fwd.get(sub, math.nan))
                  for sub, g in tabla.groupby("indice_subyacente", sort=False)]
    resultados.sort(key=lambda r: r.vencimiento_utc)
    return [*resultados, _resultado_paridad("todos", tabla, hasta, pd.NaT, math.nan)]


# --- validación frente a Deribit --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoValidacion:
    hasta_utc: pd.Timestamp
    n_opciones: int
    n_itm_excluidas: int
    n_iv: int
    n_fallos_iv: int
    mediana_dif_iv_puntos: float
    p95_dif_iv_puntos: float
    max_dif_iv_puntos: float
    n_griegas: int
    mediana_dif_delta: float
    max_dif_delta: float
    max_dif_gamma: float
    mediana_dif_rel_vega: float
    mediana_dif_rel_theta: float
    mediana_dif_rel_rho: float

    @property
    def estado(self) -> str:
        if self.n_iv < MIN_OPCIONES_VALIDACION:
            return INSUFICIENTE
        iv_ok = self.mediana_dif_iv_puntos < TOL_IV_PUNTOS
        griegas_ok = self.n_griegas == 0 or (
            self.mediana_dif_delta < TOL_DELTA and self.mediana_dif_rel_vega < TOL_RELATIVA
            and self.mediana_dif_rel_theta < TOL_RELATIVA and self.mediana_dif_rel_rho < TOL_RELATIVA)
        return COINCIDE if iv_ok and griegas_ok else DISCREPA

    def conclusion(self) -> str:
        cabecera = "Black-76 frente a Deribit"
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n_iv} opciones con mark e IV; hacen falta " \
                   f"{MIN_OPCIONES_VALIDACION})."
        texto = (f"{cabecera}: {self.estado}. IV recalculada desde el mark en {self.n_iv} opciones fuera del "
                 f"dinero ({self.n_itm_excluidas} dentro del dinero excluidas; {self.n_fallos_iv} sin solución dentro "
                 f"de las cotas): diferencia mediana "
                 f"{self.mediana_dif_iv_puntos:.4f} puntos, p95 {self.p95_dif_iv_puntos:.4f}, máxima "
                 f"{self.max_dif_iv_puntos:.3f}.")
        if self.n_griegas:
            texto += (f" Griegas en {self.n_griegas} opciones: delta mediana {self.mediana_dif_delta:.1e} (máx. "
                      f"{self.max_dif_delta:.1e}), gamma máx. {self.max_dif_gamma:.1e}; diferencia relativa mediana "
                      f"vega {self.mediana_dif_rel_vega:.2%}, theta {self.mediana_dif_rel_theta:.2%}, rho "
                      f"{self.mediana_dif_rel_rho:.2%}.")
        else:
            texto += " Sin griegas publicadas en la foto (captura sin tickers)."
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "validacion", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def _mediana(x) -> float:
    x = pd.Series(x, dtype=float).dropna()
    return float(x.median()) if len(x) else math.nan


def _maximo(x) -> float:
    x = pd.Series(x, dtype=float).dropna()
    return float(x.max()) if len(x) else math.nan


def validar_contra_deribit(cadena: pd.DataFrame) -> ResultadoValidacion:
    """IV recalculada desde el mark (y griegas al mark IV del ticker) frente a lo que publica Deribit."""
    c = cadena[(cadena.mark_btc > 0) & (cadena.iv_mark > 0) & (cadena.subyacente_usd > 0)]
    otm = ((c.tipo_opcion == "put") & (c.strike < c.subyacente_usd)) | ((c.tipo_opcion == "call")
                                                                       & (c.strike >= c.subyacente_usd))
    n_itm = int((~otm).sum())
    c = c[otm]
    dif_iv, fallos = [], 0
    for f in c.itertuples():
        t = anos_hasta(f.vencimiento_utc, f.hora_resumen_utc)
        iv = volatilidad_implicita(float(f.mark_btc * f.subyacente_usd), float(f.subyacente_usd), float(f.strike), t,
                                   f.tipo_opcion)
        if math.isnan(iv):
            fallos += 1
        else:
            dif_iv.append(abs(iv - f.iv_mark) * 100)
    g = cadena[cadena.delta.notna() & (cadena.iv_mark_ticker > 0) & (cadena.subyacente_ticker_usd > 0)]
    difs = {n: [] for n in ("delta", "gamma", "vega", "theta", "rho")}
    for f in g.itertuples():
        t = anos_hasta(f.vencimiento_utc, f.hora_ticker_utc)
        if t <= 0:
            continue
        nuestras = griegas_deribit(float(f.subyacente_ticker_usd), float(f.strike), t, float(f.iv_mark_ticker),
                                   f.tipo_opcion)
        for n in ("delta", "gamma"):
            difs[n].append(abs(nuestras[n] - getattr(f, n)))
        for n in ("vega", "theta", "rho"):
            publicada = getattr(f, n)
            difs[n].append(abs(nuestras[n] - publicada) / max(abs(publicada), PISO_GRIEGA))
    dif_iv = pd.Series(dif_iv, dtype=float)
    return ResultadoValidacion(
        hasta_utc=pd.Timestamp(cadena.instantanea_utc.max()), n_opciones=len(cadena), n_itm_excluidas=n_itm,
        n_iv=len(dif_iv) + fallos,
        n_fallos_iv=fallos, mediana_dif_iv_puntos=_mediana(dif_iv),
        p95_dif_iv_puntos=float(dif_iv.quantile(0.95)) if len(dif_iv) else math.nan,
        max_dif_iv_puntos=_maximo(dif_iv), n_griegas=len(difs["delta"]), mediana_dif_delta=_mediana(difs["delta"]),
        max_dif_delta=_maximo(difs["delta"]), max_dif_gamma=_maximo(difs["gamma"]),
        mediana_dif_rel_vega=_mediana(difs["vega"]), mediana_dif_rel_theta=_mediana(difs["theta"]),
        mediana_dif_rel_rho=_mediana(difs["rho"]))


# --- sonrisa ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoSonrisa:
    indice_subyacente: str
    vencimiento_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    dias: float
    forward_usd: float
    n_otm_puts: int
    n_otm_calls: int
    iv_atm: float
    iv_put25: float
    iv_call25: float
    rr25: float
    mariposa25: float
    iv_minima: float
    strike_iv_minima: float

    @property
    def estado(self) -> str:
        if (min(self.n_otm_puts, self.n_otm_calls) < MIN_POR_LADO or not math.isfinite(self.iv_atm)
                or not math.isfinite(self.rr25)):
            return INSUFICIENTE
        if self.rr25 < -UMBRAL_RR:
            return SKEW_PUTS
        return SKEW_CALLS if self.rr25 > UMBRAL_RR else SIMETRICA

    def conclusion(self) -> str:
        cabecera = f"Sonrisa {self.indice_subyacente} ({_plazo_dias(self.dias / 365)}, forward {self.forward_usd:,.0f} USD)"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_otm_puts} puts y {self.n_otm_calls} calls fuera del "
                    f"dinero con IV; hacen falta {MIN_POR_LADO} por lado y cubrir ATM y 25Δ).")
        return (f"{cabecera}: {self.estado}. IV ATM {self.iv_atm:.1%}; put −25Δ {self.iv_put25:.1%}, call 25Δ "
                f"{self.iv_call25:.1%}: risk reversal {self.rr25 * 100:+.1f} puntos, mariposa "
                f"{self.mariposa25 * 100:+.1f}; IV mínima {self.iv_minima:.1%} en K = {self.strike_iv_minima:,.0f}.")

    def a_fila(self) -> dict:
        return {"estudio": "sonrisa", **asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def _interpolar(x, y, x0) -> float:
    orden = np.argsort(x)
    x, y = np.asarray(x, dtype=float)[orden], np.asarray(y, dtype=float)[orden]
    if len(x) < 2 or not x[0] <= x0 <= x[-1]:
        return math.nan
    return float(np.interp(x0, x, y))


def _sonrisa(sub, g: pd.DataFrame, hasta) -> ResultadoSonrisa:
    f, t = float(g.forward.iloc[0]), float(g.anos.iloc[0])
    g = g[(g.iv_mark > 0) & (g.mark_btc > 0)]
    otm = g[((g.tipo_opcion == "put") & (g.strike < f)) | ((g.tipo_opcion == "call") & (g.strike >= f))]
    otm = otm.assign(k=np.log(otm.strike / f))
    puts, calls = otm[otm.tipo_opcion == "put"], otm[otm.tipo_opcion == "call"]
    delta = lambda d: ndtr(_d1_d2(f, d.strike.to_numpy(), t, d.iv_mark.to_numpy())[0]) if t > 0 else np.array([])
    iv_put25 = _interpolar(delta(puts) - 1, puts.iv_mark, -0.25) if len(puts) and t > 0 else math.nan
    iv_call25 = _interpolar(delta(calls), calls.iv_mark, 0.25) if len(calls) and t > 0 else math.nan
    iv_atm = _interpolar(otm.k, otm.iv_mark, 0.0)
    minimo = otm.loc[otm.iv_mark.idxmin()] if len(otm) else None
    return ResultadoSonrisa(
        indice_subyacente=sub, vencimiento_utc=pd.Timestamp(g.vencimiento_utc.iloc[0]) if len(g) else pd.NaT,
        hasta_utc=hasta, dias=t * 365, forward_usd=f, n_otm_puts=len(puts), n_otm_calls=len(calls), iv_atm=iv_atm,
        iv_put25=iv_put25, iv_call25=iv_call25, rr25=iv_call25 - iv_put25,
        mariposa25=(iv_call25 + iv_put25) / 2 - iv_atm,
        iv_minima=float(minimo.iv_mark) if minimo is not None else math.nan,
        strike_iv_minima=float(minimo.strike) if minimo is not None else math.nan)


def estudiar_sonrisa(cadena: pd.DataFrame) -> list[ResultadoSonrisa]:
    """Un resultado por vencimiento, del más cercano al más lejano."""
    c = _con_plazo(cadena)
    hasta = pd.Timestamp(cadena.instantanea_utc.max())
    return [_sonrisa(sub, g, hasta) for _, g in c.groupby("vencimiento_utc", sort=True)
            for sub in [g.indice_subyacente.iloc[0]]]


# --- estructura temporal ----------------------------------------------------------------------------------------


def iv_atm_a_plazo(estructura: pd.DataFrame, anos: float) -> float:
    """IV ATM al plazo `anos`, interpolando la varianza total σ²T linealmente en T; NaN fuera del rango."""
    e = estructura.dropna(subset=["iv_atm"]).sort_values("anos")
    if e.empty or not e.anos.iloc[0] <= anos <= e.anos.iloc[-1] or anos <= 0:
        return math.nan
    w = float(np.interp(anos, e.anos, e.iv_atm ** 2 * e.anos))
    return math.sqrt(w / anos) if w > 0 else math.nan


def _tabla_estructura(sonrisas: list[ResultadoSonrisa]) -> pd.DataFrame:
    return pd.DataFrame([{"indice_subyacente": s.indice_subyacente, "anos": s.dias / 365, "iv_atm": s.iv_atm}
                         for s in sonrisas], columns=["indice_subyacente", "anos", "iv_atm"])


@dataclass(frozen=True)
class ResultadoEstructura:
    hasta_utc: pd.Timestamp
    n_vencimientos: int
    dias_corto: float
    iv_atm_corto: float
    dias_largo: float
    iv_atm_largo: float
    monotona: bool
    iv_atm_7d: float
    iv_atm_30d: float
    iv_atm_90d: float

    @property
    def diferencia(self) -> float:
        return self.iv_atm_largo - self.iv_atm_corto

    @property
    def forma(self) -> str:
        if self.n_vencimientos < 2:
            return INSUFICIENTE
        if self.diferencia > UMBRAL_RR:
            return CRECIENTE
        return INVERTIDA if self.diferencia < -UMBRAL_RR else PLANA

    @property
    def estado(self) -> str:
        return self.forma

    def conclusion(self) -> str:
        cabecera = "Estructura temporal de la IV ATM"
        if self.forma == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes ({self.n_vencimientos} vencimientos de al menos " \
                   f"{MIN_DIAS_ESTRUCTURA:g} días con IV ATM)."
        a_plazo = ", ".join(f"{d} días {v:.1%}" for d, v in zip(DIAS_ESTRUCTURA, (self.iv_atm_7d, self.iv_atm_30d,
                                                                                   self.iv_atm_90d))
                            if math.isfinite(v))
        return (f"{cabecera}: {self.forma} ({self.n_vencimientos} vencimientos, "
                f"{'monótona' if self.monotona else 'no monótona'}): {self.iv_atm_corto:.1%} a "
                f"{self.dias_corto:.1f} días frente a {self.iv_atm_largo:.1%} a {self.dias_largo:.0f} días "
                f"({self.diferencia * 100:+.1f} puntos). Interpolada en varianza total: {a_plazo}.")

    def a_fila(self) -> dict:
        return {"estudio": "estructura", **asdict(self), "diferencia": self.diferencia, "forma": self.forma,
                "estado": self.estado, "conclusion": self.conclusion()}


def estudiar_estructura(cadena: pd.DataFrame, sonrisas: list[ResultadoSonrisa] | None = None) -> ResultadoEstructura:
    sonrisas = estudiar_sonrisa(cadena) if sonrisas is None else sonrisas
    tabla = _tabla_estructura(sonrisas)
    e = tabla[(tabla.anos * 365 >= MIN_DIAS_ESTRUCTURA) & tabla.iv_atm.notna()].sort_values("anos")
    pasos = np.diff(e.iv_atm.to_numpy())
    vacia = e.empty
    interpolada = [iv_atm_a_plazo(tabla, d / 365) for d in DIAS_ESTRUCTURA]
    return ResultadoEstructura(
        hasta_utc=pd.Timestamp(cadena.instantanea_utc.max()), n_vencimientos=len(e),
        dias_corto=math.nan if vacia else float(e.anos.iloc[0] * 365),
        iv_atm_corto=math.nan if vacia else float(e.iv_atm.iloc[0]),
        dias_largo=math.nan if vacia else float(e.anos.iloc[-1] * 365),
        iv_atm_largo=math.nan if vacia else float(e.iv_atm.iloc[-1]),
        monotona=bool(len(pasos) and (np.all(pasos > 0) or np.all(pasos < 0))),
        iv_atm_7d=interpolada[0], iv_atm_30d=interpolada[1], iv_atm_90d=interpolada[2])


# --- volatilidad realizada --------------------------------------------------------------------------------------


def vol_realizada(velas: pd.DataFrame, hasta, dias: float, intervalo_s: int = 3600) -> tuple[float, int]:
    """(volatilidad anualizada, n retornos) de las velas cerradas en los `dias` anteriores a `hasta`."""
    hasta = pd.Timestamp(hasta)
    paso = pd.Timedelta(seconds=intervalo_s)
    if velas.empty:
        return math.nan, 0
    v = velas[(velas.intervalo_s == intervalo_s) & (velas.inicio_utc >= hasta - pd.Timedelta(days=dias))
              & (velas.inicio_utc + paso <= hasta)]
    if v.empty:
        return math.nan, 0
    r = preparar_retornos(v).ret_log.dropna()
    if len(r) < 2:
        return math.nan, len(r)
    return float(r.std(ddof=1) * factor_anual(intervalo_s)), len(r)


@dataclass(frozen=True)
class ResultadoRealizada:
    dias: int
    hasta_utc: pd.Timestamp
    fuente_velas: str
    par: str
    iv_atm_plazo: float
    vol_realizada: float
    n_retornos: int
    minimo: int

    @property
    def diferencia_puntos(self) -> float:
        return (self.iv_atm_plazo - self.vol_realizada) * 100

    @property
    def ratio(self) -> float:
        return self.iv_atm_plazo / self.vol_realizada if self.vol_realizada else math.nan

    @property
    def estado(self) -> str:
        if self.n_retornos < self.minimo or not math.isfinite(self.iv_atm_plazo) or not math.isfinite(self.vol_realizada):
            return INSUFICIENTE
        return IMPLICITA_MAYOR if self.iv_atm_plazo > self.vol_realizada else IMPLICITA_MENOR

    def conclusion(self) -> str:
        cabecera = f"IV ATM a {self.dias} días frente a la realizada de los {self.dias} días anteriores"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_retornos} retornos horarios de {self.fuente_velas} "
                    f"{self.par}, hacen falta {self.minimo}; IV ATM "
                    f"{'disponible' if math.isfinite(self.iv_atm_plazo) else 'no disponible a ese plazo'}).")
        return (f"{cabecera}: {self.estado}. IV {self.iv_atm_plazo:.1%} (BTC/USD, Deribit) frente a "
                f"{self.vol_realizada:.1%} realizada ({self.n_retornos} retornos horarios de {self.fuente_velas} "
                f"{self.par}): {self.diferencia_puntos:+.1f} puntos, ratio {self.ratio:.2f}. La realizada mira "
                f"atrás y la implícita adelante; EUR frente a USD añade uno o dos puntos de diferencia.")

    def a_fila(self) -> dict:
        return {"estudio": "realizada", **asdict(self), "diferencia_puntos": self.diferencia_puntos,
                "ratio": self.ratio, "estado": self.estado, "conclusion": self.conclusion()}


def estudiar_realizada(sonrisas: list[ResultadoSonrisa], velas: pd.DataFrame, hasta,
                       ventanas=VENTANAS_REALIZADA, fuente: str = "kraken_historico",
                       par: str = "BTC/EUR") -> list[ResultadoRealizada]:
    tabla = _tabla_estructura(sonrisas)
    resultados = []
    for dias in ventanas:
        vol, n = vol_realizada(velas, hasta, dias)
        resultados.append(ResultadoRealizada(
            dias=int(dias), hasta_utc=pd.Timestamp(hasta), fuente_velas=fuente, par=par,
            iv_atm_plazo=iv_atm_a_plazo(tabla, dias / 365), vol_realizada=vol, n_retornos=n,
            minimo=int(COBERTURA_MINIMA * dias * 24)))
    return resultados


# --- estudio completo y lake ------------------------------------------------------------------------------------


def estudiar_opciones(cadena: pd.DataFrame, velas: pd.DataFrame | None = None) -> list:
    """Paridad (por vencimiento y total), validación frente a Deribit, sonrisas, estructura y realizada."""
    if cadena.empty:
        return []
    hasta = pd.Timestamp(cadena.instantanea_utc.max())
    sonrisas = estudiar_sonrisa(cadena)
    velas = pd.DataFrame() if velas is None else velas
    return [*estudiar_paridad(cadena), validar_contra_deribit(cadena), *sonrisas,
            estudiar_estructura(cadena, sonrisas), *estudiar_realizada(sonrisas, velas, hasta)]


def leer_ultima_cadena(consultar: Callable[[str], pd.DataFrame], instantanea=None) -> pd.DataFrame:
    """La foto más reciente (o la de `instantanea`) de `opciones_cadena`; vacía si aún no hay ninguna."""
    filtro = (f"TIMESTAMPTZ '{pd.Timestamp(instantanea).isoformat()}'" if instantanea is not None
              else f"(SELECT max(instantanea_utc) FROM {FUENTE_CADENA})")
    try:
        df = consultar(f"""SELECT * FROM {FUENTE_CADENA} WHERE instantanea_utc = {filtro}
            QUALIFY row_number() OVER (PARTITION BY instrumento ORDER BY recibido_utc DESC) = 1""")
    except Exception as error:   # todavía no existe la vista
        if FUENTE_CADENA in str(error).lower():
            return pd.DataFrame()
        raise
    return df.drop(columns=["fecha"], errors="ignore").reset_index(drop=True)


def _velas_horarias(consultar, hasta, dias: int) -> pd.DataFrame:
    from radar.analisis.velas import leer_velas
    try:
        return leer_velas(consultar, "kraken_historico", "kraken", 3600, pd.Timestamp(hasta) - pd.Timedelta(days=dias),
                          hasta)
    except Exception as error:   # todavía no existe la vista `velas`
        if "velas" in str(error).lower():
            return pd.DataFrame()
        raise


def estudiar_opciones_lake(consultar: Callable[[str], pd.DataFrame], instantanea=None) -> list:
    cadena = leer_ultima_cadena(consultar, instantanea)
    if cadena.empty:
        return []
    hasta = pd.Timestamp(cadena.instantanea_utc.max())
    return estudiar_opciones(cadena, _velas_horarias(consultar, hasta, max(VENTANAS_REALIZADA) + 1))


def guardar_estudio_opciones(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución en `estudios_opciones`; `hasta_utc` es la hora de la foto de la cadena."""
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_OPCIONES)
