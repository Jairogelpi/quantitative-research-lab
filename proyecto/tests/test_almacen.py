import duckdb
import pandas as pd

from radar.almacen import LakeParquet


def filas(n, inicio="2026-11-21 23:59:58", **extra):
    t0 = pd.Timestamp(inicio, tz="UTC")
    return [{"exchange": "kraken", "recibido_utc": t0 + pd.Timedelta(seconds=i), "bid": 100. + i, **extra}
            for i in range(n)]


def test_particiona_por_dia_utc_y_no_sobrescribe(tmp_path):
    lake = LakeParquet(tmp_path)
    rutas = lake.guardar(filas(4), "cotizaciones")  # 23:59:58 → 00:00:01: cruza la medianoche
    assert sorted(p.parent.name for p in rutas) == ["fecha=2026-11-21", "fecha=2026-11-22"]
    otra = lake.guardar(filas(1, "2026-11-21 23:59:58.5"), "cotizaciones")
    assert otra[0] not in rutas and len(list(tmp_path.rglob("*.parquet"))) == 3  # append-only
    assert lake.guardar([], "cotizaciones") == []


def test_consulta_sql_con_esquema_que_evoluciona(tmp_path):
    lake = LakeParquet(tmp_path)
    lake.guardar(filas(2), "cotizaciones")
    lake.guardar(filas(2, "2026-11-22 10:00:00", ronda=5), "cotizaciones")  # columna nueva
    r = lake.consultar("SELECT count(*) AS n, count(ronda) AS con_ronda, max(fecha) AS ultimo FROM cotizaciones")
    assert r.n[0] == 4 and r.con_ronda[0] == 2 and pd.Timestamp(r.ultimo[0]).date().isoformat() == "2026-11-22"
    assert str(lake.consultar("SELECT min(recibido_utc) AS t FROM cotizaciones").t[0].tz) == "UTC"
    assert lake.fuentes() == ["cotizaciones"]


def test_catalogo_para_dbeaver(tmp_path):
    lake = LakeParquet(tmp_path / "lake")
    lake.guardar(filas(3), "cotizaciones")
    ruta = tmp_path / "catalogo.duckdb"
    assert lake.crear_catalogo(ruta) == ["cotizaciones"]
    lake.guardar(filas(2, "2026-11-23 10:00:00"), "cotizaciones")  # llega después: la vista la ve igual
    with duckdb.connect(str(ruta), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM cotizaciones").fetchone()[0] == 5


def test_dos_lotes_que_empiezan_en_el_mismo_instante_no_se_pisan(tmp_path):
    """Dos capturas (REST y websocket) pueden escribir a la vez un lote igual de largo y con la misma primera hora."""
    lake, t = LakeParquet(tmp_path), pd.Timestamp("2026-11-22 10:00", tz="UTC")
    lake.guardar([{"exchange": "kraken", "recibido_utc": t, "error": "HTTP 500"}], "errores_captura")
    lake.guardar([{"exchange": "kraken", "recibido_utc": t, "error": "hueco", "origen": "flujo"}], "errores_captura")
    assert sorted(lake.consultar("SELECT error FROM errores_captura")["error"]) == ["HTTP 500", "hueco"]


def test_no_deja_ficheros_a_medio_escribir_a_la_vista_de_las_consultas(tmp_path):
    lake = LakeParquet(tmp_path)
    (ruta,) = lake.guardar([{"recibido_utc": pd.Timestamp("2026-11-22 10:00", tz="UTC"), "x": 1}], "prueba")
    assert ruta.suffix == ".parquet" and ruta.exists()
    assert not list(tmp_path.rglob("*.tmp"))  # el temporal se renombró: no queda nada a medias
