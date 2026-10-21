# Holdout audit B: what actually drove the v1 / v2 holdout grades?

Scope: `evaluation/results/holdout_v1` and `holdout_v2` (`runs['spec/spec']`, n=24, 12 fraud + 12 matched clean; v1 TP/FP/TN/FN = 4/0/12/8,
v2 = 1/0/12/11). Read-only audit: no file under agents/, tools/, graph/, prompts/, evaluation/, tests/, the v1 snapshot or any results
folder was changed, and no pipeline was re-run. Evidence comes from (a) the stored JSON, (b) the pickled pipeline states that
`.cache/holdout_audit/states_v1.pkl` and `states_v2*.pkl` already held (all 24 grades in both versions equal the official JSON grades, and
the suspicion scores equal the numbers quoted in the official `temporal` key_finding), and (c) the cached filing text inside those states
(`state["filing_texts"]`). All excerpts below were read from that text. Scratch: `.cache/holdout_audit_b/` (`g.py` = excerpt grep,
`pairs.py`, `cf.py` = Beneish counterfactuals, `benish.txt`, `dump.txt`). `docs/holdout_research.md` is used for the known fraud mechanism.

Classes: GENUINE_SIGNAL (a real fact in the filing that bears on the label), MECHANICAL_ARTIFACT (a parsing/formula/rule effect),
BOILERPLATE_FALSE_POSITIVE (stock or hypothetical language read as an admission), DATA_GAP (input missing, so the test could not run),
UNKNOWN. Everything about scores is descriptive; n=12 pairs.

## 0. Headline findings

1. **None of the four v1 Highs is a clean "the system saw the fraud" hit.** TEUM is the only one whose decisive evidence is genuine and
   points at the fraud mechanism. SNCR is boilerplate + mechanics. USAT is mostly mechanics (two Beneish years are tax/tag artifacts) plus a real but stale,
   already-remediated material weakness. OFIX is half genuine (receivables really stretched) and half mechanical.
2. **The v1 -> v2 drop 4 -> 1 is entirely the removal of the passive-voice flag.** In v1, SNCR, USAT and OFIX each reached High only because the
   language agent was Medium (passive voice plus one more Low flag). In v2 the same agent is Low for all three (language severity v1 -> v2: SNCR Medium -> Low, USAT Medium -> Low,
   OFIX Medium -> Low) and the High rule ("2+ agents flagging with escalation") no longer fires. Passive voice fired in the focus year in **24 of 24** cases in v1
   (12/12 fraud, 12/12 clean): no information, as V2_PROTOCOL.md predicted. TEUM does not depend on it (quant Medium + network High + peer Medium).
3. **Beneish was computable in the focus year for only 5 of 12 fraud cases** (TNGO, GVA, USAT, QTM, LIME). The other 7 are DATA_GAP (missing `LongTermDebt` and/or `COGS`
   tag, or pre-XBRL). Of the five computed, only QTM fired, and that fire is an artifact (AQI 5.19 from a $20.0M restricted-cash reclassification). Where the gap is only a missing
   or untagged `LongTermDebt`, a scratch counterfactual (section 3.3) gives OSIR M = -1.25 (would fire), OFIX -1.97 (near miss), TEUM +2.56 (would fire strongly).
4. **Continuous ranking is better than the grade suggests but weak and partly artifact-driven.** Paired (fraud vs its matched control) suspicion score: fraud > control in
   8 of 12 pairs, 3 ties, 1 loss in both versions (AUC-style 0.79 each; pooled 12x12 AUC 0.785 v1, 0.802 v2). Grade-level pairing is 5 wins / 7 ties / 0 losses (v1), 5 / 6 / 1 (v2).
5. **False positives are zero, but clean companies still get Medium for mechanical reasons**: 7 of 12 clean are Medium in v1, 5 of 12 in v2 (section 4).

## 1. Classification of the 12 fraud cases (decisive evidence behind the grade)

Score = focus-year suspicion score from the temporal agent (the grade is a separate rule on agent severities + trajectory). M = Beneish M-score.

| Case (FY, fraud mechanism) | v1 grade (score) | v2 grade (score) | Decisive evidence | Class | Mechanism reflected? |
|---|---|---|---|---|---|
| SNCR FY2016 (upfront licence revenue without persuasive evidence; restated ~$190M) | High (80) | Medium (70) | network.going_concern = ASU 2014-15 text; language Medium = passive voice + risk-factor growth 121% (Intralinks deal); Altman Z' 1.05 | BOILERPLATE_FALSE_POSITIVE (+ MECHANICAL_ARTIFACT) | No. M = DATA_GAP (COGS, LTD) |
| USAT FY2017 (bill-and-hold, unordered devices) | High (85) | Medium (75) | network High = remediated FY2015/16 material weakness; M in FY2014/15 fired on tax-benefit and COGS-tag artifacts; passive voice | MECHANICAL_ARTIFACT (+ stale genuine MW) | No. M FY2017 = -1.83 (grey, 0.05 below the cut) |
| OFIX FY2012 (premature revenue, Brazil / Spine) | High (70) | Medium (60) | DSO 92.4 -> 118.7 (+28.5%), peer DSO z=+4.3, accruals 7.9%, passive voice | GENUINE_SIGNAL (DSO, partly basis-distorted) + MECHANICAL_ARTIFACT (accruals, passive) | Partly (receivables) |
| TEUM FY2018 (revenue from non-binding POs) | High (75) | High (65) | AR +646% vs revenue +139%; DSO 55.5 -> 172.9; material weaknesses in Item 9A; peer z=+21.7 | GENUINE_SIGNAL | Yes (receivables-led) |
| OSIR FY2014 (consignment / backdated revenue, small) | Medium (40) | Medium (30) | network High = remediated FY2013 tax material weakness; DSO +32.3% | BOILERPLATE_FALSE_POSITIVE (network) + GENUINE_SIGNAL (DSO, weak) | Weakly (DSO). M = DATA_GAP |
| TNGO FY2014 (revenue overstated ~7%) | Low (10) | Low (0) | none (passive voice only in v1). M = -2.61 | no decisive flag; plausible ratios | No |
| CGI FY2016 (impairments hidden via truck sale/buyback) | Medium (30) | Low (20) | v1: passive voice + risk-factor growth 65%; peer D/E z=+2.3 | MECHANICAL_ARTIFACT (v1) / weak generic (v2) | No. M = DATA_GAP (COGS) |
| RRTS FY2015 (deferred/unrecorded expenses) | Medium (20) | Low (10) | v1: passive voice + new_legal (3 of 3 paragraphs "new" = reworded ordinary-course text); OCF/NI 0.78/0.74 in FY2014/13 | MECHANICAL_ARTIFACT / BOILERPLATE_FALSE_POSITIVE (new_legal) | No. M = DATA_GAP (COGS) |
| GVA FY2018 (percent-of-completion cost-forecast deferral) | Medium (30) | Medium (20) | Rule 4 (escalation + a flagged year): CFO change, FY2016 "going concern" = ASU 2014-15 boilerplate. M = -2.36 | MECHANICAL_ARTIFACT (grade) / BOILERPLATE_FALSE_POSITIVE (going concern) | No |
| QTM FY2017 (channel-partner side terms) | Medium (65) | Medium (55) | M = -0.86 fired, AQI 5.19 from restricted-cash reclass; quant High, only agent | MECHANICAL_ARTIFACT | No (DSO +3.2%, DSRI 1.03) |
| LIME FY2011 (early / non-existent revenue ~$20M) | Medium (55) | Medium (45) | peer Medium (DSO 95 vs 71, OCF/rev -3.5% vs +2.0%), Altman Z' 0.17, CEO change | GENUINE_SIGNAL (weak, distress-confounded) | Loosely. M = -2.82 does not fire |
| PTRY FY2004 (pre-tax income overstated ~$59M) | Medium (40) | Medium (30) | hedging ratio +148%, CFO change (Aug 2004), v1 passive; quant/peer unavailable | MECHANICAL_ARTIFACT (hedging, probable) + DATA_GAP | No |

## 2. Priority 1: the four v1 Highs and the v2 High

### 2.1 SNCR (v1 High, v2 Medium): not genuine

* v1 rationale: "High rule fired: 2+ agents flagging together with temporal escalation (flagging 2 of 4; High 1)". The two flagging agents are network (High) and language (Medium).
* **network.going_concern (High)** quotes ASU 2014-15, not a doubt. Verified in the FY2016 text: "In August 2014, the FASB issued ASU No. 2014-15, 'Presentation of Financial
  Statements - Going Concern (Subtopic 205-40)...' (ASU 2014-15). ASU 2014-15 is intended to define management's responsibility to evaluate whether there is substantial doubt..." (under Impact of New Accounting
  Pronouncements). The same filing says: "management concluded that, as of December 31, 2016, its internal control over financial reporting was effective ... audited by Ernst & Young LLP". BOILERPLATE_FALSE_POSITIVE. v2 still has this flag.
* **language Medium** = passive voice (28.7%, mechanical) + risk-factor growth +121% (61,296 -> 135,686 chars; Item 1A runs offsets 76,415-137,736 in the FY2015 text and 73,073-208,803 in FY2016, so it is real text). The added text is the Intralinks acquisition
  ("Intralinks" appears 30 times in FY2016 Item 1A, 0 in FY2015) and the carrier-activation divestiture: genuine content, but M&A, not accounting. MECHANICAL_ARTIFACT with respect to fraud.
* quantitative Low: Altman Z' 1.05 (real leverage; the generated line itself says "a business-distress signal, not evidence of accounting manipulation"). The DSO flag fired in FY2014 (+39.1%), not FY2016 (+16.0%, 105.1 days, below the +20% cut).
* Beneish is DATA_GAP in every year (COGS and LongTermDebt not mapped). The fraud mechanism (revenue recognised on licences without persuasive evidence) is not reflected anywhere. The only revenue-related datum is a DSO that climbed from 67.9 (FY2013) to 105.1 (FY2016) in steps each below the +20% YoY rule (and FY2016 revenue fell 18% while AR fell only 4.5%).
* v2 loses High because passive voice is gone: language Low (risk-factor growth only), 1 agent flagging, grade Medium (score still 70).

### 2.2 USAT (v1 High, v2 Medium): mostly artifact

* Drivers: network High (`network.restatement`, CFO change), quantitative Medium (Altman distress + accruals 5.04% vs a 5.0% cut), language Medium in v1 (passive + new_legal), escalation from FY2014.
* **network.restatement** is a real material weakness but stale and remediated: "Although our internal controls over financial reporting were effective as of June 30, 2017, we identified a material weakness in our internal controls over financial reporting as of June 30, 2016 and June 30, 2015."
  It concerns the earlier problem, not the bill-and-hold fraud (holdout_research caveat says the same). Genuine but off-mechanism.
* **The escalation that made it High comes from Beneish in FY2014 (-0.35) and FY2015 (-0.80), both artifacts:**
  * FY2014: TATA 0.29, AQI 2.10, DEPI 2.56. Net income $27.53M vs OCF $7.09M is the valuation-allowance release: "The reduction of the $27,255,398 in valuation allowances is reflected as an income tax benefit in the provision for income taxes for the year ended June 30, 2014". MECHANICAL_ARTIFACT.
  * FY2015: GMI 3.11. Stored COGS is $4.25M for FY2014 (Revenue $42.34M, GrossProfit $15.07M, so true cost is about $27.3M) and $41.25M for FY2015: the FY2014 COGS tag misses equipment cost, so the gross-margin index is a tag artifact. The filing says "Overall gross profit margins decreased from 36% to 29%". MECHANICAL_ARTIFACT.
  * FY2017 (the analysed year): M = -1.83, grey, 0.05 below the -1.78 cut. Components DSRI 1.09, GMI 1.11, AQI 1.01, SGI 1.34, DEPI 0.20, SGAI 0.85, TATA 0.05, LVGI 0.93. The largest push is revenue growth (SGI, +34%); nothing specific to equipment shipments.
* language "new_legal" in FY2017 is a procedural update to the old class action ("On March 28, 2017, oral argument was held before the Court of Appeals"): not a new proceeding. v1 passive voice (mechanical) made language Medium.
* v2: language Low, 2 agents flagging (quant, network), "focus-year escalation: no", grade Medium (score 75). The mechanism (unordered devices shipped, bill-and-hold) is not reflected.

### 2.3 OFIX (v1 High, v2 Medium): half genuine

* v1 rationale: 2 agents flagging (quant Medium, language Medium) + escalation; no agent at High. Flags: `quantitative.dso_growth` (92.4 -> 118.7 days), `quantitative.accruals` (7.9% of assets), `peer.dso` (119 vs 60 days, z=+4.3), `language.new_legal`, passive voice, CFO change.
* **DSO: genuine direction, distorted size.** The engine compares FY2012 ($462.3M revenue, AR $150.3M) with FY2011 as originally filed ($579.0M, AR $146.5M, which still includes the Breg unit sold 2012-05-24).
  Recast in the FY2012 filing, 2011 net sales are $470.1M and AR $132.8M. The company itself reports: "days sales in receivables of 123 days at December 31, 2012 compared to 99 days at December 31, 2011". So receivables really stretched (like-for-like roughly +15% on year-end arithmetic to +24% on management's figures), but the +28.5% is partly a basis mismatch. GENUINE_SIGNAL with a MECHANICAL_ARTIFACT component. Brazil sales fell ($48.9M -> $38.0M) while the premature-revenue findings sat in Brazil/Spine, so a high, rising DSO is on-mechanism.
* **Accruals 7.9%: MECHANICAL_ARTIFACT.** NI $51.3M vs OCF $11.2M: "During 2011, we incurred charges related to the U.S. Government resolutions and fully paid these settlements during 2012. During 2011, the escrow receivable balance increased $32.6 million. The full escrow receivable was received in cash in 2012."
* The new legal paragraph is the Breg jury verdict (July 2012): real, but a divested subsidiary's product liability, unrelated to revenue recognition. Passive voice is mechanical.
* Beneish DATA_GAP although the balance sheet has "Long-term debt | 20,000 | 191,195" (the tag lookup did not find it). Counterfactual with those two values: M = -1.97 (grey; DSRI 1.28, GMI 0.93, AQI 0.65, SGI 0.80, TATA 0.08, LVGI 0.33): a miss by 0.19.
* v2: language Low, only quant flagging, Medium (score 60).

### 2.4 TEUM (v1 High, v2 High): the one genuine hit

* quant Medium, network High, peer Medium, all with real numbers. Verified: revenue "$32,435,736, an increase of ... 139%"; cash-flow statement "(Increase) in accounts receivable | (13,239,269) | (1,446,459)"; AR $15.36M vs $2.06M (+646%) while OCF is -$7.66M; DSO 55.5 -> 172.9; peer "receivables growth minus revenue growth +506.9 pp vs peer mean +2.8 pp (z=+21.7)".
* Network High is a real current-year disclosure: "management has identified the following deficiencies that constitute material weaknesses ... Inadequate and ineffective management assessment of internal control ... Ineffective design, implementation and monitoring of information technology general controls", while the filing adds "The material weakness did not result in any identified misstatements".
* The fraud mechanism (revenue booked on non-binding purchase orders with manipulated confirmations) maps naturally onto receivables ballooning relative to revenue: reflected. Caveats: part of the growth is acquisition (Q4 Artilium contributed $5.17M of revenue) and Altman distress (Z' 0.21) is a separate business-distress flag. Beneish is a DATA_GAP (no LongTermDebt tag); counterfactual with LTD = 0 (not verified against the balance sheet) gives M = +2.56 (DSRI 3.12, AQI 5.32 [acquired intangibles], SGI 2.39), which would have fired.
* v1 -> v2: language flag gone (passive), network text now labelled "Item 9A controls section, ~74% into the document", score 75 -> 65, still High.

## 3. Priority 2: the fraud cases graded Medium/Low in both versions

### 3.1 What the system saw and missed

* **TNGO (Low/Low).** Nothing decisive. Revenue +12.5% (FY2013 $188.9M -> $212.5M); DSO 83.6 -> 97.8 (+17.0%, under the +20% rule); M = -2.61 (DSRI 1.17, GMI 1.02, AQI 0.85, SGI 1.12, DEPI 1.09, SGAI 1.01, TATA -0.08, LVGI 0.98). With a ~7% revenue misstatement and ordinary ratios this is a genuine "plausible ratios" miss. Network recorded 3 (v1) / 6 (v2) data gaps.
* **CGI (Medium/Low).** Beneish DATA_GAP (COGS absent from the XBRL; SGA and LTD also absent in earlier years; a trucking income statement lists operating expenses). OCF -$5.2M against NI +$24.8M in FY2016 was not flagged (single year; the OCF/NI rule needs two consecutive years below 0.8, and accruals are 2.7% of assets, under the 5% cut). Risk-factor growth +65% (37,971 -> 62,731) is new generic text (a new "impairments of long-lived assets" risk factor that says "We have not been required to record an impairment charge with respect to our goodwill within the past three years"). The FY2012 "restatement/material weakness" smoking gun is the long-ago lease restatement (ASC 840-10-25-14, fiscal 2008). The concealed-impairment mechanism is not visible.
* **RRTS (Medium/Low).** `language.new_legal` reports 3 of 3 paragraphs "new" with the text "In the ordinary course of business, we are a defendant in several legal proceedings ..." (rewording, not a new case). OCF/NI 0.78 (FY2014) and 0.74 (FY2013) is a real, correctly computed earnings-quality warning but it is stale (FY2015 OCF/NI = 73.4/48.0 = 1.53), and DSO +20.8% in FY2014 came with revenue +37% (acquisitions). Beneish DATA_GAP (COGS).
* **GVA (Medium/Medium).** M FY2018 = -2.36 (DSRI 0.89, GMI 0.90, AQI 1.66, SGI 1.11, DEPI 0.83, SGAI 1.10, TATA -0.02, LVGI 0.92): only AQI is elevated (about +0.27 to M). The grade comes from Rule 4 (escalation + any flagged year), where the flagged items are a CFO change (real, benign) and, in v1, FY2016's "going concern", which is ASU 2014-15 text ("The guidance was effective for our annual period ended December 31, 2016. During the year ended December 31, 2016, management assessed the Company's ability to continue as a going concern ..."), BOILERPLATE_FALSE_POSITIVE. Percent-of-completion cost-forecast manipulation does not show in annual ratios (DSO 58.6 -> 52.1).
* **QTM (Medium/Medium).** The only Beneish fire among the 12, and it is an artifact: AQI 5.19 because "Restricted cash | 20,000 | -" moved into long-term assets (investing line "Change in restricted cash (20,240)") while current assets fell from $212.6M to $188.3M, off a tiny 2016 non-current base: AQI = (1-(188.3+11.2)/225.0)/(1-(211.6+12.9)/229.5) = 0.113/0.022. Other components are flat: DSRI 1.03, GMI 1.02, SGI 1.06, DEPI 1.01, SGAI 0.90, TATA -0.02, LVGI 1.24. With AQI at 1.0, M would be about -2.55. The channel-partner side-terms mechanism shows nothing (DSO 83.8, +3.2%). Grade stayed Medium because quant is the only flagging agent.
* **LIME (Medium/Medium).** peer Medium (DSO 95 vs 71 days z=+2.2; OCF/revenue -3.5% vs +2.0% z=-2.1), Altman Z' 0.17, CEO change ("we also promoted our COO, John ORourke, to be our President and CEO", benign). M = -2.82 (DSRI 0.94, GMI 1.08, AQI 0.63, SGI 1.25, DEPI 1.65, SGAI 0.87, TATA -0.07, LVGI 1.48): DSO actually fell 100.6 -> 94.8, so the receivables flag is a level effect against a 5-company peer set. Weakly genuine, not specific.
* **PTRY (Medium/Medium).** Pre-XBRL: quant and peer unavailable (DATA_GAP, "peer facts do not exist"). The hedging ratio +148% (1.4%) is driven by "may" 3 -> 60 and "could" 4 -> 38 while the MD&A word count doubled (5,251 -> 10,722), i.e. section scope or forward-looking boilerplate rather than tone (probable MECHANICAL_ARTIFACT, not verified at paragraph level). The CFO change is real ("in August 2004 joined us as Executive Vice President and Chief Financial Officer"; the parsed name "George D. Shadid Executive VicePresident" is a signature-block slip). The v1 FY2002 "material weakness" smoking gun is the SOX 302 certification sentence ("...and have identified for the registrant's auditors any material weak..."), BOILERPLATE_FALSE_POSITIVE. The v2 Medium is Rule 4 with no agent at Medium.
* **OSIR (Medium/Medium).** network High = "Although we have recently remediated a material weakness in our internal control over financial reporting ... The material weakness related to the maintenance of effective controls over the application and monitoring of our accounting for income taxes ... We have since remediated the material weakness" (BOILERPLATE_FALSE_POSITIVE with respect to the revenue fraud). DSO 112.0 -> 148.2 (+32.3%), peer z=+2.5: on-mechanism, genuine but weak (revenue +146%, so growth-confounded). Beneish DATA_GAP: no LongTermDebt line (the filing has none; 0 hits for "long-term debt" / "notes payable"). Counterfactual LTD = 0: M = -1.25, would fire (DSRI 1.32, GMI 0.93, AQI 0.01, SGI 2.46, TATA 0.01, LVGI 0.92).

### 3.2 Beneish summary

| Case | FY | M (as run) | Why not firing / unavailable |
|---|---|---|---|
| TNGO | 2014 | -2.61 | ratios ordinary (DSRI 1.17, SGI 1.12, TATA -0.08) |
| GVA | 2018 | -2.36 | only AQI 1.66 elevated |
| LIME | 2011 | -2.82 | DSRI 0.94, TATA -0.07; only SGI 1.25 up |
| USAT | 2017 | -1.83 (grey) | 0.05 short; SGI 1.34 the main push |
| QTM | 2017 | -0.86 (fires) | artifact: AQI 5.19 (restricted cash) |
| OSIR, SNCR, CGI, RRTS, OFIX, TEUM, PTRY | focus year | unavailable | DATA_GAP: LongTermDebt (OSIR, OFIX, TEUM, SNCR), COGS (SNCR, CGI, RRTS), pre-XBRL (PTRY) |

### 3.3 Counterfactual M-scores (scratch; `cf.py` runs `tools.financial_metrics.beneish_m_score` on the stored facts with the missing LongTermDebt supplied; informal, not an official result)

OSIR FY2014 (LTD = 0) M -1.25 manipulator; OFIX FY2012 (LTD 20,000K / 191,195K from the balance sheet) M -1.97 grey; TEUM FY2018 (LTD = 0, unverified) M +2.56 manipulator. SNCR, CGI and RRTS were not recomputed because COGS is also missing. The data gap is therefore not neutral: it hides at least two flags on cases where the formula would have fired, and in both (OSIR, TEUM) the firing would be driven by growth/acquisition terms (SGI, AQI, DSRI), not by anything specific to revenue recognition.

## 4. Priority 3: clean-company Mediums

| Case | v1 | v2 | Driver | Class |
|---|---|---|---|---|
| NSTG | Medium (45) | Low (25) | v1 network High = hypothetical risk factor: "if we or our independent registered public accounting firm identifies deficiencies in our internal control over financial reporting that are deemed to be material weaknesses, the market price of our stock could decline"; Beneish FY2013 -1.65 (DSRI 1.83: AR +151% vs revenue +37%, a growth company) | BOILERPLATE_FALSE_POSITIVE (v1); fixed in v2 |
| LSTR | Medium (30) | Medium (20) | peer Medium: DSO 53 vs 39, ROA 12.5% vs 5.4%. The peer set is asset-heavy truckers (Celadon, Knight, ArcBest, Saia, Heartland, Yellow, Werner, Knight-Swift); LSTR is an asset-light broker | MECHANICAL_ARTIFACT (peer mismatch) |
| MTZ | Medium (30) | Medium (30) | language Medium: LLM-rated specificity 4/10 + passive (v1) / new_legal (v2); peer DSO 102 vs 59 (construction contract assets in receivables) | MECHANICAL_ARTIFACT (LLM rating, business-model DSO) |
| ALOT | Medium (20) | Medium (10) | Rule 4: escalation + one Low flag. DSO +23.8% is real (AR $15.7M -> $22.4M, +43%, vs revenue +15%) | MECHANICAL_ARTIFACT (grade rule on a single Low flag); the metric movement is genuine and benign |
| MITK | Medium (50) | Medium (30) | v1 network High = hypothetical 404 risk factor ("may reveal deficiencies ... that are deemed to be material weaknesses") + CFO change; v2 Rule 4 on accruals 5.1% (cut 5.0%) + CFO change | BOILERPLATE_FALSE_POSITIVE (v1); MECHANICAL_ARTIFACT (v2, threshold edge) |
| AGX | Medium (40) | Low (10) | v1 peer Medium from favourable outliers: DSO 41 vs 75 days, OCF/revenue 55.5% vs 1.1% (z=+16.9) | MECHANICAL_ARTIFACT (direction-blind); fixed in v2 (recorded as informational) |
| RAH | Medium (30) | Medium (30) | v1 Rule 4 on DSO 3.1 -> 5.5 days (+81%) on a 3-day base + the FY2002 SOX 302 sentence; v2 network High `restatement`: "In November 2003, Vail again restated its financial statements ... the Company chose to reflect the full $.8 impact ... rather than restate its previously reported financial statements" | MECHANICAL_ARTIFACT (v1); BOILERPLATE_FALSE_POSITIVE (v2: an investee restated, the company expressly did not) |

v1 had 7 clean Mediums (NSTG, LSTR, MTZ, ALOT, MITK, AGX, RAH), v2 has 5 (LSTR, MTZ, ALOT, MITK, RAH). All five persisting ones are mechanical or boilerplate; none is a GENUINE_SIGNAL about misreporting.

## 5. Paired ranking (descriptive, n = 12 pairs)

Suspicion score (focus year, temporal agent; the same score that feeds the grade rule), fraud vs matched control.

| Pair | v1 fraud / control | v1 | v2 fraud / control | v2 |
|---|---|---|---|---|
| OSIR / NSTG | 40 / 45 | loss | 30 / 25 | win |
| TNGO / LPSN | 10 / 10 | tie | 0 / 0 | tie |
| CGI / LSTR | 30 / 30 | tie | 20 / 20 | tie |
| SNCR / EPAM | 80 / 10 | win | 70 / 0 | win |
| RRTS / HUBG | 20 / 10 | win | 10 / 0 | win |
| GVA / MTZ | 30 / 30 | tie | 20 / 30 | loss |
| USAT / ALOT | 85 / 20 | win | 75 / 10 | win |
| QTM / MITK | 65 / 50 | win | 55 / 30 | win |
| OFIX / ICUI | 70 / 10 | win | 60 / 0 | win |
| LIME / AGX | 55 / 40 | win | 45 / 10 | win |
| TEUM / BAND | 75 / 20 | win | 65 / 10 | win |
| PTRY / RAH | 40 / 30 | win | 30 / 30 | tie |
| **Wins / ties / losses** | | **8 / 3 / 1** (AUC-style 0.79) | | **8 / 3 / 1** (0.79) |

* Pooled 12x12 AUC: v1 0.785, v2 0.802. Mean score fraud vs clean: v1 50.0 vs 25.4; v2 40.0 vs 13.8. Grade-level pairs: v1 5 wins / 7 ties / 0 losses; v2 5 / 6 / 1.
* Number of distinct focus-year flags (alternative continuous measure), v1: 7 wins / 3 ties / 2 losses (0.71).
* The ordering is better than the grade (v2 keeps rank information while lowering controls by removing noise), but much of the winning margin comes from the same artifacts: of the 8 v2 wins, SNCR (boilerplate going concern, M&A risk factors), USAT (stale MW), QTM (AQI artifact) and OSIR (remediated MW) rest mainly on artifacts; OFIX, TEUM and LIME (weakly RRTS) rest on genuine receivables/cash numbers. TNGO is a 0-0 tie where the system saw nothing in either company. Sign-test caveat: 8 of 9 non-tied pairs favour fraud (one-sided p about 0.02), but the pairs are not independent of the grading rule and n is small; treat as descriptive.

## 6. Defects surfaced (v3 backlog only; not fixed here)

1. Beneish tag mapping: missing `LongTermDebt` treated as unavailable even when the balance sheet shows the line (OFIX "Long-term debt 20,000 / 191,195") or the company has none (OSIR); `COGS` missing for services/trucking income statements (SNCR, CGI, RRTS). Result: 7 of 12 fraud cases get no focus-year M-score.
2. `network.going_concern` still matches ASU 2014-15 / ASC 205-40 pronouncement text (SNCR, GVA; EPAM and BAND in earlier years).
3. `network.restatement` matches the SOX 302 certification sentence (PTRY, RAH FY2002), an investee's restatement (RAH FY2004) and remediated historical weaknesses (OSIR, USAT, CGI FY2012). v2 fixed only the hypothetical-risk-factor form (NSTG, MITK).
4. Prior-year comparisons use originally filed values, so divestitures/discontinued operations distort YoY ratios (OFIX / Breg).
5. AQI is unbounded for tiny prior-year non-current bases (QTM 5.19); restricted-cash reclassifications move AQI.
6. `new_legal` counts reworded ordinary-course text and procedural updates as new proceedings (RRTS, USAT).
7. Peer-set mismatch for business models (LSTR broker vs truckers, MTZ contract assets).
8. Rule 4 (escalation + any flagged year) yields Medium on a single Low flag (GVA, ALOT, MITK v2, PTRY, RAH).
9. Accruals threshold edge: MITK 5.1%, USAT 5.04% against a 5.0% cut.

## 7. v3 ideas (each must be validated on a new, unseen set; none is a recommendation to change a cutoff)

* Repair the Beneish input mapping (resolve LongTermDebt from the balance-sheet table, make COGS-less filers explicit) and report the gap rate as the first metric on a fresh set.
* Compute YoY deltas on a like-for-like basis (use the current filing's recast prior-year column) before DSO/DSRI/SGI.
* Distinguish "disclosed" from "hypothetical / pronouncement / certification / remediated / investee" language in network flags using section context, with the model returning a structured label per sentence.
* Consider multi-year cumulative receivables-versus-revenue drift instead of a single +20% YoY test (SNCR DSO 67.9 -> 105.1 never crossed it in one year).
* Report the continuous suspicion score or rank beside the grade, and evaluate pairwise AUC on a new set of pairs.

## 8. Caveats

* The pickled states come from an earlier audit run (A) in `.cache/holdout_audit/`. Grades and scores were checked against the official JSON for all 48 case-versions and match, but they are not themselves official artifacts.
* Beneish counterfactuals are scratch calculations on stored facts; TEUM's zero-LTD assumption was not verified against the balance sheet.
* Classes for PTRY hedging and RRTS legal text rest on counts and excerpts, not a full read. "Mechanism reflected" is a judgement against docs/holdout_research.md.
* Labels: clean = no known problem, not proven clean. n = 12 + 12; the confidence intervals in the evaluation reports are very wide.
