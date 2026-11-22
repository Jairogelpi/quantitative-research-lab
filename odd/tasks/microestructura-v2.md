Objetivo: cerrar los 7 huecos que quedaban en las Fases 1 y 2 tras `microestructura-profesional`, con datos propios.
Rama: main (commits solo cuando el usuario los pide). Entrega: ask-on-risk. Tests: `python -m pytest -q` desde `proyecto/`.

## Specs

Lista aprobada por el usuario ("haz los 7"):

- S1 · "La revalidación solo existe para el imbalance. El OFI, el lead-lag y las señales guardan resultados, pero nadie los vuelve a probar con datos nuevos para decir 'se mantiene / se debilita / se cae'."
- S2 · "El websocket todavía no se usa en ningún estudio ... medir el lead-lag en milisegundos con el estimador de Hayashi-Yoshida (Hoffmann, Rosenbaum y Yoshida, 2013), que está pensado para datos asíncronos como estos."
- S3 · "Faltan las medidas estándar de liquidez con trades: spread efectivo ..., spread realizado ..., impacto en el precio ..., lambda de Kyle."
- S4 · "Relojes ... no estamos midiendo el desfase entre su reloj y el nuestro. En un lead-lag de 1–3 s, un reloj corrido puede inventar o esconder un líder."
- S5 · "Pruebas múltiples entre estudios ... llevar un registro de todo lo que se probó y corregir sobre el conjunto."
- S6 · "La volatilidad de contexto es ingenua ... Lo estándar es la volatilidad realizada robusta al ruido (por ejemplo, two-scale, con el signature plot para elegir la frecuencia)."
- S7 · "Robustez de los parámetros ... mostrar que el resultado no depende de esa elección: la misma conclusión con bandas o niveles vecinos."

## Tasks

| ID | Specs | Ruta | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | delegada (W1, paralelo) | hecho: `revalidacion.py`, `clasificar` en `hallazgos.py`, `hasta_utc` en LeadLag e ImpactoOFI, 15 tests (RED observado) | — |
| T2 | S2, S4 | delegada (W2, paralelo) | hecho: `relojes.py`, `hayashi_yoshida.py`, 19 tests (RED observado en HY) | — |
| T3 | S3, S6 | delegada (W3, paralelo) | hecho: `liquidez.py`, `volatilidad.py`, `senales.py` usa TSRV de 300 s; 11 tests (RED observado) | — |
| T4 | S5, S7 | delegada (W4, paralelo) | hecho: `registro.py`, `robustez.py`, 10 tests (RED observado) | — |
| T5 | todas | inline | hecho: comandos, curva del decaimiento, estudios re-corridos; verificación independiente: S1–S4, S6, S7 PASS, S5 con 1 bloqueante corregido; 214 tests | — |

Ruta: writers en paralelo por el disparador de paralelismo (4 unidades independientes de varios ficheros) y el de contexto (sesión muy larga). Superficies disjuntas; `__main__.py`, `analisis/__init__.py` y la documentación los edita solo el padre.

## Log

- L1 (2026-11-22) · Usuario repitió: "en las fases 1 yu dos lo hemos hecho como lo hace n los profesionales a dia de hoy faltarian cosas? conclusiones efectos corrrelaciones entre variables etc" → lista de 7 huecos nuevos. Usuario: "haz los 7".
- L2 · Pendiente de commit de la sesión anterior: escritura atómica y nombres únicos en `radar/almacen/lake.py` (154 tests en verde).
- L3 · W4 entregado. Real: 126 pruebas, 36 hallazgos sobreviven BH global (7 caen con Holm/Bonferroni); robustez 31 robustas, 3 frágiles, 7 sin vecinos (decaimiento sin curva guardada). Pendiente del padre: guardar `horizontes`, `betas`, `ts` en `Decaimiento.a_fila()` cuando W3 termine con senales.py; comandos `registro` y `robustez`.
- L4 · W1 entregado. Real: 6 hallazgos OFI predictivos revalidados (4 se mantienen, 2 se debilitan); lead-lag, impacto OFI y aporte quedan pendientes hasta re-correr sus estudios (filas sin `hasta_utc`). Pendiente del padre: comando `revalidar`, usar `guardar_estudio_senales` en `cmd_senales`, re-correr ofi/leadlag/senales.
- L5 · W3 entregado. Real: spread efectivo 2,5–5,8 bps frente a cotizado 0,6–3,2; realizado ≤ 0 e impacto ≥ efectivo en todos — sospechoso: el mid de `libros_flujo` puede tener hasta 1 s de antigüedad. Lambda de Kyle a 5 s: Kraken 8,1 bps por 100.000 € (t 9,9). Signature plot plano: sin ruido detectable en los mids REST. Mejora pendiente: mid exacto antes de cada trade desde `eventos_libro`.
- L6 · W2 entregado. Padre: 7 comandos nuevos, `cmd_senales` guarda con `hasta_utc`, `Decaimiento.a_fila` guarda la curva (test RED → GREEN). Suite 213 en verde. Real: HY con 2 h → los tres pares simultáneos con horas de recepción (el 108 ms de 1 h no se sostiene); registro 39/39 sobreviven BH global; robustez 35 robustas y 8 frágiles; revalidación toda pendiente (estudios recién re-corridos).
- L7 · Verificación independiente: un bloqueante (S5) — el registro ignoraba Hayashi-Yoshida (p en `p_sustitutos`). Corregido con RED → GREEN: `p_sustitutos` en COLUMNAS_P, `base` como parámetro, sujeto `a–b` para filas sin líder, `retardo_ms` excluido de los parámetros (es un resultado; se actualizó un test de W4 que lo fijaba como parámetro). Real: 135 pruebas de 8 estudios, 41/41 sobreviven BH global, 30 con Holm/Bonferroni. `clasificar` idéntico a la base en 22.400 casos; lake con dos escritores y un lector: 600/600 filas, 0 errores. Avisos no bloqueantes: lambda de Kyle entra en la familia sin contar como hallazgo; caracteres no cp1252 si stdout se redirige sin UTF-8 (las tareas programadas ya fijan PYTHONIOENCODING).
- L8 · Usuario pidió los tres pendientes: "Tomar el mid exacto antes de cada trade para la liquidez. / Que la PC sincronice mejor la hora; es un cambio de Windows y lo decidís vos. / Decidir si la lambda de Kyle cuenta en la familia de pruebas".
- L9 · Hecho con RED → GREEN: (1) `mids_desde_eventos` emite también `cotizado_bps` sin cambiar cuándo emite (Hayashi-Yoshida intacto, sus tests pasan); `liquidez` usa por defecto el mid exacto de `eventos_libro` (`--horas 6`) y vuelve a `libros_flujo` si no hay eventos. Efectivo real: 1,5–2,8 bps (antes 2,5–5,8: la mitad era artefacto). (3) Decisión: la lambda cuenta como hallazgo ("impacto significativo"); además `intervalo_` pasa a ser parámetro (5 s y 60 s se fusionaban). Registro: 138 pruebas, 44/46 sobreviven BH global. (2) `w32time` está detenido: la PC no sincroniza; activarlo requiere administrador → decisión del usuario. Suite 218 en verde.
