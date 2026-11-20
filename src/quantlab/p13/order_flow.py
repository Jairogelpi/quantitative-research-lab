"""Order flow: reconstrucción de un libro L2 con actualizaciones absolutas, OFI de primer nivel (Cont, Kukanov
y Stoikov), OBI, regresiones contemporánea y predictiva, respuesta del precio a trades y exposición.

Origen: P13 · Order Flow, Market Impact y exposición. Concepto: docs/conceptos/order_flow_e_impacto.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

QUOTE_COLS = ["bid", "ask", "bid_size", "ask_size"]


# --- Libro L2 ----------------------------------------------------------------------

def replay(snapshot: dict, updates) -> pd.DataFrame:
    """Aplica actualizaciones absolutas (size = cantidad total del nivel; 0 lo elimina) sobre un snapshot.

    Registra el mejor nivel y la profundidad total de cada lado tras cada mensaje. Lanza ValueError ante
    una secuencia perdida (hay que resincronizar), un lado o cantidad inválidos o un libro cruzado.
    """
    book = {k: dict(v) for k, v in snapshot.items()}
    rows = []

    def record(seq, label):
        b, a = max(book["bid"]), min(book["ask"])
        if b >= a:
            raise ValueError("Libro cruzado")
        rows.append(dict(seq=seq, event=label, bid=b, ask=a, bid_size=book["bid"][b], ask_size=book["ask"][a],
                         bid_depth=sum(book["bid"].values()), ask_depth=sum(book["ask"].values())))
    record(0, "snapshot")
    for expected, u in enumerate(updates, 1):
        seq, side, price, size, label = u
        if seq != expected:
            raise ValueError("Secuencia perdida: resincronizar")
        if side not in book or size < 0 or price <= 0:
            raise ValueError("Actualización inválida")
        if size == 0:
            book[side].pop(price, None)
        else:
            book[side][price] = size
        record(seq, label)
    return pd.DataFrame(rows)


def features(d: pd.DataFrame) -> pd.DataFrame:
    """Mid, OBI de primer nivel, contribución OFI de cada cambio y cambio del mid en bps.

    e_t = 1{b_t ≥ b_{t−1}}·q^b_t − 1{b_t ≤ b_{t−1}}·q^b_{t−1} − 1{a_t ≤ a_{t−1}}·q^a_t + 1{a_t ≥ a_{t−1}}·q^a_{t−1}
    """
    x = d.copy()
    b, a = x.bid, x.ask
    qb, qa = x.bid_size, x.ask_size
    x["mid"] = (b + a) / 2
    x["obi"] = (qb - qa) / (qb + qa)
    x["ofi_event"] = (b.ge(b.shift()) * qb - b.le(b.shift()) * qb.shift()
                      - a.le(a.shift()) * qa + a.ge(a.shift()) * qa.shift())
    x.loc[x.index[0], "ofi_event"] = np.nan
    x["mid_change_bps"] = 10000 * (x.mid / x.mid.shift() - 1)
    return x


# --- Cotizaciones ------------------------------------------------------------------

def simulate_quotes(n: int = 2400, seed: int = 73, exchange: str = "kraken", symbol: str = "BTC/EUR") -> pd.DataFrame:
    """Una cotización por segundo; el mid tiene una persistencia artificial de un paso (MA(1) con 0,2).

    Los tamaños son aleatorios e independientes del precio.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0, 2, n)
    mid = 60000 + np.cumsum(shocks + .2 * np.r_[0, shocks[:-1]])
    spread = rng.choice([1., 2., 3.], n)
    return pd.DataFrame({"received_at": pd.date_range("2025-01-01", periods=n, freq="s", tz="UTC"),
                         "exchange": exchange, "symbol": symbol, "bid": mid - spread / 2, "ask": mid + spread / 2,
                         "bid_size": rng.uniform(.05, 1, n), "ask_size": rng.uniform(.05, 1, n)})


def prepare_quotes(raw: pd.DataFrame, exchange: str = "kraken", symbol: str = "BTC/EUR",
                   max_gap_seconds: float = 2.0, min_quotes: int = 60) -> pd.DataFrame:
    """Filtra un único mercado, valida, ordena por recepción, calcula features y corta en segmentos.

    Un salto mayor que `max_gap_seconds` abre un segmento nuevo, y su primera fila no tiene OFI ni cambio
    de mid (no se calcula a través de un hueco). Lanza ValueError con columnas ausentes, menos de
    `min_quotes` cotizaciones, horas vacías o duplicadas, precios o tamaños ≤ 0 o libros cruzados.
    """
    required = {"received_at", "exchange", "symbol", *QUOTE_COLS}
    if not required.issubset(raw):
        raise ValueError(f"Faltan {required - set(raw)}")
    quotes = raw.loc[(raw.exchange == exchange) & (raw.symbol == symbol)].copy()
    quotes["received_at"] = pd.to_datetime(quotes.received_at, utc=True, errors="raise")
    quotes[QUOTE_COLS] = quotes[QUOTE_COLS].apply(pd.to_numeric, errors="raise")
    quotes = quotes.sort_values("received_at").reset_index(drop=True)
    if len(quotes) < min_quotes or quotes.received_at.isna().any() or quotes.received_at.duplicated().any():
        raise ValueError(f"Se requieren al menos {min_quotes} cotizaciones únicas con tiempo válido")
    if (not np.isfinite(quotes[QUOTE_COLS]).all().all() or not quotes[QUOTE_COLS].gt(0).all().all()
            or not quotes.ask.gt(quotes.bid).all()):
        raise ValueError("Precios o tamaños inválidos")
    x = features(quotes)
    x["gap_s"] = x.received_at.diff().dt.total_seconds()
    x["segment"] = (x.gap_s.isna() | x.gap_s.gt(max_gap_seconds)).cumsum()
    x.loc[x.segment.ne(x.segment.shift()), ["ofi_event", "mid_change_bps"]] = np.nan
    return x


# --- Regresiones y regla ---------------------------------------------------------------

def add_future(x: pd.DataFrame, k: int = 1, cut: int | None = None, name: str | None = None) -> pd.DataFrame:
    """Cambio del mid en bps desde t hasta t + k actualizaciones, sin cruzar segmentos ni el corte."""
    out = x.copy()
    col = name or ("future_bps" if k == 1 else f"future_{k}_bps")
    future_mid = out.groupby("segment").mid.shift(-k)
    out[col] = 10000 * (future_mid / out.mid - 1)
    if cut is not None:
        crosses = (out.index < cut) & (out.index + k >= cut)
        out.loc[crosses, col] = np.nan
    return out


def ofi_regressions(x: pd.DataFrame, cut: int, targets: dict, hac_lags: int = 5) -> pd.DataFrame:
    """OLS de cada objetivo sobre el OFI, por periodo, con errores HAC. `targets` = {etiqueta: columna}."""
    rows = []
    for label, y in targets.items():
        for period, d in [("desarrollo", x.iloc[:cut]), ("validación", x.iloc[cut:])]:
            z = d[["ofi_event", y]].dropna()
            if len(z) < 20 or z.ofi_event.nunique() < 2:
                continue
            model = sm.OLS(z[y], sm.add_constant(z.ofi_event)).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
            rows.append(dict(target=label, period=period, n=len(z), slope_bps_per_btc=model.params["ofi_event"],
                             p_value=model.pvalues["ofi_event"], r2=model.rsquared))
    return pd.DataFrame(rows, columns=["target", "period", "n", "slope_bps_per_btc", "p_value", "r2"])


def sign_rule(x: pd.DataFrame, cut: int, development_slope: float, future_col: str = "future_bps",
              cost_bps: float = 20.) -> dict:
    """Regla fuera de muestra: operar en el sentido sign(pendiente de desarrollo) · sign(OFI_t).

    El retorno es el del mid (no ejecutable); se resta un coste total hipotético por operación.
    """
    sign = np.sign(development_slope)
    test = x.iloc[cut:][["ofi_event", future_col]].dropna()
    test = test.loc[test.ofi_event.ne(0)]
    if sign == 0 or test.empty:
        return {"trades": 0, "gross_bps": np.nan, "net_bps": np.nan}
    gross = sign * np.sign(test.ofi_event) * test[future_col]
    return {"trades": len(test), "gross_bps": gross.mean(), "net_bps": gross.mean() - cost_bps,
            "hit_rate": (gross > 0).mean()}


# --- Market impact (laboratorio artificial) ------------------------------------------------

def impact_experiment(n_events: int = 600, seed: int = 83, horizons=(0, 1, 2, 5, 10, 30)) -> tuple[pd.DataFrame, np.ndarray]:
    """Respuesta firmada creada explícitamente: q · (3 + 8 · e^{−h/4}) + ruido. No son datos empíricos."""
    rng = np.random.default_rng(seed)
    qty = rng.uniform(.01, .5, n_events)
    side = rng.choice([-1, 1], n_events)
    h = np.asarray(horizons)
    response = qty[:, None] * (3 + 8 * np.exp(-h[None, :] / 4)) + rng.normal(0, .7, (n_events, len(h)))
    events = pd.DataFrame({"signed_qty": qty * side, "qty": qty,
                           **{f"response_{hh}s_bps": response[:, i] for i, hh in enumerate(h)}})
    return events, h


def exposure(positions: pd.DataFrame, equity: float) -> tuple[pd.DataFrame, dict]:
    """Nominal, PnL no realizado y exposiciones larga, corta, bruta y neta de instrumentos lineales."""
    if equity <= 0:
        raise ValueError("Equity debe ser positivo")
    d = positions.copy()
    d["notional"] = d.quantity * d.current_price
    d["unrealized_pnl"] = d.quantity * (d.current_price - d.entry_price)
    gross, net = d.notional.abs().sum(), d.notional.sum()
    return d, dict(long_exposure=d.notional.clip(lower=0).sum(), short_exposure=-d.notional.clip(upper=0).sum(),
                   gross_exposure=gross, net_exposure=net, gross_leverage=gross / equity, net_exposure_ratio=net / equity)


# --- Ejercicios -------------------------------------------------------------------------------

def manual_ofi(previous: dict, current: dict) -> float:
    """E2 · Contribución OFI entre dos estados consecutivos del mejor nivel, sin vectorizar."""
    e = 0.0
    if current["bid"] >= previous["bid"]:
        e += current["bid_size"]
    if current["bid"] <= previous["bid"]:
        e -= previous["bid_size"]
    if current["ask"] <= previous["ask"]:
        e -= current["ask_size"]
    if current["ask"] >= previous["ask"]:
        e += previous["ask_size"]
    return e


def manual_ofi_series(d: pd.DataFrame) -> pd.Series:
    """E2 · `manual_ofi` fila a fila; la primera fila no tiene estado anterior (NaN)."""
    rows = d[QUOTE_COLS].to_dict("records")
    return pd.Series([np.nan] + [manual_ofi(p, c) for p, c in zip(rows[:-1], rows[1:])], index=d.index)


def window_ofi(x: pd.DataFrame, window: str = "5s") -> pd.DataFrame:
    """E3 · OFI sumado en ventanas [inicio, fin) por segmento, y cambio del mid entre extremos.

    Solo se conservan ventanas completas (una cotización por segundo y todas con OFI). Ambas variables
    se conocen al cierre de la ventana.
    """
    seconds = pd.Timedelta(window).total_seconds()
    rows = []
    for _, seg in x.groupby("segment"):
        s = seg.set_index("received_at")
        g = s.resample(window, label="right", closed="left")
        agg = g.agg(ofi=("ofi_event", "sum"), n=("mid", "size"), n_ofi=("ofi_event", "count"),
                    mid_first=("mid", "first"), mid_last=("mid", "last"))
        prev_last = agg.mid_last.shift(1)
        agg["mid_change_bps"] = 10000 * (agg.mid_last / prev_last - 1)
        complete = agg.n.eq(seconds) & agg.n_ofi.eq(seconds) & prev_last.notna()
        rows.append(agg.loc[complete, ["ofi", "mid_change_bps", "n"]])
    return pd.concat(rows) if rows else pd.DataFrame(columns=["ofi", "mid_change_bps", "n"])


def impact_by_quartile(events: pd.DataFrame, horizons=(0, 5, 30)) -> pd.DataFrame:
    """E5 · Respuesta media por cuartil de tamaño y la fracción que revierte entre el primer y el último horizonte."""
    q = pd.qcut(events.qty, 4, labels=["Q1 (pequeño)", "Q2", "Q3", "Q4 (grande)"])
    cols = [f"response_{h}s_bps" for h in horizons]
    out = events.groupby(q, observed=True)[cols].mean()
    out["reverted_share"] = 1 - out[cols[-1]] / out[cols[0]]
    return out
