# Holdout audit A (read-only diagnosis; n=24: 12 fraud, 12 matched clean; live keys; spec/spec)

Source: evaluation/results/holdout_v1 and holdout_v2 evaluation_results.json (INVALID_* ignored). Scratch: .cache/holdout_audit_a/{diag,stats}.py.
No code, snapshot or result file was modified; no pipeline re-run was done (stored JSON only). Limitation: the JSON does NOT store the temporal
`focus_signal_change`, `flags_by_year` or `signal_trajectory` field; only the (truncated) temporal key_finding gives "trajectory X". Where escalation
matters it is INFERRED from the recorded grade and agent severities via the grade rule (agents_flagging = number of core agents at Medium/High severity).

## 1. Grade changes (v1 -> v2): 7 downgrades, 0 upgrades, 17 unchanged
Severity order q/l/n/p = quantitative/language/network/peer. F = fraud, C = clean.
| case | GT | v1 grade | v2 grade | v1 sev q/l/n/p | v2 sev q/l/n/p | v1 flags | v2 flags | trajectory v1 -> v2 |
|---|---|---|---|---|---|---|---|---|
| SNCR | F | High (TP) | Medium (FN) | L/M/H/- | L/L/H/- | lang passive+risk_factor_growth; net going_concern; quant altman | lang risk_factor_growth only | ? -> Volatile |
| USAT | F | High (TP) | Medium (FN) | M/M/H/- | M/L/H/- | lang passive+new_legal; net cfo_change+restatement; quant altman+accruals | lang new_legal only | Escalating -> Escalating |
| OFIX | F | High (TP) | Medium (FN) | M/M/L/L | M/L/L/L | lang passive+new_legal | lang new_legal only (first detection 2011 -> 2012) | Escalating -> Stable |
| CGI | F | Medium | Low | -/M/-/L | -/L/-/L | lang passive+risk_factor_growth | risk_factor_growth only | Stable -> Improving |
| RRTS | F | Medium | Low | -/M/-/- | -/L/-/- | lang passive+new_legal | new_legal only | Escalating -> Escalating |
| NSTG | C | Medium | Low | L/L/H/- | L/-/-/- | net restatement (forward-looking "material weaknesses" risk-factor text) | net none | Improving -> Improving |
| AGX | C | Medium | Low | L/L/-/M | L/-/-/- | peer dso (z=-2.4, LOW DSO) + ocf_to_revenue (z=+16.9, HIGH) | both now informational, peer severity None | Stable -> Volatile |

Unchanged grade (some with internal change): OSIR, TNGO, GVA, QTM, LIME, TEUM, PTRY (fraud); LPSN, LSTR, EPAM, HUBG, MTZ, ALOT, MITK, ICUI, BAND, RAH (clean).
Notable internal changes without a grade effect: MITK network High (restatement + cfo_change) -> Low (cfo_change); with flagging 0 its v2 Medium can only come from focus-year escalation + a focus-year flag. RAH network Low -> High (new restatement hit on a prior-period-correction discussion, "full $.8 impact"), so v2 Medium is now via flagging 1 (a new clean-side spurious hit). MTZ language passive -> new_legal.
Passive voice fired in the focus year in 24/24 filings in v1 (fraud and clean alike) and 0/24 in v2. Core agents at Medium+ v1 -> v2: quantitative 4 -> 4, language 7 -> 1, network 6 -> 5, peer 4 -> 3. First-detection years lost in v2: GVA (2016), PTRY (2002), LPSN (2011), AGX (2011).

## 2. Attribution of each downgrade (compute_risk_grade, v1 vs v2 semantics, recorded inputs)
Signatures: v1 `compute_risk_grade(flagging, high, escalation, jev_mean, jev_ok, any_flagged_year)`, escalation = series trajectory Escalating OR focus-year Escalating; Medium = flagging>=1 or (escalation and any flagged year, flags_fired>0 in any year).
v2 same arity with `focus_year_flagged`; escalation = focus-year `signal_change` only; Medium = flagging>=1 or (escalation and a focus-year flag). High = flagging>=2 and escalation, or high>=3 (Jev unavailable caps at High).
Method (.cache/holdout_audit_a/diag.py): recompute the grade from (flagging, high) of each version under both escalation values and both rule semantics.
| case | v1 inputs (flag,high) | v2 inputs | v1 sev under v2 rule (esc T/F) | v2 sev under v1 rule (esc T/F) | responsible change | confidence |
|---|---|---|---|---|---|---|
| SNCR | 2,1 | 1,1 | High / Medium | Medium / Medium | B7 passive voice: language Medium -> Low drops flagging 2 -> 1, High impossible whatever the escalation | high |
| OFIX | 2,0 | 1,0 | High / Medium | Medium / Medium | B7 (same; trajectory also Stable in v2 but irrelevant since flagging<2) | high |
| CGI | 1,0 | 0,0 | Medium / Medium | Medium / Low | B7 (language Medium came from passive + risk_factor_growth; sole flagging agent) | high |
| RRTS | 1,0 | 0,0 | Medium / Medium | Medium / Low | B7 (passive + new_legal -> new_legal only) | high |
| USAT | 3,1 | 2,1 | High / Medium | High / Medium | B3 focus-year-only escalation. B7 alone leaves flagging at 2 (still >=2), and v2 severities with v1 escalation=True give High. v2 is Medium with flagging 2, so v2 focus-year signal_change is not Escalating while the series trajectory IS Escalating in both versions: v1 High was carried by the trajectory | medium: v1 focus-year signal_change not stored; B5/B7 changes to the "new flag" set could in principle also have flipped it |
| NSTG | 1,1 | 0,0 | Medium / Medium | Medium / Low | B1 text/network guard (reported vs forward-looking material weakness); not a compute_risk_grade change | high (v1 excerpt is "if we ... identify deficiencies ... material weaknesses") |
| AGX | 1,0 | 0,0 | Medium / Medium | Medium / Low | B4 peer direction filter (low DSO and high OCF/revenue are favourable; numbers identical) | high |

Tally of the 7 downgrades: B7 passive voice 4 (SNCR, OFIX, CGI, RRTS); B3 focus-year escalation 1 (USAT); B1 network guard 1 (NSTG); B4 peer direction 1 (AGX).
Lost TPs (3): B7 x2 (SNCR, OFIX), B3 x1 (USAT). Clean downgrades (2): B1, B4; no outcome change at the High cutoff.
Changes with no observable grade effect in stored data: B5, B6 (no number changed), B8 shell/stub baselines (filing_entity_flags not stored), B9, B10, B11 (MTZ only), V2-SG, xbrl-1, P2 prior-year/Jev.
Cannot be separated from stored data: whether B5 or B3 changed v2 focus-year escalation for USAT; which of GVA, ALOT, MITK, PTRY(v2) Mediums rest on escalation + focus-year flag (inferred yes, since flagging=0 yet Medium).

## 3. XBRL data fix / not_meaningful effect on stored numbers (24 cases)
Compared quantitative and peer key_finding strings, flags_fired, beneish_available / beneish_focus_flag between versions.
* Quantitative key_finding and flags_fired: identical in all 24 (e.g. QTM Beneish M -0.86, NSTG -1.65, GVA -2.36, OSIR DSO 112.0 -> 148.2 days +32.3%).
* Peer key_finding numbers identical in all 24 (OSIR DSO 148 vs 55 z=+2.5; LIME; LSTR; MTZ; AGX z values). Only AGX's text differs, and only its classification (informational), not the values.
* beneish_available / beneish_focus_flag identical in all 24 (Beneish available in 8 cases: TNGO, GVA, USAT, QTM, LIME, NSTG, EPAM, HUBG; only QTM flagged).
* Conclusion: the xbrl-1 period-end fix (PG-specific) and the B6 not_meaningful rule changed NO stored number on the holdout, so neither can be credited or blamed for any grade change. Caveat: only the headline number per agent is stored (not full M-score components or annual_facts), so a silent change in a non-headline value cannot be excluded.

## 4. Statistics
Recall at the High/Critical cutoff, Wilson 95%: v1 4/12 = 33.3% [13.8%, 60.9%]; v2 1/12 = 8.3% [1.5%, 35.4%].
FPR: v1 0/12 [0.0%, 24.2%]; v2 0/12 [0.0%, 24.2%].
Paired fraud (n=12): positive in both 1 (TEUM); v1 only 3 (SNCR, USAT, OFIX); v2 only 0; neither 8. McNemar b=3, c=0, exact two-sided binomial p = 0.25.
Paired clean (n=12): negative in both 12; b=c=0 (no test). Pooled 24: b=3, c=0, p=0.25.
Grade distribution, fraud v1 -> v2: High 4 -> 1, Medium 7 -> 8, Low 1 -> 3. Clean: Medium 7 -> 5, Low 5 -> 7 (pre-registered Medium share among clean 58% -> 42%).

## 5. Pre-registered expected effect vs observed
| change | pre-registered expectation (changelog) | observed on holdout |
|---|---|---|
| B3 focus-year escalation | remove trajectory-only escalation (BRK-B Medium, VG High on dev) | USAT High -> Medium (inferred). A genuine fraud with an Escalating series lost its TP; not an artefact removal here |
| B4 peer direction | drop favourable outliers (AAPL, PG on dev) | AGX Medium -> Low as intended (clean). No fraud case's peer severity changed |
| B5 peer flag not escalating | stop one peer flag escalating the focus year | not observable (escalation not stored) |
| B6 tiny-revenue not_meaningful | remove absurd ratios for pre-commercial companies | no effect; no stored number changed |
| B7 passive voice YoY>25% (spec deviation) | remove an uninformative flag (15% cut-off fired on all healthy filings); dev note: dev recall fell only where detections were artefacts | passive 24/24 -> 0/24. It was uninformative about class but acted as the second language flag lifting weak cases to language Medium and then High: 4 of 7 downgrades, 2 of 3 lost TPs. Largest effect |
| B8 shell/stub baselines | remove SPAC-predecessor artefacts | not observable |
| B11 legal note | catch pointer-only Item 3 | MTZ (clean) gains new_legal; no grade effect |
| B1/B12 network | stop forward-looking boilerplate flagging | NSTG and MITK (clean) network High -> None/Low as intended; but OSIR (fraud) still High from a "recently remediated a material weakness" risk-factor excerpt and RAH (clean) gains a High restatement hit |
| B9 related party | remove pointer/note artefacts | network flags_fired shifts (TEUM 12->11, OFIX 6->5, PTRY 2->1, LIME 2->3, MTZ 5->7); no grade effect |
| P2 prior-year / Jev | plumbing only | no grade effect visible |
| xbrl-1 | PG-specific labelling | no effect |
Pre-registered primary metrics: recall 33% -> 8%, FPR 0% -> 0%, clean-Medium share 58% -> 42%.

## What cannot be concluded with n=12 fraud cases
* v2 recall 1/12 vs v1 4/12 is not statistically distinguishable (exact McNemar p = 0.25; Wilson CIs [14,61]% vs [1.5,35]% overlap). The defensible statement is only that on this holdout v2 lost 3 of v1's 4 detections and gained none.
* FPR 0/12 for both has an upper 95% bound of 24%: no claim of low FPR. The clean-Medium difference (7 vs 5 of 12) is noise-level.
* Attribution is a count over 7 downgrades (4/1/1/1): B7 dominance is suggestive, not established; the B3 attribution for USAT is inferred.
* Controls are "no known problem", not proven clean; each case differs by several changes at once and the JSON lacks the temporal fields needed to separate them.
* Both versions miss OSIR, TNGO, CGI, RRTS, GVA, QTM, LIME, PTRY; v2 additionally misses SNCR, USAT, OFIX. QTM has quantitative High (Beneish -0.86) but only one agent flagging, so it stays Medium; OSIR has flagging 1 (network High).
* Dev results cannot be pooled: they motivated v2.

## v3 ideas (diagnosis only; each MUST be validated on a new unseen set; no thresholds changed)
* Review how a single High-severity agent (QTM Beneish High, OSIR network High) plus corroborating Low flags from other agents is graded: structural question, must be validated on a new unseen set.
* Passive voice is now inert (0/24); find a language signal that discriminates before relying on language for High. Must be validated on a new unseen set.
* Network: test whether a "remediated material weakness" risk-factor mention (OSIR) and prior-period immaterial-correction text (RAH) are classified correctly. Must be validated on a new unseen set.
* Instrumentation only: persist focus_signal_change, flags_by_year and trajectory in evaluation JSON so audits can attribute escalation directly.
