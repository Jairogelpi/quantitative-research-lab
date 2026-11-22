"""Robustez de los parámetros: ¿se sostiene el hallazgo si se cambia un poco el parámetro elegido?

Conceptos:
- Parámetro: lo que el investigador eligió al diseñar el estudio (la banda del imbalance, los niveles del OFI, el
  horizonte, el retardo del lead-lag). Si una relación solo aparece con UN valor y desaparece con los de al
  lado, lo más probable es que ese valor se haya encontrado por azar entre muchos probados.
- Vecinos: los valores adyacentes del mismo parámetro, con todo lo demás igual y en la MISMA ejecución (mismos
  datos): la banda anterior y la siguiente, el horizonte anterior y el siguiente... Ejecuciones distintas usan
  datos distintos y no sirven para comparar.
  · imbalance (`estudios`): bandas y horizontes adyacentes, por exchange y precio de referencia.
  · OFI (`estudios_ofi`): niveles y horizontes adyacentes (poder predictivo); niveles adyacentes (impacto).
  · lead-lag (`estudios_lead_lag`): retardos adyacentes, por par líder-seguidor.
  · decaimiento (`estudios_senales`): horizontes adyacentes al pico de la curva; solo si la fila guardada
    conserva la curva (`horizontes` y `ts`).
- Umbrales (con nombre, para poder discutirlos):
  · `T_SIGNIFICATIVO` = 2: un vecino es significativo con |t| ≥ 2, el mismo umbral que usan los estudios para
    confirmar fuera de muestra. A los vecinos no se les pide pasar Benjamini-Hochberg: no se busca descubrirlos,
    sino ver si apoyan al hallazgo.
  · `MIN_MISMO_SIGNO` = 0,75: al menos tres de cada cuatro vecinos con el mismo signo. Se tolera uno en contra
    porque en el borde de la rejilla (banda muy ancha, horizonte muy largo) el efecto puede apagarse de verdad.
  · `MIN_SIGNIFICATIVOS` = 0,5: más de la mitad de los vecinos, del mismo signo y significativos ("la mayoría").
  · `MIN_PROBADOS` = 4: con menos de cuatro valores probados no hay "muchos" entre los que elegir el mejor.

Estados:
- robusta: los vecinos coinciden en signo (≥ `MIN_MISMO_SIGNO`) y más de la mitad son significativos.
- frágil: tiene vecinos, pero no la respaldan: solo funciona (o funciona mucho mejor) con ese parámetro.
- sin vecinos: no se probaron valores adyacentes (o no se guardaron), así que no se puede saber.
- Además, "selección del mejor parámetro": el hallazgo es el de mayor |t| entre al menos `MIN_PROBADOS` valores
  probados y sus vecinos no lo respaldan (frágil). Es el patrón típico de quedarse con el mejor de muchos.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .registro import _valor, describir, nombre_estudio, sujeto

FUENTE_ROBUSTEZ = "estudios_robustez"
T_SIGNIFICATIVO = 2.0
MIN_MISMO_SIGNO = 0.75
MIN_SIGNIFICATIVOS = 0.5
MIN_PROBADOS = 4
ROBUSTA, FRAGIL, SIN_VECINOS = "robusta", "frágil", "sin vecinos"


@dataclass(frozen=True)
class Especificacion:
    fuente: str
    estudio: str | None        # valor de la columna `estudio`; None si la fuente solo tiene un estudio
    dimensiones: tuple         # parámetros con vecinos
    fijos: tuple               # lo que debe ser igual para ser vecino (además de la ejecución)
    t: str
    hallazgos: frozenset


ESPECIFICACIONES = (
    Especificacion("estudios", "imbalance_retorno", ("banda_bps", "horizonte_rondas"),
                   ("exchange", "precio_referencia", "senal"), "t_descubrimiento", frozenset({"confirmada"})),
    Especificacion("estudios_ofi", "ofi_retorno", ("niveles", "horizonte_rondas"), ("exchange", "precio_referencia"),
                   "t_descubrimiento", frozenset({"confirmada"})),
    Especificacion("estudios_ofi", "ofi_impacto", ("niveles",), ("exchange",), "t_hac",
                   frozenset({"explica el precio"})),
    Especificacion("estudios_lead_lag", None, ("retardo_rondas",), ("lider", "seguidor"), "t_descubrimiento",
                   frozenset({"confirmada"})),
)
FUENTE_DECAIMIENTO = "estudios_senales"


@dataclass(frozen=True)
class Robustez:
    fuente: str
    estudio: str
    exchange: str
    contexto: str              # lo que queda fijo (precio de referencia, señal...)
    parametros: str            # el valor elegido de cada parámetro con vecinos
    ejecutado_utc: pd.Timestamp
    t: float
    vecinos: int
    vecinos_mismo_signo: int
    vecinos_significativos: int
    probados: int
    es_mejor: bool
    motivo: str = ""

    @property
    def estado(self) -> str:
        if self.vecinos == 0:
            return SIN_VECINOS
        if (self.vecinos_mismo_signo / self.vecinos >= MIN_MISMO_SIGNO
                and self.vecinos_significativos / self.vecinos > MIN_SIGNIFICATIVOS):
            return ROBUSTA
        return FRAGIL

    @property
    def seleccion_mejor(self) -> bool:
        return self.es_mejor and self.probados >= MIN_PROBADOS and self.estado == FRAGIL

    def conclusion(self) -> str:
        partes = [p for p in (self.exchange, self.contexto, self.parametros) if p]
        cabecera = f"{self.estudio} ({self.fuente}), " + ", ".join(partes)
        if self.estado == SIN_VECINOS:
            return f"{cabecera}: sin vecinos ({self.motivo or 'no se probaron valores adyacentes'}); no se sabe si es robusta."
        texto = (f"{cabecera}: {self.estado}. t {self.t:.2f}; vecinos: {self.vecinos_mismo_signo}/{self.vecinos} con el "
                 f"mismo signo, {self.vecinos_significativos}/{self.vecinos} significativos (|t| ≥ {T_SIGNIFICATIVO:g}).")
        if self.seleccion_mejor:
            texto += (f" Ojo: selección del mejor parámetro: es el mayor |t| de {self.probados} valores probados y sus "
                      f"vecinos no lo respaldan.")
        return texto

    def a_fila(self) -> dict:
        fila = asdict(self)
        fila["ejecutado_estudio_utc"] = fila.pop("ejecutado_utc")
        return {**fila, "estado": self.estado, "seleccion_mejor": self.seleccion_mejor, "conclusion": self.conclusion()}


def _signo_y_apoyo(t: float, vecinos: list[float]) -> tuple[int, int, int]:
    validos = [v for v in vecinos if math.isfinite(v)]
    mismo = [v for v in validos if np.sign(v) == np.sign(t)]
    return len(validos), len(mismo), sum(1 for v in mismo if abs(v) >= T_SIGNIFICATIVO)


def _ultima_ejecucion(g: pd.DataFrame) -> pd.DataFrame:
    if "ejecutado_utc" not in g.columns or g["ejecutado_utc"].isna().all():
        return g
    return g[g["ejecutado_utc"] == g["ejecutado_utc"].max()]


def _vecinos(run: pd.DataFrame, fila, dimensiones, columna_t: str) -> list[float]:
    """t de los valores adyacentes en cada dimensión, con las demás dimensiones iguales."""
    ts = []
    for d in dimensiones:
        otras = [o for o in dimensiones if o != d]
        linea = run[np.logical_and.reduce([run[o] == fila[o] for o in otras])] if otras else run
        valores = sorted(linea[d].dropna().unique())
        i = valores.index(fila[d])
        for j in (i - 1, i + 1):
            if 0 <= j < len(valores):
                ts += [float(x) for x in linea.loc[linea[d] == valores[j], columna_t]]
    return ts


def _rejilla(df: pd.DataFrame, esp: Especificacion) -> list[Robustez]:
    if esp.estudio is not None and "estudio" in df.columns:
        df = df[df["estudio"] == esp.estudio]
    if df.empty or not {*esp.dimensiones, esp.t, "estado"} <= set(df.columns):
        return []
    fijos = [c for c in esp.fijos if c in df.columns]
    df = df.dropna(subset=list(esp.dimensiones))
    grupos = df.groupby(fijos, dropna=False, sort=True) if fijos else [((), df)]
    resultados = []
    for _, g in grupos:
        run = _ultima_ejecucion(g)
        t_validos = run[esp.t].astype(float)
        t_validos = t_validos[np.isfinite(t_validos)]
        for fila in run[run["estado"].isin(esp.hallazgos)].to_dict("records"):
            t = float(fila[esp.t]) if _valor(fila, esp.t) is not None else math.nan
            if math.isnan(t):
                continue
            n, mismo, sig = _signo_y_apoyo(t, _vecinos(run, fila, esp.dimensiones, esp.t))
            contexto = describir(fila, [c for c in fijos if c not in ("exchange", "lider", "seguidor")])
            resultados.append(Robustez(
                esp.fuente, esp.estudio or nombre_estudio(fila, esp.fuente), sujeto(fila), contexto,
                describir(fila, esp.dimensiones), _valor(fila, "ejecutado_utc") or pd.NaT, t, n, mismo, sig,
                len(t_validos), bool(len(t_validos)) and abs(t) >= float(t_validos.abs().max())))
    return resultados


def _curva(fila, nombre: str):
    v = fila.get(nombre)
    if v is None or isinstance(v, float):
        return None
    return [float(x) for x in v]


def _decaimiento(df: pd.DataFrame) -> list[Robustez]:
    if "estudio" not in df.columns or "estado" not in df.columns:
        return []
    curvas = df[df["estudio"] == "decaimiento"]
    claves = [c for c in ("exchange", "senal") if c in curvas.columns]
    if "ejecutado_utc" in curvas.columns and claves:  # solo la última ejecución de cada exchange y señal
        ultima = curvas.groupby(claves, dropna=False)["ejecutado_utc"].transform("max")
        curvas = curvas[curvas["ejecutado_utc"] == ultima]
    resultados = []
    for fila in curvas[curvas["estado"] == "con efecto"].to_dict("records"):
        horizontes, ts, betas = _curva(fila, "horizontes"), _curva(fila, "ts"), _curva(fila, "betas")
        base = dict(fuente=FUENTE_DECAIMIENTO, estudio="decaimiento", exchange=sujeto(fila),
                    contexto=describir(fila, ["senal"]), ejecutado_utc=_valor(fila, "ejecutado_utc") or pd.NaT)
        pico = _valor(fila, "pico_rondas")
        if not horizontes or not ts or len(horizontes) != len(ts):
            resultados.append(Robustez(**base, parametros=f"horizonte_rondas={int(pico)}" if pico is not None else "",
                                       t=math.nan, vecinos=0, vecinos_mismo_signo=0, vecinos_significativos=0,
                                       probados=0, es_mejor=False,
                                       motivo="la fila guardada no conserva la curva por horizonte"))
            continue
        if pico is not None and pico in horizontes:
            i = horizontes.index(pico)
        else:
            i = int(np.nanargmax(np.abs(betas if betas and len(betas) == len(ts) else ts)))
        t = ts[i]
        vecinos = [ts[j] for j in (i - 1, i + 1) if 0 <= j < len(ts)]
        n, mismo, sig = _signo_y_apoyo(t, vecinos)
        finitos = [abs(x) for x in ts if math.isfinite(x)]
        resultados.append(Robustez(**base, parametros=f"horizonte_rondas={int(horizontes[i])}", t=t, vecinos=n,
                                   vecinos_mismo_signo=mismo, vecinos_significativos=sig, probados=len(finitos),
                                   es_mejor=bool(finitos) and abs(t) >= max(finitos)))
    return resultados


def evaluar_robustez(consultar: Callable[[str], pd.DataFrame], fuentes) -> list[Robustez]:
    """Un resultado por hallazgo de la última ejecución de cada estudio con parámetros vecinos. Las fuentes que
    no existen, o a las que les faltan columnas, se ignoran."""
    fuentes, leidas, resultados = set(fuentes), {}, []
    for esp in ESPECIFICACIONES:
        if esp.fuente in fuentes:
            df = leidas.setdefault(esp.fuente, consultar(f'SELECT * FROM "{esp.fuente}"'))
            resultados += _rejilla(df, esp)
    if FUENTE_DECAIMIENTO in fuentes:
        resultados += _decaimiento(consultar(f'SELECT * FROM "{FUENTE_DECAIMIENTO}"'))
    return resultados


def resumen_robustez(resultados: list[Robustez]) -> str:
    if not resultados:
        return "No hay hallazgos con parámetros que evaluar."
    cuenta = {e: sum(r.estado == e for r in resultados) for e in (ROBUSTA, FRAGIL, SIN_VECINOS)}
    seleccion = sum(r.seleccion_mejor for r in resultados)
    return (f"Robustez de {len(resultados)} hallazgos: {cuenta[ROBUSTA]} robustos, {cuenta[FRAGIL]} frágiles y "
            f"{cuenta[SIN_VECINOS]} sin vecinos; {seleccion} con señales de selección del mejor parámetro.")


def guardar_robustez(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda en `estudios_robustez`: una fila por hallazgo evaluado, con la ejecución de esta evaluación."""
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **r.a_fila()}
                            for r in resultados], FUENTE_ROBUSTEZ)
