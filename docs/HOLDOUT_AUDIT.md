# Holdout audit (v1 vs v2): summary

Detail: [HOLDOUT_AUDIT_A.md](HOLDOUT_AUDIT_A.md) (mechanics: which change caused which grade change, statistics) and
[HOLDOUT_AUDIT_B.md](HOLDOUT_AUDIT_B.md) (substance: genuine signal vs artifact, with filing excerpts). Protocol:
[V2_PROTOCOL.md](V2_PROTOCOL.md); freeze + incident log: [V2_FREEZE.md](V2_FREEZE.md). Both audits were read-only.

## Results (valid, n = 24: 12 fraud + 12 matched clean, run once per version, live keys, code frozen first)
| | v1 | v2 |
|---|---|---|
| TP/FP/TN/FN | 4/0/12/8 | 1/0/12/11 |
| Recall (Wilson 95%) | 33% [14, 61] | 8% [1.5, 35] |
| FPR (Wilson 95%) | 0% [0, 24] | 0% [0, 24] |
| Clean cases at Medium | 7/12 | 5/12 |
| Paired (McNemar) | 3 cases positive only in v1, 0 only in v2, exact p = 0.25 | |
| Beneish alone | 1/12 | 1/12 |
| Fraud > matched control on suspicion score (descriptive) | 8 wins / 3 ties / 1 loss (AUC ~0.79) | 8 / 3 / 1 (AUC ~0.80) |

## What the audits establish
1. **v1's four High grades were not four detections.** Only TEUM is a genuine catch (AR +646% vs revenue +139%, DSO 55 -> 173,
   real Item 9A material weaknesses). SNCR = accounting-standard going-concern boilerplate + generic risk-factor growth; USAT =
   stale remediated weakness + a tax-release / incomplete-COGS Beneish artifact; OFIX = half genuine (DSO) half artifact.
2. **The 4 -> 1 drop is the removal of the passive-voice flag** (fired on 24/24 v1 filings): it was a constant extra flag that
   pushed language to Medium and let weak cases reach High. 4 of 7 downgrades; focus-year-only escalation (1, inferred); network
   boilerplate guard (1, clean case, intended); peer direction filter (1, clean case, intended).
3. **Genuine recall is about 1/12 for both versions.** v2 did not detect less fraud than v1; it stopped counting artifacts.
4. **The XBRL provenance fix changed no stored number** in any of the 24 cases.
5. **Coverage, not rules, is the largest gap**: Beneish was computable in the focus year for only 5/12 fraud cases (missing
   LongTermDebt/COGS tag mapping, pre-XBRL filings). Counterfactual M-scores (informal): TEUM +2.56, OSIR -1.25 would fire.
6. **A weak continuous signal exists below the grade cutoff** (fraud outscores its control in 8/12 pairs) but several of those
   wins come from artifact flags.

## What cannot be concluded
n = 12 fraud cases: the recall difference is not statistically distinguishable (p = 0.25, overlapping CIs); FPR 0/12 has a 24%
upper bound; dev and holdout results must not be pooled; controls are "no known problem", not proven clean; attribution of
USAT's drop to focus-year-only escalation is inferred (focus_signal_change is not stored in the results JSON).

## v3 backlog (proposals only; each must be validated on a NEW unseen set; no thresholds tuned on these 24 cases)
* Fix Beneish input coverage (LongTermDebt / COGS tag mapping) and add instrumentation (persist focus_signal_change,
  flags_by_year, trajectory in the results JSON).
* Network flags still match accounting-pronouncement, SOX-certification and investee text (going concern / restatement).
* Grade Rule 4 yields Medium on a single Low flag; a single High agent with weak corroboration stays Medium.
* A language signal that actually discriminates (passive voice is now inert); `new_legal` counts rewording as new.
* YoY values use the originally filed prior year, so divestitures distort DSO/accruals; AQI unbounded on small bases.
* Peer set quality (asset-light broker vs asset-heavy truckers).
