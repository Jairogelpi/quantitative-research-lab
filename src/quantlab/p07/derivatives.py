"""Perpetuos lineales BTC/USDT: basis, open interest, funding, liquidaciones, cobertura spot + short y margen.

Origen: P07 · Análisis de derivados financieros. Concepto: docs/conceptos/derivados_perpetuos.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import requests

PRICE_COLS = ["spot_price", "perp_price", "mark_price", "index_price"]
COLS = PRICE_COLS + ["open_interest_btc", "funding_rate", "long_liquidation_usdt", "short_liquidation_usdt"]
OKX_BASE = "https://www.okx.com"
OKX_SWAP = "BTC-USDT-SWAP"
EVENT_LABELS = ["Liquidación long dominante", "Liquidación short dominante", "Resto"]


# --- Datos ------------------------------------------------------------------

def make_synthetic(n: int = 720, seed: int = 72) -> pd.DataFrame:
    """Serie horaria ficticia: shocks de precio, prima oscilante, OI, funding cada 8 h y liquidaciones."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2025-01-01 01:00", periods=n, freq="h", tz="UTC")
    r = rng.normal(0, .003, n)
    for i in (90, 245, 420, 615):
        if i < n:
            r[i] = -.024
    for i in (155, 335, 540):
        if i < n:
            r[i] = .021
    spot = 60000 * np.exp(np.cumsum(r))
    premium = .0004 + .001 * np.sin(np.arange(n) / 19) + rng.normal(0, .0005, n)
    perp = spot * (1 + premium)
    mark = spot * (1 + premium * .8)
    index = spot * (1 + rng.normal(0, .0001, n))
    oi = 12000 * np.exp(np.cumsum(rng.normal(.0001, .002, n) - .8 * np.maximum(abs(r) - .012, 0)))
    rate = np.where(t.hour % 8 == 0, np.clip(premium * .15, -.0004, .0004), 0)
    long_liq = rng.gamma(1.2, 12000, n) + np.maximum(-r - .008, 0) * 4e8
    short_liq = rng.gamma(1.2, 12000, n) + np.maximum(r - .008, 0) * 4e8
    return pd.DataFrame(dict(timestamp=t, spot_price=spot, perp_price=perp, mark_price=mark,
                             index_price=index, open_interest_btc=oi, funding_rate=rate,
                             long_liquidation_usdt=long_liq, short_liquidation_usdt=short_liq))


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """Valida, ordena y reindexa a frecuencia horaria sin rellenar huecos.

    Lanza ValueError si faltan columnas, hay timestamps nulos, duplicados o que no son cierres
    horarios, datos vacíos o infinitos, precios <= 0 o cantidades negativas.
    """
    d = frame.copy()
    missing = set(["timestamp"] + COLS) - set(d.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {missing}")
    d["timestamp"] = pd.to_datetime(d.timestamp, utc=True, errors="raise")
    if d.timestamp.isna().any() or d.timestamp.duplicated().any():
        raise ValueError("Timestamps nulos o duplicados")
    if not d.timestamp.eq(d.timestamp.dt.floor("h")).all():
        raise ValueError("Se requieren cierres horarios UTC")
    d = d.set_index("timestamp")[COLS].sort_index().apply(pd.to_numeric, errors="raise")
    if d.empty or np.isinf(d.to_numpy()).any():
        raise ValueError("Datos vacíos o infinitos")
    if ((d[PRICE_COLS] <= 0).any().any()
            or (d[["open_interest_btc", "long_liquidation_usdt", "short_liquidation_usdt"]] < 0).any().any()):
        raise ValueError("Precios no positivos o cantidades negativas")
    full = pd.date_range(d.index.min(), d.index.max(), freq="h", tz="UTC", name="timestamp")
    return d.reindex(full)


# --- Indicadores ---------------------------------------------------------------

def add_features(d: pd.DataFrame, qty_btc: float = .02) -> pd.DataFrame:
    """Basis, prima del mark, retorno spot, cambio de OI, OI nominal, funding y liquidaciones."""
    out = d.copy()
    out["basis_bps"] = (out.perp_price / out.spot_price - 1) * 10000
    out["mark_index_bps"] = (out.mark_price / out.index_price - 1) * 10000
    out["spot_return"] = out.spot_price.pct_change(fill_method=None)
    out["oi_change_pct"] = out.open_interest_btc.pct_change(fill_method=None) * 100
    out["oi_notional_usdt"] = out.open_interest_btc * out.mark_price
    out["funding_bps"] = out.funding_rate * 10000
    out["short_funding_usdt"] = qty_btc * out.mark_price * out.funding_rate
    out["liquidation_total_usdt"] = out.long_liquidation_usdt + out.short_liquidation_usdt
    out["liquidation_imbalance"] = ((out.long_liquidation_usdt - out.short_liquidation_usdt)
                                    / out.liquidation_total_usdt.replace(0, np.nan))
    return out


def oi_regime(d: pd.DataFrame) -> pd.DataFrame:
    """Tabla cruzada: dirección del precio frente a dirección del OI (en BTC)."""
    valid = d[["spot_return", "oi_change_pct"]].dropna()
    return pd.crosstab(np.where(valid.spot_return >= 0, "Precio sube/no cambia", "Precio baja"),
                       np.where(valid.oi_change_pct >= 0, "OI sube/no cambia", "OI baja"))


# --- Estudio de eventos de liquidación ---------------------------------------------

def split_for_horizon(d: pd.DataFrame, horizon: int, train_fraction: float = .65) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separación 65/35 descartando del desarrollo las filas cuyo objetivo cruza la frontera."""
    cut = int(len(d) * train_fraction)
    if cut <= horizon or len(d) - cut <= horizon:
        raise ValueError("Histórico insuficiente")
    return d.iloc[:cut - horizon].copy(), d.iloc[cut:].copy()


def event_summary(frame: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Retorno posterior por tipo de evento: liquidación total > umbral y predominio de largos o cortos."""
    x = frame.dropna(subset=["liquidation_total_usdt", "liquidation_imbalance", "forward_return_bps"]).copy()
    x["event"] = np.select([(x.liquidation_total_usdt > threshold) & (x.liquidation_imbalance > 0),
                            (x.liquidation_total_usdt > threshold) & (x.liquidation_imbalance < 0)],
                           EVENT_LABELS[:2], default=EVENT_LABELS[2])
    return x.groupby("event").forward_return_bps.agg(n="size", mean_bps="mean", median_bps="median")


def event_study(d: pd.DataFrame, horizon: int = 3, train_fraction: float = .65,
                quantile: float = .95) -> tuple[pd.DataFrame, float, pd.DataFrame, pd.DataFrame]:
    """Retorno spot a `horizon` horas tras eventos de liquidación. El umbral se estima SOLO en desarrollo."""
    x = d.copy()
    x["forward_return_bps"] = (x.spot_price.shift(-horizon) / x.spot_price - 1) * 10000
    train, test = split_for_horizon(x, horizon, train_fraction)
    threshold = train.liquidation_total_usdt.quantile(quantile)
    results = pd.concat({"desarrollo": event_summary(train, threshold),
                         "validacion": event_summary(test, threshold)}, names=["periodo"])
    return results, threshold, train, test


# --- Cobertura y margen ---------------------------------------------------------------

def hedge_curve(frame: pd.DataFrame, q: float, margin: float, fee_bps: float,
                maintenance_rate: float = .005) -> pd.DataFrame:
    """Largo `q` BTC spot + corto `q` BTC perpetuo, valorado como si se cerrara en cada hora.

    price_pnl = q·((spot_t − spot_0) − (perp_t − perp_0)): es exactamente −q·(variación del basis en USDT).
    Se suma el funding (sin el de la hora de entrada) y se restan cuatro ejecuciones. El margen del
    short se valora con el mark; `margin_breach` marca el cruce del mantenimiento supuesto.
    """
    if q <= 0 or margin <= 0 or fee_bps < 0:
        raise ValueError("Parámetros inválidos")
    s, p, mark = frame.spot_price, frame.perp_price, frame.mark_price
    if not np.isfinite([s.iloc[0], p.iloc[0], mark.iloc[0]]).all():
        raise ValueError("Falta precio inicial")
    fee = fee_bps / 10000
    funding = (q * mark * frame.funding_rate).copy()
    funding.iloc[0] = 0
    cum_funding = funding.cumsum(skipna=False)
    price_pnl = q * ((s - s.iloc[0]) - (p - p.iloc[0]))
    fees = q * fee * (s.iloc[0] + p.iloc[0] + s + p)
    net = price_pnl + cum_funding - fees
    # Margen ilustrativo aislado; mark para valorar el short.
    margin_equity = margin + q * (p.iloc[0] - mark) + cum_funding - q * p.iloc[0] * fee
    breach = margin_equity <= q * mark * maintenance_rate
    return pd.DataFrame(dict(price_pnl=price_pnl, funding_pnl=cum_funding, fees=fees, net_pnl=net,
                             margin_equity=margin_equity, margin_breach=breach, mark_price=mark))


def margin_scenario(notional: float = 1000, margin: float = 100, shocks=(0, .02, .05, .08, .10, .15),
                    maintenance_rate: float = .005) -> pd.DataFrame:
    """Short de `notional` con garantía `margin` ante subidas de precio, sin costes."""
    shock = np.asarray(shocks, dtype=float)
    out = pd.DataFrame({"subida_precio_pct": shock * 100, "pnl_short_usdt": -notional * shock,
                        "garantia_restante_usdt": margin - notional * shock,
                        "mantenimiento_usdt": notional * (1 + shock) * maintenance_rate})
    out["umbral_superado"] = out.garantia_restante_usdt <= out.mantenimiento_usdt
    return out


# --- OKX (captura pública) -----------------------------------------------------------

def okx_get(path: str, params: dict, okx_base: str = OKX_BASE, timeout: float = 15) -> tuple[list, str]:
    """GET público a OKX. Lanza la excepción si la API falla: nunca se sustituye por datos ficticios."""
    response = requests.get(okx_base + path, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "0" or not payload.get("data"):
        raise RuntimeError(f"OKX {path}: {payload.get('code')} {payload.get('msg')}")
    return payload["data"], str(pd.Timestamp.now(tz="UTC"))


def okx_snapshot(okx_base: str = OKX_BASE, swap: str = OKX_SWAP, history: int = 10) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Captura secuencial de spot, perpetuo, mark, índice, OI, funding anunciado e histórico de funding.

    Los endpoints se consultan uno tras otro: sus timestamps pueden diferir.
    """
    queries = {"spot": ("/api/v5/market/ticker", {"instId": "BTC-USDT"}),
               "perp": ("/api/v5/market/ticker", {"instId": swap}),
               "mark": ("/api/v5/public/mark-price", {"instType": "SWAP", "instId": swap}),
               "index": ("/api/v5/market/index-tickers", {"instId": "BTC-USDT"}),
               "oi": ("/api/v5/public/open-interest", {"instType": "SWAP", "instId": swap}),
               "funding": ("/api/v5/public/funding-rate", {"instId": swap}),
               "funding_history": ("/api/v5/public/funding-rate-history", {"instId": swap, "limit": str(history)}),
               "instrument": ("/api/v5/public/instruments", {"instType": "SWAP", "instId": swap})}
    live, received = {}, {}
    for key, (path, params) in queries.items():
        live[key], received[key] = okx_get(path, params, okx_base)
    fields = [("spot", "last"), ("perp", "last"), ("mark", "markPx"), ("index", "idxPx"), ("oi", "oi"),
              ("oi", "oiCcy"), ("funding", "fundingRate"), ("funding", "fundingTime"), ("funding", "settFundingRate"),
              ("instrument", "ctVal")]
    rows = [dict(source=k, field=f, value=live[k][0].get(f), exchange_ts_ms=live[k][0].get("ts"),
                 received_at=received[k]) for k, f in fields]
    hist = pd.DataFrame(live["funding_history"]).reindex(columns=["instId", "fundingTime", "fundingRate", "realizedRate"])
    return pd.DataFrame(rows), hist, live


# --- Ejercicios -------------------------------------------------------------------------

def basis_bps(spot: float, perp: float) -> float:
    """E1 · Basis en bps: 10.000 · (perp − spot) / spot. Un spot <= 0 no tiene sentido económico."""
    if not np.isfinite(spot) or not np.isfinite(perp) or spot <= 0 or perp <= 0:
        raise ValueError("Precios no positivos o no finitos")
    return 10_000 * (perp - spot) / spot


def oi_change_comparison(d: pd.DataFrame) -> pd.DataFrame:
    """E2 · Variación del OI en BTC frente a USDT y horas en que tienen signo distinto."""
    out = pd.DataFrame({"oi_change_btc_pct": d.open_interest_btc.pct_change(fill_method=None) * 100,
                        "oi_change_usdt_pct": (d.open_interest_btc * d.mark_price).pct_change(fill_method=None) * 100,
                        "mark_change_pct": d.mark_price.pct_change(fill_method=None) * 100}).dropna()
    out["sign_differs"] = np.sign(out.oi_change_btc_pct) != np.sign(out.oi_change_usdt_pct)
    return out


def funding_payments(q: float, mark: float, rate: float) -> dict:
    """E3 · Pago de funding por evento en un perpetuo lineal: tasa positiva, los largos pagan y los cortos cobran."""
    if q <= 0 or mark <= 0:
        raise ValueError("q y mark deben ser positivos")
    amount = q * mark * rate
    return {"long_usdt": -amount, "short_usdt": amount}


def event_study_horizons(d: pd.DataFrame, horizons=(1, 3, 6), train_fraction: float = .65) -> pd.DataFrame:
    """E4 · Estudio de eventos a varios horizontes, con el umbral fijado en el desarrollo de cada uno."""
    frames = []
    for h in horizons:
        results, threshold, _, _ = event_study(d, h, train_fraction)
        frames.append(results.assign(horizon_h=h, threshold_usdt=threshold))
    return pd.concat(frames).reset_index().set_index(["horizon_h", "periodo", "event"])


def carry_decomposition(segment: pd.DataFrame, q: float, margin: float, fee_levels=(0, 10, 20),
                        maintenance_rate: float = .005, flip_funding: bool = False) -> pd.DataFrame:
    """E5 · Resultado final de la cobertura separado en variación del basis, funding y comisiones.

    `return_on_capital_pct` usa el capital total: spot comprado + garantía del derivado.
    Con `flip_funding` se invierte el signo de todas las tasas (escenario de funding negativo).
    """
    seg = segment.assign(funding_rate=-segment.funding_rate) if flip_funding else segment
    capital = q * seg.spot_price.iloc[0] + margin
    rows = []
    for fee in fee_levels:
        h = hedge_curve(seg, q, margin, fee, maintenance_rate).iloc[-1]
        rows.append({"fee_bps": fee, "basis_change_pnl": h.price_pnl, "funding_pnl": h.funding_pnl,
                     "fees": -h.fees, "net_pnl": h.net_pnl, "capital_usdt": capital,
                     "return_on_capital_pct": 100 * h.net_pnl / capital})
    return pd.DataFrame(rows).set_index("fee_bps")


def margin_breach_table(segment: pd.DataFrame, q: float, margins=(100, 300, 600), fee_bps: float = 10,
                        maintenance_rate: float = .005) -> pd.DataFrame:
    """E6 · Primer cruce del umbral de mantenimiento para cada garantía.

    `breach_mark_rise_pct`: subida del mark desde la entrada que cruzaría el umbral, sin funding.
    Sale de igualar margin + q·(p0 − mark) − q·p0·fee = q·mark·maintenance_rate.
    """
    p0, mark0 = segment.perp_price.iloc[0], segment.mark_price.iloc[0]
    fee = fee_bps / 10000
    rows = []
    for margin in margins:
        h = hedge_curve(segment, q, margin, fee_bps, maintenance_rate)
        first = h.index[h.margin_breach][0] if h.margin_breach.any() else pd.NaT
        breach_mark = (margin + q * p0 * (1 - fee)) / (q * (1 + maintenance_rate))
        rows.append({"margin_usdt": margin, "initial_leverage": q * p0 / margin,
                     "min_equity_usdt": h.margin_equity.min(), "first_breach_utc": first,
                     "breach_hours": int(h.margin_breach.sum()),
                     "breach_mark_rise_pct": 100 * (breach_mark / mark0 - 1),
                     "spot_pnl_at_breach_usdt": (q * (segment.spot_price.loc[first] - segment.spot_price.iloc[0])
                                                 if pd.notna(first) else np.nan)})
    return pd.DataFrame(rows).set_index("margin_usdt")


def apply_price_shock(frame: pd.DataFrame, start, pct: float) -> pd.DataFrame:
    """E6 · Escenario de estrés: multiplica los cuatro precios por (1 + pct) desde `start` (incluido)."""
    out = frame.copy()
    mask = out.index >= pd.Timestamp(start)
    out.loc[mask, PRICE_COLS] = out.loc[mask, PRICE_COLS] * (1 + pct)
    return out
