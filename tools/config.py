"""Run-time configuration: flag exclusion for the pre-registered ``no_passive`` variant (docs/TUNING_LEDGER.md P2).

* :func:`get_excluded_flags` - env ``FORENSIC_EXCLUDE_FLAGS`` (comma list, default empty) with a per-call override.
* :func:`recompute_severity` - the CONTRACTS section 4 severity rule applied to a result's (possibly filtered)
  focus-year flags. On an unfiltered agent result it reproduces the agent's own ``severity`` (unit-tested).
* :func:`apply_exclusions` - post-process one agent result (agents 1-4) so that excluded flags disappear from
  ``flags_by_year`` / ``flags_fired`` / ``evidence`` / ``severity``. With nothing excluded the SAME object is
  returned untouched (default runs stay byte-identical).

Known limitation (stated, not hidden): the temporal agent additionally re-derives some flags from STRUCTURED fields
(Beneish zone, Altman zone, auditor/CFO/CEO change, going concern). Excluding one of those flags therefore does NOT
remove it from the temporal score; :func:`unpropagated_flags` lists them so the pipeline can warn. The variant that
motivated this module (``language.passive_voice``) has no structured counterpart and is fully consistent.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional, Union

ENV_VAR = "FORENSIC_EXCLUDE_FLAGS"

# CONTRACTS section 4 hard flags (any one in the focus year => High).
HARD_FLAGS = frozenset({"quantitative.beneish", "network.going_concern", "network.restatement"})
# Both in the same (focus) year => High.
HARD_COMBO = frozenset({"network.auditor_change", "network.cfo_change"})
# Flags the temporal agent re-derives from structured fields even when absent from flags_by_year.
STRUCTURAL_FLAGS = frozenset({
    "quantitative.beneish", "quantitative.altman_distress", "network.auditor_change", "network.cfo_change",
    "network.ceo_change", "network.going_concern",
})


def _parse(value: Union[None, str, Iterable[str]]) -> list[str]:
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    out: list[str] = []
    for it in items:
        s = str(it).strip()
        if s and s not in out:
            out.append(s)
    return out


def get_excluded_flags(override: Union[None, str, Iterable[str]] = None) -> list[str]:
    """Excluded flag names. ``override=None`` -> read env ``FORENSIC_EXCLUDE_FLAGS``; any other value (including
    an empty list/string, meaning "exclude nothing") replaces the environment for this call."""
    if override is not None:
        return _parse(override)
    return _parse(os.environ.get(ENV_VAR, ""))


def unpropagated_flags(excluded: Iterable[str]) -> list[str]:
    """Excluded flags that the temporal agent would still re-derive from structured fields."""
    return sorted(set(excluded) & STRUCTURAL_FLAGS)


def _year(k: Any) -> Optional[int]:
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def recompute_severity(result: dict) -> str:
    """Severity per CONTRACTS section 4 from the result's focus-year ``flags_by_year``.

    High: a hard flag (``quantitative.beneish``, ``network.going_concern``, ``network.restatement``), both
    ``network.auditor_change`` and ``network.cfo_change``, or >= 3 flags; Medium: 2; Low: 1; None: 0
    (peer: >= 3 outliers is the same ">= 3 flags => High" rule). Unavailable / malformed results -> "None".
    """
    if not isinstance(result, dict) or result.get("unavailable"):
        return "None"
    focus = _year(result.get("focus_year"))
    if focus is None:
        return "None"
    flags: set[str] = set()
    for k, fl in (result.get("flags_by_year") or {}).items():
        if _year(k) == focus:
            flags.update(fl or [])
    n = len(flags)
    if flags & HARD_FLAGS or HARD_COMBO <= flags or n >= 3:
        return "High"
    return {2: "Medium", 1: "Low"}.get(n, "None")


def apply_exclusions(result: Any, excluded: Iterable[str]) -> Any:
    """Return ``result`` with ``excluded`` flags removed (and counts/evidence/severity recomputed).

    Identity when ``excluded`` is empty, the result is not a dict, is unavailable, or contains none of the
    excluded flags. Otherwise a shallow copy with new ``flags_by_year``, ``flags_fired``, ``evidence``,
    ``outlier_metrics`` (peer), ``severity``, plus ``excluded_flags`` (what was configured), ``removed_flags``
    ({year: [flag]}) and ``severity_before_exclusion``; ``key_finding`` gets an explicit suffix.
    Per-metric raw observations (e.g. ``passive_voice[y]["flag"]``) are left as measured.
    """
    ex = set(excluded or [])
    if not ex or not isinstance(result, dict) or result.get("unavailable"):
        return result
    fby = result.get("flags_by_year") or {}
    removed: dict = {}
    new_fby: dict = {}
    for y, fl in fby.items():
        keep = [f for f in (fl or []) if f not in ex]
        drop = [f for f in (fl or []) if f in ex]
        new_fby[y] = keep
        if drop:
            removed[y] = drop
    peer_outliers_hit = [m for m in (result.get("outlier_metrics") or []) if f"peer.{m}" in ex]
    if not removed and not peer_outliers_hit:
        return result
    out = dict(result)
    out["flags_by_year"] = new_fby
    out["flags_fired"] = sum(len(v) for v in new_fby.values())
    if "evidence" in out:
        out["evidence"] = [e for e in (result.get("evidence") or []) if not (isinstance(e, dict) and e.get("flag") in ex)]
    if "outlier_metrics" in out:
        out["outlier_metrics"] = [m for m in (result.get("outlier_metrics") or []) if f"peer.{m}" not in ex]
        out["flags_fired"] = sum(len(v) for v in new_fby.values())
    out["severity_before_exclusion"] = result.get("severity")
    out["severity"] = recompute_severity(out)
    out["excluded_flags"] = sorted(ex)
    out["removed_flags"] = removed
    kf = result.get("key_finding")
    if isinstance(kf, str):
        out["key_finding"] = kf + f" [excluded by configuration: {', '.join(sorted({f for v in removed.values() for f in v}))}]"
    return out
