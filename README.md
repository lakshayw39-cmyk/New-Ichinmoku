# 潮目 Shiomega — Daily Ichimoku Scanner, Backtest & Dashboard

> **潮目が変わる — "the tide has turned."**
> The Tenkan/Kijun cross is only the *heads-up*. The clean **Chikou breakout**
> is the *trigger*. This repo turns that discretionary Ichimoku setup into a
> daily screener, a portfolio backtest, and a live Streamlit dashboard — all
> driven by **one shared engine** so the three can never disagree.

![timeframe](https://img.shields.io/badge/timeframe-daily-E2B23F) ![ichimoku](https://img.shields.io/badge/ichimoku-9%2F26%2F52-4EA3E8)

---

## What's in here

| File | Role |
|---|---|
| `app.py` | **Streamlit dashboard** — four tabs: annotated Setup (with live-ticker mode), Signals board, Backtest analyzer, Rules. |
| `shiomega_engine.py` | The **shared signal engine** — vectorized gates, the last-bar scanner, and the event-driven portfolio backtest. |
| `shiomega_core.py` | Ichimoku math, setup detection for the chart, tolerant CSV normalisation, metrics, demo data. |
| `shiomega_daily_screener.py` | Standalone **scanner** → writes `shiomega_daily_signals.csv`. |
| `shiomega_daily_backtest.py` | Standalone **portfolio backtest** → writes `shiomega_daily_trades.csv`. |
| `test_core.py`, `test_engine.py` | Unit tests (setup sequencing, no look-ahead, cash reconciliation, gap-aware stops). |
| `sample_data/` | Demo CSVs so the dashboard shows something before you run the scripts. |

The dashboard **is** the scanner and backtest — the same `shiomega_engine`
functions power the in-browser **Live scan** / **Live backtest** buttons and the
standalone scripts. Run the scripts on a schedule for the full universe, or click
the buttons for an ad-hoc ticker list.

---

## Deploy to Streamlit Community Cloud (free)

1. **Push this folder to a GitHub repo** (public or private):
   ```bash
   git init
   git add .
   git commit -m "Shiomega daily dashboard"
   git branch -M main
   git remote add origin https://github.com/<you>/shiomega-daily.git
   git push -u origin main
   ```
2. Go to **[share.streamlit.io](https://share.streamlit.io)** → **New app** →
   pick the repo, branch `main`, main file **`app.py`** → **Deploy**.
3. Streamlit installs `requirements.txt` automatically and serves the app at
   `https://<you>-shiomega-daily.streamlit.app`. The night-sea theme comes from
   `.streamlit/config.toml`.

> **Live mode & data:** the *Live ticker / Live scan / Live backtest* features
> pull daily bars from Yahoo via `yfinance`. Streamlit Cloud allows this over the
> public internet. If you self-host behind a strict firewall, allow
> `query1.finance.yahoo.com` / `query2.finance.yahoo.com`, or just use the
> **Upload CSV** / **Demo data** paths (no network needed).

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Generate the CSVs the dashboard reads

```bash
# Scanner — last closed daily bar across the liquid NA universe
python shiomega_daily_screener.py                       # full universe
python shiomega_daily_screener.py --tickers AAPL MSFT SHOP.TO
python shiomega_daily_screener.py --limit 300 --out shiomega_daily_signals.csv

# Portfolio backtest — 10y by default
python shiomega_daily_backtest.py                       # full universe
python shiomega_daily_backtest.py --tickers AAPL MSFT SU.TO --period 5y
```

Drop the resulting `shiomega_daily_signals.csv` / `shiomega_daily_trades.csv`
onto the **Signals board** / **Backtest analyzer** tabs — or commit them to the
repo and the deployed app will read them from **Upload CSV**.

The backtest analyzer **matches column names tolerantly** (`pnl`/`net_pnl`,
`side`/`direction`, `entry_price`/`entry`, …) and derives R-multiples from the
stop distance when an `r_multiple` column is absent, so hand-edited or
differently-named logs still load.

---

## The strategy

**Long (shorts mirrored):**

| Gate | Condition |
|---|---|
| L0 | Prior **downtrend** — price below Kijun & Kumo, Chikou below the candles. |
| L1 | Tenkan **gold-crosses** Kijun while price closes **below the Kumo**, within the last **40** daily bars — *the heads-up.* |
| L2 | Tenkan sloping **up** over the last 3 bars. |
| L3 | **Trigger:** close breaks cleanly **above** the 11-bar high window around the Chikou position — *fresh*, not halfway, not inside the candles. |
| L4 | Regime — close above **SMA(50)**. |

**Entries & exits**
- Signal on the daily **close** → fill at the **next bar's open** (no look-ahead).
- **Hard stop:** `min(Kijun, 10-bar swing low) − 0.1×ATR14` (mirrored for shorts); intrabar and gap-aware.
- **Kijun trail:** a close back through the Kijun against the position exits at the next open — *"ride while the Kijun is respected."*
- Conservative tie-break: the stop resolves before any target on the same bar.

**Portfolio:** $100,000 · $5,000/position · max 20 concurrent · one position per
underlier · $0.005/share commission ($1 min), both sides · universe =
NYSE / NASDAQ / TSX, market cap > $5B.

**Stand aside** when the Chikou is stuck inside the candles, the market is
ranging, or the cross fired deep inside the cloud. *No momentum, no trade.*

---

## Tests

```bash
python test_core.py     # Ichimoku, setup sequencing, CSV mapping, metrics
python test_engine.py   # gate parity, no look-ahead, gap stops, cash reconciliation
```

---

*Demo data is illustrative shape only, not results. Backtests are hypothetical
and are not investment advice.*
