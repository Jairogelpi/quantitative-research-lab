"""Investigación integral: captura multi-exchange, rejilla causal de un segundo, lead-lag Kraken → OKX,
predictibilidad con errores HAC, motor long-only con costes y profundidad, bootstrap por bloques y decisión.

Origen: P17 · Primera investigación cuantitativa integral. Concepto: docs/conceptos/investigacion_integral.md
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import statsmodels.api as sm

EXCHANGES = ["kraken", "okx", "bitvavo"]
SYMBOL = "BTC/EUR"
QUOTE_COLS = ["bid", "ask", "bid_size", "ask_size"]
PNL_COLS = ["gross_pnl", "spread_slippage", "fees", "net_pnl", "net_bps"]


# --- Datos y sincronización ------------------------------------------------------------

def synthetic_quotes(n: int = 7200, seed: int = 1701, exchanges=EXCHANGES, symbol: str = SYMBOL) -> pd.DataFrame:
    """Camino común con OKX retrasado 3 s y Bitvavo 2 s, spreads de 2/3/4 EUR y ~0,8 % de mensajes perdidos."""
    rng = np.random.default_rng(seed)
    base = 60000 + np.cumsum(rng.normal(0, 5, n + 5))
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    frames = []
    for ex, lag, spread in zip(exchanges, [0, 3, 2], [2, 3, 4]):
        mid = base[5 - lag:5 - lag + n] + rng.normal(0, .5, n)
        ms = {"kraken": 100, "okx": 250, "bitvavo": 400}[ex]
        f = pd.DataFrame({"received_at": start + pd.to_timedelta(np.arange(n), unit="s") + pd.Timedelta(milliseconds=ms),
                          "exchange": ex, "symbol": symbol, "bid": mid - spread / 2, "ask": mid + spread / 2,
                          "bid_size": rng.uniform(.003, .18, n), "ask_size": rng.uniform(.003, .18, n)})
        frames.append(f.loc[rng.random(n) > .008])
    return pd.concat(frames, ignore_index=True)


def validate(raw: pd.DataFrame, symbol: str = SYMBOL, exchanges=EXCHANGES) -> pd.DataFrame:
    """Filtra el par y los exchanges; rechaza columnas ausentes, exchanges sin datos, tiempos inválidos o
    duplicados por exchange, precios o tamaños no finitos o ≤ 0 y libros cruzados. No corrige nada."""
    req = {"received_at", "exchange", "symbol", *QUOTE_COLS}
    if not req.issubset(raw):
        raise ValueError(f"Faltan {req - set(raw)}")
    x = raw.loc[raw.symbol.eq(symbol) & raw.exchange.isin(exchanges)].copy()
    x["received_at"] = pd.to_datetime(x.received_at, utc=True, errors="raise", format="mixed")
    x[QUOTE_COLS] = x[QUOTE_COLS].apply(pd.to_numeric, errors="raise")
    if set(x.exchange) != set(exchanges) or x.received_at.isna().any() or x.duplicated(["exchange", "received_at"]).any():
        raise ValueError("Cobertura o tiempos inválidos")
    if not np.isfinite(x[QUOTE_COLS]).all().all() or not x[QUOTE_COLS].gt(0).all().all() or not x.ask.gt(x.bid).all():
        raise ValueError("Cotizaciones inválidas")
    return x.sort_values("received_at")


def synchronize(x: pd.DataFrame, exchanges=EXCHANGES, max_age_s: float = 1.5, min_seconds: int = 500,
                max_seconds: int = 2_000_000) -> pd.DataFrame:
    """Rejilla UTC de 1 s en el tramo común: en cada instante, la última cotización recibida antes o en él,
    si no tiene más de `max_age_s`; si no, NaN (sin interpolar ni rellenar)."""
    start = x.groupby("exchange").received_at.min().max().ceil("s")
    end = x.groupby("exchange").received_at.max().min().floor("s")
    grid = pd.DataFrame({"time": pd.date_range(start, end, freq="s")})
    if len(grid) < min_seconds or len(grid) > max_seconds:
        raise ValueError("Captura insuficiente o demasiado extensa para esta práctica")
    result = grid.set_index("time")
    for ex in exchanges:
        f = x.loc[x.exchange.eq(ex), ["received_at", *QUOTE_COLS]]
        a = pd.merge_asof(grid, f, left_on="time", right_on="received_at", direction="backward",
                          tolerance=pd.Timedelta(seconds=max_age_s)).set_index("time")
        a["age_s"] = (a.index.to_series() - a.received_at).dt.total_seconds()
        a["mid"] = (a.bid + a.ask) / 2
        a["obi"] = (a.bid_size - a.ask_size) / (a.bid_size + a.ask_size)
        a["spread_bps"] = (a.ask - a.bid) / a.mid * 1e4
        result = result.join(a.add_prefix(ex + "_"))
    return result


def returns_bps(g: pd.DataFrame, exchanges=EXCHANGES) -> pd.DataFrame:
    """Retornos simples de 1 s del mid en bps (NaN si falta alguno de los dos mids)."""
    r = g[[e + "_mid" for e in exchanges]].pct_change(fill_method=None) * 1e4
    r.columns = list(exchanges)
    return r


def lead_lag(r: pd.DataFrame, leader: str = "kraken", targets=("okx", "bitvavo"), max_lag: int = 5) -> pd.DataFrame:
    """Corr(r_leader,t, r_target,t+k) para k = −max_lag..max_lag. k > 0: el líder precede."""
    return pd.DataFrame({e: {k: r[leader].corr(r[e].shift(-k)) for k in range(-max_lag, max_lag + 1)} for e in targets})


# --- Oportunidades, predictibilidad y ejecución ----------------------------------------------

def opportunities(g: pd.DataFrame, cut, lookback: int = 3, delay: int = 1, hold: int = 4, qty: float = .01,
                  leader: str = "kraken", venue: str = "okx") -> pd.DataFrame:
    """Una decisión cada `delay + hold` s: señal = retorno del mid del líder en `lookback` s (bps); entrada en el
    venue `delay` s después; salida `hold` s después de entrar. Las ventanas que cruzan `cut` se purgan."""
    stride = delay + hold
    d = pd.DataFrame(index=g.index)
    d["signal_bps"] = g[leader + "_mid"].pct_change(lookback, fill_method=None) * 1e4
    d["obi"] = g[leader + "_obi"]
    d["venue_obi"] = g[venue + "_obi"]
    for field in ["ask", "mid", "ask_size"]:
        d["entry_" + field] = g[f"{venue}_{field}"].shift(-delay)
    for field in ["bid", "mid", "bid_size"]:
        d["exit_" + field] = g[f"{venue}_{field}"].shift(-stride)
    d["entry_time"] = d.index + pd.Timedelta(seconds=delay)
    d["exit_time"] = d.index + pd.Timedelta(seconds=stride)
    d["target_bps"] = (d.exit_mid / d.entry_mid - 1) * 1e4
    d = d.iloc[::stride].copy()
    d = d.loc[(d.index >= g.index[0] + pd.Timedelta(seconds=lookback)) & (d.exit_time <= g.index[-1])]
    d["split"] = np.where(d.exit_time < cut, "dev", np.where(d.index >= cut, "val", "purge"))
    d = d.loc[d.split.ne("purge")]
    needed = ["signal_bps", "entry_ask", "entry_mid", "entry_ask_size", "exit_bid", "exit_mid", "exit_bid_size"]
    d["observed"] = d[needed].notna().all(axis=1)
    d["entry_depth_ok"] = d.entry_ask_size.ge(qty)
    d["exit_depth_ok"] = d.exit_bid_size.ge(qty)
    return d


def fit_hac(frame: pd.DataFrame, x: str = "signal_bps", y: str = "target_bps", lags: int = 5):
    """OLS de y sobre x con constante y errores HAC (Newey-West)."""
    return sm.OLS(frame[y], sm.add_constant(frame[[x]], has_constant="add")).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


def predictability(dev: pd.DataFrame, val: pd.DataFrame, x: str = "signal_bps", y: str = "target_bps", lags: int = 5):
    """(tabla por muestra, R² fuera de muestra con coeficientes congelados frente a la media de desarrollo, modelos)."""
    a, b = fit_hac(dev, x, y, lags), fit_hac(val, x, y, lags)
    pred = a.predict(sm.add_constant(val[[x]], has_constant="add"))
    oos = 1 - ((val[y] - pred) ** 2).sum() / ((val[y] - dev[y].mean()) ** 2).sum()
    stats = pd.DataFrame([{"sample": label, "n": len(f), "IC": f[x].corr(f[y]), "slope": m.params[x],
                           "p_value": m.pvalues[x], "R2": m.rsquared}
                          for label, f, m in [("dev", dev, a), ("val", val, b)]]).set_index("sample")
    return stats, oos, a, b


def evaluate(frame: pd.DataFrame, threshold: float, qty: float = .01, fee_bps: float = 10., extra_bps: float = 1.,
             always: bool = False) -> pd.DataFrame:
    """Long-only: compra al ask · (1 + extra) y vende al bid · (1 − extra), comisión por lado sobre cada nominal.

    Sin señal → PnL 0. Con señal y sin profundidad L1 en la entrada o en la salida → PnL desconocido (NaN):
    excluirla sería una selección ex post. Bruto = q · (mid salida − mid entrada); neto = q · (venta − compra) − fees.
    """
    p = frame.copy()
    p["intent"] = True if always else p.signal_bps.gt(threshold)
    p["filled"] = p.intent & p.entry_depth_ok & p.exit_depth_ok
    p["failed_depth"] = p.intent & ~p.filled
    p["buy_px"] = p.entry_ask * (1 + extra_bps / 1e4)
    p["sell_px"] = p.exit_bid * (1 - extra_bps / 1e4)
    p["gross_pnl"] = qty * (p.exit_mid - p.entry_mid)
    p["spread_slippage"] = p.gross_pnl - qty * (p.sell_px - p.buy_px)
    p["fees"] = qty * (p.buy_px + p.sell_px) * fee_bps / 1e4
    p["net_pnl"] = p.gross_pnl - p.spread_slippage - p.fees
    p["net_bps"] = p.net_pnl / (qty * p.entry_mid) * 1e4
    p.loc[~p.intent, PNL_COLS] = 0.
    p.loc[p.failed_depth, PNL_COLS] = np.nan
    return p


def summarize_pnl(p: pd.DataFrame, initial_equity: float = 1000.) -> pd.Series:
    """Oportunidades, señales, ejecuciones, fallos de profundidad, PnL bruto y neto condicionado, acierto,
    profit factor, caída máxima del capital contable y PnL medio por oportunidad observada."""
    f = p.loc[p.filled]
    wins, losses = f.net_pnl[f.net_pnl > 0].sum(), -f.net_pnl[f.net_pnl < 0].sum()
    eq = initial_equity + p.net_pnl.dropna().cumsum()
    peak = eq.cummax().clip(lower=initial_equity)
    return pd.Series({"opportunities": len(p), "signals": int(p.intent.sum()), "fills": int(p.filled.sum()),
                      "failed_depth": int(p.failed_depth.sum()), "gross_eur": f.gross_pnl.sum(),
                      "net_eur_conditional": f.net_pnl.sum(), "mean_net_bps_per_fill": f.net_bps.mean(),
                      "win_rate": f.net_pnl.gt(0).mean(), "profit_factor": wins / losses if losses > 0 else np.nan,
                      "max_drawdown_conditional": (1 - eq / peak).max(), "mean_net_eur_observed": p.net_pnl.mean()})


def block_ci(values, block: int = 10, reps: int = 2000, seed: int = 1702, level: float = .95) -> np.ndarray:
    """IC percentil de la media con bootstrap de bloques circulares contiguos (los NaN se ignoran)."""
    v = np.asarray(values, float)
    rng, nn = np.random.default_rng(seed), len(v)
    starts = rng.integers(0, nn, size=(reps, int(np.ceil(nn / block))))
    idx = ((starts[:, :, None] + np.arange(block)) % nn).reshape(reps, -1)[:, :nn]
    means = np.nanmean(v[idx], axis=1)
    return np.nanquantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])


def fee_sensitivity(val: pd.DataFrame, threshold: float, fees=(0, 1, 2, 5, 10, 20), **kw) -> pd.Series:
    """PnL neto condicionado de validación con la regla fija y distintas comisiones por lado."""
    return pd.Series({fee: evaluate(val, threshold, fee_bps=fee, **kw).net_pnl.sum() for fee in fees},
                     name="PnL EUR condicionado")


def decision(b, pv: pd.DataFrame, all_op: pd.DataFrame, ci, min_fills: int = 30) -> dict:
    """Criterios fijados en el protocolo: estadístico (pendiente > 0 y p < 0,05 en validación) y económico
    conservador (≥ min_fills ejecuciones, ningún fallo de profundidad, todas las ventanas de validación
    observadas y límite inferior del IC del PnL > 0)."""
    stat_ok = bool(b.params["signal_bps"] > 0 and b.pvalues["signal_bps"] < .05)
    econ_ok = bool(pv.filled.sum() >= min_fills and pv.failed_depth.sum() == 0
                   and all_op.loc[all_op.split.eq("val"), "observed"].all() and ci[0] > 0)
    verdict = "Solo ampliar investigación; no operar" if stat_ok and econ_ok else \
        "No aprobar hipótesis económica; revisar evidencia y calidad"
    return {"stat_ok": stat_ok, "econ_ok": econ_ok, "decision": verdict}


# --- Ejercicios ---------------------------------------------------------------------------------

def register_protocol(protocol: dict) -> str:
    """E1 · Huella SHA-256 del protocolo (JSON ordenado): fija la hipótesis antes de ver resultados."""
    return hashlib.sha256(json.dumps(protocol, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audit_capture(quotes: pd.DataFrame, g: pd.DataFrame, qty: float = .01, max_age_s: float = 1.5,
                  exchanges=EXCHANGES) -> pd.DataFrame:
    """E3 · Auditoría por exchange: filas, duplicados, huecos entre recepciones, spreads, profundidad L1,
    cobertura de la rejilla y antigüedad. Comprueba que ningún valor de la rejilla es posterior a su instante."""
    rows = {}
    for ex in exchanges:
        q = quotes[quotes.exchange == ex].sort_values("received_at")
        gaps = q.received_at.diff().dt.total_seconds().dropna()
        spread = (q.ask - q.bid) / ((q.ask + q.bid) / 2) * 1e4
        age = g[ex + "_age_s"].dropna()
        received = g[ex + "_received_at"].dropna()
        rows[ex] = {"filas": len(q), "duplicados": int(q.duplicated(["received_at"]).sum()),
                    "hueco_mediano_s": gaps.median(), "hueco_max_s": gaps.max(), f"huecos_>{max_age_s}s": int((gaps > max_age_s).sum()),
                    "spread_mediano_bps": spread.median(), "spread_max_bps": spread.max(),
                    "prof_bid_ok_pct": q.bid_size.ge(qty).mean() * 100, "prof_ask_ok_pct": q.ask_size.ge(qty).mean() * 100,
                    "cobertura_rejilla_pct": g[ex + "_mid"].notna().mean() * 100, "edad_media_s": age.mean(),
                    "edad_max_s": age.max(),
                    "sin_futuro": bool((age >= 0).all() and (received.to_numpy() <= received.index.to_numpy()).all())}
    return pd.DataFrame(rows).T.infer_objects()


def session_lead_lag(r: pd.DataFrame, n_sessions: int = 2, leader: str = "kraken", targets=("okx", "bitvavo"),
                     max_lag: int = 5) -> pd.DataFrame:
    """E4 · Lead-lag en `n_sessions` tramos consecutivos del desarrollo: lag de máxima correlación y su valor."""
    rows = []
    for i, part in enumerate(np.array_split(np.arange(len(r)), n_sessions), start=1):
        ll = lead_lag(r.iloc[part], leader, targets, max_lag)
        for e in targets:
            rows.append({"sesion": i, "desde": r.index[part[0]], "hasta": r.index[part[-1]], "exchange": e,
                         "lag_max": int(ll[e].idxmax()), "corr_max": ll[e].max(), "corr_lag0": ll[e].loc[0]})
    return pd.DataFrame(rows)


def circular_shift_null(x, y, n_null: int = 1000, min_shift: int = 10, seed: int = 1703) -> dict:
    """E5 · Null de la correlación desplazando y circularmente (conserva su autocorrelación) frente a barajar.

    Solo usa los pares con x e y finitos. p unilateral = (1 + #{null ≥ observada}) / (1 + n_null).
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    n = len(x)
    if n < 2 * min_shift + 2:
        raise ValueError("Muestra demasiado corta para desplazamientos")
    rng = np.random.default_rng(seed)
    observed = np.corrcoef(x, y)[0, 1]
    shifts = rng.integers(min_shift, n - min_shift, n_null)
    circ = np.array([np.corrcoef(x, np.roll(y, s))[0, 1] for s in shifts])
    shuffled = np.array([np.corrcoef(x, rng.permutation(y))[0, 1] for _ in range(n_null)])
    return {"n": n, "observed": observed, "p_circular": (1 + (circ >= observed).sum()) / (1 + n_null),
            "p_shuffle": (1 + (shuffled >= observed).sum()) / (1 + n_null), "sd_circular": circ.std(),
            "sd_shuffle": shuffled.std(), "acf1_x": pd.Series(x).autocorr(), "acf1_y": pd.Series(y).autocorr()}


def partial_fill_engine(g: pd.DataFrame, frame: pd.DataFrame, threshold: float, qty: float = .01, fee_bps: float = 10.,
                        extra_bps: float = 1., max_wait_s: int = 5, venue: str = "okx") -> pd.DataFrame:
    """E6 · Ejecución parcial con inventario.

    Entrada: compra min(qty, tamaño del ask) en `entry_time`. Salida: desde `exit_time`, vende cada segundo
    min(inventario, tamaño del bid) durante `max_wait_s` s más; lo que quede es inventario abierto valorado al
    último mid (marcado, no realizado). No se abre una posición nueva mientras quede inventario. Supone que el
    tamaño visible se renueva cada segundo (aproximación con snapshots L1).
    """
    rows, busy_until = [], g.index[0] - pd.Timedelta(seconds=1)
    for t, o in frame.iterrows():
        if not (o.signal_bps > threshold) or o.entry_time <= busy_until or not np.isfinite(o.entry_ask):
            continue
        bought = min(qty, o.entry_ask_size)
        buy_px = o.entry_ask * (1 + extra_bps / 1e4)
        held, proceeds, fees, last_mid, end = bought, 0., bought * buy_px * fee_bps / 1e4, o.entry_mid, o.exit_time
        for s in pd.date_range(o.exit_time, o.exit_time + pd.Timedelta(seconds=max_wait_s), freq="s"):
            if s not in g.index or held <= 1e-12:
                break
            q = g.loc[s]
            if np.isfinite(q[venue + "_bid"]):
                sold = min(held, q[venue + "_bid_size"])
                px = q[venue + "_bid"] * (1 - extra_bps / 1e4)
                proceeds += sold * px
                fees += sold * px * fee_bps / 1e4
                held -= sold
                last_mid, end = q[venue + "_mid"], s
        realized = proceeds - (bought - held) * buy_px - fees
        rows.append({"decision": t, "bought": bought, "sold": bought - held, "inventory_open": held,
                     "realized_eur": realized, "marked_eur": realized + held * (last_mid - buy_px),
                     "partial_entry": bought < qty, "used_wait": end > o.exit_time, "entry_time": o.entry_time,
                     "closed_at": end})
        busy_until = end
    return pd.DataFrame(rows)


def opportunity_metrics(pnl_bps: pd.Series, pnl_eur: pd.Series, initial_equity: float = 1000.) -> dict:
    """E7 · Métricas por oportunidad, sin anualizar: media, desviación, media/desviación, acierto y caída máxima."""
    s, e = pnl_bps.dropna(), pnl_eur.dropna()
    eq = initial_equity + e.cumsum()
    peak = eq.cummax().clip(lower=initial_equity)
    traded = s[s.ne(0)]
    return {"n": len(s), "media_bps": s.mean(), "desv_bps": s.std(), "media/desv": s.mean() / s.std() if s.std() > 0 else np.nan,
            "acierto_operaciones": traded.gt(0).mean() if len(traded) else np.nan, "caida_max_pct": (1 - eq / peak).max() * 100}


def run_study(raw: pd.DataFrame, cut_share: float = .60, quantile: float = .70, qty: float = .01, fee_bps: float = 10.,
              extra_bps: float = 1., max_age_s: float = 1.5, lookback: int = 3, delay: int = 1, hold: int = 4,
              min_obs: int = 60, symbol: str = SYMBOL, exchanges=EXCHANGES) -> dict:
    """Protocolo completo sobre una captura: validar, sincronizar, cortar, umbral de desarrollo, predictibilidad,
    ejecución, bootstrap, sensibilidad a comisiones y decisión. Se detiene si hay < `min_obs` oportunidades."""
    quotes = validate(raw, symbol, exchanges)
    g = synchronize(quotes, exchanges, max_age_s)
    cut = g.index[int(len(g) * cut_share)]
    all_op = opportunities(g, cut, lookback, delay, hold, qty)
    d = all_op.loc[all_op.observed]
    dev, val = d.loc[d.split.eq("dev")], d.loc[d.split.eq("val")]
    if min(len(dev), len(val)) < min_obs:
        raise ValueError(f"Captura insuficiente: se requieren {min_obs} oportunidades observadas por segmento")
    threshold = max(0., dev.signal_bps.quantile(quantile))
    stats, oos, a, b = predictability(dev, val)
    kw = dict(qty=qty, fee_bps=fee_bps, extra_bps=extra_bps)
    pv, pdv, bench = evaluate(val, threshold, **kw), evaluate(dev, threshold, **kw), evaluate(val, threshold, always=True, **kw)
    ci = block_ci(pv.net_pnl)
    return {"quotes": quotes, "g": g, "cut": cut, "all_op": all_op, "dev": dev, "val": val, "threshold": threshold,
            "stats": stats, "oos_r2": oos, "model_dev": a, "model_val": b, "pv": pv, "pdv": pdv, "bench": bench,
            "summary": pd.DataFrame({"development": summarize_pnl(pdv), "validation": summarize_pnl(pv),
                                     "always_long_validation": summarize_pnl(bench)}),
            "ci": ci, "sensitivity": fee_sensitivity(val, threshold, qty=qty, extra_bps=extra_bps),
            "decision": decision(b, pv, all_op, ci)}
