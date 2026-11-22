"""Velas OHLCV propias a partir de los trades del websocket (Fase 4).

Conceptos:
- Vela OHLCV de [inicio, inicio + Δ): apertura (primer precio), máximo, mínimo, cierre (último precio) y volumen
  (Σ cantidad, en BTC) de los trades de ese intervalo. `inicio_utc` está alineado al reloj: es un múltiplo de Δ
  desde 1970-01-01 UTC. Una vela solo se conoce al CERRAR su intervalo (docs/conceptos/series_temporales.md).
- Volumen monetario: Σ precio · cantidad (euros negociados). VWAP de la vela: Σ precio · cantidad / Σ cantidad,
  el precio medio pagado por BTC.
- Hora de la vela: la hora del EXCHANGE (`hora_exchange_utc`), no la de recepción. Es la hora del suceso, la misma
  que usa el histórico oficial de Kraken (así las dos fuentes son comparables vela a vela) y no depende de nuestra
  latencia. Nuestro reloj va unas décimas de segundo por detrás del de los exchanges y deriva (`relojes.py`): con
  la hora de recepción, los trades cercanos a un borde cambiarían de vela según el retraso de cada mensaje.
- Vela vacía: ningún trade en el intervalo. Apertura, máximo, mínimo, cierre y VWAP son NaN y el volumen 0: no se
  inventa precio (rellenar con el último cierre crea retornos 0 falsos y baja la volatilidad).
- Cobertura de la captura: la captura guarda una foto del libro cada segundo (`libros_flujo`). Ese latido dice
  cuándo estábamos escuchando; un silencio de trades con latido es un mercado tranquilo, sin latido es un hueco de
  captura. Dos latidos separados más de `UMBRAL_HUECO_S` abren un hueco; cada tramo cubierto se recorta
  `MARGEN_RELOJ_S` por cada lado porque el latido va en nuestro reloj y las velas en el del exchange. Sin
  `libros_flujo` se usa el propio flujo de trades, con un umbral más largo (`UMBRAL_HUECO_TRADES_S`). Un error
  del websocket (`errores_captura` con `origen` = "flujo": desconexión, desincronización) puede perder trades sin
  dejar rastro: se descuenta ± `MARGEN_RELOJ_S` alrededor de él.
- Vela completa: terminó y la captura cubrió su intervalo, salvo como mucho `TOLERANCIA_HUECO` de él. La tolerancia
  existe porque la captura se reinicia cada hora y pierde unos 11-18 s: exigir el 100 % dejaría incompletas todas
  las velas de una hora y de un día. Con el 1 % los reinicios no tocan las velas horarias (12 s son el 0,3 %),
  pero sí las de 1 y 5 minutos que los contienen. `cobertura` guarda la fracción cubierta exacta.
- Velas de frontera: la primera y la última de los datos, y las que rodean un hueco, no están completas: su
  intervalo empezó antes de la captura o terminó después. Se conservan (con `completa` = False), pero no dan
  retornos (`retornos.py`).
- Idempotencia: el lake solo añade ficheros. Recalcular escribe solo las velas nuevas o que cambiaron, con un
  `recibido_utc` nuevo; `leer_velas` devuelve, por (fuente, exchange, par, intervalo_s, inicio_utc), la de cálculo
  más reciente. Volver a ejecutar sin datos nuevos no escribe nada.
- Trades repetidos: al reconectar, un exchange puede reenviar trades; se cuentan una vez por (exchange, trade_id).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from radar.configuracion import PAR

FUENTE_VELAS = "velas"
FUENTE_PROPIA = "propia"
INTERVALOS_S = (60, 300, 3600, 86400)
UMBRAL_HUECO_S = 5.0            # latidos cada 1 s; el percentil 99,9 de su separación es ~1,5 s
UMBRAL_HUECO_TRADES_S = 600.0   # sin latidos: un silencio de trades de 10 min se toma por hueco de captura
MARGEN_RELOJ_S = 2.0            # desfase y latencia entre nuestro reloj y el del exchange (décimas de segundo)
TOLERANCIA_HUECO = 0.01         # fracción del intervalo que puede faltar sin que la vela deje de estar completa

CLAVE = ["fuente", "exchange", "par", "intervalo_s", "inicio_utc"]
COLUMNAS_VELA = [*CLAVE, "apertura", "maximo", "minimo", "cierre", "volumen_btc", "volumen_eur", "vwap", "n_trades",
                 "vacia", "completa", "recibido_utc"]
_VALORES = ["apertura", "maximo", "minimo", "cierre", "volumen_btc", "volumen_eur", "vwap", "n_trades", "vacia",
            "completa", "cobertura"]
_COLUMNAS_COBERTURA = ["exchange", "desde_utc", "hasta_utc"]


def _segundos(serie) -> np.ndarray:
    """Segundos desde 1970-01-01 UTC (float) de una serie de horas."""
    t = pd.to_datetime(pd.Series(serie), utc=True)
    return ((t - pd.Timestamp(0, tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def _hora(segundos):
    """Inverso de `_segundos`: una hora UTC (o una serie de horas, si recibe un vector)."""
    if np.ndim(segundos):
        return pd.Series(pd.to_datetime(np.asarray(segundos, dtype=float), unit="s", utc=True))
    return pd.Timestamp(float(segundos), unit="s", tz="UTC")


def cobertura_desde_latidos(latidos: pd.DataFrame, umbral_s: float = UMBRAL_HUECO_S, margen_s: float = MARGEN_RELOJ_S,
                            columna: str = "recibido_utc") -> pd.DataFrame:
    """Tramos (exchange, desde_utc, hasta_utc) en los que la captura escuchaba: latidos separados como mucho
    `umbral_s`, recortados `margen_s` por cada lado."""
    filas = []
    for exchange, g in latidos.groupby("exchange", sort=True):
        t = np.sort(_segundos(g[columna]))
        if len(t) == 0:
            continue
        cortes = np.flatnonzero(np.diff(t) > umbral_s)
        inicios, finales = np.r_[t[0], t[cortes + 1]], np.r_[t[cortes], t[-1]]
        for a, b in zip(inicios + margen_s, finales - margen_s):
            if b > a:
                filas.append({"exchange": exchange, "desde_utc": _hora(a), "hasta_utc": _hora(b)})
    return pd.DataFrame(filas, columns=_COLUMNAS_COBERTURA)


def quitar_errores(cobertura: pd.DataFrame, errores: pd.DataFrame | None, margen_s: float = MARGEN_RELOJ_S
                   ) -> pd.DataFrame:
    """Descuenta de la cobertura ± `margen_s` alrededor de cada error del websocket (`origen` = "flujo") de su
    exchange. Los errores de la captura REST (sin `origen`) no dicen nada de los trades y se ignoran."""
    if errores is None or errores.empty or "origen" not in errores.columns:
        return cobertura
    errores = errores[errores["origen"] == "flujo"]
    filas = []
    for _, tramo in cobertura.iterrows():
        piezas = [(tramo.desde_utc.timestamp(), tramo.hasta_utc.timestamp())]
        for t in np.sort(_segundos(errores.loc[errores.exchange == tramo.exchange, "recibido_utc"])):
            nuevas = []
            for a, b in piezas:
                nuevas += [(x, y) for x, y in ((a, min(b, t - margen_s)), (max(a, t + margen_s), b)) if y > x]
            piezas = nuevas
        filas += [{"exchange": tramo.exchange, "desde_utc": _hora(a), "hasta_utc": _hora(b)} for a, b in piezas]
    return pd.DataFrame(filas, columns=_COLUMNAS_COBERTURA)


def _cubierto(inicios: np.ndarray, intervalo_s: float, tramos: pd.DataFrame) -> np.ndarray:
    """Segundos de cada vela [inicio, inicio + Δ) que caen dentro de los tramos cubiertos."""
    if tramos.empty:
        return np.zeros(len(inicios))
    a, b = _segundos(tramos.desde_utc), _segundos(tramos.hasta_utc)
    solape = np.minimum(inicios[:, None] + intervalo_s, b[None, :]) - np.maximum(inicios[:, None], a[None, :])
    return np.clip(solape, 0, None).sum(axis=1)


def construir_velas(trades: pd.DataFrame, intervalo_s: int, cobertura: pd.DataFrame, par: str = PAR,
                    calculado_utc: pd.Timestamp | None = None, ahora: pd.Timestamp | None = None,
                    tolerancia: float = TOLERANCIA_HUECO) -> pd.DataFrame:
    """Velas en el formato común, una por exchange e intervalo, desde la primera hasta la última vela que toca la
    captura o un trade (vacías incluidas).

    `trades`: exchange, hora_exchange_utc, precio, cantidad, trade_id. `cobertura`: tramos de
    `cobertura_desde_latidos` (con `quitar_errores` si hay errores). Una vela que termina después de `ahora`
    todavía no se ha cerrado: no está completa."""
    calculado_utc = calculado_utc if calculado_utc is not None else pd.Timestamp.now(tz="UTC")
    if not trades.empty:
        trades = trades.drop_duplicates(["exchange", "trade_id"]) if "trade_id" in trades.columns else trades
    partes = []
    for exchange in sorted(set(trades.get("exchange", pd.Series(dtype=str))) | set(cobertura.exchange)):
        g = trades[trades.exchange == exchange] if not trades.empty else trades
        tramos = cobertura[cobertura.exchange == exchange]
        t = _segundos(g.hora_exchange_utc) if len(g) else np.array([])
        extremos = np.r_[t, _segundos(tramos.desde_utc), _segundos(tramos.hasta_utc)]
        if len(extremos) == 0:
            continue
        k = np.arange(np.floor(extremos.min() / intervalo_s), np.floor(extremos.max() / intervalo_s) + 1)
        inicios = k * intervalo_s
        velas = pd.DataFrame({"k": k.astype(np.int64)})
        if len(g):
            d = pd.DataFrame({"k": np.floor(t / intervalo_s).astype(np.int64), "t": t,
                              "precio": g.precio.to_numpy(dtype=float), "cantidad": g.cantidad.to_numpy(dtype=float)})
            d = d.sort_values(["k", "t"], kind="stable")
            d["nocional"] = d.precio * d.cantidad
            agregado = d.groupby("k").agg(apertura=("precio", "first"), maximo=("precio", "max"),
                                          minimo=("precio", "min"), cierre=("precio", "last"),
                                          volumen_btc=("cantidad", "sum"), volumen_eur=("nocional", "sum"),
                                          n_trades=("precio", "size"))
            velas = velas.merge(agregado, left_on="k", right_index=True, how="left")
        else:
            for c in ("apertura", "maximo", "minimo", "cierre", "volumen_btc", "volumen_eur", "n_trades"):
                velas[c] = np.nan
        velas["n_trades"] = velas.n_trades.fillna(0).astype(np.int64)
        velas["volumen_btc"] = velas.volumen_btc.fillna(0.0)
        velas["volumen_eur"] = velas.volumen_eur.fillna(0.0)
        velas["vacia"] = velas.n_trades == 0
        velas["vwap"] = np.where(velas.vacia, np.nan, velas.volumen_eur / velas.volumen_btc.where(~velas.vacia, 1.0))
        velas["cobertura"] = _cubierto(inicios, intervalo_s, tramos) / intervalo_s
        terminada = (np.ones(len(velas), dtype=bool) if ahora is None
                     else inicios + intervalo_s <= pd.Timestamp(ahora).timestamp())
        velas["completa"] = terminada & (velas.cobertura >= 1 - tolerancia - 1e-12)
        velas["inicio_utc"] = _hora(inicios)
        velas = velas.assign(fuente=FUENTE_PROPIA, exchange=exchange, par=par, intervalo_s=int(intervalo_s),
                             recibido_utc=calculado_utc)
        partes.append(velas[[*COLUMNAS_VELA, "cobertura"]])
    if not partes:
        return pd.DataFrame(columns=[*COLUMNAS_VELA, "cobertura"])
    return pd.concat(partes, ignore_index=True)


def _literal(ts) -> str:
    return f"TIMESTAMPTZ '{pd.Timestamp(ts).tz_convert('UTC').isoformat()}'"


def leer_velas(consultar: Callable[[str], pd.DataFrame], fuente: str = FUENTE_PROPIA, exchange: str | None = None,
               intervalo_s: int | None = None, desde=None, hasta=None, tabla: str = FUENTE_VELAS) -> pd.DataFrame:
    """Una fila por vela (fuente, exchange, par, intervalo_s, inicio_utc): el cálculo más reciente (`recibido_utc`).
    `desde` ≤ inicio_utc < `hasta`; los filtros a None no se aplican."""
    filtros = [f"fuente = '{fuente}'"]
    if exchange is not None:
        filtros.append(f"exchange = '{exchange}'")
    if intervalo_s is not None:
        filtros.append(f"intervalo_s = {int(intervalo_s)}")
    if desde is not None:
        filtros.append(f"inicio_utc >= {_literal(desde)}")
    if hasta is not None:
        filtros.append(f"inicio_utc < {_literal(hasta)}")
    df = consultar(f"""
        SELECT * FROM {tabla} WHERE {' AND '.join(filtros)}
        QUALIFY row_number() OVER (PARTITION BY {', '.join(CLAVE)} ORDER BY recibido_utc DESC) = 1
        ORDER BY exchange, par, intervalo_s, inicio_utc""")
    return df.drop(columns=["fecha"], errors="ignore").reset_index(drop=True)


def _iguales(a: pd.Series, b: pd.Series) -> np.ndarray:
    if a.dtype == bool or b.dtype == bool or a.dtype == object or b.dtype == object:
        return (a.astype(object) == b.astype(object)).to_numpy()
    x, y = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    return np.isclose(x, y, rtol=1e-12, atol=0, equal_nan=True)


def solo_cambios(velas: pd.DataFrame, existentes: pd.DataFrame) -> pd.DataFrame:
    """Las velas que no están guardadas o cuyo contenido cambió respecto a la última versión guardada."""
    if existentes is None or existentes.empty:
        return velas
    existentes = existentes.copy()
    for c in _VALORES:
        if c not in existentes.columns:
            existentes[c] = np.nan
    velas = velas.reset_index(drop=True)
    unidas = velas.merge(existentes[[*CLAVE, *_VALORES]], on=CLAVE, how="left", suffixes=("", "_antes"),
                         indicator=True)
    cambia = (unidas["_merge"] == "left_only").to_numpy().copy()
    for c in _VALORES:
        cambia |= ~_iguales(unidas[c], unidas[f"{c}_antes"])
    return velas[cambia]


def actualizar_velas(lake, intervalos_s=INTERVALOS_S, horas: float | None = None,
                     ahora: pd.Timestamp | None = None) -> dict:
    """Calcula las velas propias de cada intervalo (de las últimas `horas`, o de todo el lake) y guarda en `velas`
    solo las nuevas o cambiadas. `lake`: un `LakeParquet` (necesita `fuentes`, `consultar` y `guardar`).

    La ventana empieza en un inicio de vela: la primera vela no es de frontera por empezar la ventana, porque la
    cobertura se mide con los latidos de un poco antes."""
    ahora = pd.Timestamp(ahora) if ahora is not None else pd.Timestamp.now(tz="UTC")
    fuentes = lake.fuentes()
    resumen = {"velas": 0, "escritas": 0, "por_intervalo": {}}
    if "trades" not in fuentes:
        return resumen
    desdes = {i: (None if horas is None else
                  _hora(np.floor((ahora.timestamp() - horas * 3600) / i) * i)) for i in intervalos_s}
    primero = min((d for d in desdes.values() if d is not None), default=None)
    previo = "" if primero is None else (
        f" WHERE {{col}} >= {_literal(primero - pd.Timedelta(seconds=UMBRAL_HUECO_S + MARGEN_RELOJ_S))}")
    trades = lake.consultar("SELECT exchange, hora_exchange_utc, precio, cantidad, trade_id FROM trades"
                            + previo.format(col="hora_exchange_utc"))
    if "libros_flujo" in fuentes:
        cobertura = cobertura_desde_latidos(lake.consultar(
            "SELECT exchange, recibido_utc FROM libros_flujo" + previo.format(col="recibido_utc")))
    else:
        cobertura = cobertura_desde_latidos(trades, UMBRAL_HUECO_TRADES_S, columna="hora_exchange_utc")
    if "errores_captura" in fuentes:
        cobertura = quitar_errores(cobertura, lake.consultar("SELECT * FROM errores_captura"))
    todas = []
    for intervalo in intervalos_s:
        velas = construir_velas(trades, intervalo, cobertura, calculado_utc=ahora, ahora=ahora)
        if desdes[intervalo] is not None:
            velas = velas[velas.inicio_utc >= desdes[intervalo]]
        resumen["por_intervalo"][int(intervalo)] = {
            "velas": len(velas), "vacias": int(velas.vacia.sum()), "incompletas": int((~velas.completa).sum())}
        todas.append(velas)
    velas = pd.concat(todas, ignore_index=True)
    resumen["velas"] = len(velas)
    if velas.empty:
        return resumen
    existentes = (leer_velas(lake.consultar, FUENTE_PROPIA, desde=velas.inicio_utc.min())
                  if FUENTE_VELAS in fuentes else None)
    nuevas = solo_cambios(velas, existentes)
    resumen["escritas"] = len(nuevas)
    if len(nuevas):
        lake.guardar(nuevas.to_dict("records"), FUENTE_VELAS)
    return resumen
