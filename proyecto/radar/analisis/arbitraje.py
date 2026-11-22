"""Arbitraje entre exchanges con comisiones: episodios de oportunidad, profundidad real y nuestra latencia (Fase 6).

Conceptos:
- Ruta A → B: comprar BTC en A al mejor ask y venderlo en B al mejor bid, a la vez. Hay una ruta por cada par
  ordenado de exchanges (6 con tres exchanges).
- Hora de recepción: los dos libros se alinean con NUESTRA hora de recepción, porque es lo que veríamos al decidir.
  En cada instante en que cambia cualquiera de los dos libros se toma el último mejor nivel recibido de cada uno,
  reconstruido mensaje a mensaje desde `eventos_libro` (`mejores_desde_eventos`, el mismo libro que Hayashi-Yoshida).
- Ventaja bruta (bps): (bid_B − ask_A) / ask_A. Ventaja neta: (bid_B · (1 − f_B) − ask_A · (1 + f_A)) / ask_A, con
  f la comisión de cada pata. Positiva = la ida y vuelta deja dinero.
- Escenarios de comisiones: "sin comisiones" (referencia: cuántas veces se cruzan los libros), "taker" (las dos
  patas son órdenes de mercado; lo ejecutable de verdad) y "maker en la compra" (la compra paga la comisión maker,
  la venta la taker). Este último es una COTA de comisiones mínimas con los mismos precios: una orden maker no se
  ejecuta al ask (espera en el libro), no tiene ejecución garantizada y, cuando se ejecuta, suele ser porque el
  precio va en contra (selección adversa, ver `markouts`). Sirve para ver si ni siquiera así queda algo.
- Libro vivo: un mejor nivel solo vale hasta `MAX_SILENCIO_S` después del último mensaje de su exchange. BTC/EUR
  recibe varios mensajes por segundo en los tres; un silencio más largo es la captura parada o un libro invalidado
  (hueco de secuencia) a la espera del siguiente snapshot.
- Episodio: racha máxima de instantes seguidos con ventaja neta > 0 y los dos libros vivos. Empieza al recibir el
  cambio que abre la ventaja y termina al recibir el que la cierra (o un libro deja de estar vivo). Si llega al final
  de los datos queda "censurado": su duración es una cota inferior.
- Tamaño ejecutable: se barren a la vez los asks de A y los bids de B (`barrer_compra`, `barrer_venta`) hasta la
  cantidad en la que la ventaja neta MARGINAL (la del siguiente BTC) deja de ser positiva. Se usan los libros de
  `libros_flujo` (uno por segundo, validados con checksum o secuencia) tomados DENTRO del episodio; si ninguno cae
  dentro (episodios de menos de un segundo), el tamaño es el del mejor nivel en el pico, min(cantidad ask A,
  cantidad bid B), que es exacto pero es una cota inferior.
- Alcanzable: vemos cada cambio una latencia de ida (≈ RTT/2) después de que ocurra en el exchange, y nuestra orden
  llega otra latencia de ida después de enviarla. Para que la orden encuentre el precio, el episodio (medido en
  nuestro reloj) debe durar al menos un RTT completo en las DOS patas: duración ≥ max(RTT_A, RTT_B). El RTT es el
  mínimo (percentil 1) de las peticiones REST (`relojes.medir_relojes`), así que la regla es optimista; además, los
  participantes más rápidos (cerca del exchange) ven el episodio antes y se lo llevan primero.
- Inventario: la ruta exige tener EUR en A y BTC en B antes del episodio; cada ida y vuelta desplaza el inventario
  (más BTC en A, más EUR en B) y reequilibrarlo exige transferencias con comisiones de retirada y horas de espera.
  No se modela: el beneficio "teórico" es una cota superior incluso para lo alcanzable.
- Estudio descriptivo: no contrasta hipótesis ni guarda p-valores ni estadísticos t; el registro global de pruebas
  (`registro.py`) no lo cuenta.

Estados (por ruta y escenario, y para todas las rutas a la vez):
- datos insuficientes: menos de `MIN_SEGUNDOS` con los dos libros vivos.
- sin oportunidades: ningún episodio con ventaja neta positiva.
- oportunidades inalcanzables: hay episodios, pero ninguno dura el RTT de sus dos patas.
- oportunidades alcanzables: al menos un episodio dura el RTT de sus dos patas.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from radar.configuracion import comisiones_taker
from radar.mercado.libro import Libro, barrer_compra, barrer_venta

from .hayashi_yoshida import (
    NS,
    PARAMETROS_LIBRO,
    _ns,
    eventos_flujo,
    mejores_desde_eventos,
)
from .relojes import FUENTE_REST, medir_relojes

METODO = "arbitraje/v1"
FUENTE_ARBITRAJE = "estudios_arbitraje"
MAX_SILENCIO_S = 10.0
MIN_SEGUNDOS = 600            # 10 minutos con los dos libros vivos
TOLERANCIA_FOTOS_S = 1.0      # fotos de `libros_flujo` de los dos exchanges que se emparejan
TODOS = "todos"

# Comisiones maker del nivel más bajo, de las mismas fuentes oficiales que `COMISIONES_TAKER` (configuracion.py).
COMISIONES_MAKER = {"kraken": 0.0040, "okx": 0.0010, "bitvavo": 0.0015}
SIN_COMISIONES, TAKER, MAKER_COMPRA = "sin comisiones", "taker", "maker en la compra"
ESCENARIOS = (SIN_COMISIONES, TAKER, MAKER_COMPRA)

INSUFICIENTE, SIN_OPORTUNIDADES = "datos insuficientes", "sin oportunidades"
INALCANZABLES, ALCANZABLES = "oportunidades inalcanzables", "oportunidades alcanzables"

COLUMNAS_EPISODIO = ["escenario", "compra", "venta", "inicio_utc", "fin_utc", "inicio_ns", "fin_ns", "duracion_s",
                     "censurado", "max_neto_bps", "media_neto_bps", "ask", "bid", "cantidad_tope_btc",
                     "beneficio_tope_eur", "cantidad_btc", "beneficio_eur", "fuente_tamano", "alcanzable"]


def comisiones(escenario: str, compra: str, venta: str) -> tuple[float, float]:
    """(comisión de la pata de compra, de la de venta) en fracción del importe."""
    taker = comisiones_taker()
    if escenario == SIN_COMISIONES:
        return 0.0, 0.0
    if escenario == TAKER:
        return taker[compra], taker[venta]
    if escenario == MAKER_COMPRA:
        return COMISIONES_MAKER[compra], taker[venta]
    raise ValueError(f"Escenario de comisiones desconocido: {escenario!r}")


# --- ventaja y episodios (puro) -------------------------------------------------------------------------------------

def ventaja_bps(ask_compra, bid_venta, comision_compra: float = 0.0, comision_venta: float = 0.0):
    """Ventaja neta en bps sobre lo que cuesta comprar: (bid · (1 − f_venta) − ask · (1 + f_compra)) / ask. Sin
    comisiones es la ventaja bruta. Acepta escalares o arrays."""
    ask, bid = np.asarray(ask_compra, dtype=float), np.asarray(bid_venta, dtype=float)
    neto = (bid * (1 - comision_venta) - ask * (1 + comision_compra)) / ask * 1e4
    return float(neto) if neto.ndim == 0 else neto


def serie_par(compra: pd.DataFrame, venta: pd.DataFrame, comision_compra: float = 0.0, comision_venta: float = 0.0,
              max_silencio_s: float = MAX_SILENCIO_S, desde_ns: int | None = None) -> pd.DataFrame:
    """La ruta compra → venta en cada instante en que cambia uno de los dos libros (hora de recepción).

    `compra`, `venta`: mejores niveles como `mejores_desde_eventos` (recibido_ns, bid, bid_cantidad, ask,
    ask_cantidad), ordenados. Con `desde_ns`, la serie empieza en `desde_ns` con el estado que había entonces.
    Columnas: t_ns, ask, ask_cantidad, bid, bid_cantidad, bruto_bps, neto_bps, neto_eur_btc (beneficio por BTC en
    el mejor nivel), valido (los dos libros vivos) y duracion_s (hasta el instante siguiente; 0 en el último)."""
    tc, tv = compra["recibido_ns"].to_numpy(np.int64), venta["recibido_ns"].to_numpy(np.int64)
    t = np.union1d(tc, tv)
    if desde_ns is not None:
        t = np.union1d([int(desde_ns)], t[t >= desde_ns])
    ic, iv = np.searchsorted(tc, t, side="right") - 1, np.searchsorted(tv, t, side="right") - 1
    hay = (ic >= 0) & (iv >= 0)
    ic, iv = np.maximum(ic, 0), np.maximum(iv, 0)
    silencio = int(max_silencio_s * NS)
    vivo = hay & (t - tc[ic] <= silencio) & (t - tv[iv] <= silencio) if len(tc) and len(tv) else np.zeros(len(t), bool)
    columna = lambda df, c, i: df[c].to_numpy(float)[i] if len(df) else np.full(len(t), math.nan)
    ask, ask_c = columna(compra, "ask", ic), columna(compra, "ask_cantidad", ic)
    bid, bid_c = columna(venta, "bid", iv), columna(venta, "bid_cantidad", iv)
    neto_eur = bid * (1 - comision_venta) - ask * (1 + comision_compra)
    return pd.DataFrame({"t_ns": t, "ask": ask, "ask_cantidad": ask_c, "bid": bid, "bid_cantidad": bid_c,
                         "bruto_bps": ventaja_bps(ask, bid) if len(t) else np.array([]),
                         "neto_bps": neto_eur / ask * 1e4, "neto_eur_btc": neto_eur, "valido": vivo,
                         "duracion_s": np.r_[np.diff(t), 0] / NS if len(t) else np.array([])})


def episodios(serie: pd.DataFrame) -> pd.DataFrame:
    """Rachas máximas con ventaja neta > 0 y los dos libros vivos. Por episodio: inicio_ns, fin_ns (instante que
    lo cierra, o el último dato si está censurado), duracion_s, censurado, max_neto_bps, media_neto_bps (ponderada
    por tiempo), ask y bid del pico, cantidad_tope_btc y beneficio_tope_eur (mejor nivel en el pico)."""
    columnas = ["inicio_ns", "fin_ns", "duracion_s", "censurado", "max_neto_bps", "media_neto_bps", "ask", "bid",
                "cantidad_tope_btc", "beneficio_tope_eur"]
    positivo = (serie["valido"].to_numpy(bool) & (np.nan_to_num(serie["neto_bps"].to_numpy(float), nan=-1) > 0))
    if not positivo.any():
        return pd.DataFrame(columns=columnas)
    borde = np.diff(np.r_[0, positivo.astype(np.int8), 0])
    inicios, finales = np.flatnonzero(borde == 1), np.flatnonzero(borde == -1)
    t, neto, dur = serie["t_ns"].to_numpy(np.int64), serie["neto_bps"].to_numpy(float), serie["duracion_s"].to_numpy()
    filas = []
    for i0, i1 in zip(inicios, finales):
        censurado = i1 >= len(t)
        fin = t[-1] if censurado else t[i1]
        tramo, pesos = neto[i0:i1], dur[i0:i1]
        pico = i0 + int(np.argmax(tramo))
        cantidad = float(min(serie["ask_cantidad"].iloc[pico], serie["bid_cantidad"].iloc[pico]))
        filas.append({"inicio_ns": int(t[i0]), "fin_ns": int(fin), "duracion_s": (fin - t[i0]) / NS,
                      "censurado": bool(censurado), "max_neto_bps": float(tramo.max()),
                      "media_neto_bps": float(np.average(tramo, weights=pesos) if pesos.sum() > 0 else tramo.mean()),
                      "ask": float(serie["ask"].iloc[pico]), "bid": float(serie["bid"].iloc[pico]),
                      "cantidad_tope_btc": cantidad,
                      "beneficio_tope_eur": cantidad * float(serie["neto_eur_btc"].iloc[pico])})
    return pd.DataFrame(filas, columns=columnas)


@dataclass(frozen=True)
class Arbitraje:
    """Ida y vuelta barriendo los dos libros: compra en uno y venta de la misma cantidad en el otro."""
    cantidad_btc: float
    coste_eur: float       # importe de la compra, sin comisión
    ingreso_eur: float     # importe de la venta, sin comisión
    beneficio_eur: float   # ingreso · (1 − f_venta) − coste · (1 + f_compra)


def tamano_ejecutable(libro_compra: Libro, libro_venta: Libro, comision_compra: float = 0.0,
                      comision_venta: float = 0.0) -> Arbitraje:
    """La mayor cantidad con ventaja neta marginal positiva. Entre dos cortes de nivel (de cualquiera de los dos
    libros) el precio marginal de cada lado es constante, así que basta con mirar el tramo siguiente a cada corte;
    la ejecución final se calcula con `barrer_compra` y `barrer_venta`."""
    pa = np.array([n.precio for n in libro_compra.asks])
    qa = np.cumsum([n.cantidad for n in libro_compra.asks])
    pb = np.array([n.precio for n in libro_venta.bids])
    qb = np.cumsum([n.cantidad for n in libro_venta.bids])
    cortes = np.union1d(qa, qb)
    cortes = cortes[cortes <= min(qa[-1], qb[-1])]
    previos = np.r_[0.0, cortes[:-1]]
    ia, ib = np.searchsorted(qa, previos, side="right"), np.searchsorted(qb, previos, side="right")
    marginal = pb[ib] * (1 - comision_venta) - pa[ia] * (1 + comision_compra)
    malos = np.flatnonzero(marginal <= 0)
    n = len(cortes) if not len(malos) else malos[0]
    if n == 0:
        return Arbitraje(0.0, 0.0, 0.0, 0.0)
    cantidad = float(cortes[n - 1])
    coste = float(np.sum(pa * np.clip(cantidad - np.r_[0.0, qa[:-1]], 0, np.diff(np.r_[0.0, qa]))))
    compra, venta = barrer_compra(libro_compra, coste), barrer_venta(libro_venta, cantidad)
    return Arbitraje(cantidad, compra.importe_eur, venta.importe_eur,
                     venta.importe_eur * (1 - comision_venta) - compra.importe_eur * (1 + comision_compra))


def alcanzable(duracion_s, rtt_compra_s: float, rtt_venta_s: float):
    """Duración (en nuestro reloj) ≥ el mayor RTT de las dos patas; sin RTT medido, no se da por alcanzable."""
    rtt = max(rtt_compra_s, rtt_venta_s) if not (math.isnan(rtt_compra_s) or math.isnan(rtt_venta_s)) else math.nan
    resultado = np.asarray(duracion_s, dtype=float) >= rtt if math.isfinite(rtt) else np.zeros(np.shape(duracion_s), bool)
    return bool(resultado) if np.ndim(resultado) == 0 else resultado


def rtt_desde_relojes(relojes) -> dict:
    """{exchange: RTT mínimo (s)} de las peticiones REST medidas por `relojes` (la latencia no depende de la hora
    del exchange, así que también vale con una "hora rancia")."""
    return {r.exchange: float(r.rtt_min_s) for r in relojes
            if r.fuente == FUENTE_REST and r.n >= r.minimo and math.isfinite(r.rtt_min_s)}


# --- resumen --------------------------------------------------------------------------------------------------------

def _cuantil(x, q, pesos=None) -> float:
    x = np.asarray(x, dtype=float)
    if not len(x):
        return math.nan
    if pesos is None:
        return float(np.quantile(x, q))
    w = np.asarray(pesos, dtype=float)
    if w.sum() <= 0:
        return float(np.quantile(x, q))
    orden = np.argsort(x)
    acumulado = np.cumsum(w[orden]) / w.sum()
    return float(x[orden][min(np.searchsorted(acumulado, q), len(x) - 1)])


def _union_s(intervalos) -> float:
    """Segundos cubiertos por la unión de intervalos (inicio_ns, fin_ns)."""
    total, fin_actual, inicio_actual = 0, None, None
    for a, b in sorted(intervalos):
        if fin_actual is None or a > fin_actual:
            if fin_actual is not None:
                total += fin_actual - inicio_actual
            inicio_actual, fin_actual = a, b
        else:
            fin_actual = max(fin_actual, b)
    if fin_actual is not None:
        total += fin_actual - inicio_actual
    return total / NS


@dataclass(frozen=True)
class ResumenArbitraje:
    escenario: str
    compra: str
    venta: str
    comision_compra: float
    comision_venta: float
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    segundos_validos: float
    n_episodios: int
    n_alcanzables: int
    n_censurados: int
    frac_tiempo_positivo: float
    duracion_mediana_s: float
    duracion_p90_s: float
    duracion_max_s: float
    max_neto_bps: float
    beneficio_mediano_eur: float
    beneficio_p90_eur: float
    beneficio_total_eur: float
    beneficio_alcanzable_eur: float
    cantidad_mediana_btc: float
    rtt_compra_s: float
    rtt_venta_s: float
    bruto_mediano_bps: float
    bruto_p99_bps: float
    minimo: int = MIN_SEGUNDOS

    @property
    def episodios_hora(self) -> float:
        return self.n_episodios / (self.segundos_validos / 3600) if self.segundos_validos > 0 else math.nan

    @property
    def estado(self) -> str:
        if self.segundos_validos < self.minimo:
            return INSUFICIENTE
        if self.n_episodios == 0:
            return SIN_OPORTUNIDADES
        return INALCANZABLES if self.n_alcanzables == 0 else ALCANZABLES

    def conclusion(self) -> str:
        todos = self.compra == TODOS
        if todos:
            cabecera = f"Arbitraje entre todas las rutas ({self.escenario})"
        else:
            cabecera = (f"Arbitraje {self.compra} → {self.venta} ({self.escenario}; comisiones "
                        f"{self.comision_compra:.2%} + {self.comision_venta:.2%})")
        if self.estado == INSUFICIENTE:
            return (f"{cabecera}: datos insuficientes ({self.segundos_validos:.0f} s con los dos libros vivos; hacen "
                    f"falta {self.minimo}).")
        horas = self.segundos_validos / 3600
        if self.estado == SIN_OPORTUNIDADES:
            texto = f"{cabecera}: ningún episodio con ventaja neta positiva en {horas:.1f} h."
            if not todos:
                coste = (self.comision_compra + self.comision_venta) * 1e4
                texto += (f" Ventaja bruta mediana {self.bruto_mediano_bps:+.2f} bps y p99 {self.bruto_p99_bps:+.2f} "
                          f"bps (ponderadas por tiempo), frente a unos {coste:.0f} bps de comisiones por ida y vuelta.")
            return texto
        rtt = max(self.rtt_compra_s, self.rtt_venta_s)
        texto = (f"{cabecera}: {self.n_episodios} episodios en {horas:.1f} h ({self.episodios_hora:.1f} por hora), "
                 f"{self.frac_tiempo_positivo:.3%} del tiempo con ventaja neta positiva. Duración mediana "
                 f"{self.duracion_mediana_s:.3f} s (p90 {self.duracion_p90_s:.3f} s, máxima {self.duracion_max_s:.3f} s"
                 f"{f', {self.n_censurados} censurado(s)' if self.n_censurados else ''}); ventaja neta máxima "
                 f"{self.max_neto_bps:+.2f} bps. Beneficio teórico {self.beneficio_total_eur:.2f} € (mediana "
                 f"{self.beneficio_mediano_eur:.2f} € por episodio, {self.cantidad_mediana_btc:.4f} BTC); alcanzable "
                 f"{self.beneficio_alcanzable_eur:.2f} € en {self.n_alcanzables} episodio(s) que duran al menos el RTT")
        texto += (f" ({rtt * 1e3:.0f} ms)." if math.isfinite(rtt) else " de sus dos patas.")
        if todos:
            texto += (" Exige inventario por adelantado en cada exchange (EUR donde se compra, BTC donde se vende); "
                      "reequilibrarlo con transferencias no se modela y reduce el beneficio.")
        else:
            texto += (f" Exige tener EUR en {self.compra} y BTC en {self.venta} por adelantado; reequilibrar el "
                      "inventario (transferencias, sus comisiones y su espera) no se modela y reduce el beneficio.")
        texto += (" Quien está más cerca del exchange ve cada episodio antes que nosotros: lo alcanzable es una cota "
                  "optimista.")
        return texto

    def a_fila(self) -> dict:
        return {"estudio": "arbitraje", **asdict(self), "episodios_hora": self.episodios_hora,
                "estado": self.estado, "conclusion": self.conclusion()}


def _resumir(escenario, compra, venta, fc, fv, serie, eps, desde, rtt_c, rtt_v, minimo) -> ResumenArbitraje:
    validos = serie[serie["valido"]]
    segundos = float(validos["duracion_s"].sum())
    hasta = pd.Timestamp(int(validos["t_ns"].iloc[-1]), tz="UTC") if len(validos) else pd.NaT
    positivo = float(eps["duracion_s"].sum()) if len(eps) else 0.0
    return ResumenArbitraje(
        escenario, compra, venta, fc, fv, desde, hasta, segundos, len(eps),
        int(eps["alcanzable"].sum()) if len(eps) else 0, int(eps["censurado"].sum()) if len(eps) else 0,
        positivo / segundos if segundos > 0 else math.nan, _cuantil(eps["duracion_s"], 0.5),
        _cuantil(eps["duracion_s"], 0.9), float(eps["duracion_s"].max()) if len(eps) else math.nan,
        float(eps["max_neto_bps"].max()) if len(eps) else math.nan, _cuantil(eps["beneficio_eur"], 0.5),
        _cuantil(eps["beneficio_eur"], 0.9), float(eps["beneficio_eur"].sum()) if len(eps) else 0.0,
        float(eps.loc[eps["alcanzable"].astype(bool), "beneficio_eur"].sum()) if len(eps) else 0.0,
        _cuantil(eps["cantidad_btc"], 0.5), rtt_c, rtt_v,
        _cuantil(validos["bruto_bps"], 0.5, validos["duracion_s"]),
        _cuantil(validos["bruto_bps"], 0.99, validos["duracion_s"]), minimo)


def _resumir_todos(escenario, resumenes, eps, desde, minimo) -> ResumenArbitraje:
    """Todas las rutas a la vez: episodios y beneficios sumados; el tiempo positivo es la unión de los episodios
    de todas las rutas sobre el tiempo de la ruta con más tiempo válido."""
    segundos = max((r.segundos_validos for r in resumenes), default=0.0)
    hasta = max((r.hasta_utc for r in resumenes if pd.notna(r.hasta_utc)), default=pd.NaT)
    positivo = _union_s(zip(eps["inicio_ns"], eps["fin_ns"])) if len(eps) else 0.0
    vacio = len(eps) == 0
    return ResumenArbitraje(
        escenario, TODOS, TODOS, math.nan, math.nan, desde, hasta, segundos, len(eps),
        0 if vacio else int(eps["alcanzable"].sum()), 0 if vacio else int(eps["censurado"].sum()),
        positivo / segundos if segundos > 0 else math.nan, _cuantil(eps["duracion_s"], 0.5),
        _cuantil(eps["duracion_s"], 0.9), math.nan if vacio else float(eps["duracion_s"].max()),
        math.nan if vacio else float(eps["max_neto_bps"].max()), _cuantil(eps["beneficio_eur"], 0.5),
        _cuantil(eps["beneficio_eur"], 0.9), 0.0 if vacio else float(eps["beneficio_eur"].sum()),
        0.0 if vacio else float(eps.loc[eps["alcanzable"].astype(bool), "beneficio_eur"].sum()),
        _cuantil(eps["cantidad_btc"], 0.5), math.nan, math.nan, math.nan, math.nan, minimo)


# --- tamaño con los libros de cada segundo --------------------------------------------------------------------------

def _fotos(consultar: Callable[[str], pd.DataFrame], desde_utc, hasta_utc) -> dict:
    """{exchange: fotos de `libros_flujo` en la ventana, con recibido_ns}; vacío si no hay `libros_flujo`."""
    if "libros_flujo" not in set(consultar("SELECT table_name FROM information_schema.tables")["table_name"]):
        return {}
    filtro = []
    if desde_utc is not None:
        filtro.append(f"recibido_utc >= TIMESTAMPTZ '{pd.Timestamp(desde_utc).isoformat()}'")
    if hasta_utc is not None:
        filtro.append(f"recibido_utc <= TIMESTAMPTZ '{pd.Timestamp(hasta_utc).isoformat()}'")
    donde = f" WHERE {' AND '.join(filtro)}" if filtro else ""
    df = consultar("SELECT exchange, par, solicitado_utc, recibido_utc, hora_exchange_utc, bid_precios, "
                   f"bid_cantidades, ask_precios, ask_cantidades FROM libros_flujo{donde} ORDER BY recibido_utc")
    df["recibido_ns"] = _ns(df["recibido_utc"])
    return {ex: g.reset_index(drop=True) for ex, g in df.groupby("exchange")}


def _tamano_en_fotos(fotos_c: pd.DataFrame, fotos_v: pd.DataFrame, inicio_ns: int, fin_ns: int, censurado: bool,
                     fc: float, fv: float) -> Arbitraje | None:
    """El mejor barrido entre las fotos tomadas dentro del episodio (cada foto de la compra con la de la venta más
    cercana, a menos de `TOLERANCIA_FOTOS_S`, también dentro)."""
    def dentro(f):
        t = f["recibido_ns"].to_numpy(np.int64)
        return f[(t >= inicio_ns) & ((t <= fin_ns) if censurado else (t < fin_ns))]
    c, v = dentro(fotos_c), dentro(fotos_v)
    if c.empty or v.empty:
        return None
    pares = pd.merge_asof(c.sort_values("recibido_ns"), v.sort_values("recibido_ns"), on="recibido_ns",
                          direction="nearest", tolerance=int(TOLERANCIA_FOTOS_S * NS), suffixes=("_c", "_v"))
    mejor = None
    for fila in pares.dropna(subset=["exchange_v"]).to_dict("records"):
        lados = [{k.removesuffix(s): fila[k] for k in fila if k.endswith(s)} for s in ("_c", "_v")]
        try:
            libro_c, libro_v = (Libro.desde_fila(lado) for lado in lados)
        except ValueError:  # una foto que no valida (lado vacío, cruzada) no se usa
            continue
        r = tamano_ejecutable(libro_c, libro_v, fc, fv)
        if mejor is None or r.beneficio_eur > mejor.beneficio_eur:
            mejor = r
    return mejor


def _anotar(eps: pd.DataFrame, fotos_c, fotos_v, fc, fv, rtt_c, rtt_v) -> pd.DataFrame:
    cantidades, beneficios, fuentes = [], [], []
    for e in eps.to_dict("records"):
        r = None
        if fotos_c is not None and fotos_v is not None:
            r = _tamano_en_fotos(fotos_c, fotos_v, e["inicio_ns"], e["fin_ns"], e["censurado"], fc, fv)
        if r is not None and r.beneficio_eur > 0:
            cantidades.append(r.cantidad_btc), beneficios.append(r.beneficio_eur), fuentes.append("libros_flujo")
        else:
            cantidades.append(e["cantidad_tope_btc"]), beneficios.append(e["beneficio_tope_eur"])
            fuentes.append("mejor nivel")
    return eps.assign(cantidad_btc=cantidades, beneficio_eur=beneficios, fuente_tamano=fuentes,
                      alcanzable=alcanzable(eps["duracion_s"].to_numpy(float), rtt_c, rtt_v) if len(eps) else [],
                      inicio_utc=pd.to_datetime(eps["inicio_ns"].astype("int64"), utc=True),
                      fin_utc=pd.to_datetime(eps["fin_ns"].astype("int64"), utc=True))


# --- estudio --------------------------------------------------------------------------------------------------------

def estudiar_arbitraje(consultar: Callable[[str], pd.DataFrame], desde_utc=None, hasta_utc=None, rtt_s=None,
                       escenarios=ESCENARIOS, max_silencio_s: float = MAX_SILENCIO_S, minimo: int = MIN_SEGUNDOS
                       ) -> tuple[list[ResumenArbitraje], pd.DataFrame]:
    """(resúmenes por escenario y ruta, más uno de todas las rutas por escenario; episodios). Los mejores niveles se
    reconstruyen desde `eventos_libro` (empezando en el snapshot anterior a `desde_utc`); el tamaño, con
    `libros_flujo`. `rtt_s`: {exchange: RTT en s}; si falta, se mide con `relojes.medir_relojes` en la ventana."""
    mejores = {ex: mejores_desde_eventos(ev, **PARAMETROS_LIBRO.get(ex, {}))
               for ex, ev in eventos_flujo(consultar, desde_utc, hasta_utc)}
    if rtt_s is None:
        rtt_s = rtt_desde_relojes(medir_relojes(consultar, desde_utc, hasta_utc))
    fotos = _fotos(consultar, desde_utc, hasta_utc)
    desde_ns = None if desde_utc is None else pd.Timestamp(desde_utc).value
    desde = pd.Timestamp(desde_utc) if desde_utc is not None else pd.NaT
    resumenes, todos_eps = [], []
    for escenario in escenarios:
        del_escenario, eps_escenario = [], []
        for compra, venta in itertools.permutations(sorted(mejores), 2):
            fc, fv = comisiones(escenario, compra, venta)
            serie = serie_par(mejores[compra], mejores[venta], fc, fv, max_silencio_s, desde_ns)
            if pd.isna(desde) and len(serie):
                desde = pd.Timestamp(int(serie["t_ns"].iloc[0]), tz="UTC")
            rtt_c, rtt_v = float(rtt_s.get(compra, math.nan)), float(rtt_s.get(venta, math.nan))
            eps = _anotar(episodios(serie), fotos.get(compra), fotos.get(venta), fc, fv, rtt_c, rtt_v)
            eps = eps.assign(escenario=escenario, compra=compra, venta=venta)
            del_escenario.append(_resumir(escenario, compra, venta, fc, fv, serie, eps, desde, rtt_c, rtt_v, minimo))
            eps_escenario.append(eps)
        juntos = (pd.concat([e for e in eps_escenario if len(e)], ignore_index=True)
                  if any(len(e) for e in eps_escenario) else pd.DataFrame(columns=COLUMNAS_EPISODIO))
        resumenes += del_escenario + [_resumir_todos(escenario, del_escenario, juntos, desde, minimo)]
        todos_eps.append(juntos)
    no_vacios = [e for e in todos_eps if len(e)]
    episodios_df = (pd.concat(no_vacios, ignore_index=True)[COLUMNAS_EPISODIO] if no_vacios
                    else pd.DataFrame(columns=COLUMNAS_EPISODIO))
    return resumenes, episodios_df


def guardar_arbitraje(resultados, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda una ejecución en `estudios_arbitraje`; `hasta_utc` dice hasta dónde llegaban los datos."""
    return almacen.guardar([{"metodo": METODO, "ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc,
                             **r.a_fila()} for r in resultados], FUENTE_ARBITRAJE)
