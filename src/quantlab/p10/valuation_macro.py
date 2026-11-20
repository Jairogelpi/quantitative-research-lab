"""Valor temporal del dinero, bonos, DCF, inflación y curva de tipos, y estudio de eventos de sorpresas
macroeconómicas (IPC) sobre BTC/USD con alineación temporal causal.

Origen: P10 · Valoración fundamental y macroeconomía. Concepto: docs/conceptos/valoracion_y_macro.md
"""

from __future__ import annotations

from io import StringIO

import numpy as np
import pandas as pd
import requests

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = ("CPIAUCSL", "FEDFUNDS", "DGS2", "DGS10", "UNRATE", "CBBTCUSD")
SURPRISE_GROUPS = ["Inferior", "En línea", "Superior"]


# --- Valor temporal, bonos y DCF --------------------------------------------------

def present_value(cashflows, rate: float) -> float:
    """PV = Σ CF_t / (1 + r)^t, con el primer flujo en t = 1."""
    flows = np.asarray(cashflows, dtype=float)
    if rate <= -1 or not np.isfinite(rate) or not np.isfinite(flows).all():
        raise ValueError("Flujos finitos y tasa mayor que -100 %")
    return float(np.sum(flows / (1 + rate) ** np.arange(1, len(flows) + 1)))


def bond_price(face: float, coupon_rate: float, yield_rate: float, years: int) -> float:
    """Bono con cupones anuales, curva plana y sin riesgo de impago modelado."""
    if years < 1:
        raise ValueError("Vencimiento de al menos 1 año")
    flows = np.full(years, face * coupon_rate, dtype=float)
    flows[-1] += face
    return present_value(flows, yield_rate)


def dcf(cashflows, discount_rate: float, terminal_growth: float) -> dict:
    """EV = Σ FCFF_t / (1 + r)^t + FCFF_N · (1 + g) / ((r − g) · (1 + r)^N). Exige r > g > −1."""
    flows = np.asarray(cashflows, dtype=float)
    if len(flows) == 0 or not np.isfinite(flows).all() or flows[-1] <= 0:
        raise ValueError("Flujos válidos y último flujo positivo")
    if not np.isfinite([discount_rate, terminal_growth]).all() or not (-1 < terminal_growth < discount_rate):
        raise ValueError("Se requiere r > g > -1")
    terminal = flows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_terminal = terminal / (1 + discount_rate) ** len(flows)
    pv_explicit = present_value(flows, discount_rate)
    return {"pv_explicit": pv_explicit, "pv_terminal": pv_terminal, "enterprise_value": pv_explicit + pv_terminal}


def value_per_share(cashflows, discount_rate: float, terminal_growth: float, net_debt: float, shares: float) -> float:
    """(EV − deuda financiera neta) / acciones."""
    if shares <= 0:
        raise ValueError("Número de acciones no positivo")
    return (dcf(cashflows, discount_rate, terminal_growth)["enterprise_value"] - net_debt) / shares


def dcf_sensitivity(cashflows, rates, growths, net_debt: float, shares: float) -> pd.DataFrame:
    """Valor por acción para cada combinación de tasa de descuento (filas) y crecimiento perpetuo (columnas)."""
    return pd.DataFrame([[value_per_share(cashflows, r, g, net_debt, shares) for g in growths] for r in rates],
                        index=[f"{r:.0%}" for r in rates], columns=[f"{g:.0%}" for g in growths])


# --- Inflación y curva -------------------------------------------------------------

def yoy_by_date(series: pd.Series) -> pd.Series:
    """Variación interanual en % comparando cada mes con el MISMO mes del año anterior.

    Reindexa a una rejilla mensual completa antes de desplazar: si falta un mes, `pct_change(12)`
    por posición compararía con el mes equivocado. Los meses ausentes quedan como NaN.
    """
    s = series.sort_index()
    full = pd.date_range(s.index.min(), s.index.max(), freq="MS", tz=s.index.tz)
    return (s.reindex(full).pct_change(12, fill_method=None) * 100).reindex(s.index)


def macro_features(monthly: pd.DataFrame) -> pd.DataFrame:
    """Inflación interanual (exige el mismo mes del año anterior) y pendiente 10 años − 2 años en bps."""
    out = monthly.copy().sort_index()
    out["inflation_yoy_pct"] = yoy_by_date(out["cpi"])
    out["yield_curve_bps"] = (out["yield_10y_pct"] - out["yield_2y_pct"]) * 100
    return out


def real_return(nominal_return, inflation):
    """Fisher exacto: (1 + nominal) / (1 + inflación) − 1."""
    return (1 + np.asarray(nominal_return, dtype=float)) / (1 + np.asarray(inflation, dtype=float)) - 1


def synthetic_macro(seed: int = 42, months: int = 48) -> pd.DataFrame:
    """IPC, tipo de política y rendimientos a 2 y 10 años mensuales y ficticios."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=months, freq="MS", tz="UTC")
    t = np.arange(len(idx))
    macro = pd.DataFrame({"cpi": 275 * np.cumprod(1 + .0025 + rng.normal(0, .0012, len(t))),
                          "policy_rate_pct": 3 + 1.5 * np.sin(t / 11),
                          "yield_2y_pct": 3.2 + 1.1 * np.sin(t / 10),
                          "yield_10y_pct": 3.7 + .65 * np.sin(t / 13)}, index=idx)
    return macro_features(macro)


def fetch_fred(series: str, start: str, end: str, timeout: float = 30) -> pd.Series:
    """Serie de FRED (versión disponible hoy, no un vintage histórico). Lanza el error si la descarga falla."""
    res = requests.get(FRED_CSV_URL, params={"id": series, "cosd": start, "coed": end}, timeout=timeout)
    res.raise_for_status()
    df = pd.read_csv(StringIO(res.text), na_values=["."])
    if len(df.columns) != 2 or series not in df.columns:
        raise ValueError(f"Respuesta inesperada: {series}")
    df = df.rename(columns={df.columns[0]: "observation_date"})
    df["observation_date"] = pd.to_datetime(df.observation_date, errors="raise")
    df[series] = pd.to_numeric(df[series], errors="raise")
    return df.set_index("observation_date")[series].dropna().sort_index()


# --- Estudio de eventos -------------------------------------------------------------------

def synthetic_events_and_prices(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """48 publicaciones ficticias de IPC con consenso del día anterior, y precios horarios de BTC/USD
    con un efecto programado: cada punto de sorpresa resta un 1,5 % en la hora de la publicación."""
    rng = np.random.default_rng(seed)
    releases = pd.date_range("2022-02-01", periods=48, freq="MS", tz="UTC") + pd.Timedelta(days=11, hours=13, minutes=30)
    consensus = 3 + rng.normal(0, .35, len(releases))
    surprises = rng.normal(0, .22, len(releases))
    ev = pd.DataFrame({"event_id": [f"CPI-{i:02}" for i in range(len(releases))],
                       "reference_month": (releases - pd.DateOffset(months=1)).strftime("%Y-%m"),
                       "available_at": releases, "consensus_at": releases - pd.Timedelta(days=1),
                       "actual_pct": consensus + surprises, "consensus_pct": consensus})
    idx = pd.date_range(releases.min() - pd.Timedelta(hours=48), releases.max() + pd.Timedelta(hours=48), freq="h")
    logret = rng.normal(0, .0018, len(idx))
    # Efecto artificial, explícito: inflación superior al consenso presiona a BTC.
    logret[idx.get_indexer(releases)] += -.015 * surprises
    prices = pd.DataFrame({"timestamp": idx, "price": 30000 * np.exp(np.cumsum(logret))})
    return ev, prices


def validate_events_prices(events: pd.DataFrame, prices: pd.DataFrame,
                           require_tz: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convierte tipos, valida y ordena eventos y precios. Añade `surprise_pp` = actual − consenso.

    Lanza ValueError con timestamps sin zona (si `require_tz`), IDs u horas de publicación duplicadas,
    consenso ausente o posterior a la publicación, valores no finitos, o precios duplicados o ≤ 0.
    """
    events, prices = events.copy(), prices.copy()
    if require_tz:
        for series in [events.available_at, events.consensus_at, prices.timestamp]:
            if not series.map(lambda x: pd.Timestamp(x).tzinfo is not None).all():
                raise ValueError("Todos los timestamps CSV deben incluir zona horaria.")
    for col in ["available_at", "consensus_at"]:
        events[col] = pd.to_datetime(events[col], utc=True, errors="raise")
    prices["timestamp"] = pd.to_datetime(prices.timestamp, utc=True, errors="raise")
    for col in ["actual_pct", "consensus_pct"]:
        events[col] = pd.to_numeric(events[col], errors="raise")
    prices["price"] = pd.to_numeric(prices.price, errors="raise")
    if not (events.event_id.is_unique and events.available_at.is_unique):
        raise ValueError("Eventos u horas de publicación duplicados")
    if events[["available_at", "consensus_at"]].isna().any().any():
        raise ValueError("Falta la hora de publicación o del consenso")
    if not (events.consensus_at < events.available_at).all():
        raise ValueError("Consenso posterior a publicación")
    if not np.isfinite(events[["actual_pct", "consensus_pct"]]).all().all():
        raise ValueError("Dato o consenso no finito")
    if not (prices.timestamp.is_unique and prices.timestamp.notna().all()):
        raise ValueError("Precios con timestamps duplicados o vacíos")
    if not (np.isfinite(prices.price).all() and (prices.price > 0).all()):
        raise ValueError("Precios no válidos")
    events = events.sort_values("available_at").reset_index(drop=True)
    prices = prices.sort_values("timestamp").reset_index(drop=True)
    events["surprise_pp"] = events.actual_pct - events.consensus_pct
    return events, prices


def align_events(events: pd.DataFrame, prices: pd.DataFrame, horizons=(1, 6, 24), max_age: str = "60min") -> pd.DataFrame:
    """Precio previo estrictamente anterior a la publicación y precios a cada horizonte (`backward`).

    Los precios posteriores son etiquetas de evaluación, no features. Marca ventanas solapadas.
    """
    tol = pd.Timedelta(max_age)
    base = events.copy().sort_values("available_at").reset_index(drop=True)
    market = prices[["timestamp", "price"]].sort_values("timestamp")

    def lookup(target, exact):
        return pd.merge_asof(pd.DataFrame({"target": target}), market, left_on="target", right_on="timestamp",
                             direction="backward", allow_exact_matches=exact, tolerance=tol)
    pre = lookup(base.available_at, False)
    base["pre_timestamp"] = pre.timestamp
    base["pre_price"] = pre.price
    for h in horizons:
        post = lookup(base.available_at + pd.Timedelta(hours=h), True)
        # No admitir una cotización que preceda al evento como precio posterior.
        valid = post.timestamp >= base.available_at
        base[f"post_timestamp_{h}h"] = post.timestamp.where(valid)
        base[f"return_{h}h_bps"] = (post.price.where(valid) / base.pre_price - 1) * 10000
    window = pd.Timedelta(hours=max(horizons))
    base["overlap_24h"] = ((base.available_at.diff() <= window)
                           | (base.available_at.shift(-1) - base.available_at <= window))
    return base


def split_events(results: pd.DataFrame, train_fraction: float = .65, purge_hours: int = 24) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Separación cronológica; excluye solapes y eventos de desarrollo cuyo horizonte toca la frontera."""
    if len(results) < 4:
        raise ValueError("Se necesitan al menos 4 eventos; muchos más para inferencia.")
    out = results.copy()
    cutoff = out.available_at.iloc[int(len(out) * train_fraction)]
    out["split"] = np.where(out.available_at < cutoff, "development", "validation")
    out["eligible"] = ~out.overlap_24h & ~((out.split == "development")
                                           & (out.available_at + pd.Timedelta(hours=purge_hours) >= cutoff))
    return out, cutoff


def surprise_groups(valid: pd.DataFrame, threshold_pp: float = .15) -> pd.DataFrame:
    """Clasifica la sorpresa: Inferior (≤ −umbral), Superior (≥ umbral) o En línea."""
    out = valid.copy()
    out["surprise_group"] = np.select([out.surprise_pp <= -threshold_pp, out.surprise_pp >= threshold_pp],
                                      ["Inferior", "Superior"], default="En línea")
    return out


# --- Ejercicios --------------------------------------------------------------------------------

def manual_pv(cashflows, rate: float) -> float:
    """E1 · Valor actual con un bucle explícito."""
    if rate <= -1:
        raise ValueError("Tasa mayor que -100 %")
    total = 0.0
    for t, cf in enumerate(cashflows, start=1):
        total += cf / (1 + rate) ** t
    return total


def bond_shock(maturities=(2, 5, 10), coupon: float = .04, y0: float = .04, y1: float = .05, face: float = 1000) -> pd.DataFrame:
    """E2 · Variación de precio de bonos de distinto vencimiento ante un cambio de rendimiento."""
    rows = []
    for n in maturities:
        p0, p1 = bond_price(face, coupon, y0, n), bond_price(face, coupon, y1, n)
        rows.append({"years": n, "price_before": p0, "price_after": p1, "change_pct": 100 * (p1 / p0 - 1)})
    return pd.DataFrame(rows).set_index("years")


def fisher_comparison(nominal: float, inflation: float) -> dict:
    """E4 · Aproximación (nominal − inflación) frente a Fisher exacto."""
    exact = float(real_return(nominal, inflation))
    approx = nominal - inflation
    return {"approx": approx, "exact": exact, "error_pp": 100 * (approx - exact)}


def inverted_curve(macro: pd.DataFrame) -> dict:
    """E5 · Meses con curva invertida (10 años < 2 años) y su proporción."""
    inverted = macro.index[macro.yield_curve_bps < 0]
    return {"months": list(inverted), "count": len(inverted), "share": len(inverted) / len(macro),
            "deepest_bps": macro.yield_curve_bps.min()}


def development_horizons(valid: pd.DataFrame, horizons=(1, 6, 24)) -> pd.DataFrame:
    """E6 · Retorno medio y número de eventos por grupo y horizonte, por periodo."""
    cols = [f"return_{h}h_bps" for h in horizons]
    agg = valid.groupby(["split", "surprise_group"])[cols].agg(["count", "mean"])
    return agg.reindex(SURPRISE_GROUPS, level="surprise_group")


def fred_indicators(fred: dict) -> tuple[pd.DataFrame, pd.Series]:
    """E7 · Inflación interanual (IPC mensual) y pendiente diaria 10 − 2 años en bps, sin mezclar frecuencias.

    Los meses que FRED no publica quedan como NaN en la rejilla mensual; la inflación se compara por fecha.
    """
    cpi = fred["CPIAUCSL"]
    full = pd.date_range(cpi.index.min(), cpi.index.max(), freq="MS")
    monthly = pd.DataFrame({"cpi_index": cpi.reindex(full)})
    monthly.index.name = "observation_date"
    monthly["inflation_yoy_pct"] = yoy_by_date(monthly.cpi_index.dropna()).reindex(full)
    if "FEDFUNDS" in fred:
        monthly["fed_funds_pct"] = fred["FEDFUNDS"]
    if "UNRATE" in fred:
        monthly["unemployment_pct"] = fred["UNRATE"]
    curve = ((fred["DGS10"] - fred["DGS2"]).dropna() * 100).rename("curve_10y_2y_bps")
    return monthly, curve


def availability_report(events: pd.DataFrame, prices: pd.DataFrame | None = None, max_age: str = "60min") -> pd.DataFrame:
    """E8 · Cuantifica ausencias antes de un estudio: consenso, horas de publicación y precio previo."""
    rows = {"eventos": len(events),
            "sin hora de publicación": int(events.available_at.isna().sum()),
            "sin consenso": int(events.consensus_pct.isna().sum()),
            "sin hora del consenso": int(events.consensus_at.isna().sum()),
            "sin dato publicado": int(events.actual_pct.isna().sum())}
    if prices is not None:
        known = events.dropna(subset=["available_at"]).copy()
        known["available_at"] = pd.to_datetime(known.available_at, utc=True)
        market = prices.assign(timestamp=pd.to_datetime(prices.timestamp, utc=True)).sort_values("timestamp")
        pre = pd.merge_asof(known.sort_values("available_at")[["available_at"]], market[["timestamp", "price"]],
                            left_on="available_at", right_on="timestamp", direction="backward",
                            allow_exact_matches=False, tolerance=pd.Timedelta(max_age))
        rows["sin precio previo (≤ 60 min)"] = int(pre.price.isna().sum())
    out = pd.Series(rows, name="n").to_frame()
    out["pct"] = 100 * out.n / max(len(events), 1)
    return out
