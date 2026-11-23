"""Relojes: ¿cuánto se separa la hora que pone el exchange de la nuestra? (Fase 2; base del lead-lag en ms).

Conceptos:
- Retraso aparente d = recibido − hora_exchange: el instante en que NOSOTROS recibimos el dato (nuestro reloj)
  menos el que el exchange escribió en él (su reloj). Mezcla dos cosas: d = latencia de red + desfase, con
  desfase = nuestro reloj − reloj del exchange.
- La latencia nunca es negativa: un mensaje no llega antes de salir. Si d < 0 de forma sistemática, los relojes
  NO coinciden (el nuestro va por detrás del suyo, o el suyo por delante). Es la prueba más directa de desfase.
- Suelo: el percentil `PERCENTIL_SUELO` de d en cada minuto ≈ latencia mínima + desfase. La parte de d por encima
  del suelo (exceso) es la variación de la latencia (colas, lotes del exchange); el desfase no varía con ella.
- Deriva: pendiente del suelo frente al tiempo, en ms por hora. Un reloj que adelanta o atrasa la acumula; una
  resincronización del reloj (NTP, servicio de hora de Windows) aparece como un SALTO del suelo y abre un
  segmento nuevo; la deriva se mide dentro de cada segmento.
- REST: la petición sale en `solicitado_utc` y vuelve en `recibido_utc`; si los relojes coinciden y la hora del
  exchange es la de la respuesta, debe caer dentro de esa ventana. Una hora POSTERIOR a la recepción es
  imposible (desfase); una ANTERIOR a la solicitud puede ser desfase o una hora rancia (la de la última
  actualización del libro, no la de la respuesta; Kraken la da así) y no basta para concluir.
- Algoritmo de Cristian: con el viaje de ida y vuelta (RTT) de la petición REST, la latencia mínima de ida está
  entre 0 y el RTT mínimo, y su estimación central es RTT/2. Desfase estimado = suelo − RTT/2.
- Separar latencia y desfase solo es posible hasta ese margen: sin un reloj común (PTP, GPS) la latencia mínima
  de ida no se observa; el RTT la acota.
- Desfase común: si todos los exchanges muestran el mismo desfase y la misma deriva, lo que se mueve es nuestro
  reloj. Para un lead-lag con horas de RECEPCIÓN eso no importa (todas están en nuestro reloj); con horas del
  EXCHANGE importa el desfase RELATIVO entre exchanges.
- Incertidumbre del lead-lag (`incertidumbre_lead_lag`): el mayor sesgo que relojes y latencias pueden meter en
  un adelanto medido entre dos exchanges. Un adelanto menor que ella no se distingue de un artefacto de horas.

Estados (por exchange y fuente):
- datos insuficientes: menos de `MIN_MUESTRAS` mensajes con hora del exchange.
- hora rancia: (REST) más de `MAX_FRACCION_RANCIA` de las horas antes de la solicitud; esa hora no mide el reloj.
- desfase de reloj: d < −`TOLERANCIA_S` en el percentil 1, o más de `MAX_FRACCION_IMPOSIBLE` de las fotos REST con
  la hora del exchange posterior a la recepción: llegadas antes de la salida.
- deriva de reloj: el suelo se mueve más de `UMBRAL_DERIVA_MS_H` por hora.
- reloj coherente: ninguna de las anteriores.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
import pandas as pd

METODO = "relojes/v1"
FUENTE_RELOJES = "estudios_relojes"
FUENTES = ("eventos_libro", "trades", "cotizaciones")   # websocket (libro, trades) y REST
FUENTE_REST = "cotizaciones"

MIN_MUESTRAS = 100
# Horas del exchange en ms (OKX, Bitvavo) se truncan hasta 1 ms; nuestro reloj y la conversión añaden < 1 ms.
# 5 ms deja margen a eso sin ocultar desfases de decenas de ms, que son los que afectan a un lead-lag.
TOLERANCIA_S = 0.005
MAX_FRACCION_IMPOSIBLE = 0.01   # 1 %: unas pocas fotos con horas raras no definen un reloj
# Si la mayoría de las horas REST caen antes de pedir la foto, la hora es la de la última actualización del libro
# (rancia), no la de la respuesta: el retraso aparente mide la edad del libro, no el reloj.
MAX_FRACCION_RANCIA = 0.5
# Un reloj sincronizado por NTP deriva < 1 ms/h. 10 ms/h es la resolución mínima del estimador de
# Hayashi-Yoshida (paso de 10 ms): una deriva mayor mueve el adelanto medido más que un paso cada hora.
UMBRAL_DERIVA_MS_H = 10.0
PERCENTIL_SUELO = 0.05
MIN_POR_MINUTO = 5              # minutos con menos mensajes no dan un suelo fiable
# 50 ms entre minutos seguidos es ~30 veces la deriva de un reloj de cuarzo libre (≈ 100 ms/h = 1,7 ms/min):
# solo un ajuste del reloj mueve el suelo tanto de golpe.
SALTO_S = 0.05
HUECO_SEGMENTO_MIN = 10         # sin datos durante 10 min: segmento nuevo (la captura estuvo parada)
MIN_MINUTOS_DERIVA = 30         # con menos de media hora la pendiente es ruido de la latencia
RECEPCION, EXCHANGE = "recepcion", "exchange"

INSUFICIENTE, DESFASE = "datos insuficientes", "desfase de reloj"
DERIVA, COHERENTE, RANCIA = "deriva de reloj", "reloj coherente", "hora rancia"


@dataclass(frozen=True)
class Reloj:
    exchange: str
    fuente: str
    n: int
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    mediana_s: float
    p1_s: float
    p99_s: float
    suelo_s: float
    deriva_ms_h: float
    segmentos: int
    saltos: int
    rtt_min_s: float
    frac_posterior_recepcion: float
    frac_anterior_solicitud: float
    minimo: int = MIN_MUESTRAS

    @property
    def exceso_s(self) -> float:
        """Mediana de d sobre el suelo: la latencia típica por encima de la mínima."""
        return self.mediana_s - self.suelo_s

    @property
    def desfase_estimado_s(self) -> float:
        """Cristian: suelo − RTT/2 (nuestro reloj − el del exchange). NaN sin RTT del mismo exchange."""
        return self.suelo_s - self.rtt_min_s / 2

    @property
    def estado(self) -> str:
        if self.n < self.minimo:
            return INSUFICIENTE
        if self.frac_anterior_solicitud > MAX_FRACCION_RANCIA:
            return RANCIA
        if self.p1_s < -TOLERANCIA_S or self.frac_posterior_recepcion > MAX_FRACCION_IMPOSIBLE:
            return DESFASE
        if math.isfinite(self.deriva_ms_h) and abs(self.deriva_ms_h) > UMBRAL_DERIVA_MS_H:
            return DERIVA
        return COHERENTE

    def conclusion(self) -> str:
        cabecera = f"Reloj de {self.exchange} ({self.fuente}):"
        if self.estado == INSUFICIENTE:
            return f"{cabecera} datos insuficientes ({self.n} mensajes con hora; hacen falta {self.minimo})."
        if self.estado == RANCIA:
            return (f"{cabecera} hora rancia: {self.frac_anterior_solicitud:.1%} de las horas son anteriores a la "
                    f"petición (mediana del retraso aparente {self.mediana_s * 1e3:+.0f} ms). Es la hora de la última "
                    "actualización del libro, no la de la respuesta; no sirve para medir el reloj.")
        texto = (f"{cabecera} {self.estado}. Recibido − hora del exchange: mediana {self.mediana_s * 1e3:+.0f} ms, "
                 f"p1 {self.p1_s * 1e3:+.0f} ms, p99 {self.p99_s * 1e3:+.0f} ms; suelo {self.suelo_s * 1e3:+.0f} ms, "
                 f"deriva {self.deriva_ms_h:+.1f} ms/h ({self.segmentos} segmento(s), {self.saltos} salto(s)).")
        if self.p1_s < -TOLERANCIA_S:
            texto += (" Muchos mensajes llegan antes de que el exchange diga haberlos enviado: nuestro reloj va por "
                      "detrás del suyo (o el suyo por delante).")
        if self.fuente == FUENTE_REST:
            texto += (f" REST: {self.frac_posterior_recepcion:.1%} de las horas después de recibir (imposible), "
                      f"{self.frac_anterior_solicitud:.1%} antes de pedir (desfase u hora rancia).")
        if math.isfinite(self.rtt_min_s):
            texto += (f" Con RTT mínimo {self.rtt_min_s * 1e3:.0f} ms, desfase estimado "
                      f"{self.desfase_estimado_s * 1e3:+.0f} ms (± {self.rtt_min_s * 1e3 / 2:.0f} ms).")
        return texto

    def a_fila(self) -> dict:
        return {**asdict(self), "exceso_s": self.exceso_s, "desfase_estimado_s": self.desfase_estimado_s,
                "estado": self.estado, "conclusion": self.conclusion()}


# --- lectura (DuckDB) -----------------------------------------------------------------------------------------------

def _filtro(desde_utc, hasta_utc) -> str:
    condiciones = ["hora_exchange_utc IS NOT NULL"]
    if desde_utc is not None:
        condiciones.append(f"recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}'")
    if hasta_utc is not None:
        condiciones.append(f"recibido_utc <= TIMESTAMPTZ '{pd.Timestamp(hasta_utc).isoformat()}'")
    return " AND ".join(condiciones)


def _consultas(fuente: str, filtro: str) -> tuple[str, str]:
    """(global por exchange, suelo por minuto). Los mensajes del websocket se cuentan una vez (cada fila es un
    nivel o un trade; los de un mismo mensaje comparten las dos horas)."""
    if fuente == FUENTE_REST:
        base = (f"SELECT exchange, recibido_utc, hora_exchange_utc, solicitado_utc, latencia_s FROM {fuente} "
                f"WHERE {filtro}")
        extra = ("avg((hora_exchange_utc > recibido_utc)::INT) AS frac_posterior, "
                 "avg((hora_exchange_utc < solicitado_utc)::INT) AS frac_anterior, "
                 "quantile_cont(latencia_s, 0.01) AS rtt_min")
    else:
        base = f"SELECT DISTINCT exchange, recibido_utc, hora_exchange_utc FROM {fuente} WHERE {filtro}"
        extra = "NULL::DOUBLE AS frac_posterior, NULL::DOUBLE AS frac_anterior, NULL::DOUBLE AS rtt_min"
    d = f"m AS ({base}), d AS (SELECT *, epoch(recibido_utc) - epoch(hora_exchange_utc) AS d FROM m)"
    globales = (f"WITH {d} SELECT exchange, count(*) AS n, min(recibido_utc) AS desde_utc, max(recibido_utc) AS "
                f"hasta_utc, quantile_cont(d, 0.01) AS p1, median(d) AS mediana, quantile_cont(d, 0.99) AS p99, "
                f"{extra} FROM d GROUP BY exchange")
    minutos = (f"WITH {d} SELECT exchange, time_bucket(INTERVAL 1 MINUTE, recibido_utc) AS minuto, count(*) AS n, "
               f"quantile_cont(d, {PERCENTIL_SUELO}) AS suelo FROM d GROUP BY ALL ORDER BY exchange, minuto")
    return globales, minutos


def _fuentes_disponibles(consultar: Callable[[str], pd.DataFrame]) -> list[str]:
    tablas = set(consultar("SELECT table_name FROM information_schema.tables")["table_name"])
    return [f for f in FUENTES if f in tablas]


# --- cálculo (puro) -------------------------------------------------------------------------------------------------

def _segmentos(minutos: pd.DataFrame) -> list[pd.DataFrame]:
    """Parte la serie del suelo por minuto en tramos sin huecos largos ni saltos del reloj."""
    m = minutos.sort_values("minuto").reset_index(drop=True)
    hueco = m["minuto"].diff() > pd.Timedelta(minutes=HUECO_SEGMENTO_MIN)
    salto = m["suelo"].diff().abs() > SALTO_S
    tramo = (hueco | salto).cumsum()
    return [g for _, g in m.groupby(tramo)]


def _deriva(minutos: pd.DataFrame) -> tuple[float, int, int]:
    """(deriva en ms/h, segmentos, saltos). Pendiente por mínimos cuadrados del suelo frente a las horas en cada
    segmento de al menos `MIN_MINUTOS_DERIVA` minutos, media ponderada por su duración."""
    m = minutos[minutos["n"] >= MIN_POR_MINUTO]
    if m.empty:
        return math.nan, 0, 0
    m = m.sort_values("minuto")
    saltos = int(((m["suelo"].diff().abs() > SALTO_S)
                  & (m["minuto"].diff() <= pd.Timedelta(minutes=HUECO_SEGMENTO_MIN))).sum())
    pendientes, pesos = [], []
    tramos = _segmentos(m)
    for g in tramos:
        if len(g) < MIN_MINUTOS_DERIVA:
            continue
        horas = (g["minuto"] - g["minuto"].iloc[0]).dt.total_seconds().to_numpy() / 3600
        pendientes.append(np.polyfit(horas, g["suelo"].to_numpy(dtype=float), 1)[0] * 1e3)
        pesos.append(len(g))
    deriva = float(np.average(pendientes, weights=pesos)) if pendientes else math.nan
    return deriva, len(tramos), saltos


def estudiar_relojes(globales: pd.DataFrame, minutos: pd.DataFrame, minimo: int = MIN_MUESTRAS) -> list[Reloj]:
    """Un resultado por exchange y fuente. `globales`: exchange, fuente, n, desde_utc, hasta_utc, p1, mediana, p99,
    frac_posterior, frac_anterior, rtt_min. `minutos`: exchange, fuente, minuto, n, suelo. El RTT de la fuente REST
    de un exchange se usa en todas sus fuentes (es la cota de su latencia mínima)."""
    rtt = {fila.exchange: fila.rtt_min for fila in globales.itertuples() if fila.fuente == FUENTE_REST}
    resultados = []
    for fila in globales.sort_values(["exchange", "fuente"]).itertuples():
        m = minutos[(minutos.exchange == fila.exchange) & (minutos.fuente == fila.fuente)]
        validos = m[m["n"] >= MIN_POR_MINUTO]
        deriva, segmentos, saltos = _deriva(m)
        resultados.append(Reloj(
            exchange=fila.exchange, fuente=fila.fuente, n=int(fila.n), desde_utc=fila.desde_utc,
            hasta_utc=fila.hasta_utc, mediana_s=float(fila.mediana), p1_s=float(fila.p1), p99_s=float(fila.p99),
            suelo_s=float(validos["suelo"].median()) if len(validos) else math.nan, deriva_ms_h=deriva,
            segmentos=segmentos, saltos=saltos, rtt_min_s=_flotante(rtt.get(fila.exchange)),
            frac_posterior_recepcion=_flotante(fila.frac_posterior),
            frac_anterior_solicitud=_flotante(fila.frac_anterior), minimo=minimo))
    return resultados


def _flotante(valor) -> float:
    return math.nan if valor is None or pd.isna(valor) else float(valor)


def medir_relojes(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None,
                  minimo: int = MIN_MUESTRAS) -> list[Reloj]:
    """Mide el reloj de cada exchange en cada fuente con hora del exchange (agregando en DuckDB)."""
    filtro = _filtro(desde_utc, hasta_utc)
    globales, minutos = [], []
    for fuente in _fuentes_disponibles(consultar):
        sql_global, sql_minutos = _consultas(fuente, filtro)
        g, m = consultar(sql_global), consultar(sql_minutos)
        if g.empty:
            continue
        globales.append(g.assign(fuente=fuente))
        minutos.append(m.assign(fuente=fuente))
    if not globales:
        return []
    return estudiar_relojes(pd.concat(globales, ignore_index=True), pd.concat(minutos, ignore_index=True), minimo)


# --- uso por otros estudios -----------------------------------------------------------------------------------------

def _reloj(relojes, exchange: str, fuente: str) -> Reloj | None:
    return next((r for r in relojes if r.exchange == exchange and r.fuente == fuente
                 and r.estado not in (INSUFICIENTE, RANCIA)), None)


def incertidumbre_lead_lag(relojes, a: str, b: str, base: str, fuente: str = "eventos_libro") -> float:
    """Mayor sesgo (s) que las horas pueden meter en un adelanto medido entre `a` y `b`. NaN si falta el reloj o
    el RTT de alguno.

    Con d = latencia + desfase y la latencia mínima de ida lmin ∈ [0, RTT mínimo]:
    - base "recepcion" (todo en nuestro reloj): el sesgo es la diferencia de latencias típicas,
      (exceso_a + lmin_a) − (exceso_b + lmin_b) ∈ [Δexceso − rtt_b, Δexceso + rtt_a].
    - base "exchange" (cada uno en su reloj): el sesgo es el desfase relativo entre exchanges,
      (suelo_a − lmin_a) − (suelo_b − lmin_b) ∈ [Δsuelo − rtt_a, Δsuelo + rtt_b], más lo que la diferencia de
      derivas acumula en media ventana. La deriva común (nuestro reloj) se cancela en las dos bases.
    Los suelos deben medirse en la misma ventana para que nuestra deriva afecte igual a los dos.
    """
    ra, rb = _reloj(relojes, a, fuente), _reloj(relojes, b, fuente)
    if ra is None or rb is None or not (math.isfinite(ra.rtt_min_s) and math.isfinite(rb.rtt_min_s)):
        return math.nan
    if base == RECEPCION:
        delta = ra.exceso_s - rb.exceso_s
        return max(abs(delta - rb.rtt_min_s), abs(delta + ra.rtt_min_s))
    if base == EXCHANGE:
        delta = ra.suelo_s - rb.suelo_s
        horas = min((ra.hasta_utc - ra.desde_utc).total_seconds(), (rb.hasta_utc - rb.desde_utc).total_seconds()) / 3600
        derivas = (ra.deriva_ms_h - rb.deriva_ms_h) / 1e3 * horas / 2
        extra = abs(derivas) if math.isfinite(derivas) else 0.0
        return max(abs(delta - ra.rtt_min_s), abs(delta + rb.rtt_min_s)) + extra
    raise ValueError(f"base desconocida: {base!r} (usa {RECEPCION!r} o {EXCHANGE!r})")


def diagnostico_comun(relojes, fuente: str = "eventos_libro") -> str:
    """Si todos los exchanges muestran el mismo desfase y la misma deriva, el reloj que se mueve es el nuestro."""
    validos = [r for r in relojes if r.fuente == fuente and r.estado not in (INSUFICIENTE, RANCIA)]
    if len(validos) < 2:
        return f"Diagnóstico común ({fuente}): hacen falta al menos dos exchanges con datos."
    suelos = np.array([r.suelo_s for r in validos])
    derivas = np.array([r.deriva_ms_h for r in validos])
    nombres = ", ".join(r.exchange for r in validos)
    mismo_suelo = np.ptp(suelos) < max(SALTO_S, 0.5 * np.abs(suelos).max())
    deriva_comun = (np.all(np.isfinite(derivas)) and np.abs(derivas).min() > UMBRAL_DERIVA_MS_H
                    and len(set(np.sign(derivas))) == 1 and np.ptp(derivas) < UMBRAL_DERIVA_MS_H)
    negativos = bool(np.all(suelos < -TOLERANCIA_S))
    partes = []
    if negativos and mismo_suelo:
        partes.append(f"el desfase es común a {nombres} (suelos {', '.join(f'{s * 1e3:+.0f}' for s in suelos)} ms): "
                      "apunta a nuestro reloj, no al de los exchanges")
    if deriva_comun:
        partes.append(f"la deriva es común ({', '.join(f'{d:+.0f}' for d in derivas)} ms/h): es nuestro reloj el que "
                      "se mueve; con horas de recepción se cancela entre exchanges")
    if not partes:
        return f"Diagnóstico común ({fuente}): sin desfase ni deriva comunes entre {nombres}."
    return f"Diagnóstico común ({fuente}): " + "; ".join(partes) + "."


def guardar_relojes(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda los instantes con timezone UTC explícita; DuckDB puede devolver timestamps naive."""
    def utc(valor):
        ts = pd.Timestamp(valor)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    filas = []
    for r in resultados:
        fila = r.a_fila()
        fila["desde_utc"] = utc(r.desde_utc)
        fila["hasta_utc"] = utc(r.hasta_utc)
        filas.append({"estudio": "relojes", "metodo": METODO, "ejecutado_utc": utc(ejecutado_utc),
                      "recibido_utc": utc(ejecutado_utc), **fila})
    return almacen.guardar(filas, FUENTE_RELOJES)
