"""
test_stooq_parser.py — validate Stooq parsing/resampling/indexing offline.

Runs without network access (sandbox-safe). The same code runs unchanged
against the live Stooq API on a GitHub Actions runner.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fetch_stooq_prices import (  # noqa: E402
    parse_csv, month_end_closes, index_to_100, to_dashboard_shape, fetch_company
)


# Realistic mock — Tesla-style CSV from Stooq, daily Jan-Mar 2020
MOCK_CSV = """Date,Open,High,Low,Close,Volume
2020-01-02,28.30,28.71,28.11,28.68,142981500
2020-01-03,29.37,30.27,29.13,29.53,266677500
2020-01-31,42.96,43.53,42.01,43.37,158894500
2020-02-03,42.49,52.16,42.42,51.50,378097500
2020-02-28,45.34,49.20,44.69,44.53,432978500
2020-03-02,49.20,55.18,49.04,52.13,400521000
2020-03-31,33.40,34.69,32.50,34.93,267502500
"""


def test_parse_csv_basic():
    rows = parse_csv(MOCK_CSV)
    assert len(rows) == 7
    assert rows[0]["date"] == "2020-01-02"
    assert rows[0]["close"] == 28.68
    print("  ✓ Parses Stooq CSV format")


def test_parse_csv_rejects_html():
    try:
        parse_csv("<html>Error page</html>")
        assert False, "Should have raised"
    except ValueError:
        pass
    print("  ✓ Rejects HTML error pages")


def test_parse_csv_rejects_empty():
    for bad in ["", "   \n  ", "No data"]:
        try:
            parse_csv(bad)
            assert False, f"Should have raised for {bad!r}"
        except ValueError:
            pass
    print("  ✓ Rejects empty / no-data responses")


def test_month_end_resampling():
    daily = parse_csv(MOCK_CSV)
    monthly = month_end_closes(daily)
    # Should produce one entry per month: Jan, Feb, Mar 2020
    assert len(monthly) == 3
    assert monthly[0]["date"] == "2020-01"
    # Jan should pick the latest day (2020-01-31, close 43.37)
    assert monthly[0]["close"] == 43.37
    # Feb latest (2020-02-28, close 44.53)
    assert monthly[1]["close"] == 44.53
    # Mar latest (2020-03-31, close 34.93)
    assert monthly[2]["close"] == 34.93
    print("  ✓ Resamples to month-end closes correctly")


def test_indexing():
    rows = [
        {"date": "2020-01", "close": 50.0},
        {"date": "2020-02", "close": 75.0},
        {"date": "2020-03", "close": 100.0},
    ]
    indexed = index_to_100(rows, base_value=50.0)
    assert indexed[0]["indexed"] == 100.0
    assert indexed[1]["indexed"] == 150.0
    assert indexed[2]["indexed"] == 200.0
    print("  ✓ Indexes series to 100 at base")


def test_full_company_via_mock():
    """End-to-end: monkey-patch fetch_csv to return our mock."""
    import fetch_stooq_prices as mod
    original = mod.fetch_csv
    mod.fetch_csv = lambda ticker, start, end: MOCK_CSV

    try:
        result = fetch_company("Tesla", "tsla.us", "20200101", "20200401")
    finally:
        mod.fetch_csv = original

    assert "error" not in result, f"Should succeed: {result}"
    assert result["monthsAvailable"] == 3
    assert result["firstMonth"] == "2020-01"
    assert result["lastMonth"] == "2020-03"
    assert result["baseClose"] == 43.37  # Jan close
    # Mar close 34.93 / Jan close 43.37 * 100 = 80.5
    assert 80.0 < result["lastIndexed"] < 81.0
    print(f"  ✓ End-to-end produces indexed series "
          f"(Jan→Mar 2020: {result['series'][0]['indexed']} → "
          f"{result['series'][-1]['indexed']})")


def test_dashboard_shape():
    companies = {
        "A": {"series": [{"date": "2020-01", "indexed": 100.0},
                         {"date": "2020-02", "indexed": 110.0}]},
        "B": {"series": [{"date": "2020-01", "indexed": 100.0},
                         {"date": "2020-02", "indexed":  95.0}]},
        "C": {"error": "fetch failed"},
    }
    shape = to_dashboard_shape(companies)
    assert len(shape) == 2
    assert shape[0] == {"date": "2020-01", "A": 100.0, "B": 100.0}
    assert shape[1] == {"date": "2020-02", "A": 110.0, "B": 95.0}
    # Failed company should be absent, not None
    assert "C" not in shape[0]
    print("  ✓ Dashboard shape excludes failed companies cleanly")


if __name__ == "__main__":
    print("Testing Stooq parser against mocked CSV...")
    test_parse_csv_basic()
    test_parse_csv_rejects_html()
    test_parse_csv_rejects_empty()
    test_month_end_resampling()
    test_indexing()
    test_full_company_via_mock()
    test_dashboard_shape()
    print("\nAll tests passed.")
