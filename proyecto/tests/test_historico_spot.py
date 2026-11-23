"""Pruebas sin red para la descarga histórica spot de OKX y Bitvavo."""
import pandas as pd
import pytest

from radar.captura.historico_spot import (
    interpretar_okx, interpretar_bitvavo, descargar_okx,
    descargar_bitvavo, actualizar_spot,
)

T0 = pd.Timestamp("2026-11-20T00:00:00Z")


def ms(minutes=0):
    return str(int((T0 + pd.Timedelta(minutes=minutes)).timestamp() * 1000))


def okx_bars(*minutes):
    return {"code": "0", "data": [[ms(m), "100", "105", "95", "102", "2", "204", "204", "1"]
                                  for m in minutes]}


def btv_bars(*minutes):
    return [[ms(m), "100", "105", "95", "102", "2"] for m in minutes]


def test_interpreta_okx_volumen_y_completitud():
    d = interpretar_okx(okx_bars(0), 60, T0 + pd.Timedelta(hours=1))
    assert d.iloc[0].volumen_btc == 2
    assert d.iloc[0].volumen_eur == 204
    assert d.iloc[0].vwap == 102
    assert d.iloc[0].completa
    assert pd.isna(d.iloc[0].n_trades)


def test_bitvavo_no_inventa_vwap():
    d = interpretar_bitvavo(btv_bars(0), 60, T0 + pd.Timedelta(hours=1))
    assert pd.isna(d.iloc[0].vwap) and pd.isna(d.iloc[0].volumen_eur)


def test_okx_pagina_hacia_atras():
    pedidos = []

    def pedir(_url, params):
        pedidos.append(params["after"])
        return okx_bars(4, 3) if len(pedidos) == 1 else okx_bars(2, 1, 0)

    df, paginas, completo = descargar_okx(
        T0, T0 + pd.Timedelta(minutes=6), 60, 5, pedir, lambda _: None)
    assert (len(df), paginas, completo) == (5, 2, True)
    assert df.inicio_utc.is_monotonic_increasing
    assert pedidos[1] == ms(3)


def test_bitvavo_pagina_por_ventanas():
    pedidos = []

    def pedir(_url, params):
        pedidos.append(params)
        return btv_bars(0, 60)

    df, paginas, completo = descargar_bitvavo(
        T0, T0 + pd.Timedelta(hours=2), 60, 2, pedir, lambda _: None)
    assert (len(df), paginas, completo) == (2, 1, True)
    assert pedidos[0]["start"] == int(ms(0))


def test_no_se_inventan_velas_omitidas():
    df, _, _ = descargar_bitvavo(
        T0, T0 + pd.Timedelta(minutes=3), 60, 5,
        lambda _url, _params: btv_bars(0, 2), lambda _: None)
    assert len(df) == 2


def test_errores_visibles_sin_bloquear_otro_exchange():
    class Fake:
        def fuentes(self):
            return []

        def guardar(self, rows, fuente):
            pass

    def pedir(url, params):
        return {"code": "51000", "data": []} if "okx.com" in url else btv_bars(0)

    result = actualizar_spot(Fake(), ("okx", "bitvavo"), (60,),
                            T0, T0 + pd.Timedelta(minutes=2), 1, pedir, lambda _: None)
    assert "error" in result[0]
    assert result[1]["recibidas"] == 1


@pytest.mark.parametrize("payload", [None, {}, {"code": "51000", "data": []}])
def test_okx_fallo_api_no_pasa_por_dato_valido(payload):
    with pytest.raises(ValueError):
        interpretar_okx(payload, 60, T0)


def test_limite_paginas_se_declara_sin_falsa_cobertura():
    df, paginas, completa = descargar_okx(
        T0, T0 + pd.Timedelta(hours=2), 60, 1,
        lambda _url, _params: okx_bars(60), lambda _: None)
    assert paginas == 1 and not completa and len(df) == 1
