"""Registro de pruebas: todo lo que el sistema ha probado, corregido por pruebas múltiples sobre el conjunto.

Conceptos:
- Prueba de hipótesis: cada fila guardada por un estudio que contrasta algo con un estadístico (un t o un
  p-valor): el imbalance a una banda y un horizonte, un par líder-seguidor a un retardo, el efecto de la hora...
- Pruebas múltiples entre estudios: cada estudio corrige SUS pruebas con Benjamini-Hochberg, pero el sistema
  hace muchos estudios. Con cientos de pruebas, alguna sale "confirmada" por azar aunque cada estudio, por
  separado, controle su tasa de falsos descubrimientos. Aquí la corrección se aplica sobre TODAS a la vez.
- La familia (qué se corrige junto): una prueba por hipótesis distinta, con su última ejecución. Una hipótesis
  es (fuente, estudio, exchange, parámetros). Repetir el mismo estudio con más datos no es una prueba nueva e
  independiente: casi todos los datos se solapan con la ejecución anterior y el resultado está muy
  correlacionado con ella. Contarla dos veces inflaría la familia (correcciones demasiado severas) y, a la vez,
  la trataría como si fuera una oportunidad más de acertar por azar, que no es. Con `todas_las_ejecuciones`
  se corrige sobre todas las filas guardadas, para ver la cota más pesimista.
- Qué entra: las fuentes `estudios*` y `perfiles_horarios`. No entran las revalidaciones (vuelven a probar un
  hallazgo ya descubierto con datos nuevos: son confirmaciones, no descubrimientos) ni `estudios_robustez`
  (resume otras pruebas, no prueba nada nuevo). Tampoco las filas sin estadístico o con datos insuficientes:
  su estudio no llegó a hacer la prueba.
- Estadístico: el p-valor del descubrimiento si se guardó; si solo se guardó el t, el p-valor bilateral con la
  aproximación normal (`_p_valor`); en los markouts, t = media / error.
- Benjamini-Hochberg (BH) controla la proporción esperada de falsos descubrimientos entre lo que se declara
  hallazgo. Holm y Bonferroni controlan la probabilidad de UN solo falso positivo en toda la familia: son más
  severos y se muestran como comparación.
- Hallazgo: una prueba cuyo estudio la dio por buena ("confirmada", "aporta información propia", "explica el
  precio", "depende de la hora", "con efecto", markouts con efecto).

Estados de cada prueba:
- sobrevive a la corrección global: hallazgo en su estudio y p ajustado por BH sobre toda la familia < `ALFA`.
- no sobrevive a la corrección global: hallazgo en su estudio, pero no con la familia completa.
- sin hallazgo en su estudio: su estudio no la dio por buena (se cuenta igual en la familia).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import pandas as pd
from statsmodels.stats.multitest import multipletests

from .imbalance import ALFA, _p_valor

FUENTE_REGISTRO = "registro_pruebas"
FUENTES_ADICIONALES = ("perfiles_horarios",)
FUENTES_EXCLUIDAS = ("estudios_robustez",)
COLUMNAS_P = ("p_descubrimiento", "p_valor", "p_sustitutos")  # p_sustitutos: Hayashi-Yoshida (rotaciones)
COLUMNAS_T = ("t_descubrimiento", "t_hac", "t_conjunto", "t_interaccion", "t", "t_r1")  # t_r1: R(1) de Bouchaud
NO_PROBADAS = {"datos insuficientes", "calidad de datos insuficiente", "pendiente"}
HALLAZGOS = {"confirmada", "aporta información propia", "explica el precio", "depende de la hora", "con efecto",
             "los takers aciertan (selección adversa para el maker)", "los takers pierden",
             "impacto significativo",  # lambda de Kyle: el volumen neto mueve el precio
             "el lado neto paga sobre el mid", "el lado neto mejora el mid",  # VWAP frente al mid (presión)
             "impacto permanente", "impacto mayormente transitorio", "impacto mixto"}  # respuesta de Bouchaud
PARAMETROS = ("senal", "precio_referencia", "contexto", "variable", "base", "medida", "relacion")
PREFIJOS_PARAMETRO = ("banda_", "niveles", "horizonte_", "retardo_", "ventana_", "frecuencia_", "escala_",
                      "intervalo_", "espera_")

SOBREVIVE, NO_SOBREVIVE = "sobrevive a la corrección global", "no sobrevive a la corrección global"
SIN_HALLAZGO = "sin hallazgo en su estudio"


def fuentes_de_estudios(fuentes) -> list[str]:
    """Las fuentes que guardan pruebas de descubrimiento (ver "Qué entra")."""
    return [f for f in fuentes if (f.startswith("estudios") or f in FUENTES_ADICIONALES)
            and f not in FUENTES_EXCLUIDAS and "revalid" not in f]


def _valor(fila, columna):
    v = fila.get(columna)
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    try:
        return None if pd.isna(v) else v
    except (TypeError, ValueError):  # listas o arrays: no son parámetros escalares
        return None


def _formato(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return f"{v:g}" if isinstance(v, float) else str(v)


def columnas_parametro(columnas) -> list[str]:
    """Columnas que describen los parámetros probados: las conocidas y las de prefijos conocidos, en orden."""
    otras = [c for c in columnas if c.startswith(PREFIJOS_PARAMETRO) and c not in PARAMETROS]
    return [c for c in PARAMETROS if c in columnas] + otras


def describir(fila, columnas) -> str:
    """'banda_bps=5, horizonte_rondas=10': los parámetros con valor de una fila."""
    return ", ".join(f"{c}={_formato(v)}" for c in columnas if (v := _valor(fila, c)) is not None)


def sujeto(fila) -> str:
    """El exchange probado, o 'líder->seguidor' en los estudios entre exchanges."""
    if _valor(fila, "exchange") is not None:
        return str(fila["exchange"])
    # Hayashi-Yoshida: la hipótesis es el par, tenga o no líder (una fila "simultáneo" no lo tiene).
    a, b = _valor(fila, "exchange_a"), _valor(fila, "exchange_b")
    if a is not None and b is not None:
        return f"{a}–{b}"
    lider, seguidor = _valor(fila, "lider"), _valor(fila, "seguidor")
    return f"{lider}->{seguidor}" if lider is not None and seguidor is not None else ""


def nombre_estudio(fila, fuente: str) -> str:
    """La columna `estudio` si la hay; si no, el nombre de la fuente sin el prefijo `estudios_`."""
    return str(_valor(fila, "estudio") or fuente.removeprefix("estudios_") or fuente)


def estadistico(fila) -> tuple[str, float, float, bool] | None:
    """(nombre, valor, p-valor, si el p se derivó del t), o None si la fila no guarda estadístico."""
    for c in COLUMNAS_P:
        if (p := _valor(fila, c)) is not None:
            t_col = next((t for t in COLUMNAS_T if _valor(fila, t) is not None), None)
            return (t_col, float(fila[t_col]), float(p), False) if t_col else (c, float(p), float(p), False)
    for c in COLUMNAS_T:
        if (t := _valor(fila, c)) is not None:
            return c, float(t), _p_valor(float(t)), True
    media, error = _valor(fila, "media_bps"), _valor(fila, "error_bps")
    if media is not None and error:
        t = float(media) / float(error)
        return "media_bps/error_bps", t, _p_valor(t), True
    return None


@dataclass(frozen=True)
class Prueba:
    fuente: str
    estudio: str
    exchange: str
    parametros: str
    ejecutado_utc: pd.Timestamp     # cuándo se ejecutó el estudio que hizo la prueba
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    estadistico: str
    valor: float
    p_valor: float
    p_derivado: bool
    p_ajustado_estudio: float       # el ajuste que hizo su propio estudio (NaN si no corrigió)
    estado_estudio: str
    familia: int
    p_bh: float
    p_holm: float
    p_bonferroni: float

    @property
    def hallazgo(self) -> bool:
        return self.estado_estudio in HALLAZGOS

    @property
    def sobrevive(self) -> bool:
        return self.p_bh < ALFA

    @property
    def estado(self) -> str:
        if not self.hallazgo:
            return SIN_HALLAZGO
        return SOBREVIVE if self.sobrevive else NO_SOBREVIVE

    def conclusion(self) -> str:
        cabecera = f"{self.estudio} ({self.fuente}), {self.exchange}" + (f", {self.parametros}" if self.parametros else "")
        origen = "derivado del t" if self.p_derivado else "guardado"
        return (f"{cabecera}: {self.estado}. En su estudio, {self.estado_estudio}; p {self.p_valor:.2g} ({origen}, "
                f"{self.estadistico} = {self.valor:.2f}); sobre las {self.familia} pruebas, p ajustado BH "
                f"{self.p_bh:.3f}, Holm {self.p_holm:.3f}, Bonferroni {self.p_bonferroni:.3f}.")

    def a_fila(self) -> dict:
        fila = asdict(self)
        fila["ejecutado_estudio_utc"] = fila.pop("ejecutado_utc")
        return {**fila, "hallazgo": self.hallazgo, "estado": self.estado, "conclusion": self.conclusion()}


def _leer(consultar: Callable[[str], pd.DataFrame], fuente: str) -> pd.DataFrame:
    return consultar(f'SELECT * FROM "{fuente}"')


def _candidatas(fuente: str, df: pd.DataFrame) -> list[dict]:
    # `retardo_ms` es el adelanto MEDIDO por Hayashi-Yoshida (un resultado), no un parámetro probado.
    parametros = columnas_parametro([c for c in df.columns if c not in ("lider", "seguidor", "retardo_ms")])
    filas = []
    for fila in df.to_dict("records"):
        if str(_valor(fila, "estado") or "") in NO_PROBADAS or (e := estadistico(fila)) is None:
            continue
        nombre, valor, p, derivado = e
        if math.isnan(p):
            continue
        ajustado = _valor(fila, "p_ajustado")
        filas.append(dict(fuente=fuente, estudio=nombre_estudio(fila, fuente), exchange=sujeto(fila),
                          parametros=describir(fila, parametros), ejecutado_utc=_valor(fila, "ejecutado_utc") or pd.NaT,
                          desde_utc=_valor(fila, "desde_utc") or pd.NaT, hasta_utc=_valor(fila, "hasta_utc") or pd.NaT,
                          estadistico=nombre, valor=valor, p_valor=p, p_derivado=derivado,
                          p_ajustado_estudio=float(ajustado) if ajustado is not None else math.nan,
                          estado_estudio=str(_valor(fila, "estado") or "")))
    return filas


def _ultima_por_hipotesis(filas: list[dict]) -> list[dict]:
    ultimas = {}
    for f in filas:
        clave = (f["fuente"], f["estudio"], f["exchange"], f["parametros"])
        anterior = ultimas.get(clave)
        if anterior is None or (pd.notna(f["ejecutado_utc"])
                                and (pd.isna(anterior["ejecutado_utc"]) or f["ejecutado_utc"] > anterior["ejecutado_utc"])):
            ultimas[clave] = f
    return list(ultimas.values())


def registrar_pruebas(consultar: Callable[[str], pd.DataFrame], fuentes, todas_las_ejecuciones: bool = False
                      ) -> list[Prueba]:
    """Una `Prueba` por hipótesis (su última ejecución) de todas las fuentes de estudios, con BH, Holm y
    Bonferroni sobre la familia completa. Las fuentes que no existen o no tienen estadístico se ignoran."""
    filas = []
    for fuente in fuentes_de_estudios(fuentes):
        filas += _candidatas(fuente, _leer(consultar, fuente))
    if not todas_las_ejecuciones:
        filas = _ultima_por_hipotesis(filas)
    if not filas:
        return []
    p = [f["p_valor"] for f in filas]
    bh, holm, bonferroni = (multipletests(p, method=m)[1] for m in ("fdr_bh", "holm", "bonferroni"))
    pruebas = [Prueba(**f, familia=len(filas), p_bh=float(a), p_holm=float(b), p_bonferroni=float(c))
               for f, a, b, c in zip(filas, bh, holm, bonferroni)]
    return sorted(pruebas, key=lambda x: (x.fuente, x.estudio, x.exchange, x.parametros, str(x.ejecutado_utc)))


def resumen_registro(pruebas: list[Prueba]) -> str:
    """Cuántas pruebas hay, cuántos hallazgos y cuántos aguantan la corrección global con cada método."""
    if not pruebas:
        return "No hay pruebas registradas: ningún estudio guardado tiene un estadístico que corregir."
    hallazgos = [p for p in pruebas if p.hallazgo]
    estudios = len({(p.fuente, p.estudio) for p in pruebas})
    texto = (f"Registro: {len(pruebas)} pruebas de {estudios} estudios (familia: la última ejecución de cada "
             f"hipótesis distinta). Hallazgos en su propio estudio: {len(hallazgos)}.")
    if hallazgos:
        bh = sum(p.sobrevive for p in hallazgos)
        holm = sum(p.p_holm < ALFA for p in hallazgos)
        bonferroni = sum(p.p_bonferroni < ALFA for p in hallazgos)
        texto += (f" Con Benjamini-Hochberg sobre toda la familia (α {ALFA:g}) sobreviven {bh} de {len(hallazgos)}; "
                  f"con Holm, {holm}; con Bonferroni, {bonferroni}.")
        caidos = [p for p in hallazgos if not p.sobrevive]
        if caidos:
            texto += " Hallazgos que no sobreviven: " + "; ".join(
                f"{p.estudio} {p.exchange} {p.parametros} (p {p.p_valor:.2g}, BH {p.p_bh:.3f})".replace("  ", " ")
                for p in caidos) + "."
    return texto


def guardar_registro(pruebas, almacen, ejecutado_utc: pd.Timestamp) -> list:
    """Guarda el registro en `registro_pruebas`: una fila por prueba, con la ejecución del registro."""
    return almacen.guardar([{"ejecutado_utc": ejecutado_utc, "recibido_utc": ejecutado_utc, **p.a_fila()}
                            for p in pruebas], FUENTE_REGISTRO)
