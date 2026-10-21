# v3 changelog - language / evaluator / pipeline-state (owner: lang+eval engineer)

Scope: V3_PROTOCOL.md items 4, 5, 6. Files: `agents/language_agent.py`, `agents/synthesis_agent.py`, `agents/state.py`,
`graph/pipeline.py`, `evaluation/evaluator.py`, tests `test_language_agent.py`, `test_synthesis_agent.py`, `test_pipeline.py`,
`test_evaluator.py`. Evidence comes from the 36 DEV filings only (12 original + 24 holdout-1); `holdout2` was never opened.
No spec threshold, grade rule, severity rule or flag threshold was changed.

| id | files | change and rationale | dev cases that revealed it | tests |
|----|-------|----------------------|----------------------------|-------|
| L1 | agents/language_agent.py (`compare_legal`, `_legal_ids`, `_new_identifiers`, `_legal_by_year`, constants `LEGAL_*`, `_INITIATION_RE`) | `language.new_legal` is now identifier based. A Legal Proceedings paragraph is NEW only if it introduces an identifier absent from last year's section: a case caption, a docket / case number, an agency + matter type in one sentence (SEC subpoena, DOJ investigation, ...; known if last year names that agency and that matter type anywhere), a court never mentioned before (when the paragraph initiates a suit), a bare matter type (class action, patent suit; only when it initiates one), or >= 2 unseen named parties with at most 1 known anchor (a paragraph naming >= 2 parties already in last year's section is a development of an old matter; party names count only when the paragraph initiates a matter, because capitalised table headings / accounting terms are not parties). Dates and amounts are stripped; ordinary-course boilerplate paragraphs ("in the ordinary course", "from time to time") can only be made new by a caption / docket / agency matter. A paragraph with NO extractable identifier falls back to a strict test: new only if content-word Jaccard against every prior paragraph < 0.30 AND < 70% of its content words occur in last year's section AND it describes the initiation of a matter (filed a complaint / named a defendant / received a subpoena). The 0.30 / 0.70 cuts were fixed a priori, conservatively, and are not tuned. A procedural update ("oral argument was held", "settlement approved") is a development, not a new proceeding. The flagged paragraph now reports `new_identifiers`. `_legal_by_year` was extracted from `_analyse` unchanged (status handling, shell years, source_changed). | RRTS FY2015 (ordinary-course text counted new, HOLDOUT_AUDIT_B), USAT FY2017 (procedural update), MTZ, MITK, MMM/JNJ (long contingencies notes: v2 ledger "weak spot"), ENRNQ FY2000 (reworded Vidal explosion text). The party-needs-initiation gate and the court rule were added after reading noisy dev flags (table headings, ASC text, pension plan names); they are dev-motivated, not pre-registered. | tests/test_language_agent.py `test_v3_*` (12: synthetic rewordings not new, SEC subpoena reworded vs first appearance, docket numbers, procedural update, unseen court, strict fallback + documented constants, dates/amounts, id extraction; real cached RRTS, USAT, MMM, ENRNQ, Nikola FY2020/21) + the 12 pre-existing `legal` tests still pass |
| L2a | agents/synthesis_agent.py, agents/state.py, graph/pipeline.py | `grade_inputs` {focus_year, agents_flagging, agents_high, escalation, focus_year_flagged, jev_mean_confidence, jev_available, agent_severity} is returned by `run_synthesis` and stored in the state: the exact arguments the unchanged `compute_risk_grade` received. Pure additions: no rule, no value computed differently (the two helper results are bound to locals instead of being inlined). `PIPELINE_VERSION` / `new_state` label "v2" -> "v3" (label only). | HOLDOUT_AUDIT "focus_signal_change is not stored in the results JSON" (USAT attribution had to be inferred) | tests/test_synthesis_agent.py `test_v3_grade_inputs_*` (3, incl. every grade branch reproduced from the persisted inputs), tests/test_pipeline.py `test_v3_*` (2), version asserts moved to "v3" |
| L2b | evaluation/evaluator.py (`_instrumentation`, `_grade_inputs`, `_prior_year_summary`) | Every per-case JSON row now also persists: `focus_signal_change`, `signal_trajectory`, `flags_by_year` (per agent), `focus_flags_by_agent`, `grade_inputs` (from the state; older states are re-derived with synthesis's own helpers and tagged `source: "recomputed"`), `grade_rationale`, `suspicion_score` (focus) and `suspicion_by_year`, `signal_change_by_year`, `filing_entity_flags`, `prior_year_summary`, `pipeline_version`, `match_partner`, `row_schema`. Instrumentation is wrapped so it can never alter or break a row. | same | tests/test_evaluator.py `test_v3_row_persists_*`, `*_does_not_change_grade_outcome*`, `*_recomputed_*`, `*_failure_cannot_break_a_row` |
| L3 | evaluation/evaluator.py (`paired_comparison`, `sign_test_p`, `paired_auc`, `bootstrap_auc_ci`, `beneish_availability`, report section) | Pre-registered SECONDARY metric. Per matched pair (`match_partner`): fraud vs control focus-year temporal suspicion; wins / ties / losses; exact two-sided sign test on non-tied pairs (2 * P(X <= min(w, l)), X ~ Bin(w + l, 1/2), capped at 1); paired AUC = (wins + 0.5 * ties) / pairs; percentile bootstrap 95% CI resampling pairs (10,000 resamples, seed 20261018). Also Beneish availability among OK fraud vs clean cases. Written to `runs[*].paired` / `runs[*].beneish_availability` and to the markdown report ("n/a" when a case set has no pairs, e.g. the 12 original dev cases). Reporting only: no grade, cutoff or case outcome depends on it. | HOLDOUT_AUDIT item 6 (descriptive 8/3/1 wins from the 24 holdout-1 cases) | tests/test_evaluator.py hand-computed: sign test (8,1) = 0.0390625, (2,1) = 1.0, (5,0) = 0.0625; 4 pairs (5,3)(4,4)(2,6)(7,1) -> 2/1/1, AUC 0.625, p = 1.0; 8/3/1 -> AUC 9.5/12; bootstrap (1 win + 1 loss) -> CI (0, 1); all-wins -> (1, 1); Beneish 2/4 vs 2/2; JSON + markdown; n/a path |
| L4 | evaluation/evaluator.py (`_run_case`, `_cache_path`, `_EPHEMERAL_CACHE`, `load_cases_from`, CLI) | Cache hygiene (v2 incident, docs/V2_FREEZE.md). An INJECTED `analyze` never reads or writes the on-disk results cache; it uses a process-local in-memory cache keyed by the analyzer object (resume tests still work; another analyzer never sees its rows). The disk cache key now also holds the case label and `ROW_SCHEMA` besides code hash and key availability (ANTHROPIC/Jev), so rows written before the instrumentation are never served. CLI: `--cases-module` (module path or .py file), `--cases-var`, `--results-dir`; `run_evaluation` signature unchanged. | v2 incident | tests/test_evaluator.py `test_v3_injected_analyze_never_touches_the_real_cache_dir`, `*_real_cached_rows_are_never_served_to_an_injected_analyzer`, `*_real_analyzer_path_still_uses_the_disk_cache`, `*_cache_key_covers_*`, `*_load_cases_from_*`, `*_cli_cases_module_*` |

## L1: new_legal before / after on the 36 dev cases (spec-mode focus filings, shell/SPAC years excluded as in the pipeline)
BEFORE = the v2 algorithm (`language_agent` as it was before this change), AFTER = this change, both applied to the same
cached text (`extract_sections` + `_effective_legal` + `_legal_by_year`; the LLM-free part of the language agent).
Focus-year flag: 7 -> 4 of 36 (fraud 5 -> 3 of 18; clean 2 -> 1 of 18). Flags over ALL analysed years: 48 -> 33.

| case | label | focus FY | focus BEFORE | focus AFTER | flags (all analysed years) before -> after |
|---|---|---|---|---|---|
| ENRNQ | F | 2000 | flag | - | 2 -> 0 |
| WCOM | F | 2001 | flag | - | 3 -> 2 |
| LK, NKLA, RIDE, SPCE | F | | - | - | 0 -> 0 |
| AAPL | C | 2020 | - | flag (Optis suit, genuinely new) | 1 -> 2 |
| MSFT, PG, BRK-B | C | 2020 | - | - | 0 -> 0 |
| JNJ | C | 2020 | - | - | 2 -> 2 |
| MMM | C | 2020 | flag | - | 5 -> 3 |
| OSIR | F | 2014 | - | - | 0 -> 0 |
| TNGO | F | 2014 | - | - | 2 -> 2 |
| CGI | F | 2016 | - | - | 1 -> 0 |
| SNCR | F | 2016 | - | - | 2 -> 3 |
| RRTS | F | 2015 | flag | flag (1 paragraph: five California / one Illinois purported wage class actions, vs 3 paragraphs before; prior year said "no material proceeding") | 1 -> 1 |
| GVA, LIME, PTRY | F | | - | - | 0 -> 0 |
| USAT | F | 2017 | flag | - (procedural update) | 3 -> 2 |
| QTM | F | 2017 | - | flag (Realtime Data patent suit filed 2016-07) | 3 -> 3 |
| OFIX | F | 2012 | flag | flag (Breg qui tam in W.D. Missouri) | 4 -> 3 |
| TEUM | F | 2018 | - | - | 3 -> 2 |
| NSTG, EPAM, ALOT, BAND, RAH | C | | - | - | 0 -> 0 |
| LPSN | C | 2014 | - | - | 3 -> 3 |
| LSTR | C | 2016 | - | - | 1 -> 1 |
| HUBG | C | 2015 | - | - | 2 -> 1 |
| MTZ | C | 2018 | flag | - | 4 -> 2 |
| MITK | C | 2017 | - | - | 4 -> 0 |
| ICUI | C | 2012 | - | - | 1 -> 0 |
| AGX | C | 2011 | - | - | 1 -> 1 |

Reading it honestly: reworded text (RRTS ordinary-course paragraphs, USAT procedural update, ENRNQ Vidal explosion, MMM/MTZ/MITK
long notes) no longer counts; two clean/fraud cases GAIN a focus-year flag that is a genuine new suit (AAPL, QTM), and the
FY2015 RRTS flag survives because that year really adds class actions the prior year did not mention (the audit's reading of
"3 of 3 paragraphs = reworded boilerplate" was right for the ordinary-course paragraphs, not for the class-action one).
This is a precision change, not a detector: 3 of 18 fraud and 1 of 18 clean cases carry a focus-year flag. The effect on grades
was not measured on all 36 cases (only 3 were re-run end to end, below). No spec threshold or grade rule moved.

Known limits: parties are capitalised-word heuristics (no NER), so a new suit in an already-known court against known parties
by an unnamed plaintiff can be missed; new third parties added to an old matter are called "development" when >= 2 old names
are repeated; the MMM legal note is truncated at 59,998 characters by the text parser (owner: text_parser), so its year-on-year
window moves; `_is_continuation` and the v2 similarity constants remain in the module but are unused.

## L2: proof that instrumentation changed no behaviour
1. Stored states (5 dev cases, pipeline run with API keys blanked so the run is deterministic: ENRNQ, MMM, RRTS, AAPL, OFIX):
   the pre-change `synthesis_agent.py` (copy) and the new one were both run on the same stored state. Grade, rationale, smoking
   guns, smoking-gun evidence, narrative, severities, timeline, degraded list and every other output key are identical
   (`ALL IDENTICAL`); the only difference is the new key `grade_inputs`.

   | case | grade old -> new | guns | grade_inputs (flagging / high / escalation / focus flagged) |
   |---|---|---|---|
   | ENRNQ | High -> High | 3 -> 3 | 2 / 1 / True / True |
   | MMM | Medium -> Medium | 3 -> 3 | 0 / 0 / True / True |
   | OFIX | Medium -> Medium | 3 -> 3 | 1 / 1 / True / True |
   | RRTS | Low -> Low | 3 -> 3 | 0 / 0 / False / True |
   | AAPL | Low -> Low | 3 -> 3 | 0 / 0 / False / True |
2. Evaluator rows: the pre-change `evaluator._row_from_state` and the new one on the same 5 states: no pre-existing key of the
   row changed (grade, outcome, agents, key signal, Beneish fields all equal); only keys were added.
3. End to end (new `graph.pipeline.analyze_company`, keys blanked) on ENRNQ, RRTS, AAPL against the stored states: ENRNQ
   High and RRTS Low are identical in every field except `fetch_info` (timings), `pipeline_version` and the new `grade_inputs`.
   AAPL differs in `language_result` (new_legal rule tweak made after the stored state was produced) and `peer_result`
   (peer agent edited concurrently by another engineer), neither of which is instrumentation; its grade stays Low, but its
   smoking-gun list and narrative differ through those two agents, so AAPL is NOT evidence of identity (items 1-2 are).
4. The persisted `grade_inputs` fed back into the pure `compute_risk_grade` reproduce the stored grade AND rationale in
   unit tests for every grade branch.

## What was deliberately not done
* No change to grade rules, severity rules, flag thresholds or any weight; the language severity still counts flags.
* No NER / entity resolution library for parties; no LLM judgement for "is this the same matter".
* The paired metric is not used for any pass/fail decision in code; the decision rule stays in V3_PROTOCOL.md.
* No re-run of the 36-case grades after L1 (would need live keys and the other engineers' in-flight changes).
* `holdout2` material was not opened, listed or run; the `--cases-module` CLI can load any case file but was only exercised
  on synthetic and holdout-1 case lists.
