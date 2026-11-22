"""Protocolo registrado ANTES de mirar: ¿sigue Kraken a OKX y Bitvavo? Evaluado solo con datos posteriores (Fase 6).

Conceptos:
- Protocolo previo (preregistro): hipótesis, mecanismo, señal, objetivo, regla de operación, métricas, reglas de
  decisión y muestra mínima se escriben y se fijan antes de ver los datos con los que se prueban. Así ningún
  parámetro se elige mirando el resultado (el "jardín de los senderos que se bifurcan"). Es el E1 de P17:
  "documentar una hipótesis económica alternativa y el mecanismo, escribiendo el protocolo ANTES de analizar la
  prueba" (`src/quantlab/p17/integrated_research.py::register_protocol`, docs/conceptos/investigacion_integral.md).
  P17 probó Kraken → OKX y no lo encontró; la alternativa, que apoyan `leadlag` y `senales`, es OKX y Bitvavo →
  Kraken.
- Huella: SHA-256 del JSON ordenado del protocolo (`Protocolo.texto`). Cambiar cualquier campo cambia la huella.
  `registrar_protocolo` guarda huella, texto y `registrado_utc` en `protocolos_registrados`, y se niega si el lake
  ya tiene eventos del libro recibidos después de esa hora (sería un registro retroactivo: esos datos ya se podían
  haber mirado).
- Solo datos posteriores: `evaluar_protocolo` lee `eventos_libro` con `recibido_utc` ESTRICTAMENTE posterior a
  `registrado_utc`. Ni siquiera el snapshot anterior sirve para reconstruir el libro: el libro empieza en el primer
  snapshot recibido después del registro (la captura recibe uno al conectar, cada tramo de una hora).
- Señal (en la hora de recepción, la nuestra): media de ln(mid(t) / mid(t − Δ)) de OKX y Bitvavo, en bps, con el
  mid vigente en cada instante (el del último mensaje recibido en o antes, `hayashi_yoshida.mejores_desde_eventos`:
  el libro exacto reconstruido mensaje a mensaje). Lo recibido justo en t ya se conoce en t; un ms después, no.
- Objetivo: ln(mid_K(t_e + H) / mid_K(t_e)) de Kraken, con t_e = t + latencia + retardo de decisión. Se entra al
  precio vigente en t_e (el que encontraría una orden que llega a Kraken en t_e), nunca al de t.
- Rejilla de decisiones: una cada `paso_s` segundos, con paso ≥ latencia + retardo + H, así que los objetivos de
  decisiones seguidas no se solapan (las operaciones no se pisan y el bootstrap y el null no ven solapamiento).
- Regla de operación: si |señal| > umbral, se compra (señal > 0) o se vende (señal < 0) `tamano_btc` y se deshace
  a los H segundos. Taker: entra al ask (o bid) y sale al bid (o ask), comisión taker por lado; si el mejor nivel
  no tiene `tamano_btc`, el resultado es desconocido (NaN, no cero: excluirlo sería una selección ex post, P17).
  Maker (cota optimista): entra y sale al mid con comisión maker y sin contar las órdenes que no se ejecutarían
  ni la selección adversa. Si ni así gana, no hay negocio. Vender exige poder ponerse corto (margen en Kraken).
- IC (information coefficient): correlación de Pearson entre señal y objetivo; su t con errores Newey-West
  (Newey y West, 1987, Econometrica 55, 703-708) de objetivo ~ señal estandarizada (`imbalance._retardos`).
- Null circular: correlación con el objetivo desplazado circularmente (conserva la autocorrelación de cada serie,
  a diferencia de barajar). p unilateral = (1 + #{null ≥ observada}) / (1 + n). Es la idea de
  `circular_shift_null` de P17 y de las rotaciones de `hayashi_yoshida`.
- R² fuera de muestra (Campbell y Thompson, 2008, Review of Financial Studies 21, 1509-1531): la recta se ajusta
  en la primera `fraccion_ajuste` (en orden temporal) y se congela; R² = 1 − SSE(recta) / SSE(media del ajuste) en
  el resto (`predictability` de P17). Positivo = predice mejor que la media histórica.
- Bootstrap por bloques circulares (Künsch, 1989, Annals of Statistics 17, 1217-1241; Politis y Romano, 1992):
  remuestrea bloques contiguos de operaciones para respetar la dependencia temporal; intervalo percentil de la
  media del PnL neto por operación (`block_ci` de P17).
- Decisión estadística: IC > 0, p circular < α y R² fuera de muestra > 0. Decisión económica (por separado, P17
  conclusión 12): límite inferior del intervalo del PnL neto taker por operación > 0. Predecir no es ganar.
- Una sola evaluación por protocolo (como la muestra guardada de `prediccion`): la apertura se registra antes de
  calcular y una segunda evaluación confirmatoria se rechaza. Se permite un SEGUIMIENTO, etiquetado, con los datos
  recibidos después de la última evaluación: no cambia la decisión, solo dice si el efecto sigue ahí. Sin la
  muestra mínima, la evaluación no se abre ("esperando datos").
- Desarrollo (`comprobar_desarrollo`): mismas medidas con datos ANTERIORES al registro, solo para comprobar que la
  tubería funciona. No decide, no se guarda y la evaluación no lo lee.
- Fuentes: Nosek et al. (2018), "The preregistration revolution", PNAS 115, 2600-2606; López de Prado (2018),
  Advances in Financial Machine Learning, cap. 11-12 (el peligro del backtest repetido); P17 (conclusiones 1-12).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm

from radar.configuracion import COMISIONES_TAKER

from .hayashi_yoshida import PARAMETROS_LIBRO, mejores_desde_eventos
from .imbalance import _p_valor, _retardos, _t

METODO = "protocolo_leadlag/v1"
FUENTE_PROTOCOLOS = "protocolos_registrados"
FUENTE_ESTUDIOS = "estudios_protocolo"
FUENTE_APERTURAS = "aperturas_protocolo"
NS = 1_000_000_000

CONFIRMATORIA, SEGUIMIENTO, DESARROLLO = "confirmatoria", "seguimiento", "desarrollo"
ESPERANDO, LISTA, EVALUADA = "esperando datos", "lista para evaluar", "evaluada"
COLUMNAS_COTIZACIONES = ["exchange", "recibido_ns", "bid", "ask", "bid_cantidad", "ask_cantidad"]


class ProtocoloYaRegistrado(RuntimeError):
    """Ese protocolo (misma huella) ya está registrado: registrarlo otra vez movería su hora de registro."""


class ProtocoloYaEvaluado(RuntimeError):
    """El protocolo ya tuvo su evaluación confirmatoria: no se evalúa dos veces."""


@dataclass(frozen=True)
class Protocolo:
    """Todo lo que decide la prueba. Cada campo entra en la huella."""
    nombre: str = "kraken_sigue_a_okx_y_bitvavo"
    hipotesis: str = ("El mid de Kraken BTC/EUR sigue al de OKX y Bitvavo: el retorno reciente del mid de OKX y "
                      "Bitvavo predice el retorno del mid de Kraken en los segundos siguientes, con datos "
                      "capturados después del registro. Hallazgos previos: `leadlag` (rondas REST de 1 s) da a "
                      "Kraken como seguidor de OKX y Bitvavo a 1-3 s, robusto a la latencia en los retardos 2 y "
                      "3; `senales.senal_lider` (el retorno de los otros exchanges en la ronda anterior) predice "
                      "a Kraken con +0,32 bps por desviación típica a 5 rondas (t 11). P17 probó la dirección "
                      "contraria (Kraken → OKX) y no la encontró.")
    mecanismo: str = ("El libro de Kraken se actualiza y parpadea distinto: su mejor nivel cambia menos a menudo "
                      "y con menos creadores de mercado rápidos en BTC/EUR, así que incorpora con retraso la "
                      "información que ya movió los libros de OKX y Bitvavo; el arbitraje entre exchanges cierra "
                      "la diferencia en pocos segundos. Si es así, el efecto es real pero pequeño frente a las "
                      "comisiones de Kraken.")
    objetivo: str = "kraken"
    lideres: tuple = ("okx", "bitvavo")
    base_tiempo: str = "recepción (reloj local), mids exactos del libro reconstruido desde eventos_libro"
    paso_s: float = 10.0                 # una decisión cada 10 s (≥ latencia + retardo + horizonte)
    ventana_senal_s: float = 2.0         # Δ: retornos de los líderes en los 2 s anteriores (retardos 2-3 robustos)
    # Retraso total 0,3 s, fijado ANTES de registrar con la latencia medida (`relojes`, 22-11-2026), no con la
    # comprobación de desarrollo: ida y vuelta mínima 42 ms a Kraken y 287 ms a OKX (la más lenta).
    latencia_s: float = 0.29             # la ida y vuelta más lenta medida (OKX, 287 ms)
    retardo_decision_s: float = 0.01     # tiempo para calcular y decidir
    horizonte_s: float = 5.0             # H: el horizonte de `senales` (5 rondas de 1 s)
    antiguedad_max_s: float = 60.0       # un mid sin mensajes durante más tiempo no vale
    umbral_bps: float = 1.0              # |señal| mínima para operar, fijada a priori (no calibrada)
    tamano_btc: float = 0.01
    comision_taker: float = COMISIONES_TAKER["kraken"][0]   # 0,80 % por lado
    comision_maker: float = 0.0040                           # kraken.com/pro/fees, primer nivel
    fraccion_ajuste: float = 0.5
    alfa: float = 0.05
    n_nulos: int = 999
    min_desplazamiento: int = 30         # desplazamiento circular mínimo, en decisiones (5 min)
    bloque_bootstrap: int = 10           # operaciones por bloque
    repeticiones_bootstrap: int = 2000
    nivel_ic: float = 0.95
    semilla: int = 20261122
    min_decisiones: int = 2000           # ≈ 5,6 h de decisiones válidas
    min_operaciones: int = 200
    regla_estadistica: str = "IC > 0 y p circular < alfa y R² fuera de muestra > 0"
    regla_economica: str = "límite inferior del IC bootstrap del PnL neto taker por operación > 0"
    metodo: str = METODO

    def texto(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    def huella(self) -> str:
        return hashlib.sha256(self.texto().encode("utf-8")).hexdigest()

    @classmethod
    def desde_texto(cls, texto: str) -> "Protocolo":
        datos = json.loads(texto)
        return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in datos.items()})


PROTOCOLO_KRAKEN = Protocolo()


def _validar(p: Protocolo) -> None:
    if p.paso_s < p.latencia_s + p.retardo_decision_s + p.horizonte_s:
        raise ValueError("El paso entre decisiones tiene que cubrir latencia + retardo + horizonte (sin solapes).")
    if not 0 < p.fraccion_ajuste < 1:
        raise ValueError("La fracción de ajuste tiene que estar entre 0 y 1.")


def _ts(t) -> str:
    return pd.Timestamp(t).isoformat()


def _ahora(ahora) -> pd.Timestamp:
    return (pd.Timestamp.now(tz="UTC") if ahora is None else pd.Timestamp(ahora)).floor("us")


# --- registro -----------------------------------------------------------------------------------------------


def registrar_protocolo(lake, protocolo: Protocolo = PROTOCOLO_KRAKEN, ahora=None) -> str:
    """Guarda huella, texto y hora de registro. Devuelve la huella. Se niega si ya está registrado o si el lake ya
    tiene eventos del libro recibidos después de la hora de registro (registro retroactivo)."""
    registrado = _ahora(ahora)
    huella, fuentes = protocolo.huella(), lake.fuentes()
    if FUENTE_PROTOCOLOS in fuentes and len(lake.consultar(
            f"SELECT 1 FROM {FUENTE_PROTOCOLOS} WHERE protocolo_hash = '{huella}' LIMIT 1")):
        raise ProtocoloYaRegistrado(f"El protocolo {huella[:12]} ya está registrado.")
    if "eventos_libro" in fuentes and len(lake.consultar(
            f"SELECT 1 FROM eventos_libro WHERE recibido_utc > TIMESTAMPTZ '{_ts(registrado)}' LIMIT 1")):
        raise ValueError("Registro retroactivo: el lake ya tiene eventos recibidos después de esa hora.")
    lake.guardar([{"protocolo_hash": huella, "nombre": protocolo.nombre, "metodo": protocolo.metodo,
                   "texto": protocolo.texto(), "registrado_utc": registrado, "recibido_utc": registrado}],
                 FUENTE_PROTOCOLOS)
    return huella


def leer_protocolo(consultar, huella: str) -> tuple[Protocolo, pd.Timestamp]:
    """(protocolo, registrado_utc) de una huella; comprueba que el texto guardado sigue dando esa huella."""
    filas = consultar(f"SELECT texto, registrado_utc FROM {FUENTE_PROTOCOLOS} WHERE protocolo_hash = '{huella}'")
    if filas.empty:
        raise ValueError(f"No hay ningún protocolo registrado con la huella {huella[:12]}.")
    texto = filas.texto.iloc[0]
    if hashlib.sha256(texto.encode("utf-8")).hexdigest() != huella:
        raise ValueError(f"El texto guardado del protocolo {huella[:12]} no corresponde a su huella.")
    return Protocolo.desde_texto(texto), pd.Timestamp(filas.registrado_utc.iloc[0]).tz_convert("UTC")


# --- datos: señal y objetivo --------------------------------------------------------------------------------


def cotizaciones_flujo(consultar, desde_exclusivo, hasta, exchanges) -> pd.DataFrame:
    """Mejor bid/ask tras cada mensaje del libro de cada exchange, reconstruido SOLO con eventos recibidos después
    de `desde_exclusivo` y hasta `hasta` (incluido). Columnas `COLUMNAS_COTIZACIONES`."""
    partes = []
    for ex in exchanges:
        eventos = consultar(f"""SELECT recibido_utc, hora_exchange_utc, tipo, lado, precio, cantidad, secuencia
                                FROM eventos_libro WHERE exchange = '{ex}'
                                AND recibido_utc > TIMESTAMPTZ '{_ts(desde_exclusivo)}'
                                AND recibido_utc <= TIMESTAMPTZ '{_ts(hasta)}' ORDER BY recibido_utc""")
        mejores = mejores_desde_eventos(eventos, **PARAMETROS_LIBRO.get(ex, {}))
        partes.append(mejores.assign(exchange=ex)[COLUMNAS_COTIZACIONES])
    if not partes:
        return pd.DataFrame(columns=COLUMNAS_COTIZACIONES)
    return pd.concat(partes, ignore_index=True)


class _Vigente:
    """Índice del último mensaje recibido en o antes de cada instante (−1 si no hay o tiene más de `tolerancia`)."""

    def __init__(self, g: pd.DataFrame, tolerancia_ns: int):
        g = g.sort_values("recibido_ns", kind="stable")
        self.t = g["recibido_ns"].to_numpy(np.int64)
        self.bid, self.ask = g["bid"].to_numpy(float), g["ask"].to_numpy(float)
        self.bq, self.aq = g["bid_cantidad"].to_numpy(float), g["ask_cantidad"].to_numpy(float)
        self.mid = (self.bid + self.ask) / 2
        self.tolerancia = tolerancia_ns

    def indice(self, instantes: np.ndarray) -> np.ndarray:
        i = np.searchsorted(self.t, instantes, side="right") - 1
        ok = (i >= 0) & (instantes - self.t[np.maximum(i, 0)] <= self.tolerancia) & (instantes <= self.t[-1])
        return np.where(ok, i, -1)

    def valor(self, columna: np.ndarray, i: np.ndarray) -> np.ndarray:
        return np.where(i >= 0, columna[np.maximum(i, 0)], np.nan)


COLUMNAS_DECISIONES = ["t_ns", "senal_bps", "objetivo_bps", "mid_entrada", "bid_entrada", "ask_entrada",
                       "bid_cantidad_entrada", "ask_cantidad_entrada", "mid_salida", "bid_salida", "ask_salida",
                       "bid_cantidad_salida", "ask_cantidad_salida"]


def tabla_decisiones(cotizaciones: pd.DataFrame, p: Protocolo) -> pd.DataFrame:
    """Una fila por decisión de la rejilla: señal en t, precios de Kraken en t_e = t + latencia + retardo y en
    t_e + H, y el objetivo. Solo decisiones cuya salida cae dentro de lo observado."""
    _validar(p)
    necesarios = [p.objetivo, *p.lideres]
    libros = {ex: _Vigente(g, int(round(p.antiguedad_max_s * NS))) for ex, g in cotizaciones.groupby("exchange")}
    if any(ex not in libros or not len(libros[ex].t) for ex in necesarios):
        return pd.DataFrame(columns=COLUMNAS_DECISIONES)
    paso, ventana = int(round(p.paso_s * NS)), int(round(p.ventana_senal_s * NS))
    entrada, horizonte = int(round((p.latencia_s + p.retardo_decision_s) * NS)), int(round(p.horizonte_s * NS))
    inicio = max(libros[ex].t[0] for ex in necesarios) + ventana
    inicio = -(-inicio // paso) * paso
    fin = min(libros[ex].t[-1] for ex in necesarios) - entrada - horizonte
    t = np.arange(inicio, fin + 1, paso, dtype=np.int64)
    if not len(t):
        return pd.DataFrame(columns=COLUMNAS_DECISIONES)
    retornos = []
    for ex in p.lideres:
        lb = libros[ex]
        ahora, antes = lb.valor(lb.mid, lb.indice(t)), lb.valor(lb.mid, lb.indice(t - ventana))
        retornos.append(np.log(ahora / antes) * 1e4)
    senal = np.mean(np.vstack(retornos), axis=0)      # NaN si falta algún líder
    k = libros[p.objetivo]
    ie, isal = k.indice(t + entrada), k.indice(t + entrada + horizonte)
    d = pd.DataFrame({"t_ns": t, "senal_bps": senal})
    for sufijo, i in (("entrada", ie), ("salida", isal)):
        d[f"mid_{sufijo}"], d[f"bid_{sufijo}"], d[f"ask_{sufijo}"] = k.valor(k.mid, i), k.valor(k.bid, i), \
            k.valor(k.ask, i)
        d[f"bid_cantidad_{sufijo}"], d[f"ask_cantidad_{sufijo}"] = k.valor(k.bq, i), k.valor(k.aq, i)
    d["objetivo_bps"] = np.log(d.mid_salida / d.mid_entrada) * 1e4
    return d[COLUMNAS_DECISIONES]


def _validas(d: pd.DataFrame) -> pd.DataFrame:
    return d[np.isfinite(d.senal_bps.astype(float)) & np.isfinite(d.objetivo_bps.astype(float))].reset_index(
        drop=True)


# --- piezas estadísticas ------------------------------------------------------------------------------------


def r2_fuera_de_muestra(senal, objetivo, fraccion: float) -> tuple[float, float, int, int]:
    """(R² fuera de muestra, pendiente del ajuste, n ajuste, n prueba): recta ajustada en la primera `fraccion`
    (orden temporal) y congelada; R² = 1 − SSE(recta) / SSE(media del ajuste) en el resto."""
    x, y = np.asarray(senal, float), np.asarray(objetivo, float)
    corte = int(len(x) * fraccion)
    if corte < 3 or len(x) - corte < 3:
        return math.nan, math.nan, corte, len(x) - corte
    ajuste = sm.OLS(y[:corte], sm.add_constant(x[:corte], has_constant="add")).fit()
    a, b = float(ajuste.params[0]), float(ajuste.params[1])
    prueba_x, prueba_y = x[corte:], y[corte:]
    sse = float(((prueba_y - (a + b * prueba_x)) ** 2).sum())
    sst = float(((prueba_y - y[:corte].mean()) ** 2).sum())
    return (1 - sse / sst if sst > 0 else math.nan), b, corte, len(x) - corte


def ic_bootstrap_bloques(valores, bloque: int, repeticiones: int, semilla: int, nivel: float = 0.95):
    """Intervalo percentil de la media con bootstrap de bloques circulares contiguos (los NaN se ignoran)."""
    v = np.asarray(valores, float)
    if not np.isfinite(v).any():
        return math.nan, math.nan
    rng, n = np.random.default_rng(semilla), len(v)
    inicios = rng.integers(0, n, size=(repeticiones, int(math.ceil(n / bloque))))
    idx = ((inicios[:, :, None] + np.arange(bloque)) % n).reshape(repeticiones, -1)[:, :n]
    with np.errstate(invalid="ignore"):
        medias = np.nanmean(v[idx], axis=1)
    inf, sup = np.nanquantile(medias, [(1 - nivel) / 2, 1 - (1 - nivel) / 2])
    return float(inf), float(sup)


def nulo_circular(x, y, n_nulos: int, min_desplazamiento: int, semilla: int) -> dict:
    """Correlación observada y su p unilateral frente a desplazamientos circulares de y (pares finitos)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 2 * min_desplazamiento + 2:
        raise ValueError("Muestra demasiado corta para el null circular.")
    rng = np.random.default_rng(semilla)
    observada = float(np.corrcoef(x, y)[0, 1])
    nulos = np.array([np.corrcoef(x, np.roll(y, s))[0, 1]
                      for s in rng.integers(min_desplazamiento, n - min_desplazamiento, n_nulos)])
    return {"n": n, "observada": observada, "p_circular": float((1 + (nulos >= observada).sum()) / (1 + n_nulos)),
            "desviacion_nula": float(nulos.std())}


def decision_estadistica(ic: float, p_circular: float, r2_fuera: float, alfa: float) -> bool:
    valores = (ic, p_circular, r2_fuera)
    return all(map(math.isfinite, valores)) and ic > 0 and p_circular < alfa and r2_fuera > 0


def decision_economica(ic_inferior_bps: float) -> bool:
    return math.isfinite(ic_inferior_bps) and ic_inferior_bps > 0


def _ic_hac(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    z = (x - x.mean()) / x.std() if x.std() > 0 else x * 0
    ajuste = sm.OLS(y, sm.add_constant(z, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": _retardos(len(y), 1)})
    t = _t(float(ajuste.params[1]), float(ajuste.bse[1]))
    return t, _p_valor(t)


def _operaciones(d: pd.DataFrame, p: Protocolo) -> dict[str, dict]:
    """PnL por operación (bps sobre el nominal de entrada) de las variantes taker y maker."""
    ops = d[d.senal_bps.abs() > p.umbral_bps]
    lado = np.sign(ops.senal_bps.to_numpy(float))
    largo = lado > 0
    bruto = lado * (ops.mid_salida - ops.mid_entrada).to_numpy(float) / ops.mid_entrada.to_numpy(float) * 1e4
    entrada = np.where(largo, ops.ask_entrada, ops.bid_entrada)
    salida = np.where(largo, ops.bid_salida, ops.ask_salida)
    hay = np.where(largo, (ops.ask_cantidad_entrada >= p.tamano_btc) & (ops.bid_cantidad_salida >= p.tamano_btc),
                   (ops.bid_cantidad_entrada >= p.tamano_btc) & (ops.ask_cantidad_salida >= p.tamano_btc))
    taker = (lado * (salida - entrada) / entrada - p.comision_taker * (1 + salida / entrada)) * 1e4
    taker = np.where(hay, taker, np.nan)
    m_e, m_s = ops.mid_entrada.to_numpy(float), ops.mid_salida.to_numpy(float)
    maker = (lado * (m_s - m_e) / m_e - p.comision_maker * (1 + m_s / m_e)) * 1e4
    salida_ = {}
    for nombre, neto, sin in (("taker", taker, int((~hay).sum())), ("maker", maker, 0)):
        inf, sup = ic_bootstrap_bloques(neto, p.bloque_bootstrap, p.repeticiones_bootstrap, p.semilla, p.nivel_ic)
        finitos = neto[np.isfinite(neto)]
        salida_[nombre] = {"n_operaciones": int(len(ops)), "sin_profundidad": sin,
                           "bruto_medio_bps": float(bruto.mean()) if len(bruto) else math.nan,
                           "neto_medio_bps": float(finitos.mean()) if len(finitos) else math.nan,
                           "ic_inferior_bps": inf, "ic_superior_bps": sup,
                           "neto_total_eur": float((finitos / 1e4 * p.tamano_btc * m_e[np.isfinite(neto)]).sum())}
    return salida_


# --- resultados ---------------------------------------------------------------------------------------------


def _fecha(ns) -> str:
    return f"{pd.Timestamp(int(ns), tz='UTC'):%Y-%m-%d %H:%M:%S}"


@dataclass(frozen=True)
class EstadoEvaluacion:
    """La evaluación no se abrió: falta muestra."""
    protocolo_hash: str
    estado: str
    decisiones_disponibles: int
    decisiones_necesarias: int
    operaciones_disponibles: int
    operaciones_necesarias: int
    limite_inferior_utc: pd.Timestamp
    hasta_utc: pd.Timestamp

    def texto(self) -> str:
        return (f"Protocolo {self.protocolo_hash[:12]}: {self.estado}. Decisiones válidas "
                f"{self.decisiones_disponibles} de {self.decisiones_necesarias}; operaciones "
                f"{self.operaciones_disponibles} de {self.operaciones_necesarias} (datos recibidos después de "
                f"{self.limite_inferior_utc:%Y-%m-%d %H:%M:%S} y hasta {self.hasta_utc:%Y-%m-%d %H:%M:%S} UTC). "
                "No se ha abierto la evaluación.")


@dataclass(frozen=True)
class ResultadoProtocolo:
    protocolo_hash: str
    nombre: str
    tipo: str
    limite_inferior_utc: pd.Timestamp
    desde_utc: pd.Timestamp
    hasta_utc: pd.Timestamp
    n_decisiones: int
    n_ajuste: int
    n_prueba: int
    ic: float
    t_ic_hac: float
    p_ic_hac: float
    p_circular: float
    r2_fuera: float
    pendiente_ajuste: float
    umbral_bps: float
    horizonte_s: float
    taker: dict = field(default_factory=dict)
    maker: dict = field(default_factory=dict)
    decision_estadistica: bool = False
    decision_economica: bool = False
    decision_economica_maker: bool = False

    def a_fila(self) -> dict:
        fila = {k: v for k, v in asdict(self).items() if k not in ("taker", "maker")}
        for variante in ("taker", "maker"):
            fila.update({f"{variante}_{k}": v for k, v in getattr(self, variante).items()})
        return fila

    def conclusion(self) -> str:
        def si(x):
            return "APROBADA" if x else "NO APROBADA"
        t, m = self.taker, self.maker
        cabecera = (f"Protocolo {self.protocolo_hash[:12]} ({self.tipo}), datos de {self.desde_utc:%Y-%m-%d %H:%M:%S} "
                    f"a {self.hasta_utc:%Y-%m-%d %H:%M:%S} UTC, {self.n_decisiones} decisiones. ")
        medidas = (f"IC {self.ic:.3f} (t HAC {self.t_ic_hac:.1f}, p circular {self.p_circular:.4f}), R² fuera de "
                   f"muestra {self.r2_fuera:.2%}. Taker: {t['n_operaciones']} operaciones con |señal| > "
                   f"{self.umbral_bps:g} bps, bruto medio {t['bruto_medio_bps']:+.2f} bps, neto medio "
                   f"{t['neto_medio_bps']:+.2f} bps, IC [{t['ic_inferior_bps']:+.2f}; {t['ic_superior_bps']:+.2f}] "
                   f"bps ({t['sin_profundidad']} sin profundidad). Maker (cota optimista): neto medio "
                   f"{m['neto_medio_bps']:+.2f} bps, IC [{m['ic_inferior_bps']:+.2f}; {m['ic_superior_bps']:+.2f}].")
        if self.tipo == DESARROLLO:
            return (cabecera + medidas + " Comprobación de desarrollo con datos anteriores al registro: no decide "
                    "nada y no se guarda.")
        decisiones = (f"Decisión estadística: {si(self.decision_estadistica)}. Decisión económica: "
                      f"{si(self.decision_economica)}"
                      + (" (ni siquiera la cota maker gana)." if not self.decision_economica_maker else ".") + " ")
        nota = (" Es un seguimiento con datos posteriores a la evaluación confirmatoria: no cambia su decisión."
                if self.tipo == SEGUIMIENTO else "")
        return cabecera + decisiones + medidas + nota


def _medir(d: pd.DataFrame, p: Protocolo, huella: str, tipo: str, limite, hasta, desde) -> ResultadoProtocolo:
    x, y = d.senal_bps.to_numpy(float), d.objetivo_bps.to_numpy(float)
    nulo = nulo_circular(x, y, p.n_nulos, p.min_desplazamiento, p.semilla)
    t_hac, p_hac = _ic_hac(x, y)
    r2, pendiente, n_ajuste, n_prueba = r2_fuera_de_muestra(x, y, p.fraccion_ajuste)
    ops = _operaciones(d, p)
    decide = tipo != DESARROLLO
    return ResultadoProtocolo(
        protocolo_hash=huella, nombre=p.nombre, tipo=tipo, limite_inferior_utc=pd.Timestamp(limite),
        desde_utc=desde, hasta_utc=pd.Timestamp(hasta), n_decisiones=len(d), n_ajuste=n_ajuste, n_prueba=n_prueba,
        ic=nulo["observada"], t_ic_hac=t_hac, p_ic_hac=p_hac, p_circular=nulo["p_circular"], r2_fuera=r2,
        pendiente_ajuste=pendiente, umbral_bps=p.umbral_bps, horizonte_s=p.horizonte_s, taker=ops["taker"],
        maker=ops["maker"],
        decision_estadistica=decide and decision_estadistica(nulo["observada"], nulo["p_circular"], r2, p.alfa),
        decision_economica=decide and decision_economica(ops["taker"]["ic_inferior_bps"]),
        decision_economica_maker=decide and decision_economica(ops["maker"]["ic_inferior_bps"]))


def _muestra(lake, p: Protocolo, limite, hasta) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    cot = cotizaciones_flujo(lake.consultar, limite, hasta, [p.objetivo, *p.lideres])
    desde = pd.Timestamp(int(cot.recibido_ns.min()), tz="UTC") if len(cot) else None
    return _validas(tabla_decisiones(cot, p)), desde


def _aperturas(consultar, fuentes, huella: str) -> pd.DataFrame:
    if FUENTE_APERTURAS not in fuentes:
        return pd.DataFrame(columns=["tipo", "hasta_utc"])
    return consultar(f"SELECT tipo, hasta_utc FROM {FUENTE_APERTURAS} WHERE protocolo_hash = '{huella}'")


def evaluar_protocolo(lake, huella: str, ahora=None, seguimiento: bool = False):
    """Evalúa un protocolo registrado UNA vez, solo con eventos recibidos después de `registrado_utc` (o, en un
    seguimiento, después de la última evaluación). Sin la muestra mínima devuelve un `EstadoEvaluacion` ("esperando
    datos") sin abrir nada; si no, registra la apertura, calcula, guarda en `estudios_protocolo` y devuelve el
    `ResultadoProtocolo`."""
    hasta = _ahora(ahora)
    protocolo, registrado = leer_protocolo(lake.consultar, huella)
    aperturas = _aperturas(lake.consultar, lake.fuentes(), huella)
    confirmada = (aperturas.tipo == CONFIRMATORIA).any()
    if seguimiento and not confirmada:
        raise ValueError("Un seguimiento necesita antes la evaluación confirmatoria.")
    if not seguimiento and confirmada:
        raise ProtocoloYaEvaluado(f"El protocolo {huella[:12]} ya tuvo su evaluación confirmatoria: no se evalúa "
                                  "dos veces. Usa un seguimiento (no cambia la decisión) o registra un protocolo nuevo.")
    limite = pd.to_datetime(aperturas.hasta_utc, utc=True).max() if seguimiento else registrado
    tipo = SEGUIMIENTO if seguimiento else CONFIRMATORIA
    d, desde = _muestra(lake, protocolo, limite, hasta)
    n_ops = int((d.senal_bps.abs() > protocolo.umbral_bps).sum())
    if len(d) < protocolo.min_decisiones or n_ops < protocolo.min_operaciones:
        return EstadoEvaluacion(huella, ESPERANDO, len(d), protocolo.min_decisiones, n_ops,
                                protocolo.min_operaciones, limite, hasta)
    lake.guardar([{"protocolo_hash": huella, "tipo": tipo, "abierta_utc": hasta, "recibido_utc": hasta,
                   "limite_inferior_utc": limite, "hasta_utc": hasta, "n_decisiones": len(d)}], FUENTE_APERTURAS)
    resultado = _medir(d, protocolo, huella, tipo, limite, hasta, desde)
    lake.guardar([{"metodo": protocolo.metodo, "evaluado_utc": hasta, "recibido_utc": hasta, **resultado.a_fila()}],
                 FUENTE_ESTUDIOS)
    return resultado


def comprobar_desarrollo(lake, protocolo: Protocolo, desde_utc, hasta_utc) -> ResultadoProtocolo:
    """SOLO comprobación de la tubería con datos anteriores al registro (o sin registro): mismas medidas, sin
    decisiones, sin guardar nada. No calibra el protocolo y la evaluación nunca lo lee."""
    d, desde = _muestra(lake, protocolo, pd.Timestamp(desde_utc), pd.Timestamp(hasta_utc))
    return _medir(d, protocolo, protocolo.huella(), DESARROLLO, desde_utc, hasta_utc, desde)


@dataclass(frozen=True)
class EstadoProtocolo:
    protocolo_hash: str
    nombre: str
    registrado_utc: pd.Timestamp
    evaluaciones: int
    estado: str
    decisiones_disponibles: int | None
    decisiones_necesarias: int
    operaciones_disponibles: int | None
    operaciones_necesarias: int

    def texto(self) -> str:
        base = (f"{self.protocolo_hash[:12]} {self.nombre}, registrado {self.registrado_utc:%Y-%m-%d %H:%M:%S} UTC: "
                f"{self.estado}")
        if self.decisiones_disponibles is None:
            return base + f" ({self.evaluaciones} evaluaciones)."
        return (base + f" (decisiones {self.decisiones_disponibles} de {self.decisiones_necesarias}, operaciones "
                f"{self.operaciones_disponibles} de {self.operaciones_necesarias}).")


def estado_protocolo(lake, ahora=None) -> list[EstadoProtocolo]:
    """Cada protocolo registrado: evaluado, o cuánta muestra posterior al registro hay frente a la necesaria."""
    fuentes = lake.fuentes()
    if FUENTE_PROTOCOLOS not in fuentes:
        return []
    hasta, salida = _ahora(ahora), []
    for huella in lake.consultar(f"SELECT protocolo_hash FROM {FUENTE_PROTOCOLOS} ORDER BY registrado_utc"
                                 ).protocolo_hash:
        p, registrado = leer_protocolo(lake.consultar, huella)
        n_eval = len(_aperturas(lake.consultar, fuentes, huella))
        if n_eval:
            salida.append(EstadoProtocolo(huella, p.nombre, registrado, n_eval, EVALUADA, None, p.min_decisiones,
                                          None, p.min_operaciones))
            continue
        d, _ = _muestra(lake, p, registrado, hasta)
        n_ops = int((d.senal_bps.abs() > p.umbral_bps).sum())
        listo = len(d) >= p.min_decisiones and n_ops >= p.min_operaciones
        salida.append(EstadoProtocolo(huella, p.nombre, registrado, 0, LISTA if listo else ESPERANDO, len(d),
                                      p.min_decisiones, n_ops, p.min_operaciones))
    return salida
