import math

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from radar.almacen import LakeParquet
from radar.analisis import prediccion as pr
from radar.analisis.prediccion import (CONFIRMADA, CONFIRMADA_GUARDADA, FIN_DESARROLLO, FUENTE_APERTURAS,
                                       FUENTE_PREDICCION, MuestraGuardadaYaAbierta, abrir_muestra_guardada,
                                       calcular_senales, estudiar_prediccion, estudiar_prediccion_lake,
                                       guardar_estudio_prediccion, huella_familia, ic_hac, objetivo,
                                       objetivo_conocido, operar, particiones_purgadas)
from radar.analisis.registro import registrar_pruebas
from radar.analisis.retornos import preparar_retornos

FUENTE = "kraken_historico"
DIA = 86400
T0 = pd.Timestamp("2026-01-01", tz="UTC")


def velas(cierres, intervalo_s=DIA, inicio=T0, fuente=FUENTE, exchange="kraken", quitar=()):
    """Velas en el formato común, todas completas; `quitar`: posiciones sin fila (hueco)."""
    filas = []
    for i, c in enumerate(cierres):
        if i in quitar:
            continue
        filas.append({"fuente": fuente, "exchange": exchange, "par": "BTC/EUR", "intervalo_s": intervalo_s,
                      "inicio_utc": inicio + pd.Timedelta(seconds=i * intervalo_s), "apertura": c, "maximo": c,
                      "minimo": c, "cierre": c, "volumen_btc": 1.0, "volumen_eur": c, "vwap": c, "n_trades": 1,
                      "vacia": False, "completa": True, "recibido_utc": T0})
    return pd.DataFrame(filas)


def precios_momentum(n, semilla=7, fuerza=0.8, sigma=0.02):
    """Retornos con momentum real: r_t = fuerza · media(r_{t−5..t−1}) + ε."""
    rng = np.random.default_rng(semilla)
    r = np.zeros(n)
    e = rng.normal(0, sigma, n)
    for t in range(n):
        r[t] = fuerza * r[max(0, t - 5):t].mean() + e[t] if t else e[t]
    return 10000 * np.exp(np.cumsum(r))


def paseo(n, semilla=3, sigma=0.02):
    rng = np.random.default_rng(semilla)
    return 10000 * np.exp(np.cumsum(rng.normal(0, sigma, n)))


# --- Señales y objetivo -----------------------------------------------------------------------------------


def test_las_senales_solo_usan_el_pasado():
    precios = paseo(400)
    base = calcular_senales(preparar_retornos(velas(precios)))
    alterados = precios.copy()
    alterados[251:] *= np.linspace(1.5, 0.5, len(alterados[251:]))   # cambia todo el futuro de la vela 250
    otra = calcular_senales(preparar_retornos(velas(alterados)))
    assert list(base.columns) == list(otra.columns) and len(base.columns) == len(pr.SENALES)
    pd.testing.assert_frame_equal(base.iloc[:251], otra.iloc[:251])
    assert not base.iloc[251:].equals(otra.iloc[251:])


def test_senales_de_momentum_y_reversion_a_mano():
    precios = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
    s = calcular_senales(preparar_retornos(velas(precios)), senales=(("momentum", 2, None), ("reversion_z", 3, None),
                                                                     ("reversion_corta", 1, None),
                                                                     ("cruce_medias", 2, 3)))
    assert s["momentum_2"].iloc[2] == pytest.approx(math.log(104 / 100))
    assert math.isnan(s["momentum_2"].iloc[1])                           # hacen falta 3 cierres
    assert s["reversion_z_3"].iloc[2] == pytest.approx(-1.0)              # (104 − 102) / 2 = +1 → señal −1
    assert s["reversion_corta_1"].iloc[1] == pytest.approx(-math.log(102 / 100))
    assert s["cruce_medias_2_3"].iloc[2] == pytest.approx(math.log(103 / 102))


def test_las_senales_no_cruzan_un_hueco():
    s = calcular_senales(preparar_retornos(velas([100.0, 101, 102, 103, 104, 105], quitar=(2,))),
                         senales=(("momentum", 2, None),))
    # tras el hueco (posición 2) el segmento vuelve a empezar: 3, 4 no tienen 3 cierres; 5 sí (3, 4, 5).
    assert s["momentum_2"].isna().tolist() == [True, True, True, True, True, False]


def test_objetivo_entra_en_t_mas_1_nunca_en_t():
    precios = [100.0, 110.0, 132.0, 100.0, 90.0, 95.0]
    r = preparar_retornos(velas(precios))
    o1, o2 = objetivo(r, 1), objetivo(r, 2)
    assert o1.iloc[0] == pytest.approx(math.log(132 / 110))     # entra al cierre de t + 1, sale en t + 2
    assert o2.iloc[0] == pytest.approx(math.log(100 / 110))
    assert o1.iloc[0] != pytest.approx(math.log(110 / 100))     # nunca el retorno de t a t + 1
    assert o1.iloc[3:].isna().tolist() == [False, True, True]
    assert objetivo_conocido(r, 1).iloc[0] == T0 + pd.Timedelta(days=3)   # al cerrar la vela t + 2


def test_el_objetivo_no_cruza_un_hueco():
    r = preparar_retornos(velas([100.0, 101, 102, 103, 104], quitar=(2,)))
    assert objetivo(r, 1).isna().tolist() == [True, True, True, True, True]   # 0 → 1 → 2 cruza el hueco


# --- Separación cronológica con purga ---------------------------------------------------------------------


def test_la_purga_quita_los_objetivos_de_entrenamiento_que_se_solapan_con_la_prueba():
    observado = pd.Series(T0 + pd.to_timedelta(np.arange(100), unit="h"))
    conocido = observado + pd.Timedelta(hours=6)                  # objetivo de 5 velas entrando en t + 1
    particiones = particiones_purgadas(observado, conocido, tramos=5, embargo=pd.Timedelta(0))
    assert len(particiones) == 4
    entrena, prueba = particiones[0]
    assert prueba.tolist() == list(range(20, 40))
    assert entrena.tolist() == list(range(0, 15))                  # 15..19 terminan después de que empiece la prueba
    for entrena, prueba in particiones:
        assert (conocido.iloc[entrena] <= observado.iloc[prueba[0]]).all()
        assert entrena.max() < prueba.min()
    con_embargo = particiones_purgadas(observado, conocido, tramos=5, embargo=pd.Timedelta(hours=2))
    assert con_embargo[0][0].tolist() == list(range(0, 13))


# --- IC con errores HAC -----------------------------------------------------------------------------------


def test_ic_y_hac_con_un_efecto_conocido_y_sin_efecto():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(size=5000))
    y = 0.2 * x + pd.Series(rng.normal(size=5000))       # correlación teórica 0,2 / √1,04 ≈ 0,196
    ic, t = ic_hac(x, y, horizonte=1)
    assert ic == pytest.approx(0.196, abs=0.04) and t > 8
    ic_r, t_r = ic_hac(x, y, horizonte=1, rangos=True)
    assert ic_r == pytest.approx(0.19, abs=0.04) and t_r > 8
    _, t0 = ic_hac(x, pd.Series(rng.normal(size=5000)), horizonte=1)
    assert abs(t0) < 3


def test_hac_ensancha_el_error_con_objetivos_solapados():
    rng = np.random.default_rng(2)
    ruido_x, ruido_y = rng.normal(size=6020), rng.normal(size=6020)
    x = pd.Series(ruido_x).rolling(20).mean().iloc[20:].reset_index(drop=True)        # señal persistente
    y = pd.Series(ruido_y).rolling(20).sum().shift(-19).iloc[20:].reset_index(drop=True)   # objetivos solapados
    d = pd.DataFrame({"x": x, "y": y}).dropna()
    ingenuo = d.x.corr(d.y) * math.sqrt(len(d))
    _, t_hac = ic_hac(d.x, d.y, horizonte=20)
    assert abs(t_hac) < abs(ingenuo) / 2


# --- Retorno neto y coste de equilibrio -------------------------------------------------------------------


def test_retorno_neto_rotacion_y_equilibrio():
    op = operar([1, 1, 0, 1], [0.01, 0.02, 0.0, -0.01])
    assert op.bruto == pytest.approx(0.02)
    assert op.lados == 4                            # entra, sale, entra, sale al final
    assert op.neto(0.004) == pytest.approx(0.02 - 4 * 0.004)
    assert op.equilibrio_bps == pytest.approx(50.0)  # 0,02 / 4 lados
    assert op.exposicion == pytest.approx(0.75)
    corto = operar([1, -1], [0.01, -0.02])
    assert corto.bruto == pytest.approx(0.03) and corto.lados == 4   # 0 → 1 → −1 → 0
    total = op + corto
    assert total.periodos == 6 and total.lados == 8 and total.bruto == pytest.approx(0.05)


# --- Estudio de desarrollo --------------------------------------------------------------------------------


def _desarrollo(n=2000, precios=None):
    inicio = FIN_DESARROLLO - pd.Timedelta(days=n)
    return velas(precios_momentum(n) if precios is None else precios, inicio=inicio)


def test_bh_y_bonferroni_sobre_toda_la_familia_declarada():
    resultados = estudiar_prediccion(_desarrollo(precios=paseo(2000)))
    assert len(resultados) == len(pr.SENALES) * len(pr.HORIZONTES)
    p = [r.p_valor for r in resultados]
    assert all(np.isfinite(p))
    assert [r.p_bh for r in resultados] == pytest.approx(list(multipletests(p, method="fdr_bh")[1]))
    assert [r.p_bonferroni for r in resultados] == pytest.approx([min(1.0, x * len(p)) for x in p])
    assert {r.familia for r in resultados} == {len(p)}
    assert all(r.muestra == "desarrollo" for r in resultados)


def test_un_momentum_real_se_confirma_y_la_conclusion_da_los_costes():
    resultados = estudiar_prediccion(_desarrollo())
    momentum = next(r for r in resultados if r.senal == "momentum" and r.ventana_velas == 5 and r.horizonte_velas == 1)
    assert momentum.estado == CONFIRMADA
    assert momentum.direccion == 1 and momentum.ic_spearman > 0 and momentum.tramos_a_favor >= 3
    texto = momentum.conclusion()
    assert "confirmada" in texto and "80" in texto and "40" in texto
    fila = momentum.a_fila()
    assert fila["p_descubrimiento"] == momentum.p_valor and fila["t_hac"] == momentum.t_spearman
    assert fila["hasta_utc"] <= FIN_DESARROLLO
    assert fila["neto_taker_largo"] == pytest.approx(fila["bruto_largo"] - 0.008 * fila["lados_largo"])
    assert fila["neto_maker_largo"] == pytest.approx(fila["bruto_largo"] - 0.004 * fila["lados_largo"])
    assert fila["periodos_mantener"] == fila["periodos_largo"] and "comprar y mantener" in texto.lower()


def test_el_desarrollo_rechaza_velas_de_la_muestra_guardada():
    v = velas(paseo(50), inicio=FIN_DESARROLLO - pd.Timedelta(days=10))
    with pytest.raises(ValueError, match="muestra guardada"):
        estudiar_prediccion(v)


def test_el_desarrollo_nunca_lee_velas_desde_2025(tmp_path):
    n = 2400
    precios = paseo(n)
    inicio = FIN_DESARROLLO - pd.Timedelta(days=2000)
    lake = LakeParquet(tmp_path)
    lake.guardar(velas(precios, inicio=inicio).to_dict("records"), "velas")
    consultas = []

    def espia(sql):
        consultas.append(sql)
        return lake.consultar(sql)

    a = estudiar_prediccion_lake(espia, fuente=FUENTE, intervalos=(DIA,))
    assert consultas and all("inicio_utc < TIMESTAMPTZ '2025-01-01T00:00:00+00:00'" in c for c in consultas)
    otro = LakeParquet(tmp_path / "otro")
    alterados = precios.copy()
    alterados[2000:] *= 3.0                                         # solo cambian las velas de 2025 en adelante
    otro.guardar(velas(alterados, inicio=inicio).to_dict("records"), "velas")
    b = estudiar_prediccion_lake(otro.consultar, fuente=FUENTE, intervalos=(DIA,))
    assert [x.a_fila() for x in a] == [x.a_fila() for x in b]
    assert max(x.hasta_utc for x in a) <= FIN_DESARROLLO


def test_el_registro_reconoce_las_pruebas_de_desarrollo_y_no_las_de_la_muestra_guardada(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(_desarrollo().to_dict("records"), "velas")
    ahora = pd.Timestamp("2026-11-22", tz="UTC")
    resultados = estudiar_prediccion_lake(lake.consultar, fuente=FUENTE, intervalos=(DIA,))
    guardar_estudio_prediccion(resultados, lake, ahora)
    pruebas = [p for p in registrar_pruebas(lake.consultar, lake.fuentes()) if p.fuente == FUENTE_PREDICCION]
    assert len(pruebas) == len(resultados)                          # una hipótesis distinta por fila
    assert any("senal=momentum" in p.parametros and "ventana_velas=5" in p.parametros
               and "horizonte_velas=1" in p.parametros and "intervalo_s=86400" in p.parametros for p in pruebas)
    assert any(p.hallazgo for p in pruebas)


# --- Muestra guardada (bajo llave) ------------------------------------------------------------------------


def _lake_con_desarrollo(tmp_path):
    lake = LakeParquet(tmp_path)
    n = 2365                                                        # 2000 días de desarrollo + 365 de 2025
    lake.guardar(velas(precios_momentum(n), inicio=FIN_DESARROLLO - pd.Timedelta(days=2000)).to_dict("records"),
                 "velas")
    return lake


def test_la_muestra_guardada_se_abre_una_sola_vez_y_registra_la_apertura(tmp_path):
    lake = _lake_con_desarrollo(tmp_path)
    ahora = pd.Timestamp("2026-11-22", tz="UTC")
    with pytest.raises(ValueError, match="desarrollo"):            # sin desarrollo guardado no se abre
        abrir_muestra_guardada(lake, ahora, fuente=FUENTE, intervalos=(DIA,))
    desarrollo = estudiar_prediccion_lake(lake.consultar, fuente=FUENTE, intervalos=(DIA,))
    guardar_estudio_prediccion(desarrollo, lake, ahora)
    supervivientes = [r for r in desarrollo if r.estado == CONFIRMADA]
    assert supervivientes

    guardada = abrir_muestra_guardada(lake, ahora, fuente=FUENTE, intervalos=(DIA,))
    assert len(guardada) == len(supervivientes)
    assert all(r.muestra == "guardada" and r.desde_utc >= FIN_DESARROLLO for r in guardada)
    momentum = next(r for r in guardada if r.senal == "momentum" and r.ventana_velas == 5 and r.horizonte_velas == 1)
    assert momentum.estado == CONFIRMADA_GUARDADA
    aperturas = lake.consultar(f"SELECT * FROM {FUENTE_APERTURAS}")
    assert len(aperturas) == 1
    assert aperturas.familia_hash.iloc[0] == huella_familia(FUENTE, (DIA,))
    assert aperturas.n_senales.iloc[0] == len(supervivientes)
    guardadas = lake.consultar(f"SELECT * FROM {FUENTE_PREDICCION} WHERE muestra = 'guardada'")
    assert len(guardadas) == len(guardada) and "p_descubrimiento" not in guardadas.dropna(axis=1, how="all").columns

    with pytest.raises(MuestraGuardadaYaAbierta):
        abrir_muestra_guardada(lake, ahora + pd.Timedelta(days=1), fuente=FUENTE, intervalos=(DIA,))
    assert len(lake.consultar(f"SELECT * FROM {FUENTE_APERTURAS}")) == 1
    pruebas = [p for p in registrar_pruebas(lake.consultar, lake.fuentes()) if p.fuente == FUENTE_PREDICCION]
    assert len(pruebas) == len(desarrollo)                          # la muestra guardada no entra como descubrimiento


def test_la_apertura_se_registra_antes_de_calcular(tmp_path, monkeypatch):
    lake = _lake_con_desarrollo(tmp_path)
    ahora = pd.Timestamp("2026-11-22", tz="UTC")
    guardar_estudio_prediccion(estudiar_prediccion_lake(lake.consultar, fuente=FUENTE, intervalos=(DIA,)), lake, ahora)

    def falla(*args, **kwargs):
        raise RuntimeError("fallo al leer la muestra guardada")

    monkeypatch.setattr(pr, "leer_velas", falla)
    with pytest.raises(RuntimeError, match="fallo al leer"):
        abrir_muestra_guardada(lake, ahora, fuente=FUENTE, intervalos=(DIA,))
    assert len(lake.consultar(f"SELECT * FROM {FUENTE_APERTURAS}")) == 1   # la apertura ya consta: no se repite
    monkeypatch.undo()
    with pytest.raises(MuestraGuardadaYaAbierta):
        abrir_muestra_guardada(lake, ahora, fuente=FUENTE, intervalos=(DIA,))


def test_la_huella_cambia_con_la_familia_declarada():
    assert huella_familia(FUENTE, (DIA,)) == huella_familia(FUENTE, (DIA,))
    assert huella_familia(FUENTE, (DIA,)) != huella_familia(FUENTE, (DIA, 3600))
    assert huella_familia(FUENTE, (DIA,)) != huella_familia(FUENTE, (DIA,), horizontes=(1, 5))


def test_solo_pasan_a_la_muestra_guardada_las_que_tambien_son_rentables(tmp_path):
    """Filtro económico: confirmada, neto con comisión maker positivo y mayor que comprar y mantener."""
    from radar.analisis.prediccion import supervivientes_desarrollo
    from radar.almacen import LakeParquet
    t = pd.Timestamp("2026-11-22", tz="UTC")
    base = {"familia_hash": "h", "muestra": "desarrollo", "ejecutado_utc": t, "recibido_utc": t,
            "estado": "confirmada", "bruto_mantener": 0.5}
    filas = [{**base, "senal": "rentable", "neto_maker_largo": 0.8, "neto_maker_largo_corto": 0.1},
             {**base, "senal": "no_gana_a_mantener", "neto_maker_largo": 0.3, "neto_maker_largo_corto": 0.2},
             {**base, "senal": "pierde", "neto_maker_largo": -0.1, "neto_maker_largo_corto": -0.2,
              "bruto_mantener": -0.5},
             {**base, "senal": "sin_evidencia", "estado": "sin evidencia", "neto_maker_largo": 2.0,
              "neto_maker_largo_corto": 2.0}]
    lake = LakeParquet(tmp_path)
    lake.guardar(filas, "estudios_prediccion")
    assert list(supervivientes_desarrollo(lake.consultar, lake.fuentes(), "h")["senal"]) == ["rentable"]
