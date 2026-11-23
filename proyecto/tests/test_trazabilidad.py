"""La ejecución de estudios queda ligada al identificador de los archivos guardados."""
import json

import pandas as pd
import pytest

from radar.almacen import LakeParquet
from radar.analisis.trazabilidad import registrar_estudio, run_id_actual

T = pd.Timestamp("2026-11-23T12:00:00Z")


def test_estudio_guarda_manifest_y_etiqueta_resultados(tmp_path):
    lake = LakeParquet(tmp_path / "lake")
    runs = tmp_path / "runs"
    assert run_id_actual() is None
    with registrar_estudio("retornos", {"intervalo": 60}, raiz_lake=lake.raiz,
                           raiz_runs=runs) as run:
        assert run_id_actual() == run
        lake.guardar([{"recibido_utc": T, "exchange": "okx", "n": 1}], "estudios_demo")
    assert run_id_actual() is None
    d = json.loads(next(runs.glob("*.json")).read_text(encoding="utf-8"))
    assert d["run_id"] == run
    assert d["estado"] == "correcto"
    assert d["datos_entrada"]["n_archivos"] == 0
    assert d["datos_salida"]["n_archivos"] == 1
    assert d["datos_cambiaron_durante_ejecucion"]
    assert lake.consultar("SELECT run_id FROM estudios_demo").run_id.iloc[0] == run


def test_estudio_fallido_registra_error_y_restauracion_contexto(tmp_path):
    with pytest.raises(RuntimeError, match="error simulado"):
        with registrar_estudio("prueba", {}, raiz_lake=tmp_path / "lake",
                               raiz_runs=tmp_path / "runs"):
            raise RuntimeError("error simulado")
    d = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert d["estado"] == "error" and "error simulado" in d["error"]
    assert run_id_actual() is None
