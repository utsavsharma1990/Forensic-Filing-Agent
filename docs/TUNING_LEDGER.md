# Tuning / contamination ledger

Purpose: every place where a rule, guard or threshold was influenced by looking at filings that are ALSO evaluation cases.
The evaluation report (evaluation/results/evaluation_report.md) MUST reproduce this list under "Known contamination of the evaluation".
Thresholds from the spec / literature (Beneish cut-offs, +25% hedging, +30% fees, |z|>2, etc.) were NOT changed by any entry below.

| # | Date | Module | What was done | Evidence looked at | Eval-case overlap | Effect |
|---|------|--------|---------------|--------------------|-------------------|--------|
| 1 | 2026-10-16 | agents/network_agent.py | Added agent-level false-positive guards: restatement hit must have an error/non-reliance cue and not be an adoption recast / "Amendment and Restatement of ... Plan" exhibit title / "incorporated by reference"; ASU 2014-15 boilerplate not counted as going concern; audit-fee ratio >10x or <0.1x treated as unit-parse error; name normalisation for garbled CEO/CFO text. | Base-rate runs on AAPL, MSFT, JNJ, PG, MMM, BRK-B FY2016-2020 (first unguarded run: 8 restatement hits, 1 going-concern hit, 1 fee hit, 1 false CFO change; all removed by guards). | YES - the six clean evaluation companies (FY2020 filings are in that range). | Lowers false positives on the clean set; base rates after guards are NOT out-of-sample. Guards are boilerplate/parse-error fixes, not changes to the spec thresholds, but they were fitted with clean-set filings in view. |
| 2 | 2026-10-16 | agents/network_agent.py | WorldCom FY2000 `network.related_party` fires on a 180-char -> 8,219-char jump (Item 13 pointer vs full disclosure). Left flagged deliberately: un-flagging it would be tuning on an evaluation case. | WorldCom FY2000/2001 | YES | Possible weak/spurious flag retained; reported as is. |

Rules for future entries: add a row BEFORE merging any change motivated by an evaluation-case filing; if the change cannot be
justified independently of the evaluation set, do not make it.

## Pre-registered variants (declared BEFORE any evaluation run, 2026-10-16)
| # | Variant | Why declared | Reporting rule |
|---|---------|--------------|----------------|
| P1 | `spec` (headline): all spec flags incl. `language.passive_voice` (>15% of MD&A sentences). | Spec-literal. | Always reported first. |
| P2 | `no_passive`: identical but `language.passive_voice` is excluded from flags, severity and temporal scoring. | Language agent base-rate run: passive voice fired on 25/25 healthy large-cap company-years (MD&A passive share 21.7-31.2%), i.e. no information at the spec's 15% cut-off. NOTE: motivated by looking at filings that include the clean evaluation companies (see entry 1 caveat). | Reported as a sensitivity row next to the headline; never replaces it; the report states that it was declared before the run and why. |
| P3 | `strict`: contaminated fraud cases re-run with the last annual filing filed before public revelation (`strict_alt`), cases with none excluded and listed. | docs/case_research.md validity findings (4 of 6 fraud filings post-date revelation). | Sensitivity analysis; tiny n; report with CIs. |

## Known data artifacts (disclosed, NOT corrected; found 2026-10-16 in the first real pipeline runs)
| # | Case | Artifact | Consequence for reading results |
|---|------|----------|--------------------------------|
| A1 | ENRNQ | The FY1996 "annual report" under CIK 0001024401 is a 15,667-character shell (the real FY1996 10-K sits under predecessor CIK 72859). The FY1997-vs-FY1996 comparison therefore produces spurious CEO/CFO changes, a spurious new-legal flag and a 1997 suspicion peak. | Enron `first_detection_year` = 1997 is very likely an artifact; do not quote it as evidence of early detection. FY2000 signals (Beneish M=-0.66, CEO change, related-party growth) are unaffected. |
| A2 | ENRNQ | Audit fees parsed only for FY2000 (proxy format of 2001); FY1997-99 proxies fetched but nothing extracted. | Audit-fee trend signal untested for Enron. |
| A3 | LK | No annual report exists before the April 2020 revelation; the FY2019 20-F (filed 2021-06-30) post-dates the revelation and the internal investigation. FY2018 exists only as a comparative. Beneish unavailable (no COGS/SG&A tags). | Luckin is not a true point-in-time test and is excluded from the strict run. |
| A4 | AAPL | Medium grade at FY2020 comes only from two favourable-direction peer outliers plus the passive-voice flag. | Peer flags are two-sided per spec; this is a false-positive mechanism, reported as is. |

## v2 dev-motivated (graph/pipeline.py; see docs/V2_CHANGELOG_pipeline.md)
| # | Date | Module | What was done | Evidence looked at | Dev-case overlap | Effect |
|---|------|--------|---------------|--------------------|------------------|--------|
| v2-P1 | 2026-10-16 | graph/pipeline.py | Shell/SPAC-predecessor/stub detection (cover box, blank-check vocabulary, 25,000-char stub floor, successor closing-date rule) | Nikola FY2018-20, Lordstown FY2019-20, Virgin Galactic FY2017-21, Enron FY1996 stub, AAPL/MSFT/JNJ/PG/BRK-B/MMM FY2015-20 (controls) | YES (dev) | Years flagged and kept; consumers must not use them as YoY baselines. Floor chosen from the empty gap 15,667 vs 60,252 chars, not fitted to an outcome. |
| v2-P2 | 2026-10-16 | graph/pipeline.py | Prior-year re-run for Jev material_change | Enron FY2000, Nikola FY2020 live runs (wiring check only) | YES (dev) | No threshold changed. |

## v2 dev-motivated changes (merged 2026-10-16; per-change rows with rationale/tests live in the changelogs)
Every change below was found by studying the 12 DEV cases (docs/EVAL_AUDIT.md) and is therefore NOT validated by dev results.
The only unbiased estimate of v2 is the sealed holdout (docs/V2_PROTOCOL.md). Spec numeric thresholds unchanged except where noted.
| Area | Changelog | Summary | Spec deviation? |
|---|---|---|---|
| text_parser / network (B1, B9, B10, B11, B12, mojibake, fee parsing) | docs/V2_CHANGELOG_text_network.md | Reported-weakness-only detection; like-for-like related-party measure; merger/shell context not counted; legal note exposure; Item 9A evidence | No numeric change; SPAC-shell going-concern suppression is a judgement call |
| language / peer / quant / synthesis / temporal (B3-B8, B11 consumer) | docs/V2_CHANGELOG_agents.md | Focus-year escalation only; Medium rule needs a focus-year flag; manipulation-consistent peer directions only (a-priori table with citations); revenue<1% of assets => not meaningful; shell years never baselines | YES: passive-voice 15% cut-off replaced by >25% YoY increase; Medium rule wording (CONTRACTS s6) |
| pipeline (B2, B8, Jev) | docs/V2_CHANGELOG_pipeline.md | Shell/SPAC/stub detection (stub floor 25,000 chars set from dev evidence); prior-year re-run for Jev material_change | No |
| xbrl_parser (provenance bug) | docs/V2_CHANGELOG_xbrl.md | Facts ending after the filing date can't define a filing's period of report; corrected P&G FY2012/13 values and FY2020 provenance | No (data-correctness fix; v1 snapshot retains the bug, so v1-vs-v2 holdout differences partly reflect it) |
Known weak spots deliberately left for v3: new_legal from long litigation notes fires often (MMM/JNJ); ROA-above-peers is the weakest peer direction; non-SPAC reverse mergers undetected.

## v3 dev-motivated changes (merged; per-change rows with rationale/tests live in the changelogs)
Found by studying the 36 DEV filings (12 original + 24 holdout-1, both spent). NOT validated by dev results; the only unbiased estimate is H2 (docs/V3_PROTOCOL.md). No spec threshold, severity rule or grade rule changed.
| Area | Changelog | Summary | Dev-motivated detail |
|---|---|---|---|
| data layer: Beneish coverage + prior-year basis | docs/V3_CHANGELOG_data.md | Per-item statement-table fallback (anchor-checked), LongTermDebt=0 only with balance-sheet evidence (imputed, marked), prior-year values from current-filing comparatives; no new XBRL tags (none passed the >=10-filer, >=90% agreement bar). Beneish computable 16 -> 24 of 36 dev cases | Beneish flag newly fires on OFIX, USAT, OSIR (fraud) and no clean dev case; coverage was chosen first, outcomes not used to select fixes |
| text_parser (network guards) | docs/V3_CHANGELOG_text_network.md | ASU 2014-15 text, SOX 302/906 certification, investee restatements, 'recently remediated', Item-9A-first rule | Removed false positives documented in docs/HOLDOUT_AUDIT_B.md; 7 of 36 dev cases changed; no true-signal control lost (KHC, SMCI, BBBY, Luckin, TEUM kept) |
| language new_legal | docs/V3_CHANGELOG_lang_eval.md (L1) | Identifier-based new-proceeding test; strict fallback constants fixed a priori (Jaccard 0.30, containment 0.70) | The party-needs-initiation gate and the court rule were added after reading noisy dev flags (dev-motivated, not pre-registered) |
| instrumentation / evaluator / cache hygiene | docs/V3_CHANGELOG_lang_eval.md (L2-L4) | grade_inputs persisted; paired-score secondary metric; injected analyzers can never touch the real results cache | No behaviour change (proved on 5 stored states) |
