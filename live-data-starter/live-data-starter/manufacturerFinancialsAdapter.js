/* ============================================================================
   manufacturerFinancialsAdapter.js
   ----------------------------------------------------------------------------
   Drop-in replacement for the demo `manufacturerFinancials` constant in the
   Automobile Industry Intelligence Dashboard.

   Reads the JSON produced by scripts/fetch_sec_financials.py (run by GitHub
   Actions) via the raw.githubusercontent.com CDN. Falls back gracefully to
   demo data on any failure.

   Usage in the dashboard:

       import { fetchManufacturerFinancials } from './manufacturerFinancialsAdapter';

       const [financials, setFinancials] = useState({ data: DEMO, meta: null });
       useEffect(() => {
         fetchManufacturerFinancials().then(setFinancials);
       }, []);

       // financials.data → same shape as the old demo constant
       // financials.meta → { generatedAt, ageDays, confidence, isDemoFallback }
   ============================================================================ */

// 👇 Edit these two lines after you create the data repo on GitHub.
const GH_USER = 'YOUR_GITHUB_USERNAME';
const GH_REPO = 'auto-dashboard-data';
const GH_BRANCH = 'main';

const DATA_URL =
  `https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/${GH_BRANCH}/data/financials.json`;

/**
 * Keep the original demo object exported here so the dashboard always has
 * a safe fallback. Copy from the demo data in auto_dashboard.jsx.
 */
const DEMO_FALLBACK = {
  Tesla:      { units: 1790, revenue: 97.0, grossMargin: 17.9, opMargin: 7.8,  fcfMargin: 3.5, netCash:  30, category: 'EV pure-play', hq: 'US' },
  Ford:       { units: 4470, revenue: 185.0,grossMargin: 13.5, opMargin: 3.2,  fcfMargin: 3.0, netCash:-110, category: 'Legacy',       hq: 'US' },
  GM:         { units: 6000, revenue: 187.0,grossMargin: 12.5, opMargin: 7.0,  fcfMargin: 5.0, netCash: -95, category: 'Legacy',       hq: 'US' },
  Stellantis: { units: 5540, revenue: 185.0,grossMargin: 18.5, opMargin: 5.5,  fcfMargin: 1.0, netCash:  20, category: 'Legacy',       hq: 'NL' },
};

/**
 * Pulls live SEC financials and reshapes them to the dashboard format.
 * Always returns a usable object — never throws.
 */
export async function fetchManufacturerFinancials() {
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const raw = await res.json();

    const generatedAt = new Date(raw._meta.generatedAt);
    const ageMs   = Date.now() - generatedAt.getTime();
    const ageDays = Math.round(ageMs / 86_400_000);

    // Stale-data downgrade — High when fresh, Medium 14-30d, Low past 30d.
    const confidence =
      ageDays > 30 ? 'Low' :
      ageDays > 14 ? 'Medium' : 'High';

    const data = { ...DEMO_FALLBACK };  // start from fallbacks (preserves units, category, hq)
    let liveCount = 0;

    for (const [name, c] of Object.entries(raw.companies || {})) {
      if (c.error || !c.raw?.revenue) continue;

      // Merge live financials onto the demo entry so fields like `units`,
      // `category`, `hq` (not in EDGAR) are preserved.
      data[name] = {
        ...DEMO_FALLBACK[name],
        revenue:     +(c.raw.revenue.value / 1e9).toFixed(1),     // $bn
        grossMargin: c.derived?.grossMargin  ?? data[name]?.grossMargin,
        opMargin:    c.derived?.opMargin     ?? data[name]?.opMargin,
        fcfMargin:   c.derived?.fcfMargin    ?? data[name]?.fcfMargin,
        netCash:     c.derived?.netCash != null
                       ? Math.round(c.derived.netCash / 1e9)       // $bn
                       : data[name]?.netCash,
        _liveSource:  'SEC EDGAR',
        _periodEnd:   c.raw.revenue.periodEnd,
        _fiscalYear:  c.raw.revenue.fiscalYear,
        _confidence:  confidence,
      };
      liveCount++;
    }

    return {
      data,
      meta: {
        generatedAt: raw._meta.generatedAt,
        ageDays,
        confidence,
        liveCompanyCount: liveCount,
        totalCompanyCount: Object.keys(raw.companies || {}).length,
        isDemoFallback: false,
      },
    };
  } catch (err) {
    console.warn('Live fetch failed; using demo fallback:', err.message);
    return {
      data: DEMO_FALLBACK,
      meta: {
        generatedAt: null,
        ageDays: null,
        confidence: 'Low',
        liveCompanyCount: 0,
        totalCompanyCount: Object.keys(DEMO_FALLBACK).length,
        isDemoFallback: true,
        error: err.message,
      },
    };
  }
}
