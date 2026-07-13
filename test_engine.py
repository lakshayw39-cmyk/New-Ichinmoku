"""Engine tests — run with: python test_engine.py"""
import numpy as np
import pandas as pd
import shiomega_core as sc
import shiomega_engine as se

fails = []
def ok(cond, msg):
    if not cond:
        fails.append(msg); print("FAIL:", msg)

# ---------- 1. signals fire on engineered reversals, both sides ------------ #
for side in ("long", "short"):
    hits = 0
    for seed in range(1, 21):
        d = se.prepare(sc.gen_series(side, seed))
        col = "long_signal" if side == "long" else "short_signal"
        if d[col].any():
            hits += 1
            i = int(np.flatnonzero(d[col].to_numpy())[0])
            # trigger must be a fresh chikou break with a recent qualifying cross
            bcol = "chikou_up_fresh" if side == "long" else "chikou_dn_fresh"
            ok(bool(d[bcol].iloc[i]), f"{side} {seed}: signal without fresh break")
            bars = d["bars_since_gold" if side == "long" else "bars_since_death"].iloc[i]
            ok(bars <= se.CROSS_MAX_AGE, f"{side} {seed}: cross too old ({bars})")
            # protective stop on the correct side
            stop = d["long_stop" if side == "long" else "short_stop"].iloc[i]
            cl = d["Close"].iloc[i]
            ok((stop < cl) if side == "long" else (stop > cl),
               f"{side} {seed}: stop on wrong side")
    print(f"{side}: signal fired in {hits}/20 engineered tapes")
    ok(hits >= 15, f"{side}: signals too rare ({hits}/20)")

# ---------- 2. scanner <-> backtest gate parity ----------------------------- #
d = se.prepare(sc.gen_series("long", 7))
sig_bars = np.flatnonzero(d["long_signal"].to_numpy())
ok(len(sig_bars) > 0, "no signal on default tape")
# scanner truncated at each signal bar must report TRIGGERED LONG
i = int(sig_bars[0])
res = se.scan_last_bar("SYN", sc.gen_series("long", 7).iloc[: i + 1])
ok(res is not None and res["status"] == "TRIGGERED" and res["side"] == "LONG",
   "scanner does not agree with backtest gate on the signal bar")
# one bar earlier must NOT be triggered
res_prev = se.scan_last_bar("SYN", sc.gen_series("long", 7).iloc[:i])
ok(res_prev is None or res_prev["status"] != "TRIGGERED",
   "scanner triggered one bar early — look-ahead or gate mismatch")

# ---------- 3. portfolio backtest on synthetic universe --------------------- #
# reverse_tail=True so positions actually close (clean trends never exit)
data = {f"L{k}": sc.gen_series("long", k, reverse_tail=True) for k in (7, 8, 9)} | \
       {f"S{k}": sc.gen_series("short", k, reverse_tail=True) for k in (7, 9)}
trades, equity, summ = se.backtest_portfolio(data)
ok(len(trades) >= 3, f"too few trades ({len(trades)})")
ok((trades["side"] == "SHORT").any() and (trades["side"] == "LONG").any(),
   "both sides should trade")

# 3a. no look-ahead: entry_date strictly after signal_date, fill = that bar's open
for _, t in trades.iterrows():
    ok(t["entry_date"] > t["signal_date"], f"{t['ticker']}: entry not after signal")
    df = data[t["ticker"]]
    nxt_open = round(float(df.iloc[df.index.get_loc(pd.Timestamp(t["signal_date"])) + 1]["Open"]), 4)
    ok(abs(nxt_open - t["entry_price"]) < 1e-4,
       f"{t['ticker']}: entry fill is not next bar open ({nxt_open} vs {t['entry_price']})")

# 3b. cash reconciliation to the cent: final equity = capital + sum(net_pnl)
#     (only exact when no positions remain open at the end)
if len(equity) and equity["open_positions"].iloc[-1] == 0:
    ok(abs(equity["equity"].iloc[-1] - (se.CAPITAL + trades["net_pnl"].sum())) < 0.01,
       "final equity does not reconcile with trade P&L")
else:
    print("note: open positions at end — reconciliation via MTM only")

# 3c. one position per underlier: no overlapping intervals per ticker
for tkr, g in trades.groupby("ticker"):
    g = g.sort_values("entry_date")
    prev_exit = None
    for _, t in g.iterrows():
        if prev_exit is not None:
            ok(t["entry_date"] >= prev_exit, f"{tkr}: overlapping trades")
        prev_exit = t["exit_date"]

# 3d. exit reasons only from the defined set; bars_held positive
ok(set(trades["exit_reason"]) <= {"HARD_STOP", "KIJUN_TRAIL"}, "unknown exit reason")
ok((trades["bars_held"] >= 1).all(), "bars_held must be >= 1")

# ---------- 4. deterministic stop / trail micro-cases ----------------------- #
def make_df(rows):
    idx = pd.bdate_range("2024-01-02", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])

# hand-build a prepared frame to drive the exit logic directly:
# monkeypatch prepare() to inject a single known signal + stop, then verify fills.
base = sc.gen_series("long", 7, reverse_tail=True)
d7 = se.prepare(base)
i_sig = int(np.flatnonzero(d7["long_signal"].to_numpy())[0])
stop_val = float(d7["long_stop"].iloc[i_sig])

# gap-through-stop case: force next bars to gap below the stop
crash = base.copy()
j = i_sig + 3
crash.iloc[j:, :] = crash.iloc[j:, :] * 0.0 + stop_val * 0.90  # flat tape below stop
crash.iloc[j, 0] = stop_val * 0.92                              # open below stop
tr2, eq2, _ = se.backtest_portfolio({"CRASH": crash})
if len(tr2):
    t = tr2.iloc[0]
    ok(t["exit_reason"] == "HARD_STOP", "gap case: expected HARD_STOP")
    ok(t["exit_price"] <= t["stop"] + 1e-9, "gap fill must be at/below stop for longs")

# commission sanity: net = gross - 2*max(1, shares*0.005)
t0 = trades.iloc[0]
sgn = 1 if t0["side"] == "LONG" else -1
gross = sgn * (t0["exit_price"] - t0["entry_price"]) * t0["shares"]
comm = max(1.0, t0["shares"] * 0.005)
ok(abs(t0["net_pnl"] - (gross - 2 * comm)) < 0.01, "commission accounting")

# ---------- 5. summary sanity ------------------------------------------------ #
ok(0 <= summ["win_rate"] <= 1, "win rate bounds")
ok(summ["max_dd"] >= 0, "drawdown sign")
ok(np.isfinite(summ["net_pnl"]), "net pnl finite")

print(f"\n{'ALL ENGINE TESTS PASSED' if not fails else str(len(fails)) + ' FAILURES'}")
raise SystemExit(1 if fails else 0)
