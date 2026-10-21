# V2 changelog - tools/xbrl_parser.py

| id | files | rationale | dev cases that revealed it | tests |
|----|-------|-----------|----------------------------|-------|
| xbrl-1 | tools/xbrl_parser.py, tests/test_xbrl_parser.py | Filing period end = latest annual-duration (350-380d) fact end, but forward-looking facts count: PG's FY2019 10-K (0000080424-19-000050, filed 2019-08-06) carries `UnrecognizedTaxBenefitsDecreasesResultingFromSettlementsWithTaxingAuthorities` for 2019-07-01..2020-06-30, so the filing was labelled FY2020 (period_end 2020-06-30), FY2019 had no filing, the true FY2020 10-K (-20-000053) was a "later filing", and the warning "2 annual filings for FY2020" fired. Fix: a report cannot describe a period ending after its filing date, so only facts with `end <= filed` define the period of report (filing-semantics rule, no threshold). | PG (FYE Jun 30), found by orchestrator; no other dev case affected. | test_forward_looking_duration_fact_does_not_shift_period_end (synthetic); live: test_live_original_filing_matches_edgar_submissions[PG/MSFT/AAPL/JNJ], test_live_pg_fy2020_values_and_shares_from_fy2020_10k, test_live_other_fye_conventions_one_filing_per_year[WMT/HD/MMM] |

## Diagnosis
Not a `fy`-field problem and not comparatives: a single forward-looking duration fact. Because `_pick` pass 1 filters by
`accn`, the mislabelled accession (-19-000050) had no facts ending 2020-06-30, so pass 2 (any filing) took the FY2020 10-K's
value; most values were therefore right, provenance wrong. Values that WERE wrong (item missing in the filed-original
accession falls to the "later filing" pass, or in the PG FY2012/13 case to a restated/recast later filing):

## Value changes for the 12 dev cases (as_of = analysis_filing_date, years 1995-2022, before -> after)
Only PG changed; ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, BRK-B, MMM: no filing or value changed.
* PG FY2020 SharesOutstanding: 2,502,259,668 (from the FY2019 10-K, -19-000050) -> 2,486,086,692 (FY2020 10-K, -20-000053).
* PG FY2019 SharesOutstanding: missing -> 2,502,259,668 (FY2019 10-K; FY2019 now has its own filing).
* PG FY2020 filing_by_year: -19-000050 / 2019-08-06 / n=2 -> -20-000053 / 2020-08-06 / n=1; FY2019 gained -19-000050 / 2019-08-06 / 2019-06-30.
* PG FY2012 Revenue 28.4B and GrossProfit -13.99B (taken from the FY2014 10-K, -14-000057, recast/segment fact) -> 83.68B / 41.29B (FY2012 10-K).
* PG FY2013 Revenue 29.2B, GrossProfit -13.23B (-14-000057) -> 84.167B / 41.739B (-13-000063); SharesOutstanding 2,754,274,536 (FY2012 10-K) -> 2,738,760,542 (FY2013 10-K).
* PG FY2012/2013 are outside the analysis window of the dev run (FY2015-2020 for FY2020 analysis); PG FY2020 Revenue (70.95B) and all other FY2015-2020 items were unchanged.

## Verification of other filers (EDGAR submissions via tools.edgar_api, cached)
Checked PG, MSFT (Jun), AAPL (Sep), JNJ (52/53 wk, FY2020 ends 2021-01-03), WMT/HD (Jan FYE), MMM, BRK-B: after the fix `filing_by_year`
for FY2015-2020 has exactly one annual filing per year and accession/filing_date/period_end equal list_annual_filings. No look-ahead change (`as_of` rule untouched).

## tools.edgar_api.list_annual_filings labelling (report only, file not edited)
`fiscal_year` == `fiscal_year_of(report_date)` for every filing of PG, MSFT, AAPL, JNJ, WMT, HD, MMM, BRK-B (0 mismatches); no duplicate years in
FY2010+. Two pre-2010 oddities: WMT 0000104169-09-000006 has report_date = filing date (2009-04-01, EDGAR submissions data; true period end 2009-01-31 -> should be FY2008, so FY2009 appears twice),
MMM FY1993 has two 10-Ks filed the same day (0000066740-94-000013 and -000007). Neither touches the dev window.
Convention note (D12): Jan-FYE retailers label FYE 2021-01-31 as 2020 (WMT calls it "fiscal 2021"); consistent in both modules.
