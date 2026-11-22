import pandas as pd

from radar.almacen import LakeParquet
from radar.analisis.robustez import FRAGIL, ROBUSTA, SIN_VECINOS, evaluar_robustez, guardar_robustez

T1 = pd.Timestamp("2026-11-20 10:00", tz="UTC")
T2 = pd.Timestamp("2026-11-21 10:00", tz="UTC")
BANDAS, HORIZONTES = (2.0, 5.0, 10.0), (1, 5, 10)


def rejilla_imbalance(ts: dict, ejecutado=T2, exchange="kraken"):
    """Filas de una ejecución del estudio del imbalance: `ts` = {(banda, horizonte): t}; el (5, 5) es el hallazgo."""
    return [{"ejecutado_utc": ejecutado, "recibido_utc": ejecutado, "estudio": "imbalance_retorno",
             "exchange": exchange, "precio_referencia": "mid", "banda_bps": b, "horizonte_rondas": h,
             "t_descubrimiento": t, "diferencia_descubrimiento": t / 10,
             "estado": "confirmada" if (b, h) == (5.0, 5) else ("confirmada" if abs(t) >= 3 else "sin evidencia")}
            for (b, h), t in ts.items()]


def rejilla(centro, vecinos, resto=0.1):
    ts = {(b, h): resto for b in BANDAS for h in HORIZONTES}
    ts[(5.0, 5)] = centro
    for clave, t in zip([(2.0, 5), (10.0, 5), (5.0, 1), (5.0, 10)], vecinos):
        ts[clave] = t
    return ts


def unico(resultados, **campos):
    elegidos = [r for r in resultados if all(getattr(r, k) == v for k, v in campos.items())]
    assert len(elegidos) == 1, elegidos
    return elegidos[0]


def test_hallazgo_robusto_cuando_los_vecinos_coinciden_en_signo_y_son_significativos(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(rejilla_imbalance(rejilla(4.0, [3.0, 2.5, 3.5, 1.5])), "estudios")
    resultados = evaluar_robustez(lake.consultar, lake.fuentes())
    r = unico(resultados, fuente="estudios", parametros="banda_bps=5, horizonte_rondas=5")
    assert r.contexto == "precio_referencia=mid"
    assert r.estado == ROBUSTA and r.vecinos == 4 and r.vecinos_mismo_signo == 4 and r.vecinos_significativos == 3
    assert not r.seleccion_mejor
    assert "robusta" in r.conclusion() and "3/4" in r.conclusion()


def test_hallazgo_fragil_y_seleccion_del_mejor_parametro(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(rejilla_imbalance(rejilla(4.0, [0.3, -0.5, 0.1, 0.2])), "estudios")
    r = unico(evaluar_robustez(lake.consultar, lake.fuentes()), fuente="estudios")
    assert r.estado == FRAGIL and r.vecinos_significativos == 0 and r.probados == 9
    assert r.es_mejor and r.seleccion_mejor
    assert "selección del mejor parámetro" in r.conclusion()


def test_solo_cuentan_los_vecinos_de_la_misma_ejecucion(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(rejilla_imbalance(rejilla(4.0, [3.0, 3.0, 3.0, 3.0]), ejecutado=T1), "estudios")
    lake.guardar(rejilla_imbalance({(5.0, 5): 4.0}, ejecutado=T2), "estudios")  # la última solo probó (5, 5)
    r = unico(evaluar_robustez(lake.consultar, lake.fuentes()), fuente="estudios")
    assert r.estado == SIN_VECINOS and r.ejecutado_utc == T2 and not r.seleccion_mejor


def test_ofi_lead_lag_y_decaimiento(tmp_path):
    lake = LakeParquet(tmp_path)
    ofi = [{"ejecutado_utc": T1, "recibido_utc": T1, "estudio": "ofi_retorno", "exchange": "kraken", "niveles": n,
            "horizonte_rondas": 1, "t_descubrimiento": t, "estado": "confirmada" if n == 5 else "sin evidencia"}
           for n, t in ((1, 0.2), (5, 3.0), (10, -0.4))]
    lake.guardar(ofi, "estudios_ofi")
    lake.guardar([{"ejecutado_utc": T1, "recibido_utc": T1, "lider": "binance", "seguidor": "kraken",
                   "retardo_rondas": 1, "t_descubrimiento": 5.0, "estado": "confirmada"}], "estudios_lead_lag")
    lake.guardar([{"ejecutado_utc": T1, "recibido_utc": T1, "estudio": "decaimiento", "exchange": "kraken",
                   "senal": "ofi", "estado": "con efecto", "pico_rondas": 5},
                  {"ejecutado_utc": T1, "recibido_utc": T1, "estudio": "decaimiento", "exchange": "okx",
                   "senal": "ofi", "estado": "con efecto", "pico_rondas": 5, "horizontes": [1, 5, 10],
                   "ts": [2.5, 4.0, 3.0]}], "estudios_senales")
    resultados = evaluar_robustez(lake.consultar, lake.fuentes())
    o = unico(resultados, fuente="estudios_ofi")
    assert o.estado == FRAGIL and o.parametros == "niveles=5, horizonte_rondas=1" and o.vecinos == 2
    assert unico(resultados, fuente="estudios_lead_lag").estado == SIN_VECINOS
    sin_curva = unico(resultados, fuente="estudios_senales", exchange="kraken")
    assert sin_curva.estado == SIN_VECINOS and "curva" in sin_curva.conclusion()
    con_curva = unico(resultados, fuente="estudios_senales", exchange="okx")
    assert con_curva.estado == ROBUSTA and con_curva.parametros == "horizonte_rondas=5"
    assert con_curva.contexto == "senal=ofi" and con_curva.vecinos == 2


def test_tolera_lake_vacio_y_columnas_ausentes_y_guarda(tmp_path):
    lake = LakeParquet(tmp_path)
    assert evaluar_robustez(lake.consultar, lake.fuentes()) == []
    lake.guardar([{"ejecutado_utc": T1, "recibido_utc": T1, "lider": "binance", "estado": "confirmada"}],
                 "estudios_lead_lag")  # sin seguidor, retardo ni t: no se puede evaluar, no falla
    assert evaluar_robustez(lake.consultar, lake.fuentes()) == []
    lake.guardar(rejilla_imbalance(rejilla(4.0, [3.0, 2.5, 3.5, 1.5])), "estudios")
    resultados = evaluar_robustez(lake.consultar, lake.fuentes())
    ahora = pd.Timestamp("2026-11-22 12:00", tz="UTC")
    guardar_robustez(resultados, LakeParquet(tmp_path / "salida"), ahora)
    guardado = LakeParquet(tmp_path / "salida").consultar("SELECT * FROM estudios_robustez")
    assert len(guardado) == len(resultados) and {"estado", "seleccion_mejor", "conclusion",
                                                  "ejecutado_estudio_utc"} <= set(guardado)
