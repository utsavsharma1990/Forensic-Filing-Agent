# Evaluation case research (verification log)

Scope: the 12 cases in SPEC.md, verified against SEC EDGAR (`data.sec.gov` submissions and companyfacts, fetched with
the project User-Agent, cached in `.cache/cases/`) and press/regulator pages (WebSearch/WebFetch, 2026-10-16).
Machine-readable result: `evaluation/fraud_cases.py`. Where the spec or the original task brief was wrong, it says so below.

## 1. Per-case table

| Ticker | Label | CIK (spec -> verified) | EDGAR entity name | Form | Fiscal yr | Accession | Filed | Public revelation | Collapse / terminal event | Filed before revelation? | XBRL for filing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ENRNQ | Fraud | 1024401 -> 1024401 (OK) | ENRON CORP/OR/ | 10-K | 2000 | 0001024401-01-500010 | 2001-04-02 | 2001-10-16 | 2001-12-02 Ch.11 | YES | No (pre-XBRL) |
| WCOM | Fraud | 723527 -> 723527 (OK) | MCI INC (ex WorldCom) | 10-K405 | 2001 | 0001005477-02-001226 | 2002-03-13 | 2002-06-25 | 2002-07-21 Ch.11 | YES (see caveat) | No (pre-XBRL) |
| LK | Fraud | 1767380 -> **1767582** | Luckin Coffee Inc. | 20-F | 2019 | 0001104659-21-087180 | **2021-06-30** | 2020-01-31 | 2020-07-13 Nasdaq delisting | **NO** | Yes |
| NKLA | Fraud | 1731289 -> 1731289 (OK) | Nikola Corp (ex VectoIQ) | 10-K | 2020 | 0001731289-21-000006 | **2021-02-25** | 2020-09-10 | 2021-12-21 SEC order; 2025-02-19 Ch.11 | **NO** | Yes |
| RIDE | Fraud | 1759774 -> **1759546** | Stark Novus Financial Inc. (ex Lordstown Motors, DiamondPeak) | 10-K | 2020 | 0001558370-21-003449 | **2021-03-25** | 2021-03-12 | 2021-06-14 CEO/CFO exit; 2023-06-27 Ch.11 | **NO** | Yes |
| SPCE | Fraud (weak) | 1679273 -> **1706946** | Virgin Galactic Holdings, Inc | 10-K | 2021 | 0001706946-22-000035 | **2022-02-28** | 2021-09-01 | none (see 4.6); 2021-10-14 stock drop | **NO** | Yes |
| AAPL | Clean | 320193 OK | Apple Inc. | 10-K | 2020 (FYE 2020-09-26) | 0000320193-20-000096 | 2020-10-30 | - | - | n/a | Yes |
| MSFT | Clean | 789019 OK | MICROSOFT CORP | 10-K | 2020 (FYE 2020-06-30) | 0001564590-20-034944 | 2020-07-30 | - | - | n/a | Yes |
| JNJ | Clean | 200406 OK | JOHNSON & JOHNSON | 10-K | 2020 (FYE 2021-01-03) | 0000200406-21-000008 | 2021-02-22 | - | - | n/a | Yes |
| PG | Clean | 80424 OK | PROCTER & GAMBLE Co | 10-K | 2020 (FYE 2020-06-30) | 0000080424-20-000053 | 2020-08-06 | - | - | n/a | Yes |
| BRK-B | Clean | 1067983 OK | BERKSHIRE HATHAWAY INC | 10-K | 2020 | 0001564590-21-009611 | 2021-03-01 | - | - | n/a | Yes |
| MMM | Clean | 66740 OK | 3M CO | 10-K | 2020 | 0001558370-21-000737 | 2021-02-04 | - | - | n/a | Yes |

`pre_revelation_valid = analysis_filing_date < public_revelation_date`: valid for 2 of 6 fraud cases (Enron, WorldCom); invalid for 4 (Luckin, Nikola, Lordstown, Virgin Galactic).

## 2. Corrections to the spec (and to the task brief)

| # | Spec / brief claim | Finding | Evidence |
|---|---|---|---|
| C1 | Luckin CIK 0001767380 | Does not exist (submissions API 404). Correct CIK is **1767582** (Luckin Coffee Inc., ticker LKNCY, 20-F filer). | data.sec.gov submissions |
| C2 | Lordstown (RIDE) CIK 0001759774 | That CIK is **Postal Realty Trust, Inc.** (PSTL, REIT). Lordstown is **1759546** (ex DiamondPeak Holdings; EDGAR name now "Stark Novus Financial Inc.", ticker SNFI). Ticker lookup of "RIDE" will not work; pass `cik=`. | submissions |
| C3 | Virgin Galactic CIK 0001679273 | That CIK is **Lamb Weston Holdings, Inc.** Virgin Galactic is **1706946**. | submissions |
| C4 | Task brief: "Enron Corp is 72859 I believe" | Brief is wrong, spec is right. CIK 72859 is the predecessor registrant (annual reports through FY1996 only on EDGAR). FY1997-FY2000 10-Ks, including the FY2000 10-K, are under **1024401** (ENRON CORP/OR/). | submissions list both |
| C5 | Task brief: Lordstown short report "Mar 15 2021" | Search sources give **2021-03-12** (Hindenburg, before market open). The FY2020 10-K (2021-03-25) is after either date. | ktmc.com, driveteslacanada.ca |
| C6 | Virgin Galactic "collapsed 2023" | No collapse/bankruptcy/delisting/SEC accounting action found; company still files 10-Ks (latest FY2025 filed 2026-03-30). Registry uses 2021-10-14 (class-period end, stock -14% on delay) and labels it "not a collapse". | 10-K FY2022 legal note; EDGAR |
| C7 | Lordstown "collapsed 2021" | Kept as 2021-06-14 (CEO and CFO resignations, 8-K), but the real terminal event is Chapter 11 on 2023-06-27; both are recorded. | SEC 8-K; bnnbloomberg |
| C8 | Spec treats all six as comparable "fraud" cases | Only Enron, WorldCom, Luckin are financial-statement frauds. Nikola, Lordstown, Virgin Galactic are disclosure/claims cases (SEC findings on product/pre-order claims; class action for Virgin Galactic). A statement-based detector is not expected to fire on those. Field `fraud_nature` records this. | SEC orders |
| C9 | Spec UI: "matched clean companies" | The clean set is six surviving US mega-caps, not matched on size, industry or distress. Do not describe as matched. | n/a |

Note on WorldCom: the CIK 723527 is correct but EDGAR's entity name is now "MCI INC"; ticker WCOM no longer resolves. Enron's ticker ENRNQ and WorldCom's WCOM are not in EDGAR's ticker map: callers must pass `cik=` (D6).

## 3. Look-ahead (pre-revelation) findings

* **Enron (valid).** FY2000 10-K filed 2001-04-02; the Q3 loss/charges release was 2001-10-16, the SEC inquiry came in Oct 2001, the restatement of 1997-2000 on 2001-11-08. Earlier skepticism existed (Fortune "Is Enron Overpriced?" 2001-03-05, before the filing, but it alleged no fraud) and Skilling resigned 2001-08-14. All are before bankruptcy and none is a fraud disclosure before the filing.
* **WorldCom (valid with a caveat).** 10-K405 filed 2002-03-13; fraud revealed 2002-06-25. But WorldCom disclosed a confidential SEC document request on **2002-03-11, two days before the filing** (accounting policies, loans to executives). That is an inquiry, not a fraud disclosure, so the case is kept valid; the strictest cut-off would use the FY2000 10-K405 (0000912057-01-505916, filed 2001-03-30).
* **Luckin (INVALID).** The first 20-F ever filed for FY2019 is dated 2021-06-30: 17 months after the Muddy Waters report (2020-01-31), 15 months after the company admitted ~RMB2.2B fabricated sales (2020-04-02). Luckin IPO'd 2019-05; no annual report existed before the revelation (only F-1s and 6-Ks), so `strict_alt = None`; a strict run cannot include Luckin. Further, the FY2019 20-F was produced after the internal investigation: whether its figures still contain the fabricated sales or are already corrected was NOT verified here, so a "should flag" expectation (SPEC) is unproven.
* **Nikola (INVALID).** FY2020 10-K filed 2021-02-25 vs Hindenburg 2020-09-10. The only earlier annual filing, FY2019 10-K (2020-03-06), was filed by the SPAC VectoIQ before the 2020-06-03 merger: SPAC trust financials, not Nikola's. A 10-K/A for FY2020 was filed 2021-05-06.
* **Lordstown (INVALID).** FY2020 10-K filed 2021-03-25, 13 days after Hindenburg (2021-03-12). Earlier annual filing = DiamondPeak SPAC shell 10-K (2020-03-25). A 10-K/A for FY2020 was filed 2021-06-08. Pre-revenue company: revenue-based Beneish terms are not meaningful.
* **Virgin Galactic (INVALID).** FY2021 10-K filed 2022-02-28; the Unity 22 deviation was first reported 2021-09-01 (New Yorker), FAA grounding 2021-09-02; class period ends 2021-10-14. Strict alternative: FY2020 10-K (2021-03-01), which also predates the first class action (2021-05-28).

Consequence: the spec headline run is contaminated by hindsight for 4 of 6 fraud cases; the strict run has only 2 usable fraud cases with a real operating-company filing (Enron, WorldCom) plus 2 SPAC-shell filings (not meaningful) and Luckin missing. Report the strict run as a small-sample sensitivity analysis with that stated.

## 4. Per-case notes and sources

### 4.1 Enron (ENRNQ)
Revenue inflation / SPE concealment. Revelation 2001-10-16 (Q3 loss $618M), formal SEC investigation disclosed 2001-10-31, restatement 2001-11-08 (income overstated by $586M since 1997), bankruptcy 2001-12-02. Sources: https://fortune.com/article/is-enron-overpriced-fortune-2001/ ; https://kvia.com/news/us-world/2021/04/25/enron-fast-facts/ ; EDGAR submissions CIK0001024401.

### 4.2 WorldCom (WCOM)
Capitalised line costs. 2002-06-25: restatement of 2001 ($3.055B) and Q1 2002 ($797M); 2002-08-08 further $3.8B; Chapter 11 2002-07-21. SEC request 2002-03-11. Sources: https://www.verizon.com/about/node/867723 ; https://www.verizon.com/about/node/867811 ; https://money.cnn.com/2002/07/19/news/worldcom_bankruptcy/ ; 8-K ex-99.1 https://www.sec.gov/Archives/edgar/data/0000723527/000091205702025338/a2083227zex-99_1.txt

### 4.3 Luckin (LK)
Muddy Waters 89-page report 2020-01-31 (a follow-on offering had priced 2020-01-10, 424B4); special-committee announcement and fabricated-sales disclosure 2020-04-02 (shares -80%); delisting effective 2020-07-13 (company withdrew hearing request 2020-06-25); SEC complaint 2020-12-16, $180M penalty, alleging >$300M fabricated sales from April 2019 through January 2020 (revenue overstated about 28% for H1 and 45% for Q3 2019 per SEC). Sources: https://www.qsrmagazine.com/food/beverage/luckin-coffee-faces-fraud-allegations-anonymous-report/ ; https://www.cnbc.com/2020/04/02/luckin-coffee-stock-plummets-after-investigation-finds-coo-fabricated-sales.html ; https://www.sec.gov/Archives/edgar/data/1767582/000135445720000301/lkdelistreason.txt ; https://www.sec.gov/litigation/litreleases/2020/lr24987.htm

### 4.4 Nikola (NKLA)
Hindenburg 2020-09-10; Milton resigned 2020-09-21; SEC order 2021-12-21 ($125M penalty); Chapter 11 2025-02-19. SEC finding concerns Milton's statements about technology, in-house production, hydrogen and reservations. Sources: https://fortune.com/2020/09/10/nikola-motor-stock-hindenburg-research-allegations ; https://www.electrive.com/2020/09/21/trevor-milton-resigns-as-nikola-executive-chair/ ; https://www.newsfilecorp.com/release/108208/Nikola-Corporation-to-Pay-125-Million-to-Resolve-Fraud-Charges ; Chapter 11 8-K https://www.sec.gov/Archives/edgar/data/1731289/000173128925000004/pressreleaseofnikolacorpor.htm

### 4.5 Lordstown (RIDE)
Hindenburg "Lordstown Motors Mirage" 2021-03-12 (claimed 100,000 pre-orders "largely fictitious"); CEO/CFO resignation 8-K 2021-06-14; Chapter 11 2023-06-27; SEC settled order 2024 (disgorgement $25.5M; ex-CEO Burns fined $175,000). Sources: https://www.ktmc.com/new-cases/lordstown-motors-corp ; https://www.sec.gov/Archives/edgar/data/1759546/000110465921080500/tm2119596d1_8k.htm ; https://www.bnnbloomberg.ca/us-truck-startup-lordstown-files-for-bankruptcy-after-foxconn-deal-falls-through-1.1938347 ; https://constructionequipment.com/trucking/news/33038138/lordstown-settles-sec-case-for-25-million

### 4.6 Virgin Galactic (SPCE): factual basis of the "fraud" label
The only adverse legal facts found: (a) Lavin v. Virgin Galactic, E.D.N.Y. 1:21-cv-03070, filed 2021-05-28; amended complaint (Dec 2021) alleges false/misleading statements on ship safety and the commercial flight programme for purchasers 2019-07-10 to 2021-10-14 (Sections 10(b), 20(a), 20A); a Nov 2022 ruling granted the motion to dismiss in part and denied it in part; settlement reported at $8.5M announced June 2025; derivative suits filed 2022. (b) Unity 22 (2021-07-11) flight-path deviation first reported 2021-09-01, FAA grounding 2021-09-02, cleared late Sept 2021. (c) 2021-10-14 delay of commercial service to Q4 2022, stock -14%. NOT found: any SEC enforcement action or SEC accounting finding (the FY2022 10-K legal note, which I read, lists only the class action and four derivative suits and no SEC matter), restatement, or alleged manipulation of financial statements. Conclusion: ground_truth=1 is a weak, contested label; kept per D11 but flagged `label_confidence="WEAK"`. The class-period dates from my two sources differ (2019-07-10 to 2021-10-14 per the company 10-K; 2019-10-26 to 2021-04-30 per the original May 2021 notice) because the complaint was later amended. Sources: https://www.sec.gov/Archives/edgar/data/1706946/000170694623000016/spce-20221231.htm ; https://en.wikipedia.org/wiki/Virgin_Galactic_Unity_22 ; https://www.businesswire.com/news/home/20210601006019/en/Notice-of-Lead-Plaintiff-Deadline-for-Shareholders-in-the-Virgin-Galactic-Holdings-Inc.-Class-Action-Lawsuit ; settlement stipulation https://virgingalacticsecuritiessettlement.com/wp-content/uploads/sites/17/2026/03/1_21-cv-03070-NRM-TAM_198_Exhibit-1-Stipulation-of-Settlement.pdf. The 2021-09-01 date rests on a single secondary source (Wikipedia summary of the New Yorker article); I did not open the article itself.

### 4.7 Strict alternatives (last annual filing before the revelation)

| Ticker | strict_alt | Comment |
|---|---|---|
| ENRNQ | FY2000 10-K, 2001-04-02, 0001024401-01-500010 | same filing |
| WCOM | FY2001 10-K405, 2002-03-13, 0001005477-02-001226 | same filing (FY2000 10-K405 0000912057-01-505916 if cut off at the SEC inquiry) |
| LK | none | no annual report before 2020-01-31 |
| NKLA | FY2019 10-K, 2020-03-06, 0001104659-20-030103 | SPAC shell, not meaningful |
| RIDE | FY2019 10-K, 2020-03-25, 0001213900-20-007365 | SPAC shell, not meaningful |
| SPCE | FY2020 10-K, 2021-03-01, 0001706946-21-000022 | 10-K/As on 2021-03-11 and 2021-05-10 excluded |

## 5. Clean cases: verification and caveats

All six filed a 10-K for fiscal 2020 (accessions above, all verified in EDGAR). Label "Clean" means only "no known accounting fraud or restatement", per spec.

| Ticker | Caveat |
|---|---|
| AAPL | FYE late September. Only SEC matter found: an insider-trading case against a former attorney (not the company). |
| MSFT | FYE 30 June. Historic SEC settled accounting charges (reserves, 1994-98 financials, announced 2002). Nothing found for 2019-21. |
| JNJ | Fiscal 2020 ended 2021-01-03 (53 weeks); D12 maps it to 2020 (SEC `fy`=2020 too). Massive talc litigation; SEC and DOJ subpoenas on talc disclosed Feb 2019; a 2011 FCPA action (not accounting fraud). No restatement found. Expect litigation language to trip text agents. |
| PG | FYE 30 June. A 10-K/A (0000080424-20-000059) was filed the next day (2020-08-07); the original is used and the reason for the amendment was not examined. No SEC accounting action found. |
| BRK-B | One registrant, two classes (BRK-A, BRK-B); CIK 1067983; tickers on EDGAR `['BRK-B','BRK-A']`. Insurer/conglomerate: Beneish/Altman poorly suited (no classified current assets/COGS), so expect "unavailable" metrics. A 2005 SEC matter involved General Re individuals, not Berkshire's statements. |
| MMM | Very large litigation disclosures (Combat Arms earplugs, PFAS), a 2019 securities class action about PFAS exposure statements, 2020 grand-jury subpoena (Alabama discharges). SEC FCPA books-and-records settlement (2023) over 2016-18 China travel payments: not accounting fraud or restatement. |

Limit of this check: for the clean companies I ran only general and company-specific web searches (SEC.gov-restricted) for accounting-fraud or restatement actions in roughly 2019-2022; I found none, but this is absence of evidence from search, not a proof. I did not read each company's restatement history from XBRL/8-K Item 4.02 filings.

## 6. XBRL availability matrix (data.sec.gov companyfacts)

| Ticker | companyfacts | Facts in the analysis filing | strict_alt filing facts | Notes |
|---|---|---|---|---|
| ENRNQ | 404 | 0 | same | Pre-XBRL, needs statement parser |
| WCOM | 404 | 0 | same | Pre-XBRL (companyfacts 404 for 723527) |
| LK | exists | 429 (acc 0001104659-21-087180) | n/a | 20-F with us-gaap tags |
| NKLA | exists | 639 | 134 (SPAC shell) | |
| RIDE | exists | 153 | 85 (SPAC shell) | pre-revenue |
| SPCE | exists | 517 | 551 | |
| AAPL | exists | 533 | - | |
| MSFT | exists | 626 | - | |
| JNJ | exists | 626 | - | |
| PG | exists | 612 | - | |
| BRK-B | exists | 428 | - | unclassified balance sheet |
| MMM | exists | 708 | - | |

"Facts" counts are companyfacts entries whose `accn` equals the analysis filing's accession (all taxonomies). I did not verify that every canonical line item (e.g. receivables, SGA, depreciation) is present for each; that is the xbrl_parser's job. Note that for Luckin (20-F) and Lordstown (pre-revenue) many Beneish inputs will be missing or not meaningful.

## 7. Method and what was not verified

* SEC data fetched live: submissions JSON (with paginated older files), companyfacts JSON, for 16 CIKs: the 12 verified ones plus the wrong spec CIKs 1767380 (404), 1759774, 1679273 and the brief's Enron guess 72859. UA `forensic-filing-agent contact@example.com`, <=5 req/s, cached on disk. The Python on this machine needed the `truststore` package to trust the corporate TLS proxy.
* Dates of events come from search-result snippets and fetched pages (links above). Not independently confirmed against the primary documents: Enron's 2001-10-16 loss figure details and the 2001-10-31 SEC disclosure date, WorldCom's 2002-03-11 request (taken from WorldCom's own 10-Q text as summarised by search), Muddy Waters/Hindenburg dates (taken from press), the Virgin Galactic $8.5M settlement amount (search snippet).
* Not verified: contents of any analysed filing (e.g. whether Luckin's FY2019 20-F still includes fabricated sales; whether Nikola's 10-K/A restated anything).
