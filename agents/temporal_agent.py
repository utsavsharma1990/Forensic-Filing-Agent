"""Agent 5 - Temporal intelligence (deterministic, no LLM, no I/O).

Reads ONLY the four independent agent results in the state (``quantitative_result``, ``language_result``,
``network_result``, ``peer_result``) plus ``filings`` / ``filing_metadata`` for filing dates, and turns the
per-year flag evidence into a 0-100 "suspicion score" series, a forensic timeline, an inflection year
(``first_detection_year``) and a trajectory.

Scoring (SPEC agent 5, applied exactly; CONTRACTS section 4)
------------------------------------------------------------
For every year the set of flags is the union of (a) the agents' ``flags_by_year`` and (b) flags implied by the
structured fields (Beneish zone, Altman zone, auditor/CFO/CEO change, going concern) so that an agent that
filled the structured field but forgot the flag name is still counted once (a flag is a SET member: it can
never be counted twice). Points per year:

* +10 for every flag fired that year (``network.ceo_change`` is recorded but has weight 0 in total)
* PLUS these bonuses ON TOP of the +10 the same flag already earns:
  ``quantitative.beneish`` (Beneish M in the manipulation zone) +20,
  ``quantitative.altman_distress`` +15, ``network.auditor_change`` +15,
  ``network.going_concern`` +25, ``network.cfo_change`` +10.
* cap at 100.

So the per-flag totals are: Beneish 30, Altman distress 25, auditor change 25, going concern 35, CFO change 20,
CEO change 0, every other flag 10. (Interpretation chosen: the spec says "each flag fired = +10" and lists the
bonuses separately, so both apply; this is stated here rather than guessed silently.)

Worked example (also a unit test): FY X has flags {beneish, accruals, cfo_change}:
  beneish 10+20 = 30; accruals 10; cfo_change 10+10 = 20  ->  60  (High).
Another: {beneish, altman_distress, auditor_change, going_concern} = 30+25+25+35 = 115 -> capped to 100.

Altman note: ``quantitative.altman_distress`` is a BUSINESS-DISTRESS signal, not evidence of manipulation. It is
kept in the score because the spec asks for it; synthesis must keep manipulation and distress separate.
The result lists every flag with its points in ``score_breakdown`` so the number is auditable.

Peer flags exist only for the focus year; they are attached to the focus year and still ADD to the score. Because they
are absent from every earlier year they would always be "new" in the focus year, so (v2, B5) ``peer.*`` flags are
EXCLUDED from the new-flag test that decides "Escalating" (they remain listed in ``new_flags_this_year``).

Entity validity (v2, B8/B2). ``state["filing_entity_flags"] = {year: {"is_shell": bool, "spac_predecessor": bool,
"reason": str}}`` (provided by the pipeline; tolerated when absent). A year flagged as a shell / SPAC predecessor is the
filing of a DIFFERENT legal-economic entity (a blank-check company before its business combination): its flags are not
evidence about the operating company, and it cannot serve as a baseline. Such a year gets ``data_available=False``,
``excluded_shell=True``, score 0, is dropped from the trajectory / elevated-year count / first detection, and the next
year has no prior to compare with (so, like any first year, it can never be "Escalating").

Risk level: Low 0-29, Medium 30-59, High 60-79, Critical >= 80.

signal_change per year (compared to the previous year WITH DATA in the series):
* The first year has no prior: its new flags are counted against the empty set, but it can never be
  "Escalating"; it is "Stable".
* Escalating  : >= 1 new flag (present now, absent in prior year) AND score rose.
* Improving   : (not Escalating) score fell >= 10, OR the number of flags fell.
* Stable      : otherwise.

signal_trajectory over the series: "Volatile" if the direction of year-to-year score changes flips >= 2 times
and max-min >= 20 (zero changes are ignored when finding direction); else net change (last - first)
>= +10 "Escalating", <= -10 "Improving", else "Stable". With no usable data at all: "Unknown" (a documented
fifth value, never silently "Stable").

first_detection_year = first year with score >= 40 AND signal_change == "Escalating" (None if never).
first_detection_filing_date = filing date of that year's OWN annual filing (``state["filings"]``, matched on
``fiscal_year``; ``filing_metadata[year]["filing_date"|"date"]`` only as fallback). If the year has no own filing
(comparative-filled) the next later filing is used and ``filing_date_is_proxy`` is True.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- constants

FLAG_POINTS = 10
FLAG_POINTS_ZERO_WEIGHT = frozenset({"network.ceo_change"})  # spec scores CFO only
BONUS_POINTS: dict[str, int] = {
    "quantitative.beneish": 20,
    "quantitative.altman_distress": 15,  # business-distress signal, kept per spec
    "network.auditor_change": 15,
    "network.going_concern": 25,
    "network.cfo_change": 10,
}
SCORE_CAP = 100
ELEVATED_THRESHOLD = 40
IMPROVING_DROP = 10
TRAJECTORY_NET = 10
VOLATILE_AMPLITUDE = 20
VOLATILE_REVERSALS = 2
RISK_BANDS = ((80, "Critical"), (60, "High"), (30, "Medium"), (0, "Low"))

AGENTS = ("quantitative", "language", "network", "peer")
_BENEISH_ZONES = {"manipulator", "high"}
_ALTMAN_DISTRESS = {"distress"}

NOTES = [
    "quantitative.altman_distress is a business-distress signal, not a manipulation signal (kept per spec).",
    "Peer flags exist only for the focus year and are attached to it; they add to the score but never by themselves make a year Escalating.",
    "Years flagged as SPAC/shell predecessors (filing_entity_flags) are excluded from the series and never serve as a YoY baseline.",
]


# --------------------------------------------------------------------------- small helpers

def _yr(key: Any) -> int | None:
    try:
        if isinstance(key, bool):
            return None
        s = str(key).strip()
        return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None
    except Exception:
        return None


def _is_available(result: Any) -> bool:
    return (
        isinstance(result, Mapping)
        and bool(result)
        and not result.get("unavailable")
        and not result.get("error")
    )


def _year_map(d: Any) -> dict[int, Any]:
    """Re-key a {year(str|int): value} mapping to int keys; ignore junk."""
    out: dict[int, Any] = {}
    if isinstance(d, Mapping):
        for k, v in d.items():
            y = _yr(k)
            if y is not None:
                out[y] = v
    return out


def _as_flag_list(v: Any) -> list[str]:
    if isinstance(v, (list, tuple, set, frozenset)):
        return [str(x) for x in v if x]
    return []


def risk_level(score: int | float) -> str:
    for floor, name in RISK_BANDS:
        if score >= floor:
            return name
    return "Low"


def flag_points(flag: str) -> int:
    """Total points one fired flag contributes: base +10 (0 if zero-weight) plus its bonus."""
    base = 0 if flag in FLAG_POINTS_ZERO_WEIGHT else FLAG_POINTS
    return base + BONUS_POINTS.get(flag, 0)


def score_flags(flags: Iterable[str]) -> tuple[int, list[dict], bool]:
    """Return (capped_score, breakdown, was_capped) for a set of flags."""
    breakdown: list[dict] = []
    raw = 0
    for f in sorted(set(flags)):
        base = 0 if f in FLAG_POINTS_ZERO_WEIGHT else FLAG_POINTS
        bonus = BONUS_POINTS.get(f, 0)
        breakdown.append({"flag": f, "base": base, "bonus": bonus, "points": base + bonus})
        raw += base + bonus
    return min(raw, SCORE_CAP), breakdown, raw > SCORE_CAP


# --------------------------------------------------------------------------- per-year flag collection

def collect_year_flags(
    results: Mapping[str, Any], focus_year: int | None
) -> tuple[dict[int, set[str]], set[int]]:
    """Union of flags per year from the four agent results + structured fields.

    Returns (flags_by_year, years_with_data). Unavailable/missing agents contribute nothing.
    """
    flags: dict[int, set[str]] = {}
    seen: set[int] = set()

    def add(y: int | None, f: str) -> None:
        if y is None:
            return
        flags.setdefault(y, set()).add(f)
        seen.add(y)

    def touch(ys: Iterable[Any]) -> None:
        for k in ys:
            y = _yr(k)
            if y is not None:
                seen.add(y)
                flags.setdefault(y, set())

    q = results.get("quantitative")
    if _is_available(q):
        for y, fl in _year_map(q.get("flags_by_year")).items():
            touch([y])
            for f in _as_flag_list(fl):
                add(y, f)
        for y, rec in _year_map(q.get("beneish_scores")).items():
            touch([y])
            if isinstance(rec, Mapping):
                zone = str(rec.get("zone", "")).strip().lower()
                if zone in _BENEISH_ZONES or rec.get("flag") is True:
                    add(y, "quantitative.beneish")
        for y, rec in _year_map(q.get("altman_scores")).items():
            touch([y])
            if isinstance(rec, Mapping) and str(rec.get("zone", "")).strip().lower() in _ALTMAN_DISTRESS:
                add(y, "quantitative.altman_distress")

    lang = results.get("language")
    if _is_available(lang):
        for y, fl in _year_map(lang.get("flags_by_year")).items():
            touch([y])
            for f in _as_flag_list(fl):
                add(y, f)

    n = results.get("network")
    if _is_available(n):
        for y, fl in _year_map(n.get("flags_by_year")).items():
            touch([y])
            for f in _as_flag_list(fl):
                add(y, f)
        for y, rec in _year_map(n.get("auditor_history")).items():
            touch([y])
            if isinstance(rec, Mapping) and rec.get("changed") is True:
                add(y, "network.auditor_change")
        for y, rec in _year_map(n.get("executive_changes")).items():
            touch([y])
            if isinstance(rec, Mapping):
                if rec.get("cfo_changed") is True:
                    add(y, "network.cfo_change")
                if rec.get("ceo_changed") is True:
                    add(y, "network.ceo_change")
        for y, rec in _year_map(n.get("going_concern")).items():
            touch([y])
            if isinstance(rec, Mapping) and rec.get("detected") is True:
                add(y, "network.going_concern")

    p = results.get("peer")
    if _is_available(p) and focus_year is not None:
        peer_flags: set[str] = set()
        for fl in _year_map(p.get("flags_by_year")).values():
            peer_flags.update(_as_flag_list(fl))
        if not peer_flags:
            peer_flags.update(f"peer.{m}" for m in _as_flag_list(p.get("outlier_metrics")))
        touch([focus_year])
        for f in peer_flags:
            add(focus_year, f if f.startswith("peer.") else f"peer.{f}")

    return flags, seen


# --------------------------------------------------------------------------- timeline

def entity_exclusions(entity_flags: Any) -> dict[int, str]:
    """{year: reason} for years flagged ``is_shell`` or ``spac_predecessor`` in ``filing_entity_flags`` (junk ignored)."""
    out: dict[int, str] = {}
    for y, rec in _year_map(entity_flags).items():
        if isinstance(rec, Mapping) and (rec.get("is_shell") is True or rec.get("spac_predecessor") is True):
            out[y] = str(rec.get("reason") or "shell / SPAC predecessor filing")
    return out


def build_timeline(
    years: list[int],
    flags_by_year: Mapping[int, set[str]],
    years_with_data: set[int],
    excluded: Mapping[int, str] | None = None,
) -> list[dict]:
    """Table-driven core: per-year score, new flags, risk level and signal_change.

    ``excluded`` = {year: reason} of shell/SPAC-predecessor years: no data, score 0, and the following year starts a new
    baseline (it can never be Escalating).
    """
    timeline: list[dict] = []
    prev: dict | None = None  # previous year WITH data
    excluded = excluded or {}
    for y in sorted(years):
        is_excluded = y in excluded
        has_data = (y in years_with_data) and not is_excluded
        fl = set(flags_by_year.get(y, set())) if has_data else set()
        score, breakdown, capped = score_flags(fl)
        prior_flags = set(prev["flags"]) if prev else set()
        new_flags = sorted(fl - prior_flags) if has_data else []
        escalating_new = [f for f in new_flags if not f.startswith("peer.")]  # B5: peer flags never make a year Escalating
        if is_excluded:
            prev = None  # a shell year is not a baseline; the next year starts afresh
        if not has_data or prev is None:
            change = "Stable"  # no prior to compare against: never Escalating
        elif escalating_new and score > prev["suspicion_score"]:
            change = "Escalating"
        elif score <= prev["suspicion_score"] - IMPROVING_DROP or len(fl) < len(prior_flags):
            change = "Improving"
        else:
            change = "Stable"
        entry = {
            "year": y,
            "suspicion_score": score,
            "flags_fired": len(fl),
            "new_flags_this_year": new_flags,
            "risk_level": risk_level(score),
            "signal_change": change,
            "flags": sorted(fl),
            "score_breakdown": breakdown,
            "score_capped": capped,
            "data_available": has_data,
        }
        if is_excluded:
            entry["excluded_shell"] = True
            entry["exclusion_reason"] = excluded[y]
        timeline.append(entry)
        if has_data:
            prev = {"flags": sorted(fl), "suspicion_score": score}
    return timeline


def classify_trajectory(scores: list[int]) -> str:
    """Escalating / Stable / Improving / Volatile over a score series (in year order)."""
    if not scores:
        return "Unknown"
    if len(scores) < 2:
        return "Stable"
    diffs = [b - a for a, b in zip(scores, scores[1:]) if b != a]
    signs = [1 if d > 0 else -1 for d in diffs]
    reversals = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    if reversals >= VOLATILE_REVERSALS and (max(scores) - min(scores)) >= VOLATILE_AMPLITUDE:
        return "Volatile"
    net = scores[-1] - scores[0]
    if net >= TRAJECTORY_NET:
        return "Escalating"
    if net <= -TRAJECTORY_NET:
        return "Improving"
    return "Stable"


def find_first_detection(timeline: list[dict]) -> int | None:
    for e in timeline:
        if e["data_available"] and e["suspicion_score"] >= ELEVATED_THRESHOLD and e["signal_change"] == "Escalating":
            return e["year"]
    return None


def resolve_filing_date(
    year: int, filings: Any, filing_metadata: Any
) -> tuple[str | None, bool, str | None]:
    """(filing_date, is_proxy, accession-or-None) for ``year``'s own annual filing, else the next later one."""
    rows: list[tuple[int, str, str | None]] = []
    if isinstance(filings, (list, tuple)):
        for f in filings:
            if not isinstance(f, Mapping):
                continue
            fy, fd = _yr(f.get("fiscal_year")), f.get("filing_date")
            if fy is not None and isinstance(fd, str) and fd:
                rows.append((fy, fd, f.get("accession")))
    own = sorted((r for r in rows if r[0] == year), key=lambda r: r[1])
    if own:
        return own[0][1], False, own[0][2]
    meta = _year_map(filing_metadata)
    m = meta.get(year)
    if isinstance(m, Mapping) and not rows:
        d = m.get("filing_date") or m.get("date")
        if isinstance(d, str) and d:
            return d, False, m.get("accession")
    later = sorted((r for r in rows if r[0] > year), key=lambda r: (r[0], r[1]))
    if later:
        return later[0][1], True, later[0][2]
    if not rows:
        later_meta = sorted(
            (y2, mm) for y2, mm in meta.items() if y2 > year and isinstance(mm, Mapping)
            and (mm.get("filing_date") or mm.get("date"))
        )
        if later_meta:
            mm = later_meta[0][1]
            return mm.get("filing_date") or mm.get("date"), True, mm.get("accession")
    return None, False, None


def _key_finding(
    timeline: list[dict],
    focus_year: int | None,
    first_year: int | None,
    first_date: str | None,
    is_proxy: bool,
    trajectory: str,
    elevated: int,
    inputs: Mapping[str, bool],
) -> str:
    data = [e for e in timeline if e["data_available"]]
    if not data:
        return "Temporal analysis unavailable: none of the four agent results contained per-year evidence."
    parts: list[str] = []
    focus = next((e for e in data if e["year"] == focus_year), data[-1])
    if first_year is not None:
        e = next(x for x in data if x["year"] == first_year)
        when = f", filing dated {first_date}{' (next filing used as proxy)' if is_proxy else ''}" if first_date else ""
        newf = ", ".join(e["new_flags_this_year"]) or "none"
        parts.append(
            f"Suspicion first crossed {ELEVATED_THRESHOLD} with escalating signals in FY{first_year} "
            f"(score {e['suspicion_score']}, new flags: {newf}{when})."
        )
    else:
        peak = max(data, key=lambda x: (x["suspicion_score"], -x["year"]))
        parts.append(
            f"No year combined a score of {ELEVATED_THRESHOLD}+ with escalating signals "
            f"(peak score {peak['suspicion_score']} in FY{peak['year']})."
        )
    parts.append(
        f"FY{focus['year']} scores {focus['suspicion_score']} ({focus['risk_level']}); "
        f"trajectory {trajectory}; {elevated} year(s) at or above {ELEVATED_THRESHOLD}."
    )
    missing = [a for a in AGENTS if not inputs.get(a)]
    if missing:
        parts.append(f"Scored without: {', '.join(missing)}.")
    return " ".join(parts)


def compute_temporal(state: Mapping[str, Any]) -> dict:
    """Pure computation: returns temporal_result dict (with the top-level extras under keys)."""
    results = {a: state.get(f"{a}_result") for a in AGENTS}
    inputs = {a: _is_available(results[a]) for a in AGENTS}

    analysis_years = [y for y in (_yr(v) for v in (state.get("analysis_years") or [])) if y is not None]
    focus_year = _yr(state.get("focus_year"))

    # focus year may be missing: fall back to analysis years, then to agents' own focus_year, then latest data
    if focus_year is None:
        for a in AGENTS:
            if inputs[a]:
                focus_year = _yr(results[a].get("focus_year"))
                if focus_year is not None:
                    break
    if focus_year is None and analysis_years:
        focus_year = max(analysis_years)

    flags_by_year, seen = collect_year_flags(results, focus_year)
    if focus_year is None and seen:
        focus_year = max(seen)
        flags_by_year, seen = collect_year_flags(results, focus_year)

    years = sorted(set(analysis_years) | seen)
    excluded = entity_exclusions(state.get("filing_entity_flags"))
    timeline = build_timeline(years, flags_by_year, seen, excluded)
    series = [e for e in timeline if e["data_available"]]
    trajectory = classify_trajectory([e["suspicion_score"] for e in series])
    first_year = find_first_detection(timeline)
    first_date, is_proxy, first_accn = (None, False, None)
    if first_year is not None:
        first_date, is_proxy, first_accn = resolve_filing_date(
            first_year, state.get("filings"), state.get("filing_metadata")
        )
    elevated = sum(1 for e in series if e["suspicion_score"] >= ELEVATED_THRESHOLD)
    focus_entry = next((e for e in timeline if e["year"] == focus_year), None)
    focus_score = int(focus_entry["suspicion_score"]) if focus_entry else 0

    degraded: list[str] = []
    for a in AGENTS:
        if not inputs[a]:
            degraded.append(f"temporal: {a}_result unavailable; score computed from the remaining agents")
    if not series:
        degraded.append("temporal: no per-year evidence from any agent; scores are not meaningful")
    if first_year is not None and first_date is None:
        degraded.append(f"temporal: no filing date found for FY{first_year}")
    if first_year is not None and is_proxy:
        degraded.append(f"temporal: FY{first_year} has no own annual filing; next filing date used as proxy")

    return {
        "timeline": timeline,
        "first_detection_year": first_year,
        "first_detection_filing_date": first_date,
        "first_detection_accession": first_accn,
        "filing_date_is_proxy": bool(first_year is not None and is_proxy),
        "signal_trajectory": trajectory,
        "years_of_elevated_risk": elevated,
        "key_finding": _key_finding(
            timeline, focus_year, first_year, first_date, is_proxy, trajectory, elevated, inputs
        ),
        "focus_year": focus_year,
        "suspicion_score": focus_score,
        "focus_signal_change": focus_entry["signal_change"] if focus_entry else None,
        "flags_by_year": {e["year"]: list(e["flags"]) for e in timeline},
        "inputs_available": inputs,
        "excluded_entity_years": dict(excluded),
        "weights": {
            "flag": FLAG_POINTS,
            "zero_weight_flags": sorted(FLAG_POINTS_ZERO_WEIGHT),
            "bonuses": dict(BONUS_POINTS),
            "cap": SCORE_CAP,
        },
        "notes": list(NOTES),
        "data_quality": {"unavailable": {f"{a}_result": "missing or unavailable" for a in AGENTS if not inputs[a]}},
        "degraded": degraded,
    }


# --------------------------------------------------------------------------- thin wrapper

def run_temporal(state: Mapping[str, Any]) -> dict:
    """LangGraph node body (sync, never raises). Returns a partial state update."""
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    try:
        result = compute_temporal(state)
        degraded = list(result["degraded"])
        summary = result["key_finding"]
        status = "degraded" if degraded else "ok"
        update = {
            "temporal_result": result,
            "forensic_timeline": result["timeline"],
            "suspicion_score": result["suspicion_score"],
            "first_detection_year": result["first_detection_year"],
            "first_detection_filing_date": result["first_detection_filing_date"],
        }
    except Exception as exc:  # never raise out of an agent node
        msg = f"{type(exc).__name__}: {exc}"
        degraded = [f"temporal: failed ({msg})"]
        summary = f"temporal unavailable: {msg}"
        status = "error"
        update = {
            "temporal_result": {
                "error": msg,
                "unavailable": True,
                "severity": "None",
                "flags_fired": 0,
                "flags_by_year": {},
                "timeline": [],
                "first_detection_year": None,
                "first_detection_filing_date": None,
                "signal_trajectory": "Unknown",
                "years_of_elevated_risk": 0,
                "key_finding": summary,
                "degraded": degraded,
            },
            "forensic_timeline": [],
            "suspicion_score": 0,
            "first_detection_year": None,
            "first_detection_filing_date": None,
        }
    update["agent_trace"] = [
        {
            "agent": "temporal",
            "status": status,
            "started": started,
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "summary": summary,
            "degraded": degraded,
        }
    ]
    update["degraded"] = degraded
    return update
