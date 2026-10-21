# Evaluation audit: do the flags behind the headline reflect real filing content?

Scope: headline run `spec/spec` (12 cases, TP 3 / FP 0 / TN 6 / FN 3). Read-only audit; no code under agents/, tools/, graph/,
prompts/, evaluation/, tests/ was changed. The pipeline was re-run with the evaluator's exact params (cik, end_year, as_of from
`evaluation/fraud_cases.py`) on cached data; all 12 grades reproduced the JSON exactly (Enron High, WorldCom Medium, Luckin Medium,
Nikola Medium, Lordstown High, VG High, AAPL Medium, MSFT Low, JNJ Low, PG Medium, BRK-B Medium, MMM Medium). Scratch scripts and the
pickled states are in `.cache/audit/` (`run.py`, `show.py`, `g.py`, `states.pkl`). All excerpts below are from the cached filing text
held in `state["filing_texts"]`. The report is also degraded (no LLM, no Jev), which is disclosed in the report banner.

## 1. Classification of the 12 cases

| Case | Grade | Outcome | Decisive evidence | Class | One-line reason |
|---|---|---|---|---|---|
| Enron FY2000 (10-K 0001024401-01-500010, filed 2001-04-02) | High | TP | Beneish M -0.66 (receivables +243.1% vs revenue +151.3%); related-party note growth; CEO change | GENUINE_SIGNAL | Numbers verified in the filing's own tables; Note 16 really discloses the related-party hedges. `first_detection_year` 1997 is a separate MECHANICAL_ARTIFACT (A1). |
| WorldCom FY2001 (10-K405 0001005477-02-001226) | Medium | FN | Language agent Medium = `passive_voice` + `hedging` (the only Medium+ agent) | MECHANICAL_ARTIFACT | Medium disappears in the pre-registered `no_passive` run (grade Low). Beneish is computed (-2.58 FY2000, -3.01 FY2001) and does not fire: a real miss, not a data gap. |
| Luckin FY2019 20-F (0001104659-21-087180, filed 2021-06-30) | Medium | FN | `network.restatement`: "the effect of the Non-Reliance identified in, and the resultant restatement of, certain of our previously issued financial results" | GENUINE_SIGNAL (post-revelation) | Real restatement, real material weaknesses, but the filing is the confession (2 months after the April 2020 revelation). Still only Medium: 1 agent flagging, 1 year of data, so no escalation. |
| Nikola FY2020 (10-K 0001731289-21-000006) | Medium | FN | Auditor RSM -> EY, CFO Shindler -> Brady, CEO Girsky -> Russell; `peer.ocf_to_revenue` -158,455.8% | MECHANICAL_ARTIFACT | The FY2019 "predecessor" 10-K is VectoIQ Acquisition Corp (SPAC shell, RSM). Peer outlier uses $95K revenue. Real content (SEC/DOJ subpoenas) is not flagged: DATA_GAP in `language.new_legal`. |
| Lordstown FY2020 (10-K 0001558370-21-003449) | High | TP | Withum -> KPMG + CFO Mihalitsis -> Rodriguez ("hard combo"), CEO Hamamoto -> Burns; FY2019 going-concern; escalation FY2019 -> FY2020 | MECHANICAL_ARTIFACT | All three events are SPAC-merger mechanics (details in 2.2). Only genuine item is `new_legal` (class action filed 2021-03-18), which is post-revelation. |
| Virgin Galactic FY2021 (10-K 0001706946-22-000035) | High | TP | `network.restatement` (hard flag) on forward-looking-statements boilerplate; 3 peer outliers; escalation via series trajectory | BOILERPLATE_FALSE_POSITIVE (+ MECHANICAL_ARTIFACT) | The filing reports ICFR and disclosure controls EFFECTIVE; no restatement. Peer outliers come from $3.3M revenue. See 2.1, 2.3 and bug B1. |
| AAPL FY2020 | Medium | TN | Peer severity Medium from 2 favourable-direction outliers (receivables-minus-revenue growth -35.2 pp; ROA 17.7% vs 7.4%) | MECHANICAL_ARTIFACT | Direction-blind two-sided z-test; counterfactual without them: Low. Peer set is IBM/Cisco/Deere/Caterpillar/Dell/HP/JCI. |
| MSFT FY2020 | Low | TN | none (passive-voice only, Low severity) | n/a (no decisive flag) | Correct, uninformative. |
| JNJ FY2020 | Low | TN | none (passive-voice only) | n/a (no decisive flag) | Same. |
| PG FY2020 | Medium | TN | No agent Medium+. Rule 4 (escalation + any flagged year): new `peer.dso` outlier (DSO 21 vs 58 days, favourable) makes FY2020 "Escalating"; "any flagged year" satisfied by passive voice in every year | MECHANICAL_ARTIFACT | Three stacked artifacts (2.6). Counterfactual without the favourable peer flag: Low. |
| BRK-B FY2020 | Medium | TN | Rule 4: series trajectory "Escalating" (FY2019 accruals flag, net +10) although the focus-year change is Stable; "flagged year" = `peer.roa` 4.9% vs 1.1% (favourable) | MECHANICAL_ARTIFACT | Counterfactual using the focus-year change only: Low. Insurers are also out of scope for Beneish/Altman. |
| MMM FY2020 | Medium | TN | Rule 4: focus year Escalating from real CFO change (Gangestad -> Patolawala, 3M 10-K FY2019 vs FY2020 signatures) plus `peer.debt_to_equity` 1.46x vs 0.68x | GENUINE_SIGNAL (benign) | Both facts are real; neither is evidence of fraud. It is a legitimate Medium that carries no information. |

## 2. Evidence by question

### 2.1 Did Virgin Galactic / Luckin actually report a material weakness or restatement?

Virgin Galactic FY2021 (accession 0001706946-22-000035, filed 2022-02-28). The decisive `network.restatement` hit is at 2% of the
document, in the forward-looking-statements preamble:

> "...extensive and evolving government regulation that impact the way we operate; risks associated with international expansion;
> our ability to timely and effectively remediate material weaknesses and maintain effective internal control over financial
> reporting and disclosure and procedures; and our ability to continue to use, maintain, enforce, protect and defend our owned and
> licensed intellectual property..."

The only other occurrence of "material weakness" in the filing is the auditor's boilerplate ("assessing the risk that a material
weakness exists", ~71% of the document). The filing's own conclusions (Item 9A, ~66%):

> "...our disclosure controls and procedures were effective at the reasonable assurance level."
> "...management concluded that our internal control over financial reporting was effective as of December 31, 2021."

The nine "restate" hits are all "Amended and Restated" trademark/registration-rights agreements. So the FY2021 flag is a
BOILERPLATE_FALSE_POSITIVE: the company reported neither a weakness nor a restatement. The detector is a bare regex
(`tools/text_parser.py:1373-1376`, `detect_material_weakness` at `:1615`, used at `agents/network_agent.py:436-446`). The ledger-1
guards were added only for the restatement regex, not for material weakness.

The earlier VG years show the same regex on real and historical content. FY2019 (0001628280-20-002471) is a genuine report: "we
identified two material weaknesses in our internal control over financial reporting". FY2020 (0001706946-21-000022) fires on a
remediated history: "During 2020, we completed the remediation measures ... and concluded that our internal control over financial
reporting was effective as of December 31, 2020." Only FY2019 is a real, current-period reported weakness. It was also the
SPAC-to-operating-company transition year.

Luckin FY2019 20-F (0001104659-21-087180): genuine. The filing states that the Board concluded "the Non-Reliance"; the Q2 and Q3
2019 results "have been restated"; and "we and our independent registered public accounting firm identified certain material
weaknesses ... as of December 31, 2019". The excerpt the report shows is from the forward-looking preamble, but the body contains
the real disclosure. Caveat: this is the post-hoc admission, not a pre-revelation signal (A3).

"Kraft-style positives": there is no Kraft case among the 12, so this part of the request cannot be answered. Of all restatement or
material-weakness hits in the 12 runs (Luckin 2019; VG 2019, 2020, 2021), 2 of 4 are real current-period disclosures, 1 is
remediated history and 1 is pure boilerplate.

### 2.2 Lordstown and Nikola: auditor and CFO changes are SPAC mechanics

Lordstown FY2020 10-K (filed 2021-03-25), Item 14, ~95% of the document:

> "...WithumSmith+Brown, PC ('Withum'), our independent registered public accounting firm prior to the Business Combination, was
> informed on October 23, 2020 that it would be replaced by KPMG ... which consisted only of the accounts of the pre-merger special
> purpose acquisition company."

The FY2019 10-K (0001213900-20-007365) is DiamondPeak Holdings, a blank-check company (CEO David Hamamoto). On the executive
officers list, ~74%: "Julio Rodriguez. Mr. Rodriguez has served as our Chief Financial Officer since October 2020. Mr. Rodriguez
served as Legacy Lordstown's Chief Financial Officer from September 2019 until October 2020." So the "CFO change" is the SPAC's
CFO being replaced by the operating company's existing CFO, and the "CEO change" (Hamamoto -> Burns) is the same. The FY2019
`network.going_concern` hit is a SPAC mandatory-liquidation clause: "if we fail to complete our business combination, we will
never generate any operating revenues... substantial doubt". The temporal "Escalating" for FY2020 therefore compares a shell year
with an operating year. Lordstown's High grade rests on: network High (auditor+CFO "hard combo"), language Medium (`passive_voice`
+ `new_legal`), and the escalation. The only real content is the `new_legal` paragraph (class action of 2021-03-18), disclosed
after the March 2021 revelation. In `no_passive` Lordstown is Medium (a FN).

Nikola FY2020 (0001731289-21-000006): the FY2019 10-K (0001104659-20-030103) is VectoIQ Acquisition Corp.: "/s/ RSM US LLP ... New
York, March 6, 2020", CEO Stephen Girsky, CFO Steve Shindler. The FY2020 report is signed by Ernst & Young LLP ("We have served the
Company's auditor since 2018"), CEO Mark A. Russell, CFO Kim J. Brady. Everything flagged is the shell being replaced by the
operating company. Nikola happens to be graded Medium, so this artifact was not rewarded. FY2019 `going_concern` ("mandatory
liquidation and subsequent dissolution raises substantial doubt") and the temporal first detection "FY2019 (filed 2020-03-06)" are
pure shell artifacts. Real content the system misses: the FY2020 10-K discloses SEC and DOJ subpoenas and Milton's resignation, but
`language.new_legal` is "unavailable" because the FY2019 shell 10-K has no Legal Proceedings section, and the FY2020 section is a
258-character pointer to the notes.

Virgin Galactic's FY2017-FY2018 "history" is the same (Social Capital Hedosophia SPAC). Its `first_detection_year` FY2018 comes
from a CFO change inside the shell, and the FY2019 auditor change (Marcum -> KPMG) and CEO/CFO changes are SPAC-merger mechanics.

### 2.3 Virgin Galactic peer outliers

Inputs (XBRL, FY2021): revenue $3,292,000; gross profit $3,020,000; OCF -$230,763,000. OCF/revenue = -70.098, so the percentage
-7009.8% is arithmetically correct. The peer mean is 16.48% with a peer standard deviation of 11.5%, hence z = -608. The sentence
"OCF/revenue was -7009.8%, which is 42634.6% below the peer group average" is built from `peer_pct` = (company - mean) / |mean|
= -42634.6%, a relative difference of two ratios whose mean is about 0.16. It is mathematically faithful and meaningless.
`synthesis_agent._peer_clause` (`agents/synthesis_agent.py:279`) only suppresses it when |mean| < 0.05, and 0.165 passes that
floor. The reader would think VG is 426x worse than peers on cash conversion; the truth is that it is a pre-commercial company
with about $3M of revenue and about $230M of cash burn. The gross-margin flag (91.7% vs 22.2%, "above peers", favourable
direction) uses n=3 peers and is likewise a tiny-revenue effect.

The peer group is Daseke, Verra Mobility, Lindblad, Global Business Travel, ModivCare, Diamond S Shipping, GXO and XPO
(trucking/logistics/travel; no space or aerospace comparables), with peers from FY2020 and FY2021 mixed (`peer_year_offsets`
[0, 1]). Only 3 of the 8 peers have gross margin.

The same pattern appears in the Beneish FY2020 smoking gun for VG: M = 7.12 and "DSO rose from 44.5 to 720.8 days (+1519.7%)"
come from revenue falling 93.7% to $238K (the fleet was grounded). The metrics are computed correctly but the denominator is
near zero, so they are not a manipulation signal. The same applies to Nikola `peer.ocf_to_revenue`: OCF -$150.5M over revenue $95K
gives -158,455.8%, "peer_pct" -55,574,136%.

### 2.4 Enron

Genuine (FY2000 10-K, 0001024401-01-500010): revenue +151.3%, receivables +243.1%, gross margin 13.3% -> 6.2%
from the statement parser; Beneish M -0.66 (SGAI imputed neutral; the SGAI coefficient is small, so the zone is not sensitive to
it; FY1999 was -2.00, grey). The `related_party` flag compares 2,673 -> 5,812 characters. Item 13 is a 257-character pointer to the
proxy in every year, so the growth comes from Note 16 ("transactions with limited partnerships (the Related Party) whose general
partner's managing member is a senior officer of Enron"), which is real expanding content. The FY2000 CEO change (Skilling "since
February 2001") is real and has zero weight in the temporal score.

Artifact (ledger A1, confirmed): the "FY1996" filing in the CIK-1024401 series is accession 0000950129-97-001319, a 15,667-character
Form 10-K of ENRON OREGON CORP. (commission file no. 333-13791), not Enron Corp. Against it the pipeline computes FY1997 "CEO changed
Segner -> Lay", "CFO changed Gathmann -> Fastow" and 18 "materially new" legal paragraphs. These are three spurious FY1997 flags
and a spurious Altman 1996 point. Timeline: 1996: 25, Stable; 1997: 65, Escalating; 1998: 30; 1999: 10; 2000: 70, Escalating.

Counterfactual (post-processing only; computed with `compute_temporal` on the state with FY1996 flags removed, and by hand): if FY1996 is
treated as unavailable, FY1997 becomes the first year of the series and, by the temporal agent's own definition ("the first year
can never be Escalating"), cannot be a detection year. Its remaining flags (`passive_voice`, `altman_distress`) score 35, below the
40 threshold anyway. FY1998 is 30 (Improving), FY1999 is 10 (Improving), FY2000 is 70 (Escalating). `first_detection_year` becomes
FY2000 (filing 2001-04-02), about 6.5 months before the 2001-10-16 revelation, not FY1997 (filed 1998-03-31), about 43.5 months
before. (My direct run of `compute_temporal` with only the `flags_by_year` entries dropped still returned 1997, because the
temporal agent re-derives flags from the structured fields, e.g. the Altman zone and the CEO/CFO change booleans; the figure above
applies the drop at the whole-year level.) The grade does not change (High needs only the focus year plus focus-year escalation).
The "detected 43 months early" claim in the report must not be quoted.

Weak point even for the genuine TP: the High grade needs 2+ agents flagging plus escalation. The second agent is network
(CEO change + related-party growth) or language (`passive_voice` + one `new_legal` paragraph about a 4-year-old explosion suit).
The language Medium is noise. Enron stays High in the `no_passive` variant.

### 2.5 WorldCom

Why Medium and not High: the focus-year (FY2001) severities are quantitative Low (only `altman_distress`), language Medium
(`passive_voice` 26.5% + `hedging`), network None, peer unavailable. That is 1 agent flagging (Medium rule 3) and temporal
signal change Stable, so there is no escalation. Beneish is computed and does not fire (-2.58 FY2000, -3.01 FY2001; WorldCom's
capitalised line costs are not visible in AQI/DSRI), so this is a true miss, not a data gap. The only Medium comes from
passive voice, which fires on every large-cap (ledger P2). In `no_passive` WorldCom is Low.

`network.related_party` +4466% (FY2000): Item 13 and note character counts are 180 in FY1999 (a pointer: "The information under the
caption..."), and 8,219 in FY2000 (Item 13 3,979 + note 4,240 characters). FY1998 was 179, FY1997 was 26,756 (inline), FY2001 is 3,773.
So the percentage is a pointer-versus-inline format artifact. The content is real though: the FY2000 text discloses
"Since September 2000, we agreed to loan up to $100 million to Mr. Ebbers... aggregate indebtedness $84.6 million". It is the
actual red flag of the case, surfaced by accident of formatting, and the same 1997 spike (+1876%) shows it flips with
formatting. This flag alone gives temporal "first detection FY2000", which equals the format change. The signal is NOT counted in
the FY2001 focus year (3,773 vs 8,219 is a decrease, although FY2001 text expands Ebbers guarantees).

### 2.6 The Medium grades among the clean companies

Rules (`agents/synthesis_agent.py:89-155`): Medium = (a) at least 1 agent at Medium+ severity, or (b) temporal escalation AND at
least one flagged year.

- AAPL (rule a): peer agent Medium (2 flags: `receivables_vs_revenue_growth` -35.2 pp vs peer +3.8 pp, receivables fell from
  $22.9B to $16.1B while revenue grew; `roa` 17.7% vs 7.4%). Both are favourable. Peer agent severity counts flags, direction-blind.
  Peers: Dell, IBM, Cisco, HPE, HP, Caterpillar, Deere, Johnson Controls (SIC-based). ARTIFACT (documented in A4).
- PG (rule b): no agent Medium+. `peer.dso` 21 vs 58 days (favourable) is a new flag attached only to the focus year, so FY2020
  scores 20 vs 10 and is "Escalating" (temporal docstring: peer flags exist only for the focus year, so the focus year always has
  "new flags"). "Any flagged year" is true because of `passive_voice` in all years. Triple artifact. Counterfactual: Low.
- BRK-B (rule b): focus-year change is Stable, but `_escalation` (`agents/synthesis_agent.py:158-170`) returns True as soon as the whole-
  series `signal_trajectory` is "Escalating" (net +10 from FY2016 to FY2020 because of one FY2019 accruals flag and the FY2020
  favourable `peer.roa`). Using the focus-year change: Low. An insurer in a peer set of insurers/life companies.
- MMM (rule b): focus year Escalating from CFO change (real: signed Gangestad 2020-02-06 vs Patolawala 2021-02-04, "Chief Financial
  Officer ... 2020") plus `peer.debt_to_equity` 1.46x vs 0.68x. Real facts, no fraud information.

Counterfactual with only the favourable-direction peer flags removed (re-computed through `compute_temporal` and
`compute_risk_grade`): AAPL, PG and BRK-B all go to Low; MMM stays Medium. The "0 FP" holds only because the positive threshold is
High, which sits exactly one rule above artifact-driven Mediums. At a Medium threshold the FPR is 4/6.

## 3. What the headline means after the audit

Headline: TP 3 / FP 0 / TN 6 / FN 3, precision 100%, recall 50%.

- Enron: genuine (1 of 3 true positives). Lordstown: artifact (SPAC mechanics; the only genuine content is post-revelation).
  Virgin Galactic: artifact (boilerplate hard flag + tiny-revenue peer outliers + escalation from series trajectory). Genuine
  true-positive count 1 of 3; genuine recall 1/6 (17%). Even Enron's is a single Beneish M-score hit on the one case where the fraud
  is a revenue/receivable gross-up.
- Virgin Galactic's High needs BOTH the boilerplate restatement flag and the series-trajectory escalation: with `_escalation` on the
  focus-year change only (Stable), the grade is Medium (a FN). Without the boilerplate flag, network would have only `cfo_change` (Low), leaving peer as the one Medium+ agent: by the rule text this
  is Medium (not re-run; reasoned from compute_risk_grade).
- Luckin is the best genuine content, but it only scores Medium (and is a post-revelation case).
- Real fraud content the system missed: Nikola's subpoena disclosure (data gap), WorldCom's Ebbers loans (caught only
  by format accident, not graded), WorldCom's capitalised costs (invisible).
- 0 FP: the 6 clean companies end 2 Low / 4 Medium; 3 of the 4 Mediums are artifacts, so the headline's specificity is bought by a
  grade threshold, not by a discriminating signal. No clean company was tested with a SPAC history, which is where the
  auditor/CFO "hard combo" would false-positive.
- Peer flags and passive voice behave as uninformative noise in the grade (they decide Medium/Low). Language severity is a flag
  count; `passive_voice` alone gives Low, plus any second language flag gives Medium.

## 4. Concrete bugs and artifacts (PROPOSED fixes only; none applied)

Every fix below was motivated by evaluation cases, so each must get a `docs/TUNING_LEDGER.md` row BEFORE merging (CONTRACTS 0.2).
Where a defect is also visible without the evaluation set (e.g. B1, B4), the orchestrator can justify it independently.

| # | Defect | Where | Effect on headline | Proposed fix |
|---|---|---|---|---|
| B1 | Material weakness regex fires on any non-negated mention, including forward-looking boilerplate ("our ability to timely and effectively remediate material weaknesses"), remediated history and auditor definitions. A restatement/MW flag is a "hard" flag. | `tools/text_parser.py:1373-1376`, `:1615-1617`; `agents/network_agent.py:436-446` (restatement guard exists, MW guard does not); hard rule `:516` | Creates the VG FY2021 TP and the FY2020 (remediated) flag | Require a first-person current-period assertion in Item 9A / controls section ("identified/concluded ... material weakness ... as of <period end>") or require "not effective"; ignore the forward-looking preamble and risk-factor conditionals ("may", "ability to"); classify remediated history as non-hard. |
| B2 | SPAC predecessor years are treated as the same entity: auditor, CEO, CFO, going-concern, legal comparisons across the merger year. | `agents/network_agent.py:304, 329-354`; `graph/pipeline` year selection; temporal series (`agents/temporal_agent.py`) | Creates Lordstown TP; Nikola and VG first-detection years; Nikola/Lordstown FY2019 going concern | Detect shell/SPAC predecessor filings (blank-check wording, "Business Combination" consummated in the year, tiny or no revenue) and either start the series at the first operating-company filing or tag the comparison `entity_changed` and weight 0. Also fixes the NKLA `new_legal` data gap. |
| B3 | `_escalation` returns True on the whole-series `signal_trajectory` before consulting the focus-year signal change. | `agents/synthesis_agent.py:158-170` | VG High (focus year is Stable) and BRK-B Medium are decided by this | Use `focus_signal_change` first (or only); series trajectory for narrative only. (Spec text: "temporal escalation" is ambiguous, so this needs a ledger decision.) |
| B4 | Peer flags are two-sided (direction-blind) and counted as risk flags; peer-agent severity is a flag count. | `agents/peer_agent.py:122` (`direction` computed but unused); severity at the peer agent; `agents/temporal_agent.py:34, 228-231` | AAPL, PG, BRK-B Mediums; MMM; VG peer High | Count only adverse-direction outliers (per-metric polarity table) for severity and temporal scoring; keep favourable ones as information. (Ledger A4 already notes it.) |
| B5 | Peer attach-to-focus-year-only bias: the focus year always gets "new flags" and "Escalating" when any peer flag fires. | `agents/temporal_agent.py:34, 226-235` | PG, MMM, AAPL escalation | Do not let peer-only new flags set `signal_change` to Escalating (or compute peer flags per year). |
| B6 | Tiny-denominator ratios are flagged and then narrated as huge percentages ("42634.6% below the peer group average"). | `agents/synthesis_agent.py:279-300` (`PEER_MEAN_FLOOR`), `agents/peer_agent.py` z-test, Beneish/DSO inputs | VG and NKLA smoking guns; VG FY2020 Beneish 7.12 / DSO +1519% | Suppress or label ratio outliers when revenue < materiality (e.g. revenue < 1-2% of assets) or |peer_pct| > 1000%; render as "revenue of $3.3M; operating cash burn $230.8M" instead of a percentage. Also mark peer set mismatch (SIC trucking/logistics for a spaceflight company) and mixed peer fiscal years. |
| B7 | Language severity is a flag count, and `passive_voice` (no information at 15%) gives a second flag to any company with one more language flag. | `agents/language_agent.py:898` | WorldCom Medium; Enron and Lordstown language Medium; clean-company `any_flagged_year` | Already declared as pre-registered P2; consider making `no_passive` the headline or exclude passive voice from `any_flagged_year` and severity. |
| B8 | FY1996 shell filing under the Enron CIK counted as the predecessor year (ledger A1), producing the FY1997 first detection. | `tools/edgar_api.py list_annual_filings` / `graph` fetch for CIK 1024401 | Enron `first_detection_year` 1997 (43.5 months) should be 2000 (6.5 months) | Add a predecessor-CIK mapping for Enron, or require minimum text length / entity-name match; at minimum print the A1 caveat next to the first-detection column in the report. |
| B9 | `related_party_chars` counts Item 13 pointer text (180-257 chars) in some years and inline text in others. | `tools/text_parser.py:1678`; `agents/network_agent.py:482-509` | WorldCom +4466% and +1876%; Enron | Compare only the notes-section length, or require the pointer to be resolved to the proxy before computing growth; flag `format_change` when the Item 13 length flips between pointer and inline. |
| B10 | Hard combination "auditor change + CFO change in the same year" gives High without checking that the new officers were already in the business (e.g. "served as Legacy Lordstown's CFO from September 2019"). | `agents/network_agent.py:516` | Lordstown/Nikola network High | Suppress when the 10-K text of the filing says the change follows a Business Combination, or when the new CFO tenure start predates the merger (parse "has served as our CFO since"). |
| B11 | Legal Proceedings pointer sections (`legal_chars` 258 in the Nikola FY2020 10-K) hide the real litigation disclosure in the Notes. | `agents/language_agent.py` new_legal; `tools/text_parser.py` `extract_sections` | Nikola real content missed | Follow "see Note X" pointers into the commitments/contingencies note. |
| B12 | Report prints the matched excerpt from the forward-looking preamble for Luckin and VG as "FY2019 filing discloses restatement ..." without telling the reader it is from the preface. | `agents/network_agent.py:455-469`, `_excerpt` | Presentation only | Print the section name and character offset, and prefer the Item 9A / Item 4.02 hit. |

## 5. Corrected honest reading

"The system flagged 3 of 6 known frauds with 0 of 6 false positives" should be restated as: one genuine detection (Enron FY2000,
Beneish plus related-party note growth, from a statement-fraud case), two detections produced by a SPAC-merger comparison
(Lordstown) and by boilerplate plus tiny-revenue ratios plus a trajectory rule (Virgin Galactic), and no detection of the other
statement fraud with a computed Beneish (WorldCom). Luckin's genuine content is post-revelation and still only Medium. The
clean set has no false positives only because the High cutoff sits above artifact-driven Mediums (3 of 4 clean Mediums are
artifacts). n=12, 4 of 6 fraud filings post-date revelation, and the first-detection timing for Enron, Nikola, Lordstown and
Virgin Galactic is an artifact of the shell/SPAC predecessor filings.
