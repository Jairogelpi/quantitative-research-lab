"""Perpetuos BTC con datos reales (OKX BTC-USDT-SWAP, Kraken Futures PF_XBTUSD): basis, funding, carry, OI y
liquidaciones (Fase 7). Estudio DESCRIPTIVO: mide y resume; no contrasta hipótesis ni guarda p-valores ni t.

Conceptos (definiciones de P07, `src/quantlab/p07/derivatives.py` y docs/conceptos/derivados_perpetuos.md):
- Perpetuo lineal: contrato sin vencimiento liquidado en la moneda de cotización (USDT en OKX, USD en Kraken).
- Mark e índice: el índice es la media de varios mercados spot (la referencia del subyacente; no es negociable) y
  el mark, el precio con el que el exchange valora posiciones y decide liquidaciones. Aquí se usan los cierres
  horarios de las tres series (mark, índice y precio negociado del perpetuo).
- Basis: 10⁴ · (P_perp − índice) / índice, en bps; prima (+) o descuento (−). También el del mark (mark − índice).
- Basis anualizado: un perpetuo no vence, así que el basis no converge en una fecha. Su única escala de tiempo es el
  funding, que cobra la prima en unas 8 h (OKX paga cada 8 h una tasa ligada a la prima; Kraken cobra cada hora
  prima / 8, `fundingRateCoefficient` = 8 en `/derivatives/api/v3/instruments`). Por convenio: basis anualizado =
  basis · 8 760 / 8, lo que pagarían los largos en un año si la prima se mantuviera y se cobrara entera cada 8 h.
  Así el basis y el funding anualizados son comparables: si el funding solo cobrara la prima, coincidirían.
- Funding y su pago: tasa liquidada por periodo (fracción del nominal); positiva, los largos pagan a los cortos.
  Pago de un short de q BTC: q · mark · tasa (OKX) o q · `tasa_absoluta` (Kraken, USD por contrato de 1 BTC).
  Anualizado: tasa · 8 760 / horas del periodo (8 h en OKX, 1 h en Kraken).
- Relación basis–funding: por cada periodo de funding, la prima media mark − índice de sus horas frente a la tasa
  liquidada, las dos anualizadas: correlación y pendiente (1 = el funding cobra exactamente la prima).
- Carry de una cobertura (cash and carry): largo q BTC spot + corto q BTC perpetuo, abierta al cierre de la primera
  hora y cerrada al de la última. Solo FUNDING OBSERVADO (los pagos liquidados entre la entrada y la salida), nunca
  una previsión. Resultado = q · ((S_t − S_0) − (P_t − P_0)) [= −q · variación del basis] + funding cobrado −
  comisiones de las dos piernas, al abrir y al cerrar: q · (S_0 + S_t) · f_spot + q · (P_0 + P_t) · f_perp. El
  spot se aproxima con el índice (no hay un BTC/USD spot propio). Capital = q · S_0 + garantía del short.
- Margen y umbral de mantenimiento: la cuenta del short vale garantía + q · (P_0 − mark) + funding − comisión de
  apertura; si baja de q · mark · tasa de mantenimiento, el exchange puede liquidarla aunque la pierna spot gane lo
  mismo (las cuentas están separadas). Kraken PF_XBTUSD: primer tramo de `marginLevels` con margen inicial 1 % y
  mantenimiento 0,5 % (comprobado el 22-11-2026 en `/derivatives/api/v3/instruments`). Un short apalancado A veces
  (garantía = nominal / A) cruza el umbral con una subida del mark de (1 + 1/A) / (1 + m) − 1 (fórmula de P07 sin
  comisiones): 9,45 % a 10x con m = 0,5 %.
- Open interest: contratos abiertos (en BTC; cada uno tiene un largo y un corto). Su cambio horario en % frente a
  los movimientos grandes del precio (|retorno horario| ≥ el cuantil `CUANTIL_MOVIMIENTO` de la serie).
- Grupos de liquidaciones: horas con volumen liquidado por encima del cuantil `CUANTIL_LIQUIDACION`, unidas si son
  consecutivas. Se mide qué fracción de grupos tiene un movimiento grande a ±`VECINDAD_H` h, frente a la fracción
  de horas cualesquiera que lo tienen (base). Es una coincidencia descriptiva, no causalidad ni predicción: la
  liquidación forzada ES parte del movimiento. OKX solo sirve ~1 día de órdenes liquidadas (una muestra) y Kraken
  el volumen por hora sin separar largos y cortos.

Estados:
- datos insuficientes: menos de `MIN_HORAS` horas con mark, índice y perpetuo.
- descrito: el resto. Por partes: `estado_carry` (carry neto positivo / negativo / datos insuficientes) y
  `estado_liquidaciones` (liquidaciones agrupadas con movimientos grandes, si la fracción es ≥ `RATIO_AGRUPADAS`
  veces la base con ≥ `MIN_GRUPOS` grupos; si no, sin agrupamiento visible; o datos insuficientes). Ninguno es un
  hallazgo del registro de pruebas (`registro.HALLAZGOS`): las filas no llevan estadístico y no entran en la familia.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from radar.captura import historico_derivados as hd
from radar.configuracion import comisiones_taker

METODO = "derivados/v1"
FUENTE_ESTUDIO = "estudios_derivados"
HORAS_ANO = 8760
HORAS_CONVERGENCIA = 8          # el funding absorbe la prima en unas 8 h (ver "Basis anualizado")
MIN_HORAS = 24 * 7
MIN_PAGOS = 21
MIN_HORAS_LIQUIDACION = 24 * 7
MIN_GRUPOS = 5
CUANTIL_MOVIMIENTO = 0.99
CUANTIL_LIQUIDACION = 0.99
VECINDAD_H = 1
RATIO_AGRUPADAS = 2.0
Q_BTC = 1.0
GARANTIA = 0.5                  # garantía del short como fracción del nominal (x2: lejos del mantenimiento)
MANTENIMIENTO = 0.005           # Kraken PF_XBTUSD, primer tramo (verificado); se usa también en OKX como ejemplo
APALANCAMIENTO_EJEMPLO = 10
# Spot: OKX con cuenta de spot y derivados 0,10 % (nota de `configuracion.COMISIONES_TAKER`); Kraken, su taker spot.
COMISIONES_SPOT = {"okx": 0.0010, "kraken": comisiones_taker()["kraken"]}
# Perpetuo: 0,05 % taker en los dos, SUPUESTO (no verificado en esta fase): cámbialo con `comisiones_perp`.
COMISIONES_PERP = {"okx": 0.0005, "kraken": 0.0005}

INSUFICIENTE, DESCRITO = "datos insuficientes", "descrito"
CARRY_POSITIVO, CARRY_NEGATIVO = "carry neto positivo", "carry neto negativo"
AGRUPADAS, SIN_AGRUPAMIENTO = "liquidaciones agrupadas con movimientos grandes", "sin agrupamiento visible"


# --- Cálculos ------------------------------------------------------------------------------------------------------

def basis_bps(precio, indice):
    """10⁴ · (precio − índice) / índice."""
    return (precio - indice) / indice * 1e4


def anualizar_basis(basis_en_bps, horas_convergencia: float = HORAS_CONVERGENCIA):
    """Basis en bps → fracción anual, si la prima se cobrara entera cada `horas_convergencia` horas."""
    return basis_en_bps / 1e4 * HORAS_ANO / horas_convergencia


def anualizar_funding(tasa, periodo_h):
    """Tasa por periodo → fracción anual (periodos por año = 8 760 / horas del periodo)."""
    return tasa * HORAS_ANO / periodo_h


def _cierre(horas: pd.DataFrame) -> pd.Series:
    return pd.Series(horas.index + pd.Timedelta(hours=1), index=horas.index)


def carry_cobertura(horas: pd.DataFrame, funding: pd.DataFrame, q_btc: float = Q_BTC, comision_spot: float = 0.0,
                    comision_perp: float = 0.0, garantia: float = GARANTIA,
                    mantenimiento: float = MANTENIMIENTO) -> dict:
    """Largo q BTC (índice) + corto q BTC perpetuo con el funding OBSERVADO entre la entrada y la salida.

    `horas`: índice `inicio_utc` horario y columnas `indice`, `perp`, `mark` (cierres). `funding`: `periodo_fin_utc`,
    `tasa`, `tasa_absoluta` (NaN si no la hay). Entrada al cierre de la primera hora; salida al de la última."""
    h = horas.dropna(subset=["indice", "perp", "mark"])
    vacio = {"n_pagos": 0, "horas": 0, "funding_usd": math.nan, "pnl_basis_usd": math.nan,
             "comisiones_usd": math.nan, "neto_usd": math.nan, "neto_sin_comisiones_usd": math.nan,
             "capital_usd": math.nan, "rentabilidad": math.nan, "rentabilidad_anual": math.nan,
             "garantia_minima_usd": math.nan, "cruza_mantenimiento": False, "entrada_utc": pd.NaT,
             "salida_utc": pd.NaT}
    if len(h) < 2:
        return vacio
    entrada, salida = h.index[0] + pd.Timedelta(hours=1), h.index[-1] + pd.Timedelta(hours=1)
    s0, p0, st, pt = h["indice"].iloc[0], h["perp"].iloc[0], h["indice"].iloc[-1], h["perp"].iloc[-1]
    funding = funding.assign(periodo_fin_utc=pd.to_datetime(funding["periodo_fin_utc"], utc=True))
    pagos = funding[(funding["periodo_fin_utc"] > entrada) & (funding["periodo_fin_utc"] <= salida)].copy()
    pagos = pagos.dropna(subset=["tasa"]).sort_values("periodo_fin_utc")
    if pagos.empty:
        return {**vacio, "horas": len(h) - 1, "entrada_utc": entrada, "salida_utc": salida}
    mark_cierre = pd.Series(h["mark"].to_numpy(), index=h.index + pd.Timedelta(hours=1))
    mark_pago = mark_cierre.reindex(mark_cierre.index.union(pagos["periodo_fin_utc"])).ffill()
    mark_pago = mark_pago.reindex(pagos["periodo_fin_utc"]).to_numpy()
    absoluta = pd.to_numeric(pagos.get("tasa_absoluta"), errors="coerce").to_numpy(dtype=float)
    cobro = np.where(np.isfinite(absoluta), q_btc * absoluta, q_btc * mark_pago * pagos["tasa"].to_numpy(dtype=float))
    funding_usd = float(np.sum(cobro))
    pnl_basis = q_btc * ((st - s0) - (pt - p0))
    comisiones = q_btc * (s0 + st) * comision_spot + q_btc * (p0 + pt) * comision_perp
    neto = pnl_basis + funding_usd - comisiones
    garantia_usd = garantia * q_btc * p0
    capital = q_btc * s0 + garantia_usd
    n_horas = len(h) - 1
    # Cuenta del short hora a hora: funding acumulado hasta el cierre de cada hora.
    cobros = pd.Series(cobro, index=pagos["periodo_fin_utc"].to_numpy())
    acumulado = cobros.cumsum().reindex(cobros.index.union(mark_cierre.index)).ffill().fillna(0.0)
    acumulado = acumulado.reindex(mark_cierre.index).to_numpy()
    cuenta = garantia_usd + q_btc * (p0 - h["mark"].to_numpy()) + acumulado - q_btc * p0 * comision_perp
    umbral = q_btc * h["mark"].to_numpy() * mantenimiento
    return {"n_pagos": len(pagos), "horas": n_horas, "funding_usd": funding_usd, "pnl_basis_usd": pnl_basis,
            "comisiones_usd": comisiones, "neto_usd": neto, "neto_sin_comisiones_usd": pnl_basis + funding_usd,
            "capital_usd": capital, "rentabilidad": neto / capital,
            "rentabilidad_anual": neto / capital * HORAS_ANO / n_horas if n_horas else math.nan,
            "garantia_minima_usd": float(np.min(cuenta)), "cruza_mantenimiento": bool(np.any(cuenta <= umbral)),
            "entrada_utc": entrada, "salida_utc": salida}


def relacion_basis_funding(horas: pd.DataFrame, funding: pd.DataFrame) -> dict:
    """Prima media mark − índice de cada periodo de funding frente a su tasa liquidada, ambas anualizadas."""
    prima = basis_bps(horas["mark"], horas["indice"]).dropna()
    filas = []
    for fin, periodo, tasa in funding[["periodo_fin_utc", "periodo_h", "tasa"]].itertuples(index=False):
        dentro = prima[(prima.index >= fin - pd.Timedelta(hours=periodo)) & (prima.index < fin)]
        if len(dentro) and pd.notna(tasa):
            filas.append((dentro.mean(), anualizar_funding(tasa, periodo)))
    if len(filas) < 3:
        return {"n_periodos": len(filas), "prima_media_bps": math.nan, "correlacion": math.nan, "pendiente": math.nan}
    p = np.array(filas)
    x = anualizar_basis(p[:, 0])
    sin_var = np.std(x) == 0 or np.std(p[:, 1]) == 0
    return {"n_periodos": len(filas), "prima_media_bps": float(p[:, 0].mean()),
            "correlacion": math.nan if sin_var else float(np.corrcoef(x, p[:, 1])[0, 1]),
            "pendiente": math.nan if np.std(x) == 0 else float(np.polyfit(x, p[:, 1], 1)[0])}


def oi_y_movimientos(oi_btc: pd.Series, grandes: pd.Series, ret_bps: pd.Series) -> dict:
    """Cambio horario del OI (%) en las horas de movimiento grande frente al resto; correlaciones con el retorno."""
    if oi_btc.empty:
        return {"n_horas_oi": 0, "cambio_oi_grandes_pct": math.nan, "cambio_oi_resto_pct": math.nan,
                "correlacion_oi_retorno": math.nan, "correlacion_oi_abs": math.nan}
    rejilla = pd.date_range(oi_btc.index.min(), oi_btc.index.max(), freq="h", tz="UTC")
    cambio = oi_btc.reindex(rejilla).pct_change(fill_method=None).mul(100).dropna()
    g = grandes.reindex(cambio.index).fillna(False).astype(bool)
    r = ret_bps.reindex(cambio.index)
    validas = r.notna()

    def corr(a, b):
        return float(a.corr(b)) if a.std() > 0 and b.std() > 0 and len(a) > 2 else math.nan

    return {"n_horas_oi": len(cambio), "cambio_oi_grandes_pct": float(cambio[g].mean()) if g.any() else math.nan,
            "cambio_oi_resto_pct": float(cambio[~g].mean()) if (~g).any() else math.nan,
            "correlacion_oi_retorno": corr(cambio[validas], r[validas]),
            "correlacion_oi_abs": corr(cambio[validas].abs(), r[validas].abs())}


def grupos_liquidacion(liq_btc: pd.Series, grandes: pd.Series, umbral_btc: float, vecindad_h: int = VECINDAD_H) -> dict:
    """Grupos de horas consecutivas con liquidaciones > umbral y su coincidencia con movimientos grandes (±vecindad)."""
    liq = liq_btc.dropna()
    g = grandes.reindex(liq.index.union(grandes.index)).fillna(False).astype(bool)
    cerca = g.astype(int).rolling(2 * vecindad_h + 1, center=True, min_periods=1).max().astype(bool)
    altas = liq[liq > umbral_btc]
    grupos, actual = [], []
    for t in altas.index:
        if actual and t - actual[-1] > pd.Timedelta(hours=1):
            grupos.append(actual)
            actual = []
        actual.append(t)
    if actual:
        grupos.append(actual)
    con = [any(cerca.get(t, False) for t in grupo) for grupo in grupos]
    total = float(liq.sum())
    base = float(cerca.reindex(liq.index).fillna(False).mean()) if len(liq) else math.nan
    fraccion = float(np.mean(con)) if grupos else math.nan
    return {"horas_liquidacion": len(liq), "umbral_btc": umbral_btc, "n_grupos": len(grupos),
            "fraccion_con_movimiento": fraccion, "fraccion_base": base,
            "ratio_coincidencia": fraccion / base if grupos and base > 0 else math.nan,
            "concentracion": float(altas.sum()) / total if total > 0 else math.nan, "liquidado_btc": total}


def ejemplo_margen(precio: float, q_btc: float = Q_BTC, apalancamiento: float = APALANCAMIENTO_EJEMPLO,
                   mantenimiento: float = MANTENIMIENTO) -> dict:
    """Short de q BTC a `precio` con garantía = nominal / apalancamiento: subida del mark que cruza el mantenimiento."""
    garantia = q_btc * precio / apalancamiento
    mark = (garantia + q_btc * precio) / (q_btc * (1 + mantenimiento))
    return {"precio": precio, "garantia_usd": garantia, "mark_liquidacion": mark,
            "subida_que_liquida": mark / precio - 1}


# --- Resultado ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultadoDerivados:
    exchange: str
    instrumento: str
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_horas: int
    minimo_horas: int
    basis_medio_bps: float
    basis_mediana_bps: float
    basis_p05_bps: float
    basis_p95_bps: float
    basis_anual: float
    mark_indice_medio_bps: float
    n_pagos: int
    periodo_funding_h: float
    funding_medio_bps: float
    funding_anual: float
    fraccion_funding_positivo: float
    funding_desde_utc: pd.Timestamp
    funding_hasta_utc: pd.Timestamp
    relacion_periodos: int
    relacion_prima_media_bps: float
    relacion_correlacion: float
    relacion_pendiente: float
    carry_q_btc: float
    carry_comision_spot: float
    carry_comision_perp: float
    carry_garantia: float
    carry_horas: int
    carry_pagos: int
    carry_funding_usd: float
    carry_basis_usd: float
    carry_comisiones_usd: float
    carry_neto_usd: float
    carry_neto_sin_comisiones_usd: float
    carry_capital_usd: float
    carry_rentabilidad: float
    carry_rentabilidad_anual: float
    carry_garantia_minima_usd: float
    carry_cruza_mantenimiento: bool
    umbral_movimiento_bps: float
    n_movimientos: int
    n_horas_oi: int
    cambio_oi_grandes_pct: float
    cambio_oi_resto_pct: float
    correlacion_oi_retorno: float
    correlacion_oi_abs: float
    horas_liquidacion: int
    umbral_liquidacion_btc: float
    n_grupos_liquidacion: int
    fraccion_grupos_con_movimiento: float
    fraccion_base_movimiento: float
    ratio_coincidencia: float
    concentracion_liquidaciones: float
    liquidado_btc: float
    fraccion_liquidado_largos: float
    margen_precio: float
    margen_apalancamiento: float
    margen_mantenimiento: float
    margen_subida_que_liquida: float

    @property
    def estado(self) -> str:
        return INSUFICIENTE if self.n_horas < self.minimo_horas else DESCRITO

    @property
    def estado_carry(self) -> str:
        if self.estado == INSUFICIENTE or self.carry_pagos < MIN_PAGOS or not math.isfinite(self.carry_neto_usd):
            return INSUFICIENTE
        return CARRY_POSITIVO if self.carry_neto_usd > 0 else CARRY_NEGATIVO

    @property
    def estado_liquidaciones(self) -> str:
        if self.horas_liquidacion < MIN_HORAS_LIQUIDACION or self.n_grupos_liquidacion < MIN_GRUPOS:
            return INSUFICIENTE
        agrupadas = math.isfinite(self.ratio_coincidencia) and self.ratio_coincidencia >= RATIO_AGRUPADAS
        return AGRUPADAS if agrupadas else SIN_AGRUPAMIENTO

    def _texto_carry(self) -> str:
        if self.estado_carry == INSUFICIENTE:
            return (f"Carry: datos insuficientes ({self.carry_pagos} pagos de funding observados; hacen falta "
                    f"{MIN_PAGOS}).")
        return (f"Carry largo índice / corto perpetuo de {self.carry_q_btc:g} BTC durante {self.carry_horas} h "
                f"({self.carry_pagos} pagos observados, ninguno previsto): funding {self.carry_funding_usd:+,.2f}, "
                f"basis {self.carry_basis_usd:+,.2f}, comisiones {-self.carry_comisiones_usd:+,.2f} (spot "
                f"{self.carry_comision_spot:.2%} y perpetuo {self.carry_comision_perp:.2%} por pierna, abrir y "
                f"cerrar): neto {self.carry_neto_usd:+,.2f} USD, {self.carry_rentabilidad:+.2%} sobre un capital de "
                f"{self.carry_capital_usd:,.0f} ({self.carry_rentabilidad_anual:+.1%} anual); sin comisiones "
                f"{self.carry_neto_sin_comisiones_usd:+,.2f}: {self.estado_carry}. Con garantía del "
                f"{self.carry_garantia:.0%} del nominal, la cuenta del short bajó como mínimo a "
                f"{self.carry_garantia_minima_usd:,.0f} USD y "
                f"{'CRUZÓ' if self.carry_cruza_mantenimiento else 'no cruzó'} el mantenimiento.")

    def _texto_liquidaciones(self) -> str:
        base = f"Liquidaciones ({self.horas_liquidacion} h, {self.liquidado_btc:,.1f} BTC"
        if math.isfinite(self.fraccion_liquidado_largos):
            base += f", {self.fraccion_liquidado_largos:.0%} de posiciones largas"
        base += ")"
        if self.estado_liquidaciones == INSUFICIENTE:
            return (f"{base}: datos insuficientes ({self.n_grupos_liquidacion} grupos; hacen falta {MIN_GRUPOS} "
                    f"en al menos {MIN_HORAS_LIQUIDACION} h).")
        return (f"{base}: {self.n_grupos_liquidacion} grupos por encima de {self.umbral_liquidacion_btc:,.2f} BTC/h "
                f"concentran el {self.concentracion_liquidaciones:.0%} del volumen; el "
                f"{self.fraccion_grupos_con_movimiento:.0%} tiene un movimiento de ≥ {self.umbral_movimiento_bps:.0f} "
                f"bps a ±{VECINDAD_H} h frente al {self.fraccion_base_movimiento:.0%} de cualquier hora "
                f"({self.ratio_coincidencia:.1f} veces): {self.estado_liquidaciones} (coincidencia, no causalidad).")

    def conclusion(self) -> str:
        cabecera = (f"{self.exchange} {self.instrumento}, {self.desde_utc:%Y-%m-%d %H:%M} → "
                    f"{self.hasta_utc:%Y-%m-%d %H:%M} UTC ({self.n_horas} h)")
        if self.estado == INSUFICIENTE:
            return f"{cabecera}: datos insuficientes (hacen falta {self.minimo_horas} h con mark, índice y perpetuo)."
        texto = (f"{cabecera}: basis perpetuo − índice medio {self.basis_medio_bps:+.2f} bps (mediana "
                 f"{self.basis_mediana_bps:+.2f}, del 5 % al 95 % [{self.basis_p05_bps:+.2f}, "
                 f"{self.basis_p95_bps:+.2f}]), {self.basis_anual:+.1%} anualizado (prima cobrada cada "
                 f"{HORAS_CONVERGENCIA} h); mark − índice medio {self.mark_indice_medio_bps:+.2f} bps.")
        if self.n_pagos:
            texto += (f" Funding: {self.n_pagos} pagos cada {self.periodo_funding_h:g} h "
                      f"({self.funding_desde_utc:%Y-%m-%d} → {self.funding_hasta_utc:%Y-%m-%d}), medio "
                      f"{self.funding_medio_bps:+.3f} bps por pago, {self.funding_anual:+.1%} anual; positivo en el "
                      f"{self.fraccion_funding_positivo:.0%}.")
        if self.relacion_periodos >= 3:
            texto += (f" Prima mark − índice frente al funding por periodo ({self.relacion_periodos} periodos, "
                      f"anualizados): correlación {self.relacion_correlacion:+.2f}, pendiente "
                      f"{self.relacion_pendiente:.2f} (1 = el funding cobra toda la prima).")
        texto += " " + self._texto_carry()
        if self.n_horas_oi:
            texto += (f" OI ({self.n_horas_oi} h): cambio medio {self.cambio_oi_grandes_pct:+.2f} % en las "
                      f"{self.n_movimientos} horas de movimiento grande (≥ {self.umbral_movimiento_bps:.0f} bps) "
                      f"frente a {self.cambio_oi_resto_pct:+.3f} % en el resto; correlación de |ΔOI| con |retorno| "
                      f"{self.correlacion_oi_abs:+.2f}.")
        if self.horas_liquidacion:
            texto += " " + self._texto_liquidaciones()
        texto += (f" Margen: un short {self.margen_apalancamiento:g}x de 1 BTC a {self.margen_precio:,.0f} cruza el "
                  f"mantenimiento del {self.margen_mantenimiento:.1%} con una subida del mark del "
                  f"{self.margen_subida_que_liquida:.2%}, gane lo que gane la pierna spot.")
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "derivados", **asdict(self), "estado": self.estado, "estado_carry": self.estado_carry,
                "estado_liquidaciones": self.estado_liquidaciones, "conclusion": self.conclusion()}


# --- Estudio -------------------------------------------------------------------------------------------------------

def horas_de_precios(precios: pd.DataFrame) -> pd.DataFrame:
    """Velas horarias cerradas (una fila por tipo) → rejilla horaria con `mark`, `indice`, `perp`, sin rellenar."""
    p = precios[(precios["intervalo_s"] == 3600) & precios["completa"].astype(bool)]
    if p.empty:
        return pd.DataFrame(columns=["mark", "indice", "perp"])
    tabla = p.pivot_table(index="inicio_utc", columns="tipo", values="cierre", aggfunc="last")
    tabla = tabla.reindex(columns=["mark", "indice", "perp"])
    rejilla = pd.date_range(tabla.index.min(), tabla.index.max(), freq="h", tz="UTC", name="inicio_utc")
    return tabla.reindex(rejilla)


def liquidaciones_horarias(liq: pd.DataFrame) -> tuple[pd.Series, float]:
    """(volumen liquidado por hora en BTC, fracción de largos). Órdenes sueltas (OKX): las horas sin órdenes dentro
    del tramo cubierto valen 0. Totales horarios (Kraken): como vienen."""
    if liq.empty:
        return pd.Series(dtype=float), math.nan
    sueltas = liq[liq["intervalo_s"] == 0]
    if len(sueltas):
        hora = sueltas["inicio_utc"].dt.floor("h")
        serie = sueltas.groupby(hora)["cantidad_btc"].sum()
        rejilla = pd.date_range(serie.index.min(), serie.index.max(), freq="h", tz="UTC")
        largos = sueltas.loc[sueltas["lado"] == "long", "cantidad_btc"].sum() / sueltas["cantidad_btc"].sum()
        return serie.reindex(rejilla, fill_value=0.0), float(largos)
    totales = liq[(liq["intervalo_s"] == 3600) & (liq["lado"] == "total")]
    return totales.set_index("inicio_utc")["cantidad_btc"].sort_index().astype(float), math.nan


def _pct(x: pd.Series, q: float) -> float:
    return float(x.quantile(q)) if len(x) else math.nan


def estudiar_exchange(exchange: str, instrumento: str, horas: pd.DataFrame, funding: pd.DataFrame,
                      oi_btc: pd.Series, liq: pd.DataFrame, minimo_horas: int = MIN_HORAS,
                      comision_spot: float | None = None, comision_perp: float | None = None,
                      q_btc: float = Q_BTC, garantia: float = GARANTIA) -> ResultadoDerivados:
    completas = horas.dropna(subset=["mark", "indice", "perp"])
    n = len(completas)
    desde = completas.index.min() if n else (horas.index.min() if len(horas) else pd.NaT)
    hasta = completas.index.max() + pd.Timedelta(hours=1) if n else pd.NaT
    basis = basis_bps(completas["perp"], completas["indice"])
    prima = basis_bps(completas["mark"], completas["indice"])
    f = funding.sort_values("periodo_fin_utc")
    periodo = float(f["periodo_h"].median()) if len(f) else math.nan
    tasa_anual = anualizar_funding(f["tasa"], f["periodo_h"]) if len(f) else pd.Series(dtype=float)
    # Carry en el tramo que cubren a la vez el funding y los precios.
    tramo = completas
    if len(f):
        inicio_f = f["periodo_fin_utc"].min() - pd.Timedelta(hours=float(f["periodo_h"].iloc[0]))
        tramo = completas[(completas.index >= inicio_f) & (completas.index < f["periodo_fin_utc"].max())]
    cs = COMISIONES_SPOT.get(exchange, 0.0) if comision_spot is None else comision_spot
    cp = COMISIONES_PERP.get(exchange, 0.0) if comision_perp is None else comision_perp
    c = carry_cobertura(tramo, f, q_btc, cs, cp, garantia)
    rel = relacion_basis_funding(completas, f)
    # Movimientos grandes: |retorno horario| del perpetuo (del mark si falta) en horas consecutivas.
    precio = horas["perp"].fillna(horas["mark"])
    ret = precio.pct_change(fill_method=None).mul(1e4)
    umbral_mov = _pct(ret.abs().dropna(), CUANTIL_MOVIMIENTO)
    grandes = ret.abs() >= umbral_mov
    o = oi_y_movimientos(oi_btc, grandes, ret)
    liq_h, largos = liquidaciones_horarias(liq)
    umbral_liq = max(_pct(liq_h.dropna(), CUANTIL_LIQUIDACION), 0.0) if len(liq_h) else math.nan
    gl = grupos_liquidacion(liq_h, grandes, umbral_liq) if len(liq_h) else {
        "horas_liquidacion": 0, "n_grupos": 0, "fraccion_con_movimiento": math.nan, "fraccion_base": math.nan,
        "ratio_coincidencia": math.nan, "concentracion": math.nan, "liquidado_btc": 0.0}
    ultimo = float(completas["indice"].iloc[-1]) if n else math.nan
    m = ejemplo_margen(ultimo) if n else {"subida_que_liquida": math.nan}
    return ResultadoDerivados(
        exchange=exchange, instrumento=instrumento, desde_utc=desde, hasta_utc=hasta, n_horas=n,
        minimo_horas=minimo_horas, basis_medio_bps=float(basis.mean()) if n else math.nan,
        basis_mediana_bps=float(basis.median()) if n else math.nan, basis_p05_bps=_pct(basis, 0.05),
        basis_p95_bps=_pct(basis, 0.95), basis_anual=float(anualizar_basis(basis.mean())) if n else math.nan,
        mark_indice_medio_bps=float(prima.mean()) if n else math.nan, n_pagos=len(f), periodo_funding_h=periodo,
        funding_medio_bps=float(f["tasa"].mean() * 1e4) if len(f) else math.nan,
        funding_anual=float(tasa_anual.mean()) if len(f) else math.nan,
        fraccion_funding_positivo=float((f["tasa"] > 0).mean()) if len(f) else math.nan,
        funding_desde_utc=f["periodo_fin_utc"].min() if len(f) else pd.NaT,
        funding_hasta_utc=f["periodo_fin_utc"].max() if len(f) else pd.NaT,
        relacion_periodos=rel["n_periodos"], relacion_prima_media_bps=rel["prima_media_bps"],
        relacion_correlacion=rel["correlacion"], relacion_pendiente=rel["pendiente"],
        carry_q_btc=q_btc, carry_comision_spot=cs, carry_comision_perp=cp, carry_garantia=garantia,
        carry_horas=c["horas"], carry_pagos=c["n_pagos"], carry_funding_usd=c["funding_usd"],
        carry_basis_usd=c["pnl_basis_usd"], carry_comisiones_usd=c["comisiones_usd"], carry_neto_usd=c["neto_usd"],
        carry_neto_sin_comisiones_usd=c["neto_sin_comisiones_usd"], carry_capital_usd=c["capital_usd"],
        carry_rentabilidad=c["rentabilidad"], carry_rentabilidad_anual=c["rentabilidad_anual"],
        carry_garantia_minima_usd=c["garantia_minima_usd"], carry_cruza_mantenimiento=c["cruza_mantenimiento"],
        umbral_movimiento_bps=umbral_mov, n_movimientos=int(grandes.sum()), n_horas_oi=o["n_horas_oi"],
        cambio_oi_grandes_pct=o["cambio_oi_grandes_pct"], cambio_oi_resto_pct=o["cambio_oi_resto_pct"],
        correlacion_oi_retorno=o["correlacion_oi_retorno"], correlacion_oi_abs=o["correlacion_oi_abs"],
        horas_liquidacion=gl["horas_liquidacion"], umbral_liquidacion_btc=umbral_liq,
        n_grupos_liquidacion=gl["n_grupos"], fraccion_grupos_con_movimiento=gl["fraccion_con_movimiento"],
        fraccion_base_movimiento=gl["fraccion_base"], ratio_coincidencia=gl["ratio_coincidencia"],
        concentracion_liquidaciones=gl["concentracion"], liquidado_btc=gl["liquidado_btc"],
        fraccion_liquidado_largos=largos, margen_precio=ultimo, margen_apalancamiento=APALANCAMIENTO_EJEMPLO,
        margen_mantenimiento=MANTENIMIENTO, margen_subida_que_liquida=m["subida_que_liquida"])


def estudiar_derivados_lake(consultar: Callable[[str], pd.DataFrame], **opciones) -> list[ResultadoDerivados]:
    """Un resultado por exchange con velas de derivados guardadas (última versión de cada fila)."""
    precios = hd.leer_ultimas(consultar, hd.FUENTE_PRECIOS)
    if precios.empty:
        return []
    funding = hd.leer_ultimas(consultar, hd.FUENTE_FUNDING)
    oi = hd.leer_ultimas(consultar, hd.FUENTE_OI)
    liq = hd.leer_ultimas(consultar, hd.FUENTE_LIQUIDACIONES)
    resultados = []
    for (exchange, instrumento), p in precios.groupby(["exchange", "instrumento"], sort=True):
        f = funding[(funding["exchange"] == exchange) & (funding["instrumento"] == instrumento)]
        o = oi[(oi["exchange"] == exchange) & (oi["instrumento"] == instrumento)]
        serie_oi = o.set_index("inicio_utc")["oi_btc"].sort_index().astype(float) if len(o) else pd.Series(dtype=float)
        lq = liq[(liq["exchange"] == exchange) & (liq["instrumento"] == instrumento)]
        resultados.append(estudiar_exchange(exchange, instrumento, horas_de_precios(p), f.reset_index(drop=True),
                                            serie_oi, lq.reset_index(drop=True), **opciones))
    return resultados


def guardar_estudio_derivados(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_ESTUDIO)
