"""Comparación multiactivo en EUR: capitalización, calendario semanal común, conversión de divisa,
CAGR, volatilidad, drawdown, drag de volatilidad, correlaciones y retorno total.

Origen: P14 · Laboratorio multiactivo y capitalización. Concepto: docs/conceptos/multiactivo_y_capitalizacion.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TICKERS = {"BTC": "BTC-USD", "Acciones": "SPY", "Bonos": "IEF", "Oro": "GLD", "Global": "VT", "EURUSD": "EURUSD=X"}
ASSETS = ["BTC", "Acciones", "Bonos", "Oro", "Global", "USD efectivo"]


# --- Capitalización ------------------------------------------------------------------

def future_value(capital: float, rate: float, periods: float) -> float:
    """FV = C₀ · (1 + r)^n."""
    if rate <= -1 or periods < 0:
        raise ValueError("Tipo o plazo inválido")
    return capital * (1 + rate) ** periods


def present_value(amount: float, rate: float, periods: float) -> float:
    """PV = FV / (1 + r)^n."""
    return amount / future_value(1, rate, periods)


def compound_return(returns) -> float:
    """∏(1 + r_t) − 1."""
    r = np.asarray(returns, dtype=float)
    if not np.isfinite(r).all() or (r < -1).any():
        raise ValueError("Retornos inválidos")
    return float(np.prod(1 + r) - 1)


# --- Datos -------------------------------------------------------------------------------

def synthetic_prices(seed: int = 42, start: str = "2021-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Precios ficticios en USD (y EURUSD) en días hábiles, con un factor de mercado y otro de tipos."""
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    mkt, rate, fx = rng.normal(size=(3, len(dates)))
    noise = rng.normal(size=(5, len(dates)))
    # Choques y parámetros arbitrarios: no calibrados a mercados reales.
    shock = np.array([.00025 + .018 * mkt + .025 * noise[0],
                      .00028 + .009 * mkt + .004 * noise[1],
                      .00009 - .002 * mkt + .0035 * rate + .0015 * noise[2],
                      .00013 + .002 * mkt - .002 * rate + .007 * noise[3],
                      .00023 + .008 * mkt + .0035 * noise[4],
                      .00001 + .003 * fx])
    return pd.DataFrame(np.array([30000, 370, 110, 180, 90, 1.22]) * np.exp(shock.cumsum(axis=1).T),
                        index=dates, columns=list(TICKERS)).rename_axis("date")


def download_prices(start: str = "2021-01-01", end: str = "2026-01-01", tickers: dict = TICKERS) -> pd.DataFrame:
    """Cierres ajustados diarios de Yahoo Finance (requiere `yfinance`). Lanza el error si no hay datos."""
    import yfinance as yf
    raw = yf.download(list(tickers.values()), start=start, end=end, interval="1d", auto_adjust=True,
                      group_by="column", multi_level_index=True, ignore_tz=True, progress=False,
                      threads=False, timeout=20)
    if raw is None or raw.empty or "Close" not in raw.columns.get_level_values(0):
        raise RuntimeError("No se han recibido cierres de Yahoo Finance")
    return raw["Close"].rename(columns={v: k for k, v in tickers.items()}).rename_axis("date")


def prepare_weekly(raw: pd.DataFrame, start: str = "2021-01-01", end: str = "2026-01-01",
                   tickers: dict = TICKERS, assets=ASSETS, min_weeks: int = 53) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Último cierre de cada semana (lunes a viernes) en que TODAS las series tienen dato, convertido a EUR.

    Descarta la primera y la última semana. Lanza ValueError con fechas duplicadas, precios ≤ 0 o infinitos,
    sin sesiones comunes, menos de `min_weeks` semanas o una semana interior sin datos (no se rellena).
    Devuelve (semanal en USD, semanal en EUR, número de sesiones comunes).
    """
    frame = raw[list(tickers)].copy().apply(pd.to_numeric, errors="raise")
    frame.columns.name = None
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(None).normalize()
    if frame.index.has_duplicates:
        raise ValueError("Fechas duplicadas")
    frame = frame.sort_index().loc[lambda x: (x.index >= start) & (x.index < end)]
    if np.isinf(frame.to_numpy()).any() or (frame <= 0).any().any():
        raise ValueError("Precios/FX no positivos o infinitos")
    common = frame.loc[frame.index.day_of_week < 5].dropna()
    if common.empty:
        raise ValueError("No hay sesiones comunes")
    week = common.resample("W-FRI").last().iloc[1:-1]
    if len(week) < min_weeks or week.isna().any().any():
        raise ValueError(f"Se requieren al menos {min_weeks} semanas comunes consecutivas, sin huecos")
    eur = week.drop(columns="EURUSD").div(week["EURUSD"], axis=0)
    eur["USD efectivo"] = 1 / week["EURUSD"]
    return week, eur[list(assets)], len(common)


# --- Métricas ---------------------------------------------------------------------------------

def performance(levels: pd.DataFrame, periods_per_year: int = 52) -> pd.DataFrame:
    """Retorno total, CAGR (años de calendario), volatilidad anualizada, MDD y drag (aritmética − geométrica)."""
    ret = levels.pct_change(fill_method=None).iloc[1:]
    years = (levels.index[-1] - levels.index[0]).days / 365.2425
    gross = levels.iloc[-1] / levels.iloc[0]
    geom = gross ** (1 / len(ret)) - 1
    dd = levels.div(levels.cummax()) - 1
    return pd.DataFrame({"return_pct": 100 * (gross - 1), "cagr_pct": 100 * (gross ** (1 / years) - 1),
                         "volatility_pct": 100 * ret.std(ddof=1) * np.sqrt(periods_per_year),
                         "max_drawdown_pct": -100 * dd.min(),
                         "drag_pp": 100 * periods_per_year * (ret.mean() - geom)})


def fx_decomposition(weekly_usd: pd.DataFrame) -> pd.DataFrame:
    """Retorno en EUR reconstruido: (1 + r_USD) / (1 + r_EURUSD) − 1."""
    usd = weekly_usd.drop(columns="EURUSD").pct_change(fill_method=None).iloc[1:]
    fx = weekly_usd["EURUSD"].pct_change(fill_method=None).iloc[1:]
    return (1 + usd).div(1 + fx, axis=0) - 1


def total_return(price_start: float, price_end: float, dividend: float) -> float:
    """Retorno total de un periodo con el dividendo cobrado al final."""
    if price_start <= 0 or price_end < 0 or dividend < 0:
        raise ValueError("Precios o dividendo inválidos")
    return (price_end + dividend) / price_start - 1


# --- Ejercicios -------------------------------------------------------------------------------

def manual_compound(capital: float, returns) -> float:
    """E1 · Capital final con un bucle."""
    for r in returns:
        if not np.isfinite(r) or r < -1:
            raise ValueError("Retorno inválido")
        capital *= 1 + r
    return capital


def equivalent_rate(annual_rate: float, periods_per_year: int = 12) -> float:
    """E2 · Tipo por periodo equivalente a un efectivo anual: (1 + r)^{1/m} − 1."""
    if annual_rate <= -1 or periods_per_year <= 0:
        raise ValueError("Tipo o periodos inválidos")
    return (1 + annual_rate) ** (1 / periods_per_year) - 1


def cagr(start_value: float, end_value: float, years: float) -> float:
    """E3 · Tasa anual compuesta: (V_final / V_inicial)^{1/años} − 1."""
    if start_value <= 0 or end_value <= 0 or years <= 0:
        raise ValueError("Valores o años inválidos")
    return (end_value / start_value) ** (1 / years) - 1


def eur_return(usd_return: float, eurusd_return: float) -> float:
    """E5 · Retorno en EUR de un activo en USD: (1 + r_USD) / (1 + r_EURUSD) − 1."""
    return (1 + usd_return) / (1 + eurusd_return) - 1


def dividend_paths(prices, dividends, shares: float = 1.) -> pd.DataFrame:
    """E6 · Por año: retorno de precio, retorno total sin reinvertir (dividendo en efectivo) y con reinversión."""
    p = np.asarray(prices, dtype=float)
    d = np.asarray(dividends, dtype=float)
    if len(d) != len(p) - 1 or (p <= 0).any() or (d < 0).any():
        raise ValueError("Se necesitan n + 1 precios y n dividendos no negativos")
    cash, reinvested = 0.0, shares
    rows = []
    for t in range(1, len(p)):
        cash += shares * d[t - 1]
        reinvested += reinvested * d[t - 1] / p[t]  # se compran acciones al precio de fin de año
        rows.append({"year": t, "price": p[t], "dividend": d[t - 1],
                     "price_return_pct": 100 * (p[t] / p[0] - 1),
                     "total_cash_pct": 100 * ((shares * p[t] + cash) / (shares * p[0]) - 1),
                     "total_reinvested_pct": 100 * (reinvested * p[t] / (shares * p[0]) - 1)})
    return pd.DataFrame(rows).set_index("year")


def split_halves(levels: pd.DataFrame, capital: float = 1000.) -> dict:
    """E8 · Dos mitades cronológicas, cada una rebasada a `capital` desde su propio punto inicial."""
    mid = len(levels) // 2
    first, second = levels.iloc[:mid + 1], levels.iloc[mid:]  # la segunda empieza donde acaba la primera
    out = {}
    for name, block in [("primera", first), ("segunda", second)]:
        out[name] = {"levels": block.div(block.iloc[0]) * capital, "metrics": performance(block),
                     "corr": block.pct_change(fill_method=None).iloc[1:].corr(),
                     "start": block.index[0], "end": block.index[-1]}
    return out
