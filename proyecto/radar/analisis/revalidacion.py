"""Revalidación de los hallazgos del OFI, el lead-lag y las señales con datos que su estudio todavía no había visto.

Conceptos:
- Hallazgo: un resultado confirmado en la última ejecución guardada de su estudio. Cuenta como confirmado:
  OFI predictivo "confirmada", impacto contemporáneo "explica el precio", lead-lag "confirmada", aporte de una
  señal "aporta información propia" e interacción "confirmada".
- Fuera de muestra de verdad: solo se usan datos recibidos DESPUÉS del final (`hasta_utc`) de los datos de ese
  estudio. Sin `hasta_utc` guardado (estudios de antes de registrarlo) no hay corte fiable: queda pendiente.
- Misma prueba que el estudio, sin reimplementar la estadística: OFI predictivo con `hallazgos.revalidar`
  (diferencia de medias, HAC), impacto con `impacto_contemporaneo`, lead-lag con la regresión de Granger del
  estudio y señales con sus regresiones HAC estandarizadas. Sobre los datos nuevos se estima una sola vez (no
  hay mitades: ya no se descubre nada, solo se comprueba).
- Interacciones: el umbral de "contexto alto" es el del estudio (la mediana de su mitad de descubrimiento); no
  se vuelve a fijar con los datos nuevos.
- Estados y reglas de `hallazgos.clasificar`: se mantiene, se debilita, se cae o pendiente (menos de `minimo`
  observaciones nuevas, el mismo mínimo que usó el estudio).
- Efecto: el coeficiente de cada prueba, en sus unidades: bps (diferencia de medias), bps por BTC (impacto),
  bps por bps (lead-lag) y bps por desviación típica (señales). Se compara con el de descubrimiento.
- Se guardan en la fuente `revalidaciones`, junto a las del imbalance, con la columna `estudio` (nula en las del
  imbalance, que conservan sus columnas) y nombres propios para lo que no es una diferencia de medias.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import pandas as pd

from radar.configuracion import INTERVALO_S

from .hallazgos import FUENTE_REVALIDACIONES, PENDIENTE, clasificar, revalidar
from .imbalance import CONFIRMADA, CONTROLES
from .leadlag import FUENTE_LEAD_LAG, _granger, mids_alineados, retornos
from .ofi import FUENTE_ESTUDIOS_OFI, impacto_contemporaneo, pares_ofi_retorno
from .senales import FUENTE_SENALES, SENALES, _ols, _z, tabla_senales

CONFIRMADOS = {"ofi_retorno": CONFIRMADA, "ofi_impacto": "explica el precio", "lead_lag": "confirmada",
               "aporte": "aporta información propia", "interaccion": "confirmada"}
SIN_CORTE = "el estudio guardado no registra el final de sus datos (hasta_utc); vuelve a ejecutarlo para revalidarlo"
NOMBRES_CONTEXTO = {"spread_bps": "el spread", "volatilidad_bps": "la volatilidad"}


@dataclass(frozen=True)
class RevalidacionEstudio:
    estudio: str
    hallazgo: str             # qué se revalida, legible y estable: identifica el hallazgo en el historial
    hasta_utc: pd.Timestamp   # final de los datos del estudio
    desde_utc: pd.Timestamp   # primer dato nuevo usado
    n: int                    # observaciones nuevas (en el grupo menor, para la diferencia de medias)
    minimo: int
    efecto_anterior: float
    efecto: float
    t: float
    unidad: str
    motivo: str = ""          # por qué no se puede revalidar (queda pendiente)

    @property
    def estado(self) -> str:
        suficiente = not self.motivo and self.n >= self.minimo and math.isfinite(self.efecto)
        return clasificar(suficiente, self.efecto_anterior, self.efecto, self.t)

    def conclusion(self) -> str:
        cabecera = f"{self.estudio}, {self.hallazgo}"
        if self.motivo:
            return f"{cabecera}: pendiente ({self.motivo})."
        if self.estado == PENDIENTE:
            return (f"{cabecera}: pendiente (con datos posteriores al estudio hay {self.n} observaciones; hacen falta "
                    f"{self.minimo}).")
        return (f"{cabecera}: {self.estado} con datos posteriores al estudio (desde {self.desde_utc:%Y-%m-%d %H:%M:%S} "
                f"UTC): efecto {self.efecto_anterior:+.3f} {self.unidad} al descubrirlo y {self.efecto:+.3f} ahora "
                f"(t HAC {self.t:.2f}).")

    def a_fila(self) -> dict:
        return {**asdict(self), "estado": self.estado, "conclusion": self.conclusion()}


def ultimo_estudio(consultar: Callable[[str], pd.DataFrame], fuente: str) -> pd.DataFrame:
    """Las filas de la última ejecución guardada en `fuente`."""
    return consultar(f"SELECT * FROM {fuente} WHERE ejecutado_utc = (SELECT max(ejecutado_utc) FROM {fuente})")


def _confirmados(anteriores: pd.DataFrame, estudio: str) -> list[dict]:
    if anteriores.empty:
        return []
    filas = anteriores if estudio == "lead_lag" else anteriores[anteriores["estudio"] == estudio]
    return filas[filas["estado"] == CONFIRMADOS[estudio]].to_dict("records")


def _hasta(fila: dict):
    hasta = fila.get("hasta_utc")
    return None if hasta is None or pd.isna(hasta) else pd.Timestamp(hasta)


def _sin_corte(estudio, hallazgo, minimo, anterior, unidad) -> RevalidacionEstudio:
    return RevalidacionEstudio(estudio, hallazgo, pd.NaT, pd.NaT, 0, int(minimo), float(anterior), math.nan,
                               math.nan, unidad, SIN_CORTE)


def revalidar_ofi(pares: pd.DataFrame, anteriores: pd.DataFrame) -> list[RevalidacionEstudio]:
    """OFI predictivo e impacto contemporáneo. `pares`: los de `pares_ofi_retorno` (niveles en `banda_bps`);
    `anteriores`: filas de la última ejecución de `estudios_ofi`."""
    salida = []
    for f in _confirmados(anteriores, "ofi_retorno"):
        nombre = f"{f['exchange']}, OFI {f['niveles']:g} niveles, horizonte {int(f['horizonte_rondas'])}"
        hasta = _hasta(f)
        if hasta is None:
            salida.append(_sin_corte("ofi_retorno", nombre, f["min_por_grupo"], f["diferencia_descubrimiento"], "bps"))
            continue
        hallazgo = pd.DataFrame([{**f, "banda_bps": f["niveles"], "horizonte_rondas": int(f["horizonte_rondas"]),
                                  "hasta_utc": hasta}])
        (r,) = revalidar(pares, hallazgo, int(f["min_por_grupo"]))
        salida.append(RevalidacionEstudio("ofi_retorno", nombre, hasta, r.desde_utc, min(r.n_positivo, r.n_negativo),
                                          r.min_por_grupo, r.diferencia_anterior, r.diferencia, r.t, "bps"))
    for f in _confirmados(anteriores, "ofi_impacto"):
        nombre = f"{f['exchange']}, OFI {f['niveles']:g} niveles, impacto contemporáneo"
        hasta = _hasta(f)
        if hasta is None:
            salida.append(_sin_corte("ofi_impacto", nombre, f["minimo"], f["beta_bps_por_btc"], "bps por BTC"))
            continue
        g = pares[(pares.exchange == f["exchange"]) & (pares.banda_bps == f["niveles"]) & (pares.recibido_utc > hasta)]
        (i,) = impacto_contemporaneo(g, int(f["minimo"])) or [None]
        salida.append(RevalidacionEstudio(
            "ofi_impacto", nombre, hasta, g.recibido_utc.min() if len(g) else pd.NaT, i.n if i else 0,
            int(f["minimo"]), float(f["beta_bps_por_btc"]), i.beta_bps_por_btc if i else math.nan,
            i.t_hac if i else math.nan, "bps por BTC"))
    return salida


def revalidar_lead_lag(alineados: pd.DataFrame, anteriores: pd.DataFrame,
                       intervalo_s: float = INTERVALO_S) -> list[RevalidacionEstudio]:
    """Granger r_seguidor(t + ℓ) = c0 + b · r_lider(t) + c1 · r_seguidor(t) con las rondas posteriores al estudio."""
    salida = []
    for f in _confirmados(anteriores, "lead_lag"):
        a, b, retardo = f["lider"], f["seguidor"], int(f["retardo_rondas"])
        nombre = f"{a} anticipa a {b} a {retardo} ronda(s)"
        hasta = _hasta(f)
        if hasta is None:
            salida.append(_sin_corte("lead_lag", nombre, f["minimo"], f["coef_descubrimiento"], "bps por bps"))
            continue
        nuevos = (alineados[alineados["solicitado_utc"] > hasta].reset_index(drop=True)
                  if not alineados.empty else alineados)
        if nuevos.empty or not {f"mid_{a}", f"mid_{b}"} <= set(nuevos.columns):
            coef, t, n = math.nan, math.nan, 0
        else:
            coef, t, n = _granger(retornos(nuevos, intervalo_s), a, b, retardo)
        salida.append(RevalidacionEstudio("lead_lag", nombre, hasta,
                                          nuevos["solicitado_utc"].iloc[0] if n else pd.NaT, n, int(f["minimo"]),
                                          float(f["coef_descubrimiento"]), coef, t, "bps por bps"))
    return salida


def _aporte(g: pd.DataFrame, senal: str, horizonte: int) -> tuple[float, float]:
    """Coeficiente y t de la señal en la regresión conjunta (todas las señales y los controles), estandarizada."""
    columnas = list(SENALES) + list(CONTROLES)
    z = _z(g, SENALES, g)
    if z[list(SENALES)].isna().any().any():
        return math.nan, math.nan
    modelo = _ols(z[f"ret_{horizonte}"], z[columnas], horizonte)
    return float(modelo.params[senal]), float(modelo.tvalues[senal])


def _interaccion(g: pd.DataFrame, senal: str, contexto: str, umbral: float, horizonte: int) -> tuple[float, float]:
    """Coeficiente y t de señal × [contexto > umbral del estudio], con la misma especificación que el estudio."""
    alto = (g[contexto] > umbral).astype(float)
    z = _z(g, [senal], g)
    if alto.nunique() < 2 or z[senal].isna().any():
        return math.nan, math.nan
    x = pd.DataFrame({"s": z[senal], "s_alto": z[senal] * alto, "alto": alto})
    modelo = _ols(g[f"ret_{horizonte}"], x, horizonte)
    return float(modelo.params["s_alto"]), float(modelo.tvalues["s_alto"])


def revalidar_senales(tabla: pd.DataFrame, anteriores: pd.DataFrame) -> list[RevalidacionEstudio]:
    """Aporte propio e interacciones con las filas de `tabla` (la de `tabla_senales`) posteriores al estudio."""
    salida = []
    for estudio in ("aporte", "interaccion"):
        for f in _confirmados(anteriores, estudio):
            h, s, ex = int(f["horizonte_rondas"]), f["senal"], f["exchange"]
            if estudio == "aporte":
                nombre, anterior = f"{ex}, {s} aporta información propia, horizonte {h}", f["coef_conjunto"]
                columnas = list(SENALES) + list(CONTROLES) + [f"ret_{h}"]
            else:
                nombre = (f"{ex}, {s} × {NOMBRES_CONTEXTO.get(f['contexto'], f['contexto'])} alto "
                          f"(> {f['umbral']:.3f} bps), horizonte {h}")
                anterior, columnas = f["coef_interaccion"], [s, f["contexto"], f"ret_{h}"]
            hasta = _hasta(f)
            if hasta is None:
                salida.append(_sin_corte(estudio, nombre, f["minimo"], anterior, "bps por desviación"))
                continue
            g = pd.DataFrame()
            if not tabla.empty and set(columnas) <= set(tabla.columns):
                g = (tabla[(tabla.exchange == ex) & (tabla.recibido_utc > hasta)].dropna(subset=columnas)
                     .sort_values("recibido_utc").reset_index(drop=True))
            if len(g) < int(f["minimo"]):
                coef, t = math.nan, math.nan
            elif estudio == "aporte":
                coef, t = _aporte(g, s, h)
            else:
                coef, t = _interaccion(g, s, f["contexto"], float(f["umbral"]), h)
            salida.append(RevalidacionEstudio(estudio, nombre, hasta, g.recibido_utc.iloc[0] if len(g) else pd.NaT,
                                              len(g), int(f["minimo"]), float(anterior), coef, t, "bps por desviación"))
    return salida


def revalidar_todo(consultar: Callable[[str], pd.DataFrame], fuentes, intervalo_s: float = INTERVALO_S
                   ) -> list[RevalidacionEstudio]:
    """Revalida los hallazgos de la última ejecución guardada de `estudios_ofi`, `estudios_lead_lag` y
    `estudios_senales`. `fuentes`: las del lake (`LakeParquet.fuentes()`); sin los datos que necesita una prueba,
    sus hallazgos quedan pendientes."""
    fuentes, salida = set(fuentes), []
    if FUENTE_ESTUDIOS_OFI in fuentes:
        anteriores = ultimo_estudio(consultar, FUENTE_ESTUDIOS_OFI)
        retorno, impacto = _confirmados(anteriores, "ofi_retorno"), _confirmados(anteriores, "ofi_impacto")
        if retorno or impacto:
            niveles = sorted({int(f["niveles"]) for f in retorno + impacto})
            horizontes = sorted({int(f["horizonte_rondas"]) for f in retorno} | {1})
            pares = (pares_ofi_retorno(consultar, horizontes, niveles, intervalo_s) if "libros" in fuentes
                     else pd.DataFrame(columns=["exchange", "banda_bps", "horizonte_rondas", "recibido_utc",
                                                "imbalance", "ret_bps", "ret_actual_bps"]))
            salida += revalidar_ofi(pares, anteriores)
    if FUENTE_LEAD_LAG in fuentes:
        anteriores = ultimo_estudio(consultar, FUENTE_LEAD_LAG)
        if _confirmados(anteriores, "lead_lag"):
            alineados = mids_alineados(consultar, intervalo_s) if "cotizaciones" in fuentes else pd.DataFrame()
            salida += revalidar_lead_lag(alineados, anteriores, intervalo_s)
    if FUENTE_SENALES in fuentes:
        anteriores = ultimo_estudio(consultar, FUENTE_SENALES)
        hallazgos = _confirmados(anteriores, "aporte") + _confirmados(anteriores, "interaccion")
        if hallazgos:
            datos = {"cotizaciones", "desequilibrios", "libros"} <= fuentes
            horizontes = sorted({int(f["horizonte_rondas"]) for f in hallazgos})
            tabla = tabla_senales(consultar, horizontes=horizontes, intervalo_s=intervalo_s) if datos else pd.DataFrame()
            salida += revalidar_senales(tabla, anteriores)
    return salida


def guardar_revalidaciones_estudios(revalidaciones, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda en `revalidaciones`, junto a las del imbalance, una fila por hallazgo con su `estudio`."""
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in revalidaciones], FUENTE_REVALIDACIONES)


def guardar_estudio_senales(resultados, tabla: pd.DataFrame, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda los resultados de `senales` en `estudios_senales` con `hasta_utc`: la última fila de `tabla` de su
    exchange, para que la revalidación sepa desde cuándo los datos son nuevos. El resto de columnas, como antes."""
    hasta = tabla.groupby("exchange")["recibido_utc"].max().to_dict() if not tabla.empty else {}
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila(), "hasta_utc": hasta.get(r.exchange, pd.NaT)} for r in resultados],
                           FUENTE_SENALES)
