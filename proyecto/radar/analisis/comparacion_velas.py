"""Velas propias frente a las oficiales de Kraken en los mismos intervalos y días (Fase 4, S4).

Conceptos:
- Qué se compara: por intervalo Δ, las velas propias de Kraken (`fuente` = "propia", construidas con los trades del
  websocket, `velas.py`) y las de Kraken (`fuente` = "kraken_historico", REST OHLC o ZIP OHLCVT,
  `captura/historico_kraken.py`) con el mismo `inicio_utc`. Solo entran velas propias COMPLETAS (la captura cubrió
  su intervalo) y velas de Kraken completas (no la barra abierta). Fuentes oficiales: REST OHLC
  https://docs.kraken.com/api/docs/rest-api/get-ohlc-data y OHLCVT descargable
  https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data.
- Por qué deberían coincidir: nuestros trades SON los trades públicos de Kraken tal como nos llegan, y las dos
  fuentes ponen cada trade en su vela por la hora del EXCHANGE. El desfase de nuestro reloj (`relojes.py`) no
  cambia la vela de un trade; solo decide qué velas cuenta la captura como cubiertas (los latidos van en nuestro
  reloj; `velas.py` recorta un margen por eso). Sin pérdidas, apertura, máximo, mínimo, cierre, volumen y número
  de trades deberían ser IGUALES (precios con tick de 0,1 €).
- Diferencias de precio: |propia / kraken − 1| · 10.000 en bps, mediana y máximo sobre las velas comunes no vacías
  en las dos fuentes. Diferencia de volumen: (Σ propio − Σ kraken) / Σ kraken en %, y la mediana por vela del
  |error| en %. Cobertura: velas comunes / velas de Kraken (no vacías) entre la primera y la última vela propia
  (completa o no): baja si la captura tuvo huecos o velas incompletas.
  Discrepancias de vacía: velas que una fuente da vacías y la otra no.
- Compensación en frontera: c = 1 − |Σ d| / Σ |d| con d = volumen propio − de Kraken por vela. c ≈ 1 significa que
  lo que sobra en una vela falta en la vecina (trades asignados a la vela de al lado: una hora distinta en el
  borde); c ≈ 0, que las diferencias van en un solo sentido (trades perdidos o duplicados). NaN si ninguna vela
  difiere en volumen (más de `TOLERANCIA_BTC`).
- El VWAP de la REST de Kraken viene redondeado a 0,1 € (el tick): una diferencia de VWAP de centésimas de bps es
  ese redondeo, no un trade distinto.
- Correlación de retornos: Pearson de los retornos logarítmicos cierre a cierre de velas comunes consecutivas
  (las dos velas, la del retorno y la anterior, comunes y no vacías). Con datos iguales vale 1.

Estados (por exchange e intervalo):
- datos insuficientes: menos de `MIN_VELAS` velas comunes no vacías.
- coinciden: mediana del error de cierre ≤ `UMBRAL_PRECIO_BPS`, |error de volumen| total y mediano por vela ≤
  `UMBRAL_VOLUMEN_PCT` y correlación de retornos ≥ `MIN_CORRELACION`.
- faltan trades propios: el volumen propio total queda por DEBAJO del de Kraken más de `UMBRAL_VOLUMEN_PCT`
  (la captura perdió trades: reconexiones, mensajes descartados).
- sobran trades propios: el volumen propio total supera al de Kraken más de `UMBRAL_VOLUMEN_PCT` (trades
  duplicados no filtrados, u otro mercado).
- difieren en la frontera: el volumen total cuadra pero no vela a vela o los precios difieren, con compensación
  ≥ `MIN_COMPENSACION` (trades asignados a la vela vecina).
- difieren: cualquier otro caso.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .velas import FUENTE_PROPIA, leer_velas

METODO = "comparacion_velas/v1"
FUENTE_COMPARACION = "estudios_comparacion_velas"
FUENTE_KRAKEN = "kraken_historico"
EXCHANGE = "kraken"
MIN_VELAS = 30
# El tick de BTC/EUR en Kraken es 0,1 € ≈ 0,02 bps a 55 000 €: 0,5 bps es ~25 ticks, muy por encima del redondeo
# y muy por debajo de un movimiento de un minuto (~5-10 bps).
UMBRAL_PRECIO_BPS = 0.5
UMBRAL_VOLUMEN_PCT = 1.0     # un 1 % del volumen: unos pocos trades de una hora
MIN_CORRELACION = 0.99
MIN_COMPENSACION = 0.5
TOLERANCIA_BTC = 1e-9         # el volumen de Kraken va en 8 decimales (satoshis)
PRECIOS = ("apertura", "maximo", "minimo", "cierre")

INSUFICIENTE, COINCIDEN, FALTAN, SOBRAN = ("datos insuficientes", "coinciden", "faltan trades propios",
                                          "sobran trades propios")
FRONTERA, DIFIEREN = "difieren en la frontera", "difieren"


@dataclass(frozen=True)
class ComparacionVelas:
    exchange: str
    intervalo_s: int
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_propias: int                 # propias completas
    n_kraken: int                  # de Kraken completas y no vacías en el tramo de las propias
    n_comunes: int                 # comunes y no vacías en las dos
    cobertura: float               # n_comunes / n_kraken
    vacias_discrepantes: int
    dif_apertura_bps: float        # medianas de |propia / kraken − 1| · 10.000
    dif_maximo_bps: float
    dif_minimo_bps: float
    dif_cierre_bps: float
    max_dif_cierre_bps: float
    dif_vwap_bps: float            # NaN si Kraken no da VWAP (ZIP)
    fraccion_identicas: float      # velas con los cuatro precios iguales (mismo tick)
    dif_volumen_pct: float         # (Σ propio − Σ kraken) / Σ kraken · 100
    dif_volumen_mediana_pct: float
    dif_trades_pct: float
    compensacion_frontera: float
    corr_retornos: float
    n_retornos: int
    minimo: int

    @property
    def estado(self) -> str:
        if self.n_comunes < self.minimo:
            return INSUFICIENTE
        volumen_ok = abs(self.dif_volumen_pct) <= UMBRAL_VOLUMEN_PCT
        if (volumen_ok and self.dif_volumen_mediana_pct <= UMBRAL_VOLUMEN_PCT and self.dif_cierre_bps <= UMBRAL_PRECIO_BPS
                and self.corr_retornos >= MIN_CORRELACION):
            return COINCIDEN
        if self.dif_volumen_pct < -UMBRAL_VOLUMEN_PCT:
            return FALTAN
        if self.dif_volumen_pct > UMBRAL_VOLUMEN_PCT:
            return SOBRAN
        if self.compensacion_frontera >= MIN_COMPENSACION:
            return FRONTERA
        return DIFIEREN

    def conclusion(self) -> str:
        cabecera = f"{self.exchange}, velas de {self.intervalo_s:g} s, propias frente a Kraken"
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.n_comunes} velas comunes no vacías; hacen falta "
                    f"{self.minimo}).")
        causa = {
            COINCIDEN: "nuestros trades reproducen las velas oficiales: la captura no pierde trades en las velas "
                       "completas y la hora del exchange las alinea.",
            FALTAN: "nos faltan trades (reconexiones o mensajes perdidos que la cobertura no detectó).",
            SOBRAN: "nos sobran trades (repetidos al reconectar sin filtrar u otro mercado).",
            FRONTERA: "el total cuadra y las diferencias se compensan entre velas vecinas: algunos trades caen en la "
                      "vela de al lado (hora distinta en el borde).",
            DIFIEREN: "las diferencias no se explican por pérdida de trades ni por la frontera; revisar los datos.",
        }[self.estado]
        vwap = "" if math.isnan(self.dif_vwap_bps) else f", VWAP {self.dif_vwap_bps:.3f}"
        frontera = ("ninguna vela difiere en volumen" if math.isnan(self.compensacion_frontera)
                    else f"compensación en frontera {self.compensacion_frontera:.2f}")
        return (f"{cabecera}: {self.estado}. {self.n_comunes} velas comunes ({self.cobertura:.1%} de las de Kraken "
                f"en el tramo capturado; {self.vacias_discrepantes} con vacía discrepante). Error mediano en bps: "
                f"apertura {self.dif_apertura_bps:.3f}, máximo {self.dif_maximo_bps:.3f}, mínimo "
                f"{self.dif_minimo_bps:.3f}, cierre {self.dif_cierre_bps:.3f} (máximo {self.max_dif_cierre_bps:.2f})"
                f"{vwap}; {self.fraccion_identicas:.1%} de velas con los cuatro precios idénticos. Volumen "
                f"{self.dif_volumen_pct:+.2f} % en total (mediana por vela {self.dif_volumen_mediana_pct:.2f} %), "
                f"trades {self.dif_trades_pct:+.2f} %, {frontera}; "
                f"correlación de retornos {self.corr_retornos:.4f} ({self.n_retornos} retornos). {causa}")

    def a_fila(self) -> dict:
        return {"estudio": "comparacion_velas", **asdict(self), "estado": self.estado,
                "conclusion": self.conclusion()}


def _bps(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a / b - 1).abs() * 1e4


def _mediana(serie: pd.Series) -> float:
    serie = serie.dropna()
    return float(serie.median()) if len(serie) else math.nan


def _pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else math.nan


def comparar(propias: pd.DataFrame, kraken: pd.DataFrame, minimo: int = MIN_VELAS) -> list[ComparacionVelas]:
    """Compara por (exchange, intervalo_s) dos tablas de velas en el formato común (una fila por vela)."""
    salida = []
    for (exchange, intervalo_s), todas in propias.groupby(["exchange", "intervalo_s"]):
        p = todas[todas["completa"].astype(bool)]
        k = kraken[(kraken["exchange"] == exchange) & (kraken["intervalo_s"] == intervalo_s)
                   & kraken["completa"].astype(bool)]
        desde, hasta = todas["inicio_utc"].min(), todas["inicio_utc"].max()   # tramo capturado, con huecos
        k = k[(k["inicio_utc"] >= desde) & (k["inicio_utc"] <= hasta)]
        u = p.merge(k, on="inicio_utc", suffixes=("_p", "_k")).sort_values("inicio_utc").reset_index(drop=True)
        llenas = u[~u["vacia_p"].astype(bool) & ~u["vacia_k"].astype(bool)]
        n_kraken = int((~k["vacia"].astype(bool)).sum())
        dif = {c: _bps(llenas[f"{c}_p"], llenas[f"{c}_k"]) for c in PRECIOS}
        d = u["volumen_btc_p"] - u["volumen_btc_k"]
        d = d.where(d.abs() > TOLERANCIA_BTC, 0.0)          # restas de coma flotante, no trades
        paso = pd.Timedelta(seconds=float(intervalo_s))
        llena = ~u["vacia_p"].astype(bool) & ~u["vacia_k"].astype(bool)
        consecutivas = u["inicio_utc"].diff().eq(paso) & llena & llena.shift(fill_value=False)
        rp = np.log(u["cierre_p"] / u["cierre_p"].shift())[consecutivas]
        rk = np.log(u["cierre_k"] / u["cierre_k"].shift())[consecutivas]
        corr = float(np.corrcoef(rp, rk)[0, 1]) if len(rp) > 2 and rp.std() > 0 and rk.std() > 0 else math.nan
        abs_d = float(d.abs().sum())
        salida.append(ComparacionVelas(
            exchange=exchange, intervalo_s=int(intervalo_s), desde_utc=desde, hasta_utc=hasta + paso,
            n_propias=len(p), n_kraken=n_kraken, n_comunes=len(llenas),
            cobertura=len(llenas) / n_kraken if n_kraken else math.nan,
            vacias_discrepantes=int((u["vacia_p"].astype(bool) != u["vacia_k"].astype(bool)).sum()),
            dif_apertura_bps=_mediana(dif["apertura"]), dif_maximo_bps=_mediana(dif["maximo"]),
            dif_minimo_bps=_mediana(dif["minimo"]), dif_cierre_bps=_mediana(dif["cierre"]),
            max_dif_cierre_bps=float(dif["cierre"].max()) if len(llenas) else math.nan,
            dif_vwap_bps=_mediana(_bps(llenas["vwap_p"], llenas["vwap_k"])),
            fraccion_identicas=float(np.mean(np.all([dif[c].to_numpy() < 1e-9 for c in PRECIOS], axis=0)))
            if len(llenas) else math.nan,
            dif_volumen_pct=_pct(float(u["volumen_btc_p"].sum()), float(u["volumen_btc_k"].sum())),
            dif_volumen_mediana_pct=_mediana((d / u["volumen_btc_k"]).abs()[u["volumen_btc_k"] > 0] * 100),
            dif_trades_pct=_pct(float(u["n_trades_p"].sum()), float(u["n_trades_k"].sum())),
            compensacion_frontera=1 - abs(float(d.sum())) / abs_d if abs_d > 0 else math.nan,
            corr_retornos=corr, n_retornos=len(rp), minimo=minimo))
    return salida


def comparar_velas(consultar: Callable[[str], pd.DataFrame], intervalos_s=None, desde_utc=None,
                   minimo: int = MIN_VELAS) -> list[ComparacionVelas]:
    """Lee del lake las velas propias de Kraken y las de `kraken_historico` y las compara por intervalo."""
    propias = leer_velas(consultar, FUENTE_PROPIA, EXCHANGE, desde=desde_utc)
    kraken = leer_velas(consultar, FUENTE_KRAKEN, EXCHANGE, desde=desde_utc)
    if intervalos_s is not None:
        propias = propias[propias["intervalo_s"].isin(intervalos_s)]
    if propias.empty or kraken.empty:
        return []
    for df in (propias, kraken):
        df["inicio_utc"] = pd.to_datetime(df["inicio_utc"], utc=True)
    return comparar(propias, kraken, minimo)


def guardar_comparacion_velas(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_COMPARACION)
