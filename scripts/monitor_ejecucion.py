"""Monitor de condiciones de ejecución para BTC/EUR en Kraken (solo lectura, no envía órdenes).

Uso:
    python scripts/monitor_ejecucion.py --side buy --qty 0.01
    python scripts/monitor_ejecucion.py --side sell --qty 0.05 --fee-pct 0.40 --interval 10
    python scripts/monitor_ejecucion.py --side buy --qty 0.01 --iterations 1   # una sola consulta

Cada consulta descarga el libro de órdenes (--levels niveles por lado) y simula la orden
recorriendo los niveles (P02): el precio de ejecución es el VWAP e incluye el slippage.

Cada consulta se guarda en data/raw/kraken_btceur_quotes.csv. Al arrancar se reutiliza
la historia reciente del CSV, así el veredicto está disponible antes.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quantlab.p01.execution import DEFAULT_MIN_HISTORY, execution_report
from quantlab.p01.quotes import fetch_kraken_ticker, quote_metrics, validate_quote
from quantlab.p02.orderbook import fetch_kraken_book, normalize_book, simulate_market_order

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "raw" / "kraken_btceur_quotes.csv"
CSV_FIELDS = ["received_at", "best_bid", "best_ask", "last_price",
              "best_bid_volume", "best_ask_volume", "spread_bps"]


ICONS = {
    "EJECUTAR": "✅", "NORMAL": "🟡", "ESPERAR": "🔴",
    "SIN_HISTORIAL": "⏳", "PROFUNDIDAD_INSUFICIENTE": "⚠️", "DATO_NO_VALIDO": "⛔",
}


def eur(x: float, d: int = 2) -> str:
    """Formato europeo: 57.961,20 €"""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def num(x: float, d: int = 3) -> str:
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def load_history(path: Path, window: timedelta) -> deque:
    """(timestamp, spread_bps) del CSV dentro de la ventana."""
    hist: deque = deque()
    if not path.exists():
        return hist
    cutoff = datetime.now(timezone.utc) - window
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(row["received_at"])
                if ts >= cutoff:
                    hist.append((ts, float(row["spread_bps"])))
            except (KeyError, ValueError):
                continue  # fila corrupta: se ignora
    return hist


def append_csv(path: Path, quote: dict, spread_bps: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({**{k: quote.get(k) for k in CSV_FIELDS[:-1]}, "spread_bps": spread_bps})


def fetch_snapshot(qty: float, levels: int) -> tuple[dict, dict, dict]:
    """Libro (Bid/Ask, volúmenes y simulación de ambos lados) + último precio del ticker."""
    raw, received_at = fetch_kraken_book(levels=levels)
    bids, asks = normalize_book(raw)  # valida: lados vacíos, precios <= 0, libro cruzado
    last = fetch_kraken_ticker()["last_price"]
    quote = {
        "source": "kraken_public_depth+ticker", "received_at": received_at, "symbol": "BTC/EUR",
        "best_bid": float(bids.price.iloc[0]), "best_ask": float(asks.price.iloc[0]), "last_price": last,
        "best_bid_volume": float(bids.quantity_btc.iloc[0]), "best_ask_volume": float(asks.quantity_btc.iloc[0]),
        "levels": min(len(bids), len(asks)),
    }
    validate_quote(quote["best_bid"], quote["best_ask"], last)
    buy_fill, _ = simulate_market_order(bids, asks, "buy", qty)
    sell_fill, _ = simulate_market_order(bids, asks, "sell", qty)
    return quote, buy_fill, sell_fill


def render(q: dict, r: dict) -> str:
    side_txt = "COMPRAR" if r["side"] == "buy" else "VENDER"
    lines = [f"\n{q.get('received_at', '')} · {q.get('symbol', '')} · Kraken"]
    if r["verdict"] == "DATO_NO_VALIDO":
        lines.append(f"Veredicto: {ICONS['DATO_NO_VALIDO']} DATO NO VÁLIDO · {r['reason']}")
        return "\n".join(lines)
    hist = (f"mediana: {num(r['spread_median_bps'])} bps · p90: {num(r['spread_p90_bps'])} bps "
            f"(n={r['history_n']})" if r["spread_median_bps"] is not None
            else f"historial insuficiente (n={r['history_n']})")
    lado = "Ask" if r["side"] == "buy" else "Bid"
    direction = "subir" if r["side"] == "buy" else "bajar"
    if r["depth_ok"] is None:
        depth = "sin dato"
    elif r.get("uses_book"):
        depth = (f"✅ cubierta en {r['levels_used']} nivel(es) de {q.get('levels', '?')} recibidos"
                 if r["depth_ok"] else
                 f"⚠️ el snapshot ({q.get('levels', '?')} niveles) no cubre {num(r['qty'])} BTC en entrada y salida")
    else:
        depth = (f"{'✅' if r['depth_ok'] else '⚠️'} {num(r['qty'])} BTC "
                 f"{'≤' if r['depth_ok'] else '>'} {num(r['available_at_best'])} BTC disponibles al {lado}")
    precio = f"VWAP, mejor {lado} {eur(q['best_ask'] if r['side'] == 'buy' else q['best_bid'])}" if r.get("uses_book") else lado
    lines += [
        f"Bid {eur(q['best_bid'])} · "
        f"Ask {eur(q['best_ask'])} · Mid {eur(r['mid_price'])}",
        f"Spread {eur(r['spread'])} ({num(r['spread_bps'])} bps) · {hist}",
        "",
        f"Orden: {side_txt} {num(r['qty'])} BTC",
        f"  Precio de ejecución:  {eur(r['exec_price'])} ({precio})",
        f"  Importe:              {eur(r['notional'])}",
        f"  Comisión ({num(r['fee_rate']*100, 2)} %):    {eur(r['fee'])}",
        f"  Coste spread vs mid:  {eur(r['spread_cost_vs_mid'], 4)}",
        f"  Slippage:             {eur(r['slippage_cost'], 4)} ({num(r['slippage_bps'])} bps)",
        f"  Ida y vuelta:         {eur(r['round_trip_market'], 4)} spread+slippage + {eur(r['round_trip_fees'])} comisiones"
        f" = {eur(r['round_trip_total'])}",
        f"  Punto de equilibrio:  el precio debe {direction} {eur(r['breakeven_move'])} "
        f"({num(r['breakeven_move_pct'], 2)} %) hasta {eur(r['breakeven_price'])}",
        f"  Profundidad:          {depth}",
        "",
        f"Veredicto: {ICONS[r['verdict']]} {r['verdict']} · {r['reason']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # emojis en la consola de Windows
        except AttributeError:
            pass

    ap = argparse.ArgumentParser(description="Monitor de condiciones de ejecución (Kraken BTC/EUR). No envía órdenes.")
    ap.add_argument("--side", choices=["buy", "sell"], required=True, help="buy = comprar, sell = vender")
    ap.add_argument("--qty", type=float, required=True, help="Cantidad en BTC")
    ap.add_argument("--fee-pct", type=float, default=0.80, help="Comisión por pata en %% (def. 0,80 = Kraken Pro nivel 1 taker)")
    ap.add_argument("--interval", type=float, default=5, help="Segundos entre consultas (def. 5)")
    ap.add_argument("--window", type=float, default=300, help="Ventana de historia en segundos (def. 300 = 5 min)")
    ap.add_argument("--min-history", type=int, default=DEFAULT_MIN_HISTORY, help="Observaciones mínimas para juzgar el spread")
    ap.add_argument("--iterations", type=int, default=0, help="Número de consultas (0 = sin fin, Ctrl+C para salir)")
    ap.add_argument("--levels", type=int, default=100, help="Niveles por lado del libro (def. 100, máx. 500)")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV donde se guardan las consultas")
    args = ap.parse_args(argv)

    window = timedelta(seconds=args.window)
    history = load_history(args.csv, window)
    print(f"Historia cargada: {len(history)} observaciones de los últimos {args.window:.0f} s. Ctrl+C para salir.")

    i = 0
    try:
        while args.iterations == 0 or i < args.iterations:
            i += 1
            now = datetime.now(timezone.utc)
            while history and history[0][0] < now - window:
                history.popleft()
            try:
                quote, buy_fill, sell_fill = fetch_snapshot(args.qty, args.levels)
            except Exception as exc:  # red caída, API con error o dato inválido
                report = execution_report({}, args.side, args.qty, args.fee_pct / 100)
                report["reason"] = f"{type(exc).__name__}: {exc}"
                print(render({"received_at": now.isoformat(), "symbol": "BTC/EUR"}, report))
            else:
                report = execution_report(quote, args.side, args.qty, args.fee_pct / 100,
                                          [s for _, s in history], args.min_history,
                                          buy_fill=buy_fill, sell_fill=sell_fill)
                print(render(quote, report))
                spread_bps = quote_metrics(quote["best_bid"], quote["best_ask"], quote["last_price"])["spread_bps"]
                append_csv(args.csv, quote, spread_bps)
                history.append((datetime.fromisoformat(quote["received_at"]), spread_bps))
            if args.iterations == 0 or i < args.iterations:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
