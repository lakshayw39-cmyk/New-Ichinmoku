#!/usr/bin/env python3
"""
Shiomega Daily — portfolio backtest.

Runs the event-driven Shiomega backtest across the liquid NA universe and
writes `shiomega_daily_trades.csv` — the file the dashboard's Backtest
Analyzer reads — plus `shiomega_daily_equity.csv`.

    python shiomega_daily_backtest.py                      # full universe
    python shiomega_daily_backtest.py --tickers AAPL MSFT SU.TO
    python shiomega_daily_backtest.py --period 5y --limit 250

$100K capital · $5K/position · max 20 concurrent · one position per underlier
· next-bar-open fills · $0.005/share commission ($1 min) both sides.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from shiomega_engine import (
    backtest_portfolio, CAPITAL, PER_TRADE, MAX_POSITIONS,
)
from shiomega_daily_screener import build_universe, MAX_WORKERS


def fetch_one(ticker: str, period: str) -> tuple[str, pd.DataFrame | None]:
    try:
        df = yf.download(ticker, period=period, interval="1d",
                         auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return ticker, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return ticker, df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:                             # noqa: BLE001
        return ticker, None


def _fmt(summary: dict) -> str:
    def line(k, v):
        return f"  {k:<18} {v}"
    L = ["── Shiomega daily backtest ─────────────────────"]
    L.append(line("Trades", summary.get("trades", 0)))
    if "final_equity" in summary:
        L.append(line("Final equity", f"${summary['final_equity']:,.0f}"))
        L.append(line("Total return", f"{summary['total_return']*100:,.1f}%"))
        L.append(line("CAGR", f"{summary['cagr']*100:,.1f}%" if summary.get("cagr") else "—"))
        L.append(line("Sharpe", f"{summary['sharpe']:.2f}" if summary.get("sharpe") else "—"))
        L.append(line("Max drawdown", f"{summary['max_dd']*100:,.1f}%"))
    if "win_rate" in summary:
        pf = summary["profit_factor"]
        L.append(line("Net P&L", f"${summary['net_pnl']:,.0f}"))
        L.append(line("Win rate", f"{summary['win_rate']*100:,.1f}%"))
        L.append(line("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}"))
        L.append(line("Expectancy", f"${summary['expectancy']:,.2f}"))
        L.append(line("Expectancy (R)",
                      f"{summary['expectancy_r']:.2f}R" if summary.get("expectancy_r") else "—"))
        L.append(line("Avg bars held", f"{summary['avg_bars']:.1f}"))
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Shiomega daily portfolio backtest")
    ap.add_argument("--tickers", nargs="*", help="explicit ticker list")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--period", default="10y", help="yfinance history period")
    ap.add_argument("--out", default="shiomega_daily_trades.csv")
    ap.add_argument("--equity-out", default="shiomega_daily_equity.csv")
    args = ap.parse_args()

    universe = args.tickers if args.tickers else build_universe(args.limit)
    print(f"[download] {len(universe)} tickers · {args.period} …", file=sys.stderr)

    data: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_one, t, args.period): t for t in universe}
        for k, fut in enumerate(as_completed(futs), 1):
            ticker, df = fut.result()
            if df is not None:
                data[ticker] = df
            if k % 50 == 0:
                print(f"  … {k}/{len(universe)}", file=sys.stderr)

    print(f"[backtest] {len(data)} tickers with data …", file=sys.stderr)
    trades, equity, summary = backtest_portfolio(
        data, capital=CAPITAL, per_trade=PER_TRADE, max_positions=MAX_POSITIONS,
        progress=lambda f, m: None,
    )
    trades.to_csv(args.out, index=False)
    equity.to_csv(args.equity_out)
    print(_fmt(summary), file=sys.stderr)
    print(f"\n[done] {len(trades)} trades -> {args.out} · equity -> {args.equity_out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
