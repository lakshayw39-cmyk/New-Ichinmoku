"""Unit tests for shiomega_core — run with: python test_core.py"""
import io
import numpy as np
import pandas as pd
import shiomega_core as sc

fails = []
def ok(cond, msg):
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)

# ---- pandas 3.0 boolean-shift regression guard --------------------------- #
s = pd.Series([True, False, True])
assert (~s.shift(1).astype(bool)).dtype == bool  # would raise on object dtype

# ---- 1. Setup sequencing on both sides across seeds ----------------------- #
for side in ("long", "short"):
    found = 0
    for seed in range(1, 31):
        bars = sc.gen_series(side, seed)
        st = sc.find_setup(bars, side)
        if st["trigger"] is None:
            continue
        found += 1
        c, b, d = st["cross"], st["trigger"], st["df"]
        ok(c <= b, f"{side} {seed}: cross after trigger")
        ok(b - c <= sc.CROSS_MAX_AGE, f"{side} {seed}: gap too wide")
        if side == "long":
            ok(d["Close"].iloc[c] < d["cloud_bot"].iloc[c], f"{side} {seed}: cross not below kumo")
            ok(bool(sc.chikou_break_up(d).iloc[b]), f"{side} {seed}: trigger not a chikou break")
            ok(st["stop"] < d["Close"].iloc[b], f"{side} {seed}: stop above entry")
        else:
            ok(d["Close"].iloc[c] > d["cloud_top"].iloc[c], f"{side} {seed}: cross not above kumo")
            ok(bool(sc.chikou_break_down(d).iloc[b]), f"{side} {seed}: trigger not a chikou breakdown")
            ok(st["stop"] > d["Close"].iloc[b], f"{side} {seed}: stop below entry")
    print(f"{side}: setup found in {found}/30 seeds")
    ok(found >= 25, f"{side}: setups too rare ({found}/30)")

# default seed used by the app must always yield a scene
for side in ("long", "short"):
    ok(sc.find_setup(sc.gen_series(side, 7), side)["trigger"] is not None,
       f"default seed produces no {side} setup")

# ---- 2. Tolerant trade normalisation + metric invariants ------------------ #
csv = io.StringIO(
    "ticker,side,entry_date,exit_date,entry_price,exit_price,shares,stop,net_pnl,r_multiple,exit_reason,bars_held\n"
    "AAA,LONG,2024-01-02,2024-02-15,100,110,50,95,500,2.0,KIJUN_TRAIL,31\n"
    "BBB,SHORT,2024-02-01,2024-02-20,200,210,25,208,-250,-1.25,HARD_STOP,13\n"
    "CCC,LONG,2024-03-01,2024-05-10,50,60,100,46,1000,2.5,KIJUN_TRAIL,49\n")
t = sc.normalise_trades(pd.read_csv(csv))
ok(len(t) == 3, "trades parsed")
m = sc.compute_metrics(t)
ok(abs(m["net"] - 1250) < 1e-9, "net pnl")
ok(abs(m["win_rate"] - 2 / 3) < 1e-9, "win rate")
ok(abs(m["profit_factor"] - 6.0) < 1e-9, "profit factor")
ok(abs(m["curve"].iloc[-1] - 101250) < 1e-9, "equity endpoint reconciles")
ok(abs(m["expectancy_r"] - (2.0 - 1.25 + 2.5) / 3) < 1e-9, "expectancy R")
ok(m["long_n"] == 2 and m["short_n"] == 1, "side split")
ok(m["reasons"]["KIJUN_TRAIL"] == 2 and m["reasons"]["HARD_STOP"] == 1, "reason counts")
ok(m["cagr"] is not None and m["cagr"] > 0, "cagr from dates")
ok(abs(m["max_dd"] - 250 / 100500) < 1e-9, "max drawdown")

# ---- 3. Derived pnl / R when columns absent, header drift ----------------- #
csv2 = io.StringIO("Symbol,Direction,Open Date,Close Date,Entry,Exit,Qty,Initial Stop\n"
                   "DDD,short,2024-01-05,2024-01-25,80,72,60,84\n")
t2 = sc.normalise_trades(pd.read_csv(csv2))
ok(len(t2) == 1, "derived trade parsed")
ok(abs(t2["pnl"].iloc[0] - (80 - 72) * 60) < 1e-9, "pnl derived side-aware")
ok(abs(t2["r"].iloc[0] - ((80 - 72) * 60) / (4 * 60)) < 1e-9, "r derived from stop")

# ---- 4. Signals normalisation --------------------------------------------- #
sig = sc.normalise_signals(sc.demo_signals())
ok((sig["status"] == "TRIGGERED").sum() == 3 and (sig["status"] == "WATCHLIST").sum() == 3,
   "signal tiers")
ok(sig.loc[sig.ticker == "NVAX", "risk_pct"].iloc[0] == 7.8, "signal numerics")

# ---- 5. Demo trades run cleanly through the full metric pipeline ---------- #
dm = sc.compute_metrics(sc.normalise_trades(sc.demo_trades()))
ok(dm["n"] == 120, "demo size")
ok(np.isfinite(dm["net"]) and 0 < dm["win_rate"] < 1, "demo metrics sane")
ok(len(dm["r_vals"]) == 120, "demo R values complete")

print(f"\n{'ALL TESTS PASSED' if not fails else str(len(fails)) + ' FAILURES'}")
raise SystemExit(1 if fails else 0)
