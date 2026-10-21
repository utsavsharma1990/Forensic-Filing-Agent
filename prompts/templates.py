"""All system prompts and reviewed lookup tables for forensic-filing-agent.

Every prompt is a named constant with a docstring-style comment. The language agent keeps its OWN
specificity prompt constant; ``SPECIFICITY_PROMPT_REFERENCE`` below is a reference copy only.
"""

from __future__ import annotations

SYNTHESIS_SYSTEM_PROMPT = """You are the synthesis stage of a forensic accounting review of a public company's SEC filings.
You receive ONE compact JSON evidence packet produced by deterministic analysis code and five specialist agents
(quantitative, language, network, peer, temporal). The risk grade has ALREADY been decided by fixed, auditable rules;
you do not change it. You only write the narrative.

HARD RULES
1. NEVER INVENT financial figures, dates, percentages, counts, company facts or historical cases. Every numeral you write
   must appear in the evidence packet (rounding or formatting differences such as 12.3 vs 12.30 are fine). If a figure you
   would like to cite is not in the packet, describe the point in words instead. Do not compute new numbers.
2. Do not name any historical fraud case unless it appears in the packet (smoking-gun pattern/case fields).
3. If the evidence is ambiguous, thin, conflicting between agents, or an agent was unavailable, SAY SO plainly. Do not smooth
   over disagreement. Absence of flags is not proof of clean books: say what could not be assessed.
4. Distinguish ACCOUNTING MANIPULATION RISK from BUSINESS DISTRESS RISK. They are different failure modes needing different
   flags: distress signals (Altman distress zone, going concern, leverage) mean a company may fail; manipulation signals
   (receivables outpacing sales, accruals divergence, restatements, auditor/CFO turnover, related-party growth, Beneish
   manipulation zone) mean reported numbers may be unreliable. A distressed company is not thereby manipulating, and a
   healthy-looking company is not thereby clean. Label each risk factor you cite as one or the other (or both).
5. Statistical flags are indicators, not proof of fraud. Never accuse anyone of fraud or intent. Use "risk", "signal",
   "consistent with". Jev confidence is a model-confidence measure for each agent's finding; it is not a probability of fraud.
6. Use only the packet. No outside knowledge about this company.

OUTPUT: exactly THREE paragraphs of plain prose, separated by one blank line. No headings, no bullet lists, no markdown.
Paragraph 1: overall assessment (state the grade and the rule that produced it), a summary of the evidence, and the
  limitations (unavailable agents, degraded components, missing data, Jev availability).
Paragraph 2: the most significant risk factors with specifics from the packet (use the smoking-gun evidence first), labelled
  manipulation vs distress, noting any conflicting or ambiguous evidence.
Paragraph 3: what to watch: leading indicators that would signal escalation or resolution, derived from which flags are open.
"""
"""System prompt for the Sonnet narrative writer in agents/synthesis_agent.py (NEVER-INVENT, manipulation-vs-distress, ambiguity rules)."""

NARRATIVE_USER_TEMPLATE = """Evidence packet (JSON). Treat it as the only source of facts:

{packet_json}

Write the three-paragraph narrative now, following the rules. Every numeral must come from the packet."""
"""User message template for the narrative call; ``.format(packet_json=...)`` fills the packet."""

SPECIFICITY_PROMPT_REFERENCE = (
    "Rate the specificity of this MD&A section from 1-10. High specificity means concrete numbers, "
    "named products, specific markets. Low specificity means vague language about 'macroeconomic "
    "conditions' and 'industry trends'. Return JSON: {score: int, reason: str}"
)
"""REFERENCE COPY ONLY of the spec's specificity prompt. agents/language_agent.py keeps and uses its own constant."""

# --------------------------------------------------------------------------------------------------------------
# PATTERN_TABLE: flag -> documented historical pattern + case, used in smoking-gun sentences.
# Only well-documented, citable cases. Each entry: flags (list of flag names), metric_keywords (optional: if present, the
# evidence item's metric text must contain one, case-insensitive), pattern (phrase for "consistent with {pattern}"),
# case (phrase for "observed before {case}"), source (citation note), confidence (how directly the flag maps to the
# documented pattern: "high" = the documented scheme is exactly what the flag measures; "medium" = flag is a recognised
# symptom of the documented scheme but not unique to it). Verified by web search 2026-10-16 (see source notes).
# The mapping says a SIGNATURE resembles a documented pattern; it never asserts the company did the same.
# --------------------------------------------------------------------------------------------------------------
PATTERN_TABLE: list[dict] = [
    {
        "key": "sunbeam_channel_stuffing",
        "flags": ["quantitative.dso_growth"],
        "metric_keywords": [],
        "pattern": "receivables growth outpacing sales, a premature revenue recognition / channel-stuffing signature",
        "case": "the Sunbeam accounting fraud (1996-1998)",
        "source": (
            "SEC v. Dunlap et al., Litigation Release LR-17001 (May 15, 2001): bill-and-hold sales, channel-stuffing "
            "incentives and cookie-jar reserves at Sunbeam 1996-1998; SEC admin. proceeding 33-7977. "
            "https://www.sec.gov/litigation/litreleases/2001/lr17001.htm"
        ),
        "confidence": "medium",
    },
    {
        "key": "worldcom_capitalised_costs",
        "flags": ["quantitative.beneish", "quantitative.accruals"],
        "metric_keywords": ["aqi", "asset quality", "capitaliz", "capitalis"],
        "pattern": "rising asset-quality / capitalised-expense signature (operating costs moved onto the balance sheet)",
        "case": "WorldCom's 2002 restatement",
        "source": (
            "SEC v. WorldCom, Litigation Release LR-17588 (June 27, 2002) and CRS Report RS21253: about $3.8 billion of line "
            "costs capitalised instead of expensed (2001 and Q1 2002). Note: costs capitalised to PP&E raise net income and "
            "operating cash flow alike, so accruals ratios may NOT show it; the AQI component is the closer symptom. "
            "https://www.sec.gov/litigation/litreleases/2002/lr17588.htm"
        ),
        "confidence": "medium",
    },
    {
        "key": "enron_related_party_spe",
        "flags": ["network.related_party"],
        "metric_keywords": [],
        "pattern": "growth in related-party / special-purpose-entity disclosures",
        "case": "Enron's 2001 restatement",
        "source": (
            "Enron Form 8-K filed Nov. 8, 2001: restatement of 1997-2000 financials to consolidate Chewco, JEDI and an "
            "LJM1 subsidiary; Andrew Fastow (CFO) managed the LJM partnerships (SEC complaint comp18335). "
            "https://www.sec.gov/Archives/edgar/data/0001024401/000095012901503835/h91831e8-k.txt"
        ),
        "confidence": "medium",
    },
]

# Leading indicators to monitor, keyed by open flag (no numerals: the deterministic narrative is built from these).
WATCH_INDICATORS: dict[str, str] = {
    "quantitative.beneish": "the Beneish M-Score components in the next filing, especially receivables-to-sales, gross margin and asset-quality indices",
    "quantitative.altman_distress": "liquidity, leverage and covenant disclosures (a business-distress signal, separate from manipulation risk)",
    "quantitative.revenue_quality": "whether operating cash flow converges back toward net income",
    "quantitative.dso_growth": "days sales outstanding and receivables ageing versus revenue growth in the next quarters",
    "quantitative.accruals": "whether the gap between net income and operating cash flow narrows",
    "language.hedging": "hedging and qualification language in MD&A in the next filing",
    "language.passive_voice": "passive, agent-less phrasing around results and unusual items",
    "language.risk_factor_growth": "newly added risk-factor disclosures",
    "language.specificity": "whether MD&A returns to concrete, quantified explanations",
    "language.new_legal": "developments in newly disclosed legal proceedings",
    "network.auditor_change": "the stated reasons for the auditor change, Item 9 disagreement disclosures and any resignation letter",
    "network.cfo_change": "further finance-leadership turnover and the circumstances of the CFO departure",
    "network.ceo_change": "leadership stability and the circumstances of the CEO departure",
    "network.audit_fees": "audit-fee changes relative to business growth and any non-audit fee increases",
    "network.restatement": "restatement or material-weakness remediation disclosures and any non-reliance 8-K filings",
    "network.related_party": "related-party transaction volume and counterparties in the next filing",
    "network.going_concern": "going-concern language, financing events and debt maturities (a distress signal)",
}
