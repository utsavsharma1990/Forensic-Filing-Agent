# HOLDOUT 2 (H2) research log (SEALED)

**SEALED: do not read, grep or run before the v3 freeze (docs/V3_FREEZE.md).** Nobody building v3 may open this file or `evaluation/holdout2_cases.py`. The selection agent never ran the forensic system (no graph.pipeline, agents/*, evaluator) on any candidate and never looked at how a candidate would score. Machine-readable result: `evaluation/holdout2_cases.py` (15 fraud + 15 matched clean). Protocols: `docs/V2_PROTOCOL.md`, `docs/V3_PROTOCOL.md`. Researched 2026-10-18.

## 1. Method

1. Candidate pool: (a) the full SEC *Accounting and Auditing Enforcement Releases* index (sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases,
   3,348 rows scraped; company-type respondents 2007-2026 de-duplicated to 434 entities, list in section 6), plus (b) cases named from
   memory (section 6.4). Nothing was trusted from memory: every selected case was re-verified against EDGAR filings and the SEC release.
2. Excluded by protocol before looking at any detail: the 12 dev cases (Enron, WorldCom, Luckin, Nikola, Lordstown, Virgin Galactic, AAPL, MSFT,
   JNJ, PG, BRK-B, MMM), the 24 holdout-1 cases (fraud and clean, by ticker and CIK), the test fixtures (Kraft Heinz, Bed Bath & Beyond,
   Super Micro, WMT, HD, KO, XOM, IBM, CAT and every CIK found in tests/ and .cache/text/.cache/cases), and, for the controls, every
   fraud company in this pool. The exclusion set (45 CIKs from the registries and fixtures plus the 15 H2 fraud CIKs) is checked by the validator.
3. For each shortlisted candidate: EDGAR submissions (cached `tools.edgar_api`, User-Agent `forensic-filing-agent contact@example.com`, never a
   personal address): all 10-K/10-K/A/NT 10-K/NT 10-Q and 8-K items 4.02/4.01/2.06/3.01 between the last annual report and the first
   public revelation; the text of the revelation filings (8-K, NT 10-K/10-Q, press-release exhibits); the analysed 10-K text scanned for
   pre-existing subpoena/SEC-inquiry/restatement/material-weakness language; the SEC order/litigation release (pdftotext/HTML) for
   the label and the misstatement period; companyfacts for XBRL (an accession match decides `has_xbrl`).
4. Selection by criteria and documentation quality only; industries and years stratified; at most 3 of 15 fraud cases in any 2-digit SIC
   group (20%, cap was 25%); pre-XBRL cases capped at 5 of 15 (33%, cap was 40%). No scoring information was used.
5. Control per fraud case: XBRL `Assets` frames (CY quarters around the fiscal-year end, tolerance 200 days) intersected with the SIC listing of the
   same 3-digit code (then the 2-digit group when no 3-digit peer passed), assets 0.3x-3x, fiscal-year label equal (D12), a 10-K for that year,
   no NT 10-K/10-Q or 8-K item 4.01/4.02/2.06 in FY-30d .. FY+3y+150d, at least four 10-Ks in that window, revenue > 0 (companyfacts).
   Order: same 4-digit SIC, same 3-digit SIC, fiscal-year end within 100 days, then closeness of the asset ratio (|ln ratio|). The four
   annual reports FY..FY+3 of each finalist were text-scanned (restatement excluding "amended and restated", non-boilerplate "material
   weakness", "substantial doubt", SEC subpoena/investigation), amendments and flagged 8-Ks were read, and the SEC AAER index was checked for every
   control. Controls that failed (full list in section 5) were skipped. For FY2006 and FY2008 (no XBRL frames) the pool was built from the SIC
   listing and assets were parsed from the filings' balance sheets (text run).
6. Validation (`.cache/holdout2/validate2.py`): all keys of the dev schema present and no unexpected keys, CIK format, dates parse, fiscal-year label
   = D12 of the report date, `analysis_filing_date < public_revelation_date` for all 15 fraud cases, no other 10-K/20-F filed between the analysed filing and the
   revelation, accession/form/filing date/report date equal EDGAR submissions, EDGAR filing index page fetches, `has_xbrl` equals "facts exist
   for the accession", `Assets` equals `total_assets` (XBRL cases), matched pairs reciprocal, same fiscal-year label, assets ratio 0.3-3.0, same 2-digit
   SIC, disjointness from all 36 dev/holdout-1 CIKs and tickers and the fixtures, control screen re-run. Result: 0 errors apart from the two
   revelation accessions of the RTI case, which sit under the successor CIK 0001760173 (Surgalign) and were confirmed there by hand.

## 2. Summary

| | n |
|---|---|
| Fraud cases | 15 (10 XBRL era = 67%, 5 pre-XBRL) |
| Clean controls | 15 (10 XBRL era, 5 pre-XBRL) |
| fraud_nature | 15 financial_statement (100%); 0 disclosure_claims |
| Label tiers | 11 settled/litigated orders or complaints with fraud or fraud-type findings against the issuer (Manitex, SAE, Revolution, Hill, PSI, RTI, comScore, Ener1, Saba, Volt, Isilon) / 3 controls-or-reporting orders against the issuer with a restatement and no fraud finding (Stein Mart, Plug Power, Swisher) / 1 case with enforcement only against individuals (UniTek) |
| Fiscal years (fraud) | 2006, 2008, 2010, 2010, 2011, 2011, 2011, 2014, 2015, 2016, 2016, 2017, 2018, 2018, 2019 |
| Industries (2-digit SIC group) | 35 industrial/computer machinery x3 (3559, 3510, 3572); 36 electrical equipment x3 (3640, 3620, 3690); 73 business services/software x3 (7389, 7372, 7363); 13 oil services (1382); 87 engineering services (8711); 56 apparel retail (5651); 38 medical devices (3842); 28 soap/cleaning (2840); 48 telecom services (4812) |
| Max share of one industry | 20% (3 of 15) |
| Pairs on the same 4-digit SIC | 10 of 15; same 3-digit group 12 of 15; 2-digit only: HIL/EXPO, PSIX/KAI, SWSH/SYNL |
| Months from analysed filing to first revelation | 4.7 to 12.6 (median 7.8) |

## 3. Fraud cases

| Ticker | Company | CIK | SIC | FY | Form | Accession | Filed | First public revelation | Months | Assets ($M) | XBRL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MNTX | Manitex International, Inc. | 0001302028 | 3559 | 2016 | 10-K | 0001564590-17-003903 | 2017-03-10 | 2017-11-06 | 7.9 | 318.0 | yes |
| SAEX | SAExploration Holdings, Inc. | 0001514732 | 1382 | 2018 | 10-K | 0001564590-19-009158 | 2019-03-25 | 2019-08-15 | 4.7 | 137.5 | yes |
| RVLT | Revolution Lighting Technologies, Inc. | 0000917523 | 3640 | 2017 | 10-K | 0001193125-18-074202 | 2018-03-08 | 2018-10-19 | 7.4 | 170.2 | yes |
| HIL | Hill International, Inc. | 0001287808 | 8711 | 2016 | 10-K | 0001047469-17-002267 | 2017-03-31 | 2017-09-21 | 5.7 | 401.2 | yes |
| SMRT | Stein Mart, Inc. | 0000884940 | 5651 | 2011 | 10-K | 0001193125-12-160849 | 2012-04-12 | 2012-09-07 | 4.9 | 473.2 | yes |
| PLUG | Plug Power Inc. | 0001093691 | 3620 | 2019 | 10-K | 0001558370-20-002267 | 2020-03-10 | 2021-03-02 | 11.7 | 771.2 | yes |
| PSIX | Power Solutions International, Inc. | 0001137091 | 3510 | 2015 | 10-K | 0001193125-16-482422 | 2016-02-26 | 2016-08-10 | 5.5 | 359.9 | yes |
| RTIX | RTI Surgical, Inc. (now Surgalign Holdings, Inc.) | 0001100441 | 3842 | 2018 | 10-K | 0001193125-19-063391 | 2019-03-05 | 2020-03-17 | 12.4 | 361.2 | yes |
| SCOR | comScore, Inc. | 0001158172 | 7389 | 2014 | 10-K | 0001158172-15-000020 | 2015-02-20 | 2016-02-29 | 12.3 | 354.0 | yes |
| HEV | Ener1, Inc. | 0000895642 | 3690 | 2010 | 10-K | 0001144204-11-014018 | 2011-03-10 | 2011-08-10 | 5.0 | 396.5 | no |
| SABA | Saba Software, Inc. | 0001070380 | 7372 | 2011 | 10-K | 0001193125-11-212166 | 2011-08-05 | 2012-04-09 | 8.1 | 113.6 | no |
| SWSH | Swisher Hygiene Inc. | 0001504747 | 2840 | 2010 | 10-K | 0000950123-11-031573 | 2011-03-31 | 2012-03-28 | 11.9 | 106.2 | no |
| VOL | Volt Information Sciences, Inc. | 0000103872 | 7363 | 2008 | 10-K | 0001157523-09-000729 | 2009-02-02 | 2009-09-14 | 7.4 | 925.8 | no |
| ISLN | Isilon Systems, Inc. | 0001373671 | 3572 | 2006 | 10-K | 0000950134-07-005674 | 2007-03-15 | 2007-11-08 | 7.8 | 137.0 | no |
| UNTK | UniTek Global Services, Inc. | 0000826773 | 4812 | 2011 | 10-K | 0001144204-12-013579 | 2012-03-07 | 2013-03-27 | 12.6 | 348.9 | yes |

### Fraud case details and sources

**MNTX - Manitex International, Inc.** (FY2016, period end 2016-12-31)
* Revelation: 8-K (items 2.02/4.02) filed 2017-11-06: pending restatement of previously issued financial statements (2016 sales of 39 cranes, ~$15M, to a single broker customer); NT 10-Q 2017-11-13; 10-K/A for FY2016 filed 2018-04-03.
* Fraud type: Improper revenue/inventory accounting through related-party entities (two schemes by senior officers: Lift Ventures JV inventory contribution and 2016 crane sales to a broker customer). Label strength: SEC settled cease-and-desist order 2020-09-29 (AAER-4177): financial and accounting fraud by senior officers; misstated filings Q4 2014-Q2 2017
* Validity: FY2016 10-K (FYE 2016-12-31) filed 2017-03-10, 7.9 months before the first public disclosure (2017-11-06); no other annual report filed in between.
* Caveats: The FY2016 10-K was later amended (10-K/A 2018-04-03, restated). The SEC misstatement window (Q4 2014-Q2 2017) contains the analysed year. 'Restated' mentions in the analysed 10-K concern discontinued-operations presentation and purchase-price allocation, not an error correction.
* Sources: https://www.sec.gov/Archives/edgar/data/1302028/000119312517334251/; https://www.sec.gov/Archives/edgar/data/1302028/000119312517339817/; https://www.sec.gov/files/litigation/admin/2020/33-10860.pdf

**SAEX - SAExploration Holdings, Inc.** (FY2018, period end 2018-12-31)
* Revelation: NT 10-Q filed 2019-08-15 disclosed an SEC investigation of revenue recognition, receivables and tax credits and an Audit Committee assessment of historical financial statements; 8-K item 4.02 filed 2019-08-16 (non-reliance on previously issued statements).
* Fraud type: Revenue (~$100M) recognised on seismic contracts with a purportedly unrelated customer controlled by the CEO; concealed misappropriation (~$12M); related receivables/tax-credit issues. Label strength: SEC civil complaint 2020-10-08 (SDNY 20-cv-08423) against the company and four former executives; final judgments 2023-2024 (AAER-4402/4474/4513)
* Validity: FY2018 10-K (FYE 2018-12-31) filed 2019-03-25, 4.7 months before the first public disclosure (2019-08-15); no other annual report filed in between.
* Caveats: The restatement of FY2018 was filed as a 10-K/A on 2020-02-07; the analysed filing is the original. The FY2018 10-K contains no SEC-investigation, subpoena or going-concern language (scanned). Small company (assets $137M) in an oilfield downcycle.
* Sources: https://www.sec.gov/Archives/edgar/data/1514732/000119312519222607/; https://www.sec.gov/Archives/edgar/data/1514732/000119312519222908/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25700; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25902; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26078

**RVLT - Revolution Lighting Technologies, Inc.** (FY2017, period end 2017-12-31)
* Revelation: Press release 2018-10-19 (furnished on 8-K filed 2018-10-22): ongoing SEC investigation of revenue recognition practices; Audit Committee review of bill-and-hold sales; 8-K item 4.02 filed 2018-12-11; FY2018 10-K never filed on time (NT 10-K 2019-03-27).
* Earlier hints: 2018-08-10 NT 10-Q cited only the assessment of internal-control changes; the 2018-10-17 press release (guidance cut, transaction committee for a chairman/CEO offer) contained no accounting allegation.
* Fraud type: Premature revenue recognition on bill-and-hold sales supported by backdated documents (late 2014 to mid-2018). Label strength: SEC complaint 2020-09-24 (LR-24915, AAER-4170): company, CEO, former CFO and two division CFOs settled; accounting fraud
* Validity: FY2017 10-K (FYE 2017-12-31) filed 2018-03-08, 7.4 months before the first public disclosure (2018-10-19); no other annual report filed in between.
* Caveats: The revelation date is the press-release date; the 8-K carrying it was filed three days later. The company was in a transaction process in late 2018.
* Sources: https://www.sec.gov/Archives/edgar/data/917523/000119312518303652/; https://www.sec.gov/Archives/edgar/data/917523/000119312518346645/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24915

**HIL - Hill International, Inc.** (FY2016, period end 2016-12-31)
* Revelation: 8-K item 4.02(a) filed 2017-09-21 (board determination 2017-09-20): FY2014, FY2015, FY2016 and quarters of 2015-2016 and Q1 2017 can no longer be relied upon.
* Earlier hints: 2017-03-17 NT 10-K and 2017-08-10 NT 10-Q cited the tax treatment of the sale of the Construction Claims Group, not an accounting allegation.
* Fraud type: Uncorrected foreign-currency exchange loss errors (~$5M, spread over time) and related errors that overstated net earnings (May 2014-Mar 2017). Label strength: SEC complaint 2020-01-16 (LR-24720; AAER-4185 for the accountant): company settled with permanent injunction and civil penalty; former chief accounting officer and a senior accountant charged
* Validity: FY2016 10-K (FYE 2016-12-31) filed 2017-03-31, 5.7 months before the first public disclosure (2017-09-21); no other annual report filed in between.
* Caveats: The analysed FY2016 10-K already reports material weaknesses and going-concern language (financial distress is visible), so it is not a clean-looking filing. 10-K/As for FY2016 were filed 2017-05-01 (Part III) and 2018-05-08 (restated).
* Sources: https://www.sec.gov/Archives/edgar/data/1287808/000110465917058182/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24720; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24939

**SMRT - Stein Mart, Inc.** (FY2011, period end 2012-01-28)
* Revelation: NT 10-Q filed 2012-09-07 for Q2: new inventory-system reconciliations and 'control implications related to an error correction'; 8-K item 4.02 filed 2012-11-09 (restate FY2009-FY2011 and quarters); restatement filed May 2013.
* Fraud type: Inventory valued incorrectly for 'Perm POS' markdowns (written down at sale instead of at markdown) plus errors in software assets, credit-card liabilities and other inventory items; quarterly pre-tax income misstated 2010-Nov 2012. Label strength: SEC settled cease-and-desist order 2015-09-22 (AAER-3704) against the company only; reporting, books-and-records and controls violations, no fraud finding
* Validity: FY2011 10-K (FYE 2012-01-28) filed 2012-04-12, 4.9 months before the first public disclosure (2012-09-07); no other annual report filed in between.
* Caveats: Weaker label tier (controls/reporting order, quarterly misstatements). The analysed FY2011 10-K (FYE 2012-01-28) already reports two material weaknesses (system-incident communication, credit-card receivables). 52/53-week retail year; fiscal-year label 2011 per D12.
* Sources: https://www.sec.gov/Archives/edgar/data/884940/000119312512385007/; https://www.sec.gov/Archives/edgar/data/884940/000119312512461903/; https://www.sec.gov/files/litigation/admin/2015/34-75958.pdf

**PLUG - Plug Power Inc.** (FY2019, period end 2019-12-31)
* Revelation: NT 10-K filed 2021-03-02 (review of cost classification and ICFR assessment delayed the FY2020 10-K); 8-K items 2.06/4.02 filed 2021-03-16: FY2018 and FY2019 10-Ks and 2019-2020 10-Qs should no longer be relied upon; restated in the FY2020 10-K filed 2021-05-14.
* Fraud type: Errors in right-of-use assets/lease liabilities for sale-leasebacks, classification of R&D costs as cost of revenue, and loss accruals on service contracts (restated 2018-2020). Label strength: SEC settled cease-and-desist order 2023-08-30 (AAER-4452): financial reporting, accounting and controls failures leading to a multi-year restatement; no fraud finding
* Validity: FY2019 10-K (FYE 2019-12-31) filed 2020-03-10, 11.7 months before the first public disclosure (2021-03-02); no other annual report filed in between.
* Caveats: Weakest label tier (reporting/controls order with restatement). Fast asset growth in the analysed year (assets $771M vs $390M).
* Sources: https://www.sec.gov/Archives/edgar/data/1093691/000110465921030324/; https://www.sec.gov/Archives/edgar/data/1093691/000110465921037184/; https://www.sec.gov/files/litigation/admin/2023/34-98243.pdf

**PSIX - Power Solutions International, Inc.** (FY2015, period end 2015-12-31)
* Revelation: NT 10-Q and 8-K item 7.01 filed 2016-08-10: Q2 10-Q delayed because the company had not concluded its review of transactions needed to close the books; 8-K item 4.02 filed 2017-01-05 after an Audit Committee independent review (preliminary findings 2016-12-28); FY2016 10-K not timely filed (NT 10-K 2017-03-17).
* Fraud type: Bill-and-hold and side-agreement sales recognised as revenue before acceptance; ~$25M of revenue overstated Q4 2014-Q4 2015. Label strength: SEC settled cease-and-desist order against the company 2020-09-24 (AAER-4169); the order describes accounting fraud by the former CEO and two executives
* Validity: FY2015 10-K (FYE 2015-12-31) filed 2016-02-26, 5.5 months before the first public disclosure (2016-08-10); no other annual report filed in between.
* Caveats: The first public signal (2016-08-10) is a delay notice without an accounting allegation; the independent Audit Committee review was announced at an unpinned date between 2016-08 and 2017-01. The analysed FY2015 10-K lies inside the SEC misstatement window.
* Sources: https://www.sec.gov/Archives/edgar/data/1137091/000119312516678104/; https://www.sec.gov/Archives/edgar/data/1137091/000119312517002121/; https://www.sec.gov/files/litigation/admin/2020/34-89984.pdf

**RTIX - RTI Surgical, Inc. (now Surgalign Holdings, Inc.)** (FY2018, period end 2018-12-31)
* Revelation: NT 10-K filed 2020-03-17: Audit Committee internal investigation of revenue recognition practices, precipitated by an SEC investigation; 8-K item 4.02 filed 2020-04-09: FY2014-FY2018 and 2016-2019 quarters to be restated; restated FY2018 10-K/A filed 2020-06-08.
* Fraud type: Revenue pulled forward from future quarters by shipping orders early (with or without customer approval) to meet guidance, 2015-2019; pull-forwards undisclosed. Label strength: SEC settled order 2022-08-03 (AAER-4318) against Surgalign Holdings (successor of RTI) and its former CFO; restatement of 2014-2018
* Validity: FY2018 10-K (FYE 2018-12-31) filed 2019-03-05, 12.4 months before the first public disclosure (2020-03-17); no other annual report filed in between.
* Caveats: The company was later renamed Surgalign (successor CIK 0001760173); the analysed filing is under the original RTI CIK. The FY2019 10-K was filed 2020-06-08 with the restatement.
* Sources: https://www.sec.gov/Archives/edgar/data/1760173/000119312520075447/; https://www.sec.gov/Archives/edgar/data/1760173/000119312520101786/; https://www.sec.gov/files/litigation/admin/2022/33-11088.pdf

**SCOR - comScore, Inc.** (FY2014, period end 2014-12-31)
* Revelation: NT 10-K filed 2016-02-29 (amended 2016-03-07): Audit Committee review of 'potential accounting matters' delayed the FY2015 10-K; 8-K item 4.02 filed 2016-09-15; FY2015 and FY2016 were reported in a combined 10-K filed 2018-03-23.
* Fraud type: Revenue overstated ~$50M (Feb 2014-Feb 2016) via manipulated non-monetary and monetary contracts, plus false statements on key performance metrics. Label strength: SEC settled order 2019-09-24 (AAER-4091): financial accounting and disclosure fraud committed principally through the former CEO
* Validity: FY2014 10-K (FYE 2014-12-31) filed 2015-02-20, 12.3 months before the first public disclosure (2016-02-29); no other annual report filed in between.
* Caveats: The SEC misstatement window starts Feb 2014, so the analysed FY2014 10-K lies inside it. A 10-K/A (2015-04-24; content not examined) followed the original 10-K. The FY2015 annual report was never filed on its own.
* Sources: https://www.sec.gov/Archives/edgar/data/1158172/000119312516485483/; https://www.sec.gov/Archives/edgar/data/1158172/000119312516494215/; https://www.sec.gov/Archives/edgar/data/1158172/000115817216000170/; https://www.sec.gov/files/litigation/admin/2019/33-10692.pdf

**HEV - Ener1, Inc.** (FY2010, period end 2010-12-31)
* Revelation: 8-K items 2.06/4.02 (event 2011-08-10, filed 2011-08-16): Audit Committee concluded FY2010 and Q1 2011 financial statements should be restated (Think Holdings loans/receivables, impairment timing); NT 10-Q 2011-08-09 and 2011-11-10.
* Earlier hints: 2011-06-22 8-K item 2.06 (impairment; content not examined).
* Fraud type: Failure to impair a 48%-owned related-party investment, loan and receivables at year-end 2010 and Q1 2011, and improper Q4 2010 revenue on sales to that entity. Label strength: SEC settled cease-and-desist order 2016-04-19 (AAER-3766) against the company and three former executives (CEO Gassenheimer, Seidel, Kamischke)
* Validity: FY2010 10-K (FYE 2010-12-31) filed 2011-03-10, 5.0 months before the first public disclosure (2011-08-10); no other annual report filed in between.
* Caveats: No XBRL facts for the analysed 10-K in companyfacts (treated as pre-XBRL; statement tables parsed from text). The revelation is five months after the filing.
* Sources: https://www.sec.gov/Archives/edgar/data/895642/000114420411047587/; https://www.sec.gov/files/litigation/admin/2016/33-10068.pdf

**SABA - Saba Software, Inc.** (FY2011, period end 2011-05-31)
* Revelation: 8-K filed 2012-04-09: Audit Committee engaged counsel for an independent accounting review; earnings release and 10-Q for the quarter ended 2012-02-29 delayed; 8-K item 4.02 filed 2012-06-29.
* Fraud type: Falsified consultant time records to recognise professional-services revenue early (fiscal 2008 through Q2 fiscal 2012). Label strength: SEC settled cease-and-desist order 2014-09-24 (AAER-3583) against the company and two former vice presidents; false results in at least 40 filings
* Validity: FY2011 10-K (FYE 2011-05-31) filed 2011-08-05, 8.1 months before the first public disclosure (2012-04-09); no other annual report filed in between.
* Caveats: No XBRL facts for the analysed 10-K (FYE 2011-05-31, filed 2011-08-05) in companyfacts: treated as pre-XBRL. Delisted in 2013 for delinquent filings.
* Sources: https://www.sec.gov/Archives/edgar/data/1070380/000119312512154429/; https://www.sec.gov/Archives/edgar/data/1070380/000119312512162881/; https://www.sec.gov/Archives/edgar/data/1070380/000119312512289589/; https://www.sec.gov/files/litigation/admin/2014/33-9654.pdf

**SWSH - Swisher Hygiene Inc.** (FY2010, period end 2010-12-31)
* Revelation: 8-K item 4.02 and NT 10-K filed 2012-03-28: an internal review delayed the FY2011 10-K; amended 10-Qs for Q1-Q3 2011 filed Feb 2013.
* Fraud type: Business-combination accounting not in conformity with GAAP, improper use of reserves, and earnings-management entries to hit Adjusted EBITDA targets (misstated Q1-Q3 2011). Label strength: SEC settled cease-and-desist order 2016-05-24 (AAER-3775) against the company
* Validity: FY2010 10-K (FYE 2010-12-31) filed 2011-03-31, 11.9 months before the first public disclosure (2012-03-28); no other annual report filed in between.
* Caveats: The SEC findings concern the 2011 quarters, not FY2010: the analysed FY2010 10-K is simply the last annual report before the revelation (and the first after the Nov 2010 merger); whether FY2010 itself was restated was not verified. Pre-XBRL. The control match is only on 2-digit SIC and size (no 3-digit peer passed).
* Sources: https://www.sec.gov/Archives/edgar/data/1504747/000119312512136037/; https://www.sec.gov/Archives/edgar/data/1504747/000119312512136054/; https://www.sec.gov/files/litigation/admin/2016/33-10081.pdf

**VOL - Volt Information Sciences, Inc.** (FY2008, period end 2008-11-02)
* Revelation: NT 10-Q filed 2009-09-14: Q3 10-Q delayed while the company assessed whether previously recognised revenues and related costs on certain customer contracts belonged in later periods; 8-K item 4.02 filed 2009-12-23 (FY2007, FY2008 and 2009 quarters to be restated).
* Earlier hints: 2009-09-09 8-K item 8.01 announced a delay of the Q3 earnings release (no reason). NT 10-K 2009-01-16 and 8-K 2009-01-21 (items 2.02/2.06) preceded the analysed 10-K (content not examined).
* Fraud type: Improper revenue recognition at a subsidiary (SEC: $7.55M overstated in FY2007) and related restatements. Label strength: SEC settled civil action against the company 2013-01-11 (LR-22589, AAER-3439; company enjoined); former CFO final judgment 2014-07-18 (LR-23051, AAER-3569)
* Validity: FY2008 10-K (FYE 2008-11-02) filed 2009-02-02, 7.4 months before the first public disclosure (2009-09-14); no other annual report filed in between.
* Caveats: Pre-XBRL (assets from the filing's balance sheet, $925.8M). The SEC finding concerns FY2007; the analysed FY2008 10-K carried the FY2007 overstatement as a comparative. Material-weakness language is already present in the analysed filing (text count 15).
* Sources: https://www.sec.gov/Archives/edgar/data/103872/000091068009000434/; https://www.sec.gov/Archives/edgar/data/103872/000091068009000432/; https://www.sec.gov/Archives/edgar/data/103872/000091068009000571/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-22589; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-23051

**ISLN - Isilon Systems, Inc.** (FY2006, period end 2006-12-31)
* Revelation: 8-K item 8.01 filed 2007-11-08: Audit Committee independent review of sales to resellers and other customers (revenue timing and internal controls); Q3 results and 10-Q delayed (NT 10-Q 2007-11-15); 8-K item 4.02 filed 2008-03-03 (restate FY2006, Q1-Q2 2007).
* Fraud type: Secret side deals with customers (undisclosed contingencies) allowing $4.8M of improper revenue in 2006-2007. Label strength: SEC fraud charges against the former CFO and settled proceeding against the company 2009-09-14 (LR-21210, AAER-3050)
* Validity: FY2006 10-K (FYE 2006-12-31) filed 2007-03-15, 7.8 months before the first public disclosure (2007-11-08); no other annual report filed in between.
* Caveats: Pre-XBRL (FY2006). First annual report after the Dec 2006 IPO. A 10-K/A (2007-08-09; content not examined) was filed between the analysed 10-K and the revelation. Assets read from the filing's balance sheet ($137.0M).
* Sources: https://www.sec.gov/Archives/edgar/data/1373671/000129993307006535/; https://www.sec.gov/Archives/edgar/data/1373671/000114036107022135/; https://www.sec.gov/Archives/edgar/data/1373671/000129993308001135/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-21210

**UNTK - UniTek Global Services, Inc.** (FY2011, period end 2011-12-31)
* Revelation: NT 10-K filed 2013-03-27: Audit Committee review of revenue recognition at the Pinnacle Wireless division delayed the FY2012 10-K; 8-K item 4.02 filed 2013-04-12 (event 2013-04-10): FY2011 and 2012 quarters no longer to be relied upon; FY2012 10-K with restatement filed 2013-08-12.
* Fraud type: Premature revenue recognition at the acquired Pinnacle Wireless division (invoice-based recognition tied to earn-out incentives). Label strength: SEC settled administrative orders 2017-06-09 (File 3-18020) against three former executives/employees (Pinnacle president, UniTek chief accounting officer, Pinnacle controller; joint $35,000 penalty); no SEC order against the issuer was found (details from secondary summaries; order text not retrieved)
* Validity: FY2011 10-K (FYE 2011-12-31) filed 2012-03-07, 12.6 months before the first public disclosure (2013-03-27); no other annual report filed in between.
* Caveats: Weakest label source (enforcement only against individuals, corroborated by the company's own restatement and an Audit Committee finding of fraudulent activity). The analysed FY2011 10-K is inside the restated period.
* Sources: https://www.sec.gov/Archives/edgar/data/826773/000110465913024894/; https://www.sec.gov/Archives/edgar/data/826773/000110465913029058/; https://www.secactions.com/sec-resolves-financial-fraud-action/

## 4. Clean controls

| Ticker | Company | CIK | SIC | FY | Accession | Filed | Period end | Assets ($M) | XBRL | Partner |
|---|---|---|---|---|---|---|---|---|---|---|
| ACLS | Axcelis Technologies, Inc. | 0001113232 | 3559 | 2016 | 0001558370-17-001778 | 2017-03-14 | 2016-12-31 | 302.2 | yes | MNTX |
| DWSN | Dawson Geophysical Company | 0000799165 | 1382 | 2018 | 0001558370-19-001602 | 2019-03-06 | 2018-12-31 | 150.7 | yes | SAEX |
| LYTS | LSI Industries Inc. | 0000763532 | 3640 | 2017 | 0001437749-17-015804 | 2017-09-08 | 2017-06-30 | 256.7 | yes | RVLT |
| EXPO | Exponent, Inc. | 0000851520 | 8742 | 2016 | 0001144204-17-010991 | 2017-02-24 | 2016-12-30 | 403.7 | yes | HIL |
| BKE | The Buckle, Inc. | 0000885245 | 5651 | 2011 | 0001157523-12-001574 | 2012-03-28 | 2012-01-28 | 531.5 | yes | SMRT |
| EAF | GrafTech International Ltd. | 0000931148 | 3620 | 2019 | 0000931148-20-000024 | 2020-02-21 | 2019-12-31 | 1,526.2 | yes | PLUG |
| KAI | Kadant Inc. | 0000886346 | 3550 | 2015 | 0000886346-16-000221 | 2016-03-16 | 2016-01-02 | 415.5 | yes | PSIX |
| INGN | Inogen, Inc. | 0001294133 | 3842 | 2018 | 0001564590-19-004462 | 2019-02-26 | 2018-12-31 | 375.9 | yes | RTIX |
| DHX | DHI Group, Inc. (formerly Dice Holdings, Inc.) | 0001393883 | 7389 | 2014 | 0001393883-15-000008 | 2015-02-10 | 2014-12-31 | 427.2 | yes | SCOR |
| RSTI | Rofin-Sinar Technologies Inc. | 0001019361 | 3690 | 2010 | 0000930413-10-005871 | 2010-11-30 | 2010-09-30 | 558.2 | no | HEV |
| LGTY | Logility, Inc. (Logility Supply Chain Solutions) | 0000713425 | 7372 | 2011 | 0001193125-11-188351 | 2011-07-14 | 2011-04-30 | 104.8 | no | SABA |
| SYNL | Synalloy Corporation (now Ascent Industries Co.) | 0000095953 | 2800 | 2010 | 0000095953-11-000012 | 2011-03-25 | 2011-01-01 | 81.4 | no | SWSH |
| AMN | AMN Healthcare Services, Inc. | 0001142750 | 7363 | 2008 | 0001193125-09-042607 | 2009-03-02 | 2008-12-31 | 642.8 | no | VOL |
| APKT | Acme Packet, Inc. | 0001130258 | 3576 | 2006 | 0001104659-07-019671 | 2007-03-16 | 2006-12-31 | 153.9 | no | ISLN |
| SHEN | Shenandoah Telecommunications Company | 0000354963 | 4813 | 2011 | 0001140361-12-013424 | 2012-03-06 | 2011-12-31 | 480.0 | yes | UNTK |

* **ACLS**: Clean control for MNTX (FY2016, SIC 3559 vs 3559: same 4-digit SIC, assets ratio 0.95). Text scan of FY2016-FY2019 10-Ks: only audit-report/risk boilerplate (no restatement, material weakness, going concern or SEC inquiry).
* **DWSN**: Clean control for SAEX (FY2018, SIC 1382 vs 1382: same 4-digit SIC, assets ratio 1.10). Text scan FY2018-FY2021 clean. The EDGAR screen window also contains a 2022-03-25 8-K item 3.01 (Nasdaq audit-committee composition after director resignations) and a Part III 10-K/A (2022-05-02) around the 2022 merger; both outside FY..FY+3 and benign.
* **LYTS**: Clean control for RVLT (FY2017, SIC 3640 vs 3640: same 4-digit SIC, assets ratio 1.51). Fiscal year ends 2017-06-30, six months before Revolution's; same fiscal-year label. Text scan FY2017-FY2020 clean.
* **EXPO**: Clean control for HIL (FY2016, SIC 8742 vs 8711: same 2-digit major group only, assets ratio 1.01). SIC 8742 vs 8711: same 2-digit major group 87 only (no 3-digit peer passed the screen). Text scan FY2016-FY2019: 'restatement' appears only in risk-factor and exhibit boilerplate.
* **BKE**: Clean control for SMRT (FY2011, SIC 5651 vs 5651: same 4-digit SIC, assets ratio 1.12). Same fiscal year end (2012-01-28). Text scan FY2011-FY2014 clean.
* **EAF**: Clean control for PLUG (FY2019, SIC 3620 vs 3620: same 4-digit SIC, assets ratio 1.98). SIC 3620 match; assets ratio 1.98 (upper part of the range). Text scan FY2019-FY2022: only ASC 842 'not restated' wording and cover-page error-correction check boxes.
* **KAI**: Clean control for PSIX (FY2015, SIC 3550 vs 3510: same 2-digit major group only, assets ratio 1.15). SIC 3550 vs 3510: same 2-digit group 35 only (no 3-digit peer passed). 52/53-week year ending 2016-01-02 (fiscal-year label 2015 per D12). Text scan: 'restated' only for ASU adoption and presentation changes.
* **INGN**: Clean control for RTIX (FY2018, SIC 3842 vs 3842: same 4-digit SIC, assets ratio 1.04). Text scan FY2018-FY2021: prior (2014-15) material weaknesses are described as remediated; none afterwards.
* **DHX**: Clean control for SCOR (FY2014, SIC 7389 vs 7389: same 4-digit SIC, assets ratio 1.21). Text scan FY2014-FY2017 clean.
* **RSTI**: Clean control for HEV (FY2010, SIC 3690 vs 3690: same 4-digit SIC, assets ratio 1.41). Fiscal year ends 2010-09-30 vs Ener1's 2010-12-31. A 10-K/A (2010-12-23) only corrected a cover-page filer-status box. Text scan FY2010-FY2013 clean. No XBRL facts for the analysed 10-K.
* **LGTY**: Clean control for SABA (FY2011, SIC 7372 vs 7372: same 4-digit SIC, assets ratio 0.92). Fiscal year ends 2011-04-30 (one month before Saba's). Majority-owned subsidiary of American Software. Text scan FY2011-FY2014: only risk-factor 'restatement' language. No XBRL facts for the analysed 10-K.
* **SYNL**: Clean control for SWSH (FY2010, SIC 2800 vs 2840: same 2-digit major group only, assets ratio 0.77). SIC 2800 vs 2840: same 2-digit group 28 only; the 2-digit pool is almost all pharma/biotech, so this is the weakest industry match in the set. Fiscal year ends 2011-01-01 (label 2010). Text scan FY2010-FY2013 clean. No XBRL facts for the analysed 10-K.
* **AMN**: Clean control for VOL (FY2008, SIC 7363 vs 7363: same 4-digit SIC, assets ratio 0.69). Fiscal year ends 2008-12-31 vs Volt's 2008-11-02. Pre-XBRL; assets read from the filing's balance sheet text ($642.8M). Text scan FY2008-FY2011: one segment-restatement mention (presentation).
* **APKT**: Clean control for ISLN (FY2006, SIC 3576 vs 3572: same 3-digit SIC group, assets ratio 1.12). SIC 3576 vs 3572 (same 3-digit group 357). Pre-XBRL. IPO year 2006; text scan FY2006-FY2009 clean.
* **SHEN**: Clean control for UNTK (FY2011, SIC 4813 vs 4812: same 3-digit SIC group, assets ratio 1.38). SIC 4813 vs 4812 (same 3-digit group 481). Text scan FY2011-FY2014: 'restatement' only in risk-factor boilerplate.

## 5. Matching table and skipped controls

| Fraud | Control | FY | Period end (fraud/control) | SIC (fraud/control) | Assets ratio | Same 3-digit SIC |
|---|---|---|---|---|---|---|
| MNTX | ACLS | 2016 | 2016-12-31/2016-12-31 | 3559/3559 | 0.95 | yes |
| SAEX | DWSN | 2018 | 2018-12-31/2018-12-31 | 1382/1382 | 1.10 | yes |
| RVLT | LYTS | 2017 | 2017-12-31/2017-06-30 | 3640/3640 | 1.51 | yes |
| HIL | EXPO | 2016 | 2016-12-31/2016-12-30 | 8711/8742 | 1.01 | no (same 2-digit) |
| SMRT | BKE | 2011 | 2012-01-28/2012-01-28 | 5651/5651 | 1.12 | yes |
| PLUG | EAF | 2019 | 2019-12-31/2019-12-31 | 3620/3620 | 1.98 | yes |
| PSIX | KAI | 2015 | 2015-12-31/2016-01-02 | 3510/3550 | 1.15 | no (same 2-digit) |
| RTIX | INGN | 2018 | 2018-12-31/2018-12-31 | 3842/3842 | 1.04 | yes |
| SCOR | DHX | 2014 | 2014-12-31/2014-12-31 | 7389/7389 | 1.21 | yes |
| HEV | RSTI | 2010 | 2010-12-31/2010-09-30 | 3690/3690 | 1.41 | yes |
| SABA | LGTY | 2011 | 2011-05-31/2011-04-30 | 7372/7372 | 0.92 | yes |
| SWSH | SYNL | 2010 | 2010-12-31/2011-01-01 | 2840/2800 | 0.77 | no (same 2-digit) |
| VOL | AMN | 2008 | 2008-11-02/2008-12-31 | 7363/7363 | 0.69 | yes |
| ISLN | APKT | 2006 | 2006-12-31/2006-12-31 | 3572/3576 | 1.12 | yes |
| UNTK | SHEN | 2011 | 2011-12-31/2011-12-31 | 4812/4813 | 1.38 | yes |

Control candidates that were passed over (reason checked from filings/screen):

| Case | Skipped candidate | Reason |
|---|---|---|
| Plug Power | Thermon | fiscal year ends 2020-03-31, fiscal-year label 2020 (wrong year) |
| Power Solutions | Gorman-Rupp | main 10-K document lacks the financial statements (EX-13); also an 8-K flag in the window |
| Power Solutions | Tennant | 15 material-weakness mentions in the FY2016 10-K (IRIS acquisition control failure) inside FY..FY+3 |
| Isilon | STEC | SEC informal inquiry language (3 hits) in the FY2009 10-K, inside FY..FY+3 |
| Isilon | PAR Technology | restatement and material-weakness hits in the FY2006/FY2007 text scans (contexts not read; Acme Packet cleaner) |
| Isilon | Riverbed | restatement/material-weakness hits in all four text scans (contexts not read; Acme Packet cleaner) |
| Ener1 | Hittite, Lattice, others | same 2-digit group only; Rofin-Sinar matched on 4-digit SIC |
| Saba | LogMeIn, FalconStor and others | fiscal-year end 4-5 months away; Logility FYE within one month of Saba's (sort key) |
| Volt | TTEC | 7 non-boilerplate material-weakness mentions and 12 restatement mentions in FY2008 10-K |
| Volt | Robert Half | assets ratio 1.53 (AMN 0.69 closer in |ln ratio|) |
| Swisher | BioCryst, Celldex, Filana, Ariad and other pharma/biotech | wrong industry (and several 10-K/A amendments in the window); Synalloy (chemicals) is the closest same-group non-pharma peer |
| SAE | Ranger Energy Services | SIC 1389 not 1382 and assets 2.2x (Dawson is same 4-digit SIC, 1.10x) |
| Hill | R1 RCM, Franklin Covey | 8-K/10-K/A flags in window; Exponent same group, ratio 1.01 |
| all | the remaining pool members | removed by the automatic screen (NT filings, 8-K items 4.01/4.02/2.06, fewer than four 10-Ks in the window, no revenue, wrong fiscal-year label) or ranked below the chosen control |

Screen details and ranking files are in `.cache/holdout2/` (rank_*.json, rankT_*.json, ctl.py, ctl_text.py, validate2.py; scratch).

## 6. Candidate pool and drop reasons

### 6.1 Selected (15)

MNTX (Manitex), SAEX (SAExploration), RVLT (Revolution Lighting), HIL (Hill International), SMRT (Stein Mart), PLUG (Plug Power), PSIX (Power Solutions International), RTIX (RTI Surgical / Surgalign), SCOR (comScore), HEV (Ener1), SABA (Saba Software), SWSH (Swisher Hygiene), VOL (Volt Information Sciences), ISLN (Isilon), UNTK (UniTek Global Services; found outside the AAER company index).

### 6.2 Examined against EDGAR filings and dropped (detail)

| Candidate | Reason (checked from filings and the SEC release) |
|---|---|
| Great Lakes Dredge & Dock | 4.02 (2013-03-12) restated only Q2-Q3 2012; the last annual report before it (FY2011) predates the restated quarters |
| Akorn | 4.02 (2015-03) concerned 2014 quarters and the FY2014 10-K was filed within a week; the FY2013 10-K (last before it) is not within the restated period; AAER 2018 not read |
| Lifeway Foods | 4.02 filings in 2013 and 2016 make the first revelation ambiguous; AAER 2019 not read |
| Digital Turbine | no 4.02 or NT 10-K in the window (no restatement revelation); AAER 2019 not read |
| CPI Aerostructures | SEC order covers restatements of 2018-2022; the FY2017 10-K (last before the 2019-02 4.02) predates the misstatement period |
| Evoqua | no 8-K 4.02/NT between the FY2018 10-K and the FY2019 10-K (which itself carries the correction); first revelation not pinned |
| HF Foods | revelation was a short-seller statement within two weeks of the 10-K and an NT 10-Q two months later; no restatement 8-K in the window; label not read (2024 AAER) |
| GT Advanced Technologies | revelation coincides with the Oct-2014 bankruptcy; no restatement 8-K; AAER 2019 not read |
| StoneMor | first 4.02 (2016-08) concerned only the allocation of net income to partners; the alleged misstatement surfaced later (2016-11/2017-02): ambiguous first revelation |
| Magnum Hunter Resources | FY2011 10-K was amended twice before the 4.02 (2012-10) about a calculation error; ambiguous first revelation |
| Universal Travel Group | FY2009 10-K amended twice (2010-06) before the 2011 auditor resignation/4.02; ambiguous |
| Hanger | repeated NT 10-K/4.02 series from 2013 onward; first revelation ambiguous |
| General Cable | NT 10-Q of 2012-11 precedes the FY2012 10-K and 10-K/As for FY2011/FY2012 follow (content not read); first revelation ambiguous |
| Overseas Shipholding Group | FY2011 10-K 2012-02-29, 4.02 2012-10-19; large shipping company, control search not pursued |
| Hertz | NT 10-K/10-Q series with no reasons (also dropped in holdout 1) |
| GTT Communications | large telecom, control search not pursued; FY2019 10-K and 10-K/A precede the 2020 NT 10-Qs (revelation date not pinned) |
| Koss Corporation | eligible (8-K 4.02 2009-12-23 after the FY2009 10-K, SEC action 2011-2012) but dropped: SIC 36 would exceed the 25% industry cap with three other SIC-36 cases, pre-XBRL quota, tiny assets (hard to match) |
| ModusLink Global Solutions (AAER-3758, 2016-03-15) | eligible: FY2011 10-K filed 2011-10-14, SEC inquiry disclosed in the 2012-03-12 10-Q, 4.02 on 2012-06-11 (rebate accounting). Not selected: SIC 73 already had three cases (cap 25%) and the target of 15 was reached; not control-matched |

### 6.3 SEC AAER index sweep (434 company-type respondents 2007-2026; NOT verified unless listed in 6.2 or selected)

The sweep filter keeps respondents whose name contains a corporate suffix word; a manual re-check of the other names found only ModusLink and Merge Healthcare, added here. Classification below used only the release title, date and general knowledge of the respondent (no filing was opened). Counts: LARGE 120, PRE 67, FIN 65, NFS 52, SHELL 51, NOTX 35, VER 17, SEL 14, EXC 13 (total 434).

**SEL (14): selected (see docs)**

Comscore (2019); Ener1 (2016); Hill International (2020); Manitex International (2020); Plug Power Inc. (2023); Power Solutions International (2020); Revolution Lighting Technologies (2020); SAExploration Holdings (2024); Saba Software (2014); Stein Mart (2015); Stuart W. Fuhlendorf (2009); Surgalign Holdings (2022); Swisher Hygiene Inc. (2016); Volt Information Sciences (2014)

**EXC (13): excluded by protocol (dev / holdout-1 / test fixture)**

American Italian Pasta Company; Timothy S. Webster; Warren B (2008); Cantaloupe (2023); International Business Machines Corporation (2011); Lordstown Motors Corp. (2024); Orthofix International N.V. (2017); Osiris Therapeutics (2017); Pareteum Corporation (2021); Quantum Corporation (2019); Roadrunner Transportation Systems (2023); Super Micro Computer (2020); Synchronoss Technologies (2022); The Kraft Heinz Co. (2021); Walmart Inc. (2019)

**VER (16): verified against EDGAR, dropped: analysed-year misstatement not established / revelation ambiguous or control-type label (see section 6.2)**

Akorn (2018); CPI Aerostructures (2024); Digital Turbine (2019); Evoqua Water Technologies Corp. (2024); GT Advanced Technologies Inc. (2019); GTT Communications (2023); General Cable Corporation (2016); Great Lakes Dredge & Dock Corporation (2014); HF Foods Group Inc. (2024); Hertz Global Holdings (2018); Koss Corporation (2012); Lifeway Foods (2019); Magnum Hunter Resources Corporation (2016); Overseas Shipholding Group (2017); Stonemor Partners L.P. (2019); Universal Travel Group (2013)

**VER (1): verified against EDGAR, dropped or not selected (see section 6.2)**

ModusLink Global Solutions (2016)

**FIN (65): financial institution / insurer / asset manager / fund / broker (statements not comparable to operating-company model)**

Allied Capital Corporation (2007); Altaba Inc. (2018); Anchor Bancorp Wisconsin (2013); Aon Corporation (2011); Argo Group International Holdings (2020); Assurant (2010); Asta Funding (2021); BGC Partners (2020); Bancinsurance Corporation (2009); Bank of America Corporation (2014); Barclays PLC (2022); Brixmor Property Group Inc. (2019); Capital One Financial Corporation (2013); Capitol Distributing (2007); Charles Pratt & Company (2022); Citigroup Inc. (2018); Closed Loop Partners (2024); Credit Suisse Group AG (2018); Cronos Group Inc. (2022); Doral Financial Corporation (2009); Eagle Bancorp (2022); Elbit Imaging Ltd. (2018); Federal Home Loan Mortgage Corporation (2007); Fifth Third Bancorp (2013); First BanCorp (2007); First Bancorp (2015); First National Community Bancorp Inc. (2015); Forepont Capital LLC (2023); Fulton Financial Corporation (2020); GLG Partners (2013); General Re Corporation (2010); HCC Insurance Holdings (2008); Hampton Roads Bankshares (2014); Home Loan Servicing Solutions (2015); HomeStreet (2017); ICON Capital LLC f/k/a ICON Capital Corporation (2016); INTL FCStone Inc. (2016); KCAP Financial (2018); Keybanc Capital Markets Inc. (2016); Legg Mason (2018); Lynn Tilton; Patriarch Partners (2017); MBIA Inc. (2007); Malvern Bancorp (2023); Mercantile Bancorp (2013); New Stream Capital (2015); Ocwen Financial Corp. (2016); Orrstown Financial Services (2016); Park National Corporation (2016); Prudential Financial (2008); RenaissanceRe Holdings Ltd. (2007); SCOR Holding (Switzerland) Ltd. (2008); Santander Consumer USA Holdings Inc. (2018); TCA Fund Management Group Corp. (2020); The BISYS Group (2007); The Bancorp (2022); The Bank of New York Mellon Corporation (2015); The Goldman Sachs Group (2020); The Phoenix Companies (2016); Tilton (2015); Tradebot Systems (2014); Trinity Capital Corporation (2015); True North Finance Corp. (2013); WEX Inc. (2021); Wilmington Trust Corporation (2014); World Acceptance Corporation (2020)

**LARGE (110): large-cap (assets typically > $10B: no 0.3x-3x operating control feasible) and/or SEC matter by title believed to be FCPA/disclosure/controls-only; not examined**

3M Company (2023); AAR CORP. (2024); ABB Ltd (2010); Affiliated Computer Services (2010); Albemarle Corporation (2023); Alcoa Inc. (2014); Alexion Pharmaceuticals (2020); American Electric Power Company (2025); Andeavor LLC (2020); Archer-Daniels-Midland Company (2026); AstraZeneca PLC (2016); Avery Dennison Corporation (2009); Avon Products (2014); Ball Corporation (2011); Baxter International Inc. (2022); Beam Inc. (2018); Becton (2024); Bio-Rad Laboratories (2014); Biomet (2017); BorgWarner Inc. (2020); Broadcom Corp. (2008); Bruker Corporation (2014); CHS Inc. (2022); Cablevision Systems Corporation (2009); Cadbury Limited (2017); Cardinal Health (2020); Clear Channel Outdoor Holdings (2023); Cognizant Technology Solutions Corporation (2019); Compass Minerals International (2022); Computer Sciences Corporation (2015); DXC Technology Company (2023); Dana Holding Corporation (as Successor Registrant to Dana Co (2009); Deere & Company (2024); Dell Inc. (2010); Delphi Corporation (2009); Delphi Corporation (2010); Diageo plc (2011); El Paso Corporation (2008); Elanco Animal Health Inc. (2024); Electronic Data Systems Corporation (2007); Exelon Corporation (2023); Express (2024); FCA US LLC (2019); FirstEnergy Corp. (2024); Flutter Entertainment (2023); Gartner (2023); General Electric Company (2020); General Motors Company (2017); General Motors Corporation (2009); GlobalSantaFe Corp. (2010); HP Inc. (2020); Halliburton Company (2017); Helmerich & Payne (2009); Herbalife Nutrition Ltd. (2020); Hilton Worldwide Holdings Inc. (2020); Honeywell International Inc. (Corrected) (2022); ITT Corporation (2009); Ingram Micro Inc. (2009); Interpublic Group of Companies (2008); Juniper Networks (2019); KBR (2018); Koninklijke Philips Electronics N.V. (2013); Koninklijke Philips N.V. (2023); Koppers Holdings Inc. (2022); L3 Technologies (2017); Lucent Technologies (2010); Marvell Technology Group (2019); Mattel (2022); Monsanto Company (2021); Monster Worldwide (2009); Motorola (2007); Mylan N.V. (2019); NEC Corporation (2008); Navistar International Corporation (2010); Newell Brands Inc. (2023); Nissan Motor Co. (2019); Noble Corporation (2010); Office Depot (2010); PACCAR Inc (2013); PPG Industries (2019); Panalpina (2010); Panasonic Corporation (2018); Pfizer Inc. / Wyeth LLC (2012); Portland General Electric Company (2024); Pride International (2010); RTX Corporation (2024); Rio Tinto plc (2023); Rockwell Automation (2011); Rollins (2022); Royal Dutch Shell plc (2010); Stanley Black & Decker (2023); Stryker Corporation (2018); Telia Company AB (2017); Tenet Healthcare Corporation (2009); Terex Corporation (2009); The Dow Chemical Company (2018); The Dun & Bradstreet Corporation (2018); The Goodyear Tire & Rubber Company (2015); Tidewater Inc. (2010); Transocean Inc. (2010); Travel + Leisure Co. (2026); Tupperware Brands Corporation (2022); Tyco International Ltd. (2012); United Continental Holdings (2016); United Parcel Service (2024); VMware (2022); Valeant Pharmaceuticals International (2020); Vereit (2020); Weatherford International PLC (2016); WellCare Health Plans (2009)

**LARGE (10): large-cap and/or SEC matter by title believed to be FCPA/disclosure/controls-only; not examined**

Brightpoint (2007); CVS Caremark Corporation (2007); Conrad M. Black (2008); Gentex Corporation (2023); GlaxoSmithKline plc (2016); LPB Capital d/b/a Family Office Group (2013); Moog Inc. (2024); National Energy Services Reunited Corp. (2024); Parker Drilling Company (2013); WPP plc (2021)

**NFS (52): SEC action not a financial-statement fraud/restatement case (FCPA, books-and-records, ICFR-only, disclosure-only, trading/offering fraud, or accountant/auditor proceeding)**

ADT Inc. (2018); Allion Healthcare (2009); Analogic Corporation (2016); Armor Holdings (2011); BIT Mining Ltd. (2024); Baker Tilly Hong Kong Limited (2014); Bennett Environmental (2007); Boros & Farrington Accountancy Corporation (2014); Brooge Energy Limited (2023); Calumet Specialty Products Partners (2019); Cambrex Corporation (2007); Canadian Solar (2014); Chisholm (2011); Cloopen Group Holding Limited (2024); Co-Diagnostics (2023); CytoDyn Inc. (2019); Dada Nexus Limited (2026); Deloitte Touche Tohmatsu LLC (2019); Delta & Pine Land Company (2007); Faro Technologies (2008); Frank's International N.V. (2023); Future FinTech Group Inc. (2023); Galena Biopharma (2017); Grant Thornton Audit Pty Limited (2015); Heartland Payment Systems (2018); Interface (2020); KPMG Inc. (2018); Kinross Gold Corporation (2018); Michael A. Rivers (2009); Mota Group (2018); NATCO Group Inc. (2010); Northwest Biotherapeutics (2019); PTC Inc. (2016); Paritz & Company (2017); Penn West Petroleum Ltd. (2020); Polycom (2018); Primoris Services Corporation (2018); Pyxus International (2018); Ranko Cucuz (2009); Savvides & Partners/PKF Cyprus (2009); SciClone Pharmaceuticals (2016); Singularity Future Technology (2025); Smith & Nephew PLC (2012); Smith & Wesson Holding Corporation (2014); TAL Education Group (2023); The Hain Celestial Group (2018); Thomas J. Saiz (2007); Under Armour (2021); Universal Corporation (2010); Watts Water Technologies (2011); Westinghouse Air Brake Technologies Corporation (2008); Willbros Group (2008)

**PRE (66): misstatement period pre-2005 / options-backdating era (FY<2008) and pre-XBRL quota (<= 40%) already filled; not verified**

Arthrocare Corporation (2011); Aspen Technology (2007); Atlas Air Worldwide Holdings (2007); Bally Technologies (2008); Beazer Homes USA (2008); Biovail Corporation (2011); Black Box Corporation (2009); Blue Coat Systems (2008); Bristow Group Inc. (2007); Brooks Automation (2008); CSK Auto Corporation (2009); China Yuchai International Limited (2010); Collins & Aikman Corporation (2010); Comverse Technology (2009); Con-way Inc. (2008); ConAgra Foods (2007); DHB Industries (2011); Diebold (2010); Diebold (2013); Dyadic International (2009); Entrade (2009); Ferro Corporation (2007); GSI Group (2011); Home Solutions of America (2009); Hudson Highland Group (2011); Integrated Electrical Services (2007); Integrated Silicon Solution (2007); JDA Software Group (2014); Krispy Kreme Doughnuts (2009); LaBarge (2011); Lattice Semiconductor Corp. (2007); LocatePlus Holdings Corporation (2010); Lumenis Ltd. (2009); MedQuist Inc.; John A. Donohoe; (2009); Mercury Interactive (2009); Michael Baker Corporation (2011); NIC (2011); Nortel Networks Corporation (2007); NorthWestern Corporation (2007); OM Group (2007); Pediatrix Medical Group (2009); Penthouse International (2007); Quest Software (2009); Quovadx (2007); Research in Motion Limited (2009); SafeNet (2009); Satyam Computer Services Limited d/b/a Mahindra Satyam (2011); Stratum Holdings (2009); Sunopta (2010); Sunrise Senior Living (2010); Sycamore Networks (2008); Symbol Technologies (2010); Symmetry Medical (2012); Take-Two Interactive Software (2009); Thor Industries (2011); Trident Microsystems (2010); UTStarcom (2008); UTStarcom (2009); Ulticom (2009); United Industrial Corporation (2009); United Rentals (2008); VeriFone Holdings (2009); Verint Systems Inc. (2010); Veritas Software Corporation (2007); Vitesse Semiconductor Corporation (2013); West Marine (2009)

**PRE (1): misstatement period pre-2008 / options-backdating era and pre-XBRL quota filled; not verified**

Merge Healthcare (2009)

**SHELL (51): micro-cap / shell / promotion-type case or post-FY2022 matter; not verified**

AXM Pharma (2008); Alpine 4 Holdings (2023); Ammo (2025); Anil Mathews; Rahul Agarwal; Kenneth M. Harlan; (2026); Apogee Technology (2009); Applied Wellness Corporation (2010); Artfest International (2013); Auscrete Corporation (2018); Blackout Media Corporation (2009); Cedric Kushner Promotions (2007); Celsius Holdings (2025); Chancellor Corporation (2008); China Holdings (2009); Cool Technologies (2018); DMK Pharmaceuticals Corporation (f/k/a Adamis Pharmaceutical (2025); Diatect International Corp. (2010); ECO 2 Plastics (2009); Eastgate Biotech Corporation (2018); Exotics.com (2010); Fortem Resources (2021); Freedom Environmental Services (2012); Frontier Oilfield Services (2018); GlobeTel Communications Corp. (2008); Gold Standard Mining Corp. (2012); GrubMarket (2025); HQDA Elderly Life Network (2021); Idle Media (2015); Igen Networks Corp. (2021); Imaging Diagnostic Systems (2013); Imperial Petroleum (2013); Imperiali (2012); Infrax Systems (2018); JBI (2013); Latch (2026); Lotus Bio-Technology Development Corporation (2018); MedLink International (2012); Meridian Holdings (2009); Omnia Wellness Inc. (2023); PowerCold Corporation (2009); Ramoil Management Ltd. et al. (2007); ReShape Lifesciences Inc. (2023); Rokk3r (2021); ShiftPixy (2021); Spongetech Delivery Systems (2010); Sunrise Solar Corporation (2012); TMT Capital Corporation (2009); Trutankless (2021); Tsukuda-America Inc. Brenda P. Murray (2010); Tsukuda-America Inc. et al. (2010); Vivic Corp. (2023); WMDS (2009)

**NOTX (35): XBRL-era or small-cap candidate not examined further (industry/year strata and pre-XBRL quota already satisfied, or documentation not pursued); not verified**

Aeon Global Health Corp. (2020); Agria Corporation (2018); Amyris (2021); Apex Global Brands Inc. (2020); Axesstel (2018); Cardiff Lexington Corporation (f/k/a Cardiff International (2018); China Intelligent Lighting (2013); China MediaExpress Holdings (2014); China Natural Gas (2013); China North East Petroleum Holdings Limited (2012); China Ruitai International Holdings Co. (2013); China Sky One Medical (2012); Dasan Zhone Solutions (2018); Diamond Foods (2014); FalconStor Software (2012); First Hartford Corporation (2018); Fuqi International (2013); Ideanomics (2024); Key Energy Services (2016); Keyuan Petrochemicals (2013); Life Partners Holdings (2012); MDC Partners Inc. (2017); Maxwell Technologies (2018); Medifast (2013); Medifirst Solutions (2018); Powersecure International (2016); ProPetro Holding Corp. (2021); RINO International Corporation (2013); Sequential Brands Group (2021); SinoTech Energy Limited (2012); Subaye (2013); Taronis Technologies (2022); The St. Joe Company (2015); TheStreet (2012); Vantage Drilling International (2018)

### 6.4 Additional names from memory (outside the AAER company index; NOT verified unless stated)

UniTek Global Services (selected; verified), Barrett Business Services, ArthroCare, Diamond Foods, Cubic, Ixia, KIT digital, Iconix, MiMedx, Miller Energy, Tupperware (all examined and dropped in holdout 1 for ambiguous revelations; not re-examined), AgFeed, American Superconductor, Medbox, Cemtrex, MusclePharm, ITT Educational Services, Babcock & Wilcox, Lihua International, ChinaCast, Puda Coal, A-Power, Bankrate, MagnaChip, OCZ Technology, Comverse (all not verified: considered by name only, no filing opened).

### 6.5 Counts

Considered 461 names: 434 AAER-index entities + UniTek + 12 holdout-1 names (re-listed, not re-examined) + 14 other names from memory (6.4 minus those counted above). Selected 15 (14 from the index + UniTek). Examined against EDGAR and dropped or not selected: 18 in 6.2 (all but Koss/GTT/UniTek-type exceptions appear in the index sweep). Dropped without opening a filing: the rest, mostly financial institutions (65), large-cap/FCPA-type (120), non-financial-statement matters (52), pre-2008 fiscal years / options backdating (67), micro-cap shells (51), and unexamined small/mid-cap XBRL-era names (35). Top drop reasons overall: large-cap/non-FS type, financial institution, pre-XBRL-era misstatement, no feasible control, ambiguous or pre-dated revelation.

## 7. Caveats (honest limits)

* Labels derive from SEC releases and company filings; clean means "nothing found", not proof (checks per control: the four 10-K texts FY..FY+3, an EDGAR
  8-K/NT screen over FY..FY+3 and the AAER index; only a few web searches).
* Revelation dates are the first public filing/press date found in EDGAR. Short-seller or press commentary before those dates may exist for any case
  (not exhaustively searched). For PSIX the first signal is a delay notice; for REVL it is the press-release date (8-K filed three days later).
* Label tiers differ: three issuers have only controls/reporting orders (Stein Mart, Plug Power) or an order whose findings concern other periods
  (Swisher: 2011 quarters, analysed FY2010; Volt: FY2007 carried in FY2008); UniTek has enforcement only against individuals (details from secondary
  summaries). These are properties of the labels, not reasons for selection or exclusion.
* Several analysed filings already show distress language (Hill: material weaknesses and going-concern; Stein Mart: two material weaknesses; Volt: material
  weakness text), which is a property of the cases, not examined for detectability.
* Weak matches: HIL/EXPO, PSIX/KAI and SWSH/SYNL are 2-digit-SIC matches only (Swisher/Synalloy is the weakest industry match); PLUG/EAF has an assets ratio of 1.98;
  fiscal-year-end mismatches: REVL (Dec) vs LYTS (Jun 2017), HEV (Dec) vs RSTI (Sep 2010), SABA (May) vs LGTY (Apr), VOL (Nov) vs AMN (Dec), PSIX (Dec) vs KAI (2016-01-02), SWSH (Dec) vs SYNL (2011-01-01): as_of dates differ by up to ~8 months.
* Pre-XBRL pairs (5 of 15: ENER1/RSTI, SABA/LGTY, SWSH/SYNL, VOL/AMN, ISLN/APKT) need the statement-table parser; assets come from the filings' balance
  sheets or comparative facts of later filings. The analysed accessions of those cases have no XBRL facts in companyfacts.
* Not selected for detectability, and nothing about detectability was examined.
* Terminal events (bankruptcy/acquisition dates) were not researched (collapse_date is None).
* Not verified: every name in 6.3 outside the explicit lists, and every name in 6.4 except UniTek. Only the 15 selected, the 18 in 6.2 and the 15 controls
  (plus about 25 skipped control candidates) were checked against filings.
