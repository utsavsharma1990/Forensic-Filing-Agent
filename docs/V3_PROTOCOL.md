# v3 protocol (pre-registered 2026-10-18, BEFORE any v3 code change or H2 selection result is seen)

## Why
v2 (holdout-1: recall 1/12, v1 4/12 of which ~1 genuine) showed that removing artifacts did not add detection: the largest gap is
data coverage (Beneish computable for 5/12 fraud cases) and remaining false-positive text matches (docs/HOLDOUT_AUDIT.md).
v3 tries to fix those, and is tested on a THIRD, sealed set because everything seen so far is now development data.

## Frozen artifacts
* v1: ../forensic-filing-agent-v1-snapshot (hash f9d61d46...). v2: ../forensic-filing-agent-v2-snapshot (hash 392412fa4118383f).
  Neither is modified.

## Data split
* DEV (v3 engineers may study/run freely) = the 12 original cases (evaluation/fraud_cases.py) + the 24 holdout-1 cases
  (evaluation/holdout_cases.py, docs/holdout_research.md): 36 filings, now spent.
* H2 = new sealed holdout: `evaluation/holdout2_cases.py`, `docs/holdout2_research.md`. SEALED: nobody building v3 may open, grep
  or run it; the selection agent must not run the system on candidates. Target 15 fraud + 15 matched clean (minimum 12 + 12),
  same criteria as docs/V2_PROTOCOL.md, disjoint from all 36 DEV cases and from every company used as a test fixture
  (Kraft Heinz, Bed Bath & Beyond, Super Micro, AAPL/MSFT/JNJ/PG/MMM/BRK-B, WMT, HD, and anyone in tests/ or .cache/text).
  Candidate pool must be larger than last time (>= 80 considered) so selection is by documentation quality, not detectability;
  at most 25% of fraud cases from any one industry; at least 60% XBRL era; >= 80% financial-statement fraud.

## v3 scope (all dev-motivated => logged in docs/TUNING_LEDGER.md and docs/V3_CHANGELOG_*.md; no spec thresholds changed; NO
changes to the grade rules, severity rules or flag thresholds: those would be fitting to dev cases)
1. Beneish input coverage: broader XBRL tag mapping (LongTermDebt, COGS/CostOfRevenue variants, etc.), per-item fallback to the
   statement-table parser for years where XBRL lacks an item, documented imputation only where the metric's own definition allows.
2. Prior-year comparability: Beneish/DSO/accruals prior-year values taken from the comparative columns of the CURRENT filing
   (restated for divestitures/reclassifications; available at the filing date, so no look-ahead) instead of the originally filed
   prior year.
3. Network boilerplate: going-concern / restatement / material-weakness matching must exclude accounting-pronouncement text
   (e.g. ASU 2014-15 descriptions), SOX 302/906 certification text, investee/third-party restatements, and prior-period-correction
   passages that are not restatements of the registrant's issued financials.
4. Language `new_legal`: reworded boilerplate is not a new proceeding (compare case captions / named parties / docket identifiers
   rather than raw text overlap).
5. Instrumentation (no behaviour change): persist focus_signal_change, flags_by_year, trajectory, grade inputs and per-agent
   flags in the evaluation JSON so audits don't have to infer them.
6. Evaluator addition (reporting only): paired suspicion-score comparison (fraud vs its matched control) with exact sign-test
   p-value and bootstrap CI of the paired AUC, as a pre-registered SECONDARY metric (cutoff-free).

## Run protocol (once each, no iteration)
1. v3 freeze: full suite green, code hash in docs/V3_FREEZE.md.
2. Run v1, v2 and v3 on H2 exactly once each (spec mode, as_of = analysed filing date, live keys, results cache bypassed with
   --no-cache, NEVER use injected analyzers against the real results cache). 
3. Report: confusion matrices with Wilson CIs, paired comparisons (exact McNemar), the secondary paired-AUC metric, grade
   distributions, Beneish availability rate, then an independent read-only attribution audit of v3's TPs/FPs.
4. No code, rule or threshold change after step 2 begins; defects go to a v4 backlog.

## Pre-registered primary/secondary metrics and decision rule
Primary: recall and FPR at the High/Critical cutoff. Secondary: paired AUC; Beneish availability among fraud cases.
"v3 improves" is claimed ONLY if v3 recall on H2 exceeds v2's with the paired exact test p < 0.10 AND FPR does not exceed v2's by
more than one case; otherwise the README says v3 did not demonstrably improve, whatever the point estimates.
