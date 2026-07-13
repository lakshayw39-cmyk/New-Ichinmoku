#!/usr/bin/env python3
"""
Shiomega Daily — screener.

Scans the liquid North-American universe (NYSE / NASDAQ / TSX, market cap
> $5B) for the Shiomega setup on the most recent CLOSED daily bar and writes
`shiomega_daily_signals.csv` — the file the dashboard's Signals board reads.

    python shiomega_daily_screener.py                 # full universe
    python shiomega_daily_screener.py --tickers AAPL MSFT SHOP.TO
    python shiomega_daily_screener.py --limit 300 --out signals.csv

Universe construction uses yfinance EquityQuery/screen; if that endpoint is
unavailable it falls back to a bundled large-cap list so the script still runs.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from shiomega_engine import scan_last_bar

MIN_MKT_CAP = 5_000_000_000
LOOKBACK = "2y"           # enough daily history for 52-period spans + SMA50
MAX_WORKERS = 12

FALLBACK_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD",
    "NFLX", "CRM", "ADBE", "COST", "PEP", "QCOM", "TXN", "INTC", "CSCO",
    "ORCL", "IBM", "UBER", "PYPL", "SHOP", "MRNA", "ABNB", "PLTR", "SNOW",
    "RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "CVE.TO",
    "SHOP.TO", "CP.TO", "CNR.TO", "BAM.TO", "MFC.TO", "T.TO", "BCE.TO",
]


def build_universe(limit: int | None) -> list[str]:
    """Large-cap NYSE/NASDAQ/TSX via EquityQuery; fall back on any failure."""
    syms: set[str] = set()
    try:
        from yfinance import EquityQuery as Eq
        for exch, suffix in (("NMS", ""), ("NYQ", ""), ("TOR", ".TO")):
            q = Eq("and", [
                Eq("gt", ["intradaymarketcap", MIN_MKT_CAP]),
                Eq("eq", ["exchange", exch]),
            ])
            offset = 0
            while True:
                res = yf.screen(q, offset=offset, size=250, sortField="intradaymarketcap",
                                sortAsc=False)
                quotes = (res or {}).get("quotes", [])
                if not quotes:
                    break
                for row in quotes:
                    sym = row.get("symbol")
                    if sym:
                        syms.add(sym if not suffix or sym.endswith(suffix) else sym + suffix)
                offset += 250
                if offset >= 1000:      # politeness cap per exchange
                    break
    except Exception as e:                        # noqa: BLE001
        print(f"[universe] EquityQuery unavailable ({e}); using fallback list.",
              file=sys.stderr)
    tickers = sorted(syms) if syms else list(FALLBACK_TICKERS)
    return tickers[:limit] if limit else tickers


def fetch_one(ticker: str) -> tuple[str, pd.DataFrame | None]:
    try:
        df = yf.download(ticker, period=LOOKBACK, interval="1d",
                         auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return ticker, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return ticker, df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:                             # noqa: BLE001
        return ticker, None


def main() -> None:
    ap = argparse.ArgumentParser(description="Shiomega daily screener")
    ap.add_argument("--tickers", nargs="*", help="explicit ticker list")
    ap.add_argument("--limit", type=int, default=None, help="cap universe size")
    ap.add_argument("--out", default="shiomega_daily_signals.csv")
    args = ap.parse_args()

    universe = args.tickers if args.tickers else build_universe(args.limit)
    print(f"[scan] {len(universe)} tickers …", file=sys.stderr)

    hits: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_one, t): t for t in universe}
        for k, fut in enumerate(as_completed(futs), 1):
            ticker, df = fut.result()
            if df is not None:
                res = scan_last_bar(ticker, df)
                if res:
                    hits.append(res)
                    print(f"  {res['status']:10} {res['side']:5} {ticker}", file=sys.stderr)
            if k % 50 == 0:
                print(f"  … {k}/{len(universe)}", file=sys.stderr)

    cols = ["ticker", "status", "side", "date", "close", "entry", "stop",
            "risk_pct", "bars_since_cross"]
    out = pd.DataFrame(hits, columns=cols)
    order = {"TRIGGERED": 0, "WATCHLIST": 1}
    if len(out):
        out = out.sort_values(
            ["status", "risk_pct"],
            key=lambda s: s.map(order) if s.name == "status" else s,
        )
    out.to_csv(args.out, index=False)
    trig = int((out["status"] == "TRIGGERED").sum()) if len(out) else 0
    watch = int((out["status"] == "WATCHLIST").sum()) if len(out) else 0
    print(f"[done] {trig} triggered · {watch} watchlist -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
