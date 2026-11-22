import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.retornos import (AGITACION, AGRUPAMIENTO, CAMBIOS_REGIMEN, COLAS_GRUESAS, FUENTE_RETORNOS,
                                     INSUFICIENTE, SIN_AGRUPAMIENTO, estudiar_retornos, factor_anual,
                                     guardar_estudio_retornos, objetivo_conocido_utc, preparar_retornos,
                                     retorno_futuro)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")


def velas(cierres, intervalo_s=60, completas=None, fuente="propia", exchange="kraken", quitar=()):
    """Velas en el formato común; NaN en `cierres` = vela vacía. `quitar`: posiciones sin fila (hueco)."""
    n = len(cierres)
    completas = [True] * n if completas is None else completas
    filas = []
    for i, (c, ok) in enumerate(zip(cierres, completas)):
        if i in quitar:
            continue
        vacia = c is None or (isinstance(c, float) and math.isnan(c))
        filas.append({"fuente": fuente, "exchange": exchange, "par": "BTC/EUR", "intervalo_s": intervalo_s,
                      "inicio_utc": T0 + pd.Timedelta(seconds=i * intervalo_s), "apertura": np.nan if vacia else c,
                      "maximo": np.nan if vacia else c, "minimo": np.nan if vacia else c,
                      "cierre": np.nan if vacia else c, "volumen_btc": 0.0 if vacia else 1.0,
                      "volumen_eur": 0.0 if vacia else c, "vwap": np.nan if vacia else c,
                      "n_trades": 0 if vacia else 1, "vacia": vacia, "completa": ok, "recibido_utc": T0})
    return pd.DataFrame(filas)


def test_retornos_simple_logaritmico_y_acumulado():
    r = preparar_retornos(velas([100.0, 110.0, 100.0]))
    assert r.ret_simple.tolist()[1:] == pytest.approx([0.10, 100 / 110 - 1])
    assert r.ret_log.tolist()[1:] == pytest.approx([math.log(1.1), math.log(100 / 110)])
    assert math.isnan(r.ret_simple.iloc[0])
    assert r.ret_acumulado.tolist() == pytest.approx([0.0, 0.10, 0.0])   # 100 → 110 → 100: compuesto 0
    assert r.ret_log.sum() == pytest.approx(0.0)


def test_no_hay_retorno_a_traves_de_una_vela_vacia_incompleta_o_un_hueco():
    cierres = [100.0, 101.0, np.nan, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
    completas = [True, True, True, True, True, False, True, True, True]
    r = preparar_retornos(velas(cierres, completas=completas, quitar=(7,)))
    validos = r.dropna(subset=["ret_log"]).inicio_utc
    posiciones = sorted(int((t - T0).total_seconds() // 60) for t in validos)
    # 1 (de 0 a 1) y 4 (de 3 a 4); 2 está vacía, 5 incompleta y 7 no tiene fila: no hay retornos 2, 3, 5, 6, 7 ni 8.
    assert posiciones == [1, 4]
    assert r.segmento.nunique() == 4                    # [0, 1], [3, 4], [6], [8]
    assert r.set_index("inicio_utc").ret_acumulado[T0 + pd.Timedelta(minutes=4)] == pytest.approx(104 / 103 - 1)


def test_anualizacion_24_7():
    assert factor_anual(86400) == pytest.approx(math.sqrt(365))
    assert factor_anual(3600) == pytest.approx(math.sqrt(365 * 24))
    assert factor_anual(60) == pytest.approx(math.sqrt(365 * 1440))


def test_volatilidad_movil_y_realizada_solo_dentro_del_segmento():
    cierres = [100.0, 101.0, 100.0, 102.0, np.nan, 100.0, 101.0, 102.0, 103.0]
    r = preparar_retornos(velas(cierres), ventana=3)
    ultimos = np.log([101 / 100, 100 / 101, 102 / 100])
    fila = r.set_index("inicio_utc").loc[T0 + pd.Timedelta(minutes=3)]
    assert fila.vol_movil == pytest.approx(np.std(ultimos, ddof=1))
    assert fila.vol_realizada == pytest.approx(math.sqrt(np.sum(ultimos ** 2)))
    # Tras la vela vacía hacen falta 3 retornos nuevos: en la posición 7 solo hay 2.
    assert math.isnan(r.set_index("inicio_utc").vol_movil[T0 + pd.Timedelta(minutes=7)])
    assert not math.isnan(r.set_index("inicio_utc").vol_movil[T0 + pd.Timedelta(minutes=8)])


def test_retorno_futuro_sin_mirar_el_futuro():
    rng = np.random.default_rng(1)
    cierres = list(100 * np.exp(np.cumsum(rng.normal(0, 1e-3, 60))))
    r = preparar_retornos(velas(cierres), ventana=5)
    futuro = retorno_futuro(r, 3)
    assert futuro.iloc[10] == pytest.approx(math.log(cierres[13] / cierres[10]))
    assert futuro.iloc[-3:].isna().all()                # no hay vela t + 3
    assert (objetivo_conocido_utc(r, 3).iloc[10] == T0 + pd.Timedelta(minutes=14))   # cierre de la vela 13

    # Cambiar los precios posteriores a t cambia el objetivo, pero no la señal (retornos y volatilidad) en t.
    alterados = cierres[:11] + [c * 1.05 for c in cierres[11:]]
    r2 = preparar_retornos(velas(alterados), ventana=5)
    columnas = ["ret_simple", "ret_log", "ret_acumulado", "vol_movil", "vol_realizada"]
    pd.testing.assert_frame_equal(r[columnas].iloc[:11], r2[columnas].iloc[:11])
    assert retorno_futuro(r2, 3).iloc[10] != pytest.approx(futuro.iloc[10])


def test_retorno_futuro_no_cruza_huecos():
    r = preparar_retornos(velas([100.0, 101.0, np.nan, 103.0, 104.0]))
    futuro = retorno_futuro(r, 1)
    assert futuro.notna().tolist() == [True, False, False, True, False]


def _garch(n, semilla=0, omega=1e-7, alfa=0.15, beta=0.8):
    rng = np.random.default_rng(semilla)
    r, var = np.zeros(n), omega / (1 - alfa - beta)
    for i in range(n):
        r[i] = math.sqrt(var) * rng.standard_t(5) / math.sqrt(5 / 3)
        var = omega + alfa * r[i] ** 2 + beta * var
    return 50_000 * np.exp(np.cumsum(r))


def test_estudio_detecta_agrupamiento_y_colas_gruesas_en_un_garch():
    (res,) = estudiar_retornos(velas(list(_garch(3000)), intervalo_s=3600))
    assert res.estado_agrupamiento == AGRUPAMIENTO
    assert res.estado_colas == COLAS_GRUESAS
    assert res.vol_anual == pytest.approx(res.vol_por_vela * math.sqrt(365 * 24))
    fila = res.a_fila()
    assert fila["hasta_utc"] == T0 + pd.Timedelta(hours=3000)
    assert "agrupamiento" in res.conclusion() and fila["conclusion"] == res.conclusion()


def test_estudio_sin_agrupamiento_en_ruido_independiente():
    rng = np.random.default_rng(3)
    cierres = list(50_000 * np.exp(np.cumsum(rng.normal(0, 1e-3, 3000))))
    (res,) = estudiar_retornos(velas(cierres))
    assert res.estado_agrupamiento == SIN_AGRUPAMIENTO
    assert res.estado_colas != COLAS_GRUESAS


def test_estudio_detecta_cambio_de_regimen():
    rng = np.random.default_rng(4)
    r = np.r_[rng.normal(0, 1e-3, 1000), rng.normal(0, 4e-3, 300), rng.normal(0, 1e-3, 700)]
    (res,) = estudiar_retornos(velas(list(50_000 * np.exp(np.cumsum(r)))))
    assert res.estado_regimen == CAMBIOS_REGIMEN
    assert res.fraccion_agitacion > 0.1
    assert res.regimen_actual != AGITACION


def test_estudio_con_pocos_datos():
    (res,) = estudiar_retornos(velas([100.0, 101.0, 102.0, 101.0]))
    assert res.estado == INSUFICIENTE
    assert res.estado_agrupamiento == INSUFICIENTE and res.estado_regimen == INSUFICIENTE
    assert "datos insuficientes" in res.conclusion()


def test_estudio_por_fuente_exchange_e_intervalo_y_guardado(tmp_path):
    datos = pd.concat([velas([100.0, 101.0, 102.0]), velas([100.0, 99.0], fuente="kraken_historico"),
                       velas([1.0, 2.0], intervalo_s=3600)], ignore_index=True)
    resultados = estudiar_retornos(datos)
    assert [(r.fuente, r.intervalo_s) for r in resultados] == [("kraken_historico", 60), ("propia", 60),
                                                             ("propia", 3600)]
    lake = LakeParquet(tmp_path)
    guardar_estudio_retornos(resultados, lake, T0)
    guardado = lake.consultar(f"SELECT * FROM {FUENTE_RETORNOS}")
    assert len(guardado) == 3 and set(guardado.estado) == {INSUFICIENTE}
