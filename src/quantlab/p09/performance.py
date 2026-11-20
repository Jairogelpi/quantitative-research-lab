"""Evaluador de estrategias: curva de capital, drawdown, CAGR, volatilidad, Sharpe, Sortino, Calmar,
métricas por operación cerrada, sensibilidad a costes y riesgo de ruina por bootstrap de bloques.

Origen: P09 · Evaluación de rentabilidad y riesgo. Concepto: docs/conceptos/rentabilidad_y_riesgo.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --- Datos ------------------------------------------------------------------

def synthetic_daily(seed: int = 42, cost_bps: float = 20., capital: float = 1000., days: int = 365) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retornos diarios ficticios (beta 0,35 a un mercado sintético, alfa bruto 7 bps/día y un episodio
    adverso de 10 días) y el registro equivalente de una operación cerrada al día con reinversión total."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=days, freq="D", tz="UTC")
    market = rng.normal(.00065, .018, len(dates))
    gross = .0007 + .35 * market + rng.normal(0, .008, len(dates))
    gross[120:130] -= .013
    net = gross - cost_bps / 1e4
    daily = pd.DataFrame({"net_return": net, "gross_return": gross, "benchmark_return": market}, index=dates)
    daily.index.name = "timestamp"
    before = capital * np.r_[1, np.cumprod(1 + net)[:-1]]
    trades = pd.DataFrame({"exit_time": dates, "gross_pnl": before * gross, "cost": before * cost_bps / 1e4,
                           "net_pnl": before * net})
    return daily, trades


def validate_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Exige al menos 2 días únicos, ordenados y consecutivos, y retornos finitos > −100 %.

    Lanza ValueError ante fechas duplicadas o insuficientes, huecos, falta de `net_return`
    o retornos inválidos. Los huecos no se imputan.
    """
    df = df.copy()
    if len(df) < 2 or not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError("Fechas duplicadas o insuficientes")
    if not (df.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all():
        raise ValueError("Frecuencia irregular: investiga los huecos")
    if "net_return" not in df:
        raise ValueError("Falta net_return")
    for col in ["net_return", "gross_return", "benchmark_return"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="raise")
            if not np.isfinite(df[col]).all() or (df[col] <= -1).any():
                raise ValueError(f"Retornos inválidos: {col}")
    return df


def load_daily_csv(path) -> pd.DataFrame:
    """Lee `timestamp,net_return` (y opcionalmente `gross_return,benchmark_return`) y lo valida."""
    daily = pd.read_csv(path)
    daily["timestamp"] = pd.to_datetime(daily.timestamp, utc=True, errors="raise")
    return validate_daily(daily.set_index("timestamp").sort_index())


# --- Capital y drawdown --------------------------------------------------------

def equity_curve(returns, capital: float = 1000) -> pd.Series:
    """E_t = E_{t−1}·(1 + r_t), con el capital inicial como primer punto (un periodo antes)."""
    r = pd.Series(returns, dtype=float)
    if capital <= 0 or r.empty or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError("Datos inválidos")
    initial = r.index[0] - pd.Timedelta(days=1) if isinstance(r.index, pd.DatetimeIndex) else -1
    return pd.concat([pd.Series([capital], index=[initial]), capital * (1 + r).cumprod()]).rename("equity")


def drawdown(equity: pd.Series) -> pd.Series:
    """D_t = E_t / máx_{s≤t} E_s − 1 (≤ 0). Incluye el capital inicial en el máximo."""
    return (equity / equity.cummax() - 1).rename("drawdown")


# --- Métricas ---------------------------------------------------------------------

def performance_metrics(returns, capital: float = 1000., periods: int = 365, rf_annual: float = .02) -> pd.Series:
    """Capital final, retorno acumulado, CAGR, volatilidad anualizada, MDD, Sharpe, Sortino y Calmar.

    Un denominador nulo da NaN; un CAGR negativo da un Calmar negativo.
    """
    r = pd.Series(returns, dtype=float)
    if len(r) < 2 or periods <= 0 or rf_annual <= -1:
        raise ValueError("Parámetros inválidos")
    e = equity_curve(r, capital)
    mdd = -drawdown(e).min()
    excess = r - ((1 + rf_annual) ** (1 / periods) - 1)
    std = r.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
    cagr = (e.iloc[-1] / capital) ** (periods / len(r)) - 1

    def ratio(a, b):
        return a / b if b > 1e-14 else np.nan
    return pd.Series({"final_equity": e.iloc[-1], "cumulative_return": e.iloc[-1] / capital - 1, "cagr": cagr,
                      "annualized_volatility": std * np.sqrt(periods), "max_drawdown": mdd,
                      "sharpe_ratio": ratio(excess.mean() * np.sqrt(periods), std),
                      "sortino_ratio": ratio(excess.mean() * np.sqrt(periods), downside),
                      "calmar_ratio": ratio(cagr, mdd)})


def trade_metrics(pnl) -> pd.Series:
    """Acierto, pérdidas, neutras, ganancia y pérdida medias, payoff, profit factor, esperanza y PnL total.

    Las operaciones a cero cuentan en los denominadores. Sin pérdidas, el profit factor es infinito
    si hubo ganancias y NaN si todo fue cero.
    """
    x = pd.Series(pnl, dtype=float)
    if x.empty or not np.isfinite(x).all():
        raise ValueError("Registro vacío o no finito")
    w, l = x[x > 0], x[x < 0]
    loss = -l.sum()
    return pd.Series({"trade_count": len(x), "win_rate": len(w) / len(x), "loss_rate": len(l) / len(x),
                      "flat_rate": (x == 0).mean(), "average_win": w.mean(), "average_loss": -l.mean(),
                      "payoff_ratio": w.mean() / (-l.mean()) if len(w) and len(l) else np.nan,
                      "profit_factor": w.sum() / loss if loss > 0 else (np.inf if w.sum() > 0 else np.nan),
                      "expectancy": x.mean(), "net_pnl": x.sum()})


def cost_sensitivity(gross_returns, cost_levels=(0, 5, 10, 20, 30, 40)) -> pd.DataFrame:
    """Retorno acumulado restando un coste diario hipotético al retorno BRUTO (no al neto)."""
    g = pd.Series(gross_returns, dtype=float)
    rows = [{"cost_bps_per_day": bps, "total_return_pct": 100 * ((1 + g - bps / 1e4).prod() - 1)}
            for bps in cost_levels if (g - bps / 1e4 > -1).all()]
    return pd.DataFrame(rows)


# --- Riesgo de ruina ------------------------------------------------------------------

def simulate_ruin(returns, exposure: float = 1., threshold: float = .5, horizon: int = 180, block: int = 5,
                  paths: int = 3000, seed: int = 42) -> tuple[float, np.ndarray]:
    """Probabilidad de tocar `threshold` del capital inicial en `horizon` periodos, por bootstrap de bloques.

    Extrae bloques contiguos de `block` retornos con reemplazo; el capital cero es absorbente.
    Devuelve (probabilidad, trayectorias relativas al capital inicial).
    """
    r = np.asarray(returns, dtype=float)
    if (not np.isfinite(r).all() or not 1 <= block <= len(r) or horizon < 1 or paths < 1
            or not 0 < threshold < 1 or exposure < 0):
        raise ValueError("Parámetros inválidos")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(r) - block + 1, size=(paths, int(np.ceil(horizon / block))))
    sampled = r[starts[:, :, None] + np.arange(block)].reshape(paths, -1)[:, :horizon]
    trajectories = np.column_stack([np.ones(paths), np.cumprod(np.maximum(1 + exposure * sampled, 0), axis=1)])
    return (trajectories <= threshold).any(axis=1).mean(), trajectories


def ruin_table(returns, exposures=(.25, .5, 1., 1.5), capital: float = 1000., **kwargs) -> pd.DataFrame:
    """Riesgo de ruina y capital final mediano para varias exposiciones."""
    rows = []
    for exp in exposures:
        p, paths = simulate_ruin(returns, exposure=exp, **kwargs)
        rows.append({"exposure": exp, "risk_of_ruin": p, "median_final_capital": capital * np.median(paths[:, -1])})
    return pd.DataFrame(rows)


# --- Ejercicios -------------------------------------------------------------------------

def manual_equity_drawdown(returns, capital: float = 1000.) -> pd.DataFrame:
    """E1 · Capital, máximo histórico y drawdown con un bucle, sin `cumprod` ni `cummax`."""
    if capital <= 0:
        raise ValueError("Capital no positivo")
    equity, peak = capital, capital
    rows = [{"equity": capital, "peak": capital, "drawdown": 0.0}]
    for r in returns:
        if not np.isfinite(r) or r <= -1:
            raise ValueError("Retorno inválido")
        equity = equity * (1 + r)
        peak = peak if peak >= equity else equity
        rows.append({"equity": equity, "peak": peak, "drawdown": equity / peak - 1})
    return pd.DataFrame(rows)


def recovery_return(loss) -> np.ndarray | float:
    """E2 · Retorno necesario para recuperar una pérdida L: 1 / (1 − L) − 1."""
    loss = np.asarray(loss, dtype=float)
    if ((loss < 0) | (loss >= 1)).any():
        raise ValueError("La pérdida debe estar en [0, 1)")
    out = 1 / (1 - loss) - 1
    return float(out) if out.ndim == 0 else out


def risk_free_comparison(returns, rates=(0., .02, .05), periods: int = 365) -> pd.DataFrame:
    """E4 · Sharpe y Sortino con distintos tipos libres de riesgo anuales."""
    return pd.DataFrame({f"rf_{rate:.0%}": performance_metrics(returns, periods=periods, rf_annual=rate)
                         [["sharpe_ratio", "sortino_ratio"]] for rate in rates}).T


def break_even_daily_cost(gross_returns, max_bps: float = 1000., tol: float = 1e-6) -> dict:
    """E5 · Menor coste diario (bps) con el que el retorno acumulado deja de ser positivo.

    Si ya es ≤ 0 sin costes, el umbral es 0 y `already_losing` es True. Bisección sobre la función
    monótona decreciente coste → retorno acumulado.
    """
    g = pd.Series(gross_returns, dtype=float)

    def total(bps):
        return (1 + g - bps / 1e4).prod() - 1
    base = total(0)
    if base <= 0:
        return {"break_even_bps": 0.0, "already_losing": True, "total_return_at_zero_cost": base}
    lo, hi = 0., max_bps
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if total(mid) > 0 else (lo, mid)
    return {"break_even_bps": hi, "already_losing": False, "total_return_at_zero_cost": base}


def ruin_grid(returns, thresholds=(.5, .7), horizons=(180, 365), blocks=(1, 5, 10), exposure: float = 1.,
              paths: int = 3000, seed: int = 42) -> pd.DataFrame:
    """E6 · Riesgo de ruina para combinaciones de umbral, horizonte y tamaño de bloque."""
    rows = []
    for th in thresholds:
        for h in horizons:
            for b in blocks:
                p, traj = simulate_ruin(returns, exposure, th, h, b, paths, seed)
                rows.append({"threshold": th, "horizon": h, "block": b, "risk_of_ruin": p,
                             "ruined_paths": int(round(p * paths)), "median_final": np.median(traj[:, -1])})
    return pd.DataFrame(rows)


def trade_log_to_pnl(log: pd.DataFrame, capital: float = 1000.) -> pd.DataFrame:
    """E7 · Convierte un registro de P05 (`net_return` por operación, sin solapamiento) en PnL en EUR
    con reinversión total: capital_antes = capital · ∏(1 + r) desplazado una operación."""
    out = log.copy()
    before = capital * (1 + out.net_return).cumprod().shift(1, fill_value=1)
    out["capital_before"] = before
    out["net_pnl"] = before * out.net_return
    out["gross_pnl"] = before * out.gross_return
    return out


def split_stability(returns, capital: float = 1000., periods: int = 365, rf_annual: float = .02,
                    fraction: float = .5) -> pd.DataFrame:
    """E8 · Métricas en dos tramos cronológicos con los mismos parámetros."""
    r = pd.Series(returns, dtype=float)
    cut = int(len(r) * fraction)
    return pd.DataFrame({"primer tramo": performance_metrics(r.iloc[:cut], capital, periods, rf_annual),
                         "segundo tramo": performance_metrics(r.iloc[cut:], capital, periods, rf_annual)})
