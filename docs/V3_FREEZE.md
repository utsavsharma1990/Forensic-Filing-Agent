# v3 code freeze
Frozen 2026-10-18T22:21:10.722556+00:00 (UTC) after the full test suite passed: **983 passed, 0 failed** (361 s, live keys present),
orchestrator-run, with the code hash identical before and after the run: `97187bc6a6d6b229` (first 16 hex of sha256 over agents/*.py, tools/*.py, graph/*.py,
prompts/templates.py, evaluation/fraud_cases.py). v2 snapshot hash 392412fa4118383f, v1 snapshot f9d61d46ef966477 (both unchanged).
H2 (evaluation/holdout2_cases.py) was selected blind and has not been opened by the orchestrator or any v3 engineer.
Run order (each version exactly once, `--no-cache`, live keys, as_of = analysed filing date): v3 -> v2 -> v1 on H2. Results:
evaluation/results/h2_v3/, h2_v2/, h2_v1/. After the freeze no code/threshold/rule change is allowed (docs/V3_PROTOCOL.md).
