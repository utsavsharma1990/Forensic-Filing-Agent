# Retrospective Validation Report - forensic-filing-agent

Generated 2026-10-16T17:07:16Z (UTC). Code hash `6b836165ec2d45b5`. Analysis source: graph.pipeline.analyze_company.

> **DEGRADED RUN - results are NOT the full system's performance.** ANTHROPIC_API_KEY missing (no LLM specificity/narrative) | JEV_API_KEY missing (no Jev confidence; Critical unreachable) | degraded components seen: critical_blocked; eval; fetch_data; jev; language_specificity; llm_explanations; narrative; synthesis; temporal

> **Contamination warning:** 4 of 6 fraud filings post-date revelation, only 3 of 6 are financial-statement frauds, the clean set is not matched, n=12. See [Limitations and contamination](#limitations-and-contamination-read-before-quoting-any-number).

## Headline (mode spec, variant spec)

**RESULT: WEAK / BAD on this sample.** recall is 50.0%: the system misses at least half of the fraud cases.

| n evaluable | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|---|
| 12 | 3 | 0 | 6 | 3 | 100.0% (CI 43.9-100.0%, 3/3) | 50.0% (CI 18.8-81.2%, 3/6) | 66.7% (CI n/a) | 0.0% (CI 0.0-39.0%, 0/6) |

Positive prediction = risk_grade High or Critical. CIs are exact Wilson 95% intervals; F1 has no closed-form Wilson interval. A case whose analysis errored or returned grade 'Unknown' is status ERROR and is excluded from the matrix (never counted as negative).

### Case-by-case (headline)

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Enron Corp | 2000 (as_of 2001-04-02) | Fraud-risk (High/Critical) | Fraud | High | FY1997 (filed 1998-03-31) | Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold. | OK (TP) | fetch_data: no peer group (pre-XBRL focus year 2000 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| WorldCom Inc | 2001 (as_of 2002-03-13) | Not flagged | Fraud | Medium | FY2000 (filed 2001-03-30) | Altman Z-prime score was 1.03 in FY2001, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2001 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| Luckin Coffee Inc. | 2019 (as_of 2021-06-30) | Not flagged | Fraud | Medium | - | FY2019 filing discloses restatement and material weakness: "… of these individuals in their roles as members of the board of directors of the Company; · the effect of the Non-Reliance identified in, and the resultant ... | OK (FN) | fetch_data: no peer group (reporting currency CNY != USD: asset-size matching against USD peers is not meaningful (compare ratios only; no peers selected)); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHR... | NO (filed after revelation) |
| Nikola Corp | 2020 (as_of 2021-02-25) | Not flagged | Fraud | Medium | FY2019 (filed 2020-03-06) | Auditor changed from RSM US LLP to Ernst & Young LLP in FY2020. | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Lordstown Motors Corp | 2020 (as_of 2021-03-25) | Fraud-risk (High/Critical) | Fraud | High | FY2020 (filed 2021-03-25) | Auditor changed from WithumSmith+Brown P.C. to KPMG LLP in FY2020. | OK (TP) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Virgin Galactic Holdings, Inc | 2021 (as_of 2022-02-28) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-03-18) | FY2021 filing discloses material weakness: "… government regulation that impact the way we operate; •risks associated with international expansion; •our ability to timely and effectively remediate material weaknesses ... | OK (TP) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Apple Inc. | 2020 (as_of 2020-10-30) | Not flagged | Clean | Medium | - | In FY2020, receivables growth minus revenue growth was -35.2 pp, which is 39 pp below the peer mean of 3.8 pp. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Microsoft Corp | 2020 (as_of 2020-07-30) | Not flagged | Clean | Low | - | 26.1% of MD&A sentences were passive-voice in FY2020 (flag threshold 15%). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Johnson & Johnson | 2020 (as_of 2021-02-22) | Not flagged | Clean | Low | - | 28.3% of MD&A sentences were passive-voice in FY2020 (flag threshold 15%). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Procter & Gamble Co | 2020 (as_of 2020-08-06) | Not flagged | Clean | Medium | - | In FY2020, DSO was 21 days, which is 62.9% below the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Berkshire Hathaway Inc | 2020 (as_of 2021-03-01) | Not flagged | Clean | Medium | - | In FY2020, ROA 4.9% vs peer mean 1.1% (z=+2.2). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| 3M Co | 2020 (as_of 2021-02-04) | Not flagged | Clean | Medium | FY2020 (filed 2021-02-04) | In FY2020, debt/equity was 1.46x, which is 114.1% above the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |

## All runs: headline and sensitivity

Only spec/spec is the headline. Every other row is a labelled sensitivity run (strict = point-in-time re-run of look-ahead cases with the last pre-revelation filing; no_passive = pre-registered variant without the passive-voice flag, declared before the run, see ledger P2/P3).

| Run (mode/variant) | n evaluable | TP/FP/TN/FN | Precision | Recall | F1 | FPR | Accuracy |
|---|---|---|---|---|---|---|---|
| spec/spec (HEADLINE) | 12 | 3/0/6/3 | 100.0% (CI 43.9-100.0%, 3/3) | 50.0% (CI 18.8-81.2%, 3/6) | 66.7% (CI n/a) | 0.0% (CI 0.0-39.0%, 0/6) | 75.0% (CI 46.8-91.1%, 9/12) |
| spec/no_passive (sensitivity) | 12 | 2/0/6/4 | 100.0% (CI 34.2-100.0%, 2/2) | 33.3% (CI 9.7-70.0%, 2/6) | 50.0% (CI n/a) | 0.0% (CI 0.0-39.0%, 0/6) | 66.7% (CI 39.1-86.2%, 8/12) |
| strict/spec (sensitivity) | 11 | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 57.1% (CI n/a) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |
| strict/no_passive (sensitivity) | 11 | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 57.1% (CI n/a) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |

### Sensitivity run spec/no_passive

**RESULT: WEAK / BAD on this sample.** recall is 33.3%: the system misses at least half of the fraud cases.

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Enron Corp | 2000 (as_of 2001-04-02) | Fraud-risk (High/Critical) | Fraud | High | FY1997 (filed 1998-03-31) | Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold. | OK (TP) | fetch_data: no peer group (pre-XBRL focus year 2000 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| WorldCom Inc | 2001 (as_of 2002-03-13) | Not flagged | Fraud | Low | - | Altman Z-prime score was 1.03 in FY2001, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2001 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| Luckin Coffee Inc. | 2019 (as_of 2021-06-30) | Not flagged | Fraud | Medium | - | FY2019 filing discloses restatement and material weakness: "… of these individuals in their roles as members of the board of directors of the Company; · the effect of the Non-Reliance identified in, and the resultant ... | OK (FN) | fetch_data: no peer group (reporting currency CNY != USD: asset-size matching against USD peers is not meaningful (compare ratios only; no peers selected)); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHR... | NO (filed after revelation) |
| Nikola Corp | 2020 (as_of 2021-02-25) | Not flagged | Fraud | Medium | FY2020 (filed 2021-02-25) | Auditor changed from RSM US LLP to Ernst & Young LLP in FY2020. | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Lordstown Motors Corp | 2020 (as_of 2021-03-25) | Not flagged | Fraud | Medium | FY2020 (filed 2021-03-25) | Auditor changed from WithumSmith+Brown P.C. to KPMG LLP in FY2020. | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Virgin Galactic Holdings, Inc | 2021 (as_of 2022-02-28) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-03-18) | FY2021 filing discloses material weakness: "… government regulation that impact the way we operate; •risks associated with international expansion; •our ability to timely and effectively remediate material weaknesses ... | OK (TP) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Apple Inc. | 2020 (as_of 2020-10-30) | Not flagged | Clean | Medium | - | In FY2020, receivables growth minus revenue growth was -35.2 pp, which is 39 pp below the peer mean of 3.8 pp. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Microsoft Corp | 2020 (as_of 2020-07-30) | Not flagged | Clean | Low | - | Altman Z-prime score was 1.13 in FY2017, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Johnson & Johnson | 2020 (as_of 2021-02-22) | Not flagged | Clean | Low | - | CFO changed from D. J. Caruso to J. J. Wolk in FY2018. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Procter & Gamble Co | 2020 (as_of 2020-08-06) | Not flagged | Clean | Medium | - | In FY2020, DSO was 21 days, which is 62.9% below the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Berkshire Hathaway Inc | 2020 (as_of 2021-03-01) | Not flagged | Clean | Medium | - | In FY2020, ROA 4.9% vs peer mean 1.1% (z=+2.2). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| 3M Co | 2020 (as_of 2021-02-04) | Not flagged | Clean | Medium | - | In FY2020, debt/equity was 1.46x, which is 114.1% above the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |

### Sensitivity run strict/spec

Tiny-n strict run: 11 evaluable case(s). 1 excluded.
**RESULT: WEAK / BAD on this sample.** recall is 40.0%: the system misses at least half of the fraud cases; F1 (57.1%) does not beat the Beneish-only baseline (57.1%).
0 case(s) ERRORED and 1 were EXCLUDED, so the matrix covers only 11 cases. Worst case (errored fraud counted as misses, errored clean as false alarms): recall 40.0% (CI 11.8-76.9%, 2/5), FPR 0.0% (CI 0.0-39.0%, 0/6).

**Excluded from this run:** LK (strict run: analysis filing post-dates public revelation and no earlier annual report exists (strict_alt is None))

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Enron Corp | 2000 (as_of 2001-04-02) | Fraud-risk (High/Critical) | Fraud | High | FY1997 (filed 1998-03-31) | Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold. | OK (TP) | fetch_data: no peer group (pre-XBRL focus year 2000 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| WorldCom Inc | 2001 (as_of 2002-03-13) | Not flagged | Fraud | Medium | FY2000 (filed 2001-03-30) | Altman Z-prime score was 1.03 in FY2001, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2001 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| Nikola Corp | 2019 (as_of 2020-03-06) | Not flagged | Fraud | Medium | FY2019 (filed 2020-03-06) | FY2019 filing expresses going-concern doubt: "… about an Entity's Ability to Continue as a Going Concern”, management has determined that the mandatory liquidation and subsequent dissolution raises substantial doubt a... | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Lordstown Motors Corp | 2019 (as_of 2020-03-25) | Not flagged | Fraud | Medium | - | FY2019 filing expresses going-concern doubt: "… we fail to complete our business combination, we will never generate any operating revenues. Our independent registered public accounting firm has expressed substantial ... | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Virgin Galactic Holdings, Inc | 2020 (as_of 2021-03-01) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-03-18) | Beneish M-Score was 7.12 in FY2020, above the -1.78 manipulation threshold. | OK (TP) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); critical_blocked: Jev unavailable; narrative: deterministic fall... | NO (filed after revelation) |
| Apple Inc. | 2020 (as_of 2020-10-30) | Not flagged | Clean | Medium | - | In FY2020, receivables growth minus revenue growth was -35.2 pp, which is 39 pp below the peer mean of 3.8 pp. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Microsoft Corp | 2020 (as_of 2020-07-30) | Not flagged | Clean | Low | - | 26.1% of MD&A sentences were passive-voice in FY2020 (flag threshold 15%). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Johnson & Johnson | 2020 (as_of 2021-02-22) | Not flagged | Clean | Low | - | 28.3% of MD&A sentences were passive-voice in FY2020 (flag threshold 15%). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Procter & Gamble Co | 2020 (as_of 2020-08-06) | Not flagged | Clean | Medium | - | In FY2020, DSO was 21 days, which is 62.9% below the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Berkshire Hathaway Inc | 2020 (as_of 2021-03-01) | Not flagged | Clean | Medium | - | In FY2020, ROA 4.9% vs peer mean 1.1% (z=+2.2). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| 3M Co | 2020 (as_of 2021-02-04) | Not flagged | Clean | Medium | FY2020 (filed 2021-02-04) | In FY2020, debt/equity was 1.46x, which is 114.1% above the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Luckin Coffee Inc. | - | - | Fraud | - | - | strict run: analysis filing post-dates public revelation and no earlier annual report exists (strict_alt is None) | EXCLUDED | - | - |

### Sensitivity run strict/no_passive

Tiny-n strict run: 11 evaluable case(s). 1 excluded.
**RESULT: WEAK / BAD on this sample.** recall is 40.0%: the system misses at least half of the fraud cases; F1 (57.1%) does not beat the Beneish-only baseline (57.1%).
0 case(s) ERRORED and 1 were EXCLUDED, so the matrix covers only 11 cases. Worst case (errored fraud counted as misses, errored clean as false alarms): recall 40.0% (CI 11.8-76.9%, 2/5), FPR 0.0% (CI 0.0-39.0%, 0/6).

**Excluded from this run:** LK (strict run: analysis filing post-dates public revelation and no earlier annual report exists (strict_alt is None))

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Enron Corp | 2000 (as_of 2001-04-02) | Fraud-risk (High/Critical) | Fraud | High | FY1997 (filed 1998-03-31) | Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold. | OK (TP) | fetch_data: no peer group (pre-XBRL focus year 2000 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| WorldCom Inc | 2001 (as_of 2002-03-13) | Not flagged | Fraud | Low | - | Altman Z-prime score was 1.03 in FY2001, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (FN) | fetch_data: no peer group (pre-XBRL focus year 2001 (< 2009): no companyfacts/frames for peers); language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); tempora... | yes |
| Nikola Corp | 2019 (as_of 2020-03-06) | Not flagged | Fraud | Medium | - | FY2019 filing expresses going-concern doubt: "… about an Entity's Ability to Continue as a Going Concern”, management has determined that the mandatory liquidation and subsequent dissolution raises substantial doubt a... | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Lordstown Motors Corp | 2019 (as_of 2020-03-25) | Not flagged | Fraud | Medium | - | FY2019 filing expresses going-concern doubt: "… we fail to complete our business combination, we will never generate any operating revenues. Our independent registered public accounting firm has expressed substantial ... | OK (FN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | NO (filed after revelation) |
| Virgin Galactic Holdings, Inc | 2020 (as_of 2021-03-01) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-03-18) | Beneish M-Score was 7.12 in FY2020, above the -1.78 manipulation threshold. | OK (TP) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); critical_blocked: Jev unavailable; narrative: deterministic fall... | NO (filed after revelation) |
| Apple Inc. | 2020 (as_of 2020-10-30) | Not flagged | Clean | Medium | - | In FY2020, receivables growth minus revenue growth was -35.2 pp, which is 39 pp below the peer mean of 3.8 pp. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Microsoft Corp | 2020 (as_of 2020-07-30) | Not flagged | Clean | Low | - | Altman Z-prime score was 1.13 in FY2017, inside the distress zone (below 1.23); a business-distress signal, not evidence of accounting manipulation. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Johnson & Johnson | 2020 (as_of 2021-02-22) | Not flagged | Clean | Low | - | CFO changed from D. J. Caruso to J. J. Wolk in FY2018. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Procter & Gamble Co | 2020 (as_of 2020-08-06) | Not flagged | Clean | Medium | - | In FY2020, DSO was 21 days, which is 62.9% below the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Berkshire Hathaway Inc | 2020 (as_of 2021-03-01) | Not flagged | Clean | Medium | - | In FY2020, ROA 4.9% vs peer mean 1.1% (z=+2.2). | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| 3M Co | 2020 (as_of 2021-02-04) | Not flagged | Clean | Medium | - | In FY2020, debt/equity was 1.46x, which is 114.1% above the peer group average. | OK (TN) | language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable (no heuristic stand-in is computed); llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used); jev: unavailable (JEV_API_KEY not set); narrative: deterministic fallback (no key / LLM unavailable); ev... | yes |
| Luckin Coffee Inc. | - | - | Fraud | - | - | strict run: analysis filing post-dates public revelation and no earlier annual report exists (strict_alt is None) | EXCLUDED | - | - |

## Baselines (same evaluable cases)

| Run | Predictor | TP/FP/TN/FN | Precision | Recall | FPR | Accuracy |
|---|---|---|---|---|---|---|
| spec/spec | System | 3/0/6/3 | 100.0% (CI 43.9-100.0%, 3/3) | 50.0% (CI 18.8-81.2%, 3/6) | 0.0% (CI 0.0-39.0%, 0/6) | 75.0% (CI 46.8-91.1%, 9/12) |
| spec/spec | Beneish-only (M > -1.78 in focus year) | 1/0/6/5 | 100.0% (CI 20.7-100.0%, 1/1) | 16.7% (CI 3.0-56.4%, 1/6) | 0.0% (CI 0.0-39.0%, 0/6) | 58.3% (CI 32.0-80.7%, 7/12) |
| spec/spec | Always predict clean | 0/0/6/6 | n/a (undefined, 0/0) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-39.0%, 0/6) | 50.0% (CI 25.4-74.6%, 6/12) |
| spec/no_passive | System | 2/0/6/4 | 100.0% (CI 34.2-100.0%, 2/2) | 33.3% (CI 9.7-70.0%, 2/6) | 0.0% (CI 0.0-39.0%, 0/6) | 66.7% (CI 39.1-86.2%, 8/12) |
| spec/no_passive | Beneish-only (M > -1.78 in focus year) | 1/0/6/5 | 100.0% (CI 20.7-100.0%, 1/1) | 16.7% (CI 3.0-56.4%, 1/6) | 0.0% (CI 0.0-39.0%, 0/6) | 58.3% (CI 32.0-80.7%, 7/12) |
| spec/no_passive | Always predict clean | 0/0/6/6 | n/a (undefined, 0/0) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-39.0%, 0/6) | 50.0% (CI 25.4-74.6%, 6/12) |
| strict/spec | System | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |
| strict/spec | Beneish-only (M > -1.78 in focus year) | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |
| strict/spec | Always predict clean | 0/0/6/5 | n/a (undefined, 0/0) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-39.0%, 0/6) | 54.5% (CI 28.0-78.7%, 6/11) |
| strict/no_passive | System | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |
| strict/no_passive | Beneish-only (M > -1.78 in focus year) | 2/0/6/3 | 100.0% (CI 34.2-100.0%, 2/2) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 72.7% (CI 43.4-90.3%, 8/11) |
| strict/no_passive | Always predict clean | 0/0/6/5 | n/a (undefined, 0/0) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-39.0%, 0/6) | 54.5% (CI 28.0-78.7%, 6/11) |

spec/spec: Beneish unavailable (counted as 'predict clean') for: LK, RIDE, SPCE, BRK-B.

spec/no_passive: Beneish unavailable (counted as 'predict clean') for: LK, RIDE, SPCE, BRK-B.

strict/spec: Beneish unavailable (counted as 'predict clean') for: NKLA, RIDE, BRK-B.

strict/no_passive: Beneish unavailable (counted as 'predict clean') for: NKLA, RIDE, BRK-B.

## Per-agent contribution

Flagging = agent severity Medium or High. Unique catch = fraud case flagged by this agent and by no other of agents 1-4. Plain flag rate (fraud) and false-alarm rate (clean) are reported alongside.

### spec/spec (fraud n=6, clean n=6, detected n=3)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 16.7% (CI 3.0-56.4%, 1/6) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-56.1%, 0/3) | - |
| language | 50.0% (CI 18.8-81.2%, 3/6) | 0.0% (CI 0.0-39.0%, 0/6) | 1 (WCOM) | 16.7% (CI 3.0-56.4%, 1/6) | 0.0% (CI 0.0-56.1%, 0/3) | - |
| network | 83.3% (CI 43.6-97.0%, 5/6) | 0.0% (CI 0.0-39.0%, 0/6) | 2 (LK, NKLA) | 33.3% (CI 9.7-70.0%, 2/6) | 0.0% (CI 0.0-56.1%, 0/3) | - |
| peer | 16.7% (CI 3.0-56.4%, 1/6) | 16.7% (CI 3.0-56.4%, 1/6) | 0 (-) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-56.1%, 0/3) | ENRNQ, WCOM, LK |
| temporal | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-39.0%, 0/6) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 1/3 | ENRNQ |
| language | 0/3 | - |
| network | 2/3 | RIDE, SPCE |
| peer | 1/3 | SPCE |
| temporal | 0/3 | - |

### spec/no_passive (fraud n=6, clean n=6, detected n=2)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 16.7% (CI 3.0-56.4%, 1/6) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| language | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| network | 83.3% (CI 43.6-97.0%, 5/6) | 0.0% (CI 0.0-39.0%, 0/6) | 3 (LK, NKLA, RIDE) | 50.0% (CI 18.8-81.2%, 3/6) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| peer | 16.7% (CI 3.0-56.4%, 1/6) | 16.7% (CI 3.0-56.4%, 1/6) | 0 (-) | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-65.8%, 0/2) | ENRNQ, WCOM, LK |
| temporal | 0.0% (CI 0.0-39.0%, 0/6) | 0.0% (CI 0.0-39.0%, 0/6) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 1/2 | ENRNQ |
| language | 0/2 | - |
| network | 1/2 | SPCE |
| peer | 1/2 | SPCE |
| temporal | 0/2 | - |

### strict/spec (fraud n=5, clean n=6, detected n=2)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| language | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 1 (WCOM) | 20.0% (CI 3.6-62.4%, 1/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| network | 80.0% (CI 37.6-96.4%, 4/5) | 0.0% (CI 0.0-39.0%, 0/6) | 2 (NKLA, RIDE) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| peer | 20.0% (CI 3.6-62.4%, 1/5) | 16.7% (CI 3.0-56.4%, 1/6) | 0 (-) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-65.8%, 0/2) | ENRNQ, WCOM |
| temporal | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-39.0%, 0/6) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 2/2 | ENRNQ, SPCE |
| language | 0/2 | - |
| network | 1/2 | SPCE |
| peer | 1/2 | SPCE |
| temporal | 0/2 | - |

### strict/no_passive (fraud n=5, clean n=6, detected n=2)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| language | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-39.0%, 0/6) | 0 (-) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| network | 80.0% (CI 37.6-96.4%, 4/5) | 0.0% (CI 0.0-39.0%, 0/6) | 2 (NKLA, RIDE) | 40.0% (CI 11.8-76.9%, 2/5) | 0.0% (CI 0.0-65.8%, 0/2) | - |
| peer | 20.0% (CI 3.6-62.4%, 1/5) | 16.7% (CI 3.0-56.4%, 1/6) | 0 (-) | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-65.8%, 0/2) | ENRNQ, WCOM |
| temporal | 0.0% (CI 0.0-43.4%, 0/5) | 0.0% (CI 0.0-39.0%, 0/6) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 2/2 | ENRNQ, SPCE |
| language | 0/2 | - |
| network | 1/2 | SPCE |
| peer | 1/2 | SPCE |
| temporal | 0/2 | - |

## Detection timing (D14)

### spec/spec

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| ENRNQ | FY1997 filed 1998-03-31 | 2001-10-16 | 2001-12-02 | 42.5 | 44.1 | early |
| RIDE | FY2020 filed 2021-03-25 | 2021-03-12 | 2021-06-14 | -0.4 | 2.7 | not early (at/after revelation) (filing post-dates revelation: not a valid early-warning test) |
| SPCE | FY2018 filed 2019-03-18 | 2021-09-01 | 2021-10-14 | 29.5 | 30.9 | early (filing post-dates revelation: not a valid early-warning test) |

Average months early (before revelation, early cases only): 36.0 (n early = 2, n not early = 1; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

### spec/no_passive

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| ENRNQ | FY1997 filed 1998-03-31 | 2001-10-16 | 2001-12-02 | 42.5 | 44.1 | early |
| SPCE | FY2018 filed 2019-03-18 | 2021-09-01 | 2021-10-14 | 29.5 | 30.9 | early (filing post-dates revelation: not a valid early-warning test) |

Average months early (before revelation, early cases only): 36.0 (n early = 2, n not early = 0; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

### strict/spec

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| ENRNQ | FY1997 filed 1998-03-31 | 2001-10-16 | 2001-12-02 | 42.5 | 44.1 | early |
| SPCE | FY2018 filed 2019-03-18 | 2021-09-01 | 2021-10-14 | 29.5 | 30.9 | early (filing post-dates revelation: not a valid early-warning test) |

Average months early (before revelation, early cases only): 36.0 (n early = 2, n not early = 0; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

### strict/no_passive

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| ENRNQ | FY1997 filed 1998-03-31 | 2001-10-16 | 2001-12-02 | 42.5 | 44.1 | early |
| SPCE | FY2018 filed 2019-03-18 | 2021-09-01 | 2021-10-14 | 29.5 | 30.9 | early (filing post-dates revelation: not a valid early-warning test) |

Average months early (before revelation, early cases only): 36.0 (n early = 2, n not early = 0; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

## Breakdown by fraud nature

Only financial-statement frauds are in scope for a statement-based detector; disclosure/claims cases are reported separately.

### spec/spec

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| disclosure_claims | 3 | 3 | 2 | 66.7% (CI 20.8-93.9%, 2/3) | NKLA=Medium; RIDE=High; SPCE=High |
| financial_statement | 3 | 3 | 1 | 33.3% (CI 6.1-79.2%, 1/3) | ENRNQ=High; WCOM=Medium; LK=Medium |

### spec/no_passive

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| disclosure_claims | 3 | 3 | 1 | 33.3% (CI 6.1-79.2%, 1/3) | NKLA=Medium; RIDE=Medium; SPCE=High |
| financial_statement | 3 | 3 | 1 | 33.3% (CI 6.1-79.2%, 1/3) | ENRNQ=High; WCOM=Low; LK=Medium |

### strict/spec

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| disclosure_claims | 3 | 3 | 1 | 33.3% (CI 6.1-79.2%, 1/3) | NKLA=Medium; RIDE=Medium; SPCE=High |
| financial_statement | 2 | 2 | 1 | 50.0% (CI 9.5-90.5%, 1/2) | ENRNQ=High; WCOM=Medium |

### strict/no_passive

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| disclosure_claims | 3 | 3 | 1 | 33.3% (CI 6.1-79.2%, 1/3) | NKLA=Medium; RIDE=Medium; SPCE=High |
| financial_statement | 2 | 2 | 1 | 50.0% (CI 9.5-90.5%, 1/2) | ENRNQ=High; WCOM=Low |

## Run metadata

| Field | Value |
|---|---|
| Timestamp (UTC) | 2026-10-16T17:07:16Z |
| Code hash (sha256) | 6b836165ec2d45b5de9f99f72072b335d50df82dd59f40c7a7644cb0804000a9 |
| Code hash covers | agents/*.py, tools/*.py, graph/*.py, evaluation/fraud_cases.py, prompts/templates.py |
| ANTHROPIC key available | False |
| JEV key available | False |
| Analysis source | graph.pipeline.analyze_company |
| Modes / variants | ['spec', 'strict'] / ['spec', 'no_passive'] |
| Versions | python=3.14.4; platform=Windows-11-10.0.26200-SP0; langgraph=1.2.10; langchain=1.3.14; langchain-anthropic=1.5.3; anthropic=0.120.2; typesafe-sdk=0.7.2; httpx=0.28.1; pandas=3.0.5; numpy=2.5.1; spacy=3.8.16; beautifulsoup4=4.15.0 |

Degraded components per run (union over cases):

* spec/spec: fetch_data [ENRNQ, WCOM, LK]; language_specificity [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; llm_explanations [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; temporal [ENRNQ, WCOM, LK]; jev [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; synthesis [ENRNQ, WCOM, LK]; narrative [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; eval [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]
* spec/no_passive: fetch_data [ENRNQ, WCOM, LK]; language_specificity [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; llm_explanations [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; temporal [ENRNQ, WCOM, LK]; jev [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; synthesis [ENRNQ, WCOM, LK]; narrative [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; eval [ENRNQ, WCOM, LK, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]
* strict/spec: fetch_data [ENRNQ, WCOM]; language_specificity [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; llm_explanations [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; temporal [ENRNQ, WCOM]; jev [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; synthesis [ENRNQ, WCOM]; narrative [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; eval [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; critical_blocked [SPCE]
* strict/no_passive: fetch_data [ENRNQ, WCOM]; language_specificity [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; llm_explanations [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; temporal [ENRNQ, WCOM]; jev [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; synthesis [ENRNQ, WCOM]; narrative [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; eval [ENRNQ, WCOM, NKLA, RIDE, SPCE, AAPL, MSFT, JNJ, PG, BRK-B, MMM]; critical_blocked [SPCE]

## LIMITATIONS AND CONTAMINATION (READ BEFORE QUOTING ANY NUMBER)

> **WARNING: these results are NOT clean out-of-sample evidence.** The sample is 12 hand-picked, famous cases, some rules were fitted with evaluation-set filings in view (ledger below), and most fraud filings post-date the fraud's public revelation.

1. **Look-ahead: 4 of 6 fraud filings post-date public revelation** (LK, NKLA, RIDE, SPCE). The spec (headline) run therefore sees information that was already public; a 'detection' there is not early warning. Only Enron and WorldCom filings precede revelation (WorldCom disclosed an SEC document request two days before its 10-K405).
2. **Only 3 of 6 fraud cases are financial-statement frauds** (ENRNQ, WCOM, LK). Nikola, Lordstown and Virgin Galactic are disclosure/claims cases (product claims, pre-orders, safety statements); a statement-based detector is not expected to fire on them. Virgin Galactic's fraud label is WEAK (settled class action, no SEC accounting finding). Luckin's FY2019 20-F was produced after the internal investigation; whether it still contains the fabricated sales was not verified.
3. **The clean set is six surviving US mega-caps, not matched** on size, industry or distress (AAPL, MSFT, JNJ, PG, BRK-B, MMM). 'Clean' means only 'no known accounting fraud/restatement' (absence of evidence from a web search). Survivorship and selection bias apply to both sets; BRK-B is an insurer to which Beneish/Altman apply poorly.
4. **n = 12, so confidence intervals are wide** (6 vs 6). Differences between variants/baselines of one or two cases are not statistically meaningful.
5. **The strict run has a tiny n**: Luckin is excluded (no pre-revelation annual report), Nikola and Lordstown fall back to SPAC-shell 10-Ks (no operating business), leaving effectively 2 operating-company fraud filings (Enron, WorldCom) plus Virgin Galactic FY2020. Treat strict numbers as anecdotes.
6. **Detection timing is quantised** to annual filing dates (D14) and is only meaningful for pre-revelation filings.
7. **Degraded run: ANTHROPIC_API_KEY, JEV_API_KEY not available.** LLM specificity scoring, LLM narrative and Jev confidence scoring are unavailable, so the language agent's specificity flag is off, Jev-gated 'Critical' grades are unreachable (capped at High), and any result here understates what the full system would do (or does).

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
