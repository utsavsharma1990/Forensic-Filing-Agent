# H2 audit B: what actually drove the v1 / v2 / v3 grades on holdout 2?

Scope: `evaluation/results/h2_v1|h2_v2|h2_v3` (`runs['spec/spec']`, n=30, 15 fraud + 15 matched clean). Official TP/FP/TN/FN: v1 6/1/14/9, v2 2/1/14/13, v3 2/1/14/13.
Strictly read-only: no file under agents/, tools/, graph/, prompts/, evaluation/, tests/, either snapshot or any results folder was changed and no pipeline was re-run.
Evidence = (a) stored JSON (v3 rows carry flags_by_year, grade_inputs, suspicion_by_year; v1/v2 rows do not store suspicion scores), (b) CACHED filing text through
`tools.edgar_api.fetch_filing_text` (every excerpt below was read from it), (c) cached XBRL / statement-table facts through `tools.xbrl_parser.get_annual_facts` +
`tools.financial_metrics.beneish_m_score` (my recomputed M equals the stored v3 M where both exist: PSIX -1.757 vs -1.76, HEV -1.203 vs -1.17/-1.20), and
(d) `docs/holdout2_research.md` for the later-known mechanism. Scratch: `.cache/h2_audit_b/` (ft.py = text grep, ben.py / cf.py = Beneish, legal.py = compare_legal, facts.py).
Caveat: "counterfactual" M-scores patch a missing input from the printed balance sheet; they are informal, not official results.

Classes: GENUINE_SIGNAL (a real fact in the filing bearing on the label), MECHANICAL_ARTIFACT (parsing / formula / rule effect), BOILERPLATE_FALSE_POSITIVE
(stock or hypothetical language read as an admission), DATA_GAP (input missing so the test could not run), UNKNOWN.

## 0. Headline findings

1. **Of v1's six fraud Highs, only HEV is a clean genuine hit; SAEX is a genuine concentration signal reached through a metric artifact; PSIX, SCOR, HIL and RTIX owe the High mostly to boilerplate or mechanics.**
   v1 PSIX network High = a SOX-404 risk-factor sentence (Item 9A says ICFR was *effective*); v1 SCOR network High = a hypothetical 404 risk factor; v1 HIL network High includes ASU 2014-15 text (its material weakness is real); v1 RTIX quant is an ASC 606 adoption effect.
2. **The v1 -> v2/v3 drop from 6 to 2 Highs is mostly removal of passive voice, the ROA-direction fix and (v3) network boilerplate, not removal of genuine evidence.** HIL, PSIX and SCOR lost the "2+ agents flagging" condition because a language flag (passive / new_legal) or a network boilerplate flag disappeared; HEV lost "focus-year escalation" because its v1 escalation was created by a new passive-voice flag (v2/v3 focus signal = Stable).
   The drop removed 3 artifact-Highs and 1 genuine one (HEV: M -1.17 fires + related-party Think Global). **The High rule "2+ agents flagging" cannot reward a single strong on-mechanism agent** (HEV quant High alone, PSIX quant High alone, SMRT and VOL network High alone each end at Medium).
3. **The two v3 TPs (SAEX, RTIX) are weak.** SAEX: a real, mechanism-adjacent receivable concentration, but the DSO / peer-receivable numbers are inflated by a current vs long-term reclassification of the same receivable. RTIX: the DSO rise is explained by management as ASC 606 adoption; language Medium is a new patent suit plus a hedging ratio; nothing touches pull-forward shipments (right label, wrong reason).
4. **The single FP (ACLS, High in all three versions) is driven by `network.going_concern` matching the ASU 2014-15 adoption note verbatim.** v3's pronouncement exclusion did not catch it (it did catch the RTIX / HIL variants). Without it ACLS is Medium (quant Medium alone).
5. **Beneish: computable on 9/15 fraud cases in v3 and fired in the focus year on 2 (PSIX -1.76, HEV -1.17).** The 6 unavailable cases are 4 extraction/label-mapping gaps (SCOR, SWSH, UNTK, VOL), 1 partial balance sheet (ISLN) and 1 structural (SMRT, retailer with no receivables line). Counterfactuals: only VOL (-1.43) would have fired.
6. **Paired ranking is weakly informative and all 3 pair losses are artifact-driven** (ACLS boilerplate, LGTY boilerplate, APKT IPO-growth Beneish + ISLN data gap). 11W/1T/3L, sign-test p=0.057, AUC 0.767 [0.567, 0.933]. Of the 11 wins roughly 5 are genuine (HEV, PSIX, VOL, SAEX partly, RVLT through stale in-window years).
7. **Clean "Medium" grades are mostly Rule 4 (focus-year "escalation" + any flag) with no agent at Medium**: LYTS, EXPO, KAI, AMN (4 of 8 clean Mediums). Escalation = any new non-peer flag with a higher score than the previous year (`temporal_agent.build_timeline`), so it fires on flag oscillation (Altman Z' crossing 1.23, a CFO change).

## 1. Classification table (decisive evidence behind each v3 grade; v1/v2 differences in section 2)

Score = v3 focus-year suspicion score. M = Beneish M-score (threshold -1.78; fires if above).

| Case (FY; later-known mechanism) | v1/v2/v3 | Score | Decisive evidence (v3) | Class | Mechanism reflected? |
|---|---|---|---|---|---|
| SAEX FY2018 (revenue on contracts with CEO-controlled customer; receivable / Alaska tax-credit issues) | H/H/H | 65 | peer receivables-vs-revenue z=+12.3, OCF/rev -30.6%; quant DSO "17.5 -> 95.9" + Altman Z' | GENUINE_SIGNAL (concentration) + MECHANICAL_ARTIFACT (DSO/peer magnitude from current vs LT AR split) | Partly: yes for the single-customer receivable, no for related-party control |
| RTIX FY2018 (revenue pulled forward by early shipments) | H/H/H | 55 | quant Medium = DSO 45.8 -> 62.8 (+37.2%) explained by ASC 606 adoption + Altman Z' 1.13; language Medium = new LifeNet patent suit + hedging | MECHANICAL_ARTIFACT (ASC 606) + GENUINE (new patent suit, off-mechanism) | No |
| ACLS FY2016 (CLEAN control, the FP) | H/H/H | 55 | network High = ASU 2014-15 note read as going-concern doubt; quant Medium DSO 44.6 -> 69.1 (+54.9%), accruals 6.6% | BOILERPLATE_FALSE_POSITIVE (decisive) over a real but benign receivable / cash divergence | n/a |
| HIL FY2016 (uncorrected FX loss errors, ~$5M) | H/M/M | 20 | network High = real FY2016 material weaknesses incl. "accounting close process, accounting estimates"; peer D/E z=+2.0 (Low) | GENUINE_SIGNAL (known MW, weakly on-mechanism); v1 High was BOILERPLATE (ASU going concern) + MECHANICAL (passive / new_legal) | Weakly |
| PSIX FY2015 (bill-and-hold, ~$25M) | H/M/M | 70 | quant High: M -1.757 (0.02 over cut), accruals (NI 14.3 vs OCF -23.0), revenue_quality | GENUINE_SIGNAL (borderline); v1 network High = BOILERPLATE_FALSE_POSITIVE | Weakly (revenue booked, no cash) |
| SCOR FY2014 (revenue overstated ~$50M via manipulated contracts) | H/M/M | 45 | network Medium = CEO and CFO change; quant Low = Altman Z' 1.04 every year; M DATA_GAP | GENUINE (exec turnover, off-mechanism) + DATA_GAP; v1 High = BOILERPLATE (hypothetical 404 risk factor) + MECHANICAL | No |
| HEV FY2010 (no impairment of 48%-owned related party Think; improper Q4 revenue to it) | H/M/M | 80 | quant High: M -1.17 (DSRI 1.69, SGI 2.22, DEPI 1.72), DSO 66.6 -> 112.6; network Medium: related_party + CFO change | GENUINE_SIGNAL | Yes (Think Global = "nearly all of our automotive revenue") |
| MNTX FY2016 | M/M/M | 25 | focus flag only Altman Z' 1.11; M -1.61 / -1.65 fired in FY2014 / FY2012 but stale; FY2016 M recompute -3.15 | GENUINE (stale, in-window) not credited by grade rule | Partly (SEC window began Q4 2014) |
| RVLT FY2017 | M/M/M | 35 | focus: Altman + peer DSO 84 vs 48 days; FY2015 M -1.56 fired, FY2014 DSO growth + accruals | GENUINE (stale years) | Partly (bill-and-hold -> high DSO) |
| PLUG FY2019 | M/M/M | 45 | language Medium (risk-factor growth, new_legal), FY2018 DSO +85.4%; M -3.22 (GMI 0.12) | UNKNOWN / weak | No (lease / cost-classification errors invisible) |
| SMRT FY2011 (inventory / credit-card liability errors) | M/M/M | 10 | network High: 2 real MWs "controls over communication of system incidents and credit card receivables" | GENUINE_SIGNAL; M = DATA_GAP (structural, no receivables line) | Yes |
| SABA FY2011 (falsified time records) | L/L/L | 25 | Altman Z' -0.51 only; M -2.76; peers unavailable (pre-XBRL) | no decisive flag (plausible ratios) + DATA_GAP (peer) | No |
| SWSH FY2010 (business-combination accounting; findings concern 2011) | M/M/M | 35 | quant Medium: DSO 31.8 -> 40.5 (+27.4%, acquisition year) + Altman Z' 0.64; M DATA_GAP | MECHANICAL (acquisitions) / UNKNOWN | No |
| VOL FY2008 (revenue recognised early at a subsidiary) | M/M/M | 20 | network High: Item 9A MW at a subsidiary "revenue recognition and other transactions"; accruals 14.4% (NI 64.2 vs OCF -69.2) | GENUINE_SIGNAL; M DATA_GAP (label) | Yes |
| ISLN FY2006 (side-deal revenue) | L/L/L | 0 | nothing computable (IPO-year filing, pre-XBRL, 0 flags, no peers) | DATA_GAP | No |
| UNTK FY2011 (premature revenue at Pinnacle Wireless) | M/M/M | 45 | network Medium: related-party note 547 -> 7,753 chars + CEO change; quant Low from FY2007 "OCF -956.83x NI"; peer OCF/rev z=-3.2 | UNKNOWN (related-party growth, possibly acquisitions) + MECHANICAL (NI near 0 ratio, telecom peers); M DATA_GAP | Unclear |

## 2. Priority 1: the six v1 fraud Highs and why v2/v3 dropped four

### 2.1 SAEX (High / High / High): genuine concentration, inflated by a metric artifact

* v1: High because peer was High (3 flags: receivables z=+12.3, OCF/rev z=-2.7, ROA z=-2.9), quant Medium (M -0.93 FY2016 stale + Altman + DSO), language Medium (hedging + passive). v2/v3: peer ROA became "non-manipulation direction / informational" -> peer Medium; passive voice gone -> language Low; still "2 agents flagging (quant, peer) + escalation" = High. The grade survived all three versions through different agents.
* **The receivable numbers are partly an artifact.** FY2018 note (verified): "Total accounts receivable, net | 77,663 | 84,207 / Current accounts receivable, net | 24,859 | 6,105 / Long-term accounts receivable, net | $52,804 | $78,102". The engine uses current AR only, so DSO "17.5 -> 95.9 days" and peer "receivables growth minus revenue growth +332.7 pp" (AR +307% vs revenue -25.5%) come from the same receivable moving between long-term and current. On total AR the balance fell 84.2 -> 77.7M while revenue fell 127.0 -> 94.6M (about 242 -> 300 days).
* **The underlying fact is genuine and on mechanism.** Risk factor (verified): "As of December 31, 2018, we have a $52.8 million accounts receivable, net of allowance for doubtful accounts of $19.0 million, from one customer. This is our single largest accounts receivable, constitutes the majority of our outstanding accounts receivable and is the largest single asset ... we believe that it is unlikely that the customer will be able to fully satisfy the receivable directly." The later-known fraud is ~$100M of revenue booked to a purportedly unrelated customer controlled by the CEO plus the Alaska tax-credit receivables. No agent reads this passage; the grade got there through ratios.
* OCF -$29.0M vs NI -$83.6M; gross profit -$2.6M (so my M recompute -4.89 has GMI -6.39, meaningless). v3 M FY2016 = -0.32 (v2 -0.93, comparative-column change), stale for the focus grade. Verdict: GENUINE_SIGNAL (concentration / collectability) + MECHANICAL_ARTIFACT (magnitude). Network `going_concern` in FY2014/2015/2017 is ASU 2014-15 text ("The guidance requires management's evaluation of whether there are conditions...") and is still flagged in v3 (not in the focus year, but it feeds the escalation history).

### 2.2 RTIX (High / High / High): right label, wrong reason

* quant Medium = `dso_growth` (45.8 -> 62.8, +37.2%) + `altman_distress` (Z' 1.13, "a business-distress signal, not evidence of accounting manipulation"). The company states (verified, MD&A): "At December 31, 2018, we had 63 days of revenues outstanding in trade accounts receivable, an increase of 17 days compared to December 31, 2017. The increase is primarily driven by the longer period receivables remain outstanding for contracts ... where revenue is recognized over time under ASC 606. Whereas previously, revenue and receivables were recorded at the time of shipment, they are now recorded over time." Revenue +0.5% ($279.6M -> $280.9M), AR $35.1M -> $48.4M. MECHANICAL_ARTIFACT (accounting-standard change). M = -2.27 (DSRI 1.37, AQI 1.28): no fire.
* language Medium: v1 = hedging +32% (0.8% of MD&A words) + passive voice; v2/v3 = hedging + `new_legal`. The new_legal is real: I reproduced `compare_legal` on the legal note (new identifiers `court:district court for middle district of florida`, `matter:patent`; "On June 27, 2018, LifeNet Health, Inc. filed a patent infringement lawsuit ... claiming infringement of five of their patents"). GENUINE event, unrelated to revenue recognition. Item 3 itself is a stub pointing to Note 23.
* Escalation FY2018 came from "new" flags altman_distress (absent in FY2017 only because Z' straddles 1.23), dso_growth, hedging and new_legal. The pull-forward mechanism ("shipping orders early ... to meet guidance") is not reflected.

### 2.3 HIL (High -> Medium -> Medium)

* v1 High = network High (restatement + going_concern) + language Medium (passive + new_legal) + peer Medium (D/E z=+2.0, ROA z=-2.6). Verified: the going_concern quote is "In August 2014, the FASB issued ... ASU 2014-15 ... to evaluate whether there is substantial doubt" (BOILERPLATE_FALSE_POSITIVE; the research file's caveat that the filing "already reports going-concern language" is not supported by the text I read). `restatement` = a real material weakness: "management identified material weaknesses ... certain errors related to the estimation of potential losses on our accounts receivable and ineffective procedures related to the accounting close process, accounting estimates, and non-routine transactions in addition to a newly identified material weakness related to certain tax controls". Real, already known to the company, adjacent to the later finding (uncorrected FX loss errors).
* Why dropped: v2 passive voice removed -> language Low, peer ROA direction -> Low, so 1 agent; v3 additionally drops the ASU going_concern and new_legal. v3 Medium rests on the genuine MW alone ("agents flagging 1, escalation no"). M -2.93 (DSRI 0.94, GMI 1.20, SGI 0.72, DEPI 1.61).

### 2.4 PSIX (High -> Medium -> Medium)

* v1: quant High (M -1.76, 0.02 over the cut; accruals; revenue_quality) + network High. The network High is SOX-404 risk-factor language (verified): "we are required to document and test our internal control procedures and prepare annual management assessments ... These assessments must include disclosure of identified material weaknesses ...", while Item 9A says "our internal control over financial reporting was effective". BOILERPLATE_FALSE_POSITIVE. v2/v3 network = Low (CFO change), so only quant (High) flags -> Medium.
* The quant High is the best genuine evidence: NI $14.3M vs OCF -$23.0M (accruals 10.4% of assets), OCF negative three years (-12.4, -15.7, -23.0) while profitable in 2014/2015, DSO 85.7 -> 97.8 (+14%, under the +20% rule), gross margin 19.3% -> 16.1%. Consistent with revenue booked without cash (bill-and-hold) but equally with working-capital funding of 12% growth plus acquisitions; M sits 0.02 above the cut, i.e. fragile. GENUINE_SIGNAL (borderline).

### 2.5 SCOR (High -> Medium -> Medium)

* v1 network High = hypothetical risk factor (verified): "we have in the past identified, and may in the future identify, areas requiring improvement ... Remedying any significant deficiencies or material weaknesses that we or our independent registered public accounting firm may identify could require us to incur significant costs"; no weakness is disclosed. language Medium = passive + v1 new_legal (the v3 comparator finds no new unit among 87). v1 High = BOILERPLATE + MECHANICAL.
* v2/v3: network Medium = CEO change (Magid Abraham -> Serge Matta) + CFO change (Tarpey -> Matta): genuine but off-mechanism. Altman Z' 1.04 flagged in all five years. Beneish DATA_GAP (section 4); counterfactual with COGS 97,467K / 89,963K and equipment loan + capital lease long-term 13,072K / 13,330K from the filing: M -3.26 (DSRI 0.95, AQI 0.93, SGI 1.15), would not fire. The ~$50M misstatement via non-monetary contracts is not visible in annual ratios.

### 2.6 HEV (High -> Medium -> Medium)

* quant High is real: AR $6.3M -> $23.9M (+279%) vs revenue $34.8M -> $77.4M (+122%), DSO 66.6 -> 112.6, M -1.17 (DSRI 1.69, SGI 2.22, DEPI 1.72, LVGI 1.38; SGAI imputed). The related-party flag is on mechanism: the FY2010 10-K says "Sales to Think Global have represented nearly all of our automotive revenue in the past" and refers to "our investment in Think Holdings". Later finding: failure to impair the related-party investment / loan / receivables and improper Q4 2010 revenue on sales to it. Genuine, though also consistent with a hyper-growth, cash-burning company (NI -$68.8M, OCF -$61.7M), so specificity is limited.
* Why dropped: v1 language Medium (passive 32.5% + risk-factor growth +44%) made 3 agents flag with escalation (FY2010 "Escalating" because passive voice was a new flag). v2/v3: language Low, focus signal Stable (FY2010 score 80 vs FY2009 85, no new non-peer flag) -> "2 agents flagging, escalation: no" -> Medium. The rule, not the evidence, changed.

### 2.7 Summary of v1 Highs

| Case | v1 driver | genuine or artifact | v2/v3 change |
|---|---|---|---|
| SAEX | peer High + quant M + language Medium | genuine concentration + artifact magnitude | peer ROA informational, passive removed; still 2 agents |
| RTIX | quant (ASC 606 DSO + Altman) + language (hedging, passive) | artifact | new_legal replaces passive; still High |
| HIL | network (ASU going concern + real MW) + language + peer | mixed; boilerplate decisive in v1 | -> 1 agent (real MW) |
| PSIX | quant High + network High (SOX-404 risk factor) | quant borderline genuine, network boilerplate | network -> Low CFO change |
| SCOR | network High (hypothetical 404 risk factor) + language (passive, new_legal) | artifact | -> Medium (exec turnover) |
| HEV | quant High (M fires, DSO) + network + language (passive escalation) | genuine | escalation lost with passive voice |

## 3. Priority 2/3: the v3 TPs, the FP and the clean Mediums

### 3.1 The v3 TPs (SAEX, RTIX): see 2.1 and 2.2

Both High grades hold in v1, v2 and v3, so the v2/v3 changes (passive voice removed, ROA direction, pronouncement exclusion) did not alter them. Verdict: SAEX = partly genuine (receivable concentration the later case was about), RTIX = artifact (ASC 606) plus an unrelated patent suit. Neither v3 TP shows the later-known mechanism through a mechanism-specific rule.

### 3.2 ACLS FP (High / High / High): BOILERPLATE_FALSE_POSITIVE

* v3: quant Medium (`dso_growth` 44.6 -> 69.1 days, +54.9%; `accruals` 6.6% of assets) + network High (`going_concern`) with focus-year escalation -> "2+ agents flagging with escalation".
* The going-concern "doubt" is the FASB pronouncement note (verified, FY2016 Item 8 recent-pronouncements): "In August 2014, the FASB issued ASU No. 2014-15, 'Disclosure of Uncertainties about an Entity's Ability to Continue as a Going Concern.' ASU 2014-15 introduces an explicit requirement for management to assess if there is substantial doubt ... The adoption of this standard did not have a material impact on the Company's consolidated financial statements." The v1/v2 quote was the same sentence; v3's quote starts one sentence later ("... and to provide related footnote disclosures in certain circumstances. In connection with each annual and interim period, management must assess if there is substantial d...") so the protocol item 3 exclusion (accounting-pronouncement text) **failed to match this wording**. It is the decisive evidence for the FP: remove the network flag and the grade is Medium (one agent).
* The quant side is a real but benign pattern (ACLS: revenue $301.5M -> $267.0M, AR $36.9M -> $50.6M, NI +$11.0M vs OCF -$8.8M; the company says "In 2016, $8.8 million of cash was used to support operating activities" and cash-flow line "Other assets and liabilities (12,270)"). GENUINE ratios, not fraud; a ratio screen cannot tell this from SAEX-type deterioration without text.
* ACLS also scores 55 on the continuous score and beats its paired fraud MNTX (25): the largest single pair loss. Flags by year (v3): FY2013 altman + dso_growth, FY2014 altman + going_concern, FY2016 dso_growth + accruals + going_concern; suspicion 0/55/60/0/55 for FY2012-16, so the FP recurs across years.

### 3.3 Clean Mediums under v3 (8): all but one are rule or boilerplate artifacts

| Clean | Score | What produced Medium | Class |
|---|---|---|---|
| LYTS | 20 | Rule 4: escalation + CFO change (Low network) | MECHANICAL_ARTIFACT (rule) with a benign real event |
| EXPO | 10 | Rule 4: escalation + passive voice share +35% to 18.4% (Low) | MECHANICAL_ARTIFACT |
| KAI | 20 | Rule 4: escalation + CFO change | MECHANICAL_ARTIFACT |
| AMN | 10 | Rule 4: escalation + hedging ratio +25% to 0.9% (Low) | MECHANICAL_ARTIFACT |
| EAF | 30 | language Medium (hedging + new_legal) + peer ROA +48.8% vs peer mean -1.7% (z=+3.2) recorded as an outlier (Low); M -2.61 | peer ROA = MECHANICAL (a hugely profitable GrafTech vs loss-making peers: NI $744.6M on revenue $1,790.8M); new_legal real |
| LGTY | 30 | network High `restatement` = hypothetical acquisition risk factor: "If we discover that companies we have acquired have interpreted and applied software revenue recognition rules differently than prescribed by U.S. GAAP, we could be required to devote significant management resources, and incur the expense associated with an audit, restatement or other examination of the acquired companies' financial statements." (verified) + OCF/NI 0.42x / -0.33x | BOILERPLATE_FALSE_POSITIVE (v3 exclusion list does not cover hypothetical acquired-company restatements) |
| SYNL | 20 | network Medium: CEO + CFO change in FY2010 | GENUINE events, off-mechanism; MECHANICAL grade |
| APKT | 30 | quant High: M -1.13 (SGI 2.33, LVGI 0.36; SGA missing, SGAI imputed) | MECHANICAL_ARTIFACT (IPO-year growth: the SGI term is 0.892 x 2.33 = 2.08 vs 0.89 at SGI=1, i.e. about +1.2 on M) |

## 4. Priority 4: the 13 v3 fraud misses, Beneish and availability gaps

Beneish status in v3 (stored `beneish_available`): available on 9 fraud cases (MNTX, SAEX, RVLT, HIL, PLUG, PSIX, RTIX, SABA, HEV). Focus-year M (my recompute from cached facts; v3 stored values in brackets where they differ): MNTX -3.15 (FY2014 -1.61 fired, FY2012 -1.65 fired), RVLT -4.04 (FY2015 -1.56 fired), HIL -2.96 [-2.93], PLUG -3.22, SABA -2.76, PSIX -1.757 fires, HEV -1.203 [-1.17] fires, SAEX -4.89 (meaningless, gross loss) [FY2016 -0.32 fired], RTIX -2.27.

### 4.1 Why the six "Beneish unavailable" cases are unavailable

| Case | Era | Missing input(s) as run | Cause (verified in text) | Counterfactual M (informal) |
|---|---|---|---|---|
| SMRT FY2011 | XBRL | NetReceivables | Stein Mart has no receivables line: balance sheet = Cash, Inventories, "Prepaid expenses and other current assets" (credit-card receivables presumably sit inside it; not verified). Structural: DSRI undefined. (LongTermDebt correctly imputed 0.) | not computable |
| SCOR FY2014 | XBRL | COGS, LongTermDebt | Statement has "Cost of revenues | 97,467 | 89,963" and "Equipment loan and capital lease obligations, long-term | $13,072 | $13,330" but no standard tag; per-item statement-table fallback did not fill them | -3.26, no fire |
| SWSH FY2010 | pre-XBRL | LongTermDebt | Balance sheet row is "Long term obligations | 31,028,992 | 32,029,841": label not recognised | -2.39, no fire (DSRI 1.27) |
| VOL FY2008 | pre-XBRL (.txt) | NetReceivables (and SGA) | Fixed-width legacy text: "Trade accounts receivable, net of allowances of $5,328 (2008) ...  488,482  392,970" not parsed | **-1.43, fires** (GMI 1.57, TATA 0.14, DSRI 1.21) |
| ISLN FY2006 | pre-XBRL | CurrentAssets, CurrentLiabilities, LTD, NetReceivables, PPE, TotalAssets for the prior year | first annual report after IPO: prior-year (FY2005) balance sheet absent; SGI 8.14 would dominate anyway | not computable |
| UNTK FY2011 | XBRL | NetReceivables | "Accounts receivable and unbilled revenue, net of allowances | 91,533 | 66,525" not matched by the tag list | -2.59, no fire (DSRI 1.27) |

So: 4 of 6 are tag / label gaps in the extraction layer despite v3's item-level fallback; 1 is structural (SMRT); 1 is a missing prior-year balance sheet (ISLN). Fixing all would add one extra Beneish fire (VOL), a real cost-of-gap of about 1 case in 15.

### 4.2 What the system saw / missed on each v3 miss

| Case | Saw | Missed | Why Beneish did or did not fire |
|---|---|---|---|
| MNTX | Altman Z' 1.11; stale Beneish fires FY2012/FY2014 (accruals 9.6%, DSO) | 2016 sales of 39 cranes (~$15M) to one broker; related-party JV inventory | FY2016 M -3.15 (DSRI 1.00, SGI 0.75): the 2016 misstatement does not distort annual ratios; earlier-year fires are in the SEC window but excluded by the escalation rule |
| RVLT | Altman, peer DSO 84 vs 48 days | backdated bill-and-hold | FY2017 M -4.04 (DSRI 0.74, TATA -0.28); FY2015 M -1.56 fired (in window) |
| HIL | real MW (accounts-receivable loss estimation, close process) | FX loss errors | M -2.93; not High because only network flags |
| PLUG | DSO +85% FY2018, new_legal, risk-factor +42% | lease / cost classification / loss accrual errors | M -3.22 (GMI 0.12 from a gross-profit swing) |
| PSIX | M -1.76 (just over), accruals | bill-and-hold ~$25M | fires but single agent |
| SCOR | exec turnover, Altman | contract manipulation ~$50M | M unavailable; counterfactual -3.26 |
| HEV | M -1.17, related party | impairment / related-party revenue | fires, grade rule caps at Medium |
| SABA | Altman Z' -0.51 | falsified time records (revenue timing) | M -2.76 (DSRI 1.11, AQI 1.13); peers pre-XBRL unavailable |
| SMRT | real MW on credit-card receivables | inventory markdown / liability errors | structural gap |
| SWSH | DSO +27.4%, Altman 0.64 (acquisition-year) | 2011 reserve / EBITDA entries (not FY2010) | gap; cf -2.39 |
| VOL | subsidiary revenue-recognition MW, accruals 14.4% | FY2007 subsidiary revenue overstatement ($7.55M) | gap; cf -1.43 would fire |
| ISLN | nothing | $4.8M side-deal revenue | gap |
| UNTK | related-party note growth, peer OCF/rev | Pinnacle premature revenue | gap; cf -2.59 |

Pattern: where a real, specific control or disclosure fact existed (SMRT, VOL, HIL, SAEX) it was found only by the network agent's material-weakness detector; the ratio agents see the mechanism only when it is large and sustained (HEV, SAEX).

## 5. Priority 5: paired suspicion scores (v3 stored; v1/v2 do not store scores)

| Pair (fraud vs control) | Scores | Result | Artifact-driven? |
|---|---|---|---|
| SAEX vs DWSN | 65 vs 0 | win | partly (AR reclass) but genuine concentration |
| RVLT vs LYTS | 35 vs 20 | win | weak: stale in-window Beneish vs CFO change; mostly genuine history |
| HIL vs EXPO | 20 vs 10 | win | genuine real MW vs a passive-voice flag |
| SMRT vs BKE | 10 vs 10 | tie | n/a |
| PLUG vs EAF | 45 vs 30 | win | weak; both driven by new_legal / language |
| PSIX vs KAI | 70 vs 20 | win | genuine (borderline) |
| RTIX vs INGN | 55 vs 0 | win | **artifact** (ASC 606 DSO, patent suit) |
| SCOR vs DHX | 45 vs 10 | win | weak: exec turnover + Altman |
| HEV vs RSTI | 80 vs 0 | win | genuine |
| SWSH vs SYNL | 35 vs 20 | win | acquisition-year DSO: mechanical |
| VOL vs AMN | 20 vs 10 | win | genuine (MW on revenue recognition) |
| UNTK vs SHEN | 45 vs 0 | win | unclear (related-party growth, wrong-peer OCF) |
| MNTX vs ACLS | 25 vs 55 | **loss** | artifact: ACLS ASU going-concern boilerplate; MNTX stale signals dropped |
| SABA vs LGTY | 25 vs 30 | **loss** | artifact: LGTY hypothetical restatement boilerplate; SABA no peers |
| ISLN vs APKT | 0 vs 30 | **loss** | artifact: APKT IPO-year SGI, ISLN data gap |

Totals 11W / 1T / 3L, sign test p=0.057 (14 non-tied), paired AUC 0.767 (bootstrap 95% CI 0.567-0.933). About 5 wins are genuine (SAEX, PSIX, HEV, VOL, HIL-small), 4 weak/mechanical (RTIX, SWSH, PLUG, SCOR), 2 unclear. All three losses are artifact/data-gap driven, i.e. they point at defects rather than at evidence that the controls are riskier.

## 6. Cross-cutting defects (descriptive; for the v4 backlog)

* D1 network going-concern / restatement matching still reads pronouncement or hypothetical text in v3: ACLS (ASU wording variant), SAEX FY2014/2017 going-concern, LGTY (acquired-company restatement), SMRT/VOL/HIL are the real ones.
* D2 current-AR-only metrics (SAEX): long-term receivables are invisible, current/LT reclassification moves DSO by 5x.
* D3 accounting-standard adoption effects (RTIX ASC 606) look like channel stuffing; no adoption-year awareness.
* D4 "Escalating" is triggered by any new non-peer flag with a higher score, so oscillating flags (Altman Z' near 1.23, CFO changes) make clean companies Medium (4 of 8 clean Mediums).
* D5 High needs 2+ agents; a single High agent grounded on a real mechanism (HEV, PSIX, SMRT, VOL) stays Medium.
* D6 Beneish availability: label / tag mapping gaps (VOL "Trade accounts receivable", SWSH "Long term obligations", UNTK "Accounts receivable and unbilled revenue", SCOR "Cost of revenues" and "Equipment loan ... long-term") survive v3's item fallback.
* D7 Beneish growth artifacts: APKT (IPO year SGI 2.33), HEV hyper-growth, SAEX gross loss (GMI -6.39).

## 7. v4 ideas (NOT validated; each must be validated on a new unseen set, no threshold changes proposed)

1. Treat total receivables (current + long-term + unbilled) as the DSO base and add a "single-customer receivable concentration" text feature (SAEX-type passages).
2. Extend the network exclusion list with hypothetical acquired-company restatement language and verbatim ASU 2014-15 variants; require disclosure verbs in the registrant's own voice.
3. Make escalation require persistence (a flag present in two consecutive years or magnitude-weighted) instead of any new flag.
4. Extend the label/row mapping for Beneish inputs (trade receivables, "long term obligations", unbilled receivables, cost of revenues exclusive of amortisation).
5. Flag accounting-standard adoption years (ASC 606 / 842) and suppress DSO growth when management attributes it to adoption.
6. Allow a single High agent to reach High only when its flags are mechanism-specific (material weakness over revenue / receivables in the registrant's own voice, or M above the cut with an explainable cause). Must be validated on a new unseen set because the DEV and H2 sets are now spent.

