"""Histórico largo y continuo de BTC/EUR en Kraken, guardado como velas en el formato común (Fase 4, S2).

Conceptos:
- Ubicación: el adaptador (`captura/exchanges/kraken_historico.py`) solo habla con Kraken y traduce sus formatos;
  este módulo es el caso de uso de captura: decide qué pedir, convierte a la vela común y la guarda en el almacén
  (puerto `guardar`/`consultar`). Igual que `capturador.py` frente a `exchanges/kraken.py`.
- Tres orígenes oficiales, de más largo a más reciente (fuentes verificadas en el docstring del adaptador):
  1. ZIP OHLCVT descargable (`Kraken_OHLCVT_Full.zip.part00`…`04`, historia desde el 10-09-2013 hasta el 30-09-2026
     comprobado para XBTEUR; trimestrales `Kraken_OHLCVT_<AAAA>Q<n>.zip`). Se lee en remoto con peticiones Range
     (solo los CSV de XBTEUR) o desde una copia local. Sin VWAP.
  2. REST OHLC: las 720 últimas barras de cada intervalo (12 h en 1 min, 30 días en 60 min), con VWAP.
  3. REST Trades (opcional, `rellenar_con_trades`): pagina trades desde cualquier fecha; cubre el hueco entre el
     último ZIP y la ventana REST en los intervalos cortos. ~1000 trades por petición a 1 por segundo.
- Vela común (`odd/tasks/fase4-historico.md`): una fila por (fuente, exchange, par, intervalo_s, inicio_utc) con
  apertura, maximo, minimo, cierre (NaN si vacía), volumen_btc, volumen_eur, vwap (NaN si vacía o desconocido),
  n_trades, vacia, completa, recibido_utc. Aquí `fuente` = "kraken_historico" y la hora es la de Kraken.
- Vela vacía: intervalo sin trades. El CSV no la escribe (hay que deducirla: un intervalo que falta entre dos filas
  del mismo fichero); la REST sí, con `count` = 0 y precios de relleno (el cierre anterior), que aquí pasan a NaN.
- Hueco: intervalo sin NINGUNA fila guardada (ni llena ni vacía): fuera de lo que cubrió un origen, p. ej. entre el
  final del último ZIP y el principio de la ventana REST. `huecos` los lista; no se rellenan con supuestos.
- Completa: la vela terminó antes de descargarla (la última barra REST está abierta: completa = False).
- volumen_eur = VWAP · volumen_btc (exacto: VWAP = Σ p·q / Σ q). Sin VWAP (CSV) queda NaN; 0 si la vela está vacía.
- Idempotencia: el lake es append-only y al leer gana la fila con el `recibido_utc` más reciente. Antes de guardar
  se compara con la última versión guardada y solo se escriben velas nuevas o que APORTAN algo (un valor distinto
  o que antes faltaba, o pasar de abierta a completa). Repetir la importación no escribe nada.
- Precedencia ZIP / REST: una vela sin VWAP (CSV) nunca pisa una guardada con VWAP (REST o trades). Hay velas en
  las que discrepan: la diaria del 23-06-2026 tiene 34 729 trades (616,270 BTC) en el ZIP y 34 811 (616,513 BTC)
  en la REST. Sin esta regla, importar ZIP y REST alternaría las dos versiones en cada ejecución. Manda la REST:
  es lo que Kraken sirve hoy y trae VWAP.
"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np
import pandas as pd

from radar.configuracion import PAR

from .exchanges import kraken_historico as kh

FUENTE_VELAS = "velas"
FUENTE = "kraken_historico"
EXCHANGE = "kraken"
CLAVE = ["fuente", "exchange", "par", "intervalo_s", "inicio_utc"]
VALORES = ["apertura", "maximo", "minimo", "cierre", "volumen_btc", "volumen_eur", "vwap", "n_trades", "vacia",
           "completa"]
COLUMNAS = [*CLAVE, *VALORES, "recibido_utc"]
INTERVALOS_ZIP_MIN = (60, 1440)       # 1 min del ZIP completo son 106 MB comprimidos: pedirlo explícitamente
INTERVALOS_REST_MIN = (1, 5, 15, 60, 240, 1440)
TOLERANCIA_RELATIVA = 1e-9            # el CSV suma volúmenes en coma flotante (619.6276025399945)


def _normalizar(barras: pd.DataFrame, intervalo_s: int, recibido_utc: pd.Timestamp) -> pd.DataFrame:
    """Barras (`kh.BARRA`) con n_trades conocido → velas comunes; n_trades = 0 es una vela vacía."""
    v = barras.copy()
    v["vacia"] = v["n_trades"].fillna(0).eq(0) & v["volumen_btc"].fillna(0).eq(0)
    for col in ["apertura", "maximo", "minimo", "cierre", "vwap"]:
        v.loc[v["vacia"], col] = np.nan
    v.loc[v["vwap"] <= 0, "vwap"] = np.nan
    v.loc[v["vacia"], ["volumen_btc", "n_trades"]] = 0.0
    v["volumen_eur"] = np.where(v["vacia"], 0.0, v["vwap"] * v["volumen_btc"])
    recibido = pd.Timestamp(recibido_utc)
    v["completa"] = v["inicio_utc"] + pd.Timedelta(seconds=intervalo_s) <= recibido
    v["fuente"], v["exchange"], v["par"], v["intervalo_s"] = FUENTE, EXCHANGE, PAR, int(intervalo_s)
    v["recibido_utc"] = recibido
    v["n_trades"] = v["n_trades"].astype(float)
    v["vacia"], v["completa"] = v["vacia"].astype(bool), v["completa"].astype(bool)
    return v[COLUMNAS].sort_values("inicio_utc").reset_index(drop=True)


def _rejilla(barras: pd.DataFrame, intervalo_s: int, desde=None, hasta=None) -> pd.DataFrame:
    """Añade como vacías (n_trades = 0, volumen 0) las barras que faltan entre `desde` y `hasta` (incluidos)."""
    paso = pd.Timedelta(seconds=intervalo_s)
    desde = barras["inicio_utc"].min() if desde is None else desde
    hasta = barras["inicio_utc"].max() if hasta is None else hasta
    if pd.isna(desde) or pd.isna(hasta):
        return barras
    todas = pd.date_range(desde, hasta, freq=paso, tz="UTC", name="inicio_utc")
    rellena = barras.set_index("inicio_utc").reindex(todas)
    rellena["n_trades"] = rellena["n_trades"].fillna(0.0)
    rellena["volumen_btc"] = rellena["volumen_btc"].fillna(0.0)
    return rellena.reset_index()


def velas_rest(barras: pd.DataFrame, intervalo_s: int, recibido_utc) -> pd.DataFrame:
    """Barras de `/0/public/OHLC` → velas comunes (vacías con `count` = 0; la última, abierta, no completa)."""
    return _normalizar(barras, intervalo_s, recibido_utc)


def velas_archivo(barras: pd.DataFrame, intervalo_s: int, recibido_utc) -> pd.DataFrame:
    """Barras del CSV OHLCVT → velas comunes; los intervalos ausentes entre la primera y la última fila son vacías."""
    if barras.empty:
        return pd.DataFrame(columns=COLUMNAS)
    return _normalizar(_rejilla(barras, intervalo_s), intervalo_s, recibido_utc)


def velas_trades(trades: pd.DataFrame, intervalo_s: int, desde_utc, hasta_utc, recibido_utc) -> pd.DataFrame:
    """Trades de Kraken (hora del exchange) → velas de [desde, hasta); solo velas enteras dentro del tramo cubierto.

    Las velas que el tramo corta por un extremo no se emiten: les faltarían trades."""
    paso = pd.Timedelta(seconds=intervalo_s)
    primera = pd.Timestamp(desde_utc).ceil(paso)
    ultima = pd.Timestamp(hasta_utc).floor(paso) - paso
    if ultima < primera:
        return pd.DataFrame(columns=COLUMNAS)
    t = trades[(trades["hora_exchange_utc"] >= primera) & (trades["hora_exchange_utc"] < ultima + paso)]
    t = t.sort_values("hora_exchange_utc", kind="stable").assign(
        inicio_utc=lambda d: d["hora_exchange_utc"].dt.floor(paso), nominal=lambda d: d["precio"] * d["cantidad"])
    g = t.groupby("inicio_utc")
    barras = pd.DataFrame({"apertura": g["precio"].first(), "maximo": g["precio"].max(), "minimo": g["precio"].min(),
                           "cierre": g["precio"].last(), "volumen_btc": g["cantidad"].sum(),
                           "n_trades": g["precio"].size().astype(float)})
    barras["vwap"] = g["nominal"].sum() / barras["volumen_btc"]
    barras = _rejilla(barras.reset_index().reindex(columns=kh.BARRA), intervalo_s, primera, ultima)
    return _normalizar(barras, intervalo_s, recibido_utc)


def _ultimas(consultar: Callable[[str], pd.DataFrame], intervalo_s: int, desde, hasta) -> pd.DataFrame:
    """Última versión guardada (mayor `recibido_utc`) de cada vela kraken_historico del intervalo y tramo.

    Usa el mismo lector que las velas propias (`analisis.velas.leer_velas`), para que "gana la más reciente" sea
    una sola regla."""
    from radar.analisis.velas import leer_velas
    try:
        return leer_velas(consultar, FUENTE, EXCHANGE, intervalo_s, desde, pd.Timestamp(hasta) + pd.Timedelta(seconds=1))
    except Exception as error:   # todavía no existe la vista `velas`
        if "velas" in str(error).lower():
            return pd.DataFrame(columns=COLUMNAS)
        raise


def _igual(a: pd.Series, b: pd.Series) -> pd.Series:
    if a.dtype == bool or b.dtype == bool or a.dtype == object or b.dtype == object:
        return a.astype(object).eq(b.astype(object))
    x, y = a.astype(float).to_numpy(), b.astype(float).to_numpy()
    return pd.Series(np.isclose(x, y, rtol=TOLERANCIA_RELATIVA, atol=1e-12) | np.isnan(x), index=a.index)


def nuevas_o_mejores(velas: pd.DataFrame, guardadas: pd.DataFrame) -> pd.DataFrame:
    """Velas que aportan algo frente a la última versión guardada; una vela abierta no pisa una completa."""
    if guardadas.empty or velas.empty:
        return velas
    g = guardadas[CLAVE + VALORES].copy()
    g["inicio_utc"] = pd.to_datetime(g["inicio_utc"], utc=True)
    g["intervalo_s"] = g["intervalo_s"].astype(int)
    unidas = velas.merge(g, on=CLAVE, how="left", suffixes=("", "_g"), indicator=True)
    nueva = unidas["_merge"].eq("left_only")
    aporta = pd.Series(False, index=unidas.index)
    for col in VALORES:
        if col == "completa":
            continue
        guardado = unidas[f"{col}_g"]
        aporta |= ~_igual(unidas[col], guardado) & ~nueva
    aporta |= unidas["completa"] & ~unidas["completa_g"].astype(object).eq(True) & ~nueva
    retrocede = unidas["completa_g"].astype(object).eq(True) & ~unidas["completa"]
    # Una vela sin VWAP (CSV) no pisa una con VWAP (REST o trades): si discrepan, manda la API (ver docstring).
    retrocede |= unidas["vwap"].isna() & pd.to_numeric(unidas["vwap_g"], errors="coerce").notna()
    return velas[(nueva | (aporta & ~retrocede)).to_numpy()]


def guardar_velas(almacen, velas: pd.DataFrame) -> int:
    """Guarda en `velas` solo lo que aporta algo (idempotente). Devuelve el número de filas escritas."""
    escritas = 0
    for intervalo_s, grupo in velas.groupby("intervalo_s"):
        guardadas = _ultimas(almacen.consultar, intervalo_s, grupo["inicio_utc"].min(), grupo["inicio_utc"].max())
        nuevas = nuevas_o_mejores(grupo, guardadas)
        if not nuevas.empty:
            almacen.guardar(nuevas.to_dict("records"), FUENTE_VELAS)
            escritas += len(nuevas)
    return escritas


def huecos(velas: pd.DataFrame, intervalo_s: int) -> pd.DataFrame:
    """Tramos sin ninguna vela guardada entre la primera y la última: desde_utc, hasta_utc (inicio de la vela
    siguiente que sí existe) y n_velas que faltan."""
    paso = pd.Timedelta(seconds=intervalo_s)
    inicios = pd.Series(pd.to_datetime(velas["inicio_utc"], utc=True).drop_duplicates().sort_values().to_numpy())
    salto = inicios.diff()
    i = salto[salto > paso].index
    return pd.DataFrame({"desde_utc": (inicios[i - 1] + paso).to_numpy(), "hasta_utc": inicios[i].to_numpy(),
                         "n_velas": ((salto[i] / paso) - 1).astype(int).to_numpy()})


def _resumen(velas: pd.DataFrame, escritas: int, origen: str) -> dict:
    return {"origen": origen, "intervalo_s": int(velas["intervalo_s"].iloc[0]) if len(velas) else None,
            "velas": len(velas), "escritas": escritas, "vacias": int(velas["vacia"].sum()) if len(velas) else 0,
            "desde_utc": velas["inicio_utc"].min() if len(velas) else None,
            "hasta_utc": velas["inicio_utc"].max() if len(velas) else None}


def importar_zip(almacen, partes=kh.PARTES_COMPLETO, intervalos_min=INTERVALOS_ZIP_MIN, ahora_utc=None,
                 abrir=kh.abrir_zip) -> list[dict]:
    """Importa `XBTEUR_<m>.csv` de un ZIP OHLCVT de Kraken (ruta local, URL o lista de partes)."""
    ahora = pd.Timestamp.now(tz="UTC") if ahora_utc is None else pd.Timestamp(ahora_utc)
    resumen = []
    with abrir(partes) as archivo:
        for m in intervalos_min:
            barras = kh.leer_csv_de_zip(archivo, m)
            if barras is None:
                resumen.append({"origen": "zip", "intervalo_s": m * 60, "velas": 0, "escritas": 0, "vacias": 0,
                                "desde_utc": None, "hasta_utc": None, "aviso": f"el ZIP no trae {kh.nombre_csv(m)}"})
                continue
            velas = velas_archivo(barras, m * 60, ahora)
            resumen.append(_resumen(velas, guardar_velas(almacen, velas), "zip"))
    return resumen


def actualizar_rest(almacen, intervalos_min=INTERVALOS_REST_MIN, ahora_utc=None, leer=kh.leer_ohlc,
                    dormir=None, pausa_s: float = kh.PAUSA_S) -> list[dict]:
    """Últimas 720 barras REST de cada intervalo, guardadas como velas (la abierta, con completa = False)."""
    dormir = time.sleep if dormir is None else dormir
    resumen = []
    for k, m in enumerate(intervalos_min):
        if k:
            dormir(pausa_s)
        barras, _ = leer(m)
        ahora = pd.Timestamp.now(tz="UTC") if ahora_utc is None else pd.Timestamp(ahora_utc)
        velas = velas_rest(barras, m * 60, ahora)
        resumen.append(_resumen(velas, guardar_velas(almacen, velas), "rest"))
    return resumen


def rellenar_con_trades(almacen, desde_utc, hasta_utc, intervalos_min=(1,), ahora_utc=None,
                        paginar=kh.paginar_trades) -> list[dict]:
    """Velas de [desde, hasta) a partir de los trades REST de Kraken (cubre huecos entre el ZIP y la ventana REST).

    Lento: ~1000 trades por petición y una petición por segundo (un día de BTC/EUR, ~20 000-40 000 trades)."""
    trozos = [p for p in paginar(pd.Timestamp(desde_utc), pd.Timestamp(hasta_utc)) if not p.empty]
    trades = pd.concat(trozos, ignore_index=True) if trozos else pd.DataFrame(columns=kh.TRADE)
    if trades.empty:
        return []
    trades["hora_exchange_utc"] = pd.to_datetime(trades["hora_exchange_utc"], utc=True)
    ultimo = trades["hora_exchange_utc"].max()
    # Si la paginación pasó de `hasta`, el tramo está cubierto entero; si no, solo hasta el último trade visto.
    fin = pd.Timestamp(hasta_utc) if ultimo >= pd.Timestamp(hasta_utc) else ultimo
    trades = trades[trades["hora_exchange_utc"] < fin]
    ahora = pd.Timestamp.now(tz="UTC") if ahora_utc is None else pd.Timestamp(ahora_utc)
    resumen = []
    for m in intervalos_min:
        velas = velas_trades(trades, m * 60, desde_utc, fin, ahora)
        resumen.append(_resumen(velas, guardar_velas(almacen, velas), "trades"))
    return resumen


def resumen_historico(consultar: Callable[[str], pd.DataFrame]) -> list[dict]:
    """Por intervalo: velas guardadas, primera y última, vacías y huecos (tramos sin datos)."""
    try:
        velas = consultar(f"SELECT intervalo_s, inicio_utc, vacia FROM {FUENTE_VELAS} WHERE fuente = '{FUENTE}' "
                          f"QUALIFY row_number() OVER (PARTITION BY {', '.join(CLAVE)} ORDER BY recibido_utc DESC) = 1")
    except Exception as error:
        if "velas" in str(error).lower():
            return []
        raise
    salida = []
    for intervalo_s, g in velas.groupby("intervalo_s"):
        h = huecos(g, int(intervalo_s))
        salida.append({"intervalo_s": int(intervalo_s), "velas": len(g), "vacias": int(g["vacia"].sum()),
                       "desde_utc": g["inicio_utc"].min(), "hasta_utc": g["inicio_utc"].max(), "huecos": len(h),
                       "velas_en_huecos": int(h["n_velas"].sum()), "mayor_hueco": h.loc[h["n_velas"].idxmax()].to_dict()
                       if len(h) else None})
    return salida


def actualizar_historico(almacen, partes=kh.PARTES_COMPLETO, intervalos_zip_min=INTERVALOS_ZIP_MIN,
                         intervalos_rest_min=INTERVALOS_REST_MIN, con_zip: bool = True) -> dict:
    """Comando `historico-kraken`: ZIP oficial (si `con_zip`) + REST reciente; devuelve qué se escribió y los huecos."""
    resultado = {"zip": importar_zip(almacen, partes, intervalos_zip_min) if con_zip else [],
                 "rest": actualizar_rest(almacen, intervalos_rest_min)}
    resultado["resumen"] = resumen_historico(almacen.consultar)
    return resultado

