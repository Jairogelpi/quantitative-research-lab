import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.protocolo_leadlag import (ESPERANDO, FUENTE_APERTURAS, FUENTE_ESTUDIOS, FUENTE_PROTOCOLOS,
                                              PROTOCOLO_KRAKEN, Protocolo, ProtocoloYaEvaluado,
                                              ProtocoloYaRegistrado, comprobar_desarrollo, decision_economica,
                                              decision_estadistica, estado_protocolo, evaluar_protocolo,
                                              ic_bootstrap_bloques, leer_protocolo, nulo_circular,
                                              r2_fuera_de_muestra, registrar_protocolo, tabla_decisiones)

T0 = pd.Timestamp("2026-11-22 10:00:00", tz="UTC")
REGISTRO = T0 + pd.Timedelta(hours=1)
NS = 1_000_000_000

# Protocolo de prueba: los mismos campos que el real, con mínimos pequeños para capturas sintéticas cortas.
PRUEBA = dataclasses.replace(PROTOCOLO_KRAKEN, min_decisiones=100, min_operaciones=20, umbral_bps=0.5, n_nulos=199,
                             repeticiones_bootstrap=500)


# --- datos sintéticos ---------------------------------------------------------------------------------------


def _libro(exchange, inicio, tiempos_s, mids, medio_spread=0.05, cantidad=1.0):
    """Filas de `eventos_libro`: un snapshot y luego, en cada instante, se borra el nivel anterior y se pone el nuevo."""
    filas, previo = [], None
    for k, (t, m) in enumerate(zip(tiempos_s, mids)):
        recibido = inicio + pd.Timedelta(seconds=float(t))
        tipo = "snapshot" if k == 0 else "update"
        niveles = []
        if previo is not None:
            niveles += [("bid", previo - medio_spread, 0.0), ("ask", previo + medio_spread, 0.0)]
        niveles += [("bid", m - medio_spread, cantidad), ("ask", m + medio_spread, cantidad)]
        filas += [{"exchange": exchange, "recibido_utc": recibido, "hora_exchange_utc": recibido, "tipo": tipo,
                   "lado": lado, "precio": float(p), "cantidad": float(c), "secuencia": float(k)}
                  for lado, p, c in niveles]
        previo = m
    return filas


def _eventos(inicio, duracion_s=1600, retardo_kraken_s=2.0, independiente=False, semilla=7, paso_s=0.5):
    """OKX y Bitvavo siguen un paseo común; Kraken lo sigue con `retardo_kraken_s` (o es otro paseo independiente)."""
    rng = np.random.default_rng(semilla)
    n = int(duracion_s / paso_s)
    extra = int(10 / paso_s)
    comun = 80000 + np.round(np.cumsum(rng.normal(0, 4, n + extra)), 1)
    tiempos = np.arange(n) * paso_s
    lider = comun[extra:]
    if independiente:
        kraken = 80000 + np.round(np.cumsum(rng.normal(0, 4, n)), 1)
    else:
        kraken = comun[extra - int(retardo_kraken_s / paso_s):extra - int(retardo_kraken_s / paso_s) + n]
    filas = []
    for ex, mids in (("okx", lider), ("bitvavo", lider), ("kraken", kraken)):
        filas += _libro(ex, inicio, tiempos + (0.001 if ex != "kraken" else 0.002), mids)
    return filas


def _lake_registrado(tmp_path, protocolo=PRUEBA, **kw):
    lake = LakeParquet(tmp_path)
    huella = registrar_protocolo(lake, protocolo, ahora=REGISTRO)
    lake.guardar(_eventos(REGISTRO + pd.Timedelta(milliseconds=1), **kw), "eventos_libro")
    return lake, huella


def _cotizaciones(*filas):
    """(exchange, segundos desde T0, mid): bid/ask a ±0,05 y 1 BTC en cada lado."""
    return pd.DataFrame([{"exchange": ex, "recibido_ns": int(T0.value + round(s * NS)), "bid": m - 0.05,
                          "ask": m + 0.05, "bid_cantidad": 1.0, "ask_cantidad": 1.0} for ex, s, m in filas])


# --- protocolo y registro -----------------------------------------------------------------------------------


def test_la_huella_es_estable_y_cambia_con_cada_campo():
    assert PROTOCOLO_KRAKEN.huella() == dataclasses.replace(PROTOCOLO_KRAKEN).huella()
    assert Protocolo.desde_texto(PROTOCOLO_KRAKEN.texto()) == PROTOCOLO_KRAKEN
    for campo in dataclasses.fields(Protocolo):
        valor = getattr(PROTOCOLO_KRAKEN, campo.name)
        if isinstance(valor, str):
            nuevo = valor + " (cambio)"
        elif isinstance(valor, tuple):
            nuevo = valor + ("cambio",)
        else:
            nuevo = type(valor)(valor + 1)
        cambiado = dataclasses.replace(PROTOCOLO_KRAKEN, **{campo.name: nuevo})
        assert cambiado.huella() != PROTOCOLO_KRAKEN.huella(), campo.name


def test_registrar_guarda_hash_texto_y_hora_y_no_registra_dos_veces(tmp_path):
    lake = LakeParquet(tmp_path)
    huella = registrar_protocolo(lake, PRUEBA, ahora=REGISTRO)
    filas = lake.consultar(f"SELECT * FROM {FUENTE_PROTOCOLOS}")
    assert len(filas) == 1 and filas.protocolo_hash.iloc[0] == huella == PRUEBA.huella()
    assert filas.texto.iloc[0] == PRUEBA.texto() and pd.Timestamp(filas.registrado_utc.iloc[0]) == REGISTRO
    protocolo, registrado = leer_protocolo(lake.consultar, huella)
    assert protocolo == PRUEBA and registrado == REGISTRO
    with pytest.raises(ProtocoloYaRegistrado):
        registrar_protocolo(lake, PRUEBA, ahora=REGISTRO + pd.Timedelta(hours=1))


def test_no_se_registra_con_fecha_anterior_a_datos_ya_capturados(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(_eventos(T0, duracion_s=60), "eventos_libro")
    with pytest.raises(ValueError, match="retroactivo"):
        registrar_protocolo(lake, PRUEBA, ahora=T0 + pd.Timedelta(seconds=30))


# --- señal y objetivo ---------------------------------------------------------------------------------------


def test_senal_y_objetivo_sin_mirar_el_futuro_y_con_la_latencia():
    p = dataclasses.replace(PRUEBA, paso_s=10.0, ventana_senal_s=2.0, latencia_s=0.25, retardo_decision_s=0.25,
                            horizonte_s=5.0)
    q = _cotizaciones(
        ("okx", 0, 100), ("okx", 10.0, 101), ("okx", 30, 101),               # en t = 10 exacto: ya se conoce
        ("bitvavo", 0, 100), ("bitvavo", 10.001, 101), ("bitvavo", 30, 101),  # 1 ms después: todavía no
        ("kraken", 0, 100), ("kraken", 10.4, 102),                            # antes de la entrada (10,5 s)
        ("kraken", 15.5, 103),                                                # justo al salir (10,5 + 5): cuenta
        ("kraken", 15.51, 104), ("kraken", 30, 104))                          # después de salir: no cuenta
    d = tabla_decisiones(q, p)
    primera = d.iloc[0]
    assert pd.Timestamp(int(primera.t_ns), tz="UTC") == T0 + pd.Timedelta(seconds=10)
    assert primera.senal_bps == pytest.approx(math.log(101 / 100) * 1e4 / 2)
    assert primera.mid_entrada == pytest.approx(102) and primera.mid_salida == pytest.approx(103)
    assert primera.objetivo_bps == pytest.approx(math.log(103 / 102) * 1e4)
    assert primera.ask_entrada == pytest.approx(102.05) and primera.bid_salida == pytest.approx(102.95)
    # En la segunda decisión (20 s) los dos saltos quedaron antes de la ventana (18 s → 20 s): señal 0.
    assert d.iloc[1].senal_bps == pytest.approx(0.0)
    assert len(d) == 2   # 30 s de datos: la de 30 s no tendría salida observada


# --- piezas estadísticas ------------------------------------------------------------------------------------


def test_r2_fuera_de_muestra_con_y_sin_relacion():
    rng = np.random.default_rng(1)
    x = rng.normal(size=2000)
    r2, pendiente, n_ajuste, n_prueba = r2_fuera_de_muestra(x, 0.5 * x + rng.normal(size=2000), 0.5)
    assert r2 > 0.1 and pendiente == pytest.approx(0.5, abs=0.1) and n_ajuste + n_prueba == 2000
    r2_nulo, *_ = r2_fuera_de_muestra(x, rng.normal(size=2000), 0.5)
    assert r2_nulo < 0.005


def test_bootstrap_por_bloques_contiene_la_media_y_se_ensancha_con_dependencia():
    rng = np.random.default_rng(2)
    iid = rng.normal(1.0, 1.0, 1000)
    inf, sup = ic_bootstrap_bloques(iid, bloque=10, repeticiones=1000, semilla=3)
    assert inf < iid.mean() < sup and inf > 0
    # Serie muy persistente: los bloques respetan la dependencia y dan un intervalo más ancho que bloques de 1.
    ar = np.zeros(1000)
    for i in range(1, 1000):
        ar[i] = 0.9 * ar[i - 1] + rng.normal()
    a1, b1 = ic_bootstrap_bloques(ar, bloque=1, repeticiones=1000, semilla=3)
    a20, b20 = ic_bootstrap_bloques(ar, bloque=20, repeticiones=1000, semilla=3)
    assert (b20 - a20) > 1.5 * (b1 - a1)


def test_nulo_circular_detecta_un_lider_y_no_inventa_uno():
    rng = np.random.default_rng(4)
    x = rng.normal(size=1000)
    con = nulo_circular(x, 0.3 * x + rng.normal(size=1000), n_nulos=199, min_desplazamiento=10, semilla=5)
    assert con["p_circular"] == pytest.approx(1 / 200)
    sin = nulo_circular(x, rng.normal(size=1000), n_nulos=199, min_desplazamiento=10, semilla=5)
    assert sin["p_circular"] > 0.05


def test_reglas_de_decision():
    assert decision_estadistica(0.1, 0.01, 0.02, 0.05)
    assert not decision_estadistica(-0.1, 0.01, 0.02, 0.05)          # IC negativo
    assert not decision_estadistica(0.1, 0.05, 0.02, 0.05)           # p no menor que alfa
    assert not decision_estadistica(0.1, 0.01, -0.001, 0.05)         # no predice fuera de muestra
    assert not decision_estadistica(math.nan, 0.01, 0.02, 0.05)
    assert decision_economica(0.01) and not decision_economica(0.0) and not decision_economica(math.nan)


# --- evaluación con el lake ---------------------------------------------------------------------------------


def test_esperando_datos_si_no_llega_al_minimo(tmp_path):
    lake, huella = _lake_registrado(tmp_path, duracion_s=300)
    estado = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1))
    assert estado.estado == ESPERANDO
    assert estado.decisiones_necesarias == PRUEBA.min_decisiones and estado.decisiones_disponibles < 100
    assert "esperando datos" in estado.texto() and str(estado.decisiones_disponibles) in estado.texto()
    assert FUENTE_ESTUDIOS not in lake.fuentes() and FUENTE_APERTURAS not in lake.fuentes()  # no gasta la apertura


def test_con_un_lider_conocido_aprueba_lo_estadistico_y_no_lo_economico_con_comisiones(tmp_path):
    lake, huella = _lake_registrado(tmp_path, retardo_kraken_s=2.0)
    r = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1))
    assert r.tipo == "confirmatoria" and r.n_decisiones >= PRUEBA.min_decisiones
    assert r.ic > 0.3 and r.p_circular < 0.01 and r.r2_fuera > 0 and r.decision_estadistica
    assert r.taker["neto_medio_bps"] < -150 and not r.decision_economica   # 0,80 % por lado
    assert "estadística" in r.conclusion() and "económica" in r.conclusion()
    guardado = lake.consultar(f"SELECT * FROM {FUENTE_ESTUDIOS}")
    assert len(guardado) == 1 and guardado.protocolo_hash.iloc[0] == huella
    assert bool(guardado.decision_estadistica.iloc[0]) and not bool(guardado.decision_economica.iloc[0])
    assert len(lake.consultar(f"SELECT * FROM {FUENTE_APERTURAS}")) == 1


def test_sin_comisiones_y_con_lider_la_decision_economica_es_positiva(tmp_path):
    p = dataclasses.replace(PRUEBA, comision_taker=0.0, comision_maker=0.0)
    lake, huella = _lake_registrado(tmp_path, protocolo=p, retardo_kraken_s=3.0)
    r = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1))
    assert r.taker["ic_inferior_bps"] > 0 and r.decision_economica
    assert r.maker["ic_inferior_bps"] > 0


def test_sin_lider_no_aprueba_lo_estadistico(tmp_path):
    lake, huella = _lake_registrado(tmp_path, independiente=True)
    r = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1))
    assert not r.decision_estadistica and r.p_circular > 0.05


def test_la_evaluacion_no_lee_nada_recibido_hasta_el_registro(tmp_path):
    """Datos anteriores (o en el mismo instante del registro) con un líder perfecto y precios absurdos: si la evaluación
    los usara, cambiaría. Tiene que dar exactamente lo mismo que un lake sin ellos."""
    limpio = tmp_path / "limpio"
    lake_limpio, huella = _lake_registrado(limpio, independiente=True)
    sucio = LakeParquet(tmp_path / "sucio")
    sucio.guardar(_eventos(REGISTRO - pd.Timedelta(seconds=1602), duracion_s=1600, retardo_kraken_s=2.0, semilla=9)
                  + _libro("kraken", REGISTRO, [0.0], [1.0]), "eventos_libro")   # termina justo en el registro
    assert registrar_protocolo(sucio, PRUEBA, ahora=REGISTRO) == huella
    sucio.guardar(_eventos(REGISTRO + pd.Timedelta(milliseconds=1), independiente=True), "eventos_libro")
    ahora = REGISTRO + pd.Timedelta(hours=1)
    a, b = evaluar_protocolo(lake_limpio, huella, ahora=ahora), evaluar_protocolo(sucio, huella, ahora=ahora)
    assert a.desde_utc > REGISTRO and b.desde_utc > REGISTRO
    assert (a.n_decisiones, a.ic, a.p_circular, a.r2_fuera) == (b.n_decisiones, b.ic, b.p_circular, b.r2_fuera)
    assert a.taker == b.taker and a.maker == b.maker


def test_segunda_evaluacion_rechazada_y_seguimiento_etiquetado(tmp_path):
    lake, huella = _lake_registrado(tmp_path)
    primera = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1))
    with pytest.raises(ProtocoloYaEvaluado):
        evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=2))
    # Más datos, después de lo ya evaluado: el seguimiento solo usa esos y se guarda con su etiqueta.
    lake.guardar(_eventos(REGISTRO + pd.Timedelta(hours=1, seconds=1), semilla=11), "eventos_libro")
    seguimiento = evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=2), seguimiento=True)
    assert seguimiento.tipo == "seguimiento" and seguimiento.desde_utc > primera.hasta_utc
    assert "seguimiento" in seguimiento.conclusion() and "no cambia" in seguimiento.conclusion()
    tipos = lake.consultar(f"SELECT tipo FROM {FUENTE_ESTUDIOS} ORDER BY evaluado_utc").tipo.tolist()
    assert tipos == ["confirmatoria", "seguimiento"]


def test_seguimiento_sin_confirmatoria_previa_no_vale(tmp_path):
    lake, huella = _lake_registrado(tmp_path)
    with pytest.raises(ValueError, match="confirmatoria"):
        evaluar_protocolo(lake, huella, ahora=REGISTRO + pd.Timedelta(hours=1), seguimiento=True)


def test_desarrollo_usa_datos_previos_no_guarda_y_no_cuenta(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(_eventos(T0), "eventos_libro")
    r = comprobar_desarrollo(lake, PRUEBA, desde_utc=T0, hasta_utc=T0 + pd.Timedelta(hours=1))
    assert r.tipo == "desarrollo" and r.ic > 0.3 and not r.decision_estadistica and not r.decision_economica
    assert "no decide" in r.conclusion()
    assert lake.fuentes() == ["eventos_libro"]
    # Después, el protocolo se registra igual (el desarrollo no abre nada).
    assert registrar_protocolo(lake, PRUEBA, ahora=T0 + pd.Timedelta(hours=2)) == PRUEBA.huella()


def test_estado_resume_registro_datos_y_evaluaciones(tmp_path):
    lake, huella = _lake_registrado(tmp_path, duracion_s=300)
    (e,) = estado_protocolo(lake, ahora=REGISTRO + pd.Timedelta(hours=1))
    assert e.protocolo_hash == huella and e.estado == ESPERANDO and e.evaluaciones == 0
