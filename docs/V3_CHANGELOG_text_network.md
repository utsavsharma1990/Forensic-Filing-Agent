# V3 changelog: text parser + network agent (text SEMANTICS guards, v3 protocol item 3)

Scope: `tools/text_parser.py` (all logic), `tests/test_text_parser.py`, `tests/test_network_agent.py`. `agents/network_agent.py` needed
no change (it consumes `detect_restatement` / `detect_material_weakness` / `detect_going_concern`; its own `_GC_REJECT` / `_RESTATE_REJECT`
are now redundant belt-and-braces and were left alone). No threshold, severity or grade rule changed. Guards are defined by what the
sentence says (pronouncement description / certification / third-party subject / immaterial revision / remediated or earlier-dated /
Item 9A concluded effective), not by company. Method: every dev filing's analysed-year text was captured once (v2 snapshot pipeline,
shared cache) and run through v2 (snapshot) and v3 code: 191 cached text-years, 11 change, all listed below.

| id | files | rationale | dev cases that revealed it | tests |
|---|---|---|---|---|
| T1a | text_parser `detect_going_concern` + `_gc_nongenuine_reason` | A sentence that describes ASU 2014-15 / ASC 205-40 ("requires / will be required to evaluate whether there is substantial doubt", "amendments in this update provide guidance...") is not the registrant's doubt. An affirmative conclusion next to a pronouncement reference ("these conditions raise ...", "management concluded that ... raises substantial doubt", auditor explanatory paragraph) is kept. Dropped hits go to `negated_hits` with reason `pronouncement`. | SNCR FY2014/FY2016, EPAM FY2014/15, BAND FY2017, GVA FY2016 (+NSTG FY2014 text-level) | `test_v3_going_concern_*` (6 negative, 5 positive synthetic), `test_v3_real_dev_asu_going_concern_text_no_longer_flags` (4 real) |
| T1b | same | "No substantial doubt" conclusions phrased across the sentence ("concluded there were no conditions that gave rise to substantial doubt", "did not identify conditions ...") were missed because the match started mid-sentence, after the negation cue. Sentence-level no-doubt check (reason `no_doubt`), skipped when the sentence also affirms doubt or contains a contrast word. | GVA FY2016 | same tests |
| T2a | `detect_material_weakness` (`_MW_CERT`) | SOX 302/906 certification text ("I have disclosed ... to the registrant's auditors ... all significant deficiencies and material weaknesses in the design or operation of internal control") matched the "disclosed ... material weakness" assertion. Now negated, reason `boilerplate`, kind `certification`. | PTRY / RAH FY2002 (v1 findings in HOLDOUT_AUDIT_B; not in the v2 flag window, so synthetic only) | `test_v3_sox_302_certification_is_not_a_reported_weakness` |
| T2b | `detect_restatement` (`_restatement_not_registrants`) | The registrant's OWN previously issued financials only. Excluded (moved to `other_hits`, kinds `third_party`, `declined_or_not_a_restatement`, `immaterial_revision`): (i) a restatement by an investee / customer / supplier / affiliate / equity-method party, or by a named other entity when investee context surrounds it; (ii) "rather than restate", "chose not to restate", "not a restatement"; (iii) an immaterial prior-period correction described as a revision, unless non-reliance language or the registrant itself says "we restated". | RAH FY2003/FY2004 (investee Vail restated; company chose not to) | `test_v3_investee_or_third_party_restatement_is_not_the_registrants`, `test_v3_immaterial_correction_without_restatement_is_not_a_restatement`, `test_v3_certification_investee_immaterial_and_recently_remediated_do_not_flag`, real RAH |
| T2c | `_MW_REMEDIATED` | "recently remediated", "has since been remediated", "we recently remediated" were not recognised (adverb list was closed). Now any `-ly` adverb except partial*, plus recently/previously/since/subsequently/already. Remediated language is history (recorded in `remediated_hits`). | OSIR FY2014 | `test_v3_recently_remediated_weakness_is_history_not_a_current_flag` |
| T2d | `detect_material_weakness` (adverse / not-effective conclusions) | "the audit report ... no longer expresses an adverse opinion on the effectiveness of our ICFR" matched the adverse-opinion pattern (this, not the weakness phrase, was what actually flagged OSIR FY2014). Sentences with "no longer" / "not an adverse" / "without an adverse" are not conclusions. | OSIR FY2014 | `test_v3_auditor_report_that_no_longer_expresses_an_adverse_opinion_is_history`, real OSIR |
| T2e | `detect_material_weakness` (as-of date) | "Although ICFR were effective as of June 30, 2017, we identified a material weakness ... as of June 30, 2016 and 2015": the date attached to the WEAKNESS (after the phrase) now decides prior-period history, not the max of all dates in the sentence. | USAT FY2017 | `test_v3_weakness_dated_before_the_fiscal_year_is_history_...`, real USAT |
| T3 | `detect_material_weakness` (Item 9A first) | When Item 9A is located and management concluded ICFR was effective (no not-effective conclusion, no adverse opinion), a weakness mention outside Item 9A (risk factors, preface, body notes about third parties/acquirees) is recorded in `remediated_hits` (kind `outside_9a_effective_icfr`) and cannot flag, even if the sentence says "not remediated". If Item 9A cannot be located the v2 behaviour is unchanged. | OSIR FY2014, USAT FY2017 (risk-factor mentions) | `test_v3_item_9a_first_effective_icfr_outside_weakness_mentions_cannot_flag`, `test_v3_item_9a_effective_overrides_weakness_mention_in_risk_factors` |

## Dev before/after (network flags_fired in the analysed window; v2 = frozen snapshot code, v3 = this tree, same captured states)
Only the rows that changed are listed; the other 25 cases are identical (see report).

| case | truth | v2 fired | v3 fired | flag removed |
|---|---|---|---|---|
| BAND | clean | 1 | 0 | FY2017 going_concern (ASU text) |
| EPAM | clean | 4 | 2 | FY2014, FY2015 going_concern (ASU text) |
| GVA | fraud | 2 | 1 | FY2016 going_concern (ASU text + "no conditions" conclusion) |
| SNCR | fraud | 3 | 1 | FY2014, FY2016 going_concern (ASU text) |
| RAH | clean | 4 | 2 | FY2003, FY2004 restatement (investee) |
| OSIR | fraud | 4 | 3 | FY2014 restatement ("recently remediated", "no longer ... adverse opinion"); FY2013 Item 9A weakness kept |
| USAT | fraud | 7 | 6 | FY2017 restatement (weakness dated 2015/2016); FY2015 and FY2016 Item 9A weaknesses kept |

No flag was added anywhere. Genuine detections lost: none among the dev cases (the removed flags were audited as false positives in
HOLDOUT_AUDIT_B). Caveat: the removed flags on fraud cases (GVA, SNCR, OSIR, USAT) were not what detected the fraud, so v3 recall can
only fall if those flags had carried a grade; that is a pipeline effect to be read from the evaluation, not a text-parser one.

## Real-positive controls (unchanged, still detected)
Kraft Heinz FY2018 (restatement + material weakness, Item 9A), Super Micro FY2024 (material weakness), Bed Bath FY2022 (going concern),
Luckin FY2019 20-F (non-reliance + weakness), TEUM FY2014/FY2018 (Item 9A weaknesses, going concern FY2014-16), CGI FY2012 restatement,
LK/SPCE/OSIR FY2013 Item 9A.

## Known residual false-positive classes NOT changed (v4 backlog)
* A restatement described again in later years (MTZ FY2015-17, CGI FY2014 retell an earlier genuine restatement) still flags in the later
  year; separating "this year's restatement" from "history of an earlier one" needs fiscal-period reasoning, not a sentence guard.
* HUBG FY2011 "As Previously Reported | As Restated" quarterly table still flags (not in the focus window); not examined for cause.
