# Retrospective Validation Report - forensic-filing-agent

Generated 2026-10-19T08:10:10Z (UTC). Code hash `f9d61d46ef966477`. Analysis source: graph.pipeline.analyze_company.

> **DEGRADED RUN - results are NOT the full system's performance.** degraded components seen: eval; fetch_data; language_specificity; llm_explanations; narrative; synthesis; temporal

> **PARTIAL RUN: only 30 case(s) evaluated (MNTX, SAEX, RVLT, HIL, SMRT, PLUG, PSIX, RTIX, SCOR, HEV, SABA, SWSH, VOL, ISLN, UNTK, ACLS, DWSN, LYTS, EXPO, BKE, EAF, KAI, INGN, DHX, RSTI, LGTY, SYNL, AMN, APKT, SHEN); headline metrics are not the 12-case evaluation.**

> **Contamination warning:** 4 of 6 fraud filings post-date revelation, only 3 of 6 are financial-statement frauds, the clean set is not matched, n=12. See [Limitations and contamination](#limitations-and-contamination-read-before-quoting-any-number).

## Headline (mode spec, variant spec)

**RESULT: WEAK / BAD on this sample.** recall is 40.0%: the system misses at least half of the fraud cases.

| n evaluable | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|---|
| 30 | 6 | 1 | 14 | 9 | 85.7% (CI 48.7-97.4%, 6/7) | 40.0% (CI 19.8-64.3%, 6/15) | 54.5% (CI n/a) | 6.7% (CI 1.2-29.8%, 1/15) |

Positive prediction = risk_grade High or Critical. CIs are exact Wilson 95% intervals; F1 has no closed-form Wilson interval. A case whose analysis errored or returned grade 'Unknown' is status ERROR and is excluded from the matrix (never counted as negative).

### Case-by-case (headline)

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Manitex International, Inc. | 2016 (as_of 2017-03-10) | Not flagged | Fraud | Medium | FY2014 (filed 2015-03-16) | Beneish M-Score was -1.65 in FY2012, above the -1.78 manipulation threshold. | OK (FN) | llm_explanations: FY2012 numeric validation failed; deterministic template used; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| SAExploration Holdings, Inc. | 2018 (as_of 2019-03-25) | Fraud-risk (High/Critical) | Fraud | High | FY2015 (filed 2016-03-15) | Beneish M-Score was -0.93 in FY2016, above the -1.78 manipulation threshold. | OK (TP) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Revolution Lighting Technologies, Inc. | 2017 (as_of 2018-03-08) | Not flagged | Fraud | Medium | FY2014 (filed 2015-03-16) | Beneish M-Score was -1.56 in FY2015, above the -1.78 manipulation threshold. | OK (FN) | llm_explanations: FY2015 numeric validation failed; deterministic template used; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Hill International, Inc. | 2016 (as_of 2017-03-31) | Fraud-risk (High/Critical) | Fraud | High | FY2016 (filed 2017-03-31) | FY2016 filing expresses going-concern doubt: "… a Going Concern ("ASU 2014-15"). The objective of ASU 2014-15 is to provide guidance in GAAP about management's responsibility to evaluate whether there is substantial d... | OK (TP) | none | yes |
| Stein Mart, Inc. | 2011 (as_of 2012-04-12) | Not flagged | Fraud | Medium | - | FY2011 filing discloses material weakness: "… as of the date of that evaluation to provide reasonable assurance that the objectives of disclosure controls and procedures are met. As noted below, material weaknesses in... | OK (FN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Plug Power Inc. | 2019 (as_of 2020-03-10) | Not flagged | Fraud | Medium | FY2017 (filed 2018-03-12) | FY2017 filing discloses material weakness: "… over the classification of restricted cash between current assets and noncurrent assets. Management has concluded the control deficiency constituted a material weakness in... | OK (FN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Power Solutions International, Inc. | 2015 (as_of 2016-02-26) | Fraud-risk (High/Critical) | Fraud | High | FY2015 (filed 2016-02-26) | Beneish M-Score was -1.76 in FY2015, above the -1.78 manipulation threshold. | OK (TP) | llm_explanations: FY2015 numeric validation failed; deterministic template used; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| RTI Surgical, Inc. (now Surgalign Holdings, Inc.) | 2018 (as_of 2019-03-05) | Fraud-risk (High/Critical) | Fraud | High | FY2016 (filed 2017-03-13) | FY2014 filing expresses going-concern doubt: "… Presentation of Financial StatementsGoing Concern (Subtopic 205-40). The new guidance addresses managements responsibility to evaluate whether there is substantial d... | OK (TP) | language_specificity: no valid LLM score for FY2014; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| comScore, Inc. | 2014 (as_of 2015-02-20) | Fraud-risk (High/Critical) | Fraud | High | FY2011 (filed 2012-02-22) | FY2014 filing discloses material weakness: "… and may have to design enhanced processes and controls to address issues identified through this review. Remedying any significant deficiencies or material weaknesses that... | OK (TP) | none | yes |
| Ener1, Inc. | 2010 (as_of 2011-03-10) | Fraud-risk (High/Critical) | Fraud | High | FY2009 (filed 2010-03-11) | Beneish M-Score was -1.20 in FY2010, above the -1.78 manipulation threshold. | OK (TP) | fetch_data: no peer group (no XBRL TotalAssets for FY2010 as of 2011-03-10 (pre-XBRL or not yet filed)); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3); eva... | yes |
| Saba Software, Inc. | 2011 (as_of 2011-08-05) | Not flagged | Fraud | Low | - | FY2007 filing discloses material weakness: "… in increased expenses and the devotion of significant management and other internal resources. During this process, if our management identifies one or more material weakn... | OK (FN) | fetch_data: no peer group (no XBRL TotalAssets for FY2011 as of 2011-08-05 (pre-XBRL or not yet filed)); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 5 paragraphs, expected 3); eva... | yes |
| Swisher Hygiene Inc. | 2010 (as_of 2011-03-31) | Not flagged | Fraud | Medium | - | Altman Z-prime score was 0.64 in FY2010, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (FN) | fetch_data: no peer group (no XBRL TotalAssets for FY2010 as of 2011-03-31 (pre-XBRL or not yet filed)); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3); eva... | yes |
| Volt Information Sciences, Inc. | 2008 (as_of 2009-02-02) | Not flagged | Fraud | Medium | - | FY2008 filing discloses material weakness: "… instruments. -18- IF THE COMPANY FAILS TO MAINTAIN AN EFFECTIVE SYSTEM OF INTERNAL CONTROLS OR DISCOVERS MATERIAL WEAKNESSES IN ITS INTERNAL CONTROLS OVER FINANCIAL REPORT... | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2008 (< 2009): no companyfacts/frames for peers); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3); eval: peer ... | yes |
| Isilon Systems, Inc. | 2006 (as_of 2007-03-15) | Not flagged | Fraud | Low | - | 17.6% of MD&A sentences were passive-voice in FY2006 (flag threshold 15%). | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2006 (< 2009): no companyfacts/frames for peers); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; eval: peer agent unavailable (peer comparison unavailable: pre-XBRL focus year 2006: p... | yes |
| UniTek Global Services, Inc. | 2011 (as_of 2012-03-07) | Not flagged | Fraud | Medium | FY2010 (filed 2011-03-30) | Auditor changed from BDO Seidman, LLP to Ernst & Young LLP in FY2010. | OK (FN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Axcelis Technologies, Inc. | 2016 (as_of 2017-03-14) | Fraud-risk (High/Critical) | Clean | High | FY2013 (filed 2014-03-03) | FY2016 filing expresses going-concern doubt: "… Uncertainties about an Entity’s Ability to Continue as a Going Concern.” ASU 2014-15 introduces an explicit requirement for management to assess if there is substantial ... | OK (FP) | language_specificity: no valid LLM score for FY2012; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Dawson Geophysical Company | 2018 (as_of 2019-03-06) | Not flagged | Clean | Medium | FY2016 (filed 2017-03-13) | FY2018 filing discloses material weakness: "… Failure to achieve and maintain 14 Table of Contents effective internal controls could have a material adverse effect on our stock price. In addition, a material weakness ... | OK (TN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| LSI Industries Inc. | 2017 (as_of 2017-09-08) | Not flagged | Clean | Medium | - | FY2017 filing discloses material weakness: "… of asset impairment assessments, the ability to maintain an effective system of internal control over financial reporting, the ability to remediate any material weaknesses... | OK (TN) | language_specificity: no valid LLM score for FY2013, FY2014, FY2015, FY2016, FY2017; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Exponent, Inc. | 2016 (as_of 2017-02-24) | Not flagged | Clean | Medium | - | 18.4% of MD&A sentences were passive-voice in FY2016 (flag threshold 15%). | OK (TN) | narrative: deterministic fallback (numeric validation failed: unsupported numerals 2017) | yes |
| The Buckle, Inc. | 2011 (as_of 2012-03-28) | Not flagged | Clean | Medium | FY2011 (filed 2012-03-28) | FY2008 filing discloses material weakness: "… maintained in all material respects. Our audit included obtaining an understanding of internal control over financial reporting, assessing the risk that a material weaknes... | OK (TN) | language_specificity: no valid LLM score for FY2007; narrative: deterministic fallback (LLM returned 1 paragraphs, expected 3) | yes |
| GrafTech International Ltd. | 2019 (as_of 2020-02-21) | Not flagged | Clean | Medium | FY2019 (filed 2020-02-21) | Auditor changed from PricewaterhouseCoopers LLP to Deloitte & Touche LLP in FY2015. | OK (TN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| Kadant Inc. | 2015 (as_of 2016-03-16) | Not flagged | Clean | Medium | - | 27.6% of MD&A sentences were passive-voice in FY2015 (flag threshold 15%). | OK (TN) | none | yes |
| Inogen, Inc. | 2018 (as_of 2019-02-26) | Not flagged | Clean | Medium | FY2015 (filed 2016-03-14) | FY2018 filing discloses material weakness: "… and procedures and hiring accounting or internal audit staff, which may adversely affect our results of operations and financial condition. Although prior material weaknes... | OK (TN) | narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |
| DHI Group, Inc. (formerly Dice Holdings, Inc.) | 2014 (as_of 2015-02-10) | Not flagged | Clean | Low | FY2013 (filed 2014-02-14) | 28.9% of MD&A sentences were passive-voice in FY2014 (flag threshold 15%). | OK (TN) | none | yes |
| Rofin-Sinar Technologies Inc. | 2010 (as_of 2010-11-30) | Not flagged | Clean | Low | FY2008 (filed 2008-12-01) | 32.9% of MD&A sentences were passive-voice in FY2010 (flag threshold 15%). | OK (TN) | fetch_data: no peer group (no XBRL TotalAssets for FY2010 as of 2010-11-30 (pre-XBRL or not yet filed)); language_specificity: no valid LLM score for FY2009; temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; eval: peer agent unavaila... | yes |
| Logility, Inc. (Logility Supply Chain Solutions) | 2011 (as_of 2011-07-14) | Not flagged | Clean | Medium | - | Operating cash flow was 0.42x net income in FY2011 and -0.33x in FY2010; below 0.8 in two consecutive years means reported profit is not converting into cash. | OK (TN) | fetch_data: no peer group (no XBRL TotalAssets for FY2011 as of 2011-07-14 (pre-XBRL or not yet filed)); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3); eva... | yes |
| Synalloy Corporation (now Ascent Industries Co.) | 2010 (as_of 2011-03-25) | Not flagged | Clean | Medium | - | 32.0% of MD&A sentences were passive-voice in FY2010 (flag threshold 15%). | OK (TN) | fetch_data: no financial data extracted for FY[2010]; fetch_data: no peer group (no XBRL TotalAssets for FY2010 as of 2011-03-25 (pre-XBRL or not yet filed)); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic... | yes |
| AMN Healthcare Services, Inc. | 2008 (as_of 2009-03-02) | Not flagged | Clean | Medium | - | Hedging-word ratio rose 25% to 0.9% of MD&A words in FY2008. | OK (TN) | fetch_data: no peer group (pre-XBRL focus year 2008 (< 2009): no companyfacts/frames for peers); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3); eval: peer ... | yes |
| Acme Packet, Inc. | 2006 (as_of 2007-03-16) | Not flagged | Clean | Medium | - | FY2006 filing discloses material weakness: "… testing by our independent registered public accounting firm, may reveal deficiencies in our internal controls over financial reporting that are deemed to be material weak... | OK (TN) | fetch_data: no peer group (pre-XBRL focus year 2006 (< 2009): no companyfacts/frames for peers); temporal: peer_result unavailable; score computed from the remaining agents; synthesis: agents unavailable: peer; eval: peer agent unavailable (peer comparison unavailable: pre-XBRL focus year 2006: p... | yes |
| Shenandoah Telecommunications Company | 2011 (as_of 2012-03-06) | Not flagged | Clean | Low | - | FY2007 filing discloses material weakness: "… maintained in all material respects. Our audit included obtaining an understanding of internal control over financial reporting, assessing the risk that a material weaknes... | OK (TN) | language_specificity: no valid LLM score for FY2008, FY2009; narrative: deterministic fallback (LLM returned 2 paragraphs, expected 3) | yes |

## All runs: headline and sensitivity

Only spec/spec is the headline. Every other row is a labelled sensitivity run (strict = point-in-time re-run of look-ahead cases with the last pre-revelation filing; no_passive = pre-registered variant without the passive-voice flag, declared before the run, see ledger P2/P3).

| Run (mode/variant) | n evaluable | TP/FP/TN/FN | Precision | Recall | F1 | FPR | Accuracy |
|---|---|---|---|---|---|---|---|
| spec/spec (HEADLINE) | 30 | 6/1/14/9 | 85.7% (CI 48.7-97.4%, 6/7) | 40.0% (CI 19.8-64.3%, 6/15) | 54.5% (CI n/a) | 6.7% (CI 1.2-29.8%, 1/15) | 66.7% (CI 48.8-80.8%, 20/30) |

## Baselines (same evaluable cases)

| Run | Predictor | TP/FP/TN/FN | Precision | Recall | FPR | Accuracy |
|---|---|---|---|---|---|---|
| spec/spec | System | 6/1/14/9 | 85.7% (CI 48.7-97.4%, 6/7) | 40.0% (CI 19.8-64.3%, 6/15) | 6.7% (CI 1.2-29.8%, 1/15) | 66.7% (CI 48.8-80.8%, 20/30) |
| spec/spec | Beneish-only (M > -1.78 in focus year) | 2/0/15/13 | 100.0% (CI 34.2-100.0%, 2/2) | 13.3% (CI 3.7-37.9%, 2/15) | 0.0% (CI 0.0-20.4%, 0/15) | 56.7% (CI 39.2-72.6%, 17/30) |
| spec/spec | Always predict clean | 0/0/15/15 | n/a (undefined, 0/0) | 0.0% (CI 0.0-20.4%, 0/15) | 0.0% (CI 0.0-20.4%, 0/15) | 50.0% (CI 33.2-66.8%, 15/30) |

spec/spec: Beneish unavailable (counted as 'predict clean') for: SMRT, PLUG, SCOR, SABA, SWSH, VOL, ISLN, UNTK, ACLS, DWSN, LYTS, EXPO, BKE, EAF, INGN, DHX, RSTI, LGTY, SYNL, AMN, APKT.

## Per-agent contribution

Flagging = agent severity Medium or High. Unique catch = fraud case flagged by this agent and by no other of agents 1-4. Plain flag rate (fraud) and false-alarm rate (clean) are reported alongside.

### spec/spec (fraud n=15, clean n=15, detected n=6)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 33.3% (CI 15.2-58.3%, 5/15) | 6.7% (CI 1.2-29.8%, 1/15) | 1 (SWSH) | 6.7% (CI 1.2-29.8%, 1/15) | 0.0% (CI 0.0-39.0%, 0/6) | - |
| language | 40.0% (CI 19.8-64.3%, 6/15) | 20.0% (CI 7.0-45.2%, 3/15) | 1 (PLUG) | 6.7% (CI 1.2-29.8%, 1/15) | 0.0% (CI 0.0-39.0%, 0/6) | - |
| network | 46.7% (CI 24.8-69.9%, 7/15) | 40.0% (CI 19.8-64.3%, 6/15) | 2 (SMRT, VOL) | 13.3% (CI 3.7-37.9%, 2/15) | 0.0% (CI 0.0-39.0%, 0/6) | - |
| peer | 20.0% (CI 7.0-45.2%, 3/15) | 6.7% (CI 1.2-29.8%, 1/15) | 0 (-) | 0.0% (CI 0.0-20.4%, 0/15) | 0.0% (CI 0.0-39.0%, 0/6) | HEV, SABA, SWSH, VOL, ISLN, RSTI, LGTY, SYNL, AMN, APKT |
| temporal | 0.0% (CI 0.0-20.4%, 0/15) | 0.0% (CI 0.0-20.4%, 0/15) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 2/6 | PSIX, HEV |
| language | 0/6 | - |
| network | 3/6 | HIL, PSIX, SCOR |
| peer | 1/6 | SAEX |
| temporal | 0/6 | - |

## Detection timing (D14)

### spec/spec

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| SAEX | FY2015 filed 2016-03-15 | 2019-08-15 | - | 41.0 | - | early |
| HIL | FY2016 filed 2017-03-31 | 2017-09-21 | - | 5.7 | - | early |
| PSIX | FY2015 filed 2016-02-26 | 2016-08-10 | - | 5.5 | - | early |
| RTIX | FY2016 filed 2017-03-13 | 2020-03-17 | - | 36.1 | - | early |
| SCOR | FY2011 filed 2012-02-22 | 2016-02-29 | - | 48.2 | - | early |
| HEV | FY2009 filed 2010-03-11 | 2011-08-10 | - | 17.0 | - | early |

Average months early (before revelation, early cases only): 25.6 (n early = 6, n not early = 0; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

## Breakdown by fraud nature

Only financial-statement frauds are in scope for a statement-based detector; disclosure/claims cases are reported separately.

### spec/spec

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| financial_statement | 15 | 15 | 6 | 40.0% (CI 19.8-64.3%, 6/15) | MNTX=Medium; SAEX=High; RVLT=Medium; HIL=High; SMRT=Medium; PLUG=Medium; PSIX=High; RTIX=High; SCOR=High; HEV=High; SABA=Low; SWSH=Medium; VOL=Medium; ISLN=Low; UNTK=Medium |

## Run metadata

| Field | Value |
|---|---|
| Timestamp (UTC) | 2026-10-19T08:10:10Z |
| Code hash (sha256) | f9d61d46ef9664777eba82f14c01ca04ff424afb3b4cbd5ba081c4abe4c7c0f6 |
| Code hash covers | agents/*.py, tools/*.py, graph/*.py, evaluation/fraud_cases.py, prompts/templates.py |
| ANTHROPIC key available | True |
| JEV key available | True |
| Analysis source | graph.pipeline.analyze_company |
| Modes / variants | ['spec'] / ['spec'] |
| Versions | python=3.14.4; platform=Windows-11-10.0.26200-SP0; langgraph=1.2.10; langchain=1.3.14; langchain-anthropic=1.5.3; anthropic=0.120.2; typesafe-sdk=0.7.2; httpx=0.28.1; pandas=3.0.5; numpy=2.5.1; spacy=3.8.16; beautifulsoup4=4.15.0 |

Degraded components per run (union over cases):

* spec/spec: llm_explanations [MNTX, RVLT, PSIX]; narrative [MNTX, SAEX, RVLT, SMRT, PLUG, PSIX, RTIX, HEV, SABA, SWSH, VOL, UNTK, ACLS, DWSN, LYTS, EXPO, BKE, EAF, INGN, LGTY, SYNL, AMN, SHEN]; language_specificity [RTIX, ACLS, LYTS, BKE, RSTI, SHEN]; fetch_data [HEV, SABA, SWSH, VOL, ISLN, RSTI, LGTY, SYNL, AMN, APKT]; temporal [HEV, SABA, SWSH, VOL, ISLN, RSTI, LGTY, SYNL, AMN, APKT]; synthesis [HEV, SABA, SWSH, VOL, ISLN, RSTI, LGTY, SYNL, AMN, APKT]; eval [HEV, SABA, SWSH, VOL, ISLN, RSTI, LGTY, SYNL, AMN, APKT]

## LIMITATIONS AND CONTAMINATION (READ BEFORE QUOTING ANY NUMBER)

> **WARNING: these results are NOT clean out-of-sample evidence.** The sample is 12 hand-picked, famous cases, some rules were fitted with evaluation-set filings in view (ledger below), and most fraud filings post-date the fraud's public revelation.

1. **Look-ahead: 4 of 6 fraud filings post-date public revelation** (LK, NKLA, RIDE, SPCE). The spec (headline) run therefore sees information that was already public; a 'detection' there is not early warning. Only Enron and WorldCom filings precede revelation (WorldCom disclosed an SEC document request two days before its 10-K405).
2. **Only 3 of 6 fraud cases are financial-statement frauds** (ENRNQ, WCOM, LK). Nikola, Lordstown and Virgin Galactic are disclosure/claims cases (product claims, pre-orders, safety statements); a statement-based detector is not expected to fire on them. Virgin Galactic's fraud label is WEAK (settled class action, no SEC accounting finding). Luckin's FY2019 20-F was produced after the internal investigation; whether it still contains the fabricated sales was not verified.
3. **The clean set is six surviving US mega-caps, not matched** on size, industry or distress (AAPL, MSFT, JNJ, PG, BRK-B, MMM). 'Clean' means only 'no known accounting fraud/restatement' (absence of evidence from a web search). Survivorship and selection bias apply to both sets; BRK-B is an insurer to which Beneish/Altman apply poorly.
4. **n = 12, so confidence intervals are wide** (6 vs 6). Differences between variants/baselines of one or two cases are not statistically meaningful.
5. **The strict run has a tiny n**: Luckin is excluded (no pre-revelation annual report), Nikola and Lordstown fall back to SPAC-shell 10-Ks (no operating business), leaving effectively 2 operating-company fraud filings (Enron, WorldCom) plus Virgin Galactic FY2020. Treat strict numbers as anecdotes.
6. **Detection timing is quantised** to annual filing dates (D14) and is only meaningful for pre-revelation filings.

### Tuning / contamination ledger (reproduced from docs/TUNING_LEDGER.md)

Purpose: every place where a rule, guard or threshold was influenced by looking at filings that are ALSO evaluation cases.
The evaluation report (evaluation/results/evaluation_report.md) MUST reproduce this list under "Known contamination of the evaluation".
Thresholds from the spec / literature (Beneish cut-offs, +25% hedging, +30% fees, |z|>2, etc.) were NOT changed by any entry below.

| # | Date | Module | What was done | Evidence looked at | Eval-case overlap | Effect |
|---|------|--------|---------------|--------------------|-------------------|--------|
| 1 | 2026-10-16 | agents/network_agent.py | Added agent-level false-positive guards: restatement hit must have an error/non-reliance cue and not be an adoption recast / "Amendment and Restatement of ... Plan" exhibit title / "incorporated by reference"; ASU 2014-15 boilerplate not counted as going concern; audit-fee ratio >10x or <0.1x treated as unit-parse error; name normalisation for garbled CEO/CFO text. | Base-rate runs on AAPL, MSFT, JNJ, PG, MMM, BRK-B FY2016-2020 (first unguarded run: 8 restatement hits, 1 going-concern hit, 1 fee hit, 1 false CFO change; all removed by guards). | YES - the six clean evaluation companies (FY2020 filings are in that range). | Lowers false positives on the clean set; base rates after guards are NOT out-of-sample. Guards are boilerplate/parse-error fixes, not changes to the spec thresholds, but they were fitted with clean-set filings in view. |
| 2 | 2026-10-16 | agents/network_agent.py | WorldCom FY2000 `network.related_party` fires on a 180-char -> 8,219-char jump (Item 13 pointer vs full disclosure). Left flagged deliberately: un-flagging it would be tuning on an evaluation case. | WorldCom FY2000/2001 | YES | Possible weak/spurious flag retained; reported as is. |

Rules for future entries: add a row BEFORE merging any change motivated by an evaluation-case filing; if the change cannot be
justified independently of the evaluation set, do not make it.

##### Pre-registered variants (declared BEFORE any evaluation run, 2026-10-16)
| # | Variant | Why declared | Reporting rule |
|---|---------|--------------|----------------|
| P1 | `spec` (headline): all spec flags incl. `language.passive_voice` (>15% of MD&A sentences). | Spec-literal. | Always reported first. |
| P2 | `no_passive`: identical but `language.passive_voice` is excluded from flags, severity and temporal scoring. | Language agent base-rate run: passive voice fired on 25/25 healthy large-cap company-years (MD&A passive share 21.7-31.2%), i.e. no information at the spec's 15% cut-off. NOTE: motivated by looking at filings that include the clean evaluation companies (see entry 1 caveat). | Reported as a sensitivity row next to the headline; never replaces it; the report states that it was declared before the run and why. |
| P3 | `strict`: contaminated fraud cases re-run with the last annual filing filed before public revelation (`strict_alt`), cases with none excluded and listed. | docs/case_research.md validity findings (4 of 6 fraud filings post-date revelation). | Sensitivity analysis; tiny n; report with CIs. |

##### Known data artifacts (disclosed, NOT corrected; found 2026-10-16 in the first real pipeline runs)
| # | Case | Artifact | Consequence for reading results |
|---|------|----------|--------------------------------|
| A1 | ENRNQ | The FY1996 "annual report" under CIK 0001024401 is a 15,667-character shell (the real FY1996 10-K sits under predecessor CIK 72859). The FY1997-vs-FY1996 comparison therefore produces spurious CEO/CFO changes, a spurious new-legal flag and a 1997 suspicion peak. | Enron `first_detection_year` = 1997 is very likely an artifact; do not quote it as evidence of early detection. FY2000 signals (Beneish M=-0.66, CEO change, related-party growth) are unaffected. |
| A2 | ENRNQ | Audit fees parsed only for FY2000 (proxy format of 2001); FY1997-99 proxies fetched but nothing extracted. | Audit-fee trend signal untested for Enron. |
| A3 | LK | No annual report exists before the April 2020 revelation; the FY2019 20-F (filed 2021-06-30) post-dates the revelation and the internal investigation. FY2018 exists only as a comparative. Beneish unavailable (no COGS/SG&A tags). | Luckin is not a true point-in-time test and is excluded from the strict run. |
| A4 | AAPL | Medium grade at FY2020 comes only from two favourable-direction peer outliers plus the passive-voice flag. | Peer flags are two-sided per spec; this is a false-positive mechanism, reported as is. |

### Case validity findings (from docs/case_research.md and evaluation/fraud_cases.py)

* **ENRNQ** (valid; financial_statement; label: established (restatement, bankruptcy, criminal convictions)): Valid: FY2000 10-K filed 2001-04-02, 6.5 months before the 2001-10-16 revelation. NOTE: the commonly assumed CIK 72859 is the predecessor registrant (Enron Corp, annual reports only through FY1996 on EDGAR); FY1997-FY2000 10-Ks are filed under CIK 1024401 (ENRON CORP/OR/), so the spec CIK is correct.
* **WCOM** (valid; financial_statement; label: established (restatement, bankruptcy, convictions)): Valid against the fraud revelation (filed 3 months before 2002-06-25). Caveat: a public SEC document request (2002-03-11) preceded the filing by two days; a stricter 'first public red flag' cut-off would instead use the FY2000 10-K405 (0000912057-01-505916, filed 2001-03-30). The 10-K405/A filed 2001-04-26 amends FY2000. Spec CIK 723527 verified (EDGAR name now 'MCI INC'). Form type is 10-K405.
* **LK** (INVALID; financial_statement; label: established (company admission, SEC complaint)): INVALID (look-ahead): the FY2019 20-F was filed 2021-06-30, 17 months AFTER the 2020-01-31 short report and 15 months after the fraud admission. Luckin IPO'd May 2019 and filed no annual report before the revelation, so strict_alt is None (only F-1 registration statements and 6-Ks exist). The 20-F was prepared after the internal investigation, so whether it still shows the fabricated sales is NOT verified here. Kept in the spec run, flagged invalid.
* **NKLA** (INVALID; disclosure_claims; label: established (SEC order against the company); misstatements concern product claims, not the financial statements): INVALID (look-ahead): FY2020 10-K filed 2021-02-25, five months AFTER Hindenburg (2020-09-10). The only annual filing before the revelation (FY2019 10-K, 2020-03-06) belongs to the SPAC VectoIQ and contains no operating-company financials, so the strict run has little meaning for this case.
* **RIDE** (INVALID; disclosure_claims; label: established (SEC settled order on misleading pre-order claims); not a financial-statement fraud): INVALID (look-ahead): FY2020 10-K filed 2021-03-25, thirteen days AFTER the Hindenburg report (2021-03-12). The only earlier annual filing is the DiamondPeak SPAC shell 10-K (2020-03-25).
* **SPCE** (INVALID; disclosure_claims; label: WEAK: civil securities class action settled without admission; no SEC/DOJ finding, no restatement, no financial-statement manipulation alleged): INVALID (look-ahead): FY2021 10-K filed 2022-02-28, six months AFTER the 2021-09-01 revelation and after the 2021-10-14 stock drop. Strict alternative is the FY2020 10-K (2021-03-01). The 'fraud' label is the weakest of the 12: treat Virgin Galactic as a contested/disclosure-risk case, not proven accounting fraud.

#### 2. Corrections to the spec (and to the task brief)

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

#### 3. Look-ahead (pre-revelation) findings

* **Enron (valid).** FY2000 10-K filed 2001-04-02; the Q3 loss/charges release was 2001-10-16, the SEC inquiry came in Oct 2001, the restatement of 1997-2000 on 2001-11-08. Earlier skepticism existed (Fortune "Is Enron Overpriced?" 2001-03-05, before the filing, but it alleged no fraud) and Skilling resigned 2001-08-14. All are before bankruptcy and none is a fraud disclosure before the filing.
* **WorldCom (valid with a caveat).** 10-K405 filed 2002-03-13; fraud revealed 2002-06-25. But WorldCom disclosed a confidential SEC document request on **2002-03-11, two days before the filing** (accounting policies, loans to executives). That is an inquiry, not a fraud disclosure, so the case is kept valid; the strictest cut-off would use the FY2000 10-K405 (0000912057-01-505916, filed 2001-03-30).
* **Luckin (INVALID).** The first 20-F ever filed for FY2019 is dated 2021-06-30: 17 months after the Muddy Waters report (2020-01-31), 15 months after the company admitted ~RMB2.2B fabricated sales (2020-04-02). Luckin IPO'd 2019-05; no annual report existed before the revelation (only F-1s and 6-Ks), so `strict_alt = None`; a strict run cannot include Luckin. Further, the FY2019 20-F was produced after the internal investigation: whether its figures still contain the fabricated sales or are already corrected was NOT verified here, so a "should flag" expectation (SPEC) is unproven.
* **Nikola (INVALID).** FY2020 10-K filed 2021-02-25 vs Hindenburg 2020-09-10. The only earlier annual filing, FY2019 10-K (2020-03-06), was filed by the SPAC VectoIQ before the 2020-06-03 merger: SPAC trust financials, not Nikola's. A 10-K/A for FY2020 was filed 2021-05-06.
* **Lordstown (INVALID).** FY2020 10-K filed 2021-03-25, 13 days after Hindenburg (2021-03-12). Earlier annual filing = DiamondPeak SPAC shell 10-K (2020-03-25). A 10-K/A for FY2020 was filed 2021-06-08. Pre-revenue company: revenue-based Beneish terms are not meaningful.
* **Virgin Galactic (INVALID).** FY2021 10-K filed 2022-02-28; the Unity 22 deviation was first reported 2021-09-01 (New Yorker), FAA grounding 2021-09-02; class period ends 2021-10-14. Strict alternative: FY2020 10-K (2021-03-01), which also predates the first class action (2021-05-28).

Consequence: the spec headline run is contaminated by hindsight for 4 of 6 fraud cases; the strict run has only 2 usable fraud cases with a real operating-company filing (Enron, WorldCom) plus 2 SPAC-shell filings (not meaningful) and Luckin missing. Report the strict run as a small-sample sensitivity analysis with that stated.

## Disclaimer

This evaluation uses publicly available SEC filings. Past detection performance does not guarantee future accuracy. This tool is for research purposes and does not constitute investment advice.
