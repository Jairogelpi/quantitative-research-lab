"""Eficiencia débil del mercado: controles sintéticos, autocorrelación, Ljung–Box, pruebas múltiples
(Bonferroni, Benjamini–Hochberg), data snooping, decaimiento de señales y viabilidad económica.

Origen: P11 · Eficiencia del mercado y detección de anomalías. Concepto: docs/conceptos/eficiencia_de_mercado.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.multitest import multipletests

from quantlab.p05.signals import load_p04_series, regularize


# --- Mercados ---------------------------------------------------------------------

def make_market(phi, n: int = 2400, seed: int = 42, window: str = "1min") -> pd.Series:
    """Log-precio con r_t = φ_t · r_{t−1} + ε_t. Todas las series comparten el mismo ruido ε (misma semilla)."""
    phi = np.broadcast_to(np.asarray(phi, dtype=float), (n,))
    rng = np.random.default_rng(seed)
    eps = rng.normal(0, .001, n)
    r = eps.copy()
    for i in range(1, n):
        r[i] = phi[i] * r[i - 1] + eps[i]
    idx = pd.date_range("2026-01-01T00:01:00Z", periods=n, freq=window)
    return pd.Series(60000 * np.exp(np.cumsum(r)), index=idx, name="close")


def make_markets(n: int = 2400, seed: int = 42, train_fraction: float = .65, window: str = "1min") -> dict:
    """Control nulo (φ = 0), control persistente (φ = 0,35) y una señal que desaparece en el corte."""
    cut = int(n * train_fraction)
    return {"Aleatorio": make_market(np.zeros(n), n, seed, window),
            "Persistente": make_market(np.full(n, .35), n, seed, window),
            "Decaimiento": make_market(np.where(np.arange(n) < cut, .35, 0.), n, seed, window)}


def load_p04(path, window: str = "1min") -> pd.Series:
    """`analysis_close` del `*_series.csv` de P04 en una rejilla regular (reutiliza P05)."""
    close, _ = load_p04_series(path)
    return regularize(close, window)


# --- Autocorrelación y Ljung–Box ---------------------------------------------------------

def longest_valid_run(r: pd.Series) -> pd.Series:
    """Tramo contiguo más largo sin huecos: no se comprimen los huecos para calcular autocorrelaciones."""
    groups = r.isna().cumsum()
    runs = [g.dropna() for _, g in r.groupby(groups) if g.notna().any()]
    return max(runs, key=len) if runs else r.iloc[:0]


def split_returns(price: pd.Series, train_fraction: float = .65) -> dict:
    """Retornos log de desarrollo y validación; el `diff` se hace DESPUÉS del corte (ningún retorno lo cruza)."""
    cut = int(len(price) * train_fraction)
    return {"Desarrollo": np.log(price.iloc[:cut]).diff(), "Validación": np.log(price.iloc[cut:]).diff()}


def diagnostics(markets: dict, lags: int = 10, train_fraction: float = .65) -> tuple[pd.DataFrame, pd.DataFrame]:
    """ACF de retardo 1 y p-valor de Ljung–Box por mercado y periodo; exige ≥ máx(60, 5·lags + 1) retornos."""
    rows, acf_rows = [], []
    for name, price in markets.items():
        for period, r in split_returns(price, train_fraction).items():
            series = longest_valid_run(r)
            if len(series) < max(60, 5 * lags + 1) or series.std() == 0:
                rows.append({"mercado": name, "periodo": period, "n": len(series), "acf_1": np.nan, "p_ljung_box": np.nan})
                continue
            lb = acorr_ljungbox(series, lags=[lags], return_df=True)
            rows.append({"mercado": name, "periodo": period, "n": len(series),
                         "acf_1": series.autocorr(1), "p_ljung_box": lb.lb_pvalue.iloc[0]})
            acf_rows += [{"mercado": name, "periodo": period, "lag": k, "acf": series.autocorr(k)} for k in range(1, lags + 1)]
    return pd.DataFrame(rows), pd.DataFrame(acf_rows)


# --- Pruebas múltiples --------------------------------------------------------------------

def pearson_many(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Correlación de Pearson de cada columna de X con y, y su p-valor bilateral (t con n − 2 g.l.)."""
    X0 = X - X.mean(axis=0)
    y0 = y - y.mean()
    corr = (X0.T @ y0) / np.sqrt((X0 ** 2).sum(axis=0) * (y0 ** 2).sum())
    t = corr * np.sqrt((len(y) - 2) / np.maximum(1 - corr ** 2, 1e-15))
    return corr, 2 * stats.t.sf(abs(t), df=len(y) - 2)


def null_signal_experiment(y_dev: np.ndarray, y_test: np.ndarray, n_signals: int = 500, alpha: float = .05,
                           seed: int = 52) -> tuple[pd.DataFrame, int, float]:
    """`n_signals` indicadores aleatorios contra los retornos. Elige UN candidato y su signo solo en desarrollo.

    Devuelve (tabla de pruebas, índice del candidato, signo).
    """
    rng = np.random.default_rng(seed)
    X_dev = rng.normal(size=(len(y_dev), n_signals))
    X_test = rng.normal(size=(len(y_test), n_signals))
    ic_dev, p_dev = pearson_many(X_dev, y_dev)
    ic_test, p_test = pearson_many(X_test, y_test)
    _, p_bonf, _, _ = multipletests(p_dev, alpha=alpha, method="bonferroni")
    _, p_bh, _, _ = multipletests(p_dev, alpha=alpha, method="fdr_bh")
    best = int(np.argmax(np.abs(ic_dev)))
    table = pd.DataFrame({"signal_id": np.arange(n_signals), "ic_dev": ic_dev, "p_dev": p_dev,
                          "p_bonferroni": p_bonf, "p_bh": p_bh, "ic_test": ic_test, "p_test": p_test})
    return table, best, float(np.sign(ic_dev[best]))


def monte_carlo_false_positives(n_simulations: int = 3000, n_signals: int = 500, alpha: float = .05,
                                seed: int = 62) -> dict:
    """Bajo H0 los p-valores independientes son uniformes: cuenta rechazos falsos por experimento."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(size=(n_simulations, n_signals))
    false_counts = (p < alpha).sum(axis=1)
    return {"false_counts": false_counts, "mean": false_counts.mean(), "theory": n_signals * alpha,
            "p_at_least_one": (false_counts > 0).mean(), "p_at_least_one_bonferroni": (p.min(axis=1) < alpha / n_signals).mean()}


# --- Economía ---------------------------------------------------------------------------------

def trade_experiment(price: pd.Series, cost_bps: float, train_fraction: float = .65) -> pd.DataFrame:
    """Señal fijada de antemano: comprar si el último retorno es positivo (spot 0/1, sin cortos).

    Señal en t, entrada en t + 1, salida en t + 2; decisiones cada 2 velas para no solapar.
    net = gross − coste de ida y vuelta (el coste incluye las dos piernas y no se resta dos veces).
    """
    cut = int(len(price) * train_fraction)
    output = []
    for period, p in [("Desarrollo", price.iloc[:cut]), ("Validación", price.iloc[cut:])]:
        frame = pd.DataFrame({"r": np.log(p).diff(), "entry": p.shift(-1), "exit": p.shift(-2)})
        frame = frame.iloc[::2].dropna()
        gross = frame["exit"] / frame["entry"] - 1
        chosen = gross[frame.r > 0]
        output.append({"periodo": period, "n_trades": len(chosen), "gross_bps": chosen.mean() * 10000,
                       "net_bps": chosen.mean() * 10000 - cost_bps, "baseline_gross_bps": gross.mean() * 10000})
    return pd.DataFrame(output)


# --- Ejercicios ----------------------------------------------------------------------------------

def manual_autocorrelation(values, lag: int) -> float:
    """E1 · Pearson entre x_t y x_{t−lag} sobre los pares en que ambos existen (los huecos no se comprimen)."""
    x = np.asarray(values, dtype=float)
    if lag < 1 or lag >= len(x):
        raise ValueError("Retardo fuera de rango")
    a, b = x[lag:], x[:-lag]
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return np.nan
    da, db = a - a.mean(), b - b.mean()
    den = np.sqrt((da ** 2).sum() * (db ** 2).sum())
    return float((da * db).sum() / den) if den > 0 else np.nan


def random_walk_acf(n_series: int = 100, n: int = 1000, seed: int = 7, lag: int = 1) -> pd.DataFrame:
    """E2 · Autocorrelación de niveles frente a retornos en paseos aleatorios independientes."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_series):
        r = rng.normal(0, .001, n)
        price = 60000 * np.exp(np.cumsum(r))
        rows.append({"acf_levels": manual_autocorrelation(price, lag), "acf_returns": manual_autocorrelation(r, lag),
                     "total_return_pct": 100 * (price[-1] / price[0] - 1)})
    return pd.DataFrame(rows)


def ljung_box_table(series: pd.Series, lags=(5, 10)) -> pd.DataFrame:
    """E3 · Estadístico y p-valor de Ljung–Box para retardos fijados a priori."""
    lb = acorr_ljungbox(series.dropna(), lags=list(lags), return_df=True)
    return lb.rename_axis("lags")


def ljung_box_power(phi: float = .05, sizes=(500, 2000, 10000), lags: int = 5, reps: int = 200,
                    alpha: float = .05, seed: int = 11) -> pd.DataFrame:
    """E3 · Frecuencia de rechazo de Ljung–Box con una dependencia débil fija según el tamaño de muestra."""
    rng = np.random.default_rng(seed)
    rows = []
    for n in sizes:
        rejections = 0
        for _ in range(reps):
            eps = rng.normal(0, 1, n)
            r = eps.copy()
            for i in range(1, n):
                r[i] = phi * r[i - 1] + eps[i]
            rejections += acorr_ljungbox(r, lags=[lags], return_df=True).lb_pvalue.iloc[0] < alpha
        rows.append({"n": n, "rejection_rate": rejections / reps})
    return pd.DataFrame(rows).set_index("n")


def bonferroni_manual(pvalues, alpha: float = .05) -> np.ndarray:
    """E4 · Rechaza H0_i si p_i < α / m."""
    p = np.asarray(pvalues, dtype=float)
    return p < alpha / len(p)


def false_positive_table(ms=(20, 100, 500), alpha: float = .05, n_simulations: int = 3000, seed: int = 62) -> pd.DataFrame:
    """E4 · Falsos positivos esperados (m·α) y P(≥ 1), teóricos y por Monte Carlo, con y sin Bonferroni."""
    rows = []
    for m in ms:
        mc = monte_carlo_false_positives(n_simulations, m, alpha, seed)
        rows.append({"m": m, "expected_theory": m * alpha, "expected_mc": mc["mean"],
                     "p_at_least_one_theory": 1 - (1 - alpha) ** m, "p_at_least_one_mc": mc["p_at_least_one"],
                     "p_at_least_one_bonferroni_mc": mc["p_at_least_one_bonferroni"]})
    return pd.DataFrame(rows).set_index("m")


def max_ic_by_count(y_dev: np.ndarray, y_test: np.ndarray, counts=(100, 500, 1000), seeds=(101, 202, 303)) -> pd.DataFrame:
    """E5 · IC máximo en desarrollo según el número de señales nulas; cada experimento con su semilla.

    La selección (índice y signo) se congela en desarrollo antes de calcular su IC en validación.
    """
    rows = []
    for count, seed in zip(counts, seeds):
        table, best, direction = null_signal_experiment(y_dev, y_test, count, seed=seed)
        rows.append({"n_signals": count, "seed": seed, "max_abs_ic_dev": abs(table.ic_dev.iloc[best]),
                     "oriented_ic_test": direction * table.ic_test.iloc[best], "p_test": table.p_test.iloc[best],
                     "expected_max_abs_ic": float(np.sqrt(2 * np.log(count) / len(y_dev)))})
    return pd.DataFrame(rows).set_index("n_signals")


def rolling_autocorr(returns: pd.Series, window: int = 200, lag: int = 1) -> pd.Series:
    """E6 · Autocorrelación móvil de retardo `lag` con ventana hacia atrás (sin centrar: no usa el futuro)."""
    r = pd.Series(returns, dtype=float)
    return r.rolling(window, min_periods=window).corr(r.shift(lag))


def regime_detection_delay(rolling: pd.Series, change_at, threshold: float) -> dict:
    """E6 · Velas desde el cambio de régimen hasta que la autocorrelación móvil cruza `threshold` por debajo."""
    after = rolling.loc[rolling.index >= change_at]
    below = after.index[after < threshold]
    first = below[0] if len(below) else pd.NaT
    return {"first_below": first, "bars_after_change": int(rolling.index.get_loc(first) - rolling.index.get_loc(after.index[0]))
            if len(below) else np.nan}
