# CONTRACTS — binding decisions, deviations and module interfaces

Every agent/engineer building this project MUST follow this file. It overrides docs/SPEC.md where they differ.
Project root: `C:\Users\Utsav.Sharma\source\forensic-filing-agent` (Windows, Python 3.14, run everything from the root,
`python -m pytest`, imports are root-relative: `from tools.edgar_api import ...`). Use `pathlib`, UTF-8 everywhere
(`encoding="utf-8"` on every open; avoid emoji in anything printed to a Windows console except inside Streamlit).
Installed already: langgraph 1.2.x, langchain 1.3.x, langchain-anthropic, anthropic, httpx, pandas 3, plotly, streamlit 1.60,
typesafe-sdk 0.7.2. Others (spacy, nltk, apscheduler, beautifulsoup4, lxml, python-dotenv, rich, pytest, requests, numpy)
may need `pip install`; `python -m spacy download en_core_web_sm` for the model (handle absence gracefully: fall back to a
rule-based passive-voice detector and say so in `degraded`).

## 0. Honesty rules (non-negotiable)
1. NEVER invent or hand-key financial numbers. Numbers come from XBRL, from parsed filing tables (with a provenance row label),
   or are `unavailable`. Test fixtures must be fetched from EDGAR, not typed from memory.
2. NO threshold tuning on the 12 evaluation cases. All thresholds/severity rules are fixed from the spec / published literature
   BEFORE the evaluation is run. If you want to change a rule after seeing evaluation output, you must not; report the result.
3. Missing key (`ANTHROPIC_API_KEY` / `JEV_API_KEY`) is a normal state, not an error. Every LLM/Jev step has a deterministic
   fallback and records it in the result's `degraded` list (e.g. `"llm_explanations: ANTHROPIC_API_KEY not set"`). Degraded
   runs are labelled as such everywhere (UI badge, evaluation report). Never fabricate a Jev score or an LLM answer.
4. Anything you could not verify, say so in your final report. Do not claim a test passed unless you ran it.
5. Look-ahead bias is a bug. Point-in-time (`as_of`) filtering is mandatory in data access (see §3).

## 1. Deviations from the spec (decided; implement these)
- D1 Jev package: the real package is `typesafe-sdk` (import `typesafe_sdk`); `typesafe-ai` on PyPI is a redirect shim; the URL
  typesafe.ai/docs is 404 — docs live at https://docs.typesafe.ai/sdk/python. API key: `JEV_API_KEY` (pass `api_key=` explicitly;
  SDK default env is `TYPESAFE_API_KEY`; accept either). Question types: `Noul` (boolean; answer `.noul` is P(yes) float),
  `Choice(criteria={label: description})` (answer `.choice`, `.confidence`, `.probabilities`), `Score(criteria=[ordered rubric])`
  (answer `.score` float = expected rubric position, `.confidence`, `.legend`, `.probabilities`). Response: `response.answers[name]`.
  Spec's "score 0-100" is implemented as a 5-level ordered rubric normalized to 0-100 from the legend keys.
- D2 Beneish TATA sign: spec writes (OCF − NI)/TA which inverts the signal given the +4.679 coefficient. Beneish (1999) defines
  total accruals; implement TATA = (NetIncome − OperatingCashFlow)/TotalAssets. Record this in the docstring and README.
  (Accruals ratio flag uses the same (NI − OCF)/TA > 0.05 as spec.)
- D3 Altman X4 needs market cap (not in EDGAR). If `market_cap` is supplied use original Z (zones 1.81/2.99). Otherwise use the
  Z′ book-equity variant: Z′ = 0.717·X1 + 0.847·X2 + 3.107·X3 + 0.420·(BookEquity/TotalLiabilities) + 0.998·X5, zones
  distress < 1.23, grey 1.23–2.90, safe > 2.90. Every Altman result carries `"variant"`; never mix variants within one analysis.
- D4 Pre-XBRL filers (before ~2009: Enron FY2000, WorldCom FY2001): no companyfacts exist. `tools/statement_parser.py` extracts
  the canonical line items from the filing's own financial-statement tables (deterministic label-matching over BeautifulSoup /
  text tables, identity-validated: Assets ≈ Liabilities + Equity, etc.; each value keeps its source row label). If it cannot
  extract an item it is `unavailable`. An optional Haiku-based fallback may be added but every number it returns must be
  verified to appear verbatim in the source text; otherwise discarded.
- D5 Form types: support 10-K, 10-K405, 10-KSB (small), 20-F, 40-F annual reports. Amendments (/A) excluded unless asked.
- D6 `analyze_company(ticker, years=5, *, cik=None, end_year=None, as_of=None, thread_id=None, progress_callback=None,
  previous_risk_grade=None, watchlist_id=None)`. `end_year`= last fiscal year to analyze (default: latest filed as of `as_of`).
  `as_of` = ISO date; nothing filed after it may be used (point-in-time). Delisted tickers (ENRNQ) need `cik=`.
- D7 `state["xbrl_data"]` is a compact companyfacts (only concepts in CANONICAL_CONCEPTS + dei), not the 10+MB raw dump, so
  LangGraph checkpoints stay small. Keep `entityName`, `cik`. Full raw JSON stays in the disk cache.
- D8 Jev scoring is a sub-step inside `run_synthesis` (progress event `"jev"`), not a separate graph node.
- D9 Risk grade is computed by deterministic, auditable rules (§6); Claude Sonnet writes narrative/smoking guns only and its
  numbers are validated against the evidence (§6). Rules are frozen before evaluation.
- D10 Spec says 6 sample analyses but lists 3 files; generate the 3 listed (`enron_2000`, `luckin_2019`, `apple_2022`) and note it.
- D11 Evaluation case metadata is verified against EDGAR/news and may CORRECT the spec's CIKs/years (record `spec_*` originals
  and `corrected: true` + reason). Cases whose analysed 10-K/20-F was filed AFTER the fraud became public are flagged
  `pre_revelation_valid=False`; they stay in the headline (spec) evaluation but a strict point-in-time sensitivity run is
  also reported. Never silently drop or swap a case.
- D12 Fiscal year of a filing = SEC `fy`/DocumentFiscalYearFocus when available else year(period end) (period ending in January →
  prior year). Annual duration facts: 350–380 days. Balance-sheet facts: instant at fiscal period end.
- D13 `/Date` handling: all dates ISO `YYYY-MM-DD` strings in dicts/state; `datetime.date` only internally.
- D14 Months-before-collapse = whole+fractional months between the FILING DATE of the first-detection filing and the case's
  `public_revelation_date` (also report to `collapse_date`). Annual data means timing is quantized to filing dates; say so.

## 2. Canonical financial line items (shared vocabulary for xbrl_parser, statement_parser, financial_metrics, agents)
`Revenue, COGS, GrossProfit, SGA, NetIncome, OperatingIncome, InterestExpense, IncomeTaxExpense, OperatingCashFlow,
Depreciation (D&A from cash-flow statement), TotalAssets, CurrentAssets, CurrentLiabilities, TotalLiabilities, NetReceivables,
PPE (net), LongTermDebt (non-current portion), CurrentDebt, RetainedEarnings, StockholdersEquity, CashAndEquivalents,
SharesOutstanding, AuditFees(not XBRL; from text)`. A flattened year dict is `{canonical: float|None}`.
A FactValue is `{"value": float, "tag": str, "unit": str, "form": str, "filed": "YYYY-MM-DD", "accn": str, "start": str|None,
"end": str, "derived": bool, "source": "xbrl"|"statement-table"|"derived"}` (`tag` = XBRL concept or table row label or
`"derived:Revenue-GrossProfit"`).
`AnnualFacts = {"by_year": {int: {canonical: FactValue}}, "missing": {int: {canonical: "tried tags [...]; none present in
filings filed by <as_of>"}}, "period_end": {int: "YYYY-MM-DD"}, "source_by_year": {int: "xbrl"|"statement-table"|"mixed"|"none"},
"unit": str, "warnings": [str]}`.

## 3. Module interfaces

### tools/common.py (foundation)
`get_logger(name)` (rich handler), `MODEL_HAIKU="claude-haiku-4-5-20251001"`, `MODEL_SONNET="claude-sonnet-5-5"`,
`load_env()` (dotenv, idempotent), `PROJECT_ROOT`, `CACHE_DIR` (`.cache/`), `ISO(d)`, `parse_date(s)`, `flatten_year(facts_for_year)->{canon: float|None}`,
`RISK_ORDER=["Low","Medium","High","Critical"]`, `risk_rank(grade)->int`, `safe_div(a,b)->float|None`.

### tools/llm.py (foundation)
`llm_available() -> bool`; `llm_json(tier: "haiku"|"sonnet", system: str, user: str, *, max_tokens=800) -> dict | None`
(temperature 0, JSON parse with repair, 2 retries, disk-cached by sha256(model+system+user) under `.cache/llm/` so reruns are
deterministic; returns None on any failure/no key and never raises); `llm_text(tier, system, user, max_tokens=1500) -> str | None`.
Uses `langchain_anthropic.ChatAnthropic`.

### tools/edgar_api.py (foundation)
Class `EdgarClient` (singleton `get_client()`): global rate limiter (≤ 8 req/s across threads), `User-Agent` from `SEC_USER_AGENT`
env (warn if it is the placeholder), exponential backoff + `Retry-After` on 429/503/5xx/connection errors (max 6 tries), on-disk
cache `.cache/edgar/` (JSON/text; submissions & index TTL 6h, immutable archive documents forever; companyfacts TTL 24h),
`get_json(url)`, `get_text(url)`, `get_bytes(url)`. Exceptions: `EdgarNotFound` (404), `EdgarError`.
Functions: `pad_cik(cik)->10-digit str`; `resolve_company(ticker_or_cik, cik=None) -> {"ticker","cik","name","sic","sic_description",
"fiscal_year_end","exchanges","former_names"}` (uses sec.gov/files/company_tickers.json, submissions; explicit cik for delisted);
`get_submissions(cik)` (merges the older paginated `filings.files` pages); `list_annual_filings(cik, as_of=None, forms=ANNUAL_FORMS)
-> list[Filing]` newest first, `Filing={"accession","form","filing_date","report_date","fiscal_year","primary_document",
"index_url","document_url"}` (only filed ≤ as_of); `list_filings(cik, forms, as_of)` (e.g. DEF 14A); `get_companyfacts(cik)
-> dict` ({} for 404/pre-XBRL, never raises for 404); `fetch_filing_text(filing_or_url, max_chars=None) -> str` (HTML → clean
text; tables rendered one row per line with ` | ` separators; pre-2001 `.txt` returned as-is, `<PAGE>` handled; for old
submissions fall back to the complete submission `.txt` `{accession}.txt`); `fetch_filing_html(filing) -> str`;
`find_company_by_sic(sic, limit)` (HTML/atom browse-edgar listing by SIC for peer discovery).

### tools/xbrl_parser.py (foundation)
`CANONICAL_CONCEPTS: dict[str, list[str]]` ordered candidate tags (us-gaap, ifrs-full, legacy names like SalesRevenueNet;
Revenue includes `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, ...).
`compact_companyfacts(raw) -> dict` (D7). `extract_annual_facts(companyfacts, years, as_of=None, basis="as_originally_reported")
-> AnnualFacts` — for each fiscal year pick, per canonical item, the first candidate tag with a FY-duration fact for that period
filed ≤ as_of; `basis="as_originally_reported"` takes the value from the annual filing for that fiscal year (not later restated
comparatives); choose one unit consistently (most coverage); derive items only via documented identities (COGS=Revenue−GrossProfit,
TotalLiabilities=Assets−Equity when no minority/mezzanine ambiguity, EBIT-proxy) flagged `derived`. Missing → entry in
`missing` with the tags tried. `get_annual_facts(cik, years, as_of=None, companyfacts=None) -> AnnualFacts` = facade: XBRL for
years it covers, else `statement_parser` per year (source_by_year records which). `available_years(cik, as_of)`.

### tools/statement_parser.py (legacy path)
`extract_statements(text_or_html, fiscal_year, form) -> {"values": {canonical: FactValue}, "missing": {...}, "checks": {"balance_identity": bool, ...}, "warnings": []}`.
Tested against real Enron FY2000 10-K and WorldCom FY2001 10-K (fetched from EDGAR). Prior-year comparatives in the same filing
may be used to fill year t−1 (flag `source` accordingly).

### tools/financial_metrics.py
Pure functions over flattened year dicts (`{canonical: float|None}`); no I/O. Every function returns a dict containing at least
`{"status": "ok"|"unavailable"|"not_meaningful", "missing": [canonical names or XBRL concepts not found], "explanation": str}`.
`beneish_m_score(cur, prev, impute_neutral=("SGAI","DEPI")) -> {"status","m_score","components":{DSRI,GMI,AQI,SGI,DEPI,SGAI,TATA,LVGI},
"imputed":[...],"zone":"manipulator|grey|unlikely","flag_level":"HIGH|MEDIUM|LOW","flag":bool(M>-1.78),"missing":[...],"inputs":{...}}`
(imputed neutral =1.0 only for SGAI/DEPI and always reported; never for the other six; any non-imputable gap → unavailable).
`altman_z(cur, market_cap=None) -> {"status","score","zone","variant","components","missing"}`;
`revenue_quality(cur, prev) -> {"ratio","flag","consecutive_low"}` (flag when OCF/NI < 0.8 for two consecutive years: needs both years;
NI ≤ 0 → status "not_meaningful", no flag); `dso(cur, prev)`; `accruals_ratio(cur)`; plus peer-agent ratios `gross_margin, ocf_to_revenue,
debt_to_equity, roa, receivables_vs_revenue_growth(cur, prev)`; `flatten`-friendly. Division by zero/None → unavailable, never raise, never NaN in output.
Unit tests in `tests/test_financial_metrics.py` incl. Beneish (1999) sample-mean sanity check (verify the published table via web search before using).

### tools/text_parser.py
`extract_sections(text, form) -> {"mdna","risk_factors","legal_proceedings","related_party","item9_changes","item14","signatures","notes_rpt"}` (strings, "" if
not found, plus `"found": {section: bool}` and `"method"`), robust to 10-K405/old .txt and modern iXBRL HTML text. `extract_auditor(text) -> str|None`
(normalized firm name: "Arthur Andersen LLP", "PricewaterhouseCoopers LLP", "Ernst & Young Hua Ming LLP"...), `extract_signatories(text) -> {"ceo":str|None,"cfo":str|None}`,
`extract_audit_fees(text) -> {"audit_fees": float|None, "total_fees": float|None, "year": int|None, "source_excerpt": str}|None`,
`keyword_hits(text, patterns, negations=True) -> [{"pattern","excerpt","negated":bool}]` (negation/boilerplate aware: "no material weakness", "did not identify",
"restated to conform to current presentation" are NOT restatement signals), `build_filing_metadata(filing, text, proxy_text=None) -> dict`
(`{"auditor","ceo","cfo","filing_date","form","accession","audit_fees","audit_fee_source","related_party_chars","signatures_found"}`).

### tools/peer_finder.py
`find_peers(cik, sic=None, as_of=None, focus_year=None, n=8, size_band=(0.1,10)) -> list[{"ticker","name","cik","sic","assets": float|None}]`
(same 4-digit SIC, else 3-digit; excludes the company; requires XBRL annual facts for focus_year as of as_of; size-matched on TotalAssets;
returns [] with reason when pre-XBRL).

### tools/jev_scorer.py
`score_agents(agent_results: dict[str, dict], prior_year_results: dict|None=None) -> dict[str, JevScore]` where
`JevScore={"evidence_strength": "Insufficient|Suggestive|Strong|Definitive|Unavailable","confidence_score": float|None (0-100),
"material_change": bool|None,"jev_latency_ms": int,"available": bool,"error": str|None,"model": str|None}`. One Jev `system_one` call per agent (3 questions:
choice / score / noul), compact JSON state (agent key metrics, flags, key_finding, flags_by_year), `RetryPolicy` bounded, timeout ≤ 20s, runs
agents concurrently (thread pool), NEVER raises (every failure → `available=False`). Unit-tested with mocked `SystemOneResponse`; live-tested only if `JEV_API_KEY` set.

### agents/state.py
`ForensicAgentState` TypedDict per spec PLUS: `as_of: str`, `focus_year: int`, `filings: list[dict]`, `degraded: list[str]`, `warnings: list[str]`,
`jev_available: bool`, `agent_severity: dict`, `smoking_gun_evidence: list[dict]`, `suspicion_score: int`, `first_detection_year: int|None`,
`first_detection_filing_date: str|None`. `agent_trace` uses `Annotated[list, operator.add]`, `degraded`/`warnings` too. Helpers: `new_state(...)`, `to_jsonable(state)` (int keys → str),
`from_jsonable`.

## 4. Agent contracts (agents 1-4 are INDEPENDENT: they read only raw state fields, never each other's results)
Signature: `def run_<name>(state: ForensicAgentState) -> dict` returns a partial state update:
`{"<name>_result": result, "agent_trace": [{"agent","status","started","duration_ms","summary","degraded":[...]}], "degraded": [...]}`; sync functions (pipeline wraps in `asyncio.to_thread`).
Never raise: on internal failure return a result `{"error": str, "unavailable": True, "severity": "None", "flags_fired": 0, "flags_by_year": {}, "key_finding": "<agent> unavailable: ..."}`.
Every result contains (beyond the spec's structure): `severity` ∈ {"None","Low","Medium","High"}, `flags_by_year: {int: [flag_name]}`, `focus_year`, `data_quality: {"unavailable": {metric: reason}}`, `degraded: [str]`.
Flag names (fixed vocabulary, used by temporal agent weights): quantitative: `quantitative.beneish` (HIGH zone only; grey zone is recorded, not flagged), `quantitative.altman_distress`, `quantitative.revenue_quality`, `quantitative.dso_growth`, `quantitative.accruals`;
language: `language.hedging`, `language.passive_voice`, `language.risk_factor_growth`, `language.specificity`, `language.new_legal`; network: `network.auditor_change`, `network.cfo_change`, `network.ceo_change` (recorded; counts as signal but weight 0 in temporal score — spec only scores CFO), `network.audit_fees`, `network.restatement`, `network.related_party`, `network.going_concern`; peer: `peer.<metric>` (focus year only).
`flags_fired` = total count of flags across ALL analysed years (spec output), while severity uses FOCUS-year flags only:
- severity High: a "hard" flag in focus year OR ≥3 flags in focus year; Medium: 2 flags; Low: 1 flag; None: 0.
  Hard flags: `quantitative.beneish`, `network.going_concern`, `network.restatement` (non-negated, restating previously issued financials or reporting a material weakness), (`network.auditor_change` AND `network.cfo_change` same year), `peer` ≥3 outliers.
- An agent is "flagging" when severity ∈ {Medium, High}.
Language agent: LLM specificity needs a key; without key → `specificity_scores[year] = {"score": None, "reason": "unavailable: no ANTHROPIC_API_KEY", "flag": False}` and `degraded` gets an entry. MD&A text sent to the LLM truncated to ≤ 12k chars, deterministic cache.
Quantitative: explanations from Haiku when available else deterministic template built from the numbers (e.g. "Receivables grew X% while revenue grew Y% in fiscal Z"), numbers always computed in code, never by the LLM.
Network: negation-aware keyword searching; auditor/CFO changes use name normalisation (case, punctuation, "LLP", "Inc."); proxy (DEF 14A) text fetched in fetch_data for audit fees when the 10-K incorporates Item 14 by reference.
Peer: needs `peer_companies`; pre-XBRL or no peers → `{"unavailable": True, ...}`; z-scores use sample std (ddof=1), require ≥3 peers with the metric, flag |z|>2.0.
Temporal (agent 5, after 1-4): `run_temporal(state)` reads the four results' `flags_by_year`, Beneish/Altman zones, auditor/CFO/going-concern; applies spec weights, caps 100; risk_level thresholds Low 0–29, Medium 30–59, High 60–79, Critical ≥80;
`signal_change` = Escalating if ≥1 new flag vs prior year and score rose, Improving if score fell ≥10 or flags fell, else Stable; `first_detection_year` = first year with score ≥ 40 AND Escalating; trajectory over the series (Volatile if direction changes ≥2 times with amplitude ≥20).
Also outputs `first_detection_filing_date`.

## 5. Pipeline (graph/pipeline.py)
Nodes: `fetch_data`, `run_quantitative`, `run_language`, `run_network`, `run_peer`, `run_temporal`, `run_synthesis`, `handle_error`. Fan-out from fetch_data to the four agents (LangGraph parallel supersteps; each node runs its sync agent via `asyncio.to_thread` so IO truly overlaps), fan-in to `run_temporal`, then `run_synthesis` → END. Conditional edge after fetch_data to `handle_error` on fatal error (no filings/company not found). Failures inside agents 1-4 never abort the graph (§4). `progress_callback(event: dict)` receives `{"node","status":"start|done|error","message"}` (+ `"jev"` sub-event). Export `pipeline` (StateGraph), `forensic_agent = pipeline.compile(checkpointer=MemorySaver())`, `async def analyze_company(...)` (D6).
fetch_data: resolve company → list annual filings ≤ as_of → choose fiscal years (the `years` most recent ending at `end_year`; fetch one extra year before for YoY math) → companyfacts → `get_annual_facts` → filing texts (annual 10-K/20-F per year) + DEF 14A text where needed → filing_metadata → peers. Fetch texts concurrently (≤ 4 workers) respecting the rate limiter.

## 6. Synthesis rules (frozen; agents/synthesis_agent.py)
Per-agent severity from §4. `agents_flagging = #agents (1-4 + temporal? NO: only agents 1-4) with severity ∈ {Medium, High}`; `agents_high = # with severity High`. `escalation = temporal focus-year signal_change == "Escalating" or temporal.signal_trajectory == "Escalating"`.
- Critical: agents_high ≥ 3 AND mean Jev confidence (available agents) > 80. If Jev unavailable Critical is not reachable: cap at High and add `"critical_blocked: Jev unavailable"` to `degraded`.
- High: (agents_flagging ≥ 2 AND escalation) OR (agents_high ≥ 3).
- Medium: agents_flagging ≥ 1 (and not High/Critical) OR (escalation with ≥1 flagged year).
- Low: otherwise.
Jev weights the *narrative emphasis/ranking of smoking guns* and is reported; it does not alter grade except the Critical gate. Smoking guns: ranked findings from structured evidence (`smoking_gun_evidence` items `{agent, flag, year, metric, value, peer_pct?, text}`); LLM (Sonnet) only phrases them; every number in LLM text must appear in the evidence JSON (regex check on numerals) else the deterministic template text is used and `degraded` notes `"narrative: deterministic fallback (numeric validation failed / no key)"`. Template: "In FY{year}, {metric} showed {value}[, which is {X}% above/below the peer group average]{ and consistent with {pattern} observed before {historical_case}}" — pattern→case mapping lives in prompts/templates.py as a reviewed table with a source note for each; only well-documented cases (WorldCom 2002 capitalised line costs, Sunbeam 1998 channel stuffing, Enron 2001 SPE/related-party, Luckin 2020 fabricated sales...). Final narrative 3 paragraphs; synthesis prompt must carry the NEVER-INVENT and manipulation-vs-distress rules from the spec.

## 7. Evaluation (evaluation/)
`fraud_cases.py`: `FRAUD_CASES`, `CLEAN_CASES`, `ALL_CASES` with fields `{ticker, cik, spec_cik, spec_analysis_year, analysis_year, collapsed_year, collapse_date, public_revelation_date, ground_truth, fraud_type, form_type, analysis_filing_date, pre_revelation_valid, validity_note, corrected: bool, correction_reason, sources:[urls], label}`; `as_of` for a spec run = analysis filing date (information set through that filing).
`evaluator.py`: `run_evaluation(mode="spec", cases=None, progress_callback=None, use_cache=True) -> dict` (`mode` ∈ spec|strict|both); confusion matrix, precision/recall/F1/FPR **with Wilson 95% CIs** (undefined → None, never divide by zero), per-agent contribution (unique-catch % per spec), detection timing (D14), baselines (Beneish-only M>−1.78; "always clean"), per-case rows (predicted, actual, grade, first_detection_year, agents flagging, key signal, degraded components, errors), run metadata (timestamp, git-free code hash of rule files, keys-available flags), writes `evaluation/results/evaluation_report.md` + `evaluation/results/evaluation_results.json`. A case that errors is reported as ERROR and excluded from the confusion matrix with the exclusion stated (never silently counted as negative). CLI: `python -m evaluation.evaluator [--mode spec|strict|both] [--cases AAPL,LK]`.

## 8. Watchlist
`watchlist/manager.py`: `init_db(path=None)` (path from `WATCHLIST_DB_PATH`, default `watchlist/watchlist.db`; schemas exactly as spec), `add_company(ticker, alert_threshold="Medium")`, `remove_company`, `set_active`, `list_companies() -> list[dict]` (joined with latest risk_history), `record_analysis(ticker, state)`, `get_risk_history(ticker)`, `list_alerts(unacknowledged_only=True)`, `create_alert(...)`, `acknowledge_alert(id)`.
`watchlist/scheduler.py`: `run_watchlist_check(force=False, db_path=None) -> list[dict]` per-company results; new filing = annual filing with filing_date > last_analyzed; alert only if grade worsened (risk_rank up) AND new grade rank ≥ alert_threshold rank; per-company try/except; `start_scheduler()` BackgroundScheduler (interval `WATCHLIST_CHECK_INTERVAL_HOURS`, default 24, `max_instances=1`, `coalesce=True`). `watchlist_monitor.py` CLI (`--once`, `--force`).

## 9. Ownership (one writer per file; do not edit files you don't own — message via your final report)
Foundation-A: requirements.txt, .env.example, .gitignore, pytest.ini, tools/__init__.py, tools/common.py, tools/llm.py, tools/edgar_api.py, tools/xbrl_parser.py, agents/__init__.py, agents/state.py, graph/__init__.py, prompts/__init__.py, evaluation/__init__.py, watchlist/__init__.py, tests/conftest.py.
Metrics: tools/financial_metrics.py, tests/test_financial_metrics.py. Cases: evaluation/fraud_cases.py, docs/case_research.md. Legacy: tools/statement_parser.py, tests/test_statement_parser.py.
Text: tools/text_parser.py, tests/test_text_parser.py. Jev: tools/jev_scorer.py, tests/test_jev_scorer.py.
Later phases: agents/*.py (one agent each), tools/peer_finder.py, graph/pipeline.py, prompts/templates.py, evaluation/evaluator.py, watchlist/*, app.py, watchlist_monitor.py, README.md, scripts/generate_samples.py, sample_analysis/*.

## 10. Reporting format for every build task
Final message must list: files written; public API actually implemented (signatures); tests run + real pass/fail counts; what was verified live vs mocked; known gaps/deviations; anything other modules must know.
