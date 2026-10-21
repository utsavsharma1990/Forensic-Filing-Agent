"""Retrospective validation harness (CONTRACTS section 7).

Runs the pipeline on the 12 registry cases and reports precision/recall/F1/FPR with exact Wilson 95% CIs,
baselines, per-agent contribution, detection timing (D14) and an unmissable limitations/contamination section.

Design rules (this module must be incapable of flattering the system):
* Positive prediction = risk_grade in {High, Critical}. Grade "Unknown"/missing or any analysis error => case
  status ERROR, EXCLUDED from the confusion matrix with the exclusion stated, never counted as a negative.
  A worst-case view (errored fraud cases as misses, errored clean cases as false alarms) is reported next to it.
* Undefined ratios are ``None`` (never ZeroDivisionError / NaN).
* Headline = mode "spec" and variant "spec". Every other (mode, variant) is a labelled sensitivity run.
* Thresholds are never touched here; only reporting.
* No results are fabricated: this module only reports what the injected/real ``analyze`` returned.

Public API: :func:`run_evaluation`, :func:`load_last_results`, :func:`render_report`, :func:`wilson_interval`,
:func:`compute_metrics`, :func:`agent_contribution`, :func:`detection_timing`, :func:`case_params`,
:func:`paired_comparison`, :func:`sign_test_p`, :func:`beneish_availability`.

v3 additions (docs/V3_CHANGELOG_lang_eval.md; reporting only, no grade/threshold change):
* per-case rows persist the audit instrumentation (focus_signal_change, signal_trajectory, flags_by_year, grade inputs,
  per-year suspicion, filing_entity_flags, prior-year summary, grade_rationale);
* SECONDARY metric: paired suspicion-score comparison for matched pairs (``match_partner``): wins/ties/losses, exact
  two-sided sign test, paired AUC with a fixed-seed bootstrap CI; Beneish availability among fraud vs clean cases;
* an INJECTED ``analyze`` NEVER reads or writes the on-disk results cache (v2 incident, docs/V2_FREEZE.md): it uses a
  process-local in-memory cache keyed by the analyzer object itself.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import math
import os
import platform
import re
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.fraud_cases import ALL_CASES, get_case  # noqa: E402

__all__ = [
    "run_evaluation", "load_last_results", "render_report", "wilson_interval", "compute_metrics",
    "agent_contribution", "detection_timing", "case_params", "code_hash", "VARIANTS", "RESULTS_DIR",
    "paired_comparison", "sign_test_p", "beneish_availability", "load_cases_from",
]

RESULTS_DIR = ROOT / "evaluation" / "results"
REPORT_NAME = "evaluation_report.md"
JSON_NAME = "evaluation_results.json"

POSITIVE_GRADES = ("High", "Critical")
VALID_GRADES = ("Low", "Medium", "High", "Critical")
AGENTS = ("quantitative", "language", "network", "peer", "temporal")
INDEPENDENT_AGENTS = ("quantitative", "language", "network", "peer")  # agents 1-4 (temporal is derived from them)
FLAGGING_SEVERITIES = ("Medium", "High")
MAX_CONCURRENT_CASES = 2
DAYS_PER_MONTH = 365.2425 / 12.0  # 30.436875
Z95 = 1.959963984540054
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261018         # fixed: the CI is reproducible
ROW_SCHEMA = 3                    # part of the cache key: rows written by an older schema are never served

# Pre-registered variants (docs/TUNING_LEDGER.md P1/P2). value = exclude_flags passed to analyze_company.
VARIANTS: dict[str, Optional[list[str]]] = {
    "spec": None,
    "no_passive": ["language.passive_voice"],
}

DISCLAIMER = (
    "This evaluation uses publicly available SEC filings. Past detection performance does not guarantee future "
    "accuracy. This tool is for research purposes and does not constitute investment advice."
)

CODE_HASH_GLOBS = ("agents/*.py", "tools/*.py", "graph/*.py", "evaluation/fraud_cases.py", "prompts/templates.py")


# --------------------------------------------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    """Deep JSON-safe copy: int keys -> str, tuples/sets -> lists, NaN/inf -> None, dates -> ISO strings."""
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else str(k)): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    try:  # numpy scalars etc.
        f = float(obj)
        return f if math.isfinite(f) else None
    except Exception:
        return str(obj)


def _safe_div(a: float, b: float) -> Optional[float]:
    return None if not b else a / b


def _get_year(d: Any, year: Any) -> Any:
    """Look up ``year`` in a dict whose keys may be int or str (JSON round trips)."""
    if not isinstance(d, dict) or year is None:
        return None
    for k in (year, str(year)):
        if k in d:
            return d[k]
    try:
        return d.get(int(year))
    except Exception:
        return None


def wilson_interval(k: int, n: int, z: float = Z95) -> Optional[tuple[float, float]]:
    """Wilson score 95% interval for k successes in n trials; ``None`` when n == 0."""
    if n is None or n <= 0 or k is None:
        return None
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / d
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _ratio(num: int, den: int) -> dict:
    """{"value","ci_low","ci_high","num","den"}; value/CI None when den == 0."""
    if not den:
        return {"value": None, "ci_low": None, "ci_high": None, "num": num, "den": den}
    ci = wilson_interval(num, den)
    return {"value": num / den, "ci_low": ci[0], "ci_high": ci[1], "num": num, "den": den}


def compute_metrics(tp: int, fp: int, tn: int, fn: int) -> dict:
    """Confusion-matrix metrics with Wilson CIs. F1 has no closed-form Wilson interval (ci None, stated)."""
    f1_den = 2 * tp + fp + fn
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": tp + fp + tn + fn,
        "accuracy": _ratio(tp + tn, tp + fp + tn + fn),
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "fpr": _ratio(fp, fp + tn),
        "f1": {"value": (2 * tp / f1_den) if f1_den else None, "ci_low": None, "ci_high": None,
               "num": 2 * tp, "den": f1_den, "note": "no closed-form Wilson CI for F1"},
    }


def months_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """Fractional months (1 decimal) from ``start`` to ``end`` (ISO dates); positive when start is BEFORE end."""
    if not start or not end:
        return None
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return round((d1 - d0).days / DAYS_PER_MONTH, 1)


def code_hash(root: Optional[Path] = None) -> str:
    """sha256 over (relative path, contents) of the rule/agent files; stable ordering."""
    root = Path(root) if root else ROOT
    files: list[Path] = []
    for pattern in CODE_HASH_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    h = hashlib.sha256()
    for f in sorted(set(files), key=lambda p: p.relative_to(root).as_posix()):
        h.update(f.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(f.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\0")
    return h.hexdigest()


def _cache_dir() -> Path:
    try:
        from tools import common
        base = Path(common.CACHE_DIR)
    except Exception:
        base = ROOT / ".cache"
    return base / "eval"


# --------------------------------------------------------------------------------------------------------------
# case selection / parameters
# --------------------------------------------------------------------------------------------------------------
def case_params(case: dict, mode: str) -> dict:
    """Return ``{"include": bool, "as_of", "end_year", "reason", "used_strict_alt"}`` for ``case`` in ``mode``.

    spec: as_of = analysis_filing_date, end_year = analysis_year.
    strict: fraud cases with pre_revelation_valid=False use strict_alt (fiscal_year, filing_date); a case without
    strict_alt is EXCLUDED with a reason; every other case (valid fraud, clean) is unchanged.
    """
    if mode not in ("spec", "strict"):
        raise ValueError(f"mode must be 'spec' or 'strict', got {mode!r}")
    base = {"include": True, "as_of": case.get("analysis_filing_date") or case.get("as_of"),
            "end_year": case.get("analysis_year"), "reason": "", "used_strict_alt": False}
    if mode == "spec" or case.get("pre_revelation_valid", True):
        return base
    alt = case.get("strict_alt")
    if not alt:
        base.update(include=False, reason=(
            "strict run: analysis filing post-dates public revelation and no earlier annual report exists "
            "(strict_alt is None)"))
        return base
    base.update(as_of=alt["filing_date"], end_year=alt["fiscal_year"], used_strict_alt=True,
                reason=str(alt.get("note") or ""))
    return base


def _resolve_cases(cases: Optional[Iterable[Any]]) -> list[dict]:
    if cases is None:
        return [dict(c) for c in ALL_CASES]
    out: list[dict] = []
    for c in cases:
        if isinstance(c, dict):
            out.append(dict(c))
        else:
            got = get_case(str(c))
            if got is None:
                raise ValueError(f"unknown evaluation case: {c!r}")
            out.append(got)
    return out


# --------------------------------------------------------------------------------------------------------------
# state -> case row
# --------------------------------------------------------------------------------------------------------------
def _clip(s: Any, n: int = 220) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 3] + "..."


def _dedupe(seq: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for s in seq:
        s = str(s)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _agent_summary(state: dict, agent: str, focus_year: Optional[int]) -> dict:
    res = state.get(f"{agent}_result")
    if not isinstance(res, dict):
        return {"present": False, "unavailable": True, "severity": "None", "flags_fired": 0,
                "focus_flags": [], "key_finding": "", "reason": "no result in state"}
    sev = res.get("severity")
    sev = sev if sev in ("None", "Low", "Medium", "High") else "None"
    focus_flags = _get_year(res.get("flags_by_year") or {}, focus_year) or []
    return {
        "present": True,
        "unavailable": bool(res.get("unavailable")),
        "severity": sev,
        "flags_fired": int(res.get("flags_fired") or 0),
        "focus_flags": [str(f) for f in focus_flags],
        "key_finding": _clip(res.get("key_finding")),
        "reason": _clip(res.get("error") or ""),
    }


def _key_signal(state: dict, agents: dict) -> str:
    guns = state.get("smoking_guns") or []
    if guns:
        return _clip(guns[0])
    flagged = [a for a in INDEPENDENT_AGENTS if _is_flagging(agents.get(a))]
    flagged.sort(key=lambda a: (agents[a]["severity"] != "High",))
    for a in flagged:
        if agents[a]["key_finding"]:
            return f"{a}: {agents[a]['key_finding']}"
    return "-"


def _is_flagging(a: Optional[dict]) -> bool:
    return bool(a) and not a.get("unavailable") and a.get("severity") in FLAGGING_SEVERITIES


def _grade_inputs(state: dict, agents: dict, focus: Any) -> dict:
    """The exact inputs of the grade rule. Taken from ``state['grade_inputs']`` (v3 synthesis); older states are
    re-derived with the SAME helper functions synthesis uses (never a different rule) and labelled ``recomputed``."""
    gi = state.get("grade_inputs")
    if isinstance(gi, dict) and gi:
        return {**{k: gi.get(k) for k in ("agents_flagging", "agents_high", "escalation", "focus_year_flagged",
                                           "jev_mean_confidence", "jev_available")}, "source": "state"}
    try:
        from agents import synthesis_agent as syn
        results = {a: state.get(f"{a}_result") for a in syn.ALL_AGENTS}
        fy = syn._year_key(focus)
        sev = {a: syn._severity(results.get(a)) for a in syn.CORE_AGENTS}
        jev_mean, jev_ok = syn._jev_summary(state.get("jev_scores") or {})
        return {"agents_flagging": sum(1 for v in sev.values() if v in ("Medium", "High")),
                "agents_high": sum(1 for v in sev.values() if v == "High"),
                "escalation": bool(syn._escalation(results.get("temporal"), fy)),
                "focus_year_flagged": bool(syn._focus_year_flagged(results, fy)),
                "jev_mean_confidence": jev_mean, "jev_available": jev_ok, "source": "recomputed"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"source": f"unavailable ({type(exc).__name__})"}


def _prior_year_summary(state: dict) -> dict:
    info = state.get("prior_year_info") if isinstance(state.get("prior_year_info"), dict) else {}
    pr = state.get("prior_year_results") if isinstance(state.get("prior_year_results"), dict) else {}
    agents = {}
    for a, r in pr.items():
        if isinstance(r, dict):
            agents[str(a)] = {"severity": r.get("severity"), "flags_fired": r.get("flags_fired"),
                              "unavailable": bool(r.get("unavailable"))}
    return {"status": info.get("status"), "year": info.get("year"), "reason": _clip(info.get("reason"), 160),
            "agents": agents}


def _instrumentation(state: dict, agents: dict, focus: Any) -> dict:
    """v3 audit fields (L2). Pure reads of the state: they never influence grade, outcome or metrics."""
    temporal = state.get("temporal_result") if isinstance(state.get("temporal_result"), dict) else {}
    timeline = [r for r in (temporal.get("timeline") or []) if isinstance(r, dict)]
    flags_by_year = {}
    for a in AGENTS:
        res = state.get(f"{a}_result")
        fby = res.get("flags_by_year") if isinstance(res, dict) else None
        flags_by_year[a] = ({str(y): [str(f) for f in (fl or [])] for y, fl in fby.items()}
                            if isinstance(fby, dict) else {})
    susp = temporal.get("suspicion_score", state.get("suspicion_score"))
    return {
        "focus_signal_change": temporal.get("focus_signal_change"),
        "signal_trajectory": temporal.get("signal_trajectory"),
        "flags_by_year": flags_by_year,
        "focus_flags_by_agent": {a: list(agents[a]["focus_flags"]) for a in AGENTS},
        "grade_inputs": _grade_inputs(state, agents, focus),
        "grade_rationale": _clip(state.get("grade_rationale"), 600),
        "suspicion_score": susp if isinstance(susp, (int, float)) and not isinstance(susp, bool) else None,
        "suspicion_by_year": {str(r.get("year")): r.get("suspicion_score") for r in timeline if r.get("year") is not None},
        "signal_change_by_year": {str(r.get("year")): r.get("signal_change") for r in timeline if r.get("year") is not None},
        "filing_entity_flags": (_jsonable(state["filing_entity_flags"])
                                if isinstance(state.get("filing_entity_flags"), dict) else {}),
        "prior_year_summary": _prior_year_summary(state),
        "pipeline_version": state.get("pipeline_version"),
    }


def _base_row(case: dict, params: dict, mode: str, variant: str) -> dict:
    return {
        "ticker": case["ticker"], "company": case.get("company_name") or case["ticker"], "cik": case.get("cik"),
        "mode": mode, "variant": variant,
        "analysis_year": case.get("analysis_year"), "end_year": params.get("end_year"), "as_of": params.get("as_of"),
        "used_strict_alt": bool(params.get("used_strict_alt")),
        "ground_truth": int(case.get("ground_truth", 0)),
        "actual": "Fraud" if case.get("ground_truth") else "Clean",
        "fraud_nature": case.get("fraud_nature", "none"),
        "label_confidence": case.get("label_confidence", ""),
        "pre_revelation_valid": bool(case.get("pre_revelation_valid", True)),
        "public_revelation_date": case.get("public_revelation_date"),
        "collapse_date": case.get("collapse_date"),
        "status": "ERROR", "error": "", "risk_grade": None, "predicted": None, "outcome": None,
        "first_detection_year": None, "first_detection_filing_date": None,
        "agents": {}, "agents_flagging": [], "agents_high": [],
        "key_signal": "-", "smoking_guns": [], "degraded": [], "jev_available": None,
        "beneish_focus_flag": None, "beneish_available": False,
        "match_partner": case.get("match_partner"),
        "focus_signal_change": None, "signal_trajectory": None, "flags_by_year": {}, "focus_flags_by_agent": {},
        "grade_inputs": {}, "grade_rationale": "", "suspicion_score": None, "suspicion_by_year": {},
        "signal_change_by_year": {}, "filing_entity_flags": {}, "prior_year_summary": {}, "pipeline_version": None,
        "row_schema": ROW_SCHEMA,
        "from_cache": False,
    }


def _row_from_state(case: dict, params: dict, mode: str, variant: str, state: Any) -> dict:
    """Pure conversion of a pipeline state into a case row (never raises)."""
    row = _base_row(case, params, mode, variant)
    if not isinstance(state, dict):
        row["error"] = f"analyze returned {type(state).__name__}, not a state dict"
        return row
    focus = params.get("end_year")
    agents = {a: _agent_summary(state, a, focus) for a in AGENTS}
    grade = state.get("risk_grade")
    degraded = list(state.get("degraded") or [])
    if state.get("jev_available") is not True:
        degraded.append("eval: jev unavailable (no Jev confidence; Critical grade unreachable)")
    for a in INDEPENDENT_AGENTS:
        if agents[a]["unavailable"]:
            degraded.append(f"eval: {a} agent unavailable ({agents[a]['reason'] or agents[a]['key_finding'] or 'no reason given'})")
    quant = state.get("quantitative_result") or {}
    bscore = _get_year(quant.get("beneish_scores") or {}, focus) if isinstance(quant, dict) else None
    row.update(
        risk_grade=grade if isinstance(grade, str) else None,
        first_detection_year=state.get("first_detection_year"),
        first_detection_filing_date=state.get("first_detection_filing_date"),
        agents=agents,
        agents_flagging=[a for a in INDEPENDENT_AGENTS if _is_flagging(agents[a])],
        agents_high=[a for a in INDEPENDENT_AGENTS if not agents[a]["unavailable"] and agents[a]["severity"] == "High"],
        smoking_guns=[_clip(g) for g in (state.get("smoking_guns") or [])][:3],
        key_signal=_key_signal(state, agents),
        degraded=_dedupe(degraded),
        jev_available=state.get("jev_available"),
        beneish_available=isinstance(bscore, dict) and bscore.get("flag") is not None
        and bscore.get("status", "ok") == "ok" and bscore.get("score") is not None,
        beneish_focus_flag=bool(bscore.get("flag")) if isinstance(bscore, dict) and bscore.get("status", "ok") == "ok"
        and bscore.get("score") is not None else None,
    )
    try:
        row.update(_instrumentation(state, agents, focus))
    except Exception as exc:  # instrumentation must never change or break a row
        row["degraded"] = _dedupe(list(row["degraded"]) + [f"eval: instrumentation failed ({type(exc).__name__})"])
    err = state.get("error")
    if err:
        row["error"] = _clip(err, 400)
        return row
    if grade not in VALID_GRADES:
        row["error"] = f"risk_grade {grade!r} is not a valid grade (Unknown/missing is an error state, not Low)"
        return row
    row["status"] = "OK"
    row["predicted"] = grade in POSITIVE_GRADES
    actual = bool(case.get("ground_truth"))
    row["outcome"] = ("TP" if actual else "FP") if row["predicted"] else ("FN" if actual else "TN")
    return row


def _error_row(case: dict, params: dict, mode: str, variant: str, message: str) -> dict:
    row = _base_row(case, params, mode, variant)
    row["error"] = _clip(message, 400)
    return row


# --------------------------------------------------------------------------------------------------------------
# analysis of rows
# --------------------------------------------------------------------------------------------------------------
def _confusion(rows: list[dict]) -> dict:
    c = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for r in rows:
        if r.get("status") == "OK" and r.get("outcome") in c:
            c[r["outcome"]] += 1
    return c


def agent_contribution(rows: list[dict]) -> dict:
    """Per-agent contribution on OK rows.

    For each agent: plain flag rate on fraud cases, false-alarm rate on clean cases, and unique catches (fraud
    case flagged by this agent and by NO other independent agent 1-4), as % of all evaluable fraud cases and as
    % of detected (true-positive) fraud cases. Temporal is derived from agents 1-4 so it has no unique-catch.
    """
    ok = [r for r in rows if r.get("status") == "OK"]
    fraud = [r for r in ok if r["ground_truth"] == 1]
    clean = [r for r in ok if r["ground_truth"] == 0]
    tps = [r for r in fraud if r["outcome"] == "TP"]

    def flags(r: dict, a: str) -> bool:
        return _is_flagging((r.get("agents") or {}).get(a))

    out: dict[str, Any] = {"n_fraud": len(fraud), "n_clean": len(clean), "n_true_positive": len(tps), "agents": {}}
    for a in AGENTS:
        fl_f = [r for r in fraud if flags(r, a)]
        fl_c = [r for r in clean if flags(r, a)]
        entry: dict[str, Any] = {
            "flag_rate_fraud": _ratio(len(fl_f), len(fraud)),
            "false_alarm_rate_clean": _ratio(len(fl_c), len(clean)),
            "flagged_fraud_cases": [r["ticker"] for r in fl_f],
            "flagged_clean_cases": [r["ticker"] for r in fl_c],
            "unavailable_cases": [r["ticker"] for r in ok if ((r.get("agents") or {}).get(a) or {}).get("unavailable", True)],
        }
        if a in INDEPENDENT_AGENTS:
            others = [o for o in INDEPENDENT_AGENTS if o != a]
            uniq = [r for r in fl_f if not any(flags(r, o) for o in others)]
            entry["unique_catches"] = [r["ticker"] for r in uniq]
            entry["unique_catch_pct_of_fraud"] = _ratio(len(uniq), len(fraud))
            uniq_tp = [r for r in uniq if r["outcome"] == "TP"]
            entry["unique_catch_pct_of_detected"] = _ratio(len(uniq_tp), len(tps))
            entry["unique_catches_detected"] = [r["ticker"] for r in uniq_tp]
        else:
            entry["unique_catches"] = None
            entry["note"] = "derived from agents 1-4; not an independent signal, so no unique-catch"
        out["agents"][a] = entry
    # decisive-agent table: agents at severity High among true positives
    decisive: dict[str, Any] = {}
    for a in AGENTS:
        hit = [r["ticker"] for r in tps if ((r.get("agents") or {}).get(a) or {}).get("severity") == "High"
               and not (r["agents"][a] or {}).get("unavailable")]
        decisive[a] = {"count": len(hit), "of_true_positives": len(tps), "cases": hit}
    out["decisive"] = decisive
    return out


def detection_timing(rows: list[dict]) -> dict:
    """D14 timing for true positives: months from the first-detection filing date to revelation / collapse.

    Positive = detected BEFORE the event ("early"); zero or negative = "not early" (kept in the table, excluded
    from the average). Quantised to annual filing dates.
    """
    items = []
    for r in rows:
        if r.get("status") != "OK" or r.get("outcome") != "TP":
            continue
        fd = r.get("first_detection_filing_date")
        m_rev = months_between(fd, r.get("public_revelation_date"))
        m_col = months_between(fd, r.get("collapse_date"))
        items.append({
            "ticker": r["ticker"], "first_detection_year": r.get("first_detection_year"),
            "first_detection_filing_date": fd, "public_revelation_date": r.get("public_revelation_date"),
            "collapse_date": r.get("collapse_date"), "months_before_revelation": m_rev,
            "months_before_collapse": m_col, "pre_revelation_valid": r.get("pre_revelation_valid"),
            "early": (m_rev is not None and m_rev > 0),
            "label": ("no first-detection filing date" if fd is None
                      else "early" if (m_rev is not None and m_rev > 0) else "not early (at/after revelation)"),
        })
    early = [i["months_before_revelation"] for i in items if i["early"]]
    early_c = [i["months_before_collapse"] for i in items if i["early"] and i["months_before_collapse"] is not None]
    return {
        "cases": items, "n_true_positives": len(items), "n_early": len(early),
        "n_not_early": len(items) - len(early),
        "average_months_early_before_revelation": round(sum(early) / len(early), 1) if early else None,
        "average_months_early_before_collapse": round(sum(early_c) / len(early_c), 1) if early_c else None,
        "caveat": ("Timing is quantised to annual filing dates (a flag can only appear when a 10-K/20-F is filed); "
                   "months = days/30.44 between the first-detection filing date and the event; negative = not early "
                   "and is excluded from the average."),
    }


def _baselines(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == "OK"]
    n_f = sum(1 for r in ok if r["ground_truth"] == 1)
    n_c = len(ok) - n_f
    # Always predict clean
    always = compute_metrics(0, 0, n_c, n_f)
    # Beneish-only: any Beneish flag in the focus year; unavailable => predicts clean (counted + listed)
    tp = fp = tn = fn = 0
    unavailable = []
    for r in ok:
        pred = bool(r.get("beneish_focus_flag"))
        if not r.get("beneish_available"):
            unavailable.append(r["ticker"])
        if r["ground_truth"] == 1:
            tp, fn = tp + pred, fn + (not pred)
        else:
            fp, tn = fp + pred, tn + (not pred)
    bene = compute_metrics(tp, fp, tn, fn)
    return {
        "n": len(ok),
        "always_clean": always,
        "beneish_only": bene,
        "beneish_unavailable_cases": unavailable,
        "note": ("Baselines use exactly the same evaluable cases as the headline. Beneish-only = quantitative agent's "
                 "Beneish flag (M > -1.78) in the focus year; cases where Beneish is unavailable count as 'predict clean'."),
    }


def _fraud_nature_breakdown(rows: list[dict]) -> dict:
    out: dict[str, Any] = {}
    fraud = [r for r in rows if r["ground_truth"] == 1]
    for nature in sorted({r["fraud_nature"] for r in fraud}):
        grp = [r for r in fraud if r["fraud_nature"] == nature]
        ok = [r for r in grp if r["status"] == "OK"]
        tp = sum(1 for r in ok if r["outcome"] == "TP")
        out[nature] = {
            "n_cases": len(grp), "n_evaluable": len(ok), "tp": tp, "fn": len(ok) - tp,
            "recall": _ratio(tp, len(ok)),
            "cases": [{"ticker": r["ticker"], "status": r["status"], "risk_grade": r["risk_grade"],
                       "outcome": r["outcome"]} for r in grp],
        }
    return out


def sign_test_p(wins: int, losses: int) -> Optional[float]:
    """Exact two-sided sign-test p-value on the non-tied pairs: 2 * P(X <= min(w, l)), X ~ Binomial(w + l, 1/2), capped at 1.
    ``None`` when there is no non-tied pair."""
    n = wins + losses
    if n <= 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1))
    return min(1.0, 2.0 * tail / 2 ** n)


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (numpy's default), q in [0, 100]."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def paired_auc(diffs: list[float]) -> Optional[float]:
    """Paired AUC = P(fraud score > matched control score), ties 0.5, from the per-pair differences (fraud - control)."""
    if not diffs:
        return None
    return sum(1.0 if d > 0 else 0.5 if d == 0 else 0.0 for d in diffs) / len(diffs)


def bootstrap_auc_ci(diffs: list[float], n_boot: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
                     alpha: float = 0.05) -> Optional[tuple[float, float]]:
    """Percentile bootstrap CI of the paired AUC (resampling PAIRS with replacement, fixed seed => reproducible)."""
    import random
    if not diffs:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    score = [1.0 if d > 0 else 0.5 if d == 0 else 0.0 for d in diffs]
    boots = sorted(sum(score[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (_percentile(boots, 100 * alpha / 2), _percentile(boots, 100 * (1 - alpha / 2)))


def paired_comparison(rows: list[dict]) -> dict:
    """SECONDARY, cutoff-free metric: fraud vs its matched control on the focus-year temporal suspicion score.

    A pair = an OK fraud row whose ``match_partner`` names an OK clean row of the same run (or a clean row whose
    ``match_partner`` names the fraud row). Pairs with a missing score are listed in ``excluded_pairs`` with the
    reason. wins = fraud score > control score; ties = equal; losses = fraud < control. Sign test and AUC are
    reported alongside; with no matched pair every statistic is ``None`` and ``available`` is False (the 12 original
    dev cases have no match_partner).
    """
    by_t = {r["ticker"]: r for r in rows if r.get("status") == "OK"}
    pairs, excluded, seen = [], [], set()
    for r in rows:
        if r.get("status") != "OK" or r.get("ground_truth") != 1:
            continue
        partner = r.get("match_partner")
        if not partner:
            for c in by_t.values():
                if c.get("ground_truth") == 0 and c.get("match_partner") == r["ticker"]:
                    partner = c["ticker"]
                    break
        if not partner or partner not in by_t or by_t[partner].get("ground_truth") != 0:
            if r.get("match_partner"):
                excluded.append({"fraud": r["ticker"], "control": r.get("match_partner"),
                                 "reason": "matched control missing or not OK in this run"})
            continue
        if (r["ticker"], partner) in seen:
            continue
        seen.add((r["ticker"], partner))
        f, c = r.get("suspicion_score"), by_t[partner].get("suspicion_score")
        if f is None or c is None:
            excluded.append({"fraud": r["ticker"], "control": partner, "reason": "no stored suspicion score"})
            continue
        pairs.append({"fraud": r["ticker"], "control": partner, "fraud_score": f, "control_score": c,
                      "result": "win" if f > c else "tie" if f == c else "loss"})
    wins = sum(1 for p in pairs if p["result"] == "win")
    ties = sum(1 for p in pairs if p["result"] == "tie")
    losses = sum(1 for p in pairs if p["result"] == "loss")
    diffs = [p["fraud_score"] - p["control_score"] for p in pairs]
    ci = bootstrap_auc_ci(diffs)
    return {
        "available": bool(pairs), "n_pairs": len(pairs), "wins": wins, "ties": ties, "losses": losses,
        "sign_test_p_two_sided": sign_test_p(wins, losses), "n_non_tied": wins + losses,
        "paired_auc": paired_auc(diffs), "auc_ci_low": ci[0] if ci else None, "auc_ci_high": ci[1] if ci else None,
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED, "method": "percentile, pairs resampled"},
        "pairs": pairs, "excluded_pairs": excluded,
        "note": ("n/a: no matched fraud/control pairs in this case set (cases carry no match_partner)" if not pairs else
                 "Descriptive, cutoff-free secondary metric on focus-year temporal suspicion scores; ties count 0.5 in the "
                 "AUC; the bootstrap resamples pairs, so it is wide for small n."),
    }


def beneish_availability(rows: list[dict]) -> dict:
    """Share of OK fraud / clean cases for which a Beneish M-score was computable in the focus year."""
    out: dict[str, Any] = {}
    for label, gt in (("fraud", 1), ("clean", 0)):
        grp = [r for r in rows if r.get("status") == "OK" and r.get("ground_truth") == gt]
        have = [r for r in grp if r.get("beneish_available")]
        out[label] = {**_ratio(len(have), len(grp)), "unavailable_cases": [r["ticker"] for r in grp if not r.get("beneish_available")]}
    return out


def _analyse_run(rows: list[dict], excluded: list[dict], mode: str, variant: str) -> dict:
    conf = _confusion(rows)
    metrics = compute_metrics(conf["TP"], conf["FP"], conf["TN"], conf["FN"])
    errors = [r for r in rows if r["status"] == "ERROR"]
    # worst case: errored fraud => miss, errored clean => false alarm
    wc = compute_metrics(conf["TP"], conf["FP"] + sum(1 for r in errors if r["ground_truth"] == 0),
                         conf["TN"], conf["FN"] + sum(1 for r in errors if r["ground_truth"] == 1))
    deg_union: dict[str, list[str]] = {}
    for r in rows:
        for d in r.get("degraded") or []:
            comp = d.split(":")[0].strip() if ":" in d else d
            deg_union.setdefault(comp, [])
            if r["ticker"] not in deg_union[comp]:
                deg_union[comp].append(r["ticker"])
    degraded_run = bool(deg_union) or bool(errors)
    contrib = agent_contribution(rows)
    return {
        "mode": mode, "variant": variant, "key": f"{mode}/{variant}",
        "is_headline": mode == "spec" and variant == "spec",
        "cases": rows, "excluded": excluded,
        "errors": [{"ticker": r["ticker"], "error": r["error"]} for r in errors],
        "confusion": conf, "metrics": metrics, "worst_case_metrics": wc,
        "n_evaluable": metrics["n"], "n_error": len(errors), "n_excluded": len(excluded),
        "baselines": _baselines(rows),
        "paired": paired_comparison(rows),
        "beneish_availability": beneish_availability(rows),
        "contribution": {k: v for k, v in contrib.items() if k != "decisive"},
        "decisive_agents": contrib["decisive"],
        "timing": detection_timing(rows),
        "fraud_nature": _fraud_nature_breakdown(rows),
        "degraded_components": deg_union,
        "degraded_run": degraded_run,
    }


# --------------------------------------------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------------------------------------------
def _cache_path(case: dict, params: dict, mode: str, variant: str, chash: str) -> Path:
    # Key availability changes results (specificity, narrative, Jev, Critical gate): a degraded cached run must never be
    # served to a live-keys run (or vice versa).
    try:
        from tools.jev_scorer import get_api_key
        from tools.llm import llm_available
        keys = f"llm={bool(llm_available())}|jev={bool(get_api_key())}"
    except Exception:  # pragma: no cover - defensive
        keys = "keys=unknown"
    key = (f"{case['ticker']}|{case.get('cik')}|{mode}|{variant}|{params.get('as_of')}|{params.get('end_year')}|"
           f"gt={case.get('ground_truth')}|schema={ROW_SCHEMA}|{chash}|{keys}")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(case["ticker"]))
    return _cache_dir() / f"{safe}__{mode}__{variant}__{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"


# Process-local cache used ONLY when an ``analyze`` callable was injected (tests, notebooks, fakes). It is keyed by the
# analyzer object itself, never touches the disk and is invisible to real runs: a fake analyzer can therefore never
# poison the on-disk results cache (v2 incident, docs/V2_FREEZE.md).
_EPHEMERAL_CACHE: dict[str, tuple[Callable, dict]] = {}


def _cache_read(path: Path) -> Optional[dict]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(row, dict) and row.get("status") == "OK":
            row["from_cache"] = True
            return row
    except Exception:
        pass
    return None


def _cache_write(path: Path, row: dict) -> None:
    if row.get("status") != "OK":  # never cache errors: a rerun should retry them
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_jsonable(row), allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


# --------------------------------------------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------------------------------------------
def _default_analyze() -> Callable:
    from graph.pipeline import analyze_company  # lazy: pipeline may not exist in unit tests
    return analyze_company


def _emit(cb: Optional[Callable], **event: Any) -> None:
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        pass


async def _run_case(case: dict, params: dict, mode: str, variant: str, analyze: Optional[Callable],
                    use_cache: bool, chash: str, sem: asyncio.Semaphore, cb: Optional[Callable],
                    idx: int, total: int) -> dict:
    path = _cache_path(case, params, mode, variant, chash)
    ephemeral = analyze is not None  # injected analyzer => in-memory cache only, the real cache dir is never read/written
    base_ev = dict(ticker=case["ticker"], mode=mode, variant=variant, index=idx, total=total)
    if use_cache:
        if ephemeral:
            hit = _EPHEMERAL_CACHE.get(str(path))
            cached = dict(copy.deepcopy(hit[1]), from_cache=True) if hit is not None and hit[0] is analyze else None
        else:
            cached = _cache_read(path)
        if cached is not None:
            _emit(cb, status="cached", message=f"{case['ticker']} [{mode}/{variant}] from cache", **base_ev)
            return cached
    async with sem:
        _emit(cb, status="start", message=f"{case['ticker']} [{mode}/{variant}] as_of={params['as_of']}", **base_ev)
        try:
            fn = analyze or _default_analyze()
            kwargs: dict[str, Any] = dict(
                cik=case.get("cik"), end_year=params["end_year"], as_of=params["as_of"],
                thread_id=f"eval-{mode}-{variant}-{case['ticker']}",
            )
            excl = VARIANTS.get(variant)
            if excl:
                kwargs["exclude_flags"] = list(excl)
            res = fn(case["ticker"], 5, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            row = _row_from_state(case, params, mode, variant, res)
        except Exception as exc:  # one failing case never aborts the run
            row = _error_row(case, params, mode, variant, f"{type(exc).__name__}: {exc}")
        if ephemeral:
            if row.get("status") == "OK":
                _EPHEMERAL_CACHE[str(path)] = (analyze, copy.deepcopy(row))
        else:
            _cache_write(path, row)
        _emit(cb, status="done" if row["status"] == "OK" else "error",
              message=f"{case['ticker']} [{mode}/{variant}] {row['status']} grade={row['risk_grade']} {row['error']}".strip(),
              **base_ev)
        return row


def _key_available(*names: str) -> bool:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v and not v.lower().startswith("your_"):
            return True
    return False


def _versions() -> dict:
    from importlib import metadata
    out = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in ("langgraph", "langchain", "langchain-anthropic", "anthropic", "typesafe-sdk", "httpx", "pandas",
                "numpy", "spacy", "beautifulsoup4"):
        try:
            out[pkg] = metadata.version(pkg)
        except Exception:
            out[pkg] = None
    return out


def _metadata(chash: str, analyze_injected: bool, partial: bool, tickers: list[str], modes: list[str],
              variants: list[str]) -> dict:
    try:
        from tools.common import load_env
        load_env()
    except Exception:
        pass
    return {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": _versions(),
        "anthropic_key_available": _key_available("ANTHROPIC_API_KEY"),
        "jev_key_available": _key_available("JEV_API_KEY", "TYPESAFE_API_KEY"),
        "code_hash": chash,
        "code_hash_files": list(CODE_HASH_GLOBS),
        "analyze_source": "injected" if analyze_injected else "graph.pipeline.analyze_company",
        "partial_case_subset": partial,
        "cases_requested": tickers, "modes": modes, "variants": variants,
    }


async def _run_all(cases: list[dict], modes: list[str], variants: list[str], analyze: Optional[Callable],
                   use_cache: bool, cb: Optional[Callable], chash: str) -> dict[str, dict]:
    sem = asyncio.Semaphore(MAX_CONCURRENT_CASES)
    plan: list[tuple[str, str, list[tuple[dict, dict]], list[dict]]] = []
    for mode in modes:
        for variant in variants:
            runnable, excluded = [], []
            for case in cases:
                p = case_params(case, mode)
                if p["include"]:
                    runnable.append((case, p))
                else:
                    excluded.append({"ticker": case["ticker"], "company": case.get("company_name"),
                                     "mode": mode, "variant": variant, "reason": p["reason"],
                                     "ground_truth": int(case.get("ground_truth", 0))})
            plan.append((mode, variant, runnable, excluded))
    total = sum(len(p[2]) for p in plan)
    tasks, slots = [], []
    n = 0
    for mode, variant, runnable, _ in plan:
        for case, p in runnable:
            n += 1
            tasks.append(_run_case(case, p, mode, variant, analyze, use_cache, chash, sem, cb, n, total))
            slots.append((mode, variant))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rows_by_run: dict[tuple[str, str], list[dict]] = {(m, v): [] for m, v, _, _ in plan}
    flat = iter(zip(slots, results, [c for _, _, r, _ in plan for c in r]))
    for (mode, variant), res, (case, p) in flat:
        if isinstance(res, BaseException):  # belt and braces: _run_case already catches
            res = _error_row(case, p, mode, variant, f"{type(res).__name__}: {res}")
        rows_by_run[(mode, variant)].append(res)
    return {f"{m}/{v}": _analyse_run(rows_by_run[(m, v)], ex, m, v) for m, v, _, ex in plan}


def _run_sync(coro_factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["v"] = asyncio.run(coro_factory())
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


def run_evaluation(mode: str = "spec", cases: Optional[Iterable[Any]] = None,
                   progress_callback: Optional[Callable[[dict], None]] = None, use_cache: bool = True,
                   analyze: Optional[Callable] = None, variants: Iterable[str] = ("spec",), *,
                   write: bool = True, results_dir: Optional[Path] = None) -> dict:
    """Run the backtest. ``mode`` in spec|strict|both; ``variants`` from :data:`VARIANTS`.

    ``analyze`` is an injectable ``analyze_company``-compatible callable (sync or async); default is
    ``graph.pipeline.analyze_company``. Returns the full results dict and (``write=True``) writes
    ``evaluation_report.md`` + ``evaluation_results.json`` into ``results_dir`` (default evaluation/results).
    """
    if mode not in ("spec", "strict", "both"):
        raise ValueError("mode must be spec|strict|both")
    variants = list(dict.fromkeys(variants)) or ["spec"]
    for v in variants:
        if v not in VARIANTS:
            raise ValueError(f"unknown variant {v!r}; known: {sorted(VARIANTS)}")
    modes = ["spec", "strict"] if mode == "both" else [mode]
    case_list = _resolve_cases(cases)
    partial = cases is not None and {c['ticker'] for c in case_list} != {c['ticker'] for c in ALL_CASES}
    chash = code_hash()
    runs = _run_sync(lambda: _run_all(case_list, modes, variants, analyze, use_cache, progress_callback, chash))
    head_key = "spec/spec" if "spec/spec" in runs else None
    results = {
        "metadata": _metadata(chash, analyze is not None, partial, [c["ticker"] for c in case_list], modes, variants),
        "headline_key": head_key,
        "headline": runs.get(head_key) if head_key else None,
        "runs": runs,
        "disclaimer": DISCLAIMER,
    }
    meta = results["metadata"]
    results["degraded_banner"] = bool(
        any(r["degraded_run"] for r in runs.values()) or not meta["anthropic_key_available"]
        or not meta["jev_key_available"])
    results["report_markdown"] = render_report(results)
    if write:
        out = Path(results_dir) if results_dir else RESULTS_DIR
        out.mkdir(parents=True, exist_ok=True)
        (out / REPORT_NAME).write_text(results["report_markdown"], encoding="utf-8")
        results["report_path"] = str(out / REPORT_NAME)
        results["json_path"] = str(out / JSON_NAME)
        payload = {k: v for k, v in results.items() if k != "report_markdown"}
        (out / JSON_NAME).write_text(json.dumps(_jsonable(payload), indent=2, allow_nan=False), encoding="utf-8")
    return results


def load_last_results(results_dir: Optional[Path] = None) -> Optional[dict]:
    """Load the last written evaluation_results.json (None when absent/corrupt)."""
    path = (Path(results_dir) if results_dir else RESULTS_DIR) / JSON_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    rp = path.with_name(REPORT_NAME)
    try:
        data["report_markdown"] = rp.read_text(encoding="utf-8")
    except Exception:
        pass
    return data


# --------------------------------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------------------------------
def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _fmt(m: dict) -> str:
    """'66.7% (95% CI 30.0-90.3%, 4/6)' or 'n/a (undefined: 0/0)'."""
    if m.get("value") is None:
        return f"n/a (undefined, {m.get('num')}/{m.get('den')})"
    return (f"{_pct(m['value'])} (CI {m['ci_low'] * 100:.1f}-{m['ci_high'] * 100:.1f}%, {m['num']}/{m['den']})"
            if m.get("ci_low") is not None else f"{_pct(m['value'])} (CI n/a)")


def _cell(s: Any) -> str:
    return str(s if s not in (None, "") else "-").replace("|", "/").replace("\n", " ")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _metrics_table(runs: list[dict]) -> list[str]:
    rows = []
    for r in runs:
        m = r["metrics"]
        rows.append([r["key"] + (" (HEADLINE)" if r["is_headline"] else " (sensitivity)"), m["n"],
                     f"{m['tp']}/{m['fp']}/{m['tn']}/{m['fn']}", _fmt(m["precision"]), _fmt(m["recall"]),
                     _pct(m["f1"]["value"]) + " (CI n/a)" if m["f1"]["value"] is not None else "n/a (undefined)",
                     _fmt(m["fpr"]), _fmt(m["accuracy"])])
    return _table(["Run (mode/variant)", "n evaluable", "TP/FP/TN/FN", "Precision", "Recall", "F1", "FPR", "Accuracy"], rows)


def _case_table(run: dict) -> list[str]:
    rows = []
    for r in run["cases"]:
        fd = r.get("first_detection_filing_date") or "-"
        if r.get("first_detection_year"):
            fd = f"FY{r['first_detection_year']} (filed {fd})"
        elif fd != "-":
            fd = f"filed {fd}"
        pred = "-" if r["predicted"] is None else ("Fraud-risk (High/Critical)" if r["predicted"] else "Not flagged")
        deg = "; ".join(r.get("degraded") or []) or "none"
        rows.append([r["company"], f"{r['end_year']} (as_of {r['as_of']})", pred, r["actual"],
                     r["risk_grade"] or "ERROR", fd, r["key_signal"] if r["status"] == "OK" else r["error"],
                     r["status"] + (f" ({r['outcome']})" if r.get("outcome") else ""), _clip(deg, 300),
                     "yes" if r["pre_revelation_valid"] else "NO (filed after revelation)"])
    for e in run["excluded"]:
        rows.append([e["company"] or e["ticker"], "-", "-", "Fraud" if e["ground_truth"] else "Clean", "-", "-",
                     e["reason"], "EXCLUDED", "-", "-"])
    return _table(["Company", "Year", "Predicted", "Actual", "Risk Grade", "First Detection", "Key Signal", "status",
                   "degraded", "Pre-revelation valid"], rows)


def _verdict(run: dict) -> list[str]:
    m, b = run["metrics"], run["baselines"]
    if m["n"] == 0:
        return ["**RESULT: NO EVALUABLE CASES.** Every case errored or was excluded; nothing can be concluded."]
    concerns = []
    rec, prec, fpr = m["recall"]["value"], m["precision"]["value"], m["fpr"]["value"]
    if rec is not None and rec <= 0.5:
        concerns.append(f"recall is {_pct(rec)}: the system misses at least half of the fraud cases")
    if rec is None:
        concerns.append("recall is undefined (no evaluable fraud case)")
    if prec is not None and prec < 0.5:
        concerns.append(f"precision is {_pct(prec)}: most High/Critical alerts are false")
    if prec is None and m["tp"] + m["fp"] == 0:
        concerns.append("the system never produced a High/Critical grade, so precision is undefined")
    if fpr is not None and fpr >= 0.25:
        concerns.append(f"false-positive rate is {_pct(fpr)}: it flags at least a quarter of the clean companies")
    acc_sys, acc_ac = m["accuracy"]["value"], b["always_clean"]["accuracy"]["value"]
    if acc_sys is not None and acc_ac is not None and acc_sys <= acc_ac:
        concerns.append(f"accuracy {_pct(acc_sys)} is no better than the trivial 'always predict clean' baseline ({_pct(acc_ac)})")
    f_sys, f_b = m["f1"]["value"], b["beneish_only"]["f1"]["value"]
    if f_b is not None and (f_sys is None or f_sys <= f_b):
        concerns.append(f"F1 ({_pct(f_sys)}) does not beat the Beneish-only baseline ({_pct(f_b)})")
    wc = run["worst_case_metrics"]
    lines = []
    if concerns:
        lines.append("**RESULT: WEAK / BAD on this sample.** " + "; ".join(concerns) + ".")
    else:
        lines.append("**RESULT: no automatic failure trigger fired on this sample (triggers: recall <= 50%, precision < 50%, "
                     "FPR >= 25%, accuracy <= always-clean, F1 <= Beneish-only). n is tiny and CIs are wide; this is not "
                     "evidence of general performance. Read the attribution audit before quoting any number.**")
    if run["n_error"] or run["n_excluded"]:
        lines.append(f"{run['n_error']} case(s) ERRORED and {run['n_excluded']} were EXCLUDED, so the matrix covers only "
                     f"{m['n']} cases. Worst case (errored fraud counted as misses, errored clean as false alarms): "
                     f"recall {_fmt(wc['recall'])}, FPR {_fmt(wc['fpr'])}.")
    return lines


def _slice_section(text: str, start: str, end: Optional[str]) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start)) if end else -1
    return text[i: j if j > 0 else len(text)].strip()


def _limitations(results: dict) -> list[str]:
    n_fraud = sum(1 for c in ALL_CASES if c["ground_truth"] == 1)
    invalid = [c for c in ALL_CASES if c["ground_truth"] == 1 and not c["pre_revelation_valid"]]
    fs = [c for c in ALL_CASES if c.get("fraud_nature") == "financial_statement"]
    meta = results["metadata"]
    L = ["## LIMITATIONS AND CONTAMINATION (READ BEFORE QUOTING ANY NUMBER)", "",
         "> **WARNING: these results are NOT clean out-of-sample evidence.** The sample is 12 hand-picked, famous cases, "
         "some rules were fitted with evaluation-set filings in view (ledger below), and most fraud filings post-date the fraud's "
         "public revelation.", ""]
    L += [
        f"1. **Look-ahead: {len(invalid)} of {n_fraud} fraud filings post-date public revelation** "
        f"({', '.join(c['ticker'] for c in invalid)}). The spec (headline) run therefore sees information that was already public; "
        "a 'detection' there is not early warning. Only Enron and WorldCom filings precede revelation "
        "(WorldCom disclosed an SEC document request two days before its 10-K405).",
        f"2. **Only {len(fs)} of {n_fraud} fraud cases are financial-statement frauds** ({', '.join(c['ticker'] for c in fs)}). "
        "Nikola, Lordstown and Virgin Galactic are disclosure/claims cases (product claims, pre-orders, safety statements); a "
        "statement-based detector is not expected to fire on them. Virgin Galactic's fraud label is WEAK (settled class action, "
        "no SEC accounting finding). Luckin's FY2019 20-F was produced after the internal investigation; whether it still "
        "contains the fabricated sales was not verified.",
        "3. **The clean set is six surviving US mega-caps, not matched** on size, industry or distress (AAPL, MSFT, JNJ, PG, BRK-B, "
        "MMM). 'Clean' means only 'no known accounting fraud/restatement' (absence of evidence from a web search). Survivorship "
        "and selection bias apply to both sets; BRK-B is an insurer to which Beneish/Altman apply poorly.",
        "4. **n = 12, so confidence intervals are wide** (6 vs 6). Differences between variants/baselines of one or two cases "
        "are not statistically meaningful.",
        "5. **The strict run has a tiny n**: Luckin is excluded (no pre-revelation annual report), Nikola and Lordstown fall back to "
        "SPAC-shell 10-Ks (no operating business), leaving effectively 2 operating-company fraud filings (Enron, WorldCom) "
        "plus Virgin Galactic FY2020. Treat strict numbers as anecdotes.",
        "6. **Detection timing is quantised** to annual filing dates (D14) and is only meaningful for pre-revelation filings.",
    ]
    if not meta["anthropic_key_available"] or not meta["jev_key_available"]:
        miss = [n for n, ok in (("ANTHROPIC_API_KEY", meta["anthropic_key_available"]),
                                ("JEV_API_KEY", meta["jev_key_available"])) if not ok]
        L.append(f"7. **Degraded run: {', '.join(miss)} not available.** LLM specificity scoring, LLM narrative and Jev confidence "
                 "scoring are unavailable, so the language agent's specificity flag is off, Jev-gated 'Critical' grades are "
                 "unreachable (capped at High), and any result here understates what the full system would do (or does).")
    L += ["", "### Tuning / contamination ledger (reproduced from docs/TUNING_LEDGER.md)", ""]
    ledger_p = ROOT / "docs" / "TUNING_LEDGER.md"
    try:
        ledger = ledger_p.read_text(encoding="utf-8")
        body = ledger.split("\n", 1)[1] if ledger.startswith("# ") else ledger
        L += [ln.replace("# ", "#### ", 1) if ln.startswith("## ") else ln for ln in body.strip().splitlines()]
    except OSError:
        L.append("**docs/TUNING_LEDGER.md could not be read at report time - the ledger is NOT reproduced; treat the "
                 "contamination as unknown.**")
    L += ["", "### Case validity findings (from docs/case_research.md and evaluation/fraud_cases.py)", ""]
    for c in ALL_CASES:
        if c["ground_truth"] == 1:
            L.append(f"* **{c['ticker']}** ({'valid' if c['pre_revelation_valid'] else 'INVALID'}; "
                     f"{c.get('fraud_nature')}; label: {c.get('label_confidence')}): {c.get('validity_note')}")
    try:
        cr = (ROOT / "docs" / "case_research.md").read_text(encoding="utf-8")
        s2 = _slice_section(cr, "## 2. Corrections", "## 3.")
        s3 = _slice_section(cr, "## 3. Look-ahead", "## 4.")
        for sec in (s2, s3):
            if sec:
                L += ["", sec.replace("\n## ", "\n#### ").replace("## ", "#### ", 1)]
    except OSError:
        L.append("(docs/case_research.md could not be read at report time.)")
    return L


def render_report(results: dict) -> str:
    meta = results["metadata"]
    runs = list(results["runs"].values())
    head = results.get("headline")
    L = ["# Retrospective Validation Report - forensic-filing-agent", "",
         f"Generated {meta['timestamp_utc']} (UTC). Code hash `{meta['code_hash'][:16]}`. "
         f"Analysis source: {meta['analyze_source']}.", ""]
    if results.get("degraded_banner"):
        reasons = []
        if not meta["anthropic_key_available"]:
            reasons.append("ANTHROPIC_API_KEY missing (no LLM specificity/narrative)")
        if not meta["jev_key_available"]:
            reasons.append("JEV_API_KEY missing (no Jev confidence; Critical unreachable)")
        comps = sorted({c for r in runs for c in r["degraded_components"]})
        if comps:
            reasons.append("degraded components seen: " + "; ".join(comps))
        if any(r["n_error"] for r in runs):
            reasons.append("one or more cases errored")
        L += ["> **DEGRADED RUN - results are NOT the full system's performance.** " + " | ".join(reasons), ""]
    if meta.get("partial_case_subset"):
        L += [f"> **PARTIAL RUN: only {len(meta['cases_requested'])} case(s) evaluated "
              f"({', '.join(meta['cases_requested'])}); headline metrics are not the 12-case evaluation.**", ""]
    L += ["> **Contamination warning:** 4 of 6 fraud filings post-date revelation, only 3 of 6 are financial-statement frauds, the "
          "clean set is not matched, n=12. See [Limitations and contamination](#limitations-and-contamination-read-before-quoting-any-number).",
          ""]
    L += ["## Headline (mode spec, variant spec)", ""]
    if head is None:
        L += ["**The headline run (spec/spec) was not part of this invocation; only labelled sensitivity runs below.**", ""]
    else:
        L += _verdict(head) + [""]
        m = head["metrics"]
        L += _table(["n evaluable", "TP", "FP", "TN", "FN", "Precision", "Recall", "F1", "FPR"],
                    [[m["n"], m["tp"], m["fp"], m["tn"], m["fn"], _fmt(m["precision"]), _fmt(m["recall"]),
                      _pct(m["f1"]["value"]) + " (CI n/a)" if m["f1"]["value"] is not None else "n/a (undefined)",
                      _fmt(m["fpr"])]])
        L += ["", "Positive prediction = risk_grade High or Critical. CIs are exact Wilson 95% intervals; F1 has no closed-form "
              "Wilson interval. A case whose analysis errored or returned grade 'Unknown' is status ERROR and is excluded "
              "from the matrix (never counted as negative).", ""]
        if head["errors"]:
            L += ["**Errored cases (excluded):** " + "; ".join(f"{e['ticker']}: {e['error']}" for e in head["errors"]), ""]
        wc = head["worst_case_metrics"]
        if head["n_error"]:
            L += [f"Worst-case view: TP/FP/TN/FN = {wc['tp']}/{wc['fp']}/{wc['tn']}/{wc['fn']}, recall {_fmt(wc['recall'])}, "
                  f"FPR {_fmt(wc['fpr'])}.", ""]
        L += ["### Case-by-case (headline)", ""] + _case_table(head) + [""]
    L += ["## All runs: headline and sensitivity", ""]
    L += ["Only spec/spec is the headline. Every other row is a labelled sensitivity run (strict = point-in-time re-run of "
          "look-ahead cases with the last pre-revelation filing; no_passive = pre-registered variant without the "
          "passive-voice flag, declared before the run, see ledger P2/P3).", ""]
    L += _metrics_table(runs) + [""]
    for r in runs:
        if r["is_headline"]:
            continue
        L += [f"### Sensitivity run {r['key']}", ""]
        if r["mode"] == "strict":
            L += [f"Tiny-n strict run: {r['n_evaluable']} evaluable case(s). {r['n_excluded']} excluded."]
        L += _verdict(r) + [""]
        if r["excluded"]:
            L += ["**Excluded from this run:** " + "; ".join(f"{e['ticker']} ({e['reason']})" for e in r["excluded"]), ""]
        L += _case_table(r) + [""]
    L += ["## Baselines (same evaluable cases)", ""]
    rows = []
    for r in runs:
        b = r["baselines"]
        for name, key in (("System", None), ("Beneish-only (M > -1.78 in focus year)", "beneish_only"),
                          ("Always predict clean", "always_clean")):
            m = r["metrics"] if key is None else b[key]
            rows.append([r["key"], name, f"{m['tp']}/{m['fp']}/{m['tn']}/{m['fn']}", _fmt(m["precision"]), _fmt(m["recall"]),
                         _fmt(m["fpr"]), _fmt(m["accuracy"])])
    L += _table(["Run", "Predictor", "TP/FP/TN/FN", "Precision", "Recall", "FPR", "Accuracy"], rows)
    for r in runs:
        if r["baselines"]["beneish_unavailable_cases"]:
            L += ["", f"{r['key']}: Beneish unavailable (counted as 'predict clean') for: "
                  + ", ".join(r["baselines"]["beneish_unavailable_cases"]) + "."]
    L += ["", "## Secondary metric: paired suspicion-score comparison (fraud vs matched control)", "",
          "Cutoff-free and descriptive. Per matched pair: focus-year temporal suspicion score of the fraud case vs its control. "
          "wins = fraud higher, ties = equal, losses = fraud lower; exact two-sided sign test on non-tied pairs; paired AUC "
          f"(ties 0.5) with a percentile bootstrap 95% CI ({BOOTSTRAP_RESAMPLES:,} resamples of pairs, seed {BOOTSTRAP_SEED}).", ""]
    for r in runs:
        pc = r["paired"]
        if not pc["available"]:
            L += [f"* {r['key']}: **n/a** - {pc['note']}" + (f" ({len(pc['excluded_pairs'])} pair(s) excluded: "
                  + "; ".join(f"{e['fraud']}/{e['control']}: {e['reason']}" for e in pc["excluded_pairs"]) + ")"
                  if pc["excluded_pairs"] else "")]
            continue
        p = pc["sign_test_p_two_sided"]
        L += [f"* {r['key']}: {pc['n_pairs']} pairs, **{pc['wins']} wins / {pc['ties']} ties / {pc['losses']} losses**; sign test "
              f"p = {'n/a (no non-tied pair)' if p is None else f'{p:.4f}'} (n non-tied = {pc['n_non_tied']}); paired AUC = "
              f"{pc['paired_auc']:.3f} (95% bootstrap CI {pc['auc_ci_low']:.3f}-{pc['auc_ci_high']:.3f})."]
        L += [""] + _table(["Fraud", "Control", "Fraud score", "Control score", "Result"],
                           [[x["fraud"], x["control"], x["fraud_score"], x["control_score"], x["result"]] for x in pc["pairs"]])
        if pc["excluded_pairs"]:
            L += ["", "Excluded pairs: " + "; ".join(f"{e['fraud']}/{e['control']}: {e['reason']}" for e in pc["excluded_pairs"])]
        L += [""]
    L += ["", "### Beneish availability (focus year)", ""]
    L += _table(["Run", "Fraud cases with Beneish", "Clean cases with Beneish", "Beneish unavailable on (fraud)"],
                [[r["key"], _fmt(r["beneish_availability"]["fraud"]), _fmt(r["beneish_availability"]["clean"]),
                  ", ".join(r["beneish_availability"]["fraud"]["unavailable_cases"]) or "-"] for r in runs])
    L += ["", "## Per-agent contribution", "",
          "Flagging = agent severity Medium or High. Unique catch = fraud case flagged by this agent and by no other of agents 1-4. "
          "Plain flag rate (fraud) and false-alarm rate (clean) are reported alongside.", ""]
    for r in runs:
        c = r["contribution"]
        L += [f"### {r['key']} (fraud n={c['n_fraud']}, clean n={c['n_clean']}, detected n={c['n_true_positive']})", ""]
        rows = []
        for a, e in c["agents"].items():
            uq = e.get("unique_catches")
            rows.append([a, _fmt(e["flag_rate_fraud"]), _fmt(e["false_alarm_rate_clean"]),
                         "n/a (derived)" if uq is None else f"{len(uq)} ({', '.join(uq) or '-'})",
                         "n/a" if uq is None else _fmt(e["unique_catch_pct_of_fraud"]),
                         "n/a" if uq is None else _fmt(e["unique_catch_pct_of_detected"]),
                         ", ".join(e["unavailable_cases"]) or "-"])
        L += _table(["Agent", "Flag rate on fraud", "False-alarm rate on clean", "Unique catches", "Unique % of all fraud",
                     "Unique % of detected", "Unavailable on"], rows)
        L += ["", "Decisive agent (severity High among true positives):", ""]
        L += _table(["Agent", "High on TPs", "Cases"],
                    [[a, f"{d['count']}/{d['of_true_positives']}", ", ".join(d["cases"]) or "-"]
                     for a, d in r["decisive_agents"].items()]) + [""]
    L += ["## Detection timing (D14)", ""]
    for r in runs:
        t = r["timing"]
        L += [f"### {r['key']}", ""]
        if not t["cases"]:
            L += ["No true positives, so no detection timing exists.", ""]
            continue
        L += _table(["Case", "First detection filing", "Revelation", "Collapse", "Months before revelation",
                     "Months before collapse", "Note"],
                    [[c["ticker"], f"FY{c['first_detection_year']} filed {c['first_detection_filing_date']}",
                      c["public_revelation_date"], c["collapse_date"], c["months_before_revelation"],
                      c["months_before_collapse"],
                      c["label"] + ("" if c["pre_revelation_valid"] else " (filing post-dates revelation: not a valid early-warning test)")]
                     for c in t["cases"]])
        avg = t["average_months_early_before_revelation"]
        L += ["", f"Average months early (before revelation, early cases only): "
              f"{'n/a - no case was detected early' if avg is None else avg} "
              f"(n early = {t['n_early']}, n not early = {t['n_not_early']}; not-early cases are shown above but excluded "
              "from the average). Positive = early, negative = after revelation.", "", "*" + t["caveat"] + "*", ""]
    L += ["## Breakdown by fraud nature", "",
          "Only financial-statement frauds are in scope for a statement-based detector; disclosure/claims cases are reported separately.", ""]
    for r in runs:
        L += [f"### {r['key']}", ""]
        L += _table(["Fraud nature", "Cases", "Evaluable", "TP", "Recall", "Case detail"],
                    [[k, v["n_cases"], v["n_evaluable"], v["tp"], _fmt(v["recall"]),
                      "; ".join(f"{c['ticker']}={c['risk_grade'] or c['status']}" for c in v["cases"])]
                     for k, v in r["fraud_nature"].items()]) + [""]
    L += ["## Run metadata", ""]
    L += _table(["Field", "Value"], [
        ["Timestamp (UTC)", meta["timestamp_utc"]], ["Code hash (sha256)", meta["code_hash"]],
        ["Code hash covers", ", ".join(meta["code_hash_files"])],
        ["ANTHROPIC key available", meta["anthropic_key_available"]], ["JEV key available", meta["jev_key_available"]],
        ["Analysis source", meta["analyze_source"]], ["Modes / variants", f"{meta['modes']} / {meta['variants']}"],
        ["Versions", "; ".join(f"{k}={v}" for k, v in meta["versions"].items() if v)]])
    L += ["", "Degraded components per run (union over cases):", ""]
    for r in runs:
        comps = r["degraded_components"]
        L.append(f"* {r['key']}: " + ("none" if not comps else "; ".join(f"{k} [{', '.join(v)}]" for k, v in comps.items())))
    L += [""] + _limitations(results) + ["", "## Disclaimer", "", DISCLAIMER, ""]
    return "\n".join(L)


# --------------------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------------------
def load_cases_from(module: str, var: str = "ALL_CASES") -> list[dict]:
    """Load a case list from a module path (``evaluation.holdout_cases``) or a ``.py`` file path. Existing API is
    untouched: the result is passed to :func:`run_evaluation` as ``cases``."""
    import importlib
    import importlib.util
    if module.endswith(".py") or os.sep in module or "/" in module:
        spec = importlib.util.spec_from_file_location(Path(module).stem, str(module))
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load cases module from {module!r}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    else:
        mod = importlib.import_module(module)
    cases = getattr(mod, var, None)
    if not isinstance(cases, (list, tuple)) or not all(isinstance(c, dict) for c in cases):
        raise ValueError(f"{module}.{var} is not a list of case dicts")
    return [dict(c) for c in cases]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the retrospective validation (writes evaluation/results/*).")
    ap.add_argument("--mode", default="spec", choices=["spec", "strict", "both"])
    ap.add_argument("--cases", default=None, help="comma-separated tickers, e.g. AAPL,LK (default: all 12)")
    ap.add_argument("--variants", default="spec", help="comma-separated: spec,no_passive")
    ap.add_argument("--no-cache", action="store_true", help="ignore and overwrite cached case results")
    ap.add_argument("--cases-module", default=None,
                    help="module path or .py file with the case list (e.g. evaluation.holdout_cases); default: the 12 registry cases")
    ap.add_argument("--cases-var", default="ALL_CASES", help="name of the list in --cases-module (default ALL_CASES)")
    ap.add_argument("--results-dir", default=None, help="write report/JSON here instead of evaluation/results")
    a = ap.parse_args(argv)
    cases = [c.strip() for c in a.cases.split(",") if c.strip()] if a.cases else None
    if a.cases_module:
        loaded = load_cases_from(a.cases_module, a.cases_var)
        if cases:  # --cases then filters the loaded list by ticker
            want = {c.upper() for c in cases}
            loaded = [c for c in loaded if str(c.get("ticker", "")).upper() in want]
        cases = loaded
    variants = [v.strip() for v in a.variants.split(",") if v.strip()]

    def cb(ev: dict) -> None:
        print(f"[{ev.get('index')}/{ev.get('total')}] {ev.get('status')}: {ev.get('message')}", flush=True)

    res = run_evaluation(mode=a.mode, cases=cases, progress_callback=cb, use_cache=not a.no_cache, variants=variants,
                         results_dir=Path(a.results_dir) if a.results_dir else None)
    for k, r in res["runs"].items():
        m = r["metrics"]
        print(f"{k}: n={m['n']} TP/FP/TN/FN={m['tp']}/{m['fp']}/{m['tn']}/{m['fn']} precision={_fmt(m['precision'])} "
              f"recall={_fmt(m['recall'])} FPR={_fmt(m['fpr'])} errors={r['n_error']} excluded={r['n_excluded']}")
    print("report:", res.get("report_path"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
