# H2 audit A (read-only mechanics audit; H2 = 15 fraud + 15 matched clean; live keys; spec/spec; each version run once, no cache)

Source: evaluation/results/h2_v1, h2_v2, h2_v3 `evaluation_results.json` (runs['spec/spec'].cases). Scratch: .cache/h2_audit_a/ (load.py, shap.py, stats.py, m2.py/m3.py, flags.txt, tab1.md).
No code, snapshot or official result was modified. No pipeline was re-run. The only recomputation beyond stored JSON: `run_quantitative` alone (cached EDGAR data, API key blanked, no LLM)
for PLUG, SABA and SCOR to read the Beneish M-score that v3 JSON does not store (3 single-case data-layer calls; its key_finding reproduced the stored v3 key_finding for all 3).
Limitations: v1/v2 rows have no `grade_inputs`/`focus_signal_change`/`flags_by_year`; for them agents_flagging/agents_high are derived from stored severities (this derivation was checked against
the stored v3 `grade_inputs` and matched on all 30 v3 rows), and focus-year escalation is INFERRED (see section 2). v1/v2 `compute_risk_grade` bodies were read from the snapshots; the v2-snapshot function and the
current (v3) function return identical grades on all 180 recorded-input evaluations (grade rules unchanged v2 -> v3, as pre-registered).

## 0. Headline
| | v1 | v2 | v3 |
|---|---|---|---|
| TP/FP/TN/FN (High/Critical cutoff) | 6/1/14/9 | 2/1/14/13 | 2/1/14/13 |
| Recall (Wilson 95%) | 40.0% [19.8, 64.3] | 13.3% [3.7, 37.9] | 13.3% [3.7, 37.9] |
| FPR (Wilson 95%) | 6.7% [1.2, 29.8] | 6.7% [1.2, 29.8] | 6.7% [1.2, 29.8] |
| Fraud at Medium+ / clean at Medium+ | 13/15 / 12/15 | 13/15 / 8/15 | 13/15 / 9/15 |
| Fraud grades L/M/H | 2/7/6 | 2/11/2 | 2/11/2 |
| Clean grades L/M/H | 3/11/1 | 7/7/1 | 6/8/1 |
The same 2 fraud TPs (SAEX, RTIX) and the same single FP (ACLS) in v2 and v3. All 15 fraud grades are identical v2 = v3. The only grade difference v2 -> v3 anywhere is APKT (clean) Low -> Medium.
Grade differences: v1 -> v2 = 8 downgrades (HIL, PSIX, SCOR, HEV fraud; DWSN, BKE, INGN, APKT clean), 0 upgrades; v1 -> v3 = 7 downgrades (same minus APKT, which is Medium again in v3 via Beneish).

## 1. Paired case table (grade per version; per-agent severity; flags)
Severity key q/l/n/p = quantitative / language / network / peer; `-` none, L/M/H. "Flagging" counts core agents at Medium or High severity in the focus year (Low does not count). E/e = focus-year escalation yes/no (v3 stored).
Flags in the last column are the v3 focus-year flags; where a flag set differs between versions it is listed in section 1b.

FRAUD
| case | FY | grade v1 / v2 / v3 | outcome v1/v2/v3 | severity q/l/n/p: v1 ; v2 ; v3 | v3 flagging / high / esc(E) | v3 focus-year flags (agents with flags) |
|---|---|---|---|---|---|---|
| MNTX | 2016 | Med / Med / Med | FN/FN/FN | L/L/-/L ; L/-/-/- ; L/-/-/- | 0/0/E | q:altman_distress |
| SAEX | 2018 | Hig / Hig / Hig | TP/TP/TP | M/M/-/H ; M/L/-/M ; M/L/-/M | 2/0/E | q:altman_distress,dso_growth; l:hedging; p:receivables_vs_revenue_growth,ocf_to_revenue |
| RVLT | 2017 | Med / Med / Med | FN/FN/FN | L/L/-/L ; L/-/-/L ; L/-/-/L | 0/0/E | q:altman_distress; p:dso |
| HIL | 2016 | Hig / Med / Med | TP/FN/FN | -/M/H/M ; -/L/H/L ; -/-/H/L | 1/1/e | n:restatement; p:debt_to_equity |
| SMRT | 2011 | Med / Med / Med | FN/FN/FN | -/L/H/- ; -/-/H/- ; -/-/H/- | 1/1/E | n:ceo_change,restatement |
| PLUG | 2019 | Med / Med / Med | FN/FN/FN | L/H/-/- ; L/M/-/- ; L/M/-/- | 1/0/e | q:altman_distress; l:risk_factor_growth,new_legal |
| PSIX | 2015 | Hig / Med / Med | TP/FN/FN | H/L/H/- ; H/-/L/- ; H/-/L/- | 1/1/E | q:beneish,revenue_quality,accruals; n:cfo_change |
| RTIX | 2018 | Hig / Hig / Hig | TP/TP/TP | M/M/-/- ; M/M/-/- ; M/M/-/- | 2/0/E | q:altman_distress,dso_growth; l:hedging,new_legal |
| SCOR | 2014 | Hig / Med / Med | TP/FN/FN | L/M/H/- ; L/L/M/- ; L/-/M/- | 1/0/E | q:altman_distress; n:cfo_change,ceo_change |
| HEV | 2010 | Hig / Med / Med | TP/FN/FN | H/M/M/u ; H/L/M/u ; H/L/M/u | 2/1/e | q:beneish,dso_growth; l:risk_factor_growth; n:cfo_change,related_party |
| SABA | 2011 | Low / Low / Low | FN/FN/FN | L/L/-/u ; L/-/-/u ; L/-/-/u | 0/0/e | q:altman_distress |
| SWSH | 2010 | Med / Med / Med | FN/FN/FN | M/L/-/u ; M/-/-/u ; M/-/-/u | 1/0/e | q:altman_distress,dso_growth |
| VOL | 2008 | Med / Med / Med | FN/FN/FN | L/L/H/u ; L/-/H/u ; L/-/H/u | 1/1/E | q:accruals; n:restatement |
| ISLN | 2006 | Low / Low / Low | FN/FN/FN | -/L/-/u ; -/-/-/u ; -/-/-/u | 0/0/e | - |
| UNTK | 2011 | Med / Med / Med | FN/FN/FN | L/L/M/M ; L/-/M/L ; L/-/M/L | 1/0/e | q:altman_distress; n:ceo_change,related_party; p:ocf_to_revenue |

CLEAN
| case | FY | grade v1 / v2 / v3 | outcome v1/v2/v3 | severity q/l/n/p: v1 ; v2 ; v3 | v3 flagging / high / esc(E) | v3 focus-year flags (agents with flags) |
|---|---|---|---|---|---|---|
| ACLS | 2016 | Hig / Hig / Hig | FP/FP/FP | M/L/H/- ; M/-/H/- ; M/-/H/- | 2/1/E | q:dso_growth,accruals; n:going_concern |
| DWSN | 2018 | Med / Low / Low | TN/TN/TN | -/L/H/- ; -/-/-/- ; -/-/-/- | 0/0/e | - |
| LYTS | 2017 | Med / Med / Med | TN/TN/TN | -/-/H/- ; -/-/L/- ; -/-/L/- | 0/0/E | n:cfo_change |
| EXPO | 2016 | Med / Med / Med | TN/TN/TN | -/L/-/- ; -/L/-/- ; -/L/-/- | 0/0/E | l:passive_voice |
| BKE | 2011 | Med / Low / Low | TN/TN/TN | -/L/-/H ; -/-/-/L ; -/-/-/L | 0/0/e | p:roa |
| EAF | 2019 | Med / Med / Med | TN/TN/TN | -/H/-/L ; -/M/-/L ; -/M/-/L | 1/0/E | l:hedging,new_legal; p:roa |
| KAI | 2015 | Med / Med / Med | TN/TN/TN | -/L/L/- ; -/-/L/- ; -/-/L/- | 0/0/E | n:cfo_change |
| INGN | 2018 | Med / Low / Low | TN/TN/TN | -/L/H/- ; -/-/-/- ; -/-/-/- | 0/0/e | - |
| DHX | 2014 | Low / Low / Low | TN/TN/TN | -/L/-/- ; -/-/-/- ; -/-/-/L | 0/0/e | p:gross_margin |
| RSTI | 2010 | Low / Low / Low | TN/TN/TN | -/L/-/u ; -/-/-/u ; -/-/-/u | 0/0/e | - |
| LGTY | 2011 | Med / Med / Med | TN/TN/TN | L/M/-/u ; L/L/H/u ; L/L/H/u | 1/1/E | q:revenue_quality; l:specificity; n:restatement |
| SYNL | 2010 | Med / Med / Med | TN/TN/TN | -/L/M/u ; -/-/M/u ; -/-/M/u | 1/0/E | n:cfo_change,ceo_change |
| AMN | 2008 | Med / Med / Med | TN/TN/TN | -/M/-/u ; -/L/-/u ; -/L/-/u | 0/0/E | l:hedging |
| APKT | 2006 | Med / Low / Med | TN/TN/TN | -/L/H/u ; -/-/-/u ; H/-/-/u | 1/1/e | q:beneish |
| SHEN | 2011 | Low / Low / Low | TN/TN/TN | -/L/-/- ; -/-/-/- ; -/-/-/- | 0/0/e | - |

### 1b. Every difference between versions (stored data)
**Grades.** v1 -> v2: 8 downgrades, 0 upgrades, 22 unchanged. v2 -> v3: 1 change (APKT Low -> Medium), 29 unchanged. v1 -> v3: 7 downgrades (HIL, PSIX, SCOR, HEV, DWSN, BKE, INGN); APKT is Medium in v1 (network restatement hit) and again in v3 (Beneish), for different reasons.

| transition | case | GT | grade change | what changed (stored severities and flags) |
|---|---|---|---|---|
| v1->v2 | HIL | F | High -> Medium (TP lost) | language M -> L (passive_voice gone; new_legal stays); peer M -> L (ROA outlier dropped, D/E stays); network H unchanged |
| v1->v2 | PSIX | F | High -> Medium (TP lost) | network H -> L (restatement/material-weakness hit gone, cfo_change stays); language L -> none; quant H unchanged |
| v1->v2 | SCOR | F | High -> Medium (TP lost) | language M -> L (passive_voice gone); network H -> M (restatement hit gone, cfo/ceo change stay) |
| v1->v2 | HEV | F | High -> Medium (TP lost) | language M -> L (passive gone); quant/network unchanged; focus-year escalation No (v2) vs Yes (v1; series trajectory Escalating) |
| v1->v2 | DWSN | C | Medium -> Low | network H -> none (restatement from risk-factor "failure to maintain effective controls" text gone); language L -> none |
| v1->v2 | BKE | C | Medium -> Low | peer H -> L (receivables-minus-revenue growth -80pp, OCF/revenue +, ROA +: 2 of 3 outliers favourable direction, now informational); language L -> none |
| v1->v2 | INGN | C | Medium -> Low | network H -> none (forward-looking "may adversely affect ... material weakness" text); language L -> none |
| v1->v2 | APKT | C | Medium -> Low | network H -> none (restatement from "may reveal deficiencies" forward-looking text); language L -> none |
| v1->v2 (no grade effect) | 27 of 30 | | | language severity changed in 27/30 cases (passive_voice fired in the focus year in 29/30 v1 rows, 1/30 in v2 and v3: EXPO); LGTY network gained H (restatement hit on forward-looking "required to restate" text) |
| v2->v3 | APKT | C | Low -> Medium (new FP-direction at Medium, not at the cutoff) | quant none -> H: Beneish newly computable, M = -1.13 in FY2006 (SGAI imputed), flag fires |
| v2->v3 (no grade effect) | HIL | F | Medium -> Medium | language L -> none (new_legal gone); network going_concern (ASU text) removed, restatement stays; temporal score 65 -> 20, focus-year escalation now No; first_detection_year 2016 -> None |
| v2->v3 (no grade effect) | SCOR | F | Medium -> Medium | language L -> none (new_legal gone); score 55 -> 45 |
| v2->v3 (no grade effect) | DHX | C | Low -> Low | peer none -> L (gross margin +3.1 z, newly flagged); Beneish now available |
| v2->v3 (no grade effect) | PLUG, SABA | F | | Beneish newly available (PLUG M -3.22 FY2019 recomputed; SABA M -2.76 FY2011 recomputed); neither flags |
| v2->v3 (no grade effect) | EAF, INGN | C | | Beneish newly available, not flagged |
| v2->v3 (no grade effect) | RVLT, RTIX, DWSN | | | network flags_fired 3->1, 7->4, 5->2 (ASU going-concern removed); severities unchanged |
| v2->v3 | PSIX | F | Medium -> Medium | first_detection_year 2015 -> 2012 (v3 stored data find an FY2012 score-95 year with a passive_voice flag and an auditor change); quant flags_fired 9 -> 10 |
| v2->v3 | SAEX, HEV, SHEN, BKE | | | restated prior-year basis: SAEX M -0.93 -> -0.32 (FY2016), HEV M -1.20 -> -1.17, SHEN DSO flag now FY2007 instead of FY2008 (DSO +27.3%), BKE one more DSO flag; no severity change |
First-detection years (fraud, count with any detection year): v1 10/15, v2 10/15, v3 9/15. Clean with a detection year: v1 7/15, v2 3/15, v3 2/15.

## 2. Attribution of the v1 -> v2 downgrades (compute_risk_grade, recorded inputs, v1 vs v2/v3 semantics)
Method (.cache/h2_audit_a/shap.py, grade_eval.py): agents_flagging / agents_high recomputed from stored severities (Medium/High of the 4 core agents; validated against v3 `grade_inputs` on 30/30 rows). The v1 snapshot function
`compute_risk_grade(flagging, high, escalation, jev, jev_ok, any_flagged_year)` and the v2 snapshot / current function `(..., focus_year_flagged)` were imported and called on the recorded inputs. The semantic differences are exactly:
(i) escalation: v1 = series trajectory Escalating OR focus-year Escalating, v2/v3 = focus-year signal_change only; (ii) Medium-by-escalation: v1 needs a flag in any year, v2/v3 needs a flag in the focus year.
Escalation is not stored for v1/v2, so it is inferred as the set of values consistent with the recorded grade. Known: v1 escalation was True for HIL, PSIX, SCOR, HEV (they are High with flagging >= 2); v2 escalation was False for HEV (flagging 2 but Medium);
for HIL, PSIX, SCOR v2's own temporal text says "first crossed 40 with escalating signals in FY<focus year>", i.e. focus-year escalation True in v2. For each downgrade I toggled each changed factor (language, network, peer, quant, escalation semantics, any-year -> focus-year flag semantics) individually and in all subsets
(Shapley-style credit; "alone" = that single change reproduces the downgrade, "necessary" = reverting it alone restores the v1 grade).

| case | v1 flagging/high/esc -> v2 | v1 inputs under v2 rule (esc T / F) | v2 inputs under v1 rule (esc T / F) | responsible change(s) | confidence |
|---|---|---|---|---|---|
| HIL (F) | 3/1/T -> 1/1/T | High / Medium | Medium / Medium | JOINT: passive-voice removal (language M->L) AND peer direction filter (ROA outlier M->L): each alone leaves flagging 2 + escalation = still High; both needed. Shapley 0.5 / 0.5. If v2 focus escalation had been False, escalation alone would also suffice (v2 text says True) | high |
| PSIX (F) | 2/2/T -> 1/1/T | High / Medium | Medium / Medium | network text guard (restatement/"annual management assessments must include disclosure of identified material weaknesses" hit gone, network H -> L). Alone sufficient and necessary. Passive removal irrelevant (language L -> none, not counted) | high |
| SCOR (F) | 2/1/T -> 1/0/T | High / Medium | Medium / Medium | passive-voice removal (language M -> L, flagging 2 -> 1). Alone sufficient and necessary. Network H -> M (restatement hit gone) is irrelevant: network still counts as Medium | high |
| HEV (F) | 3/1/T -> 2/1/F | High / Medium | High / Medium | focus-year-only escalation (v1 High carried by series trajectory Escalating; v3 shows trajectory Escalating, focus-year Stable). Passive removal lowers flagging 3 -> 2 but 2 + escalation would still be High. Only the escalation-semantics change reproduces the downgrade | high (v2 escalation False is certain from the recorded Medium with flagging 2; that v1's True came from the trajectory is inferred) |
| DWSN (C) | 1/1/? -> 0/0 | Medium / Medium | Medium or Low (esc T / F) | network text guard (restatement hit from risk-factor "failure to maintain effective internal controls" text). Alone sufficient if v1 escalation was False; if it was True the any-year -> focus-year flag change is also needed (v1 escalation not identifiable) | high for network; split uncertain |
| INGN (C) | 1/1/? -> 0/0 | Medium / Medium | same pattern | network text guard (forward-looking "may adversely affect ... material weakness" text); same caveat | high / split uncertain |
| APKT (C) | 1/1/? -> 0/0 | Medium / Medium | same pattern | network text guard (restatement from "may reveal deficiencies" text); same caveat | high / split uncertain |
| BKE (C) | 1/1/? -> 0/0 | Medium / Medium | Medium or Low | peer direction filter (receivables growth and OCF/revenue outliers were favourable-direction; peer H -> L). If v1 escalation was True, focus-year-only escalation is also needed | high for peer; split uncertain |

Tally of the 8 downgrades (credit per case = 1; joint cases split):
| change | fraud downgrades (4, = lost TPs) | clean downgrades (4) | total credit (range if clean-case escalation ambiguity is resolved either way) |
|---|---|---|---|
| passive-voice removal (language severity) | SCOR 1.0, HIL 0.5 | 0 | 1.5 |
| peer direction filter | HIL 0.5 | BKE 0.5-1.0 | 1.0-1.5 |
| network text guards (restatement / material-weakness / going-concern) | PSIX 1.0 | DWSN, INGN, APKT 0.5-1.0 each | 2.5-4.0 |
| focus-year-only escalation | HEV 1.0 | 0-0.17 each (BKE up to 0.5; DWSN/INGN/APKT) | 1.0-2.0 |
| any-year -> focus-year flag semantics | 0 | 0-0.33 each for DWSN, INGN, APKT | 0-1.0 |
| shell / stub / SPAC-predecessor logic | 0 | 0 | 0 (no H2 filing is flagged shell/SPAC in the v3 `filing_entity_flags`, all years of all 30 filings; v2 not instrumented, but the detection code was not changed in v3) |
| quantitative changes (xbrl period-end fix, not-meaningful rule) | 0 | 0 | 0 (quantitative severity identical v1 = v2 in all 30 cases) |
Sole-cause counts (no ambiguity): passive voice 1 (SCOR), network guard 1 fraud (PSIX) + 3 clean (DWSN, INGN, APKT), focus-year escalation 1 (HEV), peer direction 1 (BKE); joint passive + peer 1 (HIL).
Reading: of the 4 lost fraud TPs, passive voice is responsible (alone or jointly) for 2, the network text guard for 1, focus-year escalation for 1. On holdout 1 passive voice explained 4 of 7; on H2 the language flag was less pivotal because SAEX, RTIX, HEV kept a second Medium+ agent.
Passive voice fired in the focus year in 29/30 v1 rows and 1/30 in v2 and v3 (EXPO); language at Medium+ went 9 -> 3 cases, network 13 -> 9, peer 4 -> 1, quantitative 6 -> 6.
Unchanged by attribution: ACLS (clean High in all versions) and the two TPs SAEX, RTIX (High in all versions; SAEX v1 flagging 3 -> 2 but still High with escalation).

## 3. Why v3 == v2 on all 15 fraud grades
v3 differs from v2 in: data layer (Beneish input coverage; comparative prior-year basis), network text guards, language `new_legal`, plus reporting-only instrumentation. The grade rules, severity rules and flag thresholds are unchanged (identical functions, checked). A grade can only move if (a) agents_flagging, (b) agents_high or (c) focus-year escalation moves.
Across the 15 fraud cases the v2 -> v3 input triple (flagging, high, escalation-consistent-set) is identical in 15/15 (flagging/high compared from stored severities; escalation: v3 stored value lies in the v2-consistent set in 15/15).
M values below: "stored" = in the official JSON; "recomputed" = `run_quantitative` only, cached data, v3 code (PLUG, SABA, SCOR).

| fraud case (FY) | v3 vs v2: Beneish availability / M | v3 vs v2: flags removed / added / other changes | v3 grade inputs (flagging/high/esc) and rule branch | why the grade did not move |
|---|---|---|---|---|
| MNTX (2016) | available both; M -1.61 in FY2014 (not focus year) | none | 0/0/E: Medium by focus-year escalation + a flag (Altman) | no change to any input |
| SAEX (2018) | available both; M -0.93 -> -0.32 in FY2016 (restated prior-year basis), flag not in focus year | none in severities | 2/0/E: High (quant M + peer M, escalation) | already High in v2; M change not in focus year |
| RVLT (2017) | available both; M -1.56 in FY2015 (SGAI imputed), not focus year | network flags_fired 3 -> 1 (FY2015 ASU going-concern removed; only non-focus years) | 0/0/E: Medium via escalation | network had no focus-year flag in v2 either; guard acted on a non-focus year |
| HIL (2016) | available both; M -2.93 (unlikely) | language new_legal removed (L -> none); network going_concern (ASU 2014-15 text) removed, restatement/MW from Item 9A kept so network stays H; first detection 2016 -> none; temporal 65 -> 20, escalation now No | 1/1/e: Medium (1 agent at H, no escalation) | network severity unchanged (H either way); the removed language flag was Low severity (Low does not count toward flagging); High needs 2 agents + escalation |
| SMRT (2011) | unavailable both (reason not examined beyond "see data_quality"); FY2011 pre/early-XBRL | none | 1/1/E: Medium (network H: CEO change + restatement) | no change; 1 agent flagging only |
| PLUG (2019) | NEW: unavailable -> available; M -3.22 in FY2019 (recomputed; PPE / LongTermDebt from statement-table fallback), not flagged | language flags_fired 5 -> 4 (non-focus) | 1/0/e: Medium (language M: risk_factor_growth + new_legal) | new M is far inside "unlikely" (threshold -1.78), no flag; and escalation is No (focus Stable), so even a Beneish flag (flagging 2) would not reach High |
| PSIX (2015) | available both; M -1.76 FY2015 flagged in both (0.02 above the -1.78 threshold) | quant flags_fired 9 -> 10 (non-focus); first detection 2015 -> 2012 | 1/1/E: Medium (quant H only; network L cfo_change; language none) | v1 High came from a network restatement hit removed in v2; nothing in v3 re-adds a second agent |
| RTIX (2018) | available both; focus-year Beneish not flagged | language ff 5 -> 3, network ff 7 -> 4 (non-focus years; ASU going-concern text) | 2/0/E: High (quant M + language M, escalation) | already High in v2; removed flags were in non-Medium agents/years |
| SCOR (2014) | unavailable both (recomputed: COGS and LongTermDebt not found in XBRL; statement-table fallback found neither row, so imputation / fallback did not apply) | language new_legal removed (L -> none); temporal 55 -> 45 | 1/0/E: Medium (network M: CFO and CEO change) | language was Low (not counted); flagging stays 1 |
| HEV (2010) | available both; M -1.20 -> -1.17 FY2010, flagged both | language ff 4 -> 3 (non-focus) | 2/1/e: Medium (quant H + network M; focus-year escalation No) | would be High with focus-year escalation; focus-year signal_change is Stable in v3 and v2 was already Medium with flagging 2, so No in both |
| SABA (2011) | NEW: available; M -2.76 in FY2011 (recomputed; LongTermDebt imputed 0 with balance-sheet evidence, SGAI imputed), not flagged | language ff 5 -> 4 (non-focus) | 0/0/e: Low (Altman Low only) | new M far from threshold; no flag |
| SWSH (2010) | unavailable both | none | 1/0/e: Medium (quant M: Altman + DSO) | no change |
| VOL (2008) | unavailable both | none | 1/1/E: Medium (network H restatement) | no change |
| ISLN (2006) | unavailable both ("largely unavailable") | none | 0/0/e: Low | no change |
| UNTK (2011) | unavailable both | none | 1/0/e: Medium (network M) | no change |

Reasons the coverage change could not move fraud grades:
1. Beneish coverage rose on fraud 7/15 -> 9/15 (PLUG, SABA), but both new M scores are unlikely-zone (-3.22, -2.76) and flag nothing. Of the 6 still unavailable (SMRT, SCOR, SWSH, VOL, ISLN, UNTK) only SCOR was checked: COGS and LongTermDebt missing (no cost-of-goods line), which the v3 changelog lists as an out-of-scope class (expense-by-nature statements, no imputation). The other 5 reasons were not examined.
2. The Beneish flag is one flag in one agent: even a new flag lifts a case only if a second agent is at Medium+ AND focus-year escalation is Yes. In v3, 12 of the 13 missed fraud filings have <= 1 agent at Medium+ (MNTX 0, RVLT 0, SABA 0, ISLN 0, HIL 1, SMRT 1, PLUG 1, PSIX 1, SCOR 1, SWSH 1, VOL 1, UNTK 1); the 13th (HEV) has 2 but escalation No.
3. Network text guards removed flags only from non-focus years (RVLT, RTIX, SAEX unchanged) or replaced one network High by another (HIL: ASU going-concern -> Item 9A restatement); they never changed a severity on a fraud case. They also did not remove the one clean-case FP: ACLS network High (going-concern) persists in v3 with a different excerpt ("...management must assess if there is substantial doubt", which reads like pronouncement text), and SAEX still shows ASU-style going-concern hits in FY2014-17 (not in the focus year).
4. `new_legal`: removed on HIL and SCOR (both Low severity, not counted); retained on PLUG, RTIX, EAF. No effect on grade inputs.
5. Comparative prior-year basis: changed some stored values (SAEX M, HEV M, SHEN/BKE DSO) but no severity.
Net: v3 changed every fraud case's non-focus detail and no focus-year severity that matters for the grade, and one clean case (APKT) gained a Beneish High (M -1.13, SGAI imputed) that lifted it Low -> Medium.

## 4. Statistics (.cache/h2_audit_a/stats.py)
Cutoff: High/Critical = positive. Wilson 95% CIs.
| | v1 | v2 | v3 |
|---|---|---|---|
| TP / FN (fraud n=15) | 6 / 9 | 2 / 13 | 2 / 13 |
| FP / TN (clean n=15) | 1 / 14 | 1 / 14 | 1 / 14 |
| Recall | 40.0% [19.8, 64.3] | 13.3% [3.7, 37.9] | 13.3% [3.7, 37.9] |
| FPR | 6.7% [1.2, 29.8] | 6.7% [1.2, 29.8] | 6.7% [1.2, 29.8] |
| Precision | 6/7 = 85.7% [48.7, 97.4] | 2/3 = 66.7% [20.8, 93.9] | 2/3 = 66.7% [20.8, 93.9] |
| Fraud at Medium+ / clean at Medium+ | 13 / 12 | 13 / 8 | 13 / 9 |
The single FP (ACLS: network going-concern H + quantitative DSO/accruals M, escalation) is the same in all versions. The two surviving TPs (SAEX, RTIX) are the only fraud cases with two Medium+ agents and escalation; neither involves a Beneish flag.

Paired exact McNemar (two-sided exact binomial on discordant pairs; case = unit; positive = High/Critical):
| comparison | fraud: only first / only second | clean: only first / only second | pooled 30: b / c | exact p |
|---|---|---|---|---|
| v1 vs v2 | 4 (HIL, PSIX, SCOR, HEV) / 0 | 0 / 0 | 4 / 0 | 0.125 |
| v1 vs v3 | 4 (same) / 0 | 0 / 0 | 4 / 0 | 0.125 |
| v2 vs v3 | 0 / 0 | 0 / 0 | 0 / 0 | 1.0 (no discordant pair; the test is undefined and is reported as 1.0) |
With 4 discordant cases all in one direction the smallest attainable two-sided exact p is 0.125, so a 4-case difference can never reach p < 0.10 at this n.

Pre-registered decision rule (docs/V3_PROTOCOL.md): "v3 improves" only if v3 recall > v2 recall with paired exact p < 0.10 AND FPR not above v2's by more than one case.
Observed: v3 recall 2/15 = v2 recall 2/15 (not greater), p = 1.0; FPR 1/15 = 1/15 (this condition is met). Outcome: **v3 did NOT demonstrably improve over v2** (recall clause fails; zero discordant cases). Relative to v1, v3 recall is lower by 4 cases (p = 0.125, not significant).

Secondary metric, paired score (fraud vs matched control, focus-year temporal suspicion), v3 only (the only run with stored scores):
| | as reported in v3 evaluation JSON | my recomputation |
|---|---|---|
| pairs / wins / ties / losses | 15 / 11 / 1 / 3 | 15 / 11 / 1 / 3 (pairs from evaluation/holdout2_cases.py match_partner, all 15 agree with the rows; scores from `suspicion_score`, identical to `suspicion_by_year[focus]`) |
| sign test (two-sided exact, 14 non-tied) | p = 0.0574 | p = 0.0574 |
| paired AUC | 0.767 | 0.767 (= (11 + 0.5)/15) |
| 95% bootstrap CI (pairs resampled) | [0.567, 0.933] (10,000 resamples, seed 20261018, percentile) | [0.533, 0.933] (exact distribution of the resampled AUC, no Monte-Carlo; the lower bound differs by one grid step of 1/30 from the reported percentile interpolation, immaterial) |
Pair detail (fraud score vs control score): MNTX 25 / ACLS 55 (loss), SAEX 65 / DWSN 0, RVLT 35 / LYTS 20, HIL 20 / EXPO 10, SMRT 10 / BKE 10 (tie), PLUG 45 / EAF 30, PSIX 70 / KAI 20, RTIX 55 / INGN 0, SCOR 45 / DHX 10, HEV 80 / RSTI 0, SABA 25 / LGTY 30 (loss), SWSH 35 / SYNL 20, VOL 20 / AMN 10, ISLN 0 / APKT 30 (loss), UNTK 45 / SHEN 0.
Caveats: scores move in steps of 5; 5 of the 11 wins are by 15 points or less (RVLT 15, HIL 10, PLUG 15, SWSH 15, VOL 10); two losses involve a control elevated by a flag (ACLS = the FP; APKT = the new Beneish flag in v3). The metric is descriptive (no decision threshold was pre-registered); p = 0.057 does not translate into usable detection at the cutoff, as the primary metric shows. Descriptive v1/v2 equivalents (read from the temporal key_finding text, not an official field): v1 11 wins / 0 ties / 3 losses (1 pair unparseable), v2 9 / 2 / 2 (2 unparseable); indicative only.

Beneish availability (focus-year M computable among OK cases): fraud v1 7/15 = 46.7%, v2 7/15, v3 9/15 = 60.0% [35.7, 80.2]; clean v1 2/15, v2 2/15, v3 6/15 = 40.0% [19.8, 64.3] (matches the evaluator's `beneish_availability` block, which lists SMRT, SCOR, SWSH, VOL, ISLN, UNTK as the unavailable fraud cases). Beneish flag (M > -1.78) in the focus year: fraud 2/15 (PSIX, HEV) in all three versions; clean 0/15 in v1 and v2, 1/15 in v3 (APKT, which gains a Medium grade from it).

## 5. Pre-registered v3 change list: expected vs observed on H2
The protocol pre-registered the change scope and the improvement rule, not numeric expectations; "expected" below is the effect the v3 changelogs stated.
| v3 item | expected (changelog) | observed on H2 |
|---|---|---|
| 1. Beneish input coverage (LongTermDebt row labels, no-debt evidence, per-item table fallback) | dev: M computable 16/36 -> 23/36 (clean 8/18 -> 14/18; fraud 8/18 -> 9-10/18); new M flags on OSIR, OFIX, USAT (fraud), none on clean | fraud 7/15 -> 9/15 (+PLUG, SABA), clean 2/15 -> 6/15 (+EAF, INGN, DHX, APKT). New fraud flags: 0 (M -3.22, -2.76). New clean flags: 1 (APKT, M -1.13 with SGAI imputed). 6 fraud cases still unavailable. Grade effect: 1 clean case Low -> Medium, 0 fraud |
| 2. Comparative prior-year basis | remove divestiture / reclassification distortion (dev: OFIX, USAT flags newly fire) | stored values moved (SAEX M -0.93 -> -0.32, HEV -1.20 -> -1.17, SHEN and BKE DSO years) with no severity change; no fraud grade effect |
| 3. Network boilerplate guards (ASU, SOX certification, investee, remediated, Item 9A first) | remove ASU / certification / third-party false flags; dev: no genuine detection lost | flags_fired fell in RVLT, HIL, RTIX, DWSN; no severity change on any fraud case; ACLS FP persists with a different ASU-like excerpt; no detection lost or gained |
| 4. `new_legal` identifier-based | precision change, not a detector (dev focus-year flag 7 -> 4 of 36) | removed on HIL, SCOR (Low severity, no grade effect); kept on PLUG, RTIX, EAF; no grade effect |
| 5. Instrumentation | no behaviour change | `grade_inputs` reproduces the recorded grade on 30/30 rows with the unchanged function; no behavioural difference detectable |
| 6. Paired suspicion metric | reporting only | 11 / 1 / 3, p = 0.057, AUC 0.77 [0.57, 0.93] (reproduced); cutoff-based result stays 2/15 |
| Overall decision rule | recall(v3) > recall(v2) with p < 0.10 | not met: 2/15 vs 2/15, p = 1.0 |

## What cannot be concluded at n = 15 fraud
* Recall CIs are wide: v3 13% [4, 38] vs v1 40% [20, 64] overlap; v1 vs v2/v3 is p = 0.125 (4 discordant cases, all one direction). The data are consistent with a real recall loss from v1 to v2 and with noise; neither can be established.
* "v3 == v2" means no detectable effect on grades at this n; it does not show v3's changes are useless. With 0 discordant cases the test has no power; effects of 1 or 2 detections are invisible. The changes may improve flag precision (several flags were removed in non-focus years) without moving any cutoff outcome, which this metric cannot see.
* FPR 1/15 has an upper bound near 30%. Controls are "no known problem", not proven clean; whether ACLS is a genuine signal or a guard miss is not adjudicated here (substance is for audit B).
* Attribution in section 2 rests on 8 downgrades; v1/v2 escalation is inferred, the split among sufficient factors for the 3 network-guard clean cases and BKE is ambiguous, and no counterfactual end-to-end rerun was done (stored-input function evaluation only).
* v1's 6 TPs are not shown to be genuine detections (HOLDOUT_AUDIT found about 1 of 4 genuine on holdout 1); recall compares grades, not correct reasons. Whether any of v1's 4 lost TPs was a genuine catch is not established here.
* Dev, holdout 1 and H2 must not be pooled; H2 was the only unseen set for v3 and is now spent.
* The secondary metric's p = 0.057 is a descriptive number, not a pre-registered test with a threshold.
* 6 of 15 fraud filings have no Beneish value (only SCOR's reason was checked), so H2 says little about Beneish's power on those.

## v4 ideas (diagnosis only; every one MUST be validated on a new unseen set; no threshold change is recommended)
* Persist the quantitative agent's M score, components, imputed items and unavailable reasons per focus year in the results JSON, so availability and near-misses (PSIX 0.02 above threshold, APKT imputed) can be audited without recomputation. Instrumentation only; must be validated on a new unseen set.
* Review the network going-concern guard against ACLS-type text ("management must assess if there is substantial doubt ... in connection with each annual and interim period") and SAEX FY2014-17 hits: require that the registrant itself concludes doubt. Must be validated on a new unseen set.
* Investigate data coverage for expense-by-nature statements (SCOR: no COGS line) and the 5 unexamined unavailable fraud cases before treating Beneish as the limiting factor. Must be validated on a new unseen set.
* Examine how one High agent with no second Medium+ agent (HIL network, PSIX quantitative, SMRT, VOL) is graded: a structural question about corroboration, not a threshold change. Must be validated on a new unseen set.
* Find a language signal that discriminates on class, since the removed passive-voice flag was a factor in 2 of 4 lost fraud TPs and is now inert (1/30). Must be validated on a new unseen set.
