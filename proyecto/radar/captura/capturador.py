"""Caso de uso: capturar rondas de cotizaciones, compararlas y guardarlo todo.

Conceptos:
- Captura (recolector): proceso que corre sin parar y registra lo que publica el mercado.
- Snapshot (foto): el estado del libro en un instante; entre dos fotos el mercado puede cambiar mucho.
- Ronda (round): una foto del libro de cada exchange, pedidas A LA VEZ (concurrencia) para que sean comparables.
- Lote (batch): las filas se acumulan y se escriben juntas, para no crear un fichero por foto.
- Error registrado, no ocultado: si un exchange falla o su cotización es imposible, se guarda el error y se
  sigue; nunca se inventa el dato.
- Desequilibrio por ronda: imbalance de cada libro en bandas de bps alrededor del mid
  (`mercado.desequilibrio`), para estudiar después si anticipa el movimiento del precio.
- Conclusión por ronda: con las cotizaciones válidas de la ronda se calcula la comparación de costes
  (`mercado.comparar_costes`) y se guardan sus hechos, para consultarlos después con SQL.
- UTC: todas las horas en tiempo universal.

Fuentes que escribe en el almacén: `cotizaciones`, `comparaciones` (una fila por exchange y ronda),
`conclusiones` (una fila por ronda), `desequilibrios` (una fila por exchange, banda y ronda), `libros`
(una fila por exchange y ronda, con los niveles como listas) y `errores_captura`.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pandas as pd

from radar.almacen.puertos import Almacen
from radar.captura.puertos import FuenteCotizaciones
from radar.configuracion import INTERVALO_S, NIVELES_LIBRO, PAR, TAM_LOTE
from radar.mercado import Cotizacion, Libro, Nivel, comparar_costes, desequilibrio

FUENTE_COTIZACIONES, FUENTE_ERRORES = "cotizaciones", "errores_captura"
FUENTE_COMPARACIONES, FUENTE_CONCLUSIONES = "comparaciones", "conclusiones"
FUENTE_DESEQUILIBRIOS, FUENTE_LIBROS = "desequilibrios", "libros"


def ahora_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def foto_libro(fuente: FuenteCotizaciones, niveles: int, reloj: Callable[[], pd.Timestamp] = ahora_utc) -> Libro:
    """Lee `niveles` del libro de una fuente, le pone horas de solicitud y recepción, y lo valida como `Libro`."""
    solicitado = reloj()
    leido = fuente.leer(niveles)
    recibido = reloj()
    return Libro(fuente.nombre, PAR, tuple(Nivel(p, c) for p, c in leido.bids),
                 tuple(Nivel(p, c) for p, c in leido.asks), solicitado, recibido, leido.hora_exchange_utc)


def foto(fuente: FuenteCotizaciones, reloj: Callable[[], pd.Timestamp] = ahora_utc) -> Cotizacion:
    """Foto del mejor nivel (Fase 1): el libro con un solo nivel por lado."""
    return foto_libro(fuente, 1, reloj).mejor_nivel()


def ronda(fuentes, numero: int, hilos: ThreadPoolExecutor, reloj=ahora_utc,
          niveles: int = NIVELES_LIBRO) -> tuple[list, list]:
    """Una foto del libro de cada fuente, pedidas a la vez. Devuelve (libros válidos, errores)."""
    pedidos = {f.nombre: hilos.submit(foto_libro, f, niveles, reloj) for f in fuentes}
    libros, errores = [], []
    for nombre, pedido in pedidos.items():
        try:
            libros.append(pedido.result())
        except Exception as exc:  # fallo de red, de la API o libro imposible: se registra
            errores.append({"ronda": numero, "exchange": nombre, "recibido_utc": reloj(),
                            "error": f"{type(exc).__name__}: {exc}"})
    return libros, errores


def filas_de_ronda(numero: int, libros, errores, importe_eur=None, comisiones=None, bandas_bps=(),
                   niveles_guardados: int = 0) -> dict:
    """Filas por fuente de una ronda: el mejor nivel de cada libro y, si se pasan importe y comisiones, la
    comparación de costes barriendo los libros; con `bandas_bps`, el desequilibrio de cada libro en cada banda;
    con `niveles_guardados`, el propio libro (esos niveles por lado) para simular ejecuciones después."""
    filas = {FUENTE_COTIZACIONES: [{"ronda": numero, **l.mejor_nivel().a_fila()} for l in libros],
             FUENTE_ERRORES: errores}
    if niveles_guardados and libros:
        filas[FUENTE_LIBROS] = [{"ronda": numero, **l.a_fila(niveles_guardados)} for l in libros]
    if bandas_bps and libros:
        filas[FUENTE_DESEQUILIBRIOS] = [{"ronda": numero, "exchange": l.exchange, "recibido_utc": l.recibido_utc,
                                         **desequilibrio(l, b).a_fila()} for l in libros for b in bandas_bps]
    if importe_eur and comisiones and libros:
        comparacion = comparar_costes(libros, importe_eur, comisiones)
        filas[FUENTE_COMPARACIONES] = [{"ronda": numero, **f} for f in comparacion.a_filas()]
        filas[FUENTE_CONCLUSIONES] = [{"ronda": numero, **comparacion.a_conclusion()}]
    return filas


def capturar(fuentes, almacen: Almacen, segundos: float, intervalo: float = INTERVALO_S,
             tam_lote: int = TAM_LOTE, importe_eur: float | None = None, comisiones: dict | None = None,
             niveles: int = NIVELES_LIBRO, bandas_bps=(), niveles_guardados: int = 0, reloj=ahora_utc, dormir=time.sleep, monotonic=time.monotonic) -> dict:
    """Una ronda cada `intervalo` segundos durante `segundos`; guarda en lotes. Devuelve un resumen."""
    lotes: dict[str, list] = {}
    captura_id = uuid.uuid4().hex  # identifica una ejecución REST; 'ronda' vuelve a cero tras reiniciar
    rondas, n_errores, fin = 0, 0, monotonic() + segundos

    def volcar():
        for fuente, filas in lotes.items():
            almacen.guardar(filas, fuente)
        lotes.clear()

    with ThreadPoolExecutor(max_workers=max(1, len(fuentes))) as hilos:
        while monotonic() < fin:
            inicio = monotonic()
            libros, errores = ronda(fuentes, rondas, hilos, reloj, niveles)
            for fuente, filas in filas_de_ronda(rondas, libros, errores, importe_eur, comisiones, bandas_bps,
                                                   niveles_guardados).items():
                lotes.setdefault(fuente, []).extend([{**fila, "captura_id": captura_id} for fila in filas])
            n_errores += len(errores)
            rondas += 1
            if len(lotes.get(FUENTE_COTIZACIONES, [])) >= tam_lote:
                volcar()
            dormir(max(0, intervalo - (monotonic() - inicio)))
    volcar()
    return {"rondas": rondas, "errores": n_errores}
