"""Diversificación y regímenes macro: riesgo de cartera y contribuciones, riesgo sistemático frente a residual,
regímenes de política monetaria y unión de datos macro por su disponibilidad real (point-in-time).

Origen: P15 · Regímenes macroeconómicos y diversificación. Concepto: docs/conceptos/regimenes_y_diversificacion.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ASSETS = ["BTC", "Acciones", "Bonos", "Oro"]
MACRO_COLS = ["policy_rate_pct", "inflation_yoy_pct", "yield_2y_pct", "yield_10y_pct", "balance_usd_bn"]
REGIMES = ["Subida", "Estable", "Bajada"]


# --- Datos ------------------------------------------------------------------------

def synthetic_inputs(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retornos semanales ficticios en EUR y un histórico macro con ciclos de 6 meses (subida, pausa, bajada).

    Durante las subidas (estado 0) se introducen más volatilidad, menor retorno y una correlación
    acciones-bonos positiva.
    """
    rng = np.random.default_rng(seed)
    months = pd.date_range("2019-12-01", periods=74, freq="MS", tz="UTC")
    phase = (np.arange(len(months)) // 6) % 3
    step = np.choose(phase, [.25, 0., -.25])
    rate = 3 + np.cumsum(step)
    balance = 5000 + np.cumsum(np.choose(phase, [-45., 0., 65.]))
    inflation = 2.5 + .8 * np.sin(np.arange(len(months)) / 5)
    macro = pd.DataFrame({"available_at": months + pd.Timedelta(days=10, hours=13), "policy_rate_pct": rate,
                          "inflation_yoy_pct": inflation, "yield_2y_pct": rate + .2,
                          "yield_10y_pct": rate + .2 + np.choose(phase, [-.4, .2, .8]), "balance_usd_bn": balance})
    dates = pd.date_range("2020-01-03", "2025-12-26", freq="W-FRI", tz="UTC")
    decision = dates - pd.Timedelta(days=11)  # lunes de la semana anterior
    ix = np.searchsorted(macro.available_at.astype("int64"), decision.astype("int64"), side="right") - 1
    states = phase[np.maximum(ix, 0)]
    stress = (states == 0).astype(float)
    mkt, rate_shock, gold_shock = rng.normal(size=(3, len(dates)))
    noise = rng.normal(size=(4, len(dates)))
    ret = np.column_stack([.003 - .005 * stress + (.028 + .025 * stress) * mkt + .045 * noise[0],
                           .002 - .003 * stress + .022 * mkt + .012 * noise[1],
                           .001 - .001 * stress + (-.008 + .019 * stress) * mkt + .012 * rate_shock + .004 * noise[2],
                           .001 + .003 * gold_shock + .009 * noise[3]])
    return pd.DataFrame(ret, columns=ASSETS, index=dates).rename_axis("date"), macro


def validate_returns(returns: pd.DataFrame, min_weeks: int = 80) -> pd.DataFrame:
    """Retornos semanales en viernes consecutivos, únicos, finitos y > −100 %."""
    r = returns.sort_index().apply(pd.to_numeric, errors="raise")
    if (len(r) < min_weeks or r.index.has_duplicates or not (r.index.day_of_week == 4).all()
            or not (r.index.to_series().diff().dropna() == pd.Timedelta(days=7)).all()):
        raise ValueError(f"Se requieren al menos {min_weeks} retornos semanales consecutivos, viernes únicos")
    if not np.isfinite(r.to_numpy()).all() or (r <= -1).any().any():
        raise ValueError("Retornos ausentes, no finitos o <= -100%")
    return r


def validate_macro(macro: pd.DataFrame) -> pd.DataFrame:
    """Estado macro con `available_at` en UTC, sin duplicados y con valores finitos."""
    m = macro.copy()
    m["available_at"] = pd.to_datetime(m.available_at, utc=True, errors="raise")
    m = m.sort_values("available_at").reset_index(drop=True)
    m[MACRO_COLS] = m[MACRO_COLS].apply(pd.to_numeric, errors="raise")
    if len(m) < 2 or m.available_at.duplicated().any() or not np.isfinite(m[MACRO_COLS].to_numpy()).all():
        raise ValueError("Histórico macro insuficiente, duplicado o incompleto")
    return m


def macro_indicators(macro: pd.DataFrame, rate_tol: float = .01, balance_tol: float = .1) -> pd.DataFrame:
    """Cambio de tipos, cambio de balance, tipo real aproximado, pendiente y regímenes de tipos y de balance."""
    m = macro.copy()
    m["policy_change_pp"] = m.policy_rate_pct.diff()
    m["balance_change_pct"] = m.balance_usd_bn.pct_change(fill_method=None) * 100
    m["real_policy_proxy_pct"] = m.policy_rate_pct - m.inflation_yoy_pct
    m["yield_curve_bps"] = (m.yield_10y_pct - m.yield_2y_pct) * 100
    m["regime"] = np.select([m.policy_change_pp > rate_tol, m.policy_change_pp < -rate_tol, m.policy_change_pp.notna()],
                            ["Subida", "Bajada", "Estable"], default="Desconocido")
    m["balance_regime"] = np.select([m.balance_change_pct > balance_tol, m.balance_change_pct < -balance_tol,
                                     m.balance_change_pct.notna()], ["Expansión", "Contracción", "Estable"],
                                    default="Desconocido")
    return m


def align_panel(returns: pd.DataFrame, macro: pd.DataFrame, weights: pd.Series, max_age_days: int = 75,
                split: float = .65, lag_days: int = 11) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Une cada retorno semanal con el último estado macro DISPONIBLE antes del lunes de la semana anterior.

    `merge_asof` hacia atrás con antigüedad máxima: sin estado reciente, el régimen queda desconocido.
    """
    frame = returns.reset_index().rename(columns={"index": "date"})
    frame["decision_at"] = frame.date - pd.Timedelta(days=lag_days)
    panel = pd.merge_asof(frame.sort_values("decision_at"), macro, left_on="decision_at", right_on="available_at",
                          direction="backward", tolerance=pd.Timedelta(days=max_age_days))
    cutoff = frame.date.iloc[int(len(frame) * split)]
    panel["split"] = np.where(panel.date < cutoff, "Desarrollo", "Validación")
    panel["portfolio_return"] = panel[list(weights.index)] @ weights
    panel["known_regime"] = panel.regime.isin(REGIMES)
    return panel, cutoff


# --- Riesgo ------------------------------------------------------------------------------

def portfolio_risk(ret: pd.DataFrame, weights: pd.Series) -> tuple[float, pd.Series]:
    """σ_p = √(wᵀΣw) y contribución de cada activo: w_i · (Σw)_i / σ_p (suman σ_p)."""
    cov = ret[weights.index].cov()
    variance = float(weights @ cov @ weights)
    vol = np.sqrt(max(variance, 0))
    contribution = weights * (cov @ weights) / vol if vol > 0 else weights * np.nan
    return vol, contribution


def systematic_decomposition(dev: pd.DataFrame, val: pd.DataFrame, asset: str = "BTC", factor: str = "Acciones") -> dict:
    """OLS de `asset` sobre `factor` en desarrollo: alpha, beta, varianza explicada y RMSE en validación."""
    x, y = dev[factor].to_numpy(), dev[asset].to_numpy()
    alpha, beta = np.linalg.lstsq(np.column_stack([np.ones(len(x)), x]), y, rcond=None)[0]
    fitted = alpha + beta * x
    resid = y - fitted
    total = np.var(y, ddof=1)
    if total <= 0:
        raise ValueError(f"{asset} tiene varianza cero")
    return {"alpha": alpha, "beta": beta, "systematic_var": np.var(fitted, ddof=1), "residual_var": np.var(resid, ddof=1),
            "total_var": total, "explained_share": np.var(fitted, ddof=1) / total, "resid": resid, "x": x,
            "val_rmse": float(np.sqrt(np.mean((val[asset] - (alpha + beta * val[factor])) ** 2)))}


def regime_summary(panel: pd.DataFrame, cols, min_obs: int = 12) -> tuple[pd.DataFrame, pd.Series]:
    """Retorno semanal medio (%) por periodo y régimen conocido; NaN si el grupo tiene menos de `min_obs`."""
    known = panel[panel.known_regime]
    means = known.groupby(["split", "regime"])[list(cols)].mean() * 100
    counts = known.groupby(["split", "regime"]).size()
    return means.where(counts >= min_obs, axis=0), counts


def regime_correlations(panel: pd.DataFrame, a: str = "Acciones", b: str = "Bonos", min_obs: int = 12) -> pd.Series:
    """Correlación entre dos activos por periodo y régimen; NaN si hay menos de `min_obs` semanas."""
    out = {}
    for (split, regime), group in panel[panel.known_regime].groupby(["split", "regime"]):
        out[(split, regime)] = group[a].corr(group[b]) if len(group) >= min_obs else np.nan
    return pd.Series(out, dtype=float).rename(f"corr_{a}_{b}")


# --- Ejercicios ----------------------------------------------------------------------------------

def two_asset_variance(w: float, sigma_a: float, sigma_b: float, rho: float) -> float:
    """E1 · σ²_p = w²σ²_a + (1 − w)²σ²_b + 2w(1 − w)ρσ_aσ_b, sin usar `cov`."""
    if not -1 <= rho <= 1 or sigma_a < 0 or sigma_b < 0:
        raise ValueError("Correlación o volatilidades inválidas")
    return w ** 2 * sigma_a ** 2 + (1 - w) ** 2 * sigma_b ** 2 + 2 * w * (1 - w) * rho * sigma_a * sigma_b


def zero_variance_weight(sigma_a: float, sigma_b: float) -> float:
    """E1 · Peso en A que anula la varianza con ρ = −1: σ_b / (σ_a + σ_b)."""
    return sigma_b / (sigma_a + sigma_b)


def diversification_curve(ns=(1, 2, 5, 10, 20, 50, 100, 200), beta: float = 1., factor_vol: float = .02,
                          idio_vol: float = .04, weeks: int = 2000, seed: int = 7) -> pd.DataFrame:
    """E3 · Volatilidad de una cartera equiponderada de N activos con un factor común y ruido independiente.

    Teoría: σ²_p = β²σ²_f + σ²_ε / N. El primer término no desaparece al diversificar.
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0, factor_vol, weeks)
    noise = rng.normal(0, idio_vol, (weeks, max(ns)))
    rows = []
    for n in ns:
        port = beta * factor + noise[:, :n].mean(axis=1)
        rows.append({"N": n, "vol_simulated": port.std(ddof=1),
                     "vol_theory": np.sqrt(beta ** 2 * factor_vol ** 2 + idio_vol ** 2 / n),
                     "systematic_floor": beta * factor_vol})
    return pd.DataFrame(rows).set_index("N")


def balance_vs_rates(macro: pd.DataFrame) -> pd.DataFrame:
    """E5 · Tabla cruzada de régimen de tipos frente a régimen de balance (meses)."""
    known = macro[macro.regime.isin(REGIMES) & macro.balance_regime.ne("Desconocido")]
    return pd.crosstab(known.regime, known.balance_regime).reindex(REGIMES)


def delayed_publication_demo(n_weeks: int = 12, delay_days: int = 15) -> pd.DataFrame:
    """E6 · Unión por fecha de referencia frente a unión por disponibilidad con una publicación retrasada.

    Un dato del mes de marzo se publica el 15 de abril (delay). La unión por referencia lo "conoce" desde marzo.
    """
    weeks = pd.date_range("2024-03-01", periods=n_weeks, freq="W-FRI", tz="UTC")
    ref = pd.Timestamp("2024-03-01", tz="UTC")
    macro = pd.DataFrame({"reference": [ref], "available_at": [ref + pd.offsets.MonthBegin(1) + pd.Timedelta(days=delay_days - 1)],
                          "value": [1.0]})
    frame = pd.DataFrame({"date": weeks})
    by_reference = pd.merge_asof(frame, macro[["reference", "value"]], left_on="date", right_on="reference", direction="backward")
    by_availability = pd.merge_asof(frame, macro[["available_at", "value"]], left_on="date", right_on="available_at",
                                    direction="backward")
    return pd.DataFrame({"date": weeks, "known_by_reference": by_reference.value.notna(),
                         "known_by_availability": by_availability.value.notna(), "available_at": macro.available_at.iloc[0]})


def correlation_difference(panel: pd.DataFrame, regime: str = "Subida", a: str = "Acciones", b: str = "Bonos",
                           period: str = "Validación") -> dict:
    """E8 · Correlación en `regime` frente al resto, con IC del 95 % de la diferencia (transformada de Fisher).

    Supone observaciones independientes: con dependencia temporal, el intervalo es optimista.
    """
    d = panel[(panel.split == period) & panel.known_regime]
    g1, g2 = d[d.regime == regime], d[d.regime != regime]
    r1, r2 = g1[a].corr(g1[b]), g2[a].corr(g2[b])
    n1, n2 = len(g1), len(g2)
    z = np.arctanh(r1) - np.arctanh(r2)
    se = np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
    return {"period": period, "n_regime": n1, "n_rest": n2, "corr_regime": r1, "corr_rest": r2,
            "diff": r1 - r2, "z_diff": z, "z_ci_low": z - 1.96 * se, "z_ci_high": z + 1.96 * se,
            "significant": bool(abs(z) > 1.96 * se)}
