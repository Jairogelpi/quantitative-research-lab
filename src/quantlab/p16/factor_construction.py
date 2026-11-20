"""Construcción de factores: scores conocidos antes de invertir, carteras long-short por cuantiles, costes de
rotación, validación cronológica con errores HAC, modelos Fama-French oficiales y payoffs de derivados.

Origen: P16 · Construcción de factores financieros. Concepto: docs/conceptos/construccion_de_factores.md
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

SCORES = ["size", "value", "quality", "momentum", "low_vol", "carry", "liquidity", "investment"]
PANEL_COLUMNS = ["month", "asset", "available_at", "market_cap", "book_to_market", "roa", "carry_score",
                 "illiquidity", "asset_growth", "asset_return", "rf"]
# Columna del panel → score (signo: score alto = lado comprado).
ACCOUNTING_SCORES = {"size": ("market_cap", lambda x: -np.log(x)), "value": ("book_to_market", lambda x: x),
                     "quality": ("roa", lambda x: x), "carry": ("carry_score", lambda x: x),
                     "liquidity": ("illiquidity", lambda x: x), "investment": ("asset_growth", lambda x: -x)}
FF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF_FILES = {"ff3": ("F-F_Research_Data_Factors_CSV.zip", ["Mkt-RF", "SMB", "HML", "RF"]),
            "ff5": ("F-F_Research_Data_5_Factors_2x3_CSV.zip", ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"])}
CRYPTO_TICKERS = ["BTC", "ETH", "XRP", "LTC", "BCH", "ADA", "DOGE", "XLM", "LINK", "TRX",
                  "ETC", "XMR", "EOS", "DASH", "ZEC", "BNB", "SOL", "DOT", "AVAX", "ATOM"]


# --- Datos ------------------------------------------------------------------------

def synthetic_panel(seed: int = 42, months: int = 120, assets: int = 60, rf_monthly: float = .002) -> pd.DataFrame:
    """Panel mensual artificial con primas de value (+) y size (pequeñas ganan) programadas; el resto no.

    Size, value y quality evolucionan como paseos aleatorios; carry, iliquidez e inversión son constantes.
    Las características de cada mes se fijan antes de generar su retorno.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", periods=months, freq="MS")
    names = [f"A{i:03d}" for i in range(assets)]
    size, value, quality, carry, illiq, invest = rng.normal(size=(6, assets))
    rows = []
    for date in dates:
        common = rng.normal(.005, .035)
        ret = common + .004 * value - .002 * size + rng.normal(0, .055, assets)
        for i, asset in enumerate(names):
            rows.append((date, asset, date - pd.Timedelta(days=1), np.exp(20 + size[i]), np.exp(-.5 + value[i] * .35),
                         .08 + .025 * quality[i], .01 + .005 * carry[i], np.exp(illiq[i]), .08 + .04 * invest[i],
                         ret[i], rf_monthly))
        size += rng.normal(0, .10, assets)
        value += rng.normal(0, .10, assets)
        quality += rng.normal(0, .08, assets)
    return pd.DataFrame(rows, columns=PANEL_COLUMNS)


def validate_panel(panel: pd.DataFrame, required=("month", "asset", "available_at", "asset_return", "rf")) -> pd.DataFrame:
    """Valida el panel y lo devuelve ordenado por activo y mes. Lanza ValueError en lugar de corregir datos.

    Exige meses en el primer día, características conocidas ANTES del mes (`available_at < month`), sin duplicados
    activo-mes, capitalización > 0 si existe, retornos ≥ −100 % (los ausentes quedan como NaN) y un único RF por mes.
    """
    missing = set(required) - set(panel)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    out = panel.copy()
    for col in ("month", "available_at"):
        out[col] = pd.to_datetime(out[col], utc=True).dt.tz_convert(None)
    if not (out.month == out.month.dt.to_period("M").dt.to_timestamp()).all():
        raise ValueError("`month` debe ser el primer día del mes de tenencia")
    if not (out.available_at < out.month).all():
        raise ValueError("Características no disponibles al decidir (available_at ≥ month)")
    if out.duplicated(["month", "asset"]).any():
        raise ValueError("Filas activo-mes duplicadas")
    if "market_cap" in out and not (out.market_cap > 0).all():
        raise ValueError("Capitalización ≤ 0")
    if (out.asset_return < -1).any():
        raise ValueError("Retorno inferior a −100 %")
    if not out.groupby("month").rf.nunique(dropna=False).eq(1).all():
        raise ValueError("RF distinto entre activos del mismo mes")
    return out.sort_values(["asset", "month"]).reset_index(drop=True)


def add_scores(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    """Añade los scores y devuelve (panel, momentum, low_vol, calendario).

    Momentum 12-2: producto de los 11 retornos de t−12 a t−2. Low Vol: −desviación típica de t−6 a t−1.
    El calendario mensual se reindexa completo, así que un mes ausente no cuenta como retorno 0.
    Los scores contables solo se crean si su columna existe (en cripto no hay book-to-market ni ROA).
    """
    months = pd.date_range(panel.month.min(), panel.month.max(), freq="MS")
    matrix = panel.pivot(index="month", columns="asset", values="asset_return").reindex(months)
    mom = (1 + matrix.shift(2)).rolling(11, min_periods=11).apply(np.prod, raw=True) - 1
    lowvol = -matrix.shift(1).rolling(6, min_periods=6).std()
    out = panel.drop(columns=["momentum", "low_vol"], errors="ignore")
    for name, wide in (("momentum", mom), ("low_vol", lowvol)):
        long = wide.rename_axis(index="month", columns="asset").stack().rename(name).reset_index()
        out = out.merge(long, on=["month", "asset"], how="left")
    for score, (col, transform) in ACCOUNTING_SCORES.items():
        if col in out:
            out[score] = transform(out[col])
    return out, mom, lowvol, months


# --- Carteras y costes -----------------------------------------------------------------

def long_short_weights(month_data: pd.DataFrame, score: str, fraction: float = .30) -> pd.Series:
    """Pesos +1/k para el k superior y −1/k para el k inferior, con k = ⌊n · fraction⌋.

    Solo entran activos con score finito; los empates se ordenan por identificador. Sin señal (k < 1, solapamiento
    o todos los scores iguales) devuelve una serie vacía.
    """
    if not 0 < fraction <= .5:
        raise ValueError("fraction debe estar en (0, 0,5]")
    eligible = month_data.loc[np.isfinite(month_data[score]), ["asset", score]].sort_values([score, "asset"])
    k = int(len(eligible) * fraction)
    if k < 1 or 2 * k > len(eligible) or eligible[score].nunique() < 2:
        return pd.Series(dtype=float)
    weights = pd.Series(0., index=eligible.asset)
    weights.loc[eligible.asset.iloc[:k]] = -1 / k
    weights.loc[eligible.asset.iloc[-k:]] = 1 / k
    return weights


def build_factor(data: pd.DataFrame, score: str, cost_bps: float = 15, fraction: float = .30) -> pd.DataFrame:
    """Retorno mensual del factor: F_t = Σ w_i r_i; coste = c · Σ|w_t − w_{t−1}| (incluye la apertura inicial).

    Si falta el retorno de una posición elegida, el mes es desconocido (NaN), no cero.
    """
    if cost_bps < 0:
        raise ValueError("Coste negativo")
    prev, rows = pd.Series(dtype=float), []
    for month, g in data.groupby("month", sort=True):
        weights = long_short_weights(g, score, fraction)
        union = prev.index.union(weights.index)
        turnover = (weights.reindex(union, fill_value=0) - prev.reindex(union, fill_value=0)).abs().sum()
        selected = weights[weights.ne(0)]
        realized = g.set_index("asset").asset_return.reindex(selected.index)
        gross = float(selected @ realized) if len(selected) and realized.notna().all() else np.nan
        cost = turnover * cost_bps / 1e4
        rows.append((month, gross, cost, gross - cost, turnover, len(selected)))
        prev = weights
    return pd.DataFrame(rows, columns=["month", "gross", "cost", "net", "turnover", "n_assets"]).set_index("month")


def market_excess(panel: pd.DataFrame) -> pd.Series:
    """Retorno equiponderado del universo menos RF; NaN si falta algún retorno del mes."""
    market = panel.groupby("month").asset_return.agg(lambda s: s.mean() if s.notna().all() else np.nan)
    return market - panel.groupby("month").rf.first()


def factor_table(panel: pd.DataFrame, scores=SCORES, cost_bps: float = 15, fraction: float = .30):
    """(detalles por factor, retornos netos con la columna `market`, retornos brutos)."""
    details = {s: build_factor(panel, s, cost_bps, fraction) for s in scores}
    net = pd.DataFrame({s: d.net for s, d in details.items()})
    gross = pd.DataFrame({s: d.gross for s, d in details.items()})
    net["market"] = market_excess(panel)
    return details, net, gross


# --- Validación ------------------------------------------------------------------------

def summarize(s: pd.Series, lags: int = 3, min_months: int = 12) -> pd.Series:
    """n, media (bps), volatilidad anual (%), t y p HAC de la media. Sin HAC si hay huecos entre meses."""
    s = s.dropna()
    if len(s) < min_months:
        return pd.Series({"n": len(s), "mean_bps": np.nan, "vol_pct": np.nan, "t_hac": np.nan, "p_hac": np.nan})
    contiguous = (np.diff(s.index.to_period("M").asi8) == 1).all()
    fit = sm.OLS(s.to_numpy(), np.ones((len(s), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags}) if contiguous else None
    return pd.Series({"n": len(s), "mean_bps": s.mean() * 1e4, "vol_pct": s.std() * np.sqrt(12) * 100,
                      "t_hac": fit.tvalues[0] if fit else np.nan, "p_hac": fit.pvalues[0] if fit else np.nan})


def period_summary(net: pd.DataFrame, split, lags: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resumen en desarrollo (meses < split) y validación (≥ split)."""
    dev = net.loc[net.index < split].apply(summarize, lags=lags).T
    val = net.loc[net.index >= split].apply(summarize, lags=lags).T
    return dev, val


def multiple_testing(pvalues: pd.Series, alpha: float = .05) -> pd.DataFrame:
    """p-valor, Bonferroni (p · m) y Benjamini-Hochberg (FDR) con su decisión al nivel `alpha`."""
    p = pvalues.dropna()
    bonf = np.minimum(p * len(p), 1)
    bh_reject, bh = multipletests(p, alpha=alpha, method="fdr_bh")[:2]
    return pd.DataFrame({"p": p, "p_bonferroni": bonf, "rechaza_bonferroni": bonf < alpha,
                         "p_bh": bh, "rechaza_bh": bh_reject}, index=p.index)


# --- Fama-French --------------------------------------------------------------------------

def read_ff_monthly(path, columns) -> pd.DataFrame:
    """Lee solo las filas YYYYMM de un CSV oficial de Ken French y pasa de % a decimal (−99,99 = ausente)."""
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.reader(f):
            if row and re.fullmatch(r"\d{6}", row[0].strip()) and len(row) >= len(columns) + 1:
                rows.append([pd.to_datetime(row[0].strip(), format="%Y%m")] + row[1:len(columns) + 1])
    if not rows:
        raise ValueError("No hay filas mensuales YYYYMM")
    df = pd.DataFrame(rows, columns=["month"] + list(columns)).set_index("month")
    if not df.index.is_unique:
        raise ValueError("Meses duplicados en el fichero FF")
    return df.apply(pd.to_numeric, errors="raise").replace([-99.99, -999], np.nan) / 100


def download_ff(model: str, dest_dir, timeout: float = 60) -> Path:
    """Descarga y descomprime el CSV oficial mensual (`ff3` o `ff5`). Lanza el error si falla la descarga."""
    import requests

    name, _ = FF_FILES[model]
    res = requests.get(FF_URL + name, timeout=timeout)
    res.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        inner = z.namelist()[0]
        path = Path(dest_dir) / inner
        path.write_bytes(z.read(inner))
    return path


def fit_model(y: pd.Series, x: pd.DataFrame, lags: int = 3, min_months: int = 24):
    """OLS con constante y errores HAC sobre meses comunes y consecutivos."""
    d = pd.concat([y.rename("y"), x], axis=1, sort=True).dropna()
    if len(d) < min_months:
        raise ValueError(f"Se requieren al menos {min_months} meses comunes")
    if not (np.diff(d.index.to_period("M").asi8) == 1).all():
        raise ValueError("HAC requiere aquí meses consecutivos; revisar huecos")
    return sm.OLS(d.y, sm.add_constant(d[list(x.columns)], has_constant="add")).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


def model_summary(fit) -> dict:
    """Alpha mensual (bps), su p-valor, R² y n de una regresión de `fit_model`."""
    return {"alpha_bps": fit.params["const"] * 1e4, "p_alpha": fit.pvalues["const"], "r2": fit.rsquared, "n": int(fit.nobs)}


# --- Derivados ------------------------------------------------------------------------------

def derivative_pnl(spot, strike: float = 60000, premium: float = 2000, future_entry: float = 60000) -> pd.DataFrame:
    """P&L a vencimiento por 1 unidad: futuro S_T − F_0; call max(S_T − K, 0) − p; put max(K − S_T, 0) − p."""
    spot = np.asarray(spot, dtype=float)
    return pd.DataFrame({"Futuro long": spot - future_entry, "Call comprada": np.maximum(spot - strike, 0) - premium,
                         "Put comprada": np.maximum(strike - spot, 0) - premium}, index=spot)


def swap_net_flow(notional: float, floating: float, fixed: float, dt: float = 1.) -> float:
    """Flujo neto del pagador fijo: N · (r_variable − r_fijo) · Δt."""
    return notional * (floating - fixed) * dt


def annualized_basis(future: float, spot: float, days: float) -> float:
    """Basis simple anualizado: (F/S − 1) · 365 / días."""
    if spot <= 0 or days <= 0:
        raise ValueError("Spot y días deben ser positivos")
    return (future / spot - 1) * 365 / days


# --- Datos reales ------------------------------------------------------------------------------

def monthly_returns(close: pd.Series) -> pd.Series:
    """Retornos mensuales simples con el último cierre disponible de cada mes (sesiones bursátiles).

    Indexados por el primer día del mes, como los ficheros de Ken French. El primer mes queda fuera.
    """
    last = close.dropna().groupby(close.dropna().index.to_period("M")).last()
    last.index = last.index.to_timestamp()
    return last.pct_change(fill_method=None).iloc[1:]


def download_daily(tickers, start: str, end: str) -> pd.DataFrame:
    """Cierres ajustados y volúmenes diarios de Yahoo Finance (requiere yfinance). Lanza el error si no hay datos."""
    import yfinance as yf

    raw = yf.download(list(tickers), start=start, end=end, interval="1d", auto_adjust=True,
                      progress=False, threads=False)
    if raw.empty:
        raise ValueError("Yahoo Finance no devolvió datos")
    return raw

def crypto_monthly_panel(close: pd.DataFrame, volume: pd.DataFrame, rf_monthly: pd.Series,
                         min_days: int = 20) -> pd.DataFrame:
    """Panel mensual desde cierres y volúmenes diarios en USD (Yahoo, 24/7).

    - Retorno del mes m: cierre del último día natural de m / cierre del último día de m − 1 − 1. Si falta alguno
      de los dos cierres, el retorno queda NaN (no se rellena).
    - Iliquidez de Amihud conocida al empezar m: media en m − 1 de |r_d| / volumen en USD_d (por 10⁹ USD),
      exigiendo `min_days` días con dato; si no, NaN.
    - `available_at` = último día de m − 1 (las características se conocen al cierre del mes anterior).
    - RF: el mensual oficial de Ken French (USD). Solo se conservan meses con RF conocido.
    """
    close = close.sort_index()
    daily_ret = close.pct_change(fill_method=None)
    month_end = close.index.to_period("M")
    last_day = close.groupby(month_end).apply(lambda g: g.iloc[-1] if g.index[-1].day == g.index[-1].days_in_month
                                              else g.iloc[-1] * np.nan)
    last_day.index = last_day.index.to_timestamp()
    monthly_ret = last_day.pct_change(fill_method=None)
    amihud = (daily_ret.abs() / volume.where(volume > 0)).groupby(month_end)
    illiq = amihud.mean().where(amihud.count() >= min_days) * 1e9
    illiq.index = illiq.index.to_timestamp()
    illiq = illiq.shift(1)  # conocida al cierre del mes anterior
    panel = (monthly_ret.stack(future_stack=True).rename("asset_return").to_frame()
             .join(illiq.stack(future_stack=True).rename("illiquidity")))
    panel = panel.rename_axis(["month", "asset"]).reset_index()
    first_close = close.apply(lambda s: s.first_valid_index())
    panel = panel[panel.month > panel.asset.map(first_close)]  # el activo ya cotizaba al decidir
    panel["available_at"] = panel.month - pd.Timedelta(days=1)
    panel["rf"] = panel.month.map(rf_monthly)
    panel = panel.dropna(subset=["rf"])
    return panel[["month", "asset", "available_at", "illiquidity", "asset_return", "rf"]].reset_index(drop=True)


# --- Ejercicios -------------------------------------------------------------------------------

def manual_long_short(scores: dict, returns: dict, fraction: float = .30) -> dict:
    """E1 · Pesos long-short sin `long_short_weights`: ordenar, k = ⌊n · fraction⌋, ±1/k en los extremos."""
    ordered = sorted(scores, key=lambda a: (scores[a], a))
    k = int(len(ordered) * fraction)
    weights = {a: 0. for a in ordered}
    for a in ordered[:k]:
        weights[a] = -1 / k
    for a in ordered[len(ordered) - k:]:
        weights[a] = 1 / k
    factor = sum(weights[a] * returns[a] for a in ordered)
    return {"k": k, "weights": weights, "net": sum(weights.values()), "gross": sum(abs(w) for w in weights.values()),
            "factor_return": factor}


def momentum_12_2(returns: pd.Series, month) -> float:
    """E2 · Momentum 12-2 del mes `month`: ∏(1 + r) − 1 con los 11 retornos de t−12 a t−2 (calendario completo)."""
    month = pd.Timestamp(month)
    window = pd.date_range(month - pd.DateOffset(months=12), month - pd.DateOffset(months=2), freq="MS")
    values = returns.reindex(window)
    return float(np.prod(1 + values.to_numpy()) - 1) if values.notna().all() else np.nan


def quantile_comparison(panel: pd.DataFrame, split, scores=("value", "size"), fractions=(1 / 3, .2),
                        cost_bps: float = 15) -> pd.DataFrame:
    """E3 · Media bruta, neta y rotación por factor y cuantil, solo en desarrollo (meses < split)."""
    dev = panel[panel.month < split]
    rows = []
    for score in scores:
        for fraction in fractions:
            d = build_factor(dev, score, cost_bps, fraction)
            rows.append({"factor": score, "cuantil": fraction, "activos_por_lado": int(d.n_assets.iloc[-1] // 2),
                         "bruto_bps": d.gross.mean() * 1e4, "neto_bps": d.net.mean() * 1e4,
                         "rotacion_media": d.turnover.mean(), "rotacion_sin_apertura": d.turnover.iloc[1:].mean()})
    return pd.DataFrame(rows).set_index(["factor", "cuantil"])


def breakeven_cost_bps(details: pd.DataFrame, split) -> float:
    """E4 · Coste por lado que anula la media neta en desarrollo: media bruta / rotación media (en bps)."""
    dev = details[details.index < split].dropna(subset=["gross"])
    return dev.gross.mean() / dev.turnover.mean() * 1e4


def spanning_alpha(net: pd.DataFrame, target: str, controls, lags: int = 3) -> dict:
    """E5 · ¿Explican otros factores a `target`? Alpha (bps), p, betas y R² de target sobre controls."""
    fit = fit_model(net[target], net[list(controls)], lags)
    return {**model_summary(fit), **{f"beta_{c}": fit.params[c] for c in controls}}


def perp_carry_score(funding: pd.DataFrame, formation_time, lookback: int = 21) -> dict:
    """E6 · Carry de un perpetuo para el lado largo con funding CONOCIDO en la fecha de formación.

    `funding` tiene columnas `funding_time` (UTC), `rate` (decimal por periodo) y `kind` ('observado' si ya se
    liquidó, 'estimado' si es el próximo funding anunciado). Solo cuentan los observados con
    `funding_time < formation_time`. Carry largo = −media del funding observado (los largos pagan si es positivo),
    anualizado con 3 liquidaciones diarias. El estimado se informa aparte y no entra en el score.
    """
    f = funding.copy()
    f["funding_time"] = pd.to_datetime(f.funding_time, utc=True)
    formation = pd.Timestamp(formation_time).tz_convert("UTC") if pd.Timestamp(formation_time).tzinfo \
        else pd.Timestamp(formation_time, tz="UTC")
    known = f[(f.kind == "observado") & (f.funding_time < formation)].sort_values("funding_time").tail(lookback)
    if len(known) < lookback:
        raise ValueError(f"Solo {len(known)} fundings observados antes de la formación; se necesitan {lookback}")
    estimated = f[(f.kind == "estimado") & (f.funding_time >= formation)]
    return {"n_observados": len(known), "funding_medio": known.rate.mean(), "carry_largo_anual": -known.rate.mean() * 3 * 365,
            "ultimo_observado": known.funding_time.iloc[-1],
            "estimado_siguiente": estimated.rate.iloc[0] if len(estimated) else np.nan}
