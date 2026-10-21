"""Jev (TypeSafe AI) confidence scoring of forensic agent results.

Package: ``typesafe-sdk`` (import ``typesafe_sdk``) -- see docs/CONTRACTS.md D1.

For every agent (quantitative, language, network, peer, temporal) ONE
``client.system_one(state=..., questions=...)`` call is made with three questions:

1. ``evidence_strength`` -- ``Choice`` with criteria Insufficient / Suggestive / Strong /
   Definitive, with agent-specific instructions.
2. ``confidence`` -- ``Score`` with a 5-level ORDERED rubric (``CONFIDENCE_RUBRIC``, from
   "no basis" to "overwhelming"). The SDK returns ``ScoreAnswer.score`` = the expected rubric
   position (probability-weighted mean of the legend keys) plus ``legend`` (position -> rubric
   text). We normalise to 0-100 with :func:`normalize_score`::

       confidence_score = 100 * (score - min(legend)) / (max(legend) - min(legend))

   clamped to [0, 100] and rounded to 1 decimal. Using the *response's own legend keys* makes
   the result independent of whether the service numbers the rubric 0..4 or 1..5. If the legend
   is missing/degenerate the score is NOT guessed: ``confidence_score`` is ``None``.
3. ``material_change`` -- ``Noul`` (boolean; ``.noul`` is P(yes)); mapped with ``noul >= 0.5``.
   When no prior-year results are supplied, the state says so, the question text says prior data
   is unavailable, and ``material_change`` is reported as ``None`` (never guessed).

The state sent to Jev is a compact JSON object (<= ``MAX_STATE_BYTES``, ~4KB): severity, flags,
``flags_by_year``, ``key_finding`` and a handful of headline numbers lifted from the agent
result. No filing text is ever sent.

Concurrency: the synchronous ``TypeSafeClient`` is used inside a ``ThreadPoolExecutor`` (one
call per agent). The calls are network-bound and independent, and the sync client is callable
from the sync agent/synthesis code and from ``asyncio.to_thread`` without needing an event
loop, so threads are simpler and safer than ``AsyncTypeSafeClient`` here.

Nothing in this module raises: every failure (no key, no SDK, auth, rate limit, timeout,
malformed response, empty/unavailable agent result) yields
``available=False``, ``evidence_strength="Unavailable"`` and an ``error`` string.
Missing keys are a normal state (CONTRACTS section 0.3); a Jev score is never fabricated.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TypedDict

try:  # optional: foundation module may or may not exist yet
    from tools.common import load_env as _load_env
except Exception:  # pragma: no cover - depends on sibling module
    _load_env = None

try:
    from typesafe_sdk import (
        Choice,
        Noul,
        RetryPolicy,
        Score,
        TypeSafeAPIConnectionError,
        TypeSafeAPITimeoutError,
        TypeSafeAuthenticationError,
        TypeSafeClient,
        TypeSafeError,
        TypeSafePermissionDeniedError,
        TypeSafeRateLimitError,
    )

    _SDK_ERROR: str | None = None
except Exception as _exc:  # pragma: no cover - SDK is installed in this project
    Choice = Noul = RetryPolicy = Score = TypeSafeClient = None  # type: ignore[assignment]
    TypeSafeAPIConnectionError = TypeSafeAPITimeoutError = TypeSafeAuthenticationError = Exception  # type: ignore[assignment,misc]
    TypeSafeError = TypeSafePermissionDeniedError = TypeSafeRateLimitError = Exception  # type: ignore[assignment,misc]
    _SDK_ERROR = f"typesafe-sdk not importable ({type(_exc).__name__}: {_exc})"

log = logging.getLogger("forensic.jev")

AGENT_NAMES: tuple[str, ...] = ("quantitative", "language", "network", "peer", "temporal")
EVIDENCE_LEVELS: tuple[str, ...] = ("Insufficient", "Suggestive", "Strong", "Definitive")
UNAVAILABLE = "Unavailable"
STRONG_LEVELS = frozenset({"Strong", "Definitive"})

CONFIDENCE_RUBRIC: tuple[str, ...] = (
    "No basis: the primary finding is unsupported or contradicted by the supplied evidence",
    "Weak: the finding rests on thin, ambiguous or single-source evidence",
    "Moderate: the finding is supported by some evidence but plausible innocent explanations remain",
    "High: the finding is well supported by several consistent, specific data points",
    "Overwhelming: the finding is conclusively supported by multiple independent, specific data points",
)

MAX_STATE_BYTES = 4000
REQUEST_TIMEOUT_S = 15.0  # per attempt; hard requirement is <= 20s
MAX_RETRIES = 1
OVERALL_TIMEOUT_S = 45.0  # wall-clock bound for the whole thread pool
MAX_WORKERS = 5


class JevScore(TypedDict):
    """Per-agent Jev result (CONTRACTS section 3)."""

    evidence_strength: str  # Insufficient|Suggestive|Strong|Definitive|Unavailable
    confidence_score: float | None  # 0-100
    material_change: bool | None
    jev_latency_ms: int
    available: bool
    error: str | None
    model: str | None


# --------------------------------------------------------------------------- helpers


def get_api_key() -> str | None:
    """Return the Jev key from ``JEV_API_KEY`` or ``TYPESAFE_API_KEY`` (None if unset/blank)."""
    if _load_env is not None:
        try:
            _load_env()
        except Exception:
            pass
    for name in ("JEV_API_KEY", "TYPESAFE_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return None


def _unavailable(error: str, latency_ms: int = 0, model: str | None = None) -> JevScore:
    return JevScore(
        evidence_strength=UNAVAILABLE,
        confidence_score=None,
        material_change=None,
        jev_latency_ms=int(latency_ms),
        available=False,
        error=error,
        model=model,
    )


def noul_to_bool(noul: Any, threshold: float = 0.5) -> bool | None:
    """Map a Noul answer (P(yes) in [0,1]) to a bool: ``noul >= threshold``. Invalid -> None."""
    try:
        val = float(noul)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN
        return None
    return val >= threshold


def normalize_score(score: Any, legend: Any) -> float | None:
    """Normalise a Jev ``Score`` answer to 0-100 using the legend keys of the response.

    ``score`` is the expected rubric position (a float within ``[min(legend), max(legend)]``).
    Formula: ``100 * (score - lo) / (hi - lo)`` with ``lo = min(keys)``, ``hi = max(keys)``,
    clamped to [0, 100], rounded to 1 decimal. Works for 0-based (0..4) and 1-based (1..5)
    legends alike. Returns ``None`` when the legend is missing, has fewer than two integer
    keys, or the score is not a finite number (never guesses a scale).
    """
    try:
        val = float(score)
    except (TypeError, ValueError):
        return None
    if val != val or val in (float("inf"), float("-inf")):
        return None
    keys: list[int] = []
    try:
        for k in dict(legend or {}).keys():
            try:
                keys.append(int(k))
            except (TypeError, ValueError):
                continue
    except Exception:
        return None
    if len(set(keys)) < 2:
        return None
    lo, hi = min(keys), max(keys)
    pct = 100.0 * (val - lo) / (hi - lo)
    return round(max(0.0, min(100.0, pct)), 1)


# --------------------------------------------------------------------------- state


_SCALAR_TYPES = (int, float, bool)


def _num(v: Any) -> Any:
    """Round floats; map NaN/inf to None so JSON stays valid."""
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return round(v, 4)
    return v


def _scalars(d: dict, limit: int = 6) -> dict:
    """Keep up to ``limit`` short scalar values (numbers, bools, short strings) of a dict."""
    out: dict = {}
    for k, v in d.items():
        if len(out) >= limit:
            break
        if isinstance(v, _SCALAR_TYPES):
            out[str(k)] = _num(v)
        elif isinstance(v, str) and len(v) <= 80:
            out[str(k)] = v
    return out


def _as_int(k: Any) -> int | None:
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _headline_numbers(result: dict, focus_year: int | None, max_items: int = 8) -> dict:
    """Pull a handful of headline numbers out of an agent result without knowing its exact shape.

    * year-keyed dicts (``beneish_scores``, ``hedging_trend`` ...) -> the focus-year entry's scalars
      (latest year when focus_year is absent);
    * metric-keyed dicts of dicts (``metric_zscores``) -> value/z fields of up to 4 metrics.
    """
    skip = {"flags_by_year", "data_quality", "key_finding", "severity", "degraded", "timeline"}
    out: dict = {}
    for name, val in result.items():
        if len(out) >= max_items:
            break
        if name in skip or not isinstance(val, dict) or not val:
            continue
        year_keys = {_as_int(k): k for k in val if _as_int(k) is not None}
        if year_keys and len(year_keys) == len(val):
            yr = focus_year if focus_year in year_keys else max(year_keys)  # type: ignore[arg-type]
            entry = val[year_keys[yr]]
            if isinstance(entry, dict):
                sc = _scalars(entry, 4)
                if sc:
                    out[name] = {"year": yr, **sc}
            elif isinstance(entry, _SCALAR_TYPES):
                out[name] = {"year": yr, "value": _num(entry)}
        elif all(isinstance(v, dict) for v in val.values()):
            sub: dict = {}
            for mk, mv in list(val.items())[:4]:
                sc = _scalars({k: v for k, v in mv.items() if k != "interpretation"}, 3)
                if sc:
                    sub[str(mk)] = sc
            if sub:
                out[name] = sub
    return out


def _compact_agent(result: dict) -> dict:
    """Compact, JSON-safe digest of one agent result (no filing text)."""
    focus = _as_int(result.get("focus_year"))
    fby_raw = result.get("flags_by_year") or {}
    fby: dict[str, list[str]] = {}
    if isinstance(fby_raw, dict):
        for k in sorted(fby_raw, key=lambda x: (_as_int(x) is None, _as_int(x) or 0)):
            v = fby_raw[k]
            fby[str(k)] = [str(x)[:40] for x in (v if isinstance(v, (list, tuple)) else [])][:8]
    unavailable = (result.get("data_quality") or {}).get("unavailable") if isinstance(
        result.get("data_quality"), dict
    ) else None
    digest: dict[str, Any] = {
        "severity": str(result.get("severity", "None")),
        "flags_fired": result.get("flags_fired"),
        "focus_year": focus,
        "flags_by_year": fby,
        "key_finding": str(result.get("key_finding") or "")[:400],
        "headline": _headline_numbers(result, focus),
    }
    if isinstance(unavailable, dict) and unavailable:
        digest["unavailable_metrics"] = sorted(str(k) for k in unavailable)[:8]
    return digest


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True, default=str)


def build_state(
    agent: str, result: dict, prior_result: dict | None = None, max_bytes: int = MAX_STATE_BYTES
) -> dict:
    """Build the compact Jev state for one agent (serialised size <= ``max_bytes``).

    Keys: ``agent``, ``current`` (digest of the agent result), ``prior_year_available`` and,
    when available, ``prior_year`` (digest of the prior-year result). If the JSON exceeds the
    budget, detail is dropped in order: headline numbers, then per-year flag lists, then the
    key_finding is truncated.
    """
    state: dict[str, Any] = {
        "agent": agent,
        "current": _compact_agent(result),
        "prior_year_available": isinstance(prior_result, dict) and bool(prior_result),
    }
    if state["prior_year_available"]:
        state["prior_year"] = _compact_agent(prior_result)  # type: ignore[arg-type]
    for stage in range(4):
        if len(_dumps(state).encode("utf-8")) <= max_bytes:
            return state
        for part in ("current", "prior_year"):
            if part not in state:
                continue
            d = state[part]
            if stage == 0:
                d["headline"] = {}
            elif stage == 1:
                d["flags_by_year"] = {k: v[:3] for k, v in list(d["flags_by_year"].items())[-3:]}
            elif stage == 2:
                d["key_finding"] = d["key_finding"][:150]
            else:
                d["flags_by_year"] = {}
                d["key_finding"] = d["key_finding"][:60]
    return state


# --------------------------------------------------------------------------- questions

_AGENT_QUESTIONS: dict[str, dict[str, str]] = {
    "quantitative": {
        "evidence": (
            "Is the quantitative evidence sufficient to flag manipulation risk? Judge only the "
            "financial-statement signals in `current` (Beneish M-score, accruals, revenue quality, "
            "DSO growth, Altman distress). Distinguish accounting manipulation risk from plain "
            "business distress."
        ),
        "confidence": "How confident are you in the quantitative agent's primary finding (`current.key_finding`)?",
    },
    "language": {
        "evidence": (
            "Is the textual evidence (MD&A hedging, passive voice, risk-factor growth, specificity, "
            "new legal proceedings) sufficient to flag manipulation risk? Linguistic signals are "
            "indirect: require several consistent signals before answering Strong or Definitive."
        ),
        "confidence": "How confident are you in the language agent's primary finding (`current.key_finding`)?",
    },
    "network": {
        "evidence": (
            "Is the governance and relationship evidence (auditor change, CFO/CEO turnover, audit "
            "fee jumps, restatements or material weaknesses, related-party dealings, going-concern "
            "doubt) sufficient to flag manipulation risk? A single change in isolation is usually "
            "Suggestive; restatement plus auditor or CFO change together is stronger."
        ),
        "confidence": "How confident are you in the network agent's primary finding (`current.key_finding`)?",
    },
    "peer": {
        "evidence": (
            "Is the peer-comparison evidence (company metrics versus same-industry peer z-scores, "
            "outlier metrics) sufficient to flag manipulation risk? Outliers can reflect business "
            "model differences: weigh the number and consistency of outlier metrics."
        ),
        "confidence": "How confident are you in the peer agent's primary finding (`current.key_finding`)?",
    },
    "temporal": {
        "evidence": (
            "Is the multi-year trend evidence (suspicion-score timeline, new flags per year, "
            "escalation, first detection year) sufficient to flag manipulation risk? Persistent "
            "escalation across years is stronger than a single-year spike."
        ),
        "confidence": "How confident are you in the temporal agent's primary finding (`current.key_finding`)?",
    },
}

_EVIDENCE_CRITERIA: dict[str, str] = {
    "Insufficient": "Little or no usable evidence, or key inputs unavailable; no manipulation-risk flag is justified.",
    "Suggestive": "Some signals point toward manipulation risk but they are few, isolated or ambiguous.",
    "Strong": "Multiple consistent, specific signals make manipulation risk likely.",
    "Definitive": "Overwhelming, specific, mutually corroborating evidence of manipulation risk.",
}


def build_questions(agent: str, has_prior: bool) -> dict:
    """Return the three SDK question objects for ``agent`` (Choice, Score, Noul)."""
    txt = _AGENT_QUESTIONS.get(agent) or {
        "evidence": f"Is the {agent} evidence sufficient to flag manipulation risk?",
        "confidence": f"How confident are you in the {agent} agent's primary finding?",
    }
    if has_prior:
        change = (
            "Does `current` represent a material change from `prior_year` (new or additional "
            "flags, higher severity, or notably worse headline numbers)?"
        )
    else:
        change = (
            "Prior-year data is unavailable (`prior_year_available` is false), so a "
            "year-over-year comparison cannot be made. Answer no."
        )
    return {
        "evidence_strength": Choice(
            instructions=txt["evidence"] + " Base the answer only on the supplied state.",
            criteria=dict(_EVIDENCE_CRITERIA),
        ),
        "confidence": Score(instructions=txt["confidence"], criteria=list(CONFIDENCE_RUBRIC)),
        "material_change": Noul(instructions=change),
    }


# --------------------------------------------------------------------------- core


def _make_client(api_key: str) -> Any:
    """Build a sync client with bounded retry/timeout (patched in tests)."""
    retry = RetryPolicy(
        max_retries=MAX_RETRIES, backoff_initial=0.5, backoff_max=2.0, timeout=REQUEST_TIMEOUT_S
    )
    return TypeSafeClient(api_key=api_key, retry=retry, timeout=REQUEST_TIMEOUT_S)


def _classify_error(exc: BaseException) -> str:
    name = type(exc).__name__
    if _SDK_ERROR is None:
        if isinstance(exc, (TypeSafeAuthenticationError, TypeSafePermissionDeniedError)):
            return f"Jev authentication failed: check JEV_API_KEY ({name})"
        if isinstance(exc, TypeSafeRateLimitError):
            return f"Jev rate limit exceeded after retries ({name})"
        if isinstance(exc, TypeSafeAPITimeoutError):
            return f"Jev API timed out after {REQUEST_TIMEOUT_S:.0f}s ({name})"
        if isinstance(exc, TypeSafeAPIConnectionError):
            return f"Jev connection error ({name}): {exc}"
    return f"Jev API error ({name}): {exc}"[:300]


def _parse_response(response: Any, latency_ms: int, has_prior: bool) -> JevScore:
    """Convert a ``SystemOneResponse`` into a JevScore; tolerant of missing answers."""
    answers = getattr(response, "answers", None)
    if not isinstance(answers, dict) or not answers:
        return _unavailable("Jev response contained no answers", latency_ms, getattr(response, "model", None))
    model = getattr(response, "model", None)
    problems: list[str] = []

    evidence: str | None = None
    ans = answers.get("evidence_strength")
    raw_choice = getattr(ans, "choice", None)
    if isinstance(raw_choice, str):
        lookup = {lvl.lower(): lvl for lvl in EVIDENCE_LEVELS}
        evidence = lookup.get(raw_choice.strip().lower())
        if evidence is None:
            problems.append(f"unrecognised evidence_strength '{raw_choice}'")
    else:
        problems.append("evidence_strength answer missing")

    confidence: float | None = None
    ans = answers.get("confidence")
    if ans is not None and hasattr(ans, "score"):
        confidence = normalize_score(getattr(ans, "score", None), getattr(ans, "legend", None))
        if confidence is None:
            problems.append("confidence score not normalisable (legend missing/degenerate)")
    else:
        problems.append("confidence answer missing")

    material: bool | None = None
    if has_prior:
        ans = answers.get("material_change")
        if ans is not None and hasattr(ans, "noul"):
            material = noul_to_bool(getattr(ans, "noul", None))
        if material is None:
            problems.append("material_change answer missing")

    if evidence is None and confidence is None and material is None:
        return _unavailable("Jev response unusable: " + "; ".join(problems), latency_ms, model)
    return JevScore(
        evidence_strength=evidence or UNAVAILABLE,
        confidence_score=confidence,
        material_change=material,
        jev_latency_ms=latency_ms,
        available=evidence is not None or confidence is not None,
        error=("partial response: " + "; ".join(problems)) if problems else None,
        model=model,
    )


def score_one(agent: str, result: Any, prior_result: Any = None, api_key: str | None = None) -> JevScore:
    """Score a single agent with one ``system_one`` call. Never raises."""
    t0 = time.perf_counter()
    try:
        if _SDK_ERROR is not None:
            return _unavailable(_SDK_ERROR)
        key = api_key or get_api_key()
        if not key:
            return _unavailable("JEV_API_KEY not set")
        if not isinstance(result, dict) or not result:
            return _unavailable(f"{agent} result empty or not a dict: nothing to score")
        if result.get("unavailable"):
            return _unavailable(f"{agent} agent unavailable: {str(result.get('error') or 'no data')[:150]}")
        prior = prior_result if isinstance(prior_result, dict) and prior_result else None
        state = build_state(agent, result, prior)
        questions = build_questions(agent, prior is not None)
        t0 = time.perf_counter()
        try:
            client = _make_client(key)
            response = client.system_one(state=state, questions=questions)
        except Exception as exc:  # noqa: BLE001 - contract: never raise
            return _unavailable(_classify_error(exc), int((time.perf_counter() - t0) * 1000))
        latency = int((time.perf_counter() - t0) * 1000)
        return _parse_response(response, latency, prior is not None)
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"Jev scoring failed ({type(exc).__name__}): {exc}"[:300],
                            int((time.perf_counter() - t0) * 1000))


def score_agents(
    agent_results: dict[str, dict], prior_year_results: dict | None = None
) -> dict[str, JevScore]:
    """Score every agent in ``agent_results`` concurrently; returns ``{agent: JevScore}``.

    ``agent_results`` maps agent name (``quantitative``, ``language``, ``network``, ``peer``,
    ``temporal``; others are scored too) to its result dict. ``prior_year_results`` has the same
    shape (results of the analysis one year earlier); absent agents get ``material_change=None``.
    Never raises; every failure yields ``available=False``.
    """
    try:
        results = agent_results if isinstance(agent_results, dict) else {}
        priors = prior_year_results if isinstance(prior_year_results, dict) else {}
        names = [a for a in AGENT_NAMES if a in results] + [a for a in results if a not in AGENT_NAMES]
        out: dict[str, JevScore] = {}
        if not names:
            return out
        key = get_api_key()
        if not key or _SDK_ERROR is not None:
            err = _SDK_ERROR or "JEV_API_KEY not set"
            return {a: _unavailable(err) for a in names}
        pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(names)), thread_name_prefix="jev")
        try:
            futures = {
                pool.submit(score_one, a, results.get(a), priors.get(a), key): a for a in names
            }
            try:
                for fut in as_completed(futures, timeout=OVERALL_TIMEOUT_S):
                    a = futures[fut]
                    try:
                        out[a] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        out[a] = _unavailable(f"Jev worker failed ({type(exc).__name__}): {exc}"[:300])
            except Exception:  # TimeoutError from as_completed
                pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for a in names:
            out.setdefault(a, _unavailable(f"Jev scoring exceeded {OVERALL_TIMEOUT_S:.0f}s overall limit"))
        return {a: out[a] for a in names}
    except Exception as exc:  # noqa: BLE001
        log.warning("score_agents failed: %s", exc)
        return {a: _unavailable(f"Jev scoring failed ({type(exc).__name__}): {exc}"[:300])
                for a in (agent_results or {})}


def summarize_jev(jev_scores: dict[str, JevScore] | None) -> dict:
    """Aggregate per-agent Jev scores for synthesis.

    Returns ``{"mean_confidence": float|None, "available_count": int, "any_available": bool,
    "strong_agents": [...]}``. ``mean_confidence`` is the mean ``confidence_score`` over agents
    that are available and have a numeric confidence (None if none). ``strong_agents`` lists
    available agents whose evidence_strength is Strong or Definitive.
    """
    scores = jev_scores if isinstance(jev_scores, dict) else {}
    avail = {a: s for a, s in scores.items() if isinstance(s, dict) and s.get("available")}
    confs = [
        float(s["confidence_score"])
        for s in avail.values()
        if isinstance(s.get("confidence_score"), (int, float))
    ]
    return {
        "mean_confidence": round(sum(confs) / len(confs), 1) if confs else None,
        "available_count": len(avail),
        "any_available": bool(avail),
        "strong_agents": [a for a, s in avail.items() if s.get("evidence_strength") in STRONG_LEVELS],
    }
