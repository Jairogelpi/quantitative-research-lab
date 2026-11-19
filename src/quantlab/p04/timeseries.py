"""Series temporales a partir de trades: velas OHLCV, retornos, volatilidad y retorno futuro.

Origen: P04 · Motor de series temporales financieras. Concepto: docs/conceptos/series_temporales.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.p03.trades import fetch_recent_trades

SYNTHETIC_START = pd.Timestamp("2026-01-01T10:00:00Z")
# Tramo de la simulación con volatilidad 4 veces mayor (segundos desde SYNTHETIC_START).
SYNTHETIC_HIGH_VOL_S = (2880, 3900)
# Tramo de la simulación sin eventos (segundos desde SYNTHETIC_START).
SYNTHETIC_GAP_S = (1800, 1920)


def validate_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Valida y ordena trades con columnas timestamp (UTC), price y quantity.

    Lanza ValueError si faltan columnas, no hay filas, hay precios o cantidades <= 0
    o no finitos, timestamps vacíos o `trade_id` duplicados. No elimina trades con el
    mismo precio o timestamp: pueden ser ejecuciones distintas.
    """
    df = df.copy()
    required = {"timestamp", "price", "quantity"}
    if not required.issubset(df.columns) or df.empty:
        raise ValueError("Faltan columnas o no hay trades")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise", format="mixed")
    for col in ["price", "quantity"]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    if (df.timestamp.isna().any() or not np.isfinite(df[["price", "quantity"]]).all().all()
            or (df[["price", "quantity"]] <= 0).any().any()):
        raise ValueError("Datos financieros inválidos")
    if "trade_id" in df and df.trade_id.dropna().duplicated().any():
        raise ValueError("IDs duplicados; revisa la procedencia")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def fetch_trades(pair: str = "XBTEUR", symbol: str = "BTC/EUR", count: int = 1000) -> tuple[pd.DataFrame, dict]:
    """Trades recientes de Kraken (reutiliza `quantlab.p03.trades.fetch_recent_trades`).

    Si la API falla lanza la excepción: nunca se sustituye por datos ficticios.
    """
    raw, provenance = fetch_recent_trades(pair, count, symbol)
    df = raw[["timestamp", "price", "quantity", "side", "trade_id"]]
    return validate_trades(df), {"mode": "live", "source": provenance["source"], "symbol": symbol,
                                 "exchange_pair": provenance["exchange_pair"],
                                 "received_at": provenance["received_at"], "cursor": provenance["cursor"]}


def load_trades_csv(path, symbol: str = "BTC/EUR") -> tuple[pd.DataFrame, dict]:
    """Lee el `*_trades.csv` exportado en P03 (no el `*_windows.csv`)."""
    trades = validate_trades(pd.read_csv(path, dtype={"trade_id": "string"}))
    return trades, {"mode": "csv", "source": str(path), "symbol": symbol,
                    "note": "mercado declarado por el usuario"}


def synthetic_trades(symbol: str = "BTC/EUR") -> tuple[pd.DataFrame, dict]:
    """Trades ficticios reproducibles (semilla 42), con un hueco de 2 minutos y un tramo de alta volatilidad."""
    rng = np.random.default_rng(42)
    seconds = np.sort(rng.choice(np.arange(1, 5400), size=1800, replace=False))
    # Dos minutos sin eventos: permiten practicar el tratamiento de huecos.
    seconds = seconds[~((seconds >= SYNTHETIC_GAP_S[0]) & (seconds < SYNTHETIC_GAP_S[1]))]
    scale = np.where((seconds >= SYNTHETIC_HIGH_VOL_S[0]) & (seconds < SYNTHETIC_HIGH_VOL_S[1]), 8., 2.)
    price = np.round(60000 + np.cumsum(rng.normal(.02, scale)), 2)
    df = pd.DataFrame({"timestamp": SYNTHETIC_START + pd.to_timedelta(seconds, unit="s"),
                       "price": price, "quantity": rng.uniform(.001, .15, len(seconds)).round(5),
                       "trade_id": np.arange(1, len(seconds) + 1)})
    return validate_trades(df), {"mode": "synthetic", "source": "seed_42", "symbol": symbol}


def build_ohlcv(df: pd.DataFrame, window: str = "1min") -> pd.DataFrame:
    """Velas [t − Δ, t) etiquetadas con su cierre (`bar_end_utc`).

    Una vela sin trades tiene OHLC = NaN y volumen 0 (`is_empty`). La primera y la última
    se marcan como frontera (`boundary_window`): pueden estar incompletas.
    """
    data = validate_trades(df).set_index("timestamp")
    # Solo frecuencias fijas, no meses ni periodos de calendario variables.
    if pd.Timedelta(window) <= pd.Timedelta(0):
        raise ValueError("Ventana no positiva")
    data["notional"] = data.price * data.quantity
    out = data.resample(window, label="right", closed="left", origin="epoch").agg(
        open=("price", "first"), high=("price", "max"), low=("price", "min"),
        close=("price", "last"), volume=("quantity", "sum"),
        notional_volume=("notional", "sum"), trade_count=("price", "count"))
    out.index.name = "bar_end_utc"
    out["is_empty"] = out.trade_count.eq(0)
    out["boundary_window"] = False
    out.loc[out.index[[0, -1]], "boundary_window"] = True
    out["price_range"] = out.high - out.low
    out["vwap"] = out.notional_volume / out.volume.replace(0, np.nan)
    return out


def add_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Retornos simple, logarítmico y acumulado por segmento.

    Excluye los cierres de velas vacías y de frontera (`analysis_close` = NaN), no rellena
    huecos y reinicia el acumulado en cada segmento de cierres válidos consecutivos.
    """
    out = df.copy()
    close = out.close.mask(out.is_empty | out.boundary_window)
    out["analysis_close"] = close
    out["simple_return"] = close / close.shift(1) - 1
    out["log_return"] = np.log(close / close.shift(1))
    segment = close.isna().cumsum()
    out["segment_id"] = segment.where(close.notna()).astype("Int64")
    first = close.groupby(segment).transform("first")
    out["cumulative_return"] = close / first - 1
    return out


def add_volatility(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Volatilidad móvil (desv. típica muestral) y realizada (√Σℓ²) de los últimos `n` retornos log.

    Exige `n` retornos consecutivos válidos; si falta uno, el resultado queda vacío. No anualiza.
    """
    if not isinstance(n, int) or n < 2:
        raise ValueError("n debe ser entero >= 2")
    out = df.copy()
    out["rolling_volatility"] = out.log_return.rolling(n, min_periods=n).std(ddof=1)
    out["realized_volatility"] = np.sqrt(out.log_return.pow(2).rolling(n, min_periods=n).sum())
    return out


def add_target(df: pd.DataFrame, h: int = 3) -> pd.DataFrame:
    """Retorno futuro close-to-close a `h` intervalos: y_t = P_{t+h} / P_t − 1.

    Solo se define si los `h` cierres siguientes están en el mismo segmento válido (no cruza
    huecos ni fronteras). Es una etiqueta de investigación, no una feature ni un P&L ejecutable.
    """
    if not isinstance(h, int) or h < 1:
        raise ValueError("h debe ser entero positivo")
    out = df.copy()
    close = out.analysis_close
    same_segment = out.segment_id.eq(out.segment_id.shift(-h)).fillna(False).astype(bool)
    out["forward_return"] = (close.shift(-h) / close - 1).where(same_segment)
    out["target_end_utc"] = pd.Series(out.index, index=out.index).shift(-h).where(out.forward_return.notna())
    return out


def compare_frequencies(trades: pd.DataFrame, frequencies=("5s", "15s", "1min", "5min")) -> pd.DataFrame:
    """Velas, huecos, volumen total, retornos válidos y desviación típica por frecuencia."""
    rows = []
    for frequency in frequencies:
        b = build_ohlcv(trades, frequency)
        r = add_returns(b)
        rows.append({"frequency": frequency, "bars": len(b), "empty_bars": int(b.is_empty.sum()),
                     "total_volume_btc": b.volume.sum(), "valid_returns": int(r.log_return.count()),
                     "std_bps_per_bar": r.log_return.std() * 10000})
    return pd.DataFrame(rows)


# --- Ejercicios -------------------------------------------------------------

def manual_ohlcv(group: pd.DataFrame) -> pd.Series:
    """E1 · Apertura, máximo, mínimo, cierre y volumen de un grupo de trades, sin `build_ohlcv`.

    Respeta el orden temporal (estable en empates). Un grupo vacío devuelve OHLC = NaN y volumen 0.
    """
    if group.empty:
        return pd.Series({"open": np.nan, "high": np.nan, "low": np.nan, "close": np.nan, "volume": 0.0})
    g = group.sort_values("timestamp", kind="stable")
    prices = g["price"].to_numpy(dtype=float)
    return pd.Series({"open": prices[0], "high": prices.max(), "low": prices.min(),
                      "close": prices[-1], "volume": float(g["quantity"].sum())})


def return_decomposition(prices) -> pd.DataFrame:
    """E2 · Retornos simples y log de una serie de precios, con sus agregados.

    Devuelve una fila por retorno y los totales en `attrs`: suma de simples, compuesto
    (∏(1 + r) − 1) y suma de logarítmicos.
    """
    p = pd.Series(prices, dtype=float)
    simple = (p / p.shift(1) - 1).dropna()
    log = np.log(p / p.shift(1)).dropna()
    out = pd.DataFrame({"price_from": p.shift(1).dropna().to_numpy(), "price_to": p.iloc[1:].to_numpy(),
                        "simple_return": simple.to_numpy(), "log_return": log.to_numpy()})
    out.attrs = {"sum_simple": float(simple.sum()),
                 "compounded": float(np.prod(1 + simple) - 1),
                 "sum_log": float(log.sum())}
    return out


def volatility_reaction(series: pd.DataFrame, regime_start, windows=(5, 10, 20), factor: float = 2.0) -> pd.DataFrame:
    """E3 · Cuándo reacciona cada ventana de volatilidad a un cambio de régimen.

    La referencia es la mediana de la volatilidad móvil antes de `regime_start`. La reacción es la
    primera vela, desde `regime_start`, en que la volatilidad supera `factor` veces esa referencia.
    """
    regime_start = pd.Timestamp(regime_start)
    rows = {}
    for n in windows:
        vol = add_volatility(series, n)["rolling_volatility"]
        baseline = vol.loc[vol.index < regime_start].median()
        after = vol.loc[vol.index >= regime_start]
        hit = after.index[after > factor * baseline]
        first = hit[0] if len(hit) else pd.NaT
        rows[n] = {"baseline_bps": baseline * 10_000,
                   "first_alert_utc": first,
                   "bars_after_start": (int(series.index.get_loc(first) - series.index.searchsorted(regime_start))
                                        if len(hit) else np.nan),
                   "max_bps": vol.max() * 10_000,
                   "valid_values": int(vol.count())}
    return pd.DataFrame(rows).T.rename_axis("n_returns")


def forward_fill_comparison(bars: pd.DataFrame) -> pd.DataFrame:
    """E4 · Compara los retornos válidos sin imputar frente a rellenar huecos con el último cierre.

    La imputación es un supuesto de análisis, no un hecho de mercado: crea retornos exactamente
    cero en los huecos y un retorno a la salida que en realidad abarca varios intervalos.
    """
    honest = add_returns(bars)
    filled_close = bars.close.ffill().mask(bars.boundary_window)
    filled_return = np.log(filled_close / filled_close.shift(1))
    gap_or_after = bars.is_empty | bars.is_empty.shift(1, fill_value=False)
    rows = {
        "Sin imputar": {"valid_returns": int(honest.log_return.count()),
                        "zero_returns": int((honest.log_return == 0).sum()),
                        "std_bps": honest.log_return.std() * 10_000},
        "Último cierre (ffill)": {"valid_returns": int(filled_return.count()),
                                  "zero_returns": int((filled_return == 0).sum()),
                                  "std_bps": filled_return.std() * 10_000},
    }
    out = pd.DataFrame(rows).T
    out.attrs = {"imputed_returns": int(filled_return[gap_or_after].count())}
    return out


def target_alignment(series: pd.DataFrame, horizons=(1, 3, 5)) -> pd.DataFrame:
    """E5 · Para cada horizonte: objetivos conocidos y comprobaciones de alineación temporal.

    `all_after_observation`: la fecha objetivo es siempre posterior a la de observación.
    `exact_horizon`: la distancia es exactamente h intervalos (no cruza huecos con saltos).
    `no_gap_crossed`: todos los cierres intermedios son válidos.
    """
    step = series.index.to_series().diff().min()
    rows = {}
    for h in horizons:
        t = add_target(series, h)
        known = t.loc[t.forward_return.notna()]
        crossed = pd.concat([t.analysis_close.shift(-k) for k in range(1, h + 1)], axis=1).isna().any(axis=1)
        rows[h] = {"known_targets": len(known),
                   "all_after_observation": bool((known.target_end_utc > known.index).all()),
                   "exact_horizon": bool(((known.target_end_utc - known.index) == h * step).all()),
                   "no_gap_crossed": bool(not crossed.loc[known.index].any()),
                   "unknown_tail": int(t.forward_return.tail(h).isna().sum())}
    return pd.DataFrame(rows).T.rename_axis("h")
