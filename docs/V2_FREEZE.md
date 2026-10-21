# v2 code freeze
Frozen 2026-10-16T22:40:15.291481Z (UTC) after the full test suite passed: **891 passed, 0 failed** (404 s, live keys present).
v2 code hash (agents/*.py, tools/*.py, graph/*.py, prompts/templates.py, evaluation/fraud_cases.py): `392412fa4118383f6eaeceb5422066b2f796908635685f4889da5ff5934dd246`
v1 snapshot hash (../forensic-filing-agent-v1-snapshot): `f9d61d46ef966477...` (unchanged).
From this point NO code, threshold or rule change is allowed before the holdout results are published (docs/V2_PROTOCOL.md).
Holdout run order: v2 dev re-evaluation -> v2 holdout (once) -> v1 holdout (once). Results: evaluation/results/holdout_v2/, holdout_v1/.

## Incident log (disclosed)
* 2026-10-17: the first v2 holdout run was INVALID. Before the freeze I had checked the evaluator's handling of the holdout schema
  using a fake analyzer (every case graded High, no real analysis); the evaluator cached those fake results under the v2 code hash,
  and the first v2 holdout run read all 24 of them from cache (12/12/0/0: every case High). No real analysis of any holdout case by
  v2 had happened. The invalid output is kept in evaluation/results/INVALID_holdout_v2_fake_cache_read/. v2 was then re-run with the
  cache bypassed (`--no-cache`). The v1 holdout run was unaffected (different code hash; 24/24 fresh analyses). Code was not
  changed between the two v2 attempts. Lesson: an evaluator cache must never accept results from an injected analyzer.
