import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.estacionalidad import efecto_hora, medianas_diarias, perfil_horario


def lake_con(tmp_path, dias, spread_por_hora, profundidad=2.0):
    """Cada día, 3 rondas a las 03 h y 3 a las 15 h UTC, con el spread de esa hora (+ un poco de ruido por día)."""
    lake, cot, des, ronda = LakeParquet(tmp_path), [], [], 0
    for d in range(dias):
        for hora, spread in spread_por_hora.items():
            for minuto in range(3):
                t = pd.Timestamp("2026-11-01", tz="UTC") + pd.Timedelta(days=d, hours=hora, minutes=minuto)
                ronda += 1
                cot.append({"exchange": "kraken", "ronda": ronda, "recibido_utc": t, "spread_bps": spread + d * 0.01})
                des.append({"exchange": "kraken", "ronda": ronda, "recibido_utc": t, "banda_bps": 10.0,
                            "cantidad_bids": profundidad, "cantidad_asks": profundidad + hora / 100, "cubierta": True})
    lake.guardar(cot, "cotizaciones")
    lake.guardar(des, "desequilibrios")
    return lake


def test_perfil_horario_resume_por_dia_y_hora(tmp_path):
    lake = lake_con(tmp_path, dias=2, spread_por_hora={3: 1.0, 15: 3.0})
    diario = medianas_diarias(lake.consultar)
    assert len(diario) == 4 and set(diario["hora_utc"]) == {3, 15} and set(diario["rondas"]) == {3}
    perfil = perfil_horario(lake.consultar)
    fila = perfil[perfil["hora_utc"] == 15].iloc[0]
    assert fila["dias"] == 2 and fila["rondas"] == 6 and fila["spread_mediana_bps"] == pytest.approx(3.005)
    assert fila["profundidad_btc"] == pytest.approx(4.15) and fila["banda_bps"] == 10


def test_con_pocos_dias_no_se_concluye(tmp_path):
    lake = lake_con(tmp_path, dias=4, spread_por_hora={3: 1.0, 15: 3.0})
    (efecto,) = efecto_hora(medianas_diarias(lake.consultar), "spread_bps")
    assert efecto.estado == "datos insuficientes" and efecto.dias == 4
    assert "hacen falta al menos 5 días" in efecto.conclusion()


def test_con_suficientes_dias_detecta_la_hora(tmp_path):
    lake = lake_con(tmp_path, dias=6, spread_por_hora={3: 1.0, 15: 3.0})
    diario = medianas_diarias(lake.consultar)
    (spread,) = efecto_hora(diario, "spread_bps")
    assert spread.estado == "depende de la hora" and (spread.hora_maxima, spread.hora_minima) == (15, 3)
    assert "máxima a las 15 h UTC" in spread.conclusion() and spread.a_fila()["estado"] == spread.estado
    (igual,) = efecto_hora(medianas_diarias(lake_con(tmp_path / "b", 6, {3: 2.0, 15: 2.0}).consultar), "spread_bps")
    assert igual.estado == "sin evidencia"


def test_no_mezcla_capturas_que_repiten_numero_de_ronda(tmp_path):
    """Cada captura numera sus rondas desde 0: el cruce con la profundidad tiene que ser por hora de recepción."""
    lake, cot, des = LakeParquet(tmp_path), [], []
    for dia, profundidad in ((1, 1.0), (2, 9.0)):
        for ronda in range(3):
            t = pd.Timestamp(f"2026-11-0{dia} 10:00", tz="UTC") + pd.Timedelta(seconds=ronda)
            cot.append({"exchange": "kraken", "ronda": ronda, "recibido_utc": t, "spread_bps": 1.0})
            des.append({"exchange": "kraken", "ronda": ronda, "recibido_utc": t, "banda_bps": 10.0,
                        "cantidad_bids": profundidad / 2, "cantidad_asks": profundidad / 2, "cubierta": True})
    lake.guardar(cot, "cotizaciones")
    lake.guardar(des, "desequilibrios")
    diario = medianas_diarias(lake.consultar).sort_values("fecha")
    assert list(diario["rondas"]) == [3, 3] and list(diario["profundidad_btc"]) == [1.0, 9.0]
