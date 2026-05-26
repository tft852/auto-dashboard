#!/usr/bin/env python3
"""
fetch_sec_financials.py

Pulls the latest annual financial data from SEC EDGAR for selected automobile
OEMs and writes a JSON file consumable by the Automobile Industry Intelligence
Dashboard.

Output: data/financials.json

SEC EDGAR API docs: https://www.sec.gov/edgar/sec-api-documentation
Rate limit: ~10 requests/second. User-Agent header required.

Run locally:
    python scripts/fetch_sec_financials.py

Designed to run on a schedule under GitHub Actions (see .github/workflows/).
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# SEC requires a descriptive User-Agent identifying the consumer.
# Replace the email with a real contact address before deploying.
USER_AGENT = "AutoDashboard research-prototype timothyftan.gh@gmail.com"

# 10-digit zero-padded CIKs. Verify at https://www.sec.gov/cgi-bin/browse-edgar
COMPANIES = {
    "Tesla":      "0001318605",
    "Ford":       "0000037996",
    "GM":         "0001467858",
    "Stellantis": "0001605484",  # 20-F filer (foreign private issuer; IFRS tags)
}

# XBRL concept tags. Tried in order — first match wins. Different filers use
# different tags depending on accounting standard and reporting era.
CONCEPT_FALLBACKS = {
    "revenue": [
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
        ("ifrs-full", "Revenue"),
    ],
    "grossProfit": [
        ("us-gaap", "GrossProfit"),
        ("ifrs-full", "GrossProfit"),
    ],
    "operatingIncome": [
        ("us-gaap", "OperatingIncomeLoss"),
        ("ifrs-full", "ProfitLossFromOperatingActivities"),
    ],
    "netIncome": [
        ("us-gaap", "NetIncomeLoss"),
        ("ifrs-full", "ProfitLoss"),
    ],
    "operatingCashFlow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ],
    "capex": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("ifrs-full",
         "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ("ifrs-full", "CashAndCashEquivalents"),
    ],
    "longTermDebt": [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
        ("ifrs-full", "NoncurrentBorrowings"),
    ],
}

# Annual-period forms across US/foreign filers
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A")


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

def fetch_json(url: str) -> dict:
    """HTTP GET → parsed JSON, with SEC-mandated User-Agent."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def latest_annual_value(facts: dict, namespace: str, concept: str):
    """Return the most recent FY value for a concept, or None."""
    try:
        units = facts["facts"][namespace][concept]["units"]
    except KeyError:
        return None

    # Prefer USD; fall back to whatever currency the filer reports in.
    series = units.get("USD") or next(iter(units.values()), None)
    if not series:
        return None

    annual = [
        x for x in series
        if x.get("fp") == "FY" and x.get("form") in ANNUAL_FORMS
    ]
    if not annual:
        return None

    annual.sort(key=lambda x: x["end"], reverse=True)
    latest = annual[0]
    return {
        "value": latest["val"],
        "fiscalYear": latest.get("fy"),
        "periodEnd": latest["end"],
        "form": latest["form"],
        "filed": latest.get("filed"),
        "currency": "USD" if "USD" in units else next(iter(units.keys())),
    }


def find_concept(facts: dict, alternatives):
    """Try each candidate XBRL tag in order."""
    for namespace, concept in alternatives:
        result = latest_annual_value(facts, namespace, concept)
        if result is not None:
            result["sourceTag"] = f"{namespace}:{concept}"
            return result
    return None


def fetch_company(name: str, cik: str) -> dict:
    print(f"  · {name:<12} (CIK {cik})", end=" ", flush=True)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    try:
        facts = fetch_json(url)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}")
        return {"name": name, "cik": cik, "error": f"HTTP {e.code}"}
    except Exception as e:
        print(f"ERROR {type(e).__name__}")
        return {"name": name, "cik": cik, "error": str(e)}

    raw = {key: find_concept(facts, alts)
           for key, alts in CONCEPT_FALLBACKS.items()}

    # Derive margins where we have both numerator and denominator
    rev = raw["revenue"]
    derived = {}
    if rev and rev["value"]:
        rev_val = rev["value"]
        if raw["grossProfit"]:
            derived["grossMargin"] = round(
                raw["grossProfit"]["value"] / rev_val * 100, 2)
        if raw["operatingIncome"]:
            derived["opMargin"] = round(
                raw["operatingIncome"]["value"] / rev_val * 100, 2)
        if raw["netIncome"]:
            derived["netMargin"] = round(
                raw["netIncome"]["value"] / rev_val * 100, 2)
        if raw["operatingCashFlow"] and raw["capex"]:
            fcf = raw["operatingCashFlow"]["value"] - raw["capex"]["value"]
            derived["freeCashFlow"] = fcf
            derived["fcfMargin"] = round(fcf / rev_val * 100, 2)

    # Net cash position (cash − long-term debt). Crude but useful.
    if raw["cash"] and raw["longTermDebt"]:
        derived["netCash"] = raw["cash"]["value"] - raw["longTermDebt"]["value"]

    found_count = sum(1 for v in raw.values() if v is not None)
    print(f"ok ({found_count}/{len(raw)} concepts, FY{rev['fiscalYear'] if rev else '?'})")

    return {
        "name": name,
        "cik": cik,
        "entityName": facts.get("entityName"),
        "raw": raw,
        "derived": derived,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"Fetching SEC EDGAR data for {len(COMPANIES)} OEMs...")
    output = {
        "_meta": {
            "source": "SEC EDGAR (data.sec.gov)",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "schemaVersion": 1,
            "companies": list(COMPANIES.keys()),
        },
        "companies": {},
    }

    for name, cik in COMPANIES.items():
        output["companies"][name] = fetch_company(name, cik)
        time.sleep(0.15)  # well under the 10 req/s SEC limit

    out_path = Path(__file__).resolve().parent.parent / "data" / "financials.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {out_path.relative_to(out_path.parent.parent)}")
    print(f"Size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
