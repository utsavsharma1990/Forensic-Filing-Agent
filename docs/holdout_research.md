# HOLDOUT research log (SEALED)

**SEALED: do not read, grep or run before the v2 freeze (docs/V2_FREEZE.md).** Nobody building v2 may open this file or
`evaluation/holdout_cases.py`. The selection agent never ran the forensic system (no graph.pipeline, agents/*, evaluator) on
any candidate and never looked at how a candidate would score. Machine-readable result: `evaluation/holdout_cases.py`
(12 fraud + 12 matched clean). Protocol: `docs/V2_PROTOCOL.md`. Researched 2026-10-16.

## 1. Method

1. Candidate pool: US-listed companies with SEC accounting / financial-statement fraud or restatement-driven enforcement,
   2005-2022, taken from well-known cases and the orchestrator's suggestions (each re-verified, none trusted).
   Excluded by protocol: the 12 dev cases, Kraft Heinz, Bed Bath & Beyond, Super Micro, Nikola, Enron, WorldCom, Luckin,
   Lordstown, Virgin Galactic, any company in tests/ or `.cache/text`, AAPL/MSFT/JNJ/PG/MMM/BRK-B.
2. For each candidate: EDGAR submissions (cached `tools.edgar_api`, User-Agent `forensic-filing-agent contact@example.com`, never a
   personal address): annual reports, 8-K items (4.02/4.01/2.06) and NT 10-K/10-Q between the candidate 10-K and the first revelation;
   the text of the first revelation filing; the SEC enforcement release found by web search; companyfacts for XBRL; the 10-K text
   scanned for pre-existing subpoena / investigation / non-boilerplate material-weakness language.
3. Selection by criteria and documentation quality only; industries and years stratified. No scoring information was used.
4. Control per fraud case: XBRL frames `Assets` at the fiscal-year end (CY frames Q1-Q4 of the year) intersected with the SIC
   listings of the same 3-digit code (ten SIC4 codes), assets 0.3x-3x, revenue > 0, a 10-K for the same fiscal-year label (D12),
   zero NT 10-K/NT 10-Q and zero 8-K item 4.01/4.02/2.06 in the window FY-30d .. FY+3y+150d and at least four 10-Ks in that window.
   Candidates were then taken in order of closeness of the asset ratio (|ln ratio|); the four annual reports FY..FY+3 were
   text-scanned (restatement excluding "amended and restated", non-boilerplate "material weakness", "substantial doubt", SEC
   subpoena/investigation), 10-K/A and flagged 8-Ks were read, and web checks were made. The first candidate to pass was used.
   (When no SIC-3 candidate passed, the nearest same 2-digit group was used; see section 5.)
5. Validation (`.cache/holdout/validate.py`): all keys of the dev schema present, dates parse, `analysis_filing_date <
   public_revelation_date` for all 12 fraud cases, no other 10-K/20-F filed between the analysed filing and the revelation,
   accession/form/filing date/report date equal EDGAR submissions, the EDGAR filing index page fetches, XBRL facts exist for the
   accession and `Assets` equals `total_assets`, matched pairs reciprocal, same fiscal year, assets ratio in 0.3-3.0, same 2-digit SIC.
   Result: 0 errors.

## 2. Summary

| | n |
|---|---|
| Fraud cases | 12 (11 XBRL era, 1 pre-XBRL = 92% XBRL) |
| Clean controls | 12 (11 XBRL era, 1 pre-XBRL) |
| fraud_nature | 12 financial_statement (100%); 0 disclosure_claims |
| Fiscal years (fraud) | 2004, 2011, 2012, 2014 x2, 2015, 2016 x2, 2017 x2, 2018 x2 |
| Industries (SIC) | biotech 2836; software/IT 7371, 7372, 7373; trucking 4213; freight 4731; heavy construction 1600; specialty contractor 1700; computer hardware 3572, 3578; medical devices 3841; food 2090 |
| Pairs on the same 3-digit SIC | 10 of 12 (GVA/MTZ and PTRY/RAH share only the 2-digit group) |
| Months from analysed filing to first revelation | 2.5 to 12.6 |

## 3. Fraud cases

| Ticker | Company | CIK | SIC | FY | Form | Accession | Filed | First public revelation | Months | Assets ($M) | XBRL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OSIR | Osiris Therapeutics, Inc. | 0001360886 | 2836 | 2014 | 10-K | 0001047469-15-002532 | 2015-03-20 | 2015-11-06 | 7.6 | 98.1 | yes |
| TNGO | Tangoe, Inc. | 0001182325 | 7372 | 2014 | 10-K | 0001047469-15-002289 | 2015-03-16 | 2016-03-07 | 11.7 | 215.0 | yes |
| CGI | Celadon Group, Inc. | 0000865941 | 4213 | 2016 | 10-K | 0001008886-16-000363 | 2016-09-13 | 2017-05-01 | 7.6 | 1,103.3 | yes |
| SNCR | Synchronoss Technologies, Inc. | 0001131554 | 7371 | 2016 | 10-K | 0001131554-17-000037 | 2017-02-27 | 2017-05-15 | 2.5 | 1,164.7 | yes |
| RRTS | Roadrunner Transportation Systems, Inc. | 0001440024 | 4731 | 2015 | 10-K | 0001440024-16-000049 | 2016-03-01 | 2017-01-30 | 11.0 | 1,326.1 | yes |
| GVA | Granite Construction Incorporated | 0000861459 | 1600 | 2018 | 10-K | 0001564590-19-003791 | 2019-02-22 | 2020-03-02 | 12.3 | 2,476.6 | yes |
| USAT | USA Technologies, Inc. (now Cantaloupe, Inc.) | 0000896429 | 3578 | 2017 | 10-K | 0001558370-17-006780 | 2017-08-23 | 2018-09-11 | 12.6 | 97.7 | yes |
| QTM | Quantum Corporation | 0000709283 | 3572 | 2017 | 10-K | 0001628280-17-006127 | 2017-06-01 | 2018-02-08 | 8.3 | 225.0 | yes |
| OFIX | Orthofix International N.V. (now Orthofix Medical Inc.) | 0000884624 | 3841 | 2012 | 10-K | 0001193125-13-087561 | 2013-03-01 | 2013-07-29 | 4.9 | 504.3 | yes |
| LIME | Lime Energy Co. | 0001065860 | 1700 | 2011 | 10-K | 0001104659-12-018932 | 2012-03-16 | 2012-07-17 | 4.0 | 99.6 | yes |
| TEUM | Pareteum Corporation | 0001084384 | 7373 | 2018 | 10-K | 0001144204-19-014694 | 2019-03-18 | 2019-10-21 | 7.1 | 161.0 | yes |
| PTRY | American Italian Pasta Company | 0000849667 | 2090 | 2004 | 10-K | 0000922907-04-000547 | 2004-12-15 | 2005-08-09 | 7.8 | 748.4 | no |

### Fraud case details and sources

**OSIR - Osiris Therapeutics, Inc.** (FY2014, period end 2014-12-31)
* Revelation: Q3-2015 earnings release (8-K item 2.02) disclosed a review of revenue recognition on a distributor contract; NT 10-Q 2015-11-10; 8-K item 4.02 on 2015-11-20 restated Q1-Q3 2015 and 2014 product revenue.
* Fraud type: Premature / improper revenue recognition (consignment, backdated documents, inflated prices). Label strength: SEC civil complaint 2017-11-03 (fraud charges vs company settled $1.5M and four executives)
* Validity: FY2014 10-K filed 2015-03-20, 7.5 months before the first public disclosure (2015-11-06). An NT 10-K (2015-03-17) delayed it by 3 days for audit completion only, with no accounting allegation.
* Caveats: The 2014 correction was ~$1.1M on $59.9M of 2014 product revenue (small); the FY2013 10-K disclosed a remediated tax-accounting material weakness (so MW language is present in the analysed filing).
* Sources: https://www.sec.gov/Archives/edgar/data/1360886/000110465915076444/; https://www.sec.gov/Archives/edgar/data/1360886/000110465915080467/; https://www.sec.gov/litigation/litreleases/2017/lr23978.htm; https://www.sec.gov/news/press-release/2017-207

**TNGO - Tangoe, Inc.** (FY2014, period end 2014-12-31)
* Revelation: 8-K item 4.02 (event 2016-03-04, filed 2016-03-07): restatement of 2013, 2014 and Q1-Q3 2015; FY2015 10-K never filed on time (NT 10-K 2016-03-15).
* Fraud type: Revenue overstated via improper recognition and artificial transactions (~$40M over 2013-2015). Label strength: SEC complaint 2018-09-04 (company and three executives settled; fraud charges)
* Validity: FY2014 10-K filed 2015-03-16, ~12 months before the 2016-03-07 restatement notice.
* Caveats: Misstated revenue was ~7% of reported revenue; analysed filing is the original (pre-restatement) 10-K.
* Sources: https://www.sec.gov/Archives/edgar/data/1182325/000110465916102988/; https://www.sec.gov/litigation/litreleases/2018/lr24255.htm; https://www.sec.gov/newsroom/press-releases/2018-175

**CGI - Celadon Group, Inc.** (FY2016, period end 2016-06-30)
* Revelation: 8-K items 1.01/4.02 filed 2017-05-01 (event 2017-04-25): FY2016 and Q1-Q2 FY2017 statements no longer to be relied upon; Audit Committee investigation. NT 10-Q 2017-02-09 earlier concerned a litigation judgement accrual, not accounting.
* Fraud type: Concealed impairments/losses by selling and buying back trucks at inflated prices. Label strength: SEC civil complaint 2019-04-25 (company admitted fraud; restitution $42.2M; DOJ resolution)
* Validity: FY2016 (June FYE) 10-K filed 2016-09-13, 7.5 months before the 2017-05-01 non-reliance notice.
* Caveats: Misstatement ~$20M of impairments vs ~$30M pre-tax income (large relative to earnings).
* Sources: https://www.sec.gov/Archives/edgar/data/865941/000100888617000064/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24459; https://www.sec.gov/newsroom/press-releases/2019-60

**SNCR - Synchronoss Technologies, Inc.** (FY2016, period end 2016-12-31)
* Revelation: Press release / 8-K item 7.01 (2017-05-15): Q1-2017 results delayed after a review of accounting for prior-period transactions by new CEO/CFO and the audit committee; 8-K 4.02 2017-06-13 (FY2016, FY2015 restated).
* Earlier hints: 2017-04-27 new CEO/CFO announced (no accounting allegation); 2017-05-12 NT 10-Q.
* Fraud type: Improper revenue recognition (no persuasive evidence, upfront license revenue); restated ~$190M cumulative revenue. Label strength: SEC order/complaint 2022-06-07 (company settled $12.5M; CFO and controller charged)
* Validity: FY2016 10-K filed 2017-02-27, ~2.5 months before the 2017-05-15 disclosure.
* Caveats: Short horizon between filing and revelation; the FY2017 10-K was only filed 2018-07-02.
* Sources: https://www.sec.gov/Archives/edgar/data/1131554/000113155417000073/; https://www.sec.gov/Archives/edgar/data/1131554/000110465917038974/; https://www.sec.gov/newsroom/press-releases/2022-101

**RRTS - Roadrunner Transportation Systems, Inc.** (FY2015, period end 2015-12-31)
* Revelation: 8-K items 2.06/4.02 (2017-01-30): accounting discrepancies at two subsidiaries; prior-period adjustments of $20-25M expected; Board investigation (opened Nov 2016).
* Earlier hints: 2016-11-10 NT 10-Q cited a covenant-ratio calculation mistake (no accounting allegation).
* Fraud type: Improperly deferred/unrecorded expenses and unreconciled balances to hit earnings targets (2013-2017). Label strength: SEC settled order vs company (disgorgement ~$7.1M + $2.5M interest); 2019 SEC fraud charges vs former CFO and two employees
* Validity: FY2015 10-K filed 2016-03-01, 8 months before the first hint (2016-11-10) and 11 months before 2017-01-30.
* Caveats: An NT 10-K was filed the same day (2016-03-01) as the 10-K; its text contains no reason.
* Sources: https://www.sec.gov/Archives/edgar/data/1440024/000144002417000002/; https://www.sec.gov/Archives/edgar/data/1440024/000144002416000074/; https://www.sec.gov/newsroom/press-releases/2019-51

**GVA - Granite Construction Incorporated** (FY2018, period end 2018-12-31)
* Revelation: 2020-03-02 press release (8-K 2.02): Audit/Compliance Committee investigation of prior-period reporting at the Heavy Civil Operating Group; 10-K delayed (NT 10-K 2020-03-03); 2017-2019 later restated.
* Fraud type: Improper deferral of expected costs in project forecasts (percentage-of-completion revenue). Label strength: SEC order/complaint 2022 (company $12M penalty; fraud charges, injunction)
* Validity: FY2018 10-K filed 2019-02-22, ~12 months before the 2020-03-02 disclosure.
* Caveats: Largest fraud company in the set (assets $2.5B); the only other SIC-160 peer in range (KBR) had an SEC order in the analysed year (see matching table).
* Sources: https://www.sec.gov/Archives/edgar/data/861459/000143774920004057/; https://www.sec.gov/Archives/edgar/data/861459/000143774920004188/; https://www.sec.gov/newsroom/press-releases/2022-150; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25507

**USAT - USA Technologies, Inc. (now Cantaloupe, Inc.)** (FY2017, period end 2017-06-30)
* Revelation: 2018-09-11 press release (8-K 8.01): FY2018 10-K delayed; Audit Committee internal investigation of contractual arrangements and their accounting; NT 10-K 2018-09-13; 8-K 4.02 2019-02-06 (FY2017 and FY2018 quarters restated).
* Fraud type: Bill-and-hold sales and shipments of unordered devices to inflate quarterly revenue. Label strength: SEC settled order 2023 (company $1.5M penalty; two former officers charged)
* Validity: FY2017 (June FYE) 10-K filed 2017-08-23, ~12.5 months before the 2018-09-11 disclosure.
* Caveats: The analysed 10-K already discloses an earlier, different problem (material weakness at 2015/2016 FYEs and an associated class action); the FY2017 restatement was ~$2.56M (SEC: $4.61M total, 3.5% overstatement).
* Sources: https://www.sec.gov/Archives/edgar/data/896429/000114036118038228/; https://www.sec.gov/enforcement-litigation/administrative-proceedings/33-11202-s

**QTM - Quantum Corporation** (FY2017, period end 2017-03-31)
* Revelation: 2018-02-08 press release/8-K: Q3 FY2018 results postponed; NT 10-Q 2018-02-12 discloses an SEC subpoena (2018-01-11) on revenue-recognition accounting and controls; 8-K 4.02 2018-09-14 restated FY2015-FY2017 and quarters.
* Fraud type: Revenue recognised on channel-partner deals with undisclosed side terms (repeated recognition errors). Label strength: restatement + SEC settled order 34-87812 (internal accounting controls violations, $1M penalty); no fraud finding against the issuer
* Validity: FY2017 (March FYE) 10-K filed 2017-06-01, 8 months before the 2018-02-08 disclosure.
* Caveats: Weakest label in the set: controls-only SEC order; restatement is the ground-truth event.
* Sources: https://www.sec.gov/Archives/edgar/data/709283/000162828018001297/; https://www.sec.gov/Archives/edgar/data/709283/000162828018001442/; https://www.sec.gov/Archives/edgar/data/709283/000119312518274209/; https://www.sec.gov/enforcement-litigation/administrative-proceedings/34-87812-s

**OFIX - Orthofix International N.V. (now Orthofix Medical Inc.)** (FY2012, period end 2012-12-31)
* Revelation: 2013-07-29 press release (8-K 8.01 filed 2013-07-30): Audit Committee independent review of revenue recognition; 8-K 4.02 filed 2013-08-07; FY2012 10-K/A filed 2014-03-24.
* Fraud type: Premature revenue recognition (shipment before contingencies resolved) incl. Spine segment and Brazil subsidiary. Label strength: SEC settled order 2017-01 (company admitted wrongdoing; $14M incl. FCPA; misstatements 2011-Q1 2013)
* Validity: Original FY2012 10-K filed 2013-03-01, 5 months before the 2013-07-29 disclosure.
* Caveats: Order combines accounting and FCPA (Brazil) findings; legacy HHS-OIG subpoena (Blackstone) disclosed in the 10-K.
* Sources: https://www.sec.gov/Archives/edgar/data/884624/000119312513308166/; https://www.sec.gov/Archives/edgar/data/884624/000119312513322803/; https://www.sec.gov/newsroom/press-releases/2017-18; https://www.sec.gov/files/litigation/admin/2017/33-10281.pdf

**LIME - Lime Energy Co.** (FY2011, period end 2011-12-31)
* Revelation: 8-K item 4.02 (event 2012-07-15, filed 2012-07-17): FY2010, FY2011 and Q1-2012 statements should not be relied upon; some revenue improperly recorded.
* Fraud type: Revenue booked early or on non-existent jobs (~$20M over 2010-2012). Label strength: SEC complaint 2016 (company $1M settlement; four former executives charged)
* Validity: Original FY2011 10-K filed 2012-03-16, 4 months before the 2012-07-17 notice.
* Caveats: Smallest fraud company (assets ~$100M); net losses in the analysed year already.
* Sources: https://www.sec.gov/Archives/edgar/data/1065860/000110465912049223/; https://www.sec.gov/news/pressrelease/2016-218.html; https://www.sec.gov/files/litigation/complaints/2016/comp-pr2016-218.pdf

**TEUM - Pareteum Corporation** (FY2018, period end 2018-12-31)
* Revelation: 8-K item 4.02 (2019-10-21): FY2018 and Q1-Q2 2019 financial statements should no longer be relied upon; FY2018 restated 2020-12-14.
* Fraud type: Revenue recorded from non-binding purchase orders; auditor confirmation process manipulated. Label strength: SEC settled order 2021 (company) and complaint 2023 (three former executives; fraud charges)
* Validity: Original FY2018 10-K filed 2019-03-18, 7 months before the 2019-10-21 notice.
* Caveats: Earlier press/short-seller commentary in 2019 was NOT exhaustively searched (8-Ks between filing and revelation show none). The analysed 10-K itself reports material weaknesses at 2018-12-31. Assets jumped 6x in 2018 (acquisitions).
* Sources: https://www.sec.gov/Archives/edgar/data/1084384/000110465919055290/; https://www.sec.gov/enforce/33-10975-s; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25860

**PTRY - American Italian Pasta Company** (FY2004, period end 2004-10-01)
* Revelation: 2005-08-09 press release (8-K 2.02/2.06 filed 2005-08-11): third-quarter results and 10-Q delayed, Audit Committee investigation of accounting practices; 8-K 4.02 2005-10-25 (FY2002-FY2004 and quarters not to be relied upon).
* Fraud type: Overstated pre-tax income FY2002-Q2 FY2004 (~$59M, 66%) via improper accounting adjustments. Label strength: SEC complaint + AAER 2008-09-15 (company and former CEO/CFO/others; fraud charges)
* Validity: FY2004 (FYE 2004-10-01) 10-K filed 2004-12-15, 8 months before the 2005-08-09 disclosure.
* Caveats: Only pre-XBRL case; the SEC-alleged scheme ran FY2002-Q2 FY2004, so only the first half of FY2004 was affected, but the 4.02 notice covers FY2004 as well. Assets read from the filing's own balance sheet (total assets $748,410K).
* Sources: https://www.sec.gov/Archives/edgar/data/849667/000092290705000482/; https://www.sec.gov/Archives/edgar/data/849667/000092290705000683/; https://www.sec.gov/enforcement-litigation/litigation-releases/lr-20715; https://www.sec.gov/news/press/2008/2008-200.htm

## 4. Clean controls

| Ticker | Company | CIK | SIC | FY | Accession | Filed | Assets ($M) | XBRL | Partner |
|---|---|---|---|---|---|---|---|---|---|
| NSTG | NanoString Technologies, Inc. (EDGAR: NS Wind Down Co., Inc.) | 0001401708 | 2836 | 2014 | 0001193125-15-091371 | 2015-03-13 | 102.7 | yes | OSIR |
| LPSN | LivePerson, Inc. | 0001102993 | 7372 | 2014 | 0001628280-15-001726 | 2015-03-12 | 239.8 | yes | TNGO |
| LSTR | Landstar System, Inc. | 0000853816 | 4213 | 2016 | 0001193125-17-056249 | 2017-02-24 | 1,096.6 | yes | CGI |
| EPAM | EPAM Systems, Inc. | 0001352010 | 7371 | 2016 | 0001352010-17-000006 | 2017-03-01 | 925.8 | yes | SNCR |
| HUBG | Hub Group, Inc. | 0000940942 | 4731 | 2015 | 0001564590-16-013549 | 2016-02-26 | 1,301.1 | yes | RRTS |
| MTZ | MasTec, Inc. | 0000015615 | 1623 | 2018 | 0000015615-19-000011 | 2019-02-28 | 4,440.0 | yes | GVA |
| ALOT | AstroNova, Inc. | 0000008146 | 3577 | 2017 | 0001193125-18-113108 | 2018-04-10 | 122.3 | yes | USAT |
| MITK | Mitek Systems, Inc. | 0000807863 | 3577 | 2017 | 0000807863-17-000080 | 2017-11-30 | 71.7 | yes | QTM |
| ICUI | ICU Medical, Inc. | 0000883984 | 3841 | 2012 | 0000883984-13-000016 | 2013-02-26 | 428.5 | yes | OFIX |
| AGX | Argan, Inc. | 0000100591 | 1700 | 2011 | 0001193125-12-161077 | 2012-04-13 | 205.3 | yes | LIME |
| BAND | Bandwidth Inc. | 0001514416 | 7372 | 2018 | 0001514416-19-000011 | 2019-02-15 | 150.4 | yes | TEUM |
| RAH | Ralcorp Holdings, Inc. | 0001029506 | 2040 | 2004 | 0001068800-04-000720 | 2004-12-14 | 1,221.6 | no | PTRY |

* **NSTG**: Clean control for OSIR (FY2014, SIC 2836, assets ratio 1.05). Text scan of the FY2014-FY2017 10-Ks: no restatement, material weakness, going-concern doubt or SEC subpoena. The EDGAR name reflects later wind-down events outside the FY..FY+3 window (not researched).
* **LPSN**: Clean control for TNGO (FY2014, SIC 7372, assets ratio 1.12). Skipped Imperva (material weakness at 2014-09-30). Only amendment in window is a 10-K/A (2016-01-22) revising the auditor consent date. Text scan FY2014-FY2017 found only audit-report boilerplate.
* **LSTR**: Clean control for CGI (FY2016, SIC 4213, assets ratio 0.99). Calendar-year FYE vs Celadon's June FYE: same fiscal-year label, ~6 months later as_of. Asset-light truckload/brokerage model differs from Celadon's asset-heavy fleet. Text scan found only an ASC 606 'not restated' note.
* **EPAM**: Clean control for SNCR (FY2016, SIC 7371, assets ratio 0.80). FY2018 10-K 'restated' prior cash-flow presentation for ASU 2016-18 adoption (presentation change, not an error).
* **HUBG**: Clean control for RRTS (FY2015, SIC 4731, assets ratio 0.98). A 10-K/A (2018-01-05) for FY2016 only added a date to the Section 906 certification. Hub restated in 2002 and again for 2025 quarters (both far outside the window).
* **MTZ**: Clean control for GVA (FY2018, SIC 1623 vs 1600: same 2-digit major group 16 only, because SIC 160 has no passing peer; assets ratio 1.79). Skipped KBR (SEC order in analysed year) and Primoris (SEC ICFR order 2018-09). MasTec had a 2014-15 Audit Committee investigation of percentage-of-completion estimates and an SEC formal investigation closed with no enforcement action (notice 2016-11-16), i.e. before the analysed year. Text scan FY2018-FY2021 clean.
* **ALOT**: Clean control for USAT (SEC fy=2017 for FYE 2018-01-31 per D12; SIC 3577 vs 3578, assets ratio 1.25). Fiscal-year end is 7 months after USAT's. A web-search excerpt of its FY2018 10-K mentions an accounting error judged immaterial to prior periods (no restatement, no 8-K 4.02).
* **MITK**: Clean control for QTM (FY2017, SIC 3577 vs 3572, assets ratio 0.32 - near the lower bound). Skipped Digi International (material weakness remediated in FY2017). Mitek later restated interim periods (2022-10 and 2023-05) and faces an SEC investigation; these fall outside the FY2017..FY2020 window.
* **ICUI**: Clean control for OFIX (FY2012, SIC 3841, assets ratio 0.85). 10-K/A of 2015-04-30 (FY2014) only added Part III. Text scan FY2012-FY2015 clean.
* **AGX**: Clean control for LIME (SEC fy=2011 for FYE 2012-01-31, SIC 1700, assets ratio 2.06 - the only passing peer in SIC 170). Fiscal-year end is one month after Lime's. 10-K/A filings in 2014 re-filed Item 8 for FY Jan-2014 without restatement; Argan restated FY2005 (long before the window). Moved Nasdaq to NYSE in 2013.
* **BAND**: Clean control for TEUM (FY2018, SIC 7372 vs 7373, assets ratio 0.93). Text scan FY2018-FY2021 shows only risk-factor boilerplate on restatements/subpoenas.
* **RAH**: Clean control for PTRY (FY2004, SIC 2040 vs 2090: same 2-digit group 20 only, since the only SIC-209 peers in range (Reddy Ice restated in its FY2004 10-K; McCormick >3x) fail; assets ratio 1.63 from the filing's balance sheet ($1,221.6M). 'Restatement' mentions in its 10-Ks concern an equity investee (Vail Resorts); the 2007 8-K 4.01 concerned its savings plan's auditor only. Pre-XBRL.

## 5. Matching table

| Fraud | Control | FY (fraud/control) | Period end (fraud/control) | SIC (fraud/control) | Assets ratio | Same 3-digit SIC |
|---|---|---|---|---|---|---|
| OSIR | NSTG | 2014/2014 | 2014-12-31/2014-12-31 | 2836/2836 | 1.05 | yes |
| TNGO | LPSN | 2014/2014 | 2014-12-31/2014-12-31 | 7372/7372 | 1.12 | yes |
| CGI | LSTR | 2016/2016 | 2016-06-30/2016-12-31 | 4213/4213 | 0.99 | yes |
| SNCR | EPAM | 2016/2016 | 2016-12-31/2016-12-31 | 7371/7371 | 0.79 | yes |
| RRTS | HUBG | 2015/2015 | 2015-12-31/2015-12-31 | 4731/4731 | 0.98 | yes |
| GVA | MTZ | 2018/2018 | 2018-12-31/2018-12-31 | 1600/1623 | 1.79 | no (same 2-digit) |
| USAT | ALOT | 2017/2017 | 2017-06-30/2018-01-31 | 3578/3577 | 1.25 | yes |
| QTM | MITK | 2017/2017 | 2017-03-31/2017-09-30 | 3572/3577 | 0.32 | yes |
| OFIX | ICUI | 2012/2012 | 2012-12-31/2012-12-31 | 3841/3841 | 0.85 | yes |
| LIME | AGX | 2011/2011 | 2011-12-31/2012-01-31 | 1700/1700 | 2.06 | yes |
| TEUM | BAND | 2018/2018 | 2018-12-31/2018-12-31 | 7373/7372 | 0.93 | yes |
| PTRY | RAH | 2004/2004 | 2004-10-01/2004-09-30 | 2090/2040 | 1.63 | no (same 2-digit) |

Control candidates that were skipped (reason, checked from filings):

| Case | Skipped candidate | Reason |
|---|---|---|
| TNGO | Imperva | FY2014 10-K reports a material weakness at 2014-09-30 (in the analysed year) |
| GVA | KBR (only SIC-160 peer in range) | SEC subpoena and July 2018 settlement over its 2013 restatement, disclosed in the FY2018 10-K |
| GVA | Primoris | SEC settled order 2018-09 for internal-accounting-control violations (contingent cost estimates), in the analysed year |
| QTM | Digi International | FY2017 10-K discusses a material weakness (prior year) remediated in FY2017 |
| USAT | PAR Technology | material weaknesses and an SEC subpoena (2017) in the analysed filing |
| PTRY | Reddy Ice (only SIC-209 peer in range with a 10-K) | restated in its own FY2004 10-K (8-K 4.02 2005-03-31) |
| PTRY | Tootsie Roll | 10-K main document lacks the financial statements (EX-13) |
| PTRY | McCormick | assets > 3x |
| all | others in the pools | removed by the automatic screen (NT filings, 8-K 4.01/4.02/2.06, fewer than four 10-Ks in the window, no revenue) or ranked below the chosen control |

Screen details are in `.cache/holdout/` (rank_*.json, match*.py, rank.py, choose.py, multi.py; scratch).

## 6. Candidate pool and drop reasons

### 6.1 Selected (12)
OSIR, TNGO, CGI, SNCR, RRTS, GVA, USAT, QTM (Quantum), OFIX, LIME, TEUM (Pareteum), PTRY (American Italian Pasta).

### 6.2 Examined against EDGAR filings and dropped (12)
| Candidate | CIK | Reason |
|---|---|---|
| ArthroCare | 1005010 | Citron Research published its first allegations on 2008-01-28, before the FY2007 10-K (2008-02-29); 4.02 came 2008-07-21. The FY2006 10-K would be the strict choice, but whether earlier (2007) allegations existed was not resolved. |
| Hain Celestial | 910406 | SEC order (2018) found books-and-records/controls violations only; Hain concluded no restatement was needed. No restatement or fraud finding, so no financial-statement label. |
| Hertz Global Holdings | 1364479 | NT 10-K on 2014-03-03 for the FY2013 10-K (filed 2014-03-19) and an NT 10-K on the FY2012 filing day, no stated reasons; first 4.02 on 2014-06-06. First public revelation relative to the last annual report is ambiguous. |
| Barrett Business Services | 902791 | Workers' compensation accrual announced 2014-10-28, before the FY2014 10-K (2015-03-16), so FY2014 is invalid; the FY2013 10-K (2014-03-14) is possible but its inclusion in the restated periods was not verified. |
| Diamond Foods | 1320947 | Audit Committee investigation announced about 2011-11-01 (8-K 8.01) after the FY2011 10-K (2011-09-15); earlier public attention (2011-10-03 media advisory on grower payments) was not resolved; food sector already represented. |
| Tupperware Brands | 1008654 | SEC order (2022-09-29) concerns controls/books-and-records only (Fuller Mexico); the underlying issue was public from 2019-2020, before the FY2021 10-K (2022-02-23); restatement notice 2023-03-12. Ambiguous. |
| Cubic Corp | 26076 | 4.02 on 2011-08-05 precedes the FY2011 10-K (2011-11-22); the FY2010 filing is possible but no SEC accounting enforcement was verified. |
| Ixia | 1120295 | 4.02 on 2013-04-03 preceded the FY2012 10-K (2013-04-04); FY2011 inclusion in restated periods and SEC enforcement not verified. |
| KIT digital | 1076700 | NT 10-Qs (2012-05-11, 2012-08-08) carry no reason text; first documented revelation unclear; 4.02 on 2012-11-21. |
| Iconix Brand | 857737 | CEO resignation 2015-08-05, NT 10-Q 2015-08-10, 4.02 2015-11-05; first accounting revelation ambiguous; surplus after 12 were verified. |
| MiMedx | 1376339 | FY2015 10-K/A filed 2017-02-22 and several 2016-2018 events; first revelation not pinned down. |
| Miller Energy Resources | 785968 | Valuation of the Alaska assets was publicly questioned long before the FY2014 10-K; first revelation not pinned down. |

Reasons: ambiguous or pre-dated revelation 11, no restatement/fraud label 1.

### 6.3 Named but not pursued after 12 cases were verified (28; NOT verified against filings, no claim about eligibility)
Weatherford International (assets about $17B, no 0.3-3x control feasible), Computer Sciences Corp (large), VEREIT / American Realty Capital Properties
(4.02 2014-10-29, FY2013 10-K 2014-02-27, assets about $20B; REIT control not pursued), GE 2018 (assets about $300B), Akorn (data integrity rather than
financial statements), Under Armour (disclosure-type SEC order), OCZ Technology, Ener1, Bankrate, Magnachip, Comverse Technology, Dell, Krispy Kreme,
Beazer Homes, Diebold, ModusLink, ITT Educational, Saba Software, Hill International, SAExploration, Evoqua, Sito Mobile, Cemtrex, Ubiquiti
(business-email-compromise loss, not accounting), Mattel, Overstock, Penn West and NQ Mobile (foreign filers).

### 6.4 Counts
Considered 52 (12 selected, 12 examined and dropped, 28 not pursued): 40 dropped in total.

## 7. Caveats (honest limits)

* Labels derive from SEC releases and 8-Ks; clean means "nothing found", not proof (web checks were limited to a few searches per control plus the text scans).
* Revelation dates are the first public filing/press date found in EDGAR. Short-seller or press commentary before those dates may exist for any case (searched
  only for ArthroCare and by reading the 8-K/NT filings between the analysed filing and the revelation); Pareteum in particular was not checked beyond its 8-Ks.
* Quantum's SEC order is controls-only (no fraud finding); Osiris's 2014 correction was about $1.1M on $59.9M of revenue; USAT's analysed 10-K already disclosed an earlier
  material weakness; Pareteum's analysed 10-K already disclosed material weaknesses. These are properties of the labels, not reasons they were chosen or excluded.
* GVA/MTZ and PTRY/RAH are only 2-digit-SIC matches; QTM/MITK has an assets ratio of 0.32 (near the 0.3 bound); LIME/AGX is 2.06.
* Fiscal-year-end mismatches: CGI (June) vs LSTR (Dec), USAT (June) vs ALOT (Jan 31), QTM (Mar) vs MITK (Sep), LIME (Dec) vs AGX (Jan 31): as_of dates differ by up to about 8 months.
* Not selected for detectability, and nothing about detectability was examined.
* The XBRL pre-era pair (PTRY/RAH, FY2004) needs the statement-table parser; assets for that pair come from the filings' balance sheets.
* Terminal events (bankruptcy/acquisition dates) of the fraud companies were not researched (collapse_date is None).
