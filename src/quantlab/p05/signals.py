"""Momentum y mean reversion: indicadores, objetivo con entrada retrasada, separación temporal,
capacidad predictiva (IC) y simulación long/cash con costes.

Origen: P05 · Momentum y Mean Reversion. Concepto: docs/conceptos/momentum_y_reversion.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import requests

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
SIGNALS = ("momentum_signal", "reversion_signal")
RULES = ("momentum", "mean_reversion", "periodic_long")
SYNTHETIC_REGIME_CHANGE = 900  # índice desde el que la autocorrelación pasa de +0,35 a −0,35


# --- Datos ------------------------------------------------------------------

def synthetic_prices(window: str = "1min") -> tuple[pd.Series, dict]:
    """1.800 cierres ficticios (semilla 42): AR(1) de retornos con φ = +0,35 y luego −0,35, y un hueco de 3 velas."""
    rng = np.random.default_rng(42)
    count = 1800
    innovations = rng.normal(0, .0009, count)
    returns = np.zeros(count)
    for i in range(1, count):
        phi = .35 if i < SYNTHETIC_REGIME_CHANGE else -.35
        returns[i] = phi * returns[i - 1] + innovations[i]
    idx = pd.date_range("2026-01-01T10:01:00Z", periods=count, freq=window)
    close = pd.Series(60000 * np.exp(np.cumsum(returns)), index=idx, name="close")
    close.iloc[450:453] = np.nan
    return close, {"source": "synthetic_seed_42", "symbol": "BTC/EUR ficticio"}


def fetch_kraken_ohlc(pair: str = "XBTEUR", interval_min: int = 1, window: str = "1min",
                      timeout: float = 20) -> tuple[pd.Series, dict]:
    """Cierres del endpoint público OHLC de Kraken (hasta 720 velas), indexados por el fin de la vela.

    Descarta la última vela, todavía abierta. Si la API falla lanza la excepción.
    """
    if pd.Timedelta(window) != pd.Timedelta(minutes=interval_min):
        raise ValueError("WINDOW e INTERVAL_MIN deben coincidir")
    response = requests.get(KRAKEN_OHLC_URL, params={"pair": pair, "interval": interval_min}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    result = payload["result"]
    keys = [k for k in result if k != "last"]
    if len(keys) != 1:
        raise ValueError("Respuesta inesperada")
    df = pd.DataFrame(result[keys[0]][:-1], columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    idx = pd.to_datetime(df.time, unit="s", utc=True) + pd.Timedelta(window)
    close = pd.Series(pd.to_numeric(df.close).to_numpy(), index=idx, name="close")
    return close, {"source": KRAKEN_OHLC_URL, "symbol": "BTC/EUR", "pair": keys[0],
                   "received_at": pd.Timestamp.now(tz="UTC").isoformat()}


def load_p04_series(path) -> tuple[pd.Series, dict]:
    """Lee `analysis_close` del `*_series.csv` exportado en P04 (ya excluye fronteras y velas vacías)."""
    df = pd.read_csv(path)
    if not {"bar_end_utc", "analysis_close"}.issubset(df.columns):
        raise ValueError("Usa el CSV series de P04 con bar_end_utc y analysis_close")
    close = pd.Series(pd.to_numeric(df.analysis_close, errors="raise").to_numpy(),
                      index=pd.to_datetime(df.bar_end_utc, utc=True, format="mixed"), name="close")
    return close, {"source": str(path), "symbol": "verificar metadatos P04"}


def regularize(close: pd.Series, window: str) -> pd.Series:
    """Ordena y pasa a frecuencia fija sin rellenar huecos (quedan como NaN).

    Lanza ValueError si el índice está vacío, duplicado o tiene NaT, si algún timestamp no encaja
    en la rejilla de `window` o si hay precios <= 0 o no finitos.
    """
    close = close.sort_index()
    delta = pd.Timedelta(window)
    if close.empty or close.index.has_duplicates or close.index.hasnans or delta <= pd.Timedelta(0):
        raise ValueError("Índice vacío, duplicado o inválido")
    if ((close.index - close.index[0]) % delta != pd.Timedelta(0)).any():
        raise ValueError("Timestamps incompatibles con WINDOW")
    if not np.isfinite(close.dropna()).all() or (close.dropna() <= 0).any():
        raise ValueError("Precios no válidos")
    close = close.asfreq(window)
    close.index.name = "bar_end_utc"
    return close


# --- Indicadores y objetivo ---------------------------------------------------

def build_features(close: pd.Series, n: int = 20) -> pd.DataFrame:
    """Momentum, SMA, desviación típica, EMA (reiniciada tras huecos), desviación y z-score.

    Solo usa datos hasta el cierre actual. `reversion_signal` = −z_score, para que las dos señales
    esperen retornos positivos cuando su valor aumenta.
    """
    if n < 2:
        raise ValueError("n >= 2")
    out = close.to_frame("close")
    roll = close.rolling(n, min_periods=n)
    full = close.rolling(n + 1, min_periods=n + 1).count().eq(n + 1)
    out["momentum"] = (close / close.shift(n) - 1).where(full)
    out["sma"] = roll.mean()
    out["rolling_std"] = roll.std(ddof=1)
    segment = close.isna().cumsum()
    out["ema"] = close.groupby(segment).transform(
        lambda x: x.ewm(span=n, adjust=False, min_periods=n).mean()).where(close.notna())
    out["price_deviation"] = close - out.sma
    out["z_score"] = out.price_deviation / out.rolling_std.replace(0, np.nan)
    out["momentum_signal"] = out.momentum
    out["reversion_signal"] = -out.z_score  # z negativo => expectativa alcista hipotética
    return out


def add_target(df: pd.DataFrame, h: int = 5) -> pd.DataFrame:
    """Objetivo con entrada retrasada una vela: y_t = P_{t+1+h} / P_{t+1} − 1.

    Solo se define si todas las velas de t a t+1+h tienen precio. Son precios de referencia,
    no ejecuciones garantizadas; `entry_*`, `exit_*` y `forward_return` nunca son predictores.
    """
    if h < 1:
        raise ValueError("h >= 1")
    out = df.copy()
    p = out.close
    complete = pd.concat([p.shift(-k).notna() for k in range(h + 2)], axis=1).all(axis=1)
    ts = pd.Series(out.index, index=out.index)
    out["entry_time"] = ts.shift(-1).where(complete)
    out["exit_time"] = ts.shift(-(h + 1)).where(complete)
    out["entry_price"] = p.shift(-1).where(complete)
    out["exit_price"] = p.shift(-(h + 1)).where(complete)
    out["forward_return"] = out.exit_price / out.entry_price - 1
    return out


def split_train_test(dataset: pd.DataFrame, train_fraction: float = .65,
                     required=SIGNALS + ("forward_return",)) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Separación cronológica. Elimina del desarrollo las filas cuya salida toca o cruza la frontera."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction debe estar entre 0 y 1")
    split_time = dataset.index[int(len(dataset) * train_fraction)]
    eligible = dataset.dropna(subset=list(required)).copy()
    train = eligible[(eligible.index < split_time) & (eligible.exit_time < split_time)].copy()
    test = eligible[eligible.index >= split_time].copy()
    return train, test, split_time


# --- Diagnóstico y simulación ---------------------------------------------------

def information_table(train: pd.DataFrame, test: pd.DataFrame, signals=SIGNALS) -> pd.DataFrame:
    """IC de Pearson y Spearman, y retorno medio de los extremos (quintiles fijados en desarrollo)."""
    rows = []
    for sig in signals:
        qlo, qhi = train[sig].quantile([.2, .8]).tolist()
        for period, frame in [("desarrollo", train), ("validación", test)]:
            lo = frame[frame[sig] <= qlo].forward_return
            hi = frame[frame[sig] >= qhi].forward_return
            rows.append({"signal": sig, "period": period, "n": len(frame),
                         "ic_pearson": frame[sig].corr(frame.forward_return),
                         "ic_spearman": frame[sig].corr(frame.forward_return, method="spearman"),
                         "baseline_bps": frame.forward_return.mean() * 1e4,
                         "low_mean_bps": lo.mean() * 1e4, "high_mean_bps": hi.mean() * 1e4,
                         "high_minus_low_bps": (hi.mean() - lo.mean()) * 1e4,
                         "n_low": len(lo), "n_high": len(hi)})
    return pd.DataFrame(rows)


def simulate(frame: pd.DataFrame, rule: str, cost_bps: float, z_threshold: float = 1.5) -> pd.DataFrame:
    """Operaciones long/cash sin solapamiento: la siguiente entrada debe ser posterior a la salida anterior.

    Reglas: `momentum` (momentum > 0), `mean_reversion` (z_score < −z_threshold) y `periodic_long`
    (cualquier fila elegible). net_return = gross_return − cost_bps / 10.000 (aproximación).
    """
    masks = {"momentum": lambda: frame.momentum > 0,
             "mean_reversion": lambda: frame.z_score < -z_threshold,
             "periodic_long": lambda: pd.Series(True, index=frame.index)}
    if rule not in masks:
        raise ValueError(f"Regla desconocida: {rule}")
    mask = masks[rule]()
    selected = []
    last_exit = None
    for signal_time, row in frame.loc[mask].iterrows():
        if last_exit is not None and row.entry_time <= last_exit:
            continue
        selected.append({"signal_time": signal_time, "entry_time": row.entry_time, "exit_time": row.exit_time,
                         "gross_return": row.forward_return, "net_return": row.forward_return - cost_bps / 10000})
        last_exit = row.exit_time
    out = pd.DataFrame(selected, columns=["signal_time", "entry_time", "exit_time", "gross_return", "net_return"])
    if not out.empty:
        assert (out.net_return > -1).all(), "Retorno fuera del modelo long/cash"
        out["equity"] = (1 + out.net_return).cumprod()
        assert (out.entry_time.iloc[1:].reset_index(drop=True) > out.exit_time.iloc[:-1].reset_index(drop=True)).all()
    else:
        out["equity"] = pd.Series(dtype=float)
    return out


def strategy_table(periods: dict, cost_bps: float, z_threshold: float = 1.5, rules=RULES) -> tuple[pd.DataFrame, dict]:
    """Resultados por periodo y regla. `periods` = {'desarrollo': train, 'validación': test}."""
    results, logs = [], {}
    for period, frame in periods.items():
        for rule in rules:
            trades = simulate(frame, rule, cost_bps, z_threshold)
            logs[(period, rule)] = trades
            results.append({"period": period, "rule": rule, "trades": len(trades),
                            "gross_mean_bps": trades.gross_return.mean() * 1e4,
                            "net_mean_bps": trades.net_return.mean() * 1e4,
                            "win_rate_pct": 100 * (trades.net_return > 0).mean(),
                            "total_net_pct": 100 * ((trades.equity.iloc[-1] if len(trades) else 1) - 1)})
    return pd.DataFrame(results), logs


def cost_sensitivity(frame: pd.DataFrame, costs=(0, 10, 20, 40), z_threshold: float = 1.5, rules=RULES) -> pd.DataFrame:
    """Retorno neto medio por operación con distintos costes, sin cambiar la regla."""
    rows = []
    for rule in rules:
        for cost in costs:
            tr = simulate(frame, rule, cost, z_threshold)
            rows.append({"rule": rule, "cost_bps": cost, "trades": len(tr), "mean_net_bps": tr.net_return.mean() * 1e4})
    return pd.DataFrame(rows)


# --- Ejercicios -------------------------------------------------------------

def manual_momentum(prices, n: int) -> list:
    """E1 · M_t = P_t / P_{t−n} − 1 con un bucle; las n primeras posiciones no tienen pasado suficiente (None)."""
    if n < 1:
        raise ValueError("n >= 1")
    p = [float(x) for x in prices]
    return [None if i < n else p[i] / p[i - n] - 1 for i in range(len(p))]


def manual_zscore(prices) -> dict:
    """E2 · SMA, desviación típica muestral (n − 1), desviación del último precio y z-score."""
    p = np.asarray(prices, dtype=float)
    if len(p) < 2:
        raise ValueError("Se necesitan al menos 2 precios")
    sma = p.sum() / len(p)
    std = np.sqrt(((p - sma) ** 2).sum() / (len(p) - 1))
    deviation = p[-1] - sma
    return {"sma": sma, "std": std, "deviation": deviation, "z_score": deviation / std if std else np.nan}


def development_grid(close: pd.Series, lookbacks=(5, 20, 60), horizons=(1, 5, 10),
                     train_fraction: float = .65) -> pd.DataFrame:
    """E4 · IC de las dos señales para cada (N, h), calculado SOLO en el periodo de desarrollo."""
    rows = []
    for n in lookbacks:
        features = build_features(close, n)
        for h in horizons:
            train, _, _ = split_train_test(add_target(features, h), train_fraction)
            rows.append({"lookback": n, "horizon": h, "n_train": len(train),
                         "ic_momentum": train.momentum_signal.corr(train.forward_return),
                         "ic_reversion": train.reversion_signal.corr(train.forward_return)})
    return pd.DataFrame(rows)


def breakeven_costs(logs: dict, periods: dict) -> pd.DataFrame:
    """E5 · Coste de equilibrio por operación y exposición de cada estrategia.

    Con la aproximación net = gross − coste, el coste de equilibrio es el retorno bruto medio (bps).
    `exposure_pct` = tiempo invertido (Σ salida − entrada) / duración del periodo.
    """
    rows = []
    for (period, rule), trades in logs.items():
        frame = periods[period]
        span = frame.index.max() - frame.index.min()
        invested = (trades.exit_time - trades.entry_time).sum() if len(trades) else pd.Timedelta(0)
        gross = trades.gross_return.mean() * 1e4 if len(trades) else np.nan
        rows.append({"period": period, "rule": rule, "trades": len(trades),
                     "gross_mean_bps": gross, "breakeven_cost_bps": gross,
                     "gross_total_pct": 100 * ((1 + trades.gross_return).prod() - 1) if len(trades) else 0.0,
                     "exposure_pct": 100 * invested / span if span > pd.Timedelta(0) else np.nan})
    return pd.DataFrame(rows)
