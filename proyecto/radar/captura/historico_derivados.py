"""Histórico público de perpetuos BTC (OKX BTC-USDT-SWAP y Kraken Futures PF_XBTUSD) guardado en el lake (Fase 7).

Conceptos:
- Ubicación: el adaptador (`captura/exchanges/derivados.py`) habla con los exchanges y traduce sus formatos (sus
  endpoints, límites y profundidad están verificados en su docstring); este caso de uso decide qué pedir, lo pasa a
  filas comunes y lo guarda (puerto `guardar`/`consultar`). Igual que `historico_kraken.py`.
- Fuentes nuevas del lake, una fila por clave; al leer gana la de `recibido_utc` más reciente:
  - `derivados_funding`: un pago de funding por (exchange, instrumento, periodo_fin_utc). `tasa` es la tasa
    liquidada por periodo (fracción del nominal; positiva: los largos pagan a los cortos), `periodo_h` su duración
    (8 h en OKX, 1 h en Kraken) y `tasa_absoluta` el pago en USD por contrato de 1 BTC (solo Kraken).
  - `derivados_precios`: velas horarias por (exchange, instrumento, tipo, intervalo_s, inicio_utc), con `tipo` ∈
    {mark, indice, perp}. Mark: precio con el que el exchange valora posiciones y liquida. Índice: media de precios
    spot de varios mercados, la referencia del subyacente (no es negociable). Perp: el precio negociado.
  - `derivados_oi`: open interest al cierre de cada hora, en BTC (y contratos; en USD solo OKX).
  - `derivados_liquidaciones`: OKX da órdenes sueltas (intervalo_s = 0, lado long/short de la posición liquidada,
    precio de quiebra, cantidad en BTC; varias órdenes idénticas en el mismo milisegundo se suman en `n_ordenes`);
    Kraken da el volumen liquidado por hora sin lado (intervalo_s = 3600, lado = "total").
- Idempotencia: antes de guardar se compara con la última versión de cada clave y solo se escriben filas nuevas o
  con algún valor distinto (una vela que estaba abierta y ya cerró, un OI de la hora en curso que cambió). Repetir
  la descarga no escribe nada.
- Profundidad (cada endpoint llega hasta donde llega): OKX funding 3 meses, OI horario 60 días, liquidaciones ~1
  día, velas años; Kraken funding 1 año, velas, OI y liquidaciones desde 2022. Con `dias` se pide desde hace N días.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from .exchanges import derivados as dv

FUENTE_FUNDING = "derivados_funding"
FUENTE_PRECIOS = "derivados_precios"
FUENTE_OI = "derivados_oi"
FUENTE_LIQUIDACIONES = "derivados_liquidaciones"
INSTRUMENTOS = {"okx": dv.OKX_SWAP, "kraken": dv.KRAKEN_PERP}
CLAVES = {FUENTE_FUNDING: ["exchange", "instrumento", "periodo_fin_utc"],
          FUENTE_PRECIOS: ["exchange", "instrumento", "tipo", "intervalo_s", "inicio_utc"],
          FUENTE_OI: ["exchange", "instrumento", "intervalo_s", "inicio_utc"],
          FUENTE_LIQUIDACIONES: ["exchange", "instrumento", "intervalo_s", "inicio_utc", "lado", "precio"]}
VALORES = {FUENTE_FUNDING: ["periodo_h", "tasa", "tasa_prevista", "tasa_absoluta"],
           FUENTE_PRECIOS: ["apertura", "maximo", "minimo", "cierre", "volumen", "completa"],
           FUENTE_OI: ["oi_contratos", "oi_btc", "oi_usd"],
           FUENTE_LIQUIDACIONES: ["cantidad_btc", "n_ordenes"]}
DIAS = 365
TOLERANCIA_RELATIVA = 1e-12


def _tiempos(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for col in d.columns:
        if col.endswith("_utc"):
            d[col] = pd.to_datetime(d[col], utc=True).astype("datetime64[ns, UTC]")
    return d


def leer_ultimas(consultar: Callable[[str], pd.DataFrame], fuente: str, donde: str = "") -> pd.DataFrame:
    """Última versión (mayor `recibido_utc`) de cada clave de `fuente`; vacío si la fuente aún no existe."""
    filtro = f"WHERE {donde}" if donde else ""
    try:
        d = consultar(f"SELECT * FROM {fuente} {filtro} QUALIFY row_number() OVER "
                      f"(PARTITION BY {', '.join(CLAVES[fuente])} ORDER BY recibido_utc DESC) = 1")
    except Exception as error:
        if fuente in str(error).lower():
            return pd.DataFrame(columns=[*CLAVES[fuente], *VALORES[fuente], "recibido_utc"])
        raise
    return _tiempos(d.drop(columns=[c for c in ("fecha",) if c in d.columns]))


def _clave_comparable(df: pd.DataFrame, clave: list) -> pd.DataFrame:
    d = df.copy()
    for c in clave:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].fillna(-1.0)       # el precio de un total de Kraken es NaN: así casa consigo mismo
        elif c == "intervalo_s":
            d[c] = d[c].astype("int64")
        elif not c.endswith("_utc"):
            d[c] = d[c].astype(str)
    return d


def _distintos(a: pd.Series, b: pd.Series) -> np.ndarray:
    if a.dtype == bool or b.dtype == bool or a.dtype == object or b.dtype == object:
        return ~a.astype(object).eq(b.astype(object)).to_numpy()
    x, y = a.astype(float).to_numpy(), b.astype(float).to_numpy()
    iguales = np.isclose(x, y, rtol=TOLERANCIA_RELATIVA, atol=0.0) | (np.isnan(x) & np.isnan(y))
    return ~iguales


def guardar_filas(almacen, filas: pd.DataFrame, fuente: str) -> int:
    """Escribe en `fuente` solo las filas nuevas o con algún valor distinto de su última versión."""
    if filas.empty:
        return 0
    clave, valores = CLAVES[fuente], VALORES[fuente]
    nuevas = _tiempos(filas)
    exchanges = ", ".join(f"'{e}'" for e in sorted(nuevas["exchange"].unique()))
    guardadas = leer_ultimas(almacen.consultar, fuente, f"exchange IN ({exchanges})")
    if len(guardadas):
        a, g = _clave_comparable(nuevas, clave), _clave_comparable(guardadas[clave + valores], clave)
        unidas = a.merge(g, on=clave, how="left", suffixes=("", "_g"), indicator=True)
        cambia = np.array(unidas["_merge"].eq("left_only"), dtype=bool)
        for col in valores:
            cambia |= _distintos(unidas[col], unidas[f"{col}_g"])
        nuevas = nuevas[cambia]
    if nuevas.empty:
        return 0
    almacen.guardar(nuevas.to_dict("records"), fuente)
    return len(nuevas)


# --- Filas comunes --------------------------------------------------------------------------------------------------

def filas_funding(funding: pd.DataFrame, recibido_utc) -> pd.DataFrame:
    return funding.assign(recibido_utc=pd.Timestamp(recibido_utc))[[*CLAVES[FUENTE_FUNDING],
                                                                     *VALORES[FUENTE_FUNDING], "recibido_utc"]]


def filas_precios(velas: pd.DataFrame, exchange: str, instrumento: str, tipo: str, intervalo_s: int,
                  recibido_utc) -> pd.DataFrame:
    v = velas.copy()
    v["exchange"], v["instrumento"], v["tipo"], v["intervalo_s"] = exchange, instrumento, tipo, int(intervalo_s)
    v["completa"] = v["completa"].astype(bool)
    v["recibido_utc"] = pd.Timestamp(recibido_utc)
    return v[[*CLAVES[FUENTE_PRECIOS], *VALORES[FUENTE_PRECIOS], "recibido_utc"]]


def filas_oi(oi: pd.DataFrame, exchange: str, instrumento: str, recibido_utc) -> pd.DataFrame:
    if "valor" in oi.columns:      # Kraken: contratos de 1 BTC, sin nominal en USD
        oi = pd.DataFrame({"inicio_utc": oi["inicio_utc"], "oi_contratos": oi["valor"], "oi_btc": oi["valor"],
                           "oi_usd": np.nan})
    d = oi.assign(exchange=exchange, instrumento=instrumento, intervalo_s=dv.HORA_S,
                  recibido_utc=pd.Timestamp(recibido_utc))
    return d[[*CLAVES[FUENTE_OI], *VALORES[FUENTE_OI], "recibido_utc"]]


def filas_liquidaciones(liq: pd.DataFrame, exchange: str, instrumento: str, recibido_utc) -> pd.DataFrame:
    if "valor" in liq.columns:     # Kraken: volumen por hora, sin lado
        d = pd.DataFrame({"inicio_utc": liq["inicio_utc"], "intervalo_s": dv.HORA_S, "lado": "total",
                          "precio": np.nan, "cantidad_btc": liq["valor"], "n_ordenes": np.nan})
    else:                          # OKX: órdenes sueltas; idénticas en el mismo ms se suman
        g = liq.groupby(["hora_utc", "lado", "precio"], as_index=False).agg(
            cantidad_btc=("cantidad_btc", "sum"), n_ordenes=("cantidad_btc", "size"))
        d = g.rename(columns={"hora_utc": "inicio_utc"}).assign(intervalo_s=0)
        d["n_ordenes"] = d["n_ordenes"].astype(float)
    d = d.assign(exchange=exchange, instrumento=instrumento, recibido_utc=pd.Timestamp(recibido_utc))
    return d[[*CLAVES[FUENTE_LIQUIDACIONES], *VALORES[FUENTE_LIQUIDACIONES], "recibido_utc"]]


def guardar_descarga(almacen, exchange: str, datos: dict, recibido_utc) -> dict:
    """Guarda una descarga (`dv.leer_okx`/`dv.leer_kraken`) de forma idempotente; filas escritas por fuente."""
    inst = INSTRUMENTOS[exchange]
    precios = [filas_precios(v, exchange, inst, tipo, dv.HORA_S, recibido_utc)
               for tipo, v in datos.get("precios", {}).items() if len(v)]
    return {FUENTE_FUNDING: guardar_filas(almacen, filas_funding(datos["funding"], recibido_utc), FUENTE_FUNDING)
            if len(datos.get("funding", [])) else 0,
            FUENTE_PRECIOS: guardar_filas(almacen, pd.concat(precios, ignore_index=True), FUENTE_PRECIOS)
            if precios else 0,
            FUENTE_OI: guardar_filas(almacen, filas_oi(datos["oi"], exchange, inst, recibido_utc), FUENTE_OI)
            if len(datos.get("oi", [])) else 0,
            FUENTE_LIQUIDACIONES: guardar_filas(almacen, filas_liquidaciones(datos["liquidaciones"], exchange, inst,
                                                                             recibido_utc), FUENTE_LIQUIDACIONES)
            if len(datos.get("liquidaciones", [])) else 0}


def _cobertura(df: pd.DataFrame, columna: str) -> dict:
    if df is None or len(df) == 0:
        return {"n": 0, "desde_utc": None, "hasta_utc": None}
    return {"n": len(df), "desde_utc": df[columna].min(), "hasta_utc": df[columna].max()}


def cobertura(datos: dict) -> dict:
    """Filas y tramo de cada pieza descargada (para ver hasta dónde llegó cada endpoint)."""
    liq = datos.get("liquidaciones")
    salida = {"funding": _cobertura(datos.get("funding"), "periodo_fin_utc"),
              "oi": _cobertura(datos.get("oi"), "inicio_utc"),
              "liquidaciones": _cobertura(liq, "hora_utc" if liq is not None and "hora_utc" in liq else "inicio_utc")}
    salida.update({f"precios_{t}": _cobertura(v, "inicio_utc") for t, v in datos.get("precios", {}).items()})
    return salida


def actualizar_derivados(almacen, dias: int = DIAS, ahora_utc=None, lectores: dict | None = None,
                         exchanges=("okx", "kraken")) -> dict:
    """Comando `historico-derivados`: descarga cada exchange desde hace `dias` días y lo guarda (idempotente).

    Si un exchange falla, se anota su error y se sigue con el otro."""
    lectores = dv.LECTORES if lectores is None else lectores
    ahora = pd.Timestamp.now(tz="UTC").floor("s") if ahora_utc is None else pd.Timestamp(ahora_utc)
    desde = (ahora - pd.Timedelta(days=dias)).floor("h")
    resultado = {}
    for exchange in exchanges:
        try:
            datos = lectores[exchange](desde, ahora)
        except Exception as error:     # red, límite o formato: no se guarda nada de ese exchange
            resultado[exchange] = {"error": f"{type(error).__name__}: {error}"}
            continue
        resultado[exchange] = {"escritas": guardar_descarga(almacen, exchange, datos, ahora),
                               "cobertura": cobertura(datos)}
    return resultado


def resumen_derivados(consultar: Callable[[str], pd.DataFrame]) -> list[dict]:
    """Por fuente y exchange: filas (última versión) y tramo guardado."""
    salida = []
    for fuente, tiempo in [(FUENTE_FUNDING, "periodo_fin_utc"), (FUENTE_PRECIOS, "inicio_utc"),
                           (FUENTE_OI, "inicio_utc"), (FUENTE_LIQUIDACIONES, "inicio_utc")]:
        d = leer_ultimas(consultar, fuente)
        for exchange, g in d.groupby("exchange"):
            salida.append({"fuente": fuente, "exchange": exchange, "filas": len(g), "desde_utc": g[tiempo].min(),
                           "hasta_utc": g[tiempo].max()})
    return salida

