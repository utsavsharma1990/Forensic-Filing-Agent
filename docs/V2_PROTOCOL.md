# v2 protocol (pre-registered 2026-10-16, BEFORE any v2 code change or holdout run)

## Why
v1 backtest (n=12) + audit (docs/EVAL_AUDIT.md) found 12 bugs. Fixing them and re-scoring the same 12 cases would be tuning
on the test set. v2 therefore separates DEV data (used to find/fix bugs) from a HOLDOUT (never examined, run once).

## Frozen artifacts
* v1 code: `../forensic-filing-agent-v1-snapshot/` (code hash `f9d61d46ef966477...`). Never modified.
* v1 dev results: `evaluation/results/evaluation_results.json` (live keys) and `degraded_run_no_keys/`.

## Data split
* DEV = the 12 original cases (docs/case_research.md). v2 engineers may study and run these freely. Any v2 change motivated by
  them is logged in docs/TUNING_LEDGER.md ("v2 dev-motivated") before merge. Dev results of v2 are reported but are NOT an
  estimate of performance (they were used to build it).
* HOLDOUT = new cases chosen by a selection agent under the criteria below; stored in `evaluation/holdout_cases.py`, research in
  `docs/holdout_research.md`. SEALED: nobody building v2 may open, grep or run either file/any holdout ticker until v2 is
  frozen. The selection agent MUST NOT run the forensic system on them.
* Excluded from holdout (already examined in any way): the 12 dev cases; Kraft Heinz, Bed Bath & Beyond, Super Micro, Nikola
  and any company whose filings were used as unit-test fixtures (see tests/ and .cache/text); AAPL/MSFT/JNJ/PG/MMM/BRK-B.

## Holdout selection criteria (fixed in advance)
* FRAUD (target 12, minimum 10): US-listed companies with an SEC accounting/financial-statement fraud or a restatement-driven
  enforcement (AAER or equivalent) where the first PUBLIC revelation date is documented; the analysed filing is the LAST annual
  report (10-K/10-K405/20-F) filed BEFORE that revelation (strictly point-in-time, `pre_revelation_valid = True`); the filing
  must contain the full financial statements (XBRL or parsable tables); fiscal years 2005-2022 preferred (XBRL era 2009+ for
  >=60% of cases); operating companies with revenue (no SPAC shells/pre-revenue); mix of industries; NOT selected by looking at
  how the system would score them.
* CLEAN (target 12, minimum 10): one matched control per fraud case: same fiscal year, same 3-digit SIC where possible, total
  assets within 0.3x-3x, no restatement/AAER/material weakness/going-concern/auditor-resignation in the analysed year or the
  following 3 years (verify via filings + search), filed 10-K for the year.
* Record for each: cik, form, accession, filing date, revelation date + source URLs, fraud nature, SIC, assets, has_xbrl, match
  partner. Honest caveats (labels from enforcement releases / news; clean = no known problem, not proven clean).

## v2 scope (the 12 audit bugs + Jev wiring) — see docs/EVAL_AUDIT.md B1-B12
Changes must be principled (documented rationale from the literature or from filing semantics), not threshold fits. Spec
thresholds stay. Passive-voice rule is changed to a YoY-increase form (like hedging) because the fixed 15% cut-off has no
information (fires on all healthy filings); the change and rationale are logged.

## Run protocol (once each, no iteration)
1. v2 code freeze: full test suite green; record code hash in docs/V2_FREEZE.md.
2. Run v1 snapshot and v2 on the HOLDOUT, spec mode (as_of = analysed filing date), variants spec only (no passive variant),
   live keys, fresh caches for results (shared EDGAR cache is fine). ONE run per version.
3. Report: confusion matrix, precision/recall/F1/FPR with Wilson CIs for v1 and v2; paired comparison (cases where they
   differ); grade distributions (Medium counts); per-agent flag rates; per-case attribution audit of v2's true/false positives.
4. No code, threshold or rule change after step 2 begins. Defects found in holdout results go to a v3 backlog only.
5. README reports holdout numbers as the performance estimate and dev numbers as dev.

## Pre-registered primary metrics
Recall and false-positive rate at the High/Critical cutoff, plus the share of grades at Medium among clean cases. No target
values are set; whatever results come out are reported.
