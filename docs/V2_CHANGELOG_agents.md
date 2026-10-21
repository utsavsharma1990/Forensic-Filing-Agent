# v2 changelog: agents (language, peer, quantitative, synthesis, temporal) + prompts

Owner: agents engineer. Scope: docs/EVAL_AUDIT.md bugs B3, B4, B5, B6, B7, B8/B2 (consumer side), B11 (consumer side) and the
smoking-gun selection rule. Protocol: docs/V2_PROTOCOL.md. All changes were written test-first (tests listed per row), use only
the 12 DEV cases (the holdout was never opened) and keep every spec threshold unchanged except where marked "spec deviation".
The orchestrator merges the rows below into docs/TUNING_LEDGER.md as "v2 dev-motivated".

Honesty note on motivation: every row below was *revealed* by a dev case (column "Dev cases"), but the fix is defined from the
filing semantics / literature (column "Rationale"), not from the dev outcome. Dev grades after the change are NOT an estimate of
performance (see the dev table at the end).

## Ledger rows

| id | files | what changed | rationale (semantics / literature) | dev cases that revealed it | tests |
|---|---|---|---|---|---|
| V2-B3 | agents/synthesis_agent.py | `_escalation` = temporal FOCUS-YEAR `signal_change == "Escalating"` only (the whole-series `signal_trajectory` is no longer consulted; trajectory stays in the narrative). Medium rule 4 changes from "escalation AND any flagged year" to "focus-year escalation AND >= 1 flag fired in the focus year" (`_focus_year_flagged`, core agents 1-4, informational outliers are not flags). Rationale strings say "focus-year escalation". | The grade is a statement about the focus year. A trajectory is a net change over the whole series (one flag in FY2019 makes a 2016-2020 series "Escalating" although FY2020 is Stable) so it mixes past and present. "Any flagged year" is satisfiable by a flag in a year long gone (or by a flag that fires every year), so it did not condition on current evidence. Spec text ("temporal escalation") is ambiguous; this resolves it to the narrower reading. | BRK-B (Stable focus year, Medium via trajectory), VG (High needed trajectory), PG (any-year = passive voice every year) | tests/test_synthesis_agent.py::test_v2_escalation_*, test_v2_trajectory_only_*, test_v2_medium_by_escalation_*, test_v2_compute_risk_grade_medium_escalation_rule, test_v2_focus_year_flagged_helper |
| V2-B4 | agents/peer_agent.py | Two-sided z-test and display unchanged. New a-priori table `ADVERSE_DIRECTION`; only a manipulation-consistent outlier is a risk flag (counts toward severity, `flags_by_year`, `outlier_metrics`, `flags_fired`, High if >= 3, Medium 2, Low 1). Opposite-direction outliers are listed in `informational_outliers`, carry `risk_flag=False, informational=True` in `metric_zscores` and `informational=True` in `evidence`. | receivables-minus-revenue growth ABOVE peers and DSO ABOVE peers (Beneish 1999 DSRI; Dechow-Sloan-Sweeney 1996; Dechow-Ge-Larson-Sloan 2011 abnormal receivables); OCF/revenue BELOW peers (Sloan 1996; Dechow-Dichev 2002; Beneish TATA); gross margin ABOVE and ROA ABOVE peers ("too good to be true": Dechow et al. 2011, Beneish GMI logic; weakest direction, so one such outlier is only Low); debt/equity ABOVE peers (debt-covenant / external-financing motive; Beneish LVGI; Dechow et al. 1996). Favourable outliers (receivables falling faster than sales, low DSO, high cash conversion, low leverage) are not manipulation indicators. Table fixed before the dev re-run, full text in the module docstring. | AAPL (receivables growth -35 pp: favourable), PG (DSO 21 vs 58 days: favourable), BRK-B / MMM peer outliers | tests/test_peer.py::test_v2_direction_table_*, test_v2_compare_marks_*, test_v2_opposite_direction_*, test_v2_adverse_direction_*, test_v2_three_informational_* |
| V2-B5 | agents/temporal_agent.py | `peer.*` flags are excluded from the new-flag test that decides "Escalating"; they still add to the score (spec) and are still listed in `new_flags_this_year`. | Peer flags are attached only to the focus year, so they are by construction absent in every earlier year and always "new". Letting them trigger "Escalating" makes any single peer outlier escalate the focus year. | PG, AAPL, MMM (focus year escalated by a peer flag) | tests/test_temporal_agent.py::test_v2_peer_only_*, test_v2_real_new_flag_plus_peer_flag_still_escalates |
| V2-B6 | agents/quantitative_agent.py, agents/peer_agent.py, agents/synthesis_agent.py | `revenue_materiality()`: revenue < 1% of same-year total assets => revenue-denominated ratios are `not_meaningful`. Quantitative: Beneish M-score (needs DSRI/GMI/SGI/SGAI; current OR prior year immaterial) and DSO flag/YoY (current immaterial: whole DSO; prior immaterial: YoY not evaluated). Peer: gross margin, DSO, receivables-vs-revenue growth, OCF/revenue (company and each peer; prior year too for the growth gap); a peer-pct beyond +/-1000% is `None` (n/m). Synthesis `_peer_clause` never narrates a percentage above 1000%. ROA, debt/equity, accruals (assets-based) unaffected. | A ratio with revenue in the denominator measures the denominator when revenue is a rounding error relative to the balance sheet (pre-commercial company, shell, grounded fleet): SGI of 11x, DSO +1,500%, OCF/revenue -7,000%. 1% of assets is unit/currency free; operating businesses sit at revenue/assets 0.2-1.5 (banks/insurers/REITs ~0.05), so 1% is conservative: the dev operating company-years range 0.20-1.54 while the immaterial ones are 0.000-0.006 (no company-year lies in 0.007-0.19). Company with assets missing: not judged (normal missing-data path). Floor chosen from asset-turnover semantics, not tuned. | VG FY2020 (M=7.12, DSO +1519%), VG FY2021 / NKLA FY2020 peer OCF/revenue (-42,634% / -55,574,136%) | tests/test_quantitative_agent.py::test_v2_*, tests/test_peer.py::test_v2_revenue_materiality_*, test_v2_tiny_*, test_v2_absurd_peer_pct_*, tests/test_synthesis_agent.py::test_v2_absurd_peer_percentage_never_narrated |
| V2-B7 (SPEC DEVIATION) | agents/language_agent.py | `language.passive_voice` fires when the MD&A passive share rises by more than 25% relative to the prior year (same form and threshold as hedging); the fixed "> 15% of sentences" cut-off is removed (`PASSIVE_PCT_THRESHOLD` -> `PASSIVE_YOY_THRESHOLD = 0.25`). The measured percentage is still reported (`passive_voice[y]["pct"]`, plus `yoy_change_pct`). The prior year is now measured as well. Evidence: "Passive-voice share of MD&A sentences rose X% to Y% in FY". | Audit data: the 15% cut-off fired on 25/25 healthy large-cap filings (shares 21.7-31.2%) and on every dev filing, so it carries no information (TUNING_LEDGER P2, EVAL_AUDIT B7) and its only effect was to add a second language flag to any filing with one other flag (WorldCom, Enron, Lordstown language Medium). A change in the share is the signal the spec's own rationale (impersonal phrasing around results) can support; it mirrors the hedging rule. The +25% relative threshold is copied from hedging, not fitted. | WCOM, ENRNQ, RIDE (language Medium from passive + one other flag); all clean companies (fires every year) | tests/test_language_agent.py::test_v2_passive_*, test_passive_pct_measured_and_reported_rule_based |
| V2-B8 | agents/language_agent.py, agents/temporal_agent.py | Consumes `state["filing_entity_flags"]` ({year: {is_shell, spac_predecessor, reason}}, tolerated when absent/malformed). A flagged year is never a YoY baseline and never raises flags itself. Language: hedging, passive, risk-factor growth, specificity drop and new-legal are not computed against a flagged prior year (the specificity LEVEL test < 5 still applies to the operating year); result key `excluded_entity_years`. Temporal: flagged years get `data_available=False, excluded_shell=True`, score 0, are dropped from trajectory / elevated-year count / first detection, and the following year has no prior (cannot be Escalating); result key `excluded_entity_years`. | A blank-check company's 10-K is a different entity from the operating company that merged into it. Comparing the two year-over-year manufactures auditor/CFO/legal "changes", escalation and first-detection years. Treating the shell year as "no baseline" is the same convention the series already applies to a first year. | Lordstown FY2019 (DiamondPeak), Nikola FY2019 (VectoIQ), VG FY2017-18 (Social Capital Hedosophia), Enron FY1996 (Enron Oregon shell) | tests/test_language_agent.py::test_v2_hedging_flag_needs_*, test_v2_shell_year_*, test_v2_risk_factor_growth_and_legal_*, test_v2_specificity_drop_*, test_v2_malformed_*; tests/test_temporal_agent.py::test_v2_shell_*, test_v2_spac_*, test_v2_missing_* |
| V2-B11 | agents/language_agent.py | `new_legal` compares the parser's `legal_note` text when Item 3 is empty or only points to a note (`_effective_legal`); inline Item 3 is preferred when it has substantive units; `legal[y]["source"]` in {item3, legal_note}; when the two years use different sources the comparison is `source_changed` (low confidence, not flagged). | Item 3 often reads "see Note 14"; the real litigation disclosure lives in the contingencies note. Comparing pointer-to-pointer says nothing. Mixed-format years are not comparable (same logic as B9). | Nikola FY2020 (258-char pointer), Apple (pointer in later years) | tests/test_language_agent.py::test_v2_legal_note_*, test_v2_inline_item3_*, test_v2_mixed_sources_*, test_v2_without_legal_note_* |
| V2-SG | agents/synthesis_agent.py | Smoking-gun selection ignores informational candidates (`informational=True` evidence, i.e. opposite-direction peer outliers, and `language.passive_voice`) whenever a genuine candidate exists; they are used only when nothing else is available. All other ranking rules unchanged. | A narrative headline built from a favourable peer outlier or from the weakest language signal misleads the reader. | AAPL (ROA/receivables), PG (DSO), MSFT/JNJ (passive voice only) | tests/test_synthesis_agent.py::test_v2_informational_* |

## CONTRACTS section 6 wording after v2 (replace in docs/CONTRACTS.md; not edited by this engineer)
* `escalation = temporal focus-year signal_change == "Escalating"` (the series `signal_trajectory` is narrative only).
* Medium: `agents_flagging >= 1` (and not High/Critical) OR (`escalation` AND >= 1 flag fired in the focus year by agents 1-4).
* CONTRACTS section 4: peer severity counts only manipulation-consistent outliers (direction table in agents/peer_agent.py);
  `language.passive_voice` = passive share up > 25% YoY (spec deviation, was > 15% of sentences); revenue-denominated ratios are
  `not_meaningful` when revenue < 1% of total assets.

## Interface additions (for pipeline / UI / evaluator owners)
* in: `state["filing_entity_flags"]` (language, temporal); `legal_note` from `extract_sections` (language).
* out: peer_result `informational_outliers`, `metric_zscores[m].{risk_flag, informational, adverse_direction, peer_pct_not_meaningful}`,
  `data_quality.not_meaningful`; quantitative `beneish_scores[y]["status"] == "not_meaningful"` (same for `dso_trend`);
  language `excluded_entity_years`, `passive_voice[y].{yoy_change, yoy_change_pct, prior_pct}`, `new_legal_proceedings[y].source`;
  temporal `excluded_entity_years`, timeline entries `excluded_shell` / `exclusion_reason`.
* UI labels still say "Passive voice >15% of sentences" (app_components/formatting.py, app.py chart threshold line 15%): owned by
  another engineer; they should read "Passive-voice share up >25% YoY".

## Dev re-run (12 DEV cases; NOT a performance estimate: these cases motivated the fixes)
Method: the audit states (`.cache/audit/states.pkl`: same filing texts, annual facts, peers, and the FROZEN v1 `network_result`) were
re-run through the v2 quantitative, language, peer, temporal and synthesis agents (cached LLM only; Jev unavailable; no live
pipeline run, so the network agent's own v2 changes and the pipeline's real `filing_entity_flags` are NOT included). "+shell"
= the same run with `filing_entity_flags` EMULATED by hand for the known predecessor years (Enron FY1996, Nikola FY2018-19,
Lordstown FY2019, Virgin Galactic FY2017-18); the real flags come from the pipeline owner. "before" = the same states run through
the pre-v2 agents (reproduces the original v1 grades exactly).

| case | before | after (v2 agents) | after +shell | what moved it |
|---|---|---|---|---|
| Enron FY2000 (fraud) | High, first detection 1997 | High, first detection 1997 | High, first detection 2000 | language Medium -> Low (passive voice gone); High still needs quantitative High (Beneish -0.66) + network Medium + focus-year escalation. Shell flag removes the FY1996 artefact |
| WorldCom FY2001 (fraud) | Medium | Medium | Medium | language still Medium, now from `hedging` + `new_legal` (the legal flag comes from the note comparison, see caveats), not passive voice. Still a miss |
| Luckin FY2019 (fraud) | Medium | Medium | - | network High (restatement) carries it; unchanged |
| Nikola FY2020 (fraud) | Medium | Medium | Medium, focus change Stable, no first detection | peer `ocf_to_revenue` outlier (-158,455%) gone (not meaningful); network High (auditor+CFO vs the SPAC shell, B10: network agent) still decides Medium |
| Lordstown FY2020 (fraud) | High | **Medium** | Medium, focus change Stable | High needed 2 agents + escalation: language Medium (passive+legal) is now Low, and with the shell excluded the "Escalating" disappears. WORSE for recall at the High cut-off, but the old High was the SPAC artefact |
| Virgin Galactic FY2021 (fraud) | High | **Medium** | Medium | `peer` High (3 tiny-revenue outliers) -> None (not meaningful); trajectory-only escalation no longer counts; language Medium -> Low. Still Medium only because the boilerplate `network.restatement` hard flag (B1: network agent) is not fixed here. WORSE for recall at the High cut-off; the old High was an artefact |
| AAPL FY2020 (clean) | Medium | **Low** | - | favourable receivables outlier informational; ROA-above-peers counts (1 flag, Low severity) |
| MSFT FY2020 (clean) | Low | Low | - | - |
| JNJ FY2020 (clean) | Low | Low | - | - |
| PG FY2020 (clean) | Medium | Medium | - | favourable DSO outlier is informational and the peer flag no longer escalates, but a genuine non-peer new flag (cached LLM specificity 7 -> 3) escalates the focus year and satisfies the Medium rule: legitimately Medium under the v2 rule |
| BRK-B FY2020 (clean) | Medium | **Low** | - | trajectory-only escalation no longer counts (focus year Stable) |
| MMM FY2020 (clean) | Medium | Medium | - | real CFO change escalates the focus year; `new_legal` (note comparison) and `peer.debt_to_equity` (adverse direction) add focus-year flags. Benign but legitimate Medium, as the audit said |

Counts at the High cut-off: fraud High 3/6 -> 1/6 (only Enron; Lordstown and Virgin Galactic were artefact Highs), clean High 0/6 -> 0/6.
Medium among the six clean companies: 4/6 -> 2/6 (PG, MMM; both legitimate under the rule text). This is not tuning evidence: the
dev recall fell because artefact detections were removed. Whether v2 generalises is for the holdout to say.

## Not fixed here, and why
* B1 boilerplate material-weakness regex, B9 pointer-vs-inline related-party, B10 auditor+CFO hard combo on SPAC mergers, B12
  excerpt section name: network agent / text_parser (other owners). The v2 dev table shows their effect: VG and Lordstown/Nikola
  Medium grades are still carried by `network` severity High.
* The pipeline must populate `filing_entity_flags` (and pass `prior_year_results`); without it the shell consumer paths are inert
  (tested with synthetic flags; verified on real dev states only with hand-emulated flags). `state["prior_year_results"]` is
  not consumed by any agent I own.
* New-legal precision with the note source (B11): comparing contingencies NOTES fires often for companies with long litigation notes
  (dev survey of year-pairs, item-3 comparison vs note comparison: MMM flagged 5/5 years, JNJ 2 of its 2 note-sourced years,
  AAPL 1 of 3, WorldCom 3). New paragraphs in a large litigation note are weak evidence of a *new* proceeding; the flag is one Low
  signal. Not tuned; a candidate for the v3 backlog (e.g. require a new named party or a new court/agency, not new wording).
* Peer ROA/gross margin ABOVE peers is retained as manipulation-consistent per the brief; the evidence for those two directions is
  the weakest in the table (documented), so AAPL/BRK-B keep a Low peer severity from ROA.
* Passive voice stays a (weak) language flag that counts in language severity in its new YoY form; its false-positive rate in the
  new form was not measured beyond the dev re-run (no clean dev company has it as a smoking gun or in a grade driver). Excluding
  it entirely stays available through the pre-registered `no_passive` variant.
* UI strings (app.py, app_components/formatting.py) still describe the 15% passive-voice rule.
* Test status: targeted suites pass (synthesis 94, peer 31, temporal 53, quantitative 35, language 78 incl. network-marked cached
  tests); one full-suite run: 890 passed, 1 failed (`tests/test_peer.py::test_determinism_and_no_http_second_time`, a live-HTTP
  call-count assertion on tools/peer_finder that the concurrent engineers' cache activity disturbed; it passes in isolation, 31/31).
