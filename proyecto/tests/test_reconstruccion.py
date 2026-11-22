"""Reconstrucción incremental del libro a partir del flujo: snapshot, cambios, secuencia y checksum."""

from decimal import Decimal

import pandas as pd
import pytest

from radar.mercado import Libro
from radar.mercado.reconstruccion import (CHECKSUM, HUECO, Desincronizacion, LibroIncremental, cadena_checksum_kraken,
                                           checksum_kraken, continua_bitvavo, continua_okx)

D = Decimal
INSTANTE = pd.Timestamp("2026-11-22 12:00:00", tz="UTC")


def niveles(*pares):
    return tuple((D(p), D(c)) for p, c in pares)


# Ejemplo oficial de Kraken (docs.kraken.com/api/docs/guides/spot-ws-book-v2): 10 niveles por lado, checksum 3310070434.
KRAKEN_BIDS = niveles(("45283.5", "0.10000000"), ("45283.4", "1.54582015"), ("45282.1", "0.10000000"),
                      ("45281.0", "0.10000000"), ("45280.3", "1.54592586"), ("45279.0", "0.07990000"),
                      ("45277.6", "0.03310103"), ("45277.5", "0.30000000"), ("45277.3", "1.54602737"),
                      ("45276.6", "0.15445238"))
KRAKEN_ASKS = niveles(("45285.2", "0.00100000"), ("45286.4", "1.54571953"), ("45286.6", "1.54571109"),
                      ("45289.6", "1.54560911"), ("45290.2", "0.15890660"), ("45291.8", "1.54553491"),
                      ("45294.7", "0.04454749"), ("45296.1", "0.35380000"), ("45297.5", "0.09945542"),
                      ("45299.5", "0.18772827"))
KRAKEN_CHECKSUM = 3310070434
ASKS_DOC = ("45285210000045286415457195345286615457110945289615456091145290215890660452918154553491452947445474945296135"
            "380000452975994554245299518772827")
BIDS_DOC = ("452835100000004528341545820154528211000000045281010000000452803154592586452790799000045277633101034527753000"
            "000045277315460273745276615445238")


def kraken():
    return LibroIncremental("kraken", profundidad=10, checksum=checksum_kraken)


def test_snapshot_y_actualizacion_con_borrado_por_cantidad_cero():
    libro = LibroIncremental("okx")
    libro.aplicar_snapshot(niveles(("100", "1"), ("99", "2")), niveles(("101", "3"), ("102", "4")))
    libro.aplicar_actualizacion(niveles(("100", "0"), ("98", "5")), niveles(("101", "1.5")))
    assert libro.mejores("bid", 5) == niveles(("99", "2"), ("98", "5"))
    assert libro.mejores("ask", 5) == niveles(("101", "1.5"), ("102", "4"))


def test_precios_con_distinto_texto_son_el_mismo_nivel():
    # Bitvavo publica "55719" en getBook y "55719.00" en las actualizaciones: es el mismo precio.
    libro = LibroIncremental("bitvavo")
    libro.aplicar_snapshot(niveles(("55719", "1")), niveles(("55720", "1")))
    libro.aplicar_actualizacion(niveles(("55719.00", "0")), ())
    assert libro.mejores("bid", 5) == ()


def test_produce_un_libro_del_dominio_con_los_mejores_niveles():
    libro = LibroIncremental("okx")
    hora = pd.Timestamp("2026-11-22 11:59:59.9", tz="UTC")
    libro.aplicar_snapshot(niveles(("100", "1"), ("99", "2"), ("98", "3")), niveles(("101", "3"), ("102", "4")),
                           hora=hora)
    foto = libro.libro(2, INSTANTE, "BTC/EUR")
    assert isinstance(foto, Libro)
    assert [n.precio for n in foto.bids] == [100, 99] and [n.cantidad for n in foto.asks] == [3, 4]
    assert foto.recibido_utc == INSTANTE and foto.hora_exchange_utc == hora


def test_sin_snapshot_no_hay_libro():
    libro = LibroIncremental("okx")
    assert not libro.sincronizado
    with pytest.raises(ValueError):
        libro.aplicar_actualizacion(niveles(("100", "1")), ())
    with pytest.raises(ValueError):
        libro.libro(5, INSTANTE, "BTC/EUR")


def test_trunca_a_la_profundidad_suscrita():
    libro = LibroIncremental("kraken", profundidad=2)
    libro.aplicar_snapshot(niveles(("100", "1"), ("99", "1")), niveles(("101", "1"), ("102", "1")))
    libro.aplicar_actualizacion(niveles(("100.5", "1")), ())
    assert libro.mejores("bid", 5) == niveles(("100.5", "1"), ("100", "1"))  # el 99 sale de la profundidad


def test_rango_del_snapshot_no_se_rellena_con_niveles_no_vistos():
    # Bitvavo manda cambios de todo el libro, pero el snapshot solo trae N niveles: lo que queda fuera de su
    # rango no se conoce entero y no se publica.
    libro = LibroIncremental("bitvavo", solo_rango_snapshot=True)
    libro.aplicar_snapshot(niveles(("100", "1"), ("99", "1")), niveles(("101", "1"), ("102", "1")))
    libro.aplicar_actualizacion(niveles(("90", "7")), niveles(("110", "7"), ("101.5", "2")))
    assert libro.mejores("bid", 5) == niveles(("100", "1"), ("99", "1"))
    assert libro.mejores("ask", 5) == niveles(("101", "1"), ("101.5", "2"), ("102", "1"))


def test_checksum_kraken_con_el_ejemplo_oficial():
    libro = kraken()
    libro.aplicar_snapshot(KRAKEN_BIDS, KRAKEN_ASKS, checksum=KRAKEN_CHECKSUM)  # no lanza
    assert cadena_checksum_kraken(libro) == ASKS_DOC + BIDS_DOC
    assert checksum_kraken(libro) == KRAKEN_CHECKSUM


def test_checksum_kraken_con_precision_fija_aunque_llegue_sin_ceros():
    libro = kraken()
    libro.aplicar_snapshot(tuple((p, c.normalize()) for p, c in KRAKEN_BIDS),
                           tuple((p, c.normalize()) for p, c in KRAKEN_ASKS))
    assert checksum_kraken(libro, decimales_precio=1, decimales_cantidad=8) == KRAKEN_CHECKSUM


def test_checksum_kraken_distinto_desincroniza():
    libro = kraken()
    libro.aplicar_snapshot(KRAKEN_BIDS, KRAKEN_ASKS, checksum=KRAKEN_CHECKSUM)
    with pytest.raises(Desincronizacion) as error:
        libro.aplicar_actualizacion(niveles(("45283.5", "0.20000000")), (), checksum=KRAKEN_CHECKSUM)
    assert error.value.motivo == CHECKSUM
    assert not libro.sincronizado  # el libro se descarta: hay que volver a pedir el snapshot


def test_checksum_kraken_en_el_snapshot_tambien_se_verifica():
    with pytest.raises(Desincronizacion):
        kraken().aplicar_snapshot(KRAKEN_BIDS, KRAKEN_ASKS, checksum=KRAKEN_CHECKSUM + 1)


def test_okx_secuencia_continua_mantenimiento_y_reinicio():
    libro = LibroIncremental("okx", regla_secuencia=continua_okx)
    libro.aplicar_snapshot(niveles(("100", "1")), niveles(("101", "1")), secuencia=10)
    libro.aplicar_actualizacion(niveles(("100", "2")), (), secuencia=15, secuencia_previa=10)
    libro.aplicar_actualizacion((), (), secuencia=15, secuencia_previa=15)  # sin cambios (keepalive)
    libro.aplicar_actualizacion((), (), secuencia=3, secuencia_previa=15)  # reinicio por mantenimiento
    libro.aplicar_actualizacion((), niveles(("101", "4")), secuencia=5, secuencia_previa=3)
    assert libro.secuencia == 5 and libro.mejores("ask", 1) == niveles(("101", "4"))


def test_okx_hueco_de_secuencia_desincroniza():
    libro = LibroIncremental("okx", regla_secuencia=continua_okx)
    libro.aplicar_snapshot(niveles(("100", "1")), niveles(("101", "1")), secuencia=10)
    with pytest.raises(Desincronizacion) as error:
        libro.aplicar_actualizacion(niveles(("100", "2")), (), secuencia=20, secuencia_previa=12)
    assert error.value.motivo == HUECO and not libro.sincronizado


def test_bitvavo_nonce_debe_subir_de_uno_en_uno():
    libro = LibroIncremental("bitvavo", regla_secuencia=continua_bitvavo)
    libro.aplicar_snapshot(niveles(("100", "1")), niveles(("101", "1")), secuencia=7)
    libro.aplicar_actualizacion(niveles(("100", "2")), (), secuencia=8)
    with pytest.raises(Desincronizacion) as error:
        libro.aplicar_actualizacion(niveles(("100", "3")), (), secuencia=10)
    assert error.value.motivo == HUECO
    assert "8" in str(error.value) and "10" in str(error.value)
