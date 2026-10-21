# Retrospective Validation Report - forensic-filing-agent

Generated 2026-10-17T18:07:00Z (UTC). Code hash `392412fa4118383f`. Analysis source: graph.pipeline.analyze_company.

> **DEGRADED RUN - results are NOT the full system's performance.** degraded components seen: eval

> **PARTIAL RUN: only 24 case(s) evaluated (OSIR, TNGO, CGI, SNCR, RRTS, GVA, USAT, QTM, OFIX, LIME, TEUM, PTRY, NSTG, LPSN, LSTR, EPAM, HUBG, MTZ, ALOT, MITK, ICUI, AGX, BAND, RAH); headline metrics are not the 12-case evaluation.**

> **Contamination warning:** 4 of 6 fraud filings post-date revelation, only 3 of 6 are financial-statement frauds, the clean set is not matched, n=12. See [Limitations and contamination](#limitations-and-contamination-read-before-quoting-any-number).

## Headline (mode spec, variant spec)

**RESULT: WEAK / BAD on this sample.** false-positive rate is 100.0%: it flags at least a quarter of the clean companies; accuracy 50.0% is no better than the trivial 'always predict clean' baseline (50.0%).

| n evaluable | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|---|
| 24 | 12 | 12 | 0 | 0 | 50.0% (CI 31.4-68.6%, 12/24) | 100.0% (CI 75.8-100.0%, 12/12) | 66.7% (CI n/a) | 100.0% (CI 75.8-100.0%, 12/12) |

Positive prediction = risk_grade High or Critical. CIs are exact Wilson 95% intervals; F1 has no closed-form Wilson interval. A case whose analysis errored or returned grade 'Unknown' is status ERROR and is excluded from the matrix (never counted as negative).

### Case-by-case (headline)

| Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded | Pre-revelation valid |
|---|---|---|---|---|---|---|---|---|---|
| Osiris Therapeutics, Inc. | 2014 (as_of 2015-03-20) | Fraud-risk (High/Critical) | Fraud | High | FY2014 (filed 2015-03-20) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Tangoe, Inc. | 2014 (as_of 2015-03-16) | Fraud-risk (High/Critical) | Fraud | High | FY2014 (filed 2015-03-16) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Celadon Group, Inc. | 2016 (as_of 2016-09-13) | Fraud-risk (High/Critical) | Fraud | High | FY2016 (filed 2016-09-13) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Synchronoss Technologies, Inc. | 2016 (as_of 2017-02-27) | Fraud-risk (High/Critical) | Fraud | High | FY2016 (filed 2017-02-27) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Roadrunner Transportation Systems, Inc. | 2015 (as_of 2016-03-01) | Fraud-risk (High/Critical) | Fraud | High | FY2015 (filed 2016-03-01) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Granite Construction Incorporated | 2018 (as_of 2019-02-22) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-02-22) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| USA Technologies, Inc. (now Cantaloupe, Inc.) | 2017 (as_of 2017-08-23) | Fraud-risk (High/Critical) | Fraud | High | FY2017 (filed 2017-08-23) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Quantum Corporation | 2017 (as_of 2017-06-01) | Fraud-risk (High/Critical) | Fraud | High | FY2017 (filed 2017-06-01) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Orthofix International N.V. (now Orthofix Medical Inc.) | 2012 (as_of 2013-03-01) | Fraud-risk (High/Critical) | Fraud | High | FY2012 (filed 2013-03-01) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Lime Energy Co. | 2011 (as_of 2012-03-16) | Fraud-risk (High/Critical) | Fraud | High | FY2011 (filed 2012-03-16) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Pareteum Corporation | 2018 (as_of 2019-03-18) | Fraud-risk (High/Critical) | Fraud | High | FY2018 (filed 2019-03-18) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| American Italian Pasta Company | 2004 (as_of 2004-12-15) | Fraud-risk (High/Critical) | Fraud | High | FY2004 (filed 2004-12-15) | - | OK (TP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| NanoString Technologies, Inc. (EDGAR: NS Wind Down Co., Inc.) | 2014 (as_of 2015-03-13) | Fraud-risk (High/Critical) | Clean | High | FY2014 (filed 2015-03-13) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| LivePerson, Inc. | 2014 (as_of 2015-03-12) | Fraud-risk (High/Critical) | Clean | High | FY2014 (filed 2015-03-12) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Landstar System, Inc. | 2016 (as_of 2017-02-24) | Fraud-risk (High/Critical) | Clean | High | FY2016 (filed 2017-02-24) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| EPAM Systems, Inc. | 2016 (as_of 2017-03-01) | Fraud-risk (High/Critical) | Clean | High | FY2016 (filed 2017-03-01) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Hub Group, Inc. | 2015 (as_of 2016-02-26) | Fraud-risk (High/Critical) | Clean | High | FY2015 (filed 2016-02-26) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| MasTec, Inc. | 2018 (as_of 2019-02-28) | Fraud-risk (High/Critical) | Clean | High | FY2018 (filed 2019-02-28) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| AstroNova, Inc. | 2017 (as_of 2018-04-10) | Fraud-risk (High/Critical) | Clean | High | FY2017 (filed 2018-04-10) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Mitek Systems, Inc. | 2017 (as_of 2017-11-30) | Fraud-risk (High/Critical) | Clean | High | FY2017 (filed 2017-11-30) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| ICU Medical, Inc. | 2012 (as_of 2013-02-26) | Fraud-risk (High/Critical) | Clean | High | FY2012 (filed 2013-02-26) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Argan, Inc. | 2011 (as_of 2012-04-13) | Fraud-risk (High/Critical) | Clean | High | FY2011 (filed 2012-04-13) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Bandwidth Inc. | 2018 (as_of 2019-02-15) | Fraud-risk (High/Critical) | Clean | High | FY2018 (filed 2019-02-15) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |
| Ralcorp Holdings, Inc. | 2004 (as_of 2004-12-14) | Fraud-risk (High/Critical) | Clean | High | FY2004 (filed 2004-12-14) | - | OK (FP) | eval: jev unavailable (no Jev confidence; Critical grade unreachable) | yes |

## All runs: headline and sensitivity

Only spec/spec is the headline. Every other row is a labelled sensitivity run (strict = point-in-time re-run of look-ahead cases with the last pre-revelation filing; no_passive = pre-registered variant without the passive-voice flag, declared before the run, see ledger P2/P3).

| Run (mode/variant) | n evaluable | TP/FP/TN/FN | Precision | Recall | F1 | FPR | Accuracy |
|---|---|---|---|---|---|---|---|
| spec/spec (HEADLINE) | 24 | 12/12/0/0 | 50.0% (CI 31.4-68.6%, 12/24) | 100.0% (CI 75.8-100.0%, 12/12) | 66.7% (CI n/a) | 100.0% (CI 75.8-100.0%, 12/12) | 50.0% (CI 31.4-68.6%, 12/24) |

## Baselines (same evaluable cases)

| Run | Predictor | TP/FP/TN/FN | Precision | Recall | FPR | Accuracy |
|---|---|---|---|---|---|---|
| spec/spec | System | 12/12/0/0 | 50.0% (CI 31.4-68.6%, 12/24) | 100.0% (CI 75.8-100.0%, 12/12) | 100.0% (CI 75.8-100.0%, 12/12) | 50.0% (CI 31.4-68.6%, 12/24) |
| spec/spec | Beneish-only (M > -1.78 in focus year) | 0/0/12/12 | n/a (undefined, 0/0) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 50.0% (CI 31.4-68.6%, 12/24) |
| spec/spec | Always predict clean | 0/0/12/12 | n/a (undefined, 0/0) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 50.0% (CI 31.4-68.6%, 12/24) |

spec/spec: Beneish unavailable (counted as 'predict clean') for: OSIR, TNGO, CGI, SNCR, RRTS, GVA, USAT, QTM, OFIX, LIME, TEUM, PTRY, NSTG, LPSN, LSTR, EPAM, HUBG, MTZ, ALOT, MITK, ICUI, AGX, BAND, RAH.

## Per-agent contribution

Flagging = agent severity Medium or High. Unique catch = fraud case flagged by this agent and by no other of agents 1-4. Plain flag rate (fraud) and false-alarm rate (clean) are reported alongside.

### spec/spec (fraud n=12, clean n=12, detected n=12)

| Agent | Flag rate on fraud | False-alarm rate on clean | Unique catches | Unique % of all fraud | Unique % of detected | Unavailable on |
|---|---|---|---|---|---|---|
| quantitative | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 0 (-) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | - |
| language | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 0 (-) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | - |
| network | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 0 (-) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | - |
| peer | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | 0 (-) | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | - |
| temporal | 0.0% (CI 0.0-24.2%, 0/12) | 0.0% (CI 0.0-24.2%, 0/12) | n/a (derived) | n/a | n/a | - |

Decisive agent (severity High among true positives):

| Agent | High on TPs | Cases |
|---|---|---|
| quantitative | 0/12 | - |
| language | 0/12 | - |
| network | 0/12 | - |
| peer | 0/12 | - |
| temporal | 0/12 | - |

## Detection timing (D14)

### spec/spec

| Case | First detection filing | Revelation | Collapse | Months before revelation | Months before collapse | Note |
|---|---|---|---|---|---|---|
| OSIR | FY2014 filed 2015-03-20 | 2015-11-06 | - | 7.6 | - | early |
| TNGO | FY2014 filed 2015-03-16 | 2016-03-07 | - | 11.7 | - | early |
| CGI | FY2016 filed 2016-09-13 | 2017-05-01 | - | 7.6 | - | early |
| SNCR | FY2016 filed 2017-02-27 | 2017-05-15 | - | 2.5 | - | early |
| RRTS | FY2015 filed 2016-03-01 | 2017-01-30 | - | 11.0 | - | early |
| GVA | FY2018 filed 2019-02-22 | 2020-03-02 | - | 12.3 | - | early |
| USAT | FY2017 filed 2017-08-23 | 2018-09-11 | - | 12.6 | - | early |
| QTM | FY2017 filed 2017-06-01 | 2018-02-08 | - | 8.3 | - | early |
| OFIX | FY2012 filed 2013-03-01 | 2013-07-29 | - | 4.9 | - | early |
| LIME | FY2011 filed 2012-03-16 | 2012-07-17 | - | 4.0 | - | early |
| TEUM | FY2018 filed 2019-03-18 | 2019-10-21 | - | 7.1 | - | early |
| PTRY | FY2004 filed 2004-12-15 | 2005-08-09 | - | 7.8 | - | early |

Average months early (before revelation, early cases only): 8.1 (n early = 12, n not early = 0; not-early cases are shown above but excluded from the average). Positive = early, negative = after revelation.

*Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); months = days/30.44 between the first-detection filing date and the event; negative = not early and is excluded from the average.*

## Breakdown by fraud nature

Only financial-statement frauds are in scope for a statement-based detector; disclosure/claims cases are reported separately.

### spec/spec

| Fraud nature | Cases | Evaluable | TP | Recall | Case detail |
|---|---|---|---|---|---|
| financial_statement | 12 | 12 | 12 | 100.0% (CI 75.8-100.0%, 12/12) | OSIR=High; TNGO=High; CGI=High; SNCR=High; RRTS=High; GVA=High; USAT=High; QTM=High; OFIX=High; LIME=High; TEUM=High; PTRY=High |

## Run metadata

| Field | Value |
|---|---|
| Timestamp (UTC) | 2026-10-17T18:07:00Z |
| Code hash (sha256) | 392412fa4118383f6eaeceb5422066b2f796908635685f4889da5ff5934dd246 |
| Code hash covers | agents/*.py, tools/*.py, graph/*.py, evaluation/fraud_cases.py, prompts/templates.py |
| ANTHROPIC key available | True |
| JEV key available | True |
| Analysis source | graph.pipeline.analyze_company |
| Modes / variants | ['spec'] / ['spec'] |
| Versions | python=3.14.4; platform=Windows-11-10.0.26200-SP0; langgraph=1.2.10; langchain=1.3.14; langchain-anthropic=1.5.3; anthropic=0.120.2; typesafe-sdk=0.7.2; httpx=0.28.1; pandas=3.0.5; numpy=2.5.1; spacy=3.8.16; beautifulsoup4=4.15.0 |

Degraded components per run (union over cases):

* spec/spec: eval [OSIR, TNGO, CGI, SNCR, RRTS, GVA, USAT, QTM, OFIX, LIME, TEUM, PTRY, NSTG, LPSN, LSTR, EPAM, HUBG, MTZ, ALOT, MITK, ICUI, AGX, BAND, RAH]

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

##### v2 dev-motivated (graph/pipeline.py; see docs/V2_CHANGELOG_pipeline.md)
| # | Date | Module | What was done | Evidence looked at | Dev-case overlap | Effect |
|---|------|--------|---------------|--------------------|------------------|--------|
| v2-P1 | 2026-10-16 | graph/pipeline.py | Shell/SPAC-predecessor/stub detection (cover box, blank-check vocabulary, 25,000-char stub floor, successor closing-date rule) | Nikola FY2018-20, Lordstown FY2019-20, Virgin Galactic FY2017-21, Enron FY1996 stub, AAPL/MSFT/JNJ/PG/BRK-B/MMM FY2015-20 (controls) | YES (dev) | Years flagged and kept; consumers must not use them as YoY baselines. Floor chosen from the empty gap 15,667 vs 60,252 chars, not fitted to an outcome. |
| v2-P2 | 2026-10-16 | graph/pipeline.py | Prior-year re-run for Jev material_change | Enron FY2000, Nikola FY2020 live runs (wiring check only) | YES (dev) | No threshold changed. |

##### v2 dev-motivated changes (merged 2026-10-16; per-change rows with rationale/tests live in the changelogs)
Every change below was found by studying the 12 DEV cases (docs/EVAL_AUDIT.md) and is therefore NOT validated by dev results.
The only unbiased estimate of v2 is the sealed holdout (docs/V2_PROTOCOL.md). Spec numeric thresholds unchanged except where noted.
| Area | Changelog | Summary | Spec deviation? |
|---|---|---|---|
| text_parser / network (B1, B9, B10, B11, B12, mojibake, fee parsing) | docs/V2_CHANGELOG_text_network.md | Reported-weakness-only detection; like-for-like related-party measure; merger/shell context not counted; legal note exposure; Item 9A evidence | No numeric change; SPAC-shell going-concern suppression is a judgement call |
| language / peer / quant / synthesis / temporal (B3-B8, B11 consumer) | docs/V2_CHANGELOG_agents.md | Focus-year escalation only; Medium rule needs a focus-year flag; manipulation-consistent peer directions only (a-priori table with citations); revenue<1% of assets => not meaningful; shell years never baselines | YES: passive-voice 15% cut-off replaced by >25% YoY increase; Medium rule wording (CONTRACTS s6) |
| pipeline (B2, B8, Jev) | docs/V2_CHANGELOG_pipeline.md | Shell/SPAC/stub detection (stub floor 25,000 chars set from dev evidence); prior-year re-run for Jev material_change | No |
| xbrl_parser (provenance bug) | docs/V2_CHANGELOG_xbrl.md | Facts ending after the filing date can't define a filing's period of report; corrected P&G FY2012/13 values and FY2020 provenance | No (data-correctness fix; v1 snapshot retains the bug, so v1-vs-v2 holdout differences partly reflect it) |
Known weak spots deliberately left for v3: new_legal from long litigation notes fires often (MMM/JNJ); ROA-above-peers is the weakest peer direction; non-SPAC reverse mergers undetected.

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
