"""Línea de comandos del radar (desde la carpeta `proyecto/`):

    python -m radar capturar [segundos] [--exchanges kraken,okx,bitvavo] [--importe 1000] [--niveles 50] [--sin-comparar]
    python -m radar costes [--importe 1000] [--niveles 50]
    python -m radar analizar [--horizontes 1,5,10,30] [--minimo 200] [--precio mid|microprice] [--no-guardar]
    python -m radar catalogo
    python -m radar consultar "SELECT exchange, median(spread_bps) FROM cotizaciones GROUP BY exchange"
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from radar.almacen import LakeParquet
from radar.analisis import (FUENTE_ESTUDIOS, HORIZONTES, PRECIOS, estudiar_imbalance, evaluar_calidad, guardar_estudio,
                            guardar_revalidaciones, leer_ultimo_estudio, pares_imbalance_retorno, revalidar)
from radar.captura.capturador import capturar, foto_libro
from radar.captura.exchanges import crear_fuentes
from radar.configuracion import (BANDAS_BPS, CATALOGO, COMISIONES_TAKER, EXCHANGES, IMPORTE_COMPARACION,
                                 NIVELES_LIBRO, comisiones_taker)
from radar.mercado import comparar_costes


def cmd_capturar(args):
    fuentes = crear_fuentes(args.exchanges.split(","))
    print(f"Capturando {', '.join(f.nombre for f in fuentes)} durante {args.segundos:.0f} s…")
    importe = None if args.sin_comparar else args.importe
    resumen = capturar(fuentes, LakeParquet(), args.segundos, importe_eur=importe, comisiones=comisiones_taker(),
                       niveles=args.niveles, bandas_bps=BANDAS_BPS)
    print(f"Terminado: {resumen['rondas']} rondas, {resumen['errores']} errores.")


def cmd_costes(args):
    libros = [foto_libro(f, args.niveles) for f in crear_fuentes(args.exchanges.split(","))]
    comparacion = comparar_costes(libros, args.importe, comisiones_taker())
    for c in comparacion.costes:
        cot, k, estado = c.libro.mejor_nivel(), c.coste, COMISIONES_TAKER[c.exchange][1]
        print(f"\n{c.exchange}: bid {cot.bid:.2f} € · ask {cot.ask:.2f} € · spread {cot.spread_eur:.2f} € "
              f"({cot.spread_bps:.3f} bps)")
        print(f"  comisión taker {c.comision:.2%} por pata ({estado})")
        print(f"  compra: {k.cantidad_btc:.4f} BTC a {k.compra.precio_medio:.2f} € de media ({k.compra.niveles_usados} "
              f"niveles) · venta a {k.venta.precio_medio:.2f} € ({k.venta.niveles_usados} niveles)"
              + ("" if k.completa else " · INCOMPLETA: el libro capturado no alcanza"))
        print(f"  ida y vuelta: spread {k.coste_spread_eur:.2f} € + slippage {k.slippage_eur:.2f} € + comisiones "
              f"{k.comisiones_eur:.2f} € = {k.coste_total_eur:.2f} € | punto de equilibrio {k.punto_equilibrio_pct:.3f} %")
    print("\nConclusiones del sistema:")
    for frase in comparacion.conclusiones():
        print(f"  - {frase}")


def cmd_analizar(args):
    lake = LakeParquet()
    fuentes = lake.fuentes()
    # El estudio anterior se lee ANTES de guardar el nuevo: sus hallazgos se revalidan con datos posteriores.
    anterior = leer_ultimo_estudio(lake.consultar, metodo=None) if FUENTE_ESTUDIOS in fuentes else None
    calidad = evaluar_calidad(lake.consultar, fuentes)
    print("Calidad de los datos:")
    for c in calidad.values():
        print(f"  - {c.exchange}: {c.rondas} rondas, huecos {c.fraccion_huecos:.1%}, errores {c.fraccion_errores:.1%}, "
              f"latencia p99 {c.latencia_p99_s:.2f} s → {'pasa' if c.pasa else 'NO pasa (' + c.motivo + ')'}")
    pares = pares_imbalance_retorno(lake.consultar, args.horizontes, precio=args.precio)
    # Equilibrio taker solo por comisiones: cota inferior (sin spread ni slippage), así "no rentable" es seguro.
    equilibrio = {ex: ((1 + c) / (1 - c) - 1) * 10_000 for ex, c in comisiones_taker().items()}
    resultados = estudiar_imbalance(pares, args.minimo, equilibrio, calidad, args.precio)
    print(f"\n¿Anticipa el imbalance el {args.precio}? {len(pares)} pares imbalance → retorno, "
          f"horizontes {list(args.horizontes)}.")
    for r in resultados:
        print(f"  - {r.conclusion()}")
    revalidaciones = revalidar(pares, anterior, args.minimo) if anterior is not None else []
    if revalidaciones:
        print("\nRevalidación de los hallazgos confirmados del estudio anterior, con datos posteriores:")
        for r in revalidaciones:
            print(f"  - {r.conclusion()}")
    if not args.no_guardar:
        ahora = pd.Timestamp.now(tz="UTC")
        guardar_estudio(resultados, lake, ahora)
        guardar_revalidaciones(revalidaciones, lake, ahora)
        print(f"\nGuardado en el lake: {len(resultados)} resultados en 'estudios' y {len(revalidaciones)} en "
              f"'revalidaciones'.")


def cmd_catalogo(args):
    print(f"Vistas: {LakeParquet().crear_catalogo()} → {CATALOGO}")


def cmd_consultar(args):
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(LakeParquet().consultar(args.sql))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # € y tildes en la consola de Windows
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m radar", description="Radar · QuantLab observa el mercado")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("capturar", help="Captura rondas de cotizaciones y las guarda en el lake")
    p.add_argument("segundos", nargs="?", type=float, default=60)
    p.add_argument("--exchanges", default=",".join(EXCHANGES))
    p.add_argument("--importe", type=float, default=IMPORTE_COMPARACION, help="EUR de la comparación por ronda")
    p.add_argument("--niveles", type=int, default=NIVELES_LIBRO, help="Niveles del libro por lado")
    p.add_argument("--sin-comparar", action="store_true", help="No guardar comparaciones ni conclusiones")
    p.set_defaults(func=cmd_capturar)
    p = sub.add_parser("costes", help="Coste de una ida y vuelta barriendo el libro y punto de equilibrio, con datos de ahora")
    p.add_argument("--importe", type=float, default=IMPORTE_COMPARACION)
    p.add_argument("--exchanges", default=",".join(EXCHANGES))
    p.add_argument("--niveles", type=int, default=NIVELES_LIBRO, help="Niveles del libro por lado")
    p.set_defaults(func=cmd_costes)
    p = sub.add_parser("analizar", help="Estudia si el desequilibrio del libro anticipa el movimiento del mid")
    p.add_argument("--horizontes", type=lambda t: tuple(int(x) for x in t.split(",")), default=HORIZONTES,
                   help="Rondas hacia delante del retorno futuro, separadas por comas")
    p.add_argument("--minimo", type=int, default=200, help="Rondas mínimas por grupo y mitad para concluir")
    p.add_argument("--precio", choices=sorted(PRECIOS), default="mid", help="Precio de referencia del retorno")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar el estudio en el lake")
    p.set_defaults(func=cmd_analizar)
    sub.add_parser("catalogo", help="Crea data/quantlab.duckdb para DBeaver").set_defaults(func=cmd_catalogo)
    p = sub.add_parser("consultar", help="Ejecuta SQL sobre el lake")
    p.add_argument("sql")
    p.set_defaults(func=cmd_consultar)
    args = parser.parse_args(argv)
    if getattr(args, "segundos", 1) <= 0:
        parser.error("los segundos deben ser positivos")
    if min(getattr(args, "horizontes", (1,))) < 1 or getattr(args, "minimo", 2) < 2:
        parser.error("los horizontes deben ser al menos 1 y el mínimo al menos 2")
    if getattr(args, "niveles", 1) < 1:
        parser.error("los niveles deben ser al menos 1")
    args.func(args)


if __name__ == "__main__":
    main()
