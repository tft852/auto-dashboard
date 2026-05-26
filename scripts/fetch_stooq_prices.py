#!/usr/bin/env python3
"""
fetch_stooq_prices.py

Pulls daily price history for tracked auto OEMs from Stooq, resamples to
month-end closes, and indexes each series to 100 at January 2020. Output is
consumed by the dashboard via src/adapters/stockPricesAdapter.js.

Stooq CSV endpoint:
    https://stooq.com/q/d/l/?s={ticker}&d1=YYYYMMDD&d2=YYYYMMDD&i=d

No API key, no rate limit advertised. Be courteous: small sleep between calls.

Run locally:
    python scripts/fetch_stooq_prices.py
"""

import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

USER_AGENT = "AutoDashboard research-prototype timothyftan.gh@gmail.com"

# Tracked tickers. Where a US ADR exists with reasonable liquidity, prefer it;
# otherwise use the home-market primary listing. Mixed currencies are fine —
# each series is indexed independently so absolute currency level doesn't matter.
TICKERS = {
    "Toyota":     "tm.us",       # NYSE ADR (USD)
    "Volkswagen": "vow3.de",     # Frankfurt VOW3 (EUR)
    "Stellantis": "stla.us",     # NYSE (USD) — post-2021 merger
    "Ford":       "f.us",        # NYSE (USD)
    "GM":         "gm.us",       # NYSE (USD) — post-2009 reorg
    "Tesla":      "tsla.us",     # NASDAQ (USD)
    "BYD":        "1211.hk",     # HKEX (HKD)
    "Hyundai":    "hymtf.us",    # OTC ADR (USD) — KRX 005380 not always on Stooq
    "BMW":        "bmw.de",      # Frankfurt (EUR)
}

START_DATE = "20200101"   # Index base = Jan 2020 (matches existing dashboard)
INDEX_BASE = 100.0


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------

def fetch_csv(ticker: str, start: str, end: str) -> str:
    url = f"https://stooq.com/q/d/l/?s={ticker}&d1={start}&d2={end}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_csv(csv_text: str):
    """
    Parse Stooq CSV. Validates that it looks like CSV rather than an error page.
    Returns list of {date: 'YYYY-MM-DD', close: float}.
    """
    text = csv_text.strip()
    if not text or text.lower().startswith("<") or "no data" in text.lower():
        raise ValueError("Empty or error response from Stooq")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")

    # Stooq headers are: Date,Open,High,Low,Close,Volume
    required = {"Date", "Close"}
    if not required.issubset(set(reader.fieldnames)):
        raise ValueError(f"Unexpected CSV columns: {reader.fieldnames}")

    rows = []
    for r in reader:
        try:
            rows.append({"date": r["Date"], "close": float(r["Close"])})
        except (ValueError, KeyError):
            continue  # skip rows with bad values

    if not rows:
        raise ValueError("CSV had headers but no usable data rows")
    return rows


def month_end_closes(daily_rows):
    """Pick the LAST trading day's close for each calendar month."""
    by_month = defaultdict(list)
    for r in daily_rows:
        month = r["date"][:7]  # 'YYYY-MM'
        by_month[month].append(r)

    out = []
    for month in sorted(by_month.keys()):
        # rows in original order; date is YYYY-MM-DD so lexical sort works
        last = sorted(by_month[month], key=lambda r: r["date"])[-1]
        out.append({"date": month, "close": last["close"]})
    return out


def index_to_100(monthly_rows, base_value: float):
    """Convert close prices to indexed series with base = 100."""
    if base_value == 0:
        raise ValueError("Base value is zero; cannot index")
    return [
        {"date": r["date"], "indexed": round(r["close"] / base_value * INDEX_BASE, 2)}
        for r in monthly_rows
    ]


def fetch_company(name: str, ticker: str, start: str, end: str) -> dict:
    print(f"  · {name:<12} ({ticker:<10})", end=" ", flush=True)
    try:
        csv_text = fetch_csv(ticker, start, end)
        daily = parse_csv(csv_text)
        monthly = month_end_closes(daily)
        if not monthly:
            raise ValueError("No monthly data after resampling")

        base = monthly[0]["close"]
        indexed = index_to_100(monthly, base)

        last_close = monthly[-1]["close"]
        last_indexed = indexed[-1]["indexed"]
        print(f"ok ({len(monthly)} months, last close {last_close:.2f}, "
              f"indexed {last_indexed:.0f})")

        return {
            "ticker": ticker,
            "monthsAvailable": len(monthly),
            "firstMonth": monthly[0]["date"],
            "lastMonth": monthly[-1]["date"],
            "baseClose": base,
            "lastClose": last_close,
            "lastIndexed": last_indexed,
            "series": indexed,
        }
    except Exception as e:
        print(f"FAILED — {type(e).__name__}: {e}")
        return {"ticker": ticker, "error": str(e)}


# ---------------------------------------------------------------------------
# Dashboard-shape transformation
# ---------------------------------------------------------------------------

def to_dashboard_shape(companies: dict):
    """
    Reshape from per-company {date, indexed} to per-date {date, Toyota, Ford...}
    matching the existing stockPricesIndexed array shape in App.jsx.
    """
    all_months = set()
    for c in companies.values():
        if "series" in c:
            for row in c["series"]:
                all_months.add(row["date"])

    result = []
    for month in sorted(all_months):
        entry = {"date": month}
        for name, c in companies.items():
            if "series" not in c:
                continue
            match = next((r for r in c["series"] if r["date"] == month), None)
            if match:
                entry[name] = match["indexed"]
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    print(f"Fetching Stooq prices for {len(TICKERS)} OEMs "
          f"({START_DATE} → {today})...")

    companies = {}
    for name, ticker in TICKERS.items():
        companies[name] = fetch_company(name, ticker, START_DATE, today)
        time.sleep(0.5)  # courtesy delay

    successful = sum(1 for c in companies.values() if "series" in c)

    output = {
        "_meta": {
            "source": "Stooq (stooq.com)",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "schemaVersion": 1,
            "indexBase": "2020-01 = 100",
            "resampling": "month-end close",
            "tickersAttempted": len(TICKERS),
            "tickersSuccessful": successful,
            "tickers": {name: c["ticker"] for name, c in companies.items()},
        },
        "perCompany": companies,                       # debug detail
        "dashboardSeries": to_dashboard_shape(companies),  # what the UI reads
    }

    out_path = Path(__file__).resolve().parent.parent / "data" / "stocks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {out_path.relative_to(out_path.parent.parent)}")
    print(f"Successful: {successful}/{len(TICKERS)} tickers")
    print(f"Size: {out_path.stat().st_size:,} bytes")

    if successful == 0:
        print("\nERROR: no tickers succeeded. Failing build.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
