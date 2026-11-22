"""Línea de comandos del radar (desde la carpeta `proyecto/`):

    python -m radar capturar [segundos] [--exchanges kraken,okx,bitvavo] [--importe 1000] [--niveles 100]
                             [--guardar-niveles 50] [--sin-comparar]
    python -m radar costes [--importe 1000] [--niveles 100]
    python -m radar analizar [--horizontes 1,5,10,30] [--minimo 200] [--precio mid|microprice] [--no-guardar]
    python -m radar simular [--exchange kraken] [--importe 100000] [--trozos 20] [--duracion 600]
                            [--impactos 0,1,5] [--urgencias 1,3] [--urgencia-adaptativa 1]
                            [--intensidades 0.5,1] [--no-guardar]
    python -m radar estacionalidad [--banda 10] [--no-guardar]
    python -m radar flujo [segundos] [--exchanges kraken,okx,bitvavo]
    python -m radar markouts [--no-guardar]
    python -m radar liquidez [--horas 6] [--no-guardar]
    python -m radar volatilidad [--no-guardar]
    python -m radar relojes [--horas 24] [--no-guardar]
    python -m radar hy [--horas 2] [--rango 5] [--paso 0.01] [--sustitutos 199] [--no-guardar]
    python -m radar revalidar [--no-guardar]
    python -m radar registro [--todas] [--no-guardar]
    python -m radar robustez [--no-guardar]
    python -m radar ofi-eventos [--horas 6] [--intervalos 1,10] [--minimo 200] [--no-guardar]
    python -m radar presion [--horas 6] [--no-guardar]
    python -m radar respuesta [--horas 6] [--no-guardar]
    python -m radar velas [--horas 168] [--intervalos 60,300,3600,86400]
    python -m radar historico-kraken [--archivo RUTA_O_URL ...] [--intervalos-zip 60,1440] [--sin-zip]
    python -m radar comparar-velas [--intervalos 60,300,3600,86400] [--no-guardar]
    python -m radar retornos [--fuente propia|kraken_historico] [--intervalo 3600] [--exchange kraken] [--no-guardar]
    python -m radar leadlag [--retardos 1,2,3] [--minimo 500] [--no-guardar]
    python -m radar senales [--horizonte 5] [--minimo 500] [--no-guardar]
    python -m radar ofi [--horizontes 1,5,10,30] [--niveles 1,5,10] [--minimo 200] [--no-guardar]
    python -m radar catalogo
    python -m radar consultar "SELECT exchange, median(spread_bps) FROM cotizaciones GROUP BY exchange"
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from radar.almacen import LakeParquet
from radar.analisis.ofi import (FUENTE_ESTUDIOS_OFI, estudiar_ofi, guardar_estudio_ofi, impacto_contemporaneo,
                               pares_ofi_retorno)
from radar.analisis.leadlag import FUENTE_LEAD_LAG, estudiar_lead_lag, matriz_correlaciones, mids_alineados
from radar.analisis.senales import (FUENTE_SENALES, HORIZONTES_DECAIMIENTO, aporte_senales, correlaciones,
                                   decaimiento, interacciones, tabla_senales)
from radar.analisis.markouts import FUENTE_MARKOUTS, estudiar_markouts
from radar.analisis.liquidez import FUENTE_LIQUIDEZ, estudiar_liquidez, guardar_estudio_liquidez
from radar.analisis.volatilidad import FUENTE_VOLATILIDAD, estudiar_volatilidad, guardar_estudio_volatilidad
from radar.analisis.relojes import FUENTE_RELOJES, diagnostico_comun, guardar_relojes, medir_relojes
from radar.analisis.hayashi_yoshida import (FUENTE_HY, estudiar_hayashi_yoshida, guardar_hayashi_yoshida,
                                            incertidumbres_desde_relojes, mids_flujo)
from radar.analisis.revalidacion import guardar_estudio_senales, guardar_revalidaciones_estudios, revalidar_todo
from radar.analisis.registro import FUENTE_REGISTRO, guardar_registro, registrar_pruebas, resumen_registro
from radar.analisis.ofi_eventos import FUENTE_OFI_EVENTOS, estudio_ofi_eventos, guardar_ofi_eventos
from radar.analisis.presion import FUENTE_PRESION, estudiar_presion, guardar_estudio_presion
from radar.analisis.respuesta import FUENTE_RESPUESTA, estudiar_respuesta, guardar_estudio_respuesta
from radar.analisis.velas import actualizar_velas
from radar.analisis.retornos import FUENTE_RETORNOS, estudiar_retornos_lake, guardar_estudio_retornos
from radar.analisis.comparacion_velas import FUENTE_COMPARACION, comparar_velas, guardar_comparacion_velas
from radar.captura import historico_kraken
from radar.captura.exchanges import kraken_historico
from radar.analisis.robustez import FUENTE_ROBUSTEZ, evaluar_robustez, guardar_robustez, resumen_robustez
from radar.analisis.estacionalidad import FUENTE_PERFILES, efecto_hora, medianas_diarias, perfil_horario
from radar.analisis import (FUENTE_ESTUDIOS, HORIZONTES, PRECIOS, estudiar_imbalance, evaluar_calidad, guardar_estudio,
                            guardar_revalidaciones, leer_ultimo_estudio, pares_imbalance_retorno, revalidar)
from radar.captura.capturador import capturar, foto_libro
from radar.captura.flujo import capturar_flujo
from radar.captura.exchanges import crear_fuentes
from radar.configuracion import (BANDAS_BPS, CATALOGO, COMISIONES_TAKER, EXCHANGES, IMPORTE_COMPARACION,
                                 NIVELES_GUARDADOS, NIVELES_LIBRO, comisiones_taker)
from radar.ejecucion import (FUENTE_SIMULACIONES, aversion_implicita, cargar_libros, comparar_estrategias,
                             comparar_texto, elegir_senal, estimar_impacto_temporal, estimar_volatilidad)
from radar.ejecucion.replay import MIN_VENTANAS
from radar.mercado import comparar_costes


def cmd_capturar(args):
    fuentes = crear_fuentes(args.exchanges.split(","))
    print(f"Capturando {', '.join(f.nombre for f in fuentes)} durante {args.segundos:.0f} s…")
    importe = None if args.sin_comparar else args.importe
    resumen = capturar(fuentes, LakeParquet(), args.segundos, importe_eur=importe, comisiones=comisiones_taker(),
                       niveles=args.niveles, bandas_bps=BANDAS_BPS, niveles_guardados=args.guardar_niveles)
    print(f"Terminado: {resumen['rondas']} rondas, {resumen['errores']} errores.")


def cmd_flujo(args):
    exchanges = args.exchanges.split(",")
    print(f"Capturando el flujo del libro y los trades por websocket de {', '.join(exchanges)} durante "
          f"{args.segundos:.0f} s…")
    resumen = capturar_flujo(exchanges, LakeParquet(), args.segundos)
    print(f"Terminado: {resumen['eventos_libro']} cambios del libro, {resumen['trades']} trades y {resumen['libros']} "
          f"libros reconstruidos; {resumen['errores']} errores, {resumen['resincronizaciones']} resincronizaciones y "
          f"{resumen['reconexiones']} reconexiones.")


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


def cmd_simular(args):
    lake = LakeParquet()
    libros = cargar_libros(lake.consultar, args.exchange)
    print(f"{args.exchange}: {len(libros)} libros guardados. Compra de {args.importe:,.0f} € todo de golpe frente a "
          f"TWAP en {args.trozos} trozos durante {args.duracion:g} s.")
    if libros:
        sigma2, k = estimar_volatilidad(libros), estimar_impacto_temporal(libros[::60])  # una foto por minuto basta
        print(f"Parámetros medidos: σ² = {sigma2:.3f} €²/s (σ = {sigma2 ** 0.5:.2f} € por √s), slippage de golpe "
              f"k = {k:.2f} € por BTC y por BTC.")
        for u in args.urgencias:
            print(f"  Almgren-Chriss κT={u:g}: aversión al riesgo implícita λ = "
                  f"{aversion_implicita(u, args.duracion, args.trozos, sigma2, k):.2e} por €.")
    senal = None
    if libros and args.intensidades and FUENTE_ESTUDIOS in lake.fuentes():
        # La señal debe venir de un estudio que terminó antes de las ventanas que se simulan (fuera de muestra).
        limite = libros[-1].recibido_utc - pd.Timedelta(seconds=MIN_VENTANAS * args.duracion)
        senal = elegir_senal(lake.consultar(f"SELECT * FROM {FUENTE_ESTUDIOS}"), args.exchange,
                             args.duracion / args.trozos, limite)
    if senal:
        print(f"Señal para el adaptativo: {senal.descripcion()}. Todas las estrategias se comparan solo en ventanas "
              f"posteriores a {senal.hasta_utc:%Y-%m-%d %H:%M:%S} UTC (fuera de muestra).")
    elif args.intensidades:
        print("Sin hallazgo confirmado de imbalance en un estudio anterior a los libros: no se simula el adaptativo.")
    resumenes = comparar_estrategias(libros, args.importe, args.trozos, args.duracion,
                                     comisiones_taker()[args.exchange], args.impactos, urgencias=args.urgencias,
                                     senal=senal, adaptativas=[(args.urgencia_adaptativa, i) for i in args.intensidades],
                                     desde_utc=senal.hasta_utc if senal else None)
    for r in resumenes:
        print(f"  - {r.conclusion()}")
    for frase in comparar_texto(resumenes):
        print(f"  → {frase}")
    if not args.no_guardar and resumenes:
        ahora = pd.Timestamp.now(tz="UTC")
        lake.guardar([{"ejecutado_utc": ahora, "recibido_utc": ahora, **r.a_fila()} for r in resumenes],
                     FUENTE_SIMULACIONES)
        print(f"Guardado en el lake: {len(resumenes)} resúmenes en '{FUENTE_SIMULACIONES}'.")


def cmd_ofi(args):
    lake = LakeParquet()
    calidad = evaluar_calidad(lake.consultar, lake.fuentes())
    pares = pares_ofi_retorno(lake.consultar, args.horizontes, args.niveles_ofi)
    print(f"Order Flow Imbalance: {len(pares)} pares OFI → retorno, niveles {list(args.niveles_ofi)}, horizontes "
          f"{list(args.horizontes)}.")
    impactos = impacto_contemporaneo(pares)
    print("\nImpacto contemporáneo (el OFI de un intervalo frente al movimiento del mid en ese mismo intervalo):")
    for i in impactos:
        print(f"  - {i.conclusion()}")
    equilibrio = {ex: ((1 + c) / (1 - c) - 1) * 10_000 for ex, c in comisiones_taker().items()}
    resultados = estudiar_ofi(pares, args.minimo, equilibrio, calidad)
    print("\n¿Anticipa el OFI de ahora el retorno futuro?")
    for r in resultados:
        print(f"  - {r.conclusion()}")
    if not args.no_guardar:
        guardar_estudio_ofi(impactos, resultados, lake, pd.Timestamp.now(tz="UTC"))
        print(f"\nGuardado en el lake: {len(impactos) + len(resultados)} resultados en '{FUENTE_ESTUDIOS_OFI}'.")


def cmd_leadlag(args):
    lake = LakeParquet()
    alineados = mids_alineados(lake.consultar)
    if alineados.empty:
        print("No hay cotizaciones en el lake.")
        return
    print(f"Lead-lag entre exchanges: {len(alineados)} rondas con los tres mids alineados.")
    print(f"\nCorrelación simultánea de los retornos por ronda:")
    print(matriz_correlaciones(alineados).round(3).to_string())
    resultados = estudiar_lead_lag(alineados, args.retardos, args.minimo)
    print(f"\n¿Qué exchange se mueve primero?")
    for r in resultados:
        print(f"  - {r.conclusion()}")
    if not args.no_guardar:
        ahora = pd.Timestamp.now(tz="UTC")
        lake.guardar([{"ejecutado_utc": ahora, "recibido_utc": ahora, **r.a_fila()} for r in resultados],
                     FUENTE_LEAD_LAG)
        print(f"\nGuardado en el lake: {len(resultados)} resultados en '{FUENTE_LEAD_LAG}'.")


def cmd_senales(args):
    lake = LakeParquet()
    tabla = tabla_senales(lake.consultar, horizontes=sorted({args.horizonte, *HORIZONTES_DECAIMIENTO}))
    if tabla.empty:
        print("No hay cotizaciones en el lake.")
        return
    print(f"Señales: imbalance (banda 5 bps), OFI (5 niveles) y líder (retorno de los otros exchanges en la "
          f"ronda anterior); {len(tabla)} filas.")
    for exchange in sorted(tabla.exchange.unique()):
        print(f"\nCorrelación (Spearman) entre señales y contexto en {exchange}:")
        print(correlaciones(tabla, exchange).round(2).to_string())
    resultados = (aporte_senales(tabla, args.horizonte, args.minimo) + interacciones(tabla, args.horizonte, args.minimo)
                  + decaimiento(tabla, minimo=args.minimo))
    for titulo, tipo in (("¿Qué señal aporta información propia?", "aporte"),
                         ("¿Funciona distinto con el spread o la volatilidad altos?", "interaccion"),
                         ("¿Cuánto dura cada señal?", "decaimiento")):
        print(f"\n{titulo}")
        for r in resultados:
            if r.a_fila()["estudio"] == tipo:
                print(f"  - {r.conclusion()}")
    if not args.no_guardar:
        ahora = pd.Timestamp.now(tz="UTC")
        guardar_estudio_senales(resultados, tabla, lake, ahora)  # con `hasta_utc`, para poder revalidarlos
        print(f"\nGuardado en el lake: {len(resultados)} resultados en '{FUENTE_SENALES}'.")


def cmd_markouts(args):
    lake = LakeParquet()
    if not {"trades", "libros_flujo"} <= set(lake.fuentes()):
        print("Faltan trades o libros del websocket: captúralos con `python -m radar flujo`.")
        return
    markouts, llenados = estudiar_markouts(lake.consultar)
    print("Markout de los trades (cuánto se movió el mid después, desde el que tomó liquidez):")
    for m in markouts:
        print(f"  - {m.conclusion()}")
    print()
    print("Órdenes limit hipotéticas en el mejor precio (¿se habrían llenado y con qué markout?):")
    for l in llenados:
        print(f"  - {l.conclusion()}")
    if not args.no_guardar:
        ahora = pd.Timestamp.now(tz="UTC")
        resultados = markouts + llenados
        lake.guardar([{"ejecutado_utc": ahora, "recibido_utc": ahora, **r.a_fila()} for r in resultados],
                     FUENTE_MARKOUTS)
        print()
        print(f"Guardado en el lake: {len(resultados)} resultados en '{FUENTE_MARKOUTS}'.")


def _mostrar_y_guardar(args, lake, titulo, resultados, guardar, fuente):
    """Imprime la conclusión de cada resultado y, salvo `--no-guardar`, los guarda en `fuente`."""
    print(titulo)
    for r in resultados:
        print(f"  - {r.conclusion()}")
    if not args.no_guardar and resultados:
        guardar(resultados, lake, pd.Timestamp.now(tz="UTC"))
        print()
        print(f"Guardado en el lake: {len(resultados)} resultados en '{fuente}'.")


def _hace_horas(horas):
    return pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=horas)


def cmd_liquidez(args):
    lake = LakeParquet()
    if not {"trades", "eventos_libro"} <= set(lake.fuentes()):
        print("Faltan trades o cambios del libro del websocket: captúralos con `python -m radar flujo`.")
        return
    print(f"Mid exacto antes de cada trade, reconstruido con los cambios del libro de las últimas {args.horas:g} h.")
    spreads, lambdas = estudiar_liquidez(lake.consultar, _hace_horas(args.horas))
    _mostrar_y_guardar(args, lake, "Spreads efectivo y realizado, impacto y lambda de Kyle (datos del websocket):",
                       spreads + lambdas, guardar_estudio_liquidez, FUENTE_LIQUIDEZ)


def cmd_volatilidad(args):
    lake = LakeParquet()
    _mostrar_y_guardar(args, lake, "Volatilidad realizada robusta al ruido (two-scale) y signature plot:",
                       estudiar_volatilidad(lake.consultar), guardar_estudio_volatilidad, FUENTE_VOLATILIDAD)


def cmd_relojes(args):
    lake = LakeParquet()
    relojes = medir_relojes(lake.consultar, _hace_horas(args.horas))
    _mostrar_y_guardar(args, lake, f"Relojes: desfase entre la hora del exchange y la nuestra (últimas {args.horas:g} h):",
                       relojes, guardar_relojes, FUENTE_RELOJES)
    print()
    print(diagnostico_comun(relojes))
    print(diagnostico_comun(relojes, "cotizaciones"))


def cmd_hy(args):
    lake = LakeParquet()
    desde = _hace_horas(args.horas)
    relojes = medir_relojes(lake.consultar, desde)  # misma ventana: así nuestra deriva se cancela
    mids = mids_flujo(lake.consultar, desde)
    if mids.empty:
        print("No hay cambios del libro del websocket en esa ventana: captúralos con `python -m radar flujo`.")
        return
    print(f"Hayashi-Yoshida: {len(mids)} cambios del mid en las últimas {args.horas:g} h; {args.sustitutos} sustitutos.")
    resultados = estudiar_hayashi_yoshida(mids, args.rango, args.paso, args.sustitutos,
                                          incertidumbres=incertidumbres_desde_relojes(relojes, mids.exchange.unique()))
    _mostrar_y_guardar(args, lake, "Lead-lag en milisegundos entre exchanges:", resultados, guardar_hayashi_yoshida,
                       FUENTE_HY)


def cmd_revalidar(args):
    lake = LakeParquet()
    _mostrar_y_guardar(args, lake, "Revalidación de los hallazgos de OFI, lead-lag y señales con datos posteriores:",
                       revalidar_todo(lake.consultar, lake.fuentes()), guardar_revalidaciones_estudios,
                       "revalidaciones")


def cmd_registro(args):
    lake = LakeParquet()
    pruebas = registrar_pruebas(lake.consultar, lake.fuentes(), todas_las_ejecuciones=args.todas)
    print(resumen_registro(pruebas))
    _mostrar_y_guardar(args, lake, "Hallazgos de cada estudio frente a la corrección global:",
                       [p for p in pruebas if p.hallazgo], lambda _, a, t: guardar_registro(pruebas, a, t),
                       FUENTE_REGISTRO)


def cmd_robustez(args):
    lake = LakeParquet()
    resultados = evaluar_robustez(lake.consultar, lake.fuentes())
    print(resumen_robustez(resultados))
    _mostrar_y_guardar(args, lake, "Robustez de cada hallazgo frente a los parámetros vecinos:", resultados,
                       guardar_robustez, FUENTE_ROBUSTEZ)


def _hay_flujo(lake) -> bool:
    if {"trades", "eventos_libro"} <= set(lake.fuentes()):
        return True
    print("Faltan trades o cambios del libro del websocket: captúralos con `python -m radar flujo`.")
    return False


def cmd_ofi_eventos(args):
    lake = LakeParquet()
    if "eventos_libro" not in lake.fuentes():
        print("No hay cambios del libro del websocket: captúralos con `python -m radar flujo`.")
        return
    impactos, predicciones = estudio_ofi_eventos(lake.consultar, _hace_horas(args.horas), intervalos_s=args.intervalos,
                                                 minimo=args.minimo, con_fotos="libros" in lake.fuentes())
    _mostrar_y_guardar(args, lake, f"OFI evento a evento, Cont-Kukanov-Stoikov (últimas {args.horas:g} h):",
                       impactos + predicciones,
                       lambda r, a, t: guardar_ofi_eventos(impactos, predicciones, a, t), FUENTE_OFI_EVENTOS)


def cmd_presion(args):
    lake = LakeParquet()
    if _hay_flujo(lake):
        _mostrar_y_guardar(args, lake, f"Presión compradora y vendedora: trade imbalance, CVD, intensidad, VWAP y "
                                       f"exposición (últimas {args.horas:g} h):",
                           estudiar_presion(lake.consultar, _hace_horas(args.horas)), guardar_estudio_presion,
                           FUENTE_PRESION)


def cmd_respuesta(args):
    lake = LakeParquet()
    if _hay_flujo(lake):
        _mostrar_y_guardar(args, lake, f"Respuesta del precio a un trade, Bouchaud (últimas {args.horas:g} h):",
                           estudiar_respuesta(lake.consultar, desde_utc=_hace_horas(args.horas)),
                           guardar_estudio_respuesta, FUENTE_RESPUESTA)


def cmd_velas(args):
    lake = LakeParquet()
    if "trades" not in lake.fuentes():
        print("No hay trades del websocket: captúralos con `python -m radar flujo`.")
        return
    resumen = actualizar_velas(lake, intervalos_s=args.intervalos, horas=args.horas)
    print(f"Velas propias: {resumen['velas']} calculadas, {resumen['escritas']} nuevas o cambiadas escritas en 'velas'.")
    for intervalo, r in resumen["por_intervalo"].items():
        print(f"  - {intervalo} s: {r['velas']} velas, {r['vacias']} vacías, {r['incompletas']} incompletas.")


def cmd_historico_kraken(args):
    lake = LakeParquet()
    partes = args.archivo or kraken_historico.PARTES_COMPLETO
    print("Histórico oficial de Kraken (BTC/EUR): archivo OHLCVT por lecturas parciales y la API para lo reciente…")
    resultado = historico_kraken.actualizar_historico(lake, partes=partes, intervalos_zip_min=args.intervalos_zip,
                                                      intervalos_rest_min=args.intervalos_rest,
                                                      con_zip=not args.sin_zip)
    for fila in resultado["resumen"]:
        print(f"  - {fila}")


def cmd_comparar_velas(args):
    lake = LakeParquet()
    if "velas" not in lake.fuentes():
        print("No hay velas: créalas con `python -m radar velas` y `python -m radar historico-kraken`.")
        return
    _mostrar_y_guardar(args, lake, "Velas propias frente a las oficiales de Kraken, en los mismos intervalos:",
                       comparar_velas(lake.consultar, args.intervalos), guardar_comparacion_velas, FUENTE_COMPARACION)


def cmd_retornos(args):
    lake = LakeParquet()
    if "velas" not in lake.fuentes():
        print("No hay velas: créalas con `python -m radar velas` y `python -m radar historico-kraken`.")
        return
    resultados = estudiar_retornos_lake(lake.consultar, args.fuente, args.intervalo, args.exchange)
    _mostrar_y_guardar(args, lake, f"Retornos y volatilidad (velas {args.fuente}):", resultados,
                       guardar_estudio_retornos, FUENTE_RETORNOS)


def cmd_estacionalidad(args):
    lake = LakeParquet()
    perfil = perfil_horario(lake.consultar, args.banda)
    if perfil.empty:
        print("No hay cotizaciones en el lake.")
        return
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print(perfil.round(4).to_string(index=False))
    diario = medianas_diarias(lake.consultar, args.banda)
    efectos = efecto_hora(diario, "spread_bps") + efecto_hora(diario, "profundidad_btc")
    print("\nConclusiones del sistema:")
    for e in efectos:
        print(f"  - {e.conclusion()}")
    if not args.no_guardar:
        ahora = pd.Timestamp.now(tz="UTC")
        lake.guardar([{"ejecutado_utc": ahora, "recibido_utc": ahora, **e.a_fila()} for e in efectos], FUENTE_PERFILES)
        print(f"Guardado en el lake: {len(efectos)} conclusiones en '{FUENTE_PERFILES}'.")


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
    p.add_argument("--guardar-niveles", type=int, default=NIVELES_GUARDADOS,
                   help="Niveles por lado del libro que se guardan (0 = no guardar libros)")
    p.add_argument("--sin-comparar", action="store_true", help="No guardar comparaciones ni conclusiones")
    p.set_defaults(func=cmd_capturar)
    p = sub.add_parser("flujo", help="Captura por websocket los cambios del libro (con secuencia y checksum) y los trades")
    p.add_argument("segundos", nargs="?", type=float, default=60)
    p.add_argument("--exchanges", type=str, default=",".join(EXCHANGES))
    p.set_defaults(func=cmd_flujo)
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
    p = sub.add_parser("simular", help="Simula una compra grande (todo de golpe, TWAP, Almgren-Chriss y adaptativo) sobre los libros guardados")
    p.add_argument("--exchange", choices=EXCHANGES, default="kraken")
    p.add_argument("--importe", type=float, default=100_000, help="EUR a comprar")
    p.add_argument("--trozos", type=int, default=20, help="Trozos del TWAP")
    p.add_argument("--duracion", type=float, default=600, help="Segundos que dura el TWAP (y cada ventana)")
    p.add_argument("--impactos", type=lambda t: tuple(float(x) for x in t.split(",")), default=(0.0, 1.0, 5.0),
                   help="Impacto permanente supuesto, en bps por cada 100.000 € ejecutados, separados por comas")
    p.add_argument("--urgencias", type=lambda t: tuple(float(x) for x in t.split(",")), default=(1.0, 3.0),
                   help="Urgencias κT de Almgren-Chriss, separadas por comas (0 = TWAP)")
    p.add_argument("--urgencia-adaptativa", type=float, default=1.0,
                   help="Urgencia κT del Almgren-Chriss base del adaptativo")
    p.add_argument("--intensidades", type=lambda t: tuple(float(x) for x in t.split(",") if x), default=(0.5, 1.0),
                   help="Intensidades del adaptativo (cuánto adelanta o retrasa con el imbalance); vacío = no simular")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_simular)
    p = sub.add_parser("ofi", help="Order Flow Imbalance: impacto en el precio y poder predictivo")
    p.add_argument("--horizontes", type=lambda t: tuple(int(x) for x in t.split(",")), default=HORIZONTES,
                   help="Rondas hacia delante del retorno futuro, separadas por comas")
    p.add_argument("--niveles", dest="niveles_ofi", type=lambda t: tuple(int(x) for x in t.split(",")),
                   default=(1, 5, 10),
                   help="Niveles por lado del OFI multinivel, separados por comas")
    p.add_argument("--minimo", type=int, default=200, help="Rondas mínimas por grupo y mitad para concluir")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_ofi)
    p = sub.add_parser("leadlag", help="Qué exchange se mueve primero (Granger, lead-lag ratio, correlaciones)")
    p.add_argument("--retardos", type=lambda t: tuple(int(x) for x in t.split(",")), default=(1, 2, 3),
                   help="Rondas de adelanto que se prueban, separadas por comas")
    p.add_argument("--minimo", type=int, default=500, help="Rondas mínimas por mitad para concluir")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_leadlag)
    p = sub.add_parser("senales", help="Correlaciones, aporte propio, interacciones y decaimiento de las señales")
    p.add_argument("--horizonte", type=int, default=5, help="Rondas del retorno futuro del aporte y las interacciones")
    p.add_argument("--minimo", type=int, default=500, help="Filas mínimas por mitad para concluir")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_senales)
    p = sub.add_parser("markouts", help="Markouts de los trades y llenado de órdenes limit (datos del websocket)")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_markouts)
    for nombre, ayuda, funcion in (
            ("volatilidad", "Volatilidad realizada two-scale y signature plot", cmd_volatilidad),
            ("revalidar", "Revalida con datos posteriores los hallazgos de OFI, lead-lag y señales", cmd_revalidar),
            ("robustez", "Si cada hallazgo se sostiene con los parámetros vecinos", cmd_robustez)):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
        p.set_defaults(func=funcion)
    p = sub.add_parser("liquidez", help="Spread efectivo y realizado, impacto y lambda de Kyle con los trades del websocket")
    p.add_argument("--horas", type=float, default=6, help="Ventana hacia atrás, en horas (reconstruir el libro es lento)")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_liquidez)
    for nombre, ayuda, funcion in (
            ("presion", "Trade imbalance, CVD, intensidad, VWAP frente al mid y exposición neta y bruta", cmd_presion),
            ("respuesta", "Función de respuesta de Bouchaud: impacto permanente y transitorio de un trade", cmd_respuesta)):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("--horas", type=float, default=6, help="Ventana hacia atrás, en horas (reconstruir el libro es lento)")
        p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
        p.set_defaults(func=funcion)
    p = sub.add_parser("velas", help="Velas OHLCV propias desde los trades del websocket")
    p.add_argument("--horas", type=float, default=168, help="Ventana hacia atrás, en horas")
    p.add_argument("--intervalos", type=lambda t: tuple(int(x) for x in t.split(",")), default=(60, 300, 3600, 86400),
                   help="Segundos de cada vela, separados por comas")
    p.set_defaults(func=cmd_velas)
    p = sub.add_parser("historico-kraken", help="Histórico oficial de velas de Kraken (archivo OHLCVT y API)")
    p.add_argument("--archivo", nargs="+", help="Ruta o URL del ZIP (o de sus partes); por defecto, el completo de Kraken")
    p.add_argument("--intervalos-zip", type=lambda t: tuple(int(x) for x in t.split(",")), default=(60, 1440),
                   help="Minutos de las velas que se importan del archivo, separados por comas")
    p.add_argument("--intervalos-rest", type=lambda t: tuple(int(x) for x in t.split(",")), default=(1, 5, 15, 60, 240, 1440),
                   help="Minutos de las velas que se piden a la API (las 720 más recientes), separados por comas")
    p.add_argument("--sin-zip", action="store_true", help="Solo la API (lo reciente), sin el archivo")
    p.set_defaults(func=cmd_historico_kraken)
    p = sub.add_parser("comparar-velas", help="Compara las velas propias con las oficiales de Kraken")
    p.add_argument("--intervalos", type=lambda t: tuple(int(x) for x in t.split(",")), default=(60, 300, 3600, 86400),
                   help="Segundos de las velas que se comparan, separados por comas")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_comparar_velas)
    p = sub.add_parser("retornos", help="Retornos, volatilidad anualizada, colas, agrupamiento y regímenes")
    p.add_argument("--fuente", choices=("propia", "kraken_historico"), default="propia")
    p.add_argument("--intervalo", type=int, default=None, help="Segundos de vela (por defecto, todos)")
    p.add_argument("--exchange", choices=EXCHANGES, default=None)
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_retornos)
    p = sub.add_parser("ofi-eventos", help="OFI evento a evento (Cont-Kukanov-Stoikov) con los cambios del libro")
    p.add_argument("--horas", type=float, default=6, help="Ventana hacia atrás, en horas (reconstruir el libro es lento)")
    p.add_argument("--intervalos", type=lambda t: tuple(float(x) for x in t.split(",")), default=(1.0, 10.0),
                   help="Segundos de cada intervalo de agregación, separados por comas")
    p.add_argument("--minimo", type=int, default=200, help="Intervalos mínimos para concluir")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_ofi_eventos)
    p = sub.add_parser("registro", help="Registro de todas las pruebas y corrección por pruebas múltiples global")
    p.add_argument("--todas", action="store_true", help="Contar todas las ejecuciones, no solo la última de cada estudio")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_registro)
    p = sub.add_parser("relojes", help="Desfase y deriva entre la hora de cada exchange y la nuestra")
    p.add_argument("--horas", type=float, default=24, help="Ventana hacia atrás, en horas")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_relojes)
    p = sub.add_parser("hy", help="Lead-lag en milisegundos (Hayashi-Yoshida) con los cambios del libro del websocket")
    p.add_argument("--horas", type=float, default=2, help="Ventana hacia atrás, en horas (el coste crece con ella)")
    p.add_argument("--rango", type=float, default=5, help="Mayor adelanto probado, en segundos")
    p.add_argument("--paso", type=float, default=0.01, help="Paso de la rejilla de adelantos, en segundos")
    p.add_argument("--sustitutos", type=int, default=199, help="Series rotadas para el p-valor")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_hy)
    p = sub.add_parser("estacionalidad", help="Spread y profundidad por hora del día (UTC) y si dependen de la hora")
    p.add_argument("--banda", type=float, default=10, help="Banda en bps alrededor del mid para la profundidad")
    p.add_argument("--no-guardar", action="store_true", help="Solo mostrar, sin guardar en el lake")
    p.set_defaults(func=cmd_estacionalidad)
    sub.add_parser("catalogo", help="Crea data/quantlab.duckdb para DBeaver").set_defaults(func=cmd_catalogo)
    p = sub.add_parser("consultar", help="Ejecuta SQL sobre el lake")
    p.add_argument("sql")
    p.set_defaults(func=cmd_consultar)
    args = parser.parse_args(argv)
    if args.comando == "flujo" and not set(args.exchanges.split(",")) <= set(EXCHANGES):
        parser.error(f"exchanges disponibles: {', '.join(EXCHANGES)}")
    if getattr(args, "segundos", 1) <= 0:
        parser.error("los segundos deben ser positivos")
    if args.comando in ("relojes", "hy", "liquidez", "presion", "respuesta", "ofi-eventos") and args.horas <= 0:
        parser.error("las horas deben ser positivas")
    if args.comando == "hy" and (args.rango <= 0 or args.paso <= 0 or args.paso > args.rango or args.sustitutos < 19):
        parser.error("rango y paso positivos, paso no mayor que el rango y al menos 19 sustitutos")
    if args.comando == "velas" and (args.horas <= 0 or min(args.intervalos) <= 0):
        parser.error("horas e intervalos positivos")
    if args.comando in ("historico-kraken",) and min(args.intervalos_zip + args.intervalos_rest) <= 0:
        parser.error("los intervalos deben ser positivos")
    if args.comando == "comparar-velas" and min(args.intervalos) <= 0:
        parser.error("los intervalos deben ser positivos")
    if args.comando == "retornos" and args.intervalo is not None and args.intervalo <= 0:
        parser.error("el intervalo debe ser positivo")
    if args.comando == "ofi-eventos" and (min(args.intervalos) <= 0 or args.minimo < 2):
        parser.error("los intervalos deben ser positivos y el mínimo al menos 2")
    if getattr(args, "horizonte", 1) < 1:
        parser.error("el horizonte debe ser de al menos 1 ronda")
    if min(getattr(args, "retardos", (1,))) < 1:
        parser.error("los retardos deben ser de al menos 1 ronda")
    if min(getattr(args, "niveles_ofi", (1,))) < 1:
        parser.error("los niveles del OFI deben ser al menos 1")
    if min(getattr(args, "horizontes", (1,))) < 1 or getattr(args, "minimo", 2) < 2:
        parser.error("los horizontes deben ser al menos 1 y el mínimo al menos 2")
    if getattr(args, "guardar_niveles", 0) < 0:
        parser.error("los niveles guardados no pueden ser negativos")
    if getattr(args, "niveles", 1) < 1:
        parser.error("los niveles deben ser al menos 1")
    if args.comando == "simular" and (args.importe <= 0 or args.trozos < 1 or args.duracion <= 0
                                      or min(args.impactos) < 0 or min(args.urgencias, default=0) < 0
                                      or args.urgencia_adaptativa < 0 or min(args.intensidades, default=0) < 0):
        parser.error("importe y duración positivos, al menos 1 trozo, e impactos, urgencias e intensidades no negativos")
    args.func(args)


if __name__ == "__main__":
    main()
