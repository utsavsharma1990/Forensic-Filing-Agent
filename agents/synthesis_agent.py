"""Agent 6: synthesis (Jev scoring, deterministic risk grade, smoking guns, narrative).

Design (CONTRACTS section 6, frozen before evaluation):
* The risk grade is computed by :func:`compute_risk_grade`, a pure rule function. The LLM never sets the grade.
* Smoking guns are built deterministically from structured ``evidence`` items supplied by agents 1-5.
* The narrative is written by Claude Sonnet from a compact JSON evidence packet; every numeral in the output must appear
  in the packet (:func:`validate_numbers`) or the deterministic 3-paragraph template is used instead.
* Missing keys are a normal state; nothing here raises and nothing is fabricated.

Assumed agent-result fields (see tests): ``severity`` ("None|Low|Medium|High"), ``unavailable`` (bool), ``flags_fired``,
``flags_by_year`` ({year: [flag]}), ``focus_year``, ``key_finding``, ``data_quality.unavailable``, ``degraded``, and
``evidence``: list of ``{"flag","year","metric","value","display","numbers":[...],"peer_pct"?, "magnitude"?}``.
Temporal result: ``timeline`` (list of {year, signal_change, ...}), ``signal_trajectory``, ``first_detection_year``,
``years_of_elevated_risk``.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from prompts.templates import (
    NARRATIVE_USER_TEMPLATE,
    PATTERN_TABLE,
    SYNTHESIS_SYSTEM_PROMPT,
    WATCH_INDICATORS,
)
from tools.common import get_logger, risk_rank
from tools.llm import llm_text

try:  # Jev is optional at import time; failures are handled at call time
    from tools import jev_scorer
except Exception:  # pragma: no cover
    jev_scorer = None  # type: ignore[assignment]

log = get_logger("forensic.synthesis")

CORE_AGENTS = ("quantitative", "language", "network", "peer")
ALL_AGENTS = CORE_AGENTS + ("temporal",)
AGENT_ORDER = {a: i for i, a in enumerate(ALL_AGENTS)}
HARD_FLAGS = frozenset({"quantitative.beneish", "network.going_concern", "network.restatement"})
HARD_COMBO = frozenset({"network.auditor_change", "network.cfo_change"})  # both in the same year = hard
CRITICAL_JEV_THRESHOLD = 80.0
MAX_SMOKING_GUNS = 3
# Flags that are recorded for transparency but are not risk evidence on their own: passive voice (v2: YoY-increase form,
# still the weakest language signal) and any evidence item an agent marks ``informational`` (peer outliers in the
# non-manipulation direction). They are surfaced as smoking guns only when no genuine candidate exists.
INFORMATIONAL_FLAGS = frozenset({"language.passive_voice"})
MAX_NARRATED_PCT = 1000.0  # a peer-relative percentage beyond this is a tiny-denominator artefact: never narrated


# ------------------------------------------------------------------------------------------------ helpers
def _emit(cb: Optional[Callable[[dict], None]], event: dict) -> None:
    if cb is None:
        return
    try:
        cb(event)
    except Exception:  # a UI callback must never break the analysis
        pass


def _year_key(y: Any) -> Optional[int]:
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _is_unavailable(res: Any) -> bool:
    return not isinstance(res, dict) or not res or bool(res.get("unavailable"))


def _severity(res: Any) -> str:
    if _is_unavailable(res):
        return "Unavailable"
    sev = str(res.get("severity", "None")).strip().capitalize()
    return sev if sev in ("None", "Low", "Medium", "High") else "None"


def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


# ------------------------------------------------------------------------------------------------ grade
def compute_risk_grade(
    agents_flagging: int,
    agents_high: int,
    escalation: bool,
    jev_mean_confidence: Optional[float],
    jev_available: bool,
    focus_year_flagged: bool = False,
) -> dict:
    """CONTRACTS section 6 grading rule (pure function), v2 wording (docs/V2_CHANGELOG_agents.md B3).

    Critical: agents_high >= 3 AND Jev mean confidence > 80 (Jev unavailable => cap at High, note ``critical_blocked``).
    High:     (agents_flagging >= 2 AND escalation) OR agents_high >= 3.
    Medium:   agents_flagging >= 1 (not High/Critical) OR (escalation AND >= 1 flag fired IN THE FOCUS YEAR).
    Low:      otherwise.

    ``escalation`` is the temporal FOCUS-YEAR ``signal_change == "Escalating"`` only (never the whole-series
    trajectory: a trajectory is a statement about the past series, the grade is about the focus year).

    Returns ``{"grade", "rationale", "degraded"}``; ``rationale`` names the rule that fired.
    """
    degraded: list[str] = []
    jev_ok = bool(jev_available) and jev_mean_confidence is not None
    ctx = (
        f"agents flagging (Medium/High severity): {agents_flagging} of 4; agents at High severity: {agents_high}; "
        f"focus-year escalation: {'yes' if escalation else 'no'}"
    )
    if agents_high >= 3:
        if jev_ok and jev_mean_confidence > CRITICAL_JEV_THRESHOLD:  # type: ignore[operator]
            return {
                "grade": "Critical",
                "rationale": f"Critical rule fired: {agents_high} agents at High severity and mean Jev confidence "
                f"{jev_mean_confidence:.1f} exceeds {CRITICAL_JEV_THRESHOLD:.0f} ({ctx}).",
                "degraded": degraded,
            }
        if not jev_ok:
            degraded.append("critical_blocked: Jev unavailable")
            why = "Jev confidence is unavailable, so Critical cannot be reached and the grade is capped at High"
        else:
            why = (
                f"mean Jev confidence {jev_mean_confidence:.1f} does not exceed {CRITICAL_JEV_THRESHOLD:.0f}, "
                "so the Critical gate is not met"
            )
        return {
            "grade": "High",
            "rationale": f"High rule fired: {agents_high} agents at High severity (3+ agents high); {why} ({ctx}).",
            "degraded": degraded,
        }
    if agents_flagging >= 2 and escalation:
        return {
            "grade": "High",
            "rationale": f"High rule fired: 2+ agents flagging together with focus-year escalation ({ctx}).",
            "degraded": degraded,
        }
    if agents_flagging >= 1:
        return {
            "grade": "Medium",
            "rationale": f"Medium rule fired: {agents_flagging} agent(s) flagging without the conditions for High ({ctx}).",
            "degraded": degraded,
        }
    if escalation and focus_year_flagged:
        return {
            "grade": "Medium",
            "rationale": f"Medium rule fired: focus-year escalation with at least one flag fired in the focus year, no agent at Medium+ severity in the focus year ({ctx}).",
            "degraded": degraded,
        }
    return {
        "grade": "Low",
        "rationale": f"Low: no agent at Medium+ severity in the focus year and no qualifying focus-year escalation ({ctx}).",
        "degraded": degraded,
    }


def _escalation(temporal: Any, focus_year: Optional[int]) -> bool:
    """True iff the temporal FOCUS-YEAR ``signal_change`` is "Escalating" (v2 B3: the series trajectory is NOT consulted)."""
    if _is_unavailable(temporal):
        return False
    focus_change = temporal.get("focus_signal_change")
    if isinstance(focus_change, str) and focus_change.strip():
        return focus_change.strip().lower() == "escalating"
    for row in temporal.get("timeline") or []:
        if isinstance(row, dict) and _year_key(row.get("year")) == focus_year:
            return str(row.get("signal_change", "")).strip().lower() == "escalating"
    return False


def _focus_year_flagged(results: dict[str, Any], focus_year: Optional[int]) -> bool:
    """True iff some core agent fired >= 1 (risk) flag in the focus year. Informational outliers are never in flags_by_year."""
    if focus_year is None:
        return False
    for a in CORE_AGENTS:
        r = results.get(a)
        if _is_unavailable(r):
            continue
        for y, fl in (r.get("flags_by_year") or {}).items():
            if _year_key(y) == focus_year and fl:
                return True
    return False


# ------------------------------------------------------------------------------------------------ jev
def _jev_summary(jev_scores: dict) -> tuple[Optional[float], bool]:
    vals = []
    for s in (jev_scores or {}).values():
        if isinstance(s, dict) and s.get("available") and _num(s.get("confidence_score")) is not None:
            vals.append(float(s["confidence_score"]))
    if not vals:
        return None, False
    return sum(vals) / len(vals), True


def _unavailable_jev(agent: str, error: str) -> dict:
    return {
        "evidence_strength": "Unavailable",
        "confidence_score": None,
        "material_change": None,
        "jev_latency_ms": 0,
        "available": False,
        "error": error,
        "model": None,
    }


def _run_jev(results: dict[str, Any], state: dict, cb) -> dict:
    _emit(cb, {"node": "synthesis", "status": "jev", "message": "Running Jev confidence scoring..."})
    try:
        if jev_scorer is None:
            raise RuntimeError("tools.jev_scorer not importable")
        scores = jev_scorer.score_agents(
            {a: (results.get(a) or {}) for a in ALL_AGENTS}, state.get("prior_year_results")
        )
        if not isinstance(scores, dict):
            raise TypeError("score_agents did not return a dict")
        out = {}
        for a in ALL_AGENTS:
            s = scores.get(a)
            out[a] = s if isinstance(s, dict) else _unavailable_jev(a, "no score returned")
        for a, s in scores.items():
            out.setdefault(a, s)
        return out
    except Exception as exc:  # Jev must never crash synthesis
        log.warning("Jev scoring failed: %s", exc)
        return {a: _unavailable_jev(a, f"jev scoring failed: {type(exc).__name__}: {exc}") for a in ALL_AGENTS}


# ------------------------------------------------------------------------------------------------ smoking guns
def match_pattern(flag: str, metric: str = "") -> Optional[dict]:
    """Return the PATTERN_TABLE entry matching ``flag`` (and metric keywords when the entry defines them), else None."""
    m = (metric or "").lower()
    for entry in PATTERN_TABLE:
        if flag in entry.get("flags", []):
            kws = entry.get("metric_keywords") or []
            if not kws or any(k.lower() in m for k in kws):
                return entry
    return None


def _fmt_pct(x: float) -> str:
    s = f"{abs(x):.1f}"
    return s[:-2] if s.endswith(".0") else s


PEER_MEAN_FLOOR = {"ratio_level": 0.05, "days": 1.0}  # |peer mean| below this: a percent-vs-mean is meaningless
_NOTE_BY_FLAG = {
    "quantitative.altman_distress": "a business-distress signal, not evidence of accounting manipulation",
}


def _is_sentence(text: str) -> bool:
    """True when a display string is prose (>= 4 alphabetic words) rather than a bare value such as '95.0 days'."""
    return len(re.findall(r"[A-Za-z]{2,}", text)) >= 4


def _first_sentence(text: str) -> str:
    """First sentence of ``text``; a '. ' inside double quotes or inside a number never ends it."""
    in_q = False
    for i, ch in enumerate(text):
        if ch == '"':
            in_q = not in_q
        elif (ch == "." and not in_q and i > 0 and text[i + 1:i + 2] == " "
              and (text[i - 1].isalnum() or text[i - 1] in ")%") and text[i + 2:i + 3].isupper()
              and not re.search(r"(?:^|[\s(])[A-Za-z]{1,3}$", text[:i])):  # not initials / abbreviations (L., Mr.)
            return text[:i]
    return text


def _clean_body(text: Any) -> str:
    t = " ".join(str(text).split())
    t = t.replace("...", "…")  # ellipsis markers become one character so '..' never appears
    t = re.sub(r"\.{2,}", ".", t)  # doubled periods (the unicode ellipsis is untouched)
    t = re.sub(r"\s+([,;:.])", r"\1", t)
    return t.strip().rstrip(" .;,:")


def _peer_clause(ev: dict) -> str:
    """Comparison against the peer mean that is meaningful for the metric's unit; '' when none is."""
    flag = str(ev.get("flag", ""))
    peer = _num(ev.get("peer_pct"))
    kind = ev.get("unit_kind") if ev.get("unit_kind") in ("ratio_level", "pp_difference", "days") else "ratio_level"
    nums = ev.get("numbers") if isinstance(ev.get("numbers"), (list, tuple)) else []
    company = _num(ev.get("value"))
    mean = _num(nums[1]) if flag.startswith("peer.") and len(nums) > 1 else None
    if kind == "pp_difference":
        if company is None or mean is None:
            return ""
        d = (company - mean) * 100.0
        return f", which is {_fmt_pct(d)} pp {'above' if d >= 0 else 'below'} the peer mean of {mean * 100:.1f} pp"
    floor = PEER_MEAN_FLOOR.get(kind, 0.05)
    if mean is not None and abs(mean) < floor:
        if kind == "days" and company is not None:
            d = company - mean
            return f", which is {_fmt_pct(d)} days {'above' if d >= 0 else 'below'} the peer mean of {mean:.1f} days"
        return ""
    if peer is None:
        return ""
    if abs(peer) > MAX_NARRATED_PCT:
        return ", a gap too large to express as a percentage of the peer mean (n/m)"
    return f", which is {_fmt_pct(peer)}% {'above' if peer >= 0 else 'below'} the peer group average"


def _peer_subject(display: Any) -> Optional[str]:
    """'Gross margin 43.2% vs peer mean ...' -> 'gross margin was 43.2%' (None when the text has another shape)."""
    m = re.match(r"^(.+?)\s+([+-]?[\d.,]+(?: ?(?:%|pp|days|x))?)\s+vs peer mean\b", str(display or ""))
    if not m:
        return None
    label = m.group(1)
    if len(label) > 1 and label[1].islower():
        label = label[0].lower() + label[1:]
    return f"{label} was {m.group(2)}"


def format_smoking_gun(ev: dict) -> str:
    """One clean sentence: ``In FY{year}, {finding}[, peer clause][, consistent with {pattern} observed before {case}].``

    Prose displays from the agents are used as the finding (first sentence only); bare values use the spec template
    ``{metric} showed {value}``.  The peer clause is unit-aware (see ``_peer_clause``); output never contains doubled
    periods or stray spaces and always ends with exactly one period.
    """
    year, metric, flag = ev.get("year"), ev.get("metric"), str(ev.get("flag", ""))
    raw = ev.get("display") if ev.get("display") not in (None, "") else ev.get("value")
    raw = " ".join(str(raw).split())
    clause = _peer_clause(ev)
    if flag.startswith("peer.") and " vs peer mean" in raw:
        full = _clean_body(raw.split(":")[0])
        subj = _peer_subject(raw)
        head = f"In FY{year}, {subj if (subj and clause) else full}"
    elif _is_sentence(raw):
        body = _clean_body(_first_sentence(raw))
        head = body if f"FY{year}" in body else f"{body} in FY{year}"
        if flag in _NOTE_BY_FLAG:
            head += f"; {_NOTE_BY_FLAG[flag]}"
    else:
        head = f"In FY{year}, {metric} showed {_clean_body(raw)}"
    parts = head
    if clause and not (flag.startswith("peer.") and " vs peer mean" in raw and not _peer_subject(raw)):
        parts += clause
    pat = match_pattern(flag, str(metric or ""))
    if pat:
        parts += (" and consistent with " if clause else ", consistent with ") + f"{pat['pattern']} observed before {pat['case']}"
    parts = " ".join(parts.split())
    parts = re.sub(r"\s+([,;:.])", r"\1", parts)
    return parts.rstrip(" .;,:") + "."


def is_informational(c: dict) -> bool:
    return bool(c.get("informational")) or str(c.get("flag")) in INFORMATIONAL_FLAGS


def _hard_set(candidates: list[dict]) -> set[tuple]:
    """Identify (agent-independent) hard candidates: HARD_FLAGS, or both HARD_COMBO flags present in the same year."""
    by_year: dict[Any, set] = {}
    for c in candidates:
        by_year.setdefault(c["year"], set()).add(c["flag"])
    combo_years = {y for y, fl in by_year.items() if HARD_COMBO <= fl}
    return {id(c) for c in candidates if c["flag"] in HARD_FLAGS or (c["flag"] in HARD_COMBO and c["year"] in combo_years)}


def _magnitude(c: dict) -> float:
    """Explicit ``magnitude`` if an agent supplies one, else |peer_pct|, else 0 (raw values are not comparable)."""
    m = _num(c.get("magnitude"))
    if m is not None:
        return abs(m)
    p = _num(c.get("peer_pct"))
    if p is not None:
        return abs(p)
    return 0.0  # raw values are not comparable across metrics, so they never rank


def excluded_entity_years(state: Any) -> set[int]:
    """Years flagged ``is_shell`` / ``spac_predecessor`` in ``state["filing_entity_flags"]`` (junk / absence tolerated)."""
    raw = state.get("filing_entity_flags") if isinstance(state, dict) else None
    out: set[int] = set()
    if isinstance(raw, dict):
        for k, rec in raw.items():
            y = _year_key(k)
            if y is not None and isinstance(rec, dict) and (rec.get("is_shell") is True or rec.get("spac_predecessor") is True):
                out.add(y)
    return out


def collect_candidates(results: dict[str, Any], exclude_years: Optional[set[int]] = None) -> list[dict]:
    """Flatten ``evidence`` lists of all agents into candidate dicts (adds ``agent``); drops items lacking value text.

    v2 (B8/B2): evidence from shell / SPAC-predecessor years (``exclude_years``) is not evidence about the operating company
    and is never a smoking gun."""
    cands, seen = [], set()
    exclude_years = exclude_years or set()
    for agent in ALL_AGENTS:
        res = results.get(agent)
        if _is_unavailable(res):
            continue
        for item in res.get("evidence") or []:
            if not isinstance(item, dict) or not item.get("flag"):
                continue
            year = _year_key(item.get("year"))
            has_val = item.get("display") not in (None, "") or item.get("value") not in (None, "")
            if year is None or not item.get("metric") or not has_val or year in exclude_years:
                continue
            key = (agent, item["flag"], year, item["metric"])
            if key in seen:
                continue
            seen.add(key)
            c = dict(item)
            c["agent"], c["year"] = agent, year
            cands.append(c)
    return cands


def rank_candidates(cands: list[dict], focus_year: Optional[int]) -> list[dict]:
    """Deterministic ranking: hard flags, then focus year, then magnitude (desc), then agent order, flag, year, metric."""
    hard = _hard_set(cands)
    return sorted(
        cands,
        key=lambda c: (
            0 if id(c) in hard else 1,
            0 if c["year"] == focus_year else 1,
            -_magnitude(c),
            AGENT_ORDER.get(c["agent"], 99),
            str(c["flag"]),
            c["year"],
            str(c["metric"]),
        ),
    )


def select_smoking_guns(ranked: list[dict], n: int = MAX_SMOKING_GUNS) -> list[dict]:
    """Pick up to ``n`` from the ranked list preferring distinct agents, then distinct flags, then the remainder."""
    genuine = [c for c in ranked if not is_informational(c)]
    if genuine:  # informational items (opposite-direction peer outliers, passive voice) never displace a genuine flag
        ranked = genuine
    chosen: list[dict] = []

    def take(pred):
        for c in ranked:
            if len(chosen) >= n:
                return
            if any(c is x for x in chosen):
                continue
            if pred(c):
                chosen.append(c)

    take(lambda c: c["agent"] not in {x["agent"] for x in chosen})
    take(lambda c: c["flag"] not in {x["flag"] for x in chosen})
    take(lambda c: True)
    # keep rank order in the output
    return sorted(chosen, key=lambda c: next(i for i, r in enumerate(ranked) if r is c))


# ------------------------------------------------------------------------------------------------ number validation
_NUM_RE = re.compile(r"(?<![\d.])\d[\d,]*(?:\.\d+)?")
_FORM_RE = re.compile(r"\b(?:10-K405|10-KSB|10-K|10-Q|20-F|40-F|8-K|DEF\s*14A|S-1|F-1)(?:/A)?\b", re.I)
_LIST_MARK_RE = re.compile(r"(?m)^\s*(?:\(?\d{1,2}[.)]|[-*•])\s+")


def _to_float(tok: str) -> Optional[float]:
    t = tok.replace(",", "").rstrip(".")
    try:
        return float(t)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[str]:
    """Numeral tokens in ``text`` (form names like 10-K and leading list markers ignored)."""
    t = _FORM_RE.sub(" ", text or "")
    t = _LIST_MARK_RE.sub("", t)
    return [m.group(0).rstrip(",") for m in _NUM_RE.finditer(t)]


def collect_numbers(obj: Any) -> list[float]:
    """All numeric values in a JSON-like structure, plus numerals found inside any string (keys included)."""
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        v = _num(obj)
        return [v] if v is not None else []
    if isinstance(obj, str):
        for tok in extract_numbers(obj):
            v = _to_float(tok)
            if v is not None:
                out.append(v)
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(collect_numbers(str(k)) if isinstance(k, (str, int)) else [])
            out.extend(collect_numbers(v))
        return out
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            out.extend(collect_numbers(v))
    return out


def _decimals(tok: str) -> int:
    t = tok.replace(",", "")
    return len(t.split(".")[1]) if "." in t else 0


def validate_numbers(text: str, allowed_numbers) -> list[str]:
    """Return the numerals in ``text`` NOT supported by ``allowed_numbers`` (empty list == valid).

    Tolerances: formatting (12.3 vs 12.30, thousands commas), sign (a fall of 5% vs -5), rounding to the number of decimals
    written in the text (12.3 supports 12.34), and percent scaling of fractions (0.4 supports 40). Years and ordinals are
    ordinary numerals and must be present in ``allowed_numbers`` (the packet carries focus year, timeline years etc.).
    Allowed items may be numbers or numeric strings.
    """
    allowed: list[float] = []
    for a in allowed_numbers or []:
        v = _num(a)
        if v is None and isinstance(a, str):
            v = _to_float(a)
        if v is not None:
            allowed.append(abs(v))
    bad = []
    for tok in extract_numbers(text):
        v = _to_float(tok)
        if v is None:
            continue
        d = _decimals(tok)
        ok = False
        for a in allowed:
            cands = [a] + ([a * 100.0] if a <= 1.5 else [])
            for c in cands:
                if round(c, d) == round(v, d) or abs(c - v) < 1e-9:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            bad.append(tok)
    return bad


# ------------------------------------------------------------------------------------------------ narrative
def _compact_agent(res: Any) -> dict:
    if _is_unavailable(res):
        return {"available": False, "reason": (res or {}).get("error") if isinstance(res, dict) else "no result"}
    dq = (res.get("data_quality") or {}).get("unavailable") or {}
    return {
        "available": True,
        "severity": _severity(res),
        "flags_fired_all_years": res.get("flags_fired"),
        "flags_by_year": {str(k): v for k, v in (res.get("flags_by_year") or {}).items() if v},
        "key_finding": res.get("key_finding"),
        "unavailable_metrics": sorted(str(k) for k in dq),
    }


def build_packet(
    state: dict, results: dict, grade: dict, counts: dict, jev_scores: dict, jev_mean: Optional[float],
    guns: list[dict], gun_texts: list[str], degraded: list[str], focus_year: Optional[int],
) -> dict:
    """Compact evidence packet for the narrative prompt (also the source of allowed numerals)."""
    temporal = results.get("temporal")
    tl = []
    if not _is_unavailable(temporal):
        for row in temporal.get("timeline") or []:
            if isinstance(row, dict):
                tl.append({k: row.get(k) for k in ("year", "suspicion_score", "risk_level", "signal_change")})
    jev = {
        a: {"evidence_strength": s.get("evidence_strength"), "confidence_score": s.get("confidence_score")}
        for a, s in (jev_scores or {}).items()
        if isinstance(s, dict) and s.get("available")
    }
    return {
        "company": state.get("company_name") or state.get("ticker"),
        "ticker": state.get("ticker"),
        "focus_year": focus_year,
        "risk_grade": grade["grade"],
        "grade_rationale": grade["rationale"],
        "counts": counts,
        "agents": {a: _compact_agent(results.get(a)) for a in CORE_AGENTS},
        "temporal": {
            "available": not _is_unavailable(temporal),
            "signal_trajectory": (temporal or {}).get("signal_trajectory") if isinstance(temporal, dict) else None,
            "first_detection_year": (temporal or {}).get("first_detection_year") if isinstance(temporal, dict) else None,
            "years_of_elevated_risk": (temporal or {}).get("years_of_elevated_risk") if isinstance(temporal, dict) else None,
            "key_finding": (temporal or {}).get("key_finding") if isinstance(temporal, dict) else None,
            "timeline": tl,
        },
        "jev": {"available": bool(jev), "mean_confidence": jev_mean, "per_agent": jev},
        "smoking_guns": [
            {
                "text": t,
                "flag": g["flag"],
                "year": g["year"],
                "metric": g["metric"],
                "display": g.get("display"),
                "peer_pct": g.get("peer_pct"),
                "numbers": g.get("numbers"),
            }
            for g, t in zip(guns, gun_texts)
        ],
        "degraded": list(degraded),
    }


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]


def _list_join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def deterministic_narrative(packet: dict, open_flags: list[str]) -> str:
    """Three-paragraph narrative built only from packet content (no LLM, no new numbers)."""
    fy = packet.get("focus_year")
    name = packet.get("company") or "the company"
    agents = packet["agents"]
    avail = [a for a, v in agents.items() if v.get("available")]
    unavail = [a for a, v in agents.items() if not v.get("available")]
    counts = packet["counts"]

    # paragraph 1
    p1 = (
        f"Overall assessment: {name} receives a {packet['risk_grade']} accounting-manipulation risk grade for FY{fy}. "
        f"{packet['grade_rationale']} "
    )
    if avail:
        summ = []
        for a in avail:
            kf = agents[a].get("key_finding")
            summ.append(f"{a} agent severity {agents[a]['severity']}" + (f" ({kf.rstrip('.')})" if kf else ""))
        p1 += "Evidence summary: " + "; ".join(summ) + ". "
    else:
        p1 += "No specialist agent produced usable evidence, so this grade reflects missing evidence rather than a clean result. "
    lim = []
    if unavail:
        lim.append(f"the {_list_join(unavail)} agent(s) were unavailable")
    if not packet["temporal"]["available"]:
        lim.append("temporal analysis was unavailable")
    if not packet["jev"]["available"]:
        lim.append("Jev confidence scoring was unavailable, so agent findings carry no independent confidence weighting")
    dq = sorted({m for a in avail for m in agents[a].get("unavailable_metrics", [])})
    if dq:
        lim.append(f"some metrics could not be computed ({_list_join(dq[:6])})")
    for d in packet["degraded"]:
        if d.startswith("critical_blocked"):
            lim.append("the Critical grade was blocked because Jev confidence was unavailable")
    p1 += ("Limitations: " + "; ".join(lim) + ". ") if lim else "No agent or component was reported as unavailable. "
    p1 += "These are statistical risk indicators, not proof of misconduct."

    # paragraph 2
    guns = packet["smoking_guns"]
    if guns:
        p2 = "The most significant risk factors are: " + " ".join(g["text"] for g in guns) + " "
    else:
        flagged = [(a, agents[a]) for a in avail if agents[a]["severity"] in ("Medium", "High", "Low")]
        if flagged:
            p2 = "No structured evidence items were available to quantify the specific findings, but the agents report: " + "; ".join(
                f"{a} ({v['severity']}): {v.get('key_finding') or 'no key finding'}" for a, v in flagged
            ) + ". "
        else:
            p2 = "No agent reported a flagged risk factor in the focus year, so there are no specific risk factors to highlight. "
    distress = [f for f in open_flags if f in ("quantitative.altman_distress", "network.going_concern")]
    manip = [f for f in open_flags if f not in distress]
    if distress and manip:
        p2 += "Both manipulation-risk and business-distress signals are open; they are different failure modes and should be assessed separately. "
    elif distress:
        p2 += "Open signals are distress-type (business failure risk) rather than manipulation-type, which call for different follow-up. "
    sevs = {agents[a]["severity"] for a in avail}
    if ("High" in sevs or "Medium" in sevs) and ("None" in sevs):
        p2 += "Agents disagree: some report no flags while others do, so the evidence is mixed rather than uniform."
    p2 = p2.strip()

    # paragraph 3
    if open_flags:
        inds = [WATCH_INDICATORS[f] for f in sorted(set(open_flags)) if f in WATCH_INDICATORS]
        p3 = "What to watch: in the next filings monitor " + _list_join(inds) + ". Escalation would be signalled by additional flags appearing; resolution by these indicators normalising."
    else:
        p3 = "What to watch: no flags are open in the focus year, so monitor the next filing for the first appearance of any flag (receivables versus revenue, accruals, auditor or CFO changes, restatements, related-party growth)."
    traj = packet["temporal"].get("signal_trajectory")
    if traj:
        p3 += f" The temporal agent reports a {traj} signal trajectory."
    return "\n\n".join([p1, p2, p3])


def build_narrative(packet: dict, open_flags: list[str]) -> tuple[str, list[str]]:
    """Return (narrative, degraded_notes). Sonnet text is used only if it is 3 paragraphs with every numeral supported."""
    note = None
    try:
        user = NARRATIVE_USER_TEMPLATE.format(packet_json=json.dumps(packet, ensure_ascii=False, sort_keys=True, default=str))
        text = llm_text("sonnet", SYNTHESIS_SYSTEM_PROMPT, user, max_tokens=1500)
    except Exception as exc:  # llm_text should not raise, but be safe
        text, note = None, f"LLM call failed: {type(exc).__name__}"
    if text:
        paras = _split_paragraphs(text)
        if len(paras) != 3:
            note = f"narrative: deterministic fallback (LLM returned {len(paras)} paragraphs, expected 3)"
        else:
            bad = validate_numbers(text, collect_numbers(packet))
            if not bad:
                return "\n\n".join(paras), []
            note = "narrative: deterministic fallback (numeric validation failed: unsupported numerals " + ", ".join(bad[:5]) + ")"
    elif note is None:
        note = "narrative: deterministic fallback (no key / LLM unavailable)"
    elif not note.startswith("narrative"):
        note = f"narrative: deterministic fallback ({note})"
    return deterministic_narrative(packet, open_flags), [note]


# ------------------------------------------------------------------------------------------------ entry point
def run_synthesis(state: dict, progress_callback: Optional[Callable[[dict], None]] = None) -> dict:
    """Agent 6. Sync, never raises. Returns a partial state update (see module docstring)."""
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    try:
        return _run(state, progress_callback, started, t0)
    except Exception as exc:  # last-resort guard
        log.exception("synthesis failed")
        msg = f"synthesis: internal error {type(exc).__name__}: {exc}"
        return {
            "risk_grade": "Unknown",
            "grade_rationale": msg,
            "smoking_guns": [],
            "smoking_gun_evidence": [],
            "final_narrative": "Synthesis failed; no grade could be assigned. " + msg,
            "jev_scores": {},
            "jev_available": False,
            "agent_severity": {},
            "forensic_timeline": (state.get("temporal_result") or {}).get("timeline", []) if isinstance(state.get("temporal_result"), dict) else [],
            "risk_changed": False,
            "degraded": [msg],
            "error": msg,
            "agent_trace": [
                {"agent": "synthesis", "status": "error", "started": started,
                 "duration_ms": int((time.time() - t0) * 1000), "summary": msg, "degraded": [msg]}
            ],
        }


def _run(state: dict, cb, started: str, t0: float) -> dict:
    results = {a: state.get(f"{a}_result") for a in ALL_AGENTS}
    years = [y for y in (_year_key(v) for v in state.get("analysis_years") or []) if y is not None]
    focus = _year_key(state.get("focus_year")) or (max(years) if years else None)
    if focus is None:
        for a in ALL_AGENTS:
            if isinstance(results.get(a), dict) and _year_key(results[a].get("focus_year")):
                focus = _year_key(results[a]["focus_year"])
                break
    degraded: list[str] = []

    # (1) Jev
    jev_scores = _run_jev(results, state, cb)
    jev_mean, jev_ok = _jev_summary(jev_scores)
    if not jev_ok:
        reasons = sorted({str(s.get("error")) for s in jev_scores.values() if isinstance(s, dict) and s.get("error")})
        degraded.append("jev: unavailable" + (f" ({'; '.join(reasons)[:200]})" if reasons else ""))

    # (2) grade
    sev = {a: _severity(results.get(a)) for a in CORE_AGENTS}
    agents_flagging = sum(1 for s in sev.values() if s in ("Medium", "High"))
    agents_high = sum(1 for s in sev.values() if s == "High")
    esc = _escalation(results.get("temporal"), focus)
    focus_flagged = _focus_year_flagged(results, focus)
    grade = compute_risk_grade(agents_flagging, agents_high, esc, jev_mean, jev_ok, focus_flagged)
    # v3 instrumentation (L2, NO behaviour change): the exact inputs the grade rule saw, persisted for audits.
    grade_inputs = {
        "focus_year": focus, "agents_flagging": agents_flagging, "agents_high": agents_high, "escalation": esc,
        "focus_year_flagged": focus_flagged, "jev_mean_confidence": jev_mean, "jev_available": jev_ok,
        "agent_severity": dict(sev),
    }
    degraded.extend(grade["degraded"])
    unavailable = [a for a in ALL_AGENTS if _is_unavailable(results.get(a))]
    if unavailable:
        degraded.append("synthesis: agents unavailable: " + ", ".join(unavailable))
    degraded = list(dict.fromkeys(degraded))

    # (3) smoking guns
    ranked = rank_candidates(collect_candidates(results, excluded_entity_years(state)), focus)
    guns = select_smoking_guns(ranked)
    gun_texts = [format_smoking_gun(g) for g in guns]
    gun_evidence = [
        {**{k: v for k, v in g.items()}, "text": t, "pattern": (match_pattern(g["flag"], str(g["metric"])) or {}).get("key")}
        for g, t in zip(guns, gun_texts)
    ]

    # (4) narrative
    open_flags = sorted(
        {f for a in CORE_AGENTS if not _is_unavailable(results.get(a))
         for y, fl in (results[a].get("flags_by_year") or {}).items() if _year_key(y) == focus for f in (fl or [])}
    )
    counts = {
        "agents_flagging": agents_flagging, "agents_high": agents_high, "agents_total": len(CORE_AGENTS),
        "agents_unavailable": len([a for a in CORE_AGENTS if a in unavailable]),
        "temporal_escalation": esc,
    }
    packet = build_packet(state, results, grade, counts, jev_scores, jev_mean, guns, gun_texts, list(state.get("degraded") or []) + degraded, focus)
    narrative, ndeg = build_narrative(packet, open_flags)
    degraded.extend(ndeg)

    prev = state.get("previous_risk_grade")
    changed = risk_rank(prev) >= 0 and risk_rank(prev) != risk_rank(grade["grade"])
    temporal = results.get("temporal")
    timeline = (temporal.get("timeline") if isinstance(temporal, dict) else None) or state.get("forensic_timeline") or []

    summary = f"grade={grade['grade']} flagging={agents_flagging} high={agents_high} guns={len(guns)} jev={'yes' if jev_ok else 'no'}"
    _emit(cb, {"node": "synthesis", "status": "done", "message": summary})
    return {
        "risk_grade": grade["grade"],
        "grade_rationale": grade["rationale"],
        "smoking_guns": gun_texts,
        "smoking_gun_evidence": gun_evidence,
        "final_narrative": narrative,
        "jev_scores": jev_scores,
        "jev_available": jev_ok,
        "agent_severity": sev,
        "grade_inputs": grade_inputs,
        "forensic_timeline": timeline,
        "risk_changed": bool(changed),
        "degraded": degraded,
        "agent_trace": [
            {"agent": "synthesis", "status": "ok", "started": started,
             "duration_ms": int((time.time() - t0) * 1000), "summary": summary, "degraded": degraded}
        ],
    }
