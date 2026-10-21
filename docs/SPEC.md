# forensic-filing-agent — ORIGINAL SPEC (verbatim from the user)

> Read docs/CONTRACTS.md too: it records decisions/deviations from this spec that every module MUST follow.
> Where CONTRACTS.md and this file disagree, CONTRACTS.md wins (it is the reviewed, corrected version).

Build a production-quality multi-agent system called forensic-filing-agent.
This is a senior-level portfolio project targeting financial AI leads.
It must be genuinely rigorous — not a demo.
Where something is ambiguous, make the more production-quality choice.

## WHAT YOU ARE BUILDING

A six-agent LangGraph system that performs forensic analysis of public company SEC filings to detect accounting manipulation risk.

Three features make this different from every existing fraud detection tool:
1. Multi-signal independence — six specialist agents analyze the same filing from completely different angles with no information sharing between them
2. Temporal intelligence — tracks how signals CHANGE across 5 years, not just point-in-time scoring
3. Retrospective validation — an evaluation framework that backtests on known fraud cases and publishes precision/recall results. This is what separates serious work from a demo.

Plus a real-time watchlist that monitors new SEC filings and alerts when a watched company's risk score changes materially.

## FILE STRUCTURE

```
forensic-filing-agent/
├── README.md
├── requirements.txt
├── .env.example
├── app.py                       ← Streamlit multi-page UI
├── watchlist_monitor.py         ← Background scheduler entry point
├── agents/
│   ├── __init__.py
│   ├── state.py                 ← Shared LangGraph state
│   ├── quantitative_agent.py    ← Beneish, Altman, ratio analysis
│   ├── language_agent.py        ← NLP on MD&A text
│   ├── network_agent.py         ← Auditor, exec, restatement history
│   ├── peer_agent.py            ← SIC code peer comparison
│   ├── temporal_agent.py        ← Multi-year trend analysis
│   └── synthesis_agent.py       ← Jev scoring + final verdict
├── tools/
│   ├── __init__.py
│   ├── edgar_api.py             ← SEC EDGAR API wrappers
│   ├── xbrl_parser.py           ← XBRL financial data extraction
│   ├── text_parser.py           ← 10-K text + NLP extraction
│   ├── peer_finder.py           ← SIC peer lookup
│   ├── jev_scorer.py            ← Jev confidence scoring
│   └── financial_metrics.py     ← Beneish, Altman, ratio functions
├── graph/
│   ├── __init__.py
│   └── pipeline.py              ← LangGraph assembly
├── evaluation/
│   ├── __init__.py
│   ├── fraud_cases.py           ← Known fraud + clean company cases
│   ├── evaluator.py             ← Precision/recall computation
│   └── results/
│       └── evaluation_report.md ← Auto-generated report
├── watchlist/
│   ├── __init__.py
│   ├── manager.py               ← Add/remove/list companies
│   ├── scheduler.py             ← APScheduler monitoring
│   └── watchlist.db             ← SQLite persistent storage
├── prompts/
│   ├── __init__.py
│   └── templates.py             ← All system prompts
└── sample_analysis/
    ├── enron_2000.json
    ├── luckin_2019.json
    └── apple_2022.json          ← Clean company baseline
```

## TECH STACK

- Python 3.10+
- langgraph>=0.2.0, langchain>=0.3.0
- langchain-anthropic (Claude Haiku for routing/extraction, Sonnet for synthesis/language analysis)
- typesafe-ai (Jev — check typesafe.ai/docs for exact package)  [see CONTRACTS: real package is `typesafe-sdk`, import `typesafe_sdk`]
- streamlit>=1.35.0, plotly (temporal visualizations)
- pandas, numpy
- nltk + spacy (NLP for language forensics)
- apscheduler (watchlist background monitoring)
- requests, httpx (EDGAR API calls)
- beautifulsoup4 (HTML filing parsing)
- sqlite3 (built-in)
- python-dotenv, rich (terminal logging)

## SEC EDGAR API — FREE, NO AUTH NEEDED

All endpoints require header: "User-Agent: forensic-filing-agent contact@example.com"

- Company search by ticker: GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=10-K&dateb=&owner=include&count=10&search_text=&output=atom
- Company CIK lookup: GET https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=10-K
- Company submissions: GET https://data.sec.gov/submissions/CIK{cik_padded_to_10}.json
- XBRL facts: GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json — primary source for Beneish and Altman inputs.
- Individual filing index: GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/ — use the .htm or .txt file for full 10-K text.

Rate limit: 10 requests/second. Add time.sleep(0.1) between calls. Always handle 429 and 503 with exponential backoff.

## SHARED STATE — agents/state.py

ForensicAgentState as TypedDict:
```
# Input
ticker: str; company_name: str; cik: str
analysis_years: list[int]      # default last 5 fiscal years
# Raw data (fetched once, shared read-only)
xbrl_data: dict                # raw XBRL companyfacts response
filing_texts: dict             # {year: full 10-K text}
filing_metadata: dict          # {year: {auditor, cfo, ceo, date}}
peer_companies: list[dict]     # from peer_finder
# Agent outputs (populated in parallel)
quantitative_result, language_result, network_result, peer_result, temporal_result: dict
# Synthesis outputs
jev_scores: dict               # confidence per agent
risk_grade: str                # Low/Medium/High/Critical
smoking_guns: list[str]        # top 3 most specific findings
forensic_timeline: list[dict]  # {year, signals_fired, risk_level}
final_narrative: str
# Watchlist fields
watchlist_id: str; previous_risk_grade: str; risk_changed: bool
# Meta
agent_trace: list[dict]; analysis_timestamp: str; error: str
```

## FINANCIAL METRICS — tools/financial_metrics.py

Implement exactly. All inputs come from XBRL data.

BENEISH M-SCORE (8 variables), requires two consecutive years:
```
DSRI = (NetReceivables_t / Revenue_t) / (NetReceivables_t-1 / Revenue_t-1)
GMI  = ((Revenue_t-1 - COGS_t-1) / Revenue_t-1) / ((Revenue_t - COGS_t) / Revenue_t)
AQI  = (1 - (CurrentAssets_t + PPE_t) / TotalAssets_t) / (1 - (CurrentAssets_t-1 + PPE_t-1) / TotalAssets_t-1)
SGI  = Revenue_t / Revenue_t-1
DEPI = (Depreciation_t-1 / (PPE_t-1 + Depreciation_t-1)) / (Depreciation_t / (PPE_t + Depreciation_t))
SGAI = (SGA_t / Revenue_t) / (SGA_t-1 / Revenue_t-1)
LVGI = ((LongTermDebt_t + CurrentLiabilities_t) / TotalAssets_t) / ((LongTermDebt_t-1 + CurrentLiabilities_t-1) / TotalAssets_t-1)
TATA = (OperatingCashFlow_t - NetIncome_t) / TotalAssets_t     [SIGN ERROR IN SPEC — see CONTRACTS: use (NI - OCF)/TA]
M_SCORE = (-4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI)
```
Interpretation: M > -1.78 likely manipulator (HIGH); -2.22 < M < -1.78 grey zone (MEDIUM); M < -2.22 unlikely (LOW).

ALTMAN Z-SCORE (public companies):
```
X1 = WorkingCapital / TotalAssets; X2 = RetainedEarnings / TotalAssets; X3 = EBIT / TotalAssets
X4 = MarketCap / TotalLiabilities; X5 = Revenue / TotalAssets
Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
```
Zones: Z < 1.81 distress; 1.81–2.99 grey; Z > 2.99 safe.

REVENUE QUALITY RATIO: OperatingCashFlow / NetIncome; < 0.8 for two consecutive years = flag.
DSO: (AccountsReceivable / Revenue) * 365; flag if DSO grows > 20% YoY.
ACCRUALS RATIO: (NetIncome - OperatingCashFlow) / TotalAssets; > 0.05 = flag.

For every metric: handle missing XBRL tags gracefully. If a required tag is missing, mark that metric "unavailable" and explain which XBRL concept was not found. Never crash; never invent numbers.

## AGENT 1: QUANTITATIVE FORENSICS (agents/quantitative_agent.py)
Input: xbrl_data, analysis_years. Output: quantitative_result dict.
Steps: 1 extract figures per year; 2 Beneish for each consecutive pair; 3 Altman each year; 4 Revenue Quality, DSO, Accruals; 5 for each metric that flags, generate a specific plain-English explanation — not "M-Score is -1.2" but "Revenue grew 40% while receivables grew 90% in fiscal 2019 — a classic channel stuffing signal observed before revenue restatements"; 6 Claude Haiku for explanations.
```
{
  "beneish_scores": {year: {"score": float, "zone": str, "flag": bool, "explanation": str}},
  "altman_scores": {year: {"score": float, "zone": str}},
  "revenue_quality": {year: {"ratio": float, "flag": bool}},
  "dso_trend": {year: {"dso_days": float, "yoy_change_pct": float, "flag": bool}},
  "accruals_ratio": {year: {"ratio": float, "flag": bool}},
  "flags_fired": int, "highest_risk_year": int,
  "key_finding": str          # one sentence, most important signal
}
```

## AGENT 2: LANGUAGE FORENSICS (agents/language_agent.py)
Input: filing_texts (MD&A extracted), analysis_years. Output: language_result.
Extract MD&A: headers "Management's Discussion", "MD&A", "Results of Operations". Per year:
1. HEDGING WORD FREQUENCY — count: may, might, could, subject to, uncertain, contingent, approximately, estimated, believe, expect, intend, plan; normalize by word count → hedging_ratio; flag if increases > 25% YoY
2. PASSIVE VOICE % — spacy POS/dep tagging; flag if passive > 15% of sentences
3. RISK FACTOR DISCLOSURE LENGTH — char count of Risk Factors section; flag if grows > 40% YoY
4. SPECIFICITY SCORE — Claude Haiku: "Rate the specificity of this MD&A section from 1-10. High specificity means concrete numbers, named products, specific markets. Low specificity means vague language about 'macroeconomic conditions' and 'industry trends'. Return JSON: {score: int, reason: str}"; flag if score < 5 or drops > 2 points YoY
5. NEW LEGAL PROCEEDINGS — compare Legal Proceedings section YoY; flag if new proceedings appear
```
{
  "hedging_trend": {year: {"ratio": float, "flag": bool}},
  "passive_voice": {year: {"pct": float, "flag": bool}},
  "risk_factor_length": {year: {"chars": int, "yoy_change": float, "flag": bool}},
  "specificity_scores": {year: {"score": int, "reason": str, "flag": bool}},
  "new_legal_proceedings": {year: {"detected": bool, "text": str}},
  "flags_fired": int, "key_finding": str
}
```

## AGENT 3: NETWORK FORENSICS (agents/network_agent.py)
Input: filing_metadata, analysis_years. Output: network_result.
1. AUDITOR CHANGES — track auditor name YoY from filing; flag any change
2. CFO/CEO TURNOVER — from DEF 14A or 10-K signature sections; flag CFO change specifically (stronger than CEO)
3. AUDIT FEE TREND — from proxy or 10-K; flag if fees up > 30% YoY without corresponding revenue growth
4. PRIOR RESTATEMENTS — search text: "restate", "restatement", "material weakness", "significant deficiency"; flag any occurrence
5. RELATED PARTY TRANSACTIONS — track volume of RPT disclosures YoY; flag if section grows significantly
6. GOING CONCERN — "going concern", "substantial doubt", "ability to continue"; flag any occurrence
```
{
  "auditor_history": {year: {"name": str, "changed": bool}},
  "executive_changes": {year: {"cfo_changed": bool, "ceo_changed": bool}},
  "audit_fees": {year: {"amount": float, "yoy_change_pct": float, "flag": bool}},
  "restatements": {year: {"detected": bool, "text": str}},
  "related_party_flags": {year: {"detected": bool}},
  "going_concern": {year: {"detected": bool}},
  "flags_fired": int, "key_finding": str
}
```

## AGENT 4: PEER COMPARISON (agents/peer_agent.py)
Input: xbrl_data, peer_companies, analysis_years. For each peer fetch XBRL, compute same metrics. For the most recent year compute z = (M_company - mean(M_peers)) / std(M_peers); flag if |z| > 2.0.
Metrics: Gross Margin; DSO; Revenue Growth vs Receivables Growth; Operating Cash Flow / Revenue; Debt/Equity; Return on Assets.
```
{
  "peer_list": [{"ticker": str, "name": str}],
  "metric_zscores": {metric: {"z_score": float, "company_value": float, "peer_mean": float, "peer_std": float, "flag": bool, "interpretation": str}},
  "outlier_metrics": list[str], "flags_fired": int, "key_finding": str
}
```

## AGENT 5: TEMPORAL INTELLIGENCE (agents/temporal_agent.py)
Input: all four agent results across years. Per year raw "suspicion score" (0-100):
- each flag fired = +10; Beneish in manipulation zone = +20; Altman distress = +15; auditor change = +15; going concern = +25; CFO change = +10.
forensic_timeline: `[{"year", "suspicion_score", "flags_fired", "new_flags_this_year": list[str], "risk_level": "Low/Medium/High/Critical", "signal_change": "Escalating/Stable/Improving"}]`
Inflection point = first year where suspicion score crosses 40 AND signals are escalating (new flags appearing) → "first_detection_year".
```
{ "timeline": list[dict], "first_detection_year": int or None,
  "signal_trajectory": "Escalating/Stable/Improving/Volatile",
  "years_of_elevated_risk": int, "key_finding": str }
```

## JEV SCORING — tools/jev_scorer.py
Read TypeSafe AI docs (https://docs.typesafe.ai) first. For each agent's result, use Jev to score confidence. State = agent's key metrics and findings. Questions per agent:
1. "Is the quantitative evidence sufficient to flag manipulation risk?" choice: Insufficient/Suggestive/Strong/Definitive
2. "How confident are you in this agent's primary finding?" score (0-100)
3. "Does this evidence represent a material change from prior year?" boolean
Return per agent: `{"evidence_strength": str, "confidence_score": float, "material_change": bool, "jev_latency_ms": int}`

## AGENT 6: SYNTHESIS (agents/synthesis_agent.py)
Input: all five agent results + jev_scores. Claude Sonnet:
1. Read all five agent findings 2. Weight evidence by Jev confidence 3. risk_grade:
   - Critical: 3+ agents flagging High + Jev confidence > 80%
   - High: 2+ agents flagging + temporal escalation
   - Medium: 1-2 agents flagging + no temporal escalation
   - Low: no significant flags
4. 3 "smoking gun" highlights: "In FY{year}, {metric} showed {specific_value}, which is {X}% above the peer group average and consistent with {named_pattern} observed before {named_historical_case}."
5. final_narrative (3 paragraphs): overall assessment w/ evidence summary; most significant risk factors with specifics; what to watch — leading indicators for escalating or resolving.
Synthesis prompt must emphasize: NEVER invent financial figures. All specific numbers must come from the agent results passed to you. If evidence is ambiguous, say so. Distinguish between accounting manipulation risk and business distress risk — different failure modes requiring different flags.

## LANGGRAPH PIPELINE — graph/pipeline.py
Nodes: fetch_data; run_quantitative; run_language; run_network; run_peer; run_temporal (AFTER 1-4); run_synthesis (after temporal); handle_error.
Edges: START → fetch_data → [quant, language, network, peer] parallel fan-out → run_temporal (fan-in) → run_synthesis → END.
Use LangGraph parallel execution for agents 1-4. Compile with MemorySaver.
Export: `forensic_agent = pipeline.compile()` and `async def analyze_company(ticker: str, years: int = 5) -> ForensicAgentState`

## EVALUATION FRAMEWORK — evaluation/
FRAUD CASES (ground_truth = 1) — use the filing year BEFORE the fraud was publicly revealed:
```
ENRNQ cik 0001024401 analysis_year 2000 collapsed 2001 "Revenue inflation, SPE concealment"
WCOM  cik 0000723527 analysis_year 2001 collapsed 2002 "Capitalized expenses as assets"
LK    cik 0001767380 analysis_year 2019 collapsed 2020 "Fabricated sales transactions"
NKLA  cik 0001731289 analysis_year 2020 collapsed 2021 "False product capability claims"
RIDE  cik 0001759774 analysis_year 2020 collapsed 2021 "Inflated order book"
SPCE  cik 0001679273 analysis_year 2021 collapsed 2023 "Misleading safety disclosures"
```
CLEAN CASES (ground_truth = 0), all analysis_year 2020, label "Clean":
```
AAPL 0000320193; MSFT 0000789019; JNJ 0000200406; PG 0000080424; BRK-B 0001067983; MMM 0000066740
```
EVALUATOR `run_evaluation() -> dict`: for each case run analyze_company for the specified year; record risk_grade, first_detection_year, which agents fired flags. Positive prediction: risk_grade in [High, Critical].
Compute TP/FP/TN/FN; precision = TP/(TP+FP); recall = TP/(TP+FN); f1; false_positive_rate = FP/(FP+TN).
Per-agent contribution: for each agent what % of fraud cases did it flag that were missed by other agents.
Detection timing: for correctly detected fraud cases, months before the collapse the system first flagged it (first_detection_year vs collapsed_year).
Generate evaluation/results/evaluation_report.md with all results. Return full metrics dict.

## WATCHLIST — watchlist/
```sql
CREATE TABLE watchlist (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL UNIQUE, company_name TEXT, cik TEXT, added_date TEXT, last_analyzed TEXT, last_risk_grade TEXT, alert_threshold TEXT DEFAULT 'Medium', active INTEGER DEFAULT 1);
CREATE TABLE risk_history (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, analysis_date TEXT, risk_grade TEXT, flags_fired INTEGER, smoking_gun_1 TEXT, suspicion_score INTEGER);
CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, alert_date TEXT, previous_grade TEXT, new_grade TEXT, trigger_reason TEXT, acknowledged INTEGER DEFAULT 0);
```
SCHEDULER (watchlist/scheduler.py): APScheduler BackgroundScheduler. Job run_watchlist_check() every 24 hours. For each active company: 1 check EDGAR for new 10-K since last_analyzed; 2 if new filing: run full analysis; 3 compare new risk_grade to last_risk_grade; 4 if worsened (Low→Medium, Medium→High): insert into alerts, set risk_changed = True; 5 update last_analyzed and last_risk_grade. If analysis fails for one company log the error and continue — never crash the scheduler.

## STREAMLIT UI — app.py (three pages, sidebar navigation)
PAGE 1 FORENSIC ANALYSIS. Header "Forensic Filing Intelligence Agent"; subtitle "Multi-agent SEC filing analysis powered by LangGraph + Claude + Jev". Inputs: text input ticker ("Enter ticker symbol (e.g. AAPL, ENRNQ)"); number input "Years to analyze" (default 5, max 10); large red button "Run Forensic Analysis". While running animated agent-by-agent status:
"🔍 Fetching SEC EDGAR data..." "📊 Running quantitative forensics..." "📝 Analyzing filing language..." "🔗 Checking auditor and executive history..." "👥 Comparing against peer group..." "📈 Building temporal intelligence..." "⚡ Running Jev confidence scoring..." "🧠 Synthesizing final verdict..."
Results: TOP large risk grade badge (Critical red, High orange, Medium yellow, Low green); three "smoking gun" red callout boxes ([icon] [specific finding in bold]); FORENSIC TIMELINE Plotly chart (x years, y suspicion 0-100, color zones green 0-30 / yellow 30-60 / orange 60-80 / red 80-100, annotation markers where flags fired — the LinkedIn screenshot visual); TABS per agent: 1 Quantitative (Beneish/Altman charts, ratio trends, flags table) 2 Language (hedging trend chart, specificity scores, notable excerpts) 3 Network (auditor history table, exec changes, fee trend) 4 Peer (radar chart company vs peers on all metrics) 5 Temporal (timeline detail, first detection year callout). JEV CONFIDENCE SIDEBAR: per agent evidence strength badge, confidence progress bar, material change indicator.
PAGE 2 WATCHLIST. Header "Filing Watchlist — Real-Time Risk Monitor". Add company: ticker input + alert threshold dropdown (Low/Medium/High/Critical) + "Add to Watchlist". Table columns Company | Risk Grade | Last Analyzed | Flags Fired | Trend | Actions; color-coded grade; trend ↑ escalating → stable ↓ improving; Actions Run Now | Remove | View History. Unacknowledged alerts: "⚠️ {Company} risk elevated from {previous} to {current} on {date}" with Acknowledge button. Risk history chart: select company → Plotly line of suspicion score over analysis dates.
PAGE 3 RETROSPECTIVE VALIDATION. Header "Backtesting Results — Known Fraud vs Clean Companies". Description: "The evaluation framework that separates a serious tool from a demo. Results on 12 SEC filings from known fraud cases and matched clean companies." Run Evaluation button (~10-15 min), per-company progress. After: HEADLINE METRICS cards (Precision, Recall, F1, False Positive Rate); DETECTION TIMING chart (months before collapse first flagged; "Average detection: X months before public revelation"); AGENT CONTRIBUTION chart; CASE-BY-CASE TABLE (Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal). Disclaimer: "This evaluation uses publicly available SEC filings. Past detection performance does not guarantee future accuracy. This tool is for research purposes and does not constitute investment advice."

## .ENV.EXAMPLE
```
ANTHROPIC_API_KEY=your_anthropic_api_key
JEV_API_KEY=your_jev_api_key
SEC_USER_AGENT=forensic-filing-agent your@email.com
WATCHLIST_CHECK_INTERVAL_HOURS=24
```

## README.md (written last, exceptional)
1 One-line: "Six-agent forensic analysis of SEC filings with retrospective validation on known fraud cases"; 2 Live demo badge (Streamlit Cloud); 3 ASCII architecture diagram (6 agents + temporal + synthesis + Jev layer); 4 evaluation results (centerpiece, fill AFTER backtests); 5 Why different (3 differentiators); 6 Detection timing "Flagged Enron X months before collapse" — REAL numbers only; 7 Quick start (4 commands); 8 agent table; 9 data sources; 10 Limitations (false positives, what it cannot detect, survivorship bias); 11 tech badges.

## QUALITY BAR
- All financial calculations mathematically correct; verify Beneish and Altman against published formulas.
- EDGAR calls handle rate limits, 404s, missing data. Never crash on a missing XBRL tag.
- Evaluation must produce honest results. If precision is 60%, report 60%. Do not cherry-pick cases.
- Jev failures must never crash the pipeline.
- Streamlit app must launch cleanly: streamlit run app.py
- All sample analyses in sample_analysis/ must complete without errors.

## EXECUTION ORDER
1 tools/edgar_api.py + xbrl_parser.py → verify EDGAR works for AAPL; 2 financial_metrics.py → verify Beneish on Enron 2000 (expect manipulation zone); 3 quantitative_agent → test AAPL (clean) and LK 2019 (should flag); 4 language/network/peer agents independently; 5 pipeline → verify parallel; 6 synthesis + jev_scorer → full run on LK 2019; 7 evaluator → all 12 cases; 8 watchlist add/remove/check cycle; 9 app.py; 10 README with real numbers.

When complete show: 1 Beneish M-Score for Luckin Coffee 2019; 2 full forensic analysis output for Enron 2000; 3 precision/recall/F1; 4 detection timing per fraud case; 5 confirmation streamlit run app.py launches cleanly.
