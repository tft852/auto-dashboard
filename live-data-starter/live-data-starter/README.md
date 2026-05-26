# Auto Dashboard — Live Data Starter (SEC EDGAR)

Concrete starting point for taking the Automobile Industry Intelligence Dashboard from demo data to live data, free of charge.

This kit covers **SEC EDGAR financials** for Tesla, Ford, GM and Stellantis. It is intentionally one data source done end-to-end rather than a half-finished sweep across many. Once the pattern is in place, additional adapters (Stooq stock prices, AFDC charging, DVLA vehicle stock, IEA EV outlook) follow the same shape.

## What's in here

```
live-data-starter/
├── scripts/
│   ├── fetch_sec_financials.py     # Pulls XBRL data from data.sec.gov
│   └── test_parser.py              # Offline tests; run in CI before fetch
├── .github/
│   └── workflows/
│       └── fetch-financials.yml    # Weekly cron, commits refreshed data
├── data/
│   └── financials.json             # Generated output (committed by workflow)
├── manufacturerFinancialsAdapter.js # Drop-in for the dashboard
└── README.md
```

## How it works

```
┌─────────────────┐   weekly cron   ┌──────────────────┐
│  data.sec.gov   │ ──────────────▶ │ GitHub Actions   │
│  XBRL JSON      │                 │ runner           │
└─────────────────┘                 └──────────────────┘
                                             │
                                             │ git commit
                                             ▼
                                    ┌──────────────────┐
                                    │ data/            │
                                    │  financials.json │
                                    └──────────────────┘
                                             │
                                             │ raw.githubusercontent.com
                                             ▼
                                    ┌──────────────────┐
                                    │ Dashboard React  │
                                    │ adapter (fetch)  │
                                    └──────────────────┘
```

No backend, no API keys, no hosting cost. Everything is public.

## Setup (10 minutes)

### 1. Create the data repository

Make a new **public** GitHub repo, e.g. `auto-dashboard-data`. (Public so `raw.githubusercontent.com` serves the JSON without auth.)

Copy the contents of this folder into it. Push to `main`.

### 2. Set a real User-Agent

SEC requires an identifiable User-Agent. Open `scripts/fetch_sec_financials.py` and change:

```python
USER_AGENT = "AutoDashboard research-prototype contact@example.com"
```

to use your real name and email. SEC will block requests that look like generic scrapers.

### 3. Trigger the first run

Go to **Actions → Fetch SEC financials → Run workflow**. After ~30 seconds you should see a new commit on `main` updating `data/financials.json`.

The cron then runs every Sunday at 06:00 UTC.

### 4. Wire the dashboard

Open `manufacturerFinancialsAdapter.js`, edit two lines:

```javascript
const GH_USER = 'your-username';
const GH_REPO = 'auto-dashboard-data';
```

In `auto_dashboard.jsx`, import and call the adapter:

```javascript
import { fetchManufacturerFinancials } from './manufacturerFinancialsAdapter';

// Inside the App component:
const [financials, setFinancials] = useState({ data: DEMO_FINANCIALS, meta: null });

useEffect(() => {
  fetchManufacturerFinancials().then(setFinancials);
}, []);

// Then replace references to the old constant:
// manufacturerFinancials      →  financials.data
```

The adapter merges live SEC values onto the demo objects, so non-EDGAR fields (`units`, `category`, `hq`) are preserved. Companies not covered by SEC EDGAR (Toyota, VW, BYD, etc.) continue using demo values until you add their adapter.

### 5. Show freshness on the UI

`financials.meta` contains `{ generatedAt, ageDays, confidence, isDemoFallback }`. Surface it on the existing "Last updated" indicator and on the per-company confidence badges — that's the system you already built. When `isDemoFallback === true`, show the amber "Demo data" pill clearly.

## What's actually live after this

| Field        | Live (Tesla/Ford/GM/Stellantis) | Demo |
|--------------|---------------------------------|------|
| revenue      | ✓ SEC EDGAR                     |      |
| grossMargin  | ✓ Derived from XBRL             |      |
| opMargin     | ✓ Derived from XBRL             |      |
| fcfMargin    | ✓ Derived (OCF − CapEx) / Rev   |      |
| netCash      | ✓ Cash − LongTermDebt           |      |
| units        |                                 | ✓ (deliveries are not GAAP) |
| mktCap       |                                 | ✓ (next adapter: Stooq) |
| category, hq |                                 | ✓ (static) |

The two big missing pieces — vehicle deliveries and market cap — are *deliberately* the next two adapters. Deliveries come from company IR pages (scrape monthly). Market cap comes from Stooq daily close × shares outstanding (already in the SEC submissions endpoint, easy add).

## Known limitations

- **Stellantis** files as a 20-F under IFRS. The parser tries IFRS tags as fallbacks but the field coverage is thinner than for US-domestic filers. You may see fewer derived metrics for STLA than for TSLA/F/GM until you map additional IFRS concepts.
- **Vehicle deliveries** are not in XBRL. Tesla and BYD publish monthly delivery press releases on their IR sites — a separate scraper, not this one.
- **Quarterly vs annual.** This script pulls the latest *annual* (FY) value. Replace `ANNUAL_FORMS` with `("10-Q",)` and `fp != "FY"` filtering inverted if you want trailing-twelve-months.
- **Free, not zero-maintenance.** When SEC tweaks the API or a filer changes their XBRL tagging, the parser may miss a concept. The `found_count` log line in each run tells you how many concepts resolved — set up a notification if that number drops.

## Next adapters (suggested order)

1. **Stooq stock prices** — `https://stooq.com/q/d/l/?s={ticker}&i=d` returns CSV, no key. Trivial.
2. **DVLA vehicle stock** — quarterly CSV at `gov.uk/government/statistical-data-sets/all-vehicles-veh01`. Replace `regionalSales.UK` historical baseline.
3. **AFDC charging stations** — `developer.nrel.gov/api/alt-fuel-stations/v1.json` (free key). Replace US row of `chargingInfrastructure`.
4. **IEA Global EV Outlook** — annual CSV download. Replace cross-region powertrain baselines.

Each follows the same pattern: a `fetch_X.py` script, the same workflow runner, a paired `XAdapter.js` in the dashboard.

## Why this design

- **Public repo as a CDN.** Cheaper and simpler than running a server. raw.githubusercontent.com is free, fast, has a global CDN.
- **Commit history = audit trail.** Every data refresh is a git commit. If something looks wrong, you can `git log data/financials.json` and see exactly when it changed.
- **Tests run before fetch.** The workflow runs `test_parser.py` before hitting SEC. If parsing logic breaks, you find out before you write a corrupt JSON file.
- **Demo fallback in the adapter.** The dashboard never breaks. If raw.githubusercontent.com is down, the workflow hasn't run, or the JSON shape is wrong, you fall back to the in-bundle demo data with `confidence: 'Low'` and `isDemoFallback: true`. Users see degraded data, not a broken page.

## Compliance note

SEC EDGAR's terms ([sec.gov/os/accessing-edgar-data](https://www.sec.gov/os/accessing-edgar-data)) require:
- A User-Agent with contact information ✓
- Maximum 10 requests/second ✓ (we sleep 150 ms between calls)
- No request bursts during downtime windows

The script complies with all three.
