"""Comparación entre exchanges (Kraken, OKX, Bitvavo): cotizaciones L1, alineación causal,
correlación de retornos, lead-lag y escáner de arbitraje al mejor nivel.

Origen: P06 · Comparación entre exchanges. Concepto: docs/conceptos/comparacion_entre_exchanges.md
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from itertools import permutations

import numpy as np
import pandas as pd
import requests

EXCHANGES = ("kraken", "okx", "bitvavo")
SYMBOL = "BTC/EUR"
OKX_BASE = "https://www.okx.com"
QUOTE_FIELDS = ["bid", "ask", "bid_size", "ask_size", "mid", "spread_bps"]


# --- Adaptadores y captura ------------------------------------------------------

def parse_quote(exchange: str, payload) -> dict:
    """Mejor bid/ask y sus tamaños visibles a partir de la respuesta pública de cada exchange.

    Kraken: se prefiere el libro `Depth` (count=1), porque el tamaño del `Ticker` (`b`/`a`[2])
    vale siempre 1 y no es la cantidad real (ver P01). Se acepta también el formato `Ticker`.
    `exchange_at` solo se rellena si el proveedor informa del instante del evento (OKX `ts`).
    """
    event_at = pd.NaT
    if exchange == "kraken":
        if payload["error"]:
            raise ValueError(payload["error"])
        d = next(iter(payload["result"].values()))
        if "bids" in d:  # Depth: [precio, cantidad, timestamp del nivel]
            (bid, bs, *_), (ask, az, *_) = d["bids"][0], d["asks"][0]
        else:  # Ticker: [precio, volumen de lote entero, volumen de lote]
            bid, ask, bs, az = d["b"][0], d["a"][0], d["b"][2], d["a"][2]
    elif exchange == "okx":
        if payload["code"] != "0":
            raise ValueError(payload.get("msg"))
        d = payload["data"][0]
        if d["instId"] != "BTC-EUR":
            raise ValueError("Par incorrecto")
        bid, ask, bs, az = d["bidPx"], d["askPx"], d["bidSz"], d["askSz"]
        event_at = pd.to_datetime(int(d["ts"]), unit="ms", utc=True)
    elif exchange == "bitvavo":
        d = payload[0] if isinstance(payload, list) else payload
        if d["market"] != "BTC-EUR":
            raise ValueError("Par incorrecto")
        bid, ask, bs, az = d["bid"], d["ask"], d["bidSize"], d["askSize"]
    else:
        raise ValueError(exchange)
    return dict(bid=float(bid), ask=float(ask), bid_size=float(bs), ask_size=float(az), exchange_at=event_at)


def fetch_quote(exchange: str, okx_base: str = OKX_BASE, symbol: str = SYMBOL, timeout: float = 8) -> dict:
    """Una cotización L1 con `request_at` (antes de pedirla) y `received_at` (al recibirla)."""
    urls = {"kraken": ("https://api.kraken.com/0/public/Depth", {"pair": "XBTEUR", "count": 1}),
            "okx": (okx_base + "/api/v5/market/ticker", {"instId": "BTC-EUR"}),
            "bitvavo": ("https://api.bitvavo.com/v2/ticker/book", {"market": "BTC-EUR"})}
    url, params = urls[exchange]
    started = pd.Timestamp.now(tz="UTC")
    r = requests.get(url, params=params, timeout=timeout)
    received = pd.Timestamp.now(tz="UTC")
    r.raise_for_status()
    return dict(exchange=exchange, symbol=symbol, request_at=started, received_at=received,
                **parse_quote(exchange, r.json()))


def collect_live(rounds: int, exchanges=EXCHANGES, okx_base: str = OKX_BASE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Una ronda por segundo con solicitudes concurrentes. Los fallos se registran, no se sustituyen."""
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=len(exchanges)) as pool:
        for i in range(rounds):
            start = time.monotonic()
            jobs = {e: pool.submit(fetch_quote, e, okx_base) for e in exchanges}
            for e, job in jobs.items():
                try:
                    rows.append(job.result())
                except Exception as exc:  # se conserva el error para documentarlo
                    errors.append((i, e, str(exc)))
            time.sleep(max(0, 1 - (time.monotonic() - start)))
    return pd.DataFrame(rows), pd.DataFrame(errors, columns=["round", "exchange", "error"])


def synthetic_quotes(n: int = 1800, seed: int = 61, exchanges=EXCHANGES, symbol: str = SYMBOL) -> pd.DataFrame:
    """Trayectoria común con OKX retrasado 2 s y Bitvavo 1 s, ruido, desajustes extremos y pérdidas."""
    rng = np.random.default_rng(seed)
    base = 60000 + np.cumsum(rng.normal(0, 4, n + 2))
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    rows = []
    for i, e in enumerate(exchanges):
        lag = [0, 2, 1][i]
        for t in range(n):
            if rng.random() < .008:
                continue
            mid = base[t + 2 - lag] + rng.normal(0, .45) + [0, 1, -1][i]
            if e == "okx" and 200 <= t < 206:
                mid += 220
            if e == "bitvavo" and 1250 <= t < 1254:
                mid -= 230
            spread = [2, 3, 4][i]
            when = start + pd.Timedelta(seconds=t, milliseconds=100 + 100 * i)
            rows.append(dict(exchange=e, symbol=symbol, received_at=when,
                             request_at=when - pd.Timedelta(milliseconds=80),
                             exchange_at=when - pd.Timedelta(milliseconds=30),
                             bid=mid - spread / 2, ask=mid + spread / 2,
                             bid_size=rng.uniform(.003, .18), ask_size=rng.uniform(.003, .18)))
    return pd.DataFrame(rows)


# --- Calidad y alineación ---------------------------------------------------------

def validate_quotes(raw: pd.DataFrame, exchanges=EXCHANGES, symbol: str = SYMBOL) -> pd.DataFrame:
    """Valida cotizaciones L1 y añade mid, spread en bps y tiempo de ida y vuelta (RTT).

    Lanza ValueError si faltan columnas, falta algún exchange o hay otro par, si hay precios o
    tamaños <= 0 o no finitos, libros cruzados, recepciones vacías o duplicadas por exchange,
    o una solicitud posterior a su recepción.
    """
    required = {"exchange", "symbol", "received_at", "bid", "ask", "bid_size", "ask_size"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"Faltan columnas: {missing}")
    d = raw.copy()
    for col in ["received_at", "request_at", "exchange_at"]:
        d[col] = pd.to_datetime(d[col], utc=True, errors="raise", format="mixed") if col in d else pd.NaT
        d[col] = pd.to_datetime(d[col], utc=True)
    cols = ["bid", "ask", "bid_size", "ask_size"]
    d[cols] = d[cols].apply(pd.to_numeric, errors="raise")
    if d.empty or set(d.exchange) != set(exchanges) or not d.symbol.eq(symbol).all():
        raise ValueError("Se requieren los tres exchanges y un único par BTC/EUR")
    if not np.isfinite(d[cols]).all().all() or not (d[cols] > 0).all().all() or not d.ask.ge(d.bid).all():
        raise ValueError("Cotización inválida")
    if d.received_at.isna().any() or d.duplicated(["exchange", "received_at"]).any():
        raise ValueError("Recepción ausente o duplicada")
    if (d.request_at > d.received_at).any():
        raise ValueError("Relojes de solicitud/recepción inconsistentes")
    d["mid"] = (d.bid + d.ask) / 2
    d["spread_bps"] = (d.ask - d.bid) / d.mid * 10000
    d["rtt_ms"] = (d.received_at - d.request_at).dt.total_seconds() * 1000
    return d.sort_values("received_at").reset_index(drop=True)


def align_quotes(quotes: pd.DataFrame, grid: str = "1s", max_age=pd.Timedelta(seconds=2),
                 clock_tolerance_ms: float = 250, exchanges=EXCHANGES) -> pd.DataFrame:
    """Para cada instante t de la rejilla, la última cotización recibida en o antes de t (`backward`).

    Descarta las cotizaciones con recepción más antigua que `max_age` y, si hay `exchange_at`,
    los eventos más antiguos que `max_age` o futuros más allá de `clock_tolerance_ms`.
    """
    start = quotes.received_at.min().ceil(grid)
    end = quotes.received_at.max().floor(grid)
    timeline = pd.DataFrame({"decision_at": pd.date_range(start, end, freq=grid)})
    if len(timeline) < 2:
        raise ValueError("Captura demasiado breve")
    blocks = {}
    for e in exchanges:
        d = quotes.loc[quotes.exchange.eq(e)].drop(columns=["exchange", "symbol"])
        a = pd.merge_asof(timeline, d.sort_values("received_at"), left_on="decision_at", right_on="received_at",
                          direction="backward", tolerance=max_age)
        a["age_ms"] = (a.decision_at - a.received_at).dt.total_seconds() * 1000
        event_age = (a.decision_at - a.exchange_at).dt.total_seconds() * 1000
        a["valid"] = a.received_at.notna() & (
            event_age.isna() | event_age.between(-clock_tolerance_ms, max_age.total_seconds() * 1000))
        a.loc[~a.valid, QUOTE_FIELDS] = np.nan
        blocks[e] = a.set_index("decision_at")
    return pd.concat(blocks, axis=1)


def fresh_returns(aligned: pd.DataFrame) -> pd.DataFrame:
    """Retornos log del mid solo entre dos cotizaciones nuevas consecutivas (no precios arrastrados)."""
    mid = aligned.xs("mid", axis=1, level=1)
    received = aligned.xs("received_at", axis=1, level=1)
    fresh = received.notna() & received.ne(received.shift())
    return np.log(mid).diff().where(fresh & fresh.shift(1, fill_value=False))


# --- Lead-lag ----------------------------------------------------------------------

def lag_profile(x: pd.Series, y: pd.Series, max_lag: int = 5, method: str = "pearson", min_pairs: int = 20) -> pd.DataFrame:
    """ρ(k) = Corr(x_t, y_{t+k}) para k en [−max_lag, max_lag]. k > 0: x se adelanta a y."""
    rows = []
    for k in range(-max_lag, max_lag + 1):
        pairs = pd.concat([x.rename("x"), y.shift(-k).rename("y")], axis=1).dropna()
        rows.append((k, len(pairs), pairs.x.corr(pairs.y, method=method) if len(pairs) >= min_pairs else np.nan))
    return pd.DataFrame(rows, columns=["lag_s", "n", "corr"]).set_index("lag_s")


def leadlag_summary(returns: pd.DataFrame, leader: str = "kraken", targets=("okx", "bitvavo"),
                    max_lag: int = 5, train_fraction: float = .65, method: str = "pearson") -> tuple[pd.DataFrame, dict]:
    """Elige el desplazamiento con mayor correlación en desarrollo y lo evalúa, sin reoptimizar, en validación.

    Deja una fila de separación entre segmentos porque cada retorno usa el precio anterior.
    """
    cut = int(len(returns) * train_fraction)
    dev, test = returns.iloc[:cut], returns.iloc[cut + 1:]
    summary, profiles = [], {}
    for target in targets:
        p = lag_profile(dev[leader], dev[target], max_lag, method)
        q = lag_profile(test[leader], test[target], max_lag, method)
        profiles[target] = (p, q)
        if p["corr"].notna().any():
            best = int(p["corr"].idxmax())
            summary.append(dict(target=target, lag_s=best, dev_corr=p.loc[best, "corr"],
                                test_corr=q.loc[best, "corr"], test_n=q.loc[best, "n"]))
    return pd.DataFrame(summary, columns=["target", "lag_s", "dev_corr", "test_corr", "test_n"]), profiles


# --- Arbitraje al mejor nivel ---------------------------------------------------------

def scan_pair(aligned: pd.DataFrame, buy: str, sell: str, qty: float, fees: dict, extra_bps: float = 1.0,
              max_skew=pd.Timedelta(milliseconds=750)) -> pd.DataFrame:
    """Comprar `qty` en `buy` al ask y venderla en `sell` al bid, con reserva adversa y comisiones.

    C = q·Ask_A·(1+s)·(1+f_A); V = q·Bid_B·(1−s)·(1−f_B); PnL = V − C. Solo es elegible si las dos
    cotizaciones son válidas, su desfase de recepción es <= `max_skew` y `qty` cabe en ambos tamaños.
    El spread ya está dentro de Ask_A y Bid_B: no se resta otra vez.
    """
    a, b = aligned[buy], aligned[sell]
    out = pd.DataFrame(index=aligned.index)
    out["buy"], out["sell"] = buy, sell
    out["gross_gap_eur_per_btc"] = b.bid - a.ask
    out["max_visible_btc"] = pd.concat([a.ask_size, b.bid_size], axis=1).min(axis=1, skipna=False)
    out["skew_ms"] = (a.received_at - b.received_at).abs().dt.total_seconds() * 1000
    out["eligible"] = (a.valid & b.valid & out.skew_ms.le(max_skew.total_seconds() * 1000)
                       & out.max_visible_btc.ge(qty))
    s = extra_bps / 10000
    cost = qty * a.ask * (1 + s) * (1 + fees[buy] / 10000)
    proceeds = qty * b.bid * (1 - s) * (1 - fees[sell] / 10000)
    out["net_eur"] = (proceeds - cost).where(out.eligible)
    out["net_bps"] = (10000 * (proceeds - cost) / cost).where(out.eligible)
    out["candidate"] = out.eligible & out.net_eur.gt(0)
    return out


def scan_routes(aligned: pd.DataFrame, qty: float, fees: dict, extra_bps: float = 1.0,
                max_skew=pd.Timedelta(milliseconds=750), exchanges=EXCHANGES) -> dict:
    """Las seis direcciones de compra y venta entre los tres exchanges."""
    return {f"{a} → {b}": scan_pair(aligned, a, b, qty, fees, extra_bps, max_skew)
            for a, b in permutations(exchanges, 2)}


def route_summary(scans: dict) -> pd.DataFrame:
    return pd.DataFrame([dict(route=name, eligible_seconds=int(d.eligible.sum()),
                              candidate_seconds=int(d.candidate.sum()), best_net_bps=d.net_bps.max())
                         for name, d in scans.items()]).set_index("route")


def episodes(scans: dict) -> pd.DataFrame:
    """Secuencias de segundos consecutivos en que la misma ruta es candidata."""
    rows = []
    for route, d in scans.items():
        mask = d.candidate
        groups = mask.ne(mask.shift(fill_value=False)).cumsum()
        for _, g in d[mask].groupby(groups[mask]):
            rows.append(dict(route=route, start=g.index[0], end=g.index[-1],
                             observed_seconds=len(g), peak_net_bps=g.net_bps.max()))
    return pd.DataFrame(rows, columns=["route", "start", "end", "observed_seconds", "peak_net_bps"])


def fee_sensitivity(aligned: pd.DataFrame, qty: float, fee_levels=(0, 5, 10, 20, 40), extra_bps: float = 1.0,
                    max_skew=pd.Timedelta(milliseconds=750), exchanges=EXCHANGES) -> pd.DataFrame:
    """Segundos-ruta candidatos y episodios con la misma comisión por lado en todos los exchanges."""
    rows = []
    for fee in fee_levels:
        scans = scan_routes(aligned, qty, {e: fee for e in exchanges}, extra_bps, max_skew, exchanges)
        rows.append((fee, int(sum(d.candidate.sum() for d in scans.values())), len(episodes(scans))))
    return pd.DataFrame(rows, columns=["fee_bps_per_side", "candidate_route_seconds", "episodes"])


# --- Ejercicios -------------------------------------------------------------------------

def mid_and_spread(bid: float, ask: float) -> tuple[float, float]:
    """E1 · (mid, spread en bps del mid)."""
    if bid <= 0 or ask < bid:
        raise ValueError("Cotización inválida")
    mid = (bid + ask) / 2
    return mid, (ask - bid) / mid * 10_000


def manual_cross_correlation(x: pd.Series, y: pd.Series, max_lag: int = 5, min_pairs: int = 20) -> pd.Series:
    """E2 · Correlación cruzada ρ(k) = Corr(x_t, y_{t+k}) con `shift` y la fórmula de Pearson explícita."""
    out = {}
    for k in range(-max_lag, max_lag + 1):
        yk = y.shift(-k)
        ok = x.notna() & yk.notna()
        xs, ys = x[ok].to_numpy(), yk[ok].to_numpy()
        if len(xs) < min_pairs:
            out[k] = np.nan
            continue
        dx, dy = xs - xs.mean(), ys - ys.mean()
        out[k] = (dx * dy).sum() / np.sqrt((dx ** 2).sum() * (dy ** 2).sum())
    return pd.Series(out, name="corr").rename_axis("lag_s")


def size_comparison(aligned: pd.DataFrame, sizes=(0.01, 0.05, 0.1), fees: dict | None = None, extra_bps: float = 1.0,
                    max_skew=pd.Timedelta(milliseconds=750), exchanges=EXCHANGES) -> pd.DataFrame:
    """E3 · Segundos elegibles y candidatos por tamaño, con los mismos precios."""
    fees = fees or {e: 10.0 for e in exchanges}
    rows = []
    for qty in sizes:
        scans = scan_routes(aligned, qty, fees, extra_bps, max_skew, exchanges)
        rows.append(dict(qty_btc=qty, eligible_route_seconds=int(sum(d.eligible.sum() for d in scans.values())),
                         candidate_route_seconds=int(sum(d.candidate.sum() for d in scans.values())),
                         episodes=len(episodes(scans))))
    return pd.DataFrame(rows)


def delay_receipt(raw: pd.DataFrame, exchange: str, delay=pd.Timedelta(seconds=1)) -> pd.DataFrame:
    """E5 · Retrasa la recepción (y la solicitud) de un exchange sin tocar precios ni `exchange_at`."""
    out = raw.copy()
    mask = out.exchange.eq(exchange)
    for col in ["received_at", "request_at"]:
        if col in out:
            out[col] = pd.to_datetime(out[col], utc=True)
            out.loc[mask, col] = out.loc[mask, col] + delay
    return out


def capture_report(quotes: pd.DataFrame, errors: pd.DataFrame, aligned: pd.DataFrame, scans: dict,
                   exchanges=EXCHANGES) -> pd.DataFrame:
    """E6 · Filas, errores, cobertura, RTT, spread y pares válidos (elegibles) por exchange."""
    valid = aligned.xs("valid", axis=1, level=1)
    rows = {}
    for e in exchanges:
        q = quotes.loc[quotes.exchange.eq(e)]
        pairs = sum(int(d.eligible.sum()) for name, d in scans.items() if e in name.split(" → "))
        rows[e] = {"rows": len(q), "errors": int(errors.exchange.eq(e).sum()) if not errors.empty else 0,
                   "coverage_pct": 100 * valid[e].mean(), "rtt_ms_median": q.rtt_ms.median(),
                   "spread_bps_median": q.spread_bps.median(), "eligible_route_seconds": pairs}
    return pd.DataFrame(rows).T
