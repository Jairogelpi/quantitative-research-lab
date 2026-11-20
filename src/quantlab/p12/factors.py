"""Alpha, beta y factores: regresión de Jensen y multifactor con errores HAC, atribución de rentabilidad,
validación con exposiciones congeladas, beta móvil y factores long-short construidos sin mirar el futuro.

Origen: P12 · Alpha, Beta y factores financieros. Concepto: docs/conceptos/alpha_beta_factores.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


# --- Datos ------------------------------------------------------------------------

def daily_risk_free(annual: float = .02, periods: int = 365) -> float:
    """Tipo diario equivalente: (1 + RF)^{1/A} − 1."""
    if annual <= -1 or periods <= 0:
        raise ValueError("Tipo o periodos inválidos")
    return (1 + annual) ** (1 / periods) - 1


def synthetic_factor_data(seed: int = 42, n: int = 900, rf_daily: float | None = None) -> pd.DataFrame:
    """Mercado, dos factores long-short y dos estrategias: A sin alpha estructural y B con 4,5 bps diarios."""
    rf = daily_risk_free() if rf_daily is None else rf_daily
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    market = rng.normal(.00065, .018, len(dates))
    momentum = .20 * (market - rf) + rng.normal(.0005, .008, len(dates))
    liquidity = -.08 * (market - rf) + rng.normal(.00035, .006, len(dates))
    noise = rng.normal(0, .003, len(dates))
    # Estrategia A: sin alpha estructural; estrategia B: intercepto positivo artificial.
    base = rf + .75 * (market - rf) + .65 * momentum + .45 * liquidity
    daily = pd.DataFrame({"benchmark_return": market, "risk_free_return": rf, "momentum_factor": momentum,
                          "liquidity_factor": liquidity, "A": base + noise, "B": base + .00045 + noise}, index=dates)
    daily.index.name = "timestamp"
    return daily


def read_daily(path) -> pd.DataFrame:
    """CSV diario con columna `timestamp` en UTC, sin duplicados."""
    raw = pd.read_csv(path)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="raise")
    raw = raw.set_index("timestamp").sort_index()
    if raw.index.has_duplicates or raw.index.hasnans:
        raise ValueError(f"Timestamps duplicados o inválidos: {path}")
    return raw


def validate_daily_factors(daily: pd.DataFrame, strategies, min_days: int = 100) -> pd.DataFrame:
    """Exige valores finitos, días consecutivos, al menos `min_days` y retornos > −100 %. Añade `market_excess`.

    No imputa huecos ni ausencias: lanza ValueError.
    """
    d = daily.copy()
    d.index.name = "timestamp"
    for col in d.columns:
        d[col] = pd.to_numeric(d[col], errors="raise")
    if not np.isfinite(d.to_numpy()).all():
        raise ValueError("Faltan datos o hay valores no finitos; no imputar retornos sin investigar")
    if not (d.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all():
        raise ValueError("Se requieren retornos diarios consecutivos en UTC; no rellenar huecos con cero")
    if len(d) < min_days or (d[list(strategies) + ["benchmark_return", "risk_free_return"]] <= -1).any().any():
        raise ValueError("Muestra insuficiente o retorno de capital inválido")
    d["market_excess"] = d.benchmark_return - d.risk_free_return
    return d


def chronological_split(daily: pd.DataFrame, train_fraction: float = .65, hac_lags: int = 5,
                        n_factors: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Primer `train_fraction` para desarrollo y el resto para validación; exige ventanas suficientes."""
    cut = int(len(daily) * train_fraction)
    train, test = daily.iloc[:cut].copy(), daily.iloc[cut:].copy()
    if min(len(train), len(test)) <= max(hac_lags, n_factors + 2):
        raise ValueError("Ventanas demasiado cortas")
    return train, test


# --- Regresión y atribución -------------------------------------------------------------

def fit_model(frame: pd.DataFrame, strategy: str, factors, hac_lags: int = 5):
    """OLS de r_s − r_f sobre los factores, con errores estándar HAC (Newey-West)."""
    X = sm.add_constant(frame[list(factors)], has_constant="add")
    if np.linalg.matrix_rank(X.to_numpy()) != X.shape[1]:
        raise ValueError("Factores colineales o constantes")
    y = frame[strategy] - frame.risk_free_return
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})


def model_table(train: pd.DataFrame, strategies, specs: dict, hac_lags: int = 5,
                periods: int = 365) -> tuple[pd.DataFrame, dict]:
    """Alpha diario (bps) y anual aritmético, su IC del 95 %, p-valor, beta de mercado y R² por estrategia y modelo."""
    models, rows = {}, []
    for s in strategies:
        for name, factors in specs.items():
            fit = fit_model(train, s, factors, hac_lags)
            models[s, name] = fit
            lo, hi = fit.conf_int().loc["const"]
            rows.append({"strategy": s, "model": name, "alpha_daily_bps": fit.params["const"] * 1e4,
                         "alpha_annual_linear_pct": fit.params["const"] * periods * 100,
                         "ci_low_bps": lo * 1e4, "ci_high_bps": hi * 1e4, "alpha_p_value": fit.pvalues["const"],
                         "beta": fit.params["market_excess"], "r_squared": fit.rsquared})
    return pd.DataFrame(rows), models


def attribution(frame: pd.DataFrame, strategy: str, fit) -> pd.DataFrame:
    """r_s = r_f + α + Σ β_j · f_j + ε, término a término. La suma por fila reproduce exactamente r_s."""
    parts = pd.DataFrame({"risk_free": frame.risk_free_return, "alpha_model": fit.params["const"]}, index=frame.index)
    for f in fit.params.index.drop("const"):
        parts[f] = frame[f] * fit.params[f]
    parts["residual"] = frame[strategy] - parts.sum(axis=1)
    return parts


def frozen_validation(test: pd.DataFrame, strategies, models: dict, chosen: str, factors, hac_lags: int = 5,
                      periods: int = 365) -> tuple[pd.DataFrame, dict]:
    """Aplica las exposiciones de desarrollo a la validación sin reestimarlas, y añade una regresión
    diagnóstica separada en validación (solo para estabilidad, no para decidir)."""
    rows, parts_by = [], {}
    for s in strategies:
        fit = models[s, chosen]
        parts = attribution(test, s, fit)
        parts_by[s] = parts
        check = fit_model(test, s, factors, hac_lags)
        active = test[s] - test.benchmark_return
        te = active.std(ddof=1) * np.sqrt(periods)
        rows.append({"strategy": s, "return_pct": ((1 + test[s]).prod() - 1) * 100,
                     "benchmark_pct": ((1 + test.benchmark_return).prod() - 1) * 100,
                     "frozen_unexplained_bps": (parts.alpha_model + parts.residual).mean() * 1e4,
                     "frozen_residual_bps": parts.residual.mean() * 1e4,
                     "diagnostic_alpha_bps": check.params["const"] * 1e4,
                     "diagnostic_alpha_p": check.pvalues["const"],
                     "tracking_error_annual_pct": te * 100,
                     "information_ratio": active.mean() * periods / te if te > 0 else np.nan})
    return pd.DataFrame(rows), parts_by


def rolling_beta(daily: pd.DataFrame, strategies, window: int = 90) -> pd.DataFrame:
    """Beta unifactorial con las últimas `window` observaciones conocidas en cada fecha (ventana hacia atrás)."""
    if window < 2:
        raise ValueError("Ventana de al menos 2 observaciones")
    market = daily.market_excess
    return pd.DataFrame({s: (daily[s] - daily.risk_free_return).rolling(window).cov(market)
                            / market.rolling(window).var() for s in strategies})


# --- Factores long-short ----------------------------------------------------------------------

def synthetic_universe(seed: int = 43, n_days: int = 150, assets: str = "ABCDEF") -> pd.DataFrame:
    """Retornos diarios ficticios de seis activos independientes."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(.0005, .02, (n_days, len(assets))), columns=list(assets),
                        index=pd.date_range("2024-01-01", periods=n_days, freq="D", tz="UTC"))


def long_short_factor(universe: pd.DataFrame, lookback: int = 20, k: int = 2, reverse: bool = False) -> dict:
    """Diferencial entre los `k` mejores y los `k` peores según el retorno acumulado HASTA AYER.

    Con `reverse=True` se compra a los perdedores y se vende a los ganadores (reversión).
    Devuelve el factor, la puntuación, las máscaras y la rotación diaria de la cartera (0 a 1).
    """
    n = universe.shape[1]
    if not 1 <= k <= n // 2:
        raise ValueError("k debe estar entre 1 y la mitad de los activos")
    score = (1 + universe).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True).shift(1) - 1
    rank = score.rank(axis=1, method="first")
    winners, losers = rank >= n - k + 1, rank <= k
    long_mask, short_mask = (losers, winners) if reverse else (winners, losers)
    factor = universe.where(long_mask).mean(axis=1) - universe.where(short_mask).mean(axis=1)
    factor = factor.where(score.notna().all(axis=1)).rename("reversal" if reverse else "momentum")
    available = score.notna().all(axis=1)
    weights = (long_mask.astype(float) / k - short_mask.astype(float) / k).where(available, 0.)
    # Rotación de un sentido: mitad de Σ|Δw|. El primer día disponible se construye la cartera completa (1).
    turnover = ((weights - weights.shift(1, fill_value=0.)).abs().sum(axis=1) / 2).where(available)
    return {"factor": factor, "score": score, "long_mask": long_mask, "short_mask": short_mask, "turnover": turnover}


def factor_after_costs(factor: pd.Series, turnover: pd.Series, cost_bps_per_side: float) -> pd.Series:
    """Factor neto: cada unidad de rotación de un sentido mueve las dos patas, coste = 2 · rotación · coste por lado."""
    if cost_bps_per_side < 0:
        raise ValueError("Coste negativo")
    return (factor - 2 * turnover * cost_bps_per_side / 1e4).rename(f"{factor.name}_net")


# --- Ejercicios ------------------------------------------------------------------------------

def manual_alpha_beta(strategy_excess, market_excess) -> tuple[float, float]:
    """E1 · β = Cov(x, y) / Var(x) y α = media(y) − β · media(x), con retornos excedentes."""
    y = np.asarray(strategy_excess, dtype=float)
    x = np.asarray(market_excess, dtype=float)
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("Series de distinta longitud o demasiado cortas")
    var = ((x - x.mean()) ** 2).sum()
    if var == 0:
        raise ValueError("El mercado no varía: beta indefinida")
    beta = ((x - x.mean()) * (y - y.mean())).sum() / var
    return float(y.mean() - beta * x.mean()), float(beta)


def active_vs_alpha(frame: pd.DataFrame, strategies, models: dict, model: str = "Mercado") -> pd.DataFrame:
    """E2 · Retorno activo medio (r_s − r_m) frente al alpha de Jensen, y la parte que explica la beta."""
    rows = []
    for s in strategies:
        fit = models[s, model]
        beta = fit.params["market_excess"]
        active = (frame[s] - frame.benchmark_return).mean()
        rows.append({"strategy": s, "active_bps": active * 1e4, "alpha_bps": fit.params["const"] * 1e4, "beta": beta,
                     "beta_gap_bps": (beta - 1) * frame.market_excess.mean() * 1e4})
    return pd.DataFrame(rows).set_index("strategy")


def omitted_factor_table(train: pd.DataFrame, strategy: str, factor_cols, hac_lags: int = 5) -> pd.DataFrame:
    """E3 · Alpha, beta, IC y R² del modelo completo y quitando cada factor no de mercado."""
    specs = {"Completo": list(factor_cols)}
    for f in factor_cols:
        if f != "market_excess":
            specs[f"Sin {f}"] = [c for c in factor_cols if c != f]
    specs["Solo mercado"] = ["market_excess"]
    rows = []
    for name, factors in specs.items():
        fit = fit_model(train, strategy, factors, hac_lags)
        lo, hi = fit.conf_int().loc["const"]
        rows.append({"model": name, "alpha_daily_bps": fit.params["const"] * 1e4, "ci_low_bps": lo * 1e4,
                     "ci_high_bps": hi * 1e4, "alpha_p_value": fit.pvalues["const"],
                     "beta": fit.params["market_excess"], "r_squared": fit.rsquared})
    return pd.DataFrame(rows).set_index("model")


def annualized_attribution(attr_bps: pd.DataFrame, periods: int = 365) -> pd.DataFrame:
    """E4 · Componentes medios diarios (bps) a % anual aritmético, con su suma de control."""
    out = attr_bps * periods / 100
    out["total"] = out.sum(axis=1)
    return out


def daily_rule_returns(close: pd.Series, lookback: int = 20, round_trip_bps: float = 20.) -> pd.DataFrame:
    """E7 · Regla long/cash diaria: invertido el día t si el momentum de `lookback` días al cierre de t − 1 es positivo.

    La posición se decide con datos hasta ayer. El coste es la mitad del de ida y vuelta en cada cambio de posición.
    """
    r = close.pct_change(fill_method=None)
    momentum = close / close.shift(lookback) - 1
    position = (momentum.shift(1) > 0).astype(float).where(momentum.shift(1).notna())
    trades = position.diff().abs()
    strategy = position * r - trades * round_trip_bps / 2 / 1e4
    out = pd.DataFrame({"strategy": strategy, "benchmark_return": r, "position": position})
    return out.dropna()
