# H2 audit (v1 vs v2 vs v3): summary
Detail: [H2_AUDIT_A.md](H2_AUDIT_A.md) (mechanics, attribution, statistics) and [H2_AUDIT_B.md](H2_AUDIT_B.md) (genuine vs artifact, per case).
Protocol: [V3_PROTOCOL.md](V3_PROTOCOL.md); freeze: [V3_FREEZE.md](V3_FREEZE.md). Both audits were read-only.

## Results (valid: 15 fraud + 15 matched clean, sealed until after the freeze, one run per version, no cache, live keys)
| | v1 | v2 | v3 |
|---|---|---|---|
| TP/FP/TN/FN | 6/1/14/9 | 2/1/14/13 | 2/1/14/13 |
| Recall (Wilson 95%) | 40% [20, 64] | 13% [4, 38] | 13% [4, 38] |
| FPR (Wilson 95%) | 7% [1, 30] | 7% [1, 30] | 7% [1, 30] |
| Beneish computable, fraud | 7/15 | 7/15 | 9/15 |

Pre-registered rule "v3 improves": v3 recall > v2 with paired exact p < 0.10 and FPR not worse. **FAILED** (2/15 vs 2/15, p = 1.0). v3 did not demonstrably improve.
Secondary (cutoff-free, v3 rows only): fraud outscores its matched control in 11/15 pairs (1 tie, 3 losses), sign test p = 0.057,
paired AUC 0.77 [0.57, 0.93]. About 5 of the 11 wins are genuine; all 3 losses are artifact-driven.

## What the audits establish
1. **v1's 40% recall is mostly not genuine detection** (same pattern as holdout 1). Of its six fraud Highs only HEV is a clean hit;
   SAEX is real but reached through a current/long-term receivables artifact; PSIX, SCOR, HIL and RTIX leaned on boilerplate or mechanics.
   Passive voice fired on 29/30 v1 filings.
2. **v2/v3's two true positives are weak**: SAEX (real single-customer receivable, but the DSO and peer z come from the AR-split artifact)
   and RTIX (the DSO rise is explained by ASC 606 adoption).
3. **The single false positive (ACLS, High in all versions)** comes from `network.going_concern` matching ASU 2014-15 adoption
   wording verbatim; v3's pronouncement exclusion missed that exact phrasing.
4. **Structural bottleneck = the spec's grade rule**: 12 of 13 missed fraud cases have at most one agent at Medium+, and High
   needs two; a single strong on-mechanism signal (HEV, PSIX, SMRT, VOL) stays Medium. Beneish fired in the focus year on only 2/15 fraud cases.
5. **v3's data work moved coverage (7 -> 9 of 15) but no fraud grade**; its text guards touched non-focus years or swapped one
   network High for another. The only v2 -> v3 grade change is a clean case (APKT Low -> Medium).
6. A weak ranking signal exists below the cutoff (AUC ~0.77), consistent with holdout 1 (~0.8).

## What cannot be concluded
n = 15 fraud: 4 discordant cases can never reach p < 0.10 (smallest exact p = 0.125); v2 = v3 means no detectable effect, not
that the changes are useless; v1's TPs are not shown genuine; FPR upper bound ~30%; controls are "no known problem"; dev, holdout 1
and H2 must not be pooled; all three sets are now spent.

## v4 backlog (proposals only; each must be validated on a NEW unseen set)
Receivables DSO base = current + long-term; ASU 2014-15 verbatim wording in the going-concern guard; require persistence for
"escalation"; extend Beneish row-label mapping (expense-by-nature statements, "Long term obligations", fixed-width "Trade accounts
receivable", IPO-year prior balance sheet); persist Beneish components and unavailability reasons in the results JSON; handle
accounting-standard adoption years (ASC 606); reconsider how a single High agent without a second Medium+ agent is graded (the
spec's rule is the bottleneck); a language signal that discriminates.
Sonnet narrative: live runs reject the model's text in validation (paragraph count) and use the deterministic fallback; fix the prompt/parser (found when regenerating samples, not part of the audit).
