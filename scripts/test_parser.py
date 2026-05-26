"""
test_parser.py — validate the SEC parsing logic against a mocked response
that matches the documented data.sec.gov companyfacts API shape.

This is an offline test so it can run in any environment, including the
sandbox where data.sec.gov is not allowlisted. The same parsing code runs
unchanged against the live API on a GitHub Actions runner.
"""

import json
import sys
from pathlib import Path

# Import functions from the real script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fetch_sec_financials import (  # noqa: E402
    find_concept, latest_annual_value, CONCEPT_FALLBACKS, fetch_company
)

# Realistic mock for Tesla based on the documented EDGAR API shape.
# Real values approximated from public 10-Ks.
MOCK_TESLA_FACTS = {
    "cik": 1318605,
    "entityName": "Tesla, Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {"start": "2022-01-01", "end": "2022-12-31", "val": 81462000000,
                         "accn": "0000950170-23-001409", "fy": 2022, "fp": "FY",
                         "form": "10-K", "filed": "2023-01-31"},
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 96773000000,
                         "accn": "0001628280-24-002390", "fy": 2023, "fp": "FY",
                         "form": "10-K", "filed": "2024-01-29"},
                        # Quarterly noise we should ignore
                        {"start": "2024-01-01", "end": "2024-03-31", "val": 21301000000,
                         "fy": 2024, "fp": "Q1", "form": "10-Q", "filed": "2024-04-24"},
                    ]
                }
            },
            "GrossProfit": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 17660000000,
                         "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
            "OperatingIncomeLoss": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 8891000000,
                         "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 13256000000,
                         "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 8898000000,
                         "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {
                    "USD": [
                        {"end": "2023-12-31", "val": 16398000000, "fy": 2023, "fp": "FY",
                         "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
            "LongTermDebtNoncurrent": {
                "units": {
                    "USD": [
                        {"end": "2023-12-31", "val": 2857000000, "fy": 2023, "fp": "FY",
                         "form": "10-K", "filed": "2024-01-29"},
                    ]
                }
            },
        }
    }
}


def test_latest_annual_value_picks_most_recent_FY():
    r = latest_annual_value(MOCK_TESLA_FACTS, "us-gaap", "Revenues")
    assert r is not None, "Should find Revenues"
    assert r["fiscalYear"] == 2023, f"Expected FY2023, got {r['fiscalYear']}"
    assert r["value"] == 96773000000
    assert r["form"] == "10-K"
    print("  ✓ Picks most recent FY (FY2023, $96.77bn)")


def test_skips_quarterly_data():
    r = latest_annual_value(MOCK_TESLA_FACTS, "us-gaap", "Revenues")
    # The Q1 2024 entry exists but should be skipped (fp != FY)
    assert r["fiscalYear"] == 2023, "Should skip Q1 2024 entry"
    print("  ✓ Correctly skips quarterly filings")


def test_find_concept_uses_fallback_order():
    # GrossProfit exists at us-gaap, should hit on first try
    r = find_concept(MOCK_TESLA_FACTS, CONCEPT_FALLBACKS["grossProfit"])
    assert r is not None
    assert r["sourceTag"] == "us-gaap:GrossProfit"
    print("  ✓ find_concept walks the fallback list")


def test_missing_concept_returns_none():
    r = find_concept(MOCK_TESLA_FACTS, [("us-gaap", "ThisDoesNotExist")])
    assert r is None
    print("  ✓ Returns None for missing concepts")


def test_full_company_derive_margins():
    """End-to-end: monkey-patch fetch_json then run fetch_company."""
    import fetch_sec_financials as mod

    original = mod.fetch_json
    mod.fetch_json = lambda url: MOCK_TESLA_FACTS

    try:
        result = mod.fetch_company("Tesla", "0001318605")
    finally:
        mod.fetch_json = original

    d = result["derived"]
    # Gross margin: 17,660 / 96,773 = 18.25%
    assert 18.0 < d["grossMargin"] < 18.5, f"Gross margin off: {d['grossMargin']}"
    # Op margin: 8,891 / 96,773 = 9.19%
    assert 9.0 < d["opMargin"] < 9.5, f"Op margin off: {d['opMargin']}"
    # FCF margin: (13,256 - 8,898) / 96,773 = 4.50%
    assert 4.3 < d["fcfMargin"] < 4.7, f"FCF margin off: {d['fcfMargin']}"
    # Net cash: 16,398 - 2,857 = 13,541
    assert d["netCash"] == 13541000000
    print(f"  ✓ Derived margins correct (GM {d['grossMargin']}%, "
          f"Op {d['opMargin']}%, FCF {d['fcfMargin']}%, "
          f"NetCash ${d['netCash']/1e9:.1f}bn)")


if __name__ == "__main__":
    print("Testing SEC EDGAR parser against mocked response...")
    test_latest_annual_value_picks_most_recent_FY()
    test_skips_quarterly_data()
    test_find_concept_uses_fallback_order()
    test_missing_concept_returns_none()
    test_full_company_derive_margins()
    print("\nAll tests passed.")
