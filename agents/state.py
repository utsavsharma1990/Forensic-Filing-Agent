"""Shared LangGraph state for forensic-filing-agent.

``ForensicAgentState`` follows the spec plus the extra fields required by docs/CONTRACTS.md.
Reducer-annotated list fields (``agent_trace``, ``degraded``, ``warnings``) use ``operator.add`` so
parallel agent nodes can each append without clobbering each other.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict


class ForensicAgentState(TypedDict, total=False):
    """Shared state passed between graph nodes (agents 1-4 read only the raw data fields)."""

    # ---- Input ----
    ticker: str
    company_name: str
    cik: str
    analysis_years: list[int]
    as_of: str                      # ISO date; nothing filed after it may be used
    focus_year: int                 # last fiscal year analysed (before fetch_data: the REQUESTED end_year, if any)
    years_requested: int            # number of analysis years requested
    exclude_flags: list[str]        # flags removed from agents 1-4 results (tools.config; pre-registered variants)

    # ---- Raw data (fetched once, shared read-only) ----
    xbrl_data: dict                 # compact companyfacts (CANONICAL_CONCEPTS + dei only)
    filing_texts: dict              # {year: full annual-report text}
    filing_metadata: dict           # {year: {auditor, cfo, ceo, filing_date, ...}}
    filings: list[dict]             # Filing dicts for the analysed years (+ baseline year)
    peer_companies: list[dict]
    peer_reason: str                # why peer discovery returned nothing ("" when peers were found)
    annual_facts: dict              # AnnualFacts (CONTRACTS section 2), built once, point-in-time
    fetch_info: dict                # provenance of the fetch (selected filings, proxies used, sources, timings)
    filing_entity_flags: dict       # v2: {fiscal_year: {"is_shell": bool, "spac_predecessor": bool, "reason": str, "kind": str, ...}}
                                    # years flagged are KEPT in the state but must not be used as YoY baselines by consumers

    # ---- Agent outputs (populated in parallel) ----
    quantitative_result: dict
    language_result: dict
    network_result: dict
    peer_result: dict
    temporal_result: dict

    # ---- Synthesis outputs ----
    prior_year_results: dict        # optional {agent: result} for Jev material-change questions (v2: computed by run_synthesis_node)
    prior_year_info: dict           # v2: {"status": "ok|skipped|failed|timeout", "year", "agents", "seconds", "reason"}
    jev_scores: dict
    jev_available: bool
    agent_severity: dict
    grade_inputs: dict              # v3: exact inputs of the grade rule {focus_year, agents_flagging, agents_high, escalation, focus_year_flagged, jev_mean_confidence, jev_available, agent_severity}
    risk_grade: str                 # Low / Medium / High / Critical (or "Unknown" = error state, never Low)
    grade_rationale: str
    smoking_guns: list[str]
    smoking_gun_evidence: list[dict]
    forensic_timeline: list[dict]
    final_narrative: str
    suspicion_score: int
    first_detection_year: Optional[int]
    first_detection_filing_date: Optional[str]

    # ---- Watchlist ----
    watchlist_id: str
    previous_risk_grade: str
    risk_changed: bool

    # ---- Meta (reducers allow concurrent appends) ----
    agent_trace: Annotated[list, operator.add]
    degraded: Annotated[list, operator.add]
    warnings: Annotated[list, operator.add]
    node_timings: Annotated[list, operator.add]   # [{node, start_ts, end_ts, duration_ms}] wall-clock per graph node
    analysis_timestamp: str
    pipeline_version: str                          # "v3" (v1 states lack the key); lets caches/evaluators tell versions apart
    total_ms: int                                  # wall time of the whole analysis (set by analyze_company)
    error: str


def new_state(
    ticker: str,
    years: int = 5,
    *,
    cik: Optional[str] = None,
    end_year: Optional[int] = None,
    as_of: Optional[str] = None,
    previous_risk_grade: Optional[str] = None,
    watchlist_id: Optional[str] = None,
) -> ForensicAgentState:
    """Build an initial state. ``analysis_years`` is filled in later by ``fetch_data`` when ``end_year`` is None.

    Reducer fields start empty; ``analysis_years`` is the ``years`` most recent years ending at ``end_year``
    (oldest first) when ``end_year`` is known, else ``[]``.
    """
    n = max(1, int(years))
    analysis_years = list(range(end_year - n + 1, end_year + 1)) if end_year else []
    state: ForensicAgentState = {
        "ticker": str(ticker).strip().upper(),
        "company_name": "",
        "cik": cik or "",
        "analysis_years": analysis_years,
        "years_requested": n,
        "as_of": as_of or "",
        "annual_facts": {},
        "peer_reason": "",
        "fetch_info": {},
        "filing_entity_flags": {},
        "prior_year_results": {},
        "prior_year_info": {},
        "pipeline_version": "v3",
        "grade_rationale": "",
        "exclude_flags": [],
        "node_timings": [],
        "xbrl_data": {},
        "filing_texts": {},
        "filing_metadata": {},
        "filings": [],
        "peer_companies": [],
        "jev_scores": {},
        "jev_available": False,
        "agent_severity": {},
        "grade_inputs": {},
        "smoking_guns": [],
        "smoking_gun_evidence": [],
        "forensic_timeline": [],
        "final_narrative": "",
        "suspicion_score": 0,
        "first_detection_year": None,
        "first_detection_filing_date": None,
        "watchlist_id": watchlist_id or "",
        "previous_risk_grade": previous_risk_grade or "",
        "risk_changed": False,
        "agent_trace": [],
        "degraded": [],
        "warnings": [],
        "analysis_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": "",
    }
    if end_year:
        state["focus_year"] = int(end_year)
    return state


def _convert_keys(obj: Any, to_str: bool) -> Any:
    """Recursively convert dict keys int<->str (digit-only strings become ints when ``to_str`` is False)."""
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            if to_str:
                nk = str(k) if isinstance(k, int) and not isinstance(k, bool) else k
            else:
                nk = int(k) if isinstance(k, str) and k.isdigit() and len(k) == 4 else k
            out[nk] = _convert_keys(v, to_str)
        return out
    if isinstance(obj, (list, tuple)):
        return [_convert_keys(v, to_str) for v in obj]
    if isinstance(obj, float) and obj != obj:  # NaN is not valid JSON
        return None
    return obj


def to_jsonable(state: dict) -> dict:
    """Return a deep JSON-safe copy of ``state`` (int keys -> str, tuples -> lists, NaN -> None)."""
    return _convert_keys(dict(state), to_str=True)


def from_jsonable(data: dict) -> ForensicAgentState:
    """Inverse of :func:`to_jsonable`: four-digit numeric string keys become ints again.

    ``xbrl_data`` is left untouched except for the same key conversion rule (its keys are concept names and
    dates, never four-digit numerics, so this is safe).
    """
    return _convert_keys(dict(data), to_str=False)  # type: ignore[return-value]
