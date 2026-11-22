import math

import pandas as pd

from radar.almacen import LakeParquet
from radar.analisis.registro import (NO_SOBREVIVE, SIN_HALLAZGO, SOBREVIVE, guardar_registro, registrar_pruebas,
                                     resumen_registro)

T1 = pd.Timestamp("2026-11-20 10:00", tz="UTC")
T2 = pd.Timestamp("2026-11-21 10:00", tz="UTC")


def fila(ejecutado=T1, **campos):
    return {"ejecutado_utc": ejecutado, "recibido_utc": ejecutado, **campos}


def imbalance(p, estado, ejecutado=T1, banda=5.0, horizonte=10, exchange="kraken"):
    return fila(ejecutado, estudio="imbalance_retorno", metodo="imbalance_retorno/v3", exchange=exchange,
                banda_bps=banda, horizonte_rondas=horizonte, precio_referencia="mid", t_descubrimiento=3.0,
                p_descubrimiento=p, p_ajustado=p, estado=estado, desde_utc=T1 - pd.Timedelta(days=3),
                hasta_utc=T1)


def lead_lag(p, retardo):
    return fila(lider="binance", seguidor="kraken", retardo_rondas=retardo, t_descubrimiento=0.5,
                p_descubrimiento=p, p_ajustado=p, estado="sin evidencia")


def por_hipotesis(pruebas):
    return {(p.fuente, p.exchange, p.parametros): p for p in pruebas}


def test_la_correccion_global_cambia_que_hallazgos_sobreviven(tmp_path):
    lake = LakeParquet(tmp_path)
    # Dentro de su estudio (una sola prueba) p = 0,01 es "confirmada"; con 20 pruebas más en otro estudio, no.
    lake.guardar([imbalance(0.01, "confirmada"), imbalance(1e-6, "confirmada", banda=10.0)], "estudios")
    lake.guardar([lead_lag(0.5, r) for r in range(1, 21)], "estudios_lead_lag")
    pruebas = registrar_pruebas(lake.consultar, lake.fuentes())
    assert len(pruebas) == 22 and {p.familia for p in pruebas} == {22}
    debil = next(p for p in pruebas if p.p_valor == 0.01)
    fuerte = next(p for p in pruebas if p.p_valor == 1e-6)
    assert debil.p_ajustado_estudio < 0.05 and debil.p_bh > 0.05 and debil.estado == NO_SOBREVIVE
    assert fuerte.estado == SOBREVIVE and fuerte.p_bh < 0.05
    assert math.isclose(debil.p_bh, 0.01 * 22 / 2)                   # BH: p · m / rango
    assert math.isclose(debil.p_bonferroni, 0.22) and math.isclose(debil.p_holm, 0.01 * 21)
    assert all(p.estado == SIN_HALLAZGO for p in pruebas if p.fuente == "estudios_lead_lag")
    assert "binance->kraken" in {p.exchange for p in pruebas}
    assert "retardo_rondas=1" in por_hipotesis(pruebas)[("estudios_lead_lag", "binance->kraken",
                                                         "retardo_rondas=1")].parametros
    texto = resumen_registro(pruebas)
    assert "22 pruebas" in texto and "1 de 2" in texto and "no sobreviven" in texto
    assert "kraken" in debil.conclusion() and NO_SOBREVIVE in debil.conclusion()


def test_p_valor_bilateral_derivado_del_t_cuando_no_se_guardo(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([fila(estudio="ofi_impacto", exchange="kraken", niveles=5, t_hac=3.0, estado="explica el precio")],
                 "estudios_ofi")
    lake.guardar([fila(estudio="markout", exchange="kraken", horizonte_s=5, media_bps=0.4, error_bps=0.1,
                       estado="los takers aciertan (selección adversa para el maker)")], "estudios_markouts")
    pruebas = por_hipotesis(registrar_pruebas(lake.consultar, lake.fuentes()))
    ofi = pruebas[("estudios_ofi", "kraken", "niveles=5")]
    assert ofi.p_derivado and ofi.estadistico == "t_hac" and math.isclose(ofi.p_valor, math.erfc(3 / math.sqrt(2)))
    markout = pruebas[("estudios_markouts", "kraken", "horizonte_s=5")]
    assert markout.p_derivado and math.isclose(markout.valor, 4.0) and markout.hallazgo


def test_por_defecto_cada_hipotesis_cuenta_una_vez_con_su_ultima_ejecucion(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([imbalance(0.01, "confirmada", T1)], "estudios")
    lake.guardar([imbalance(0.30, "sin evidencia", T2)], "estudios")
    ultimas = registrar_pruebas(lake.consultar, lake.fuentes())
    assert len(ultimas) == 1 and ultimas[0].p_valor == 0.30 and ultimas[0].ejecutado_utc == T2
    todas = registrar_pruebas(lake.consultar, lake.fuentes(), todas_las_ejecuciones=True)
    assert len(todas) == 2 and {p.familia for p in todas} == {2}


def test_tolera_fuentes_ausentes_columnas_ausentes_y_excluye_lo_que_no_es_descubrimiento(tmp_path):
    lake = LakeParquet(tmp_path)
    assert registrar_pruebas(lake.consultar, lake.fuentes()) == []
    assert "no hay pruebas" in resumen_registro([]).lower()
    # Decaimiento guardado sin t: no hay estadístico; un estudio nuevo con columnas desconocidas sí entra.
    lake.guardar([fila(estudio="decaimiento", exchange="kraken", senal="ofi", estado="con efecto")], "estudios_senales")
    lake.guardar([fila(exchange="kraken", retardo_ms=250, t=2.5, estado="confirmada", columna_rara="x")],
                 "estudios_hayashi_yoshida")
    lake.guardar([fila(exchange="kraken", banda_bps=5.0, horizonte_rondas=10, t=3.0, estado="se mantiene")],
                 "revalidaciones")
    lake.guardar([fila(exchange="kraken", t=9.0, estado="robusta")], "estudios_robustez")
    lake.guardar([fila(exchange="kraken", variable="spread_bps", p_valor=0.001, estado="depende de la hora")],
                 "perfiles_horarios")
    pruebas = por_hipotesis(registrar_pruebas(lake.consultar, lake.fuentes()))
    # retardo_ms es un resultado de Hayashi-Yoshida (el adelanto medido), no un parámetro de la hipótesis.
    assert set(pruebas) == {("estudios_hayashi_yoshida", "kraken", ""),
                            ("perfiles_horarios", "kraken", "variable=spread_bps")}
    assert pruebas[("perfiles_horarios", "kraken", "variable=spread_bps")].p_derivado is False


def test_guarda_el_registro_con_su_ejecucion(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([imbalance(0.01, "confirmada")], "estudios")
    pruebas = registrar_pruebas(lake.consultar, lake.fuentes())
    ahora = pd.Timestamp("2026-11-22 12:00", tz="UTC")
    guardar_registro(pruebas, LakeParquet(tmp_path / "salida"), ahora)
    guardado = LakeParquet(tmp_path / "salida").consultar("SELECT * FROM registro_pruebas")
    assert len(guardado) == 1 and guardado.estado[0] == SOBREVIVE
    assert {"ejecutado_utc", "ejecutado_estudio_utc", "p_bh", "p_holm", "p_bonferroni", "conclusion"} <= set(guardado)


def test_las_pruebas_de_hayashi_yoshida_entran_en_la_familia(tmp_path):
    """El p de HY se guarda como `p_sustitutos`; cada par y base es una hipótesis distinta, con líder o sin él."""
    lake = LakeParquet(tmp_path)
    comun = {"estudio": "hayashi_yoshida", "ejecutado_utc": T1, "recibido_utc": T1, "exchange_a": "bitvavo",
             "exchange_b": "kraken"}
    lake.guardar([{**comun, "base": "recepcion", "lider": None, "seguidor": None, "p_sustitutos": 0.30,
                   "estado": "simultáneo"},
                  {**comun, "base": "exchange", "lider": "bitvavo", "seguidor": "kraken", "p_sustitutos": 0.005,
                   "estado": "confirmada"}], "estudios_hayashi_yoshida")
    pruebas = registrar_pruebas(lake.consultar, lake.fuentes())
    assert len(pruebas) == 2 and {p.p_valor for p in pruebas} == {0.30, 0.005}
    assert all("retardo_ms" not in p.parametros for p in pruebas)  # el adelanto medido es un resultado, no un parámetro
    assert sum(p.hallazgo for p in pruebas) == 1
    assert all("bitvavo" in p.exchange and "kraken" in p.exchange for p in pruebas)


def test_una_lambda_de_kyle_significativa_cuenta_como_hallazgo(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([fila(exchange="kraken", intervalo_s=5, t=9.9, estado="impacto significativo"),
                  fila(exchange="okx", intervalo_s=5, t=0.5, estado="sin evidencia")], "estudios_liquidez")
    pruebas = {p.exchange: p for p in registrar_pruebas(lake.consultar, lake.fuentes())}
    assert pruebas["kraken"].hallazgo and not pruebas["okx"].hallazgo


def test_cada_intervalo_de_la_lambda_es_una_hipotesis_distinta(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar([fila(exchange="kraken", intervalo_s=5, t=9.9, estado="impacto significativo"),
                  fila(exchange="kraken", intervalo_s=60, t=2.0, estado="impacto significativo")], "estudios_liquidez")
    assert len(registrar_pruebas(lake.consultar, lake.fuentes())) == 2


def test_los_estudios_de_la_fase_3_entran_completos_en_la_familia(tmp_path):
    """Presión guarda varias pruebas por exchange e intervalo (medida y relación); VWAP y la respuesta de Bouchaud
    tienen sus propios estados de hallazgo, y la respuesta guarda su t como `t_r1`."""
    lake = LakeParquet(tmp_path)
    relacion = [fila(estudio="presion_relacion", exchange="kraken", intervalo_s=1, medida=m, relacion=r, t=3.0,
                     estado="confirmada") for m in ("volumen", "numero") for r in ("contemporanea", "predictiva")]
    vwap = [fila(estudio="presion_vwap", exchange="okx", intervalo_s=1, t=6.0, estado="el lado neto paga sobre el mid")]
    lake.guardar(relacion + vwap, "estudios_presion")
    lake.guardar([fila(estudio="respuesta_precio", exchange="bitvavo", t_r1=8.0, estado="impacto mixto")],
                 "estudios_respuesta")
    pruebas = registrar_pruebas(lake.consultar, lake.fuentes())
    por_estudio = {}
    for p in pruebas:
        por_estudio.setdefault(p.estudio, []).append(p)
    assert len(por_estudio["presion_relacion"]) == 4
    assert por_estudio["presion_vwap"][0].hallazgo and por_estudio["respuesta_precio"][0].hallazgo
