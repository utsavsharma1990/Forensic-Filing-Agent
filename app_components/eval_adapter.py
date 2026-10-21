"""Reader for evaluation/results/evaluation_results.json (written by evaluation/evaluator.py).

Real layout (verified against the evaluator's output): ``{"metadata", "headline_key": "spec/spec", "headline": run,
"runs": {"spec/spec": run, "spec/no_passive": run, "strict/spec": run, "strict/no_passive": run}, "degraded_banner", ...}``
where a *run* holds ``confusion``, ``metrics`` ({value, ci_low, ci_high, num, den}), ``baselines``, ``contribution.agents``,
``timing.cases``, ``cases`` (one row per case) and ``fraud_nature``. The older tolerant alias lists are kept so that
synthetic/other layouts still work; anything not understood is reported as missing (never invented). ``wilson`` is used
ONLY when counts exist but the evaluator did not supply a CI, and such values are labelled "computed by UI".

The RESULT verdict and the limitations text are NOT in the JSON; they are parsed from the report markdown the evaluator
wrote next to it (``load_last_results`` attaches it as ``report_markdown``) and never re-derived here.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from .formatting import finite

MODE_KEYS = ("spec", "strict")

RUN_LABELS = {
    "spec": "spec analysis years", "strict": "strict point-in-time (pre-revelation filings only)",
    "no_passive": "no passive-voice flag (pre-registered variant)",
}


def wilson(k: int, n: int, z: float = 1.959964) -> Optional[tuple[float, float]]:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _first(d: dict, names: tuple, default=None):
    for n in names:
        if isinstance(d, dict) and n in d and d[n] is not None:
            return d[n]
    return default


def pick_mode(results: dict, mode: Optional[str] = None) -> tuple[dict, str]:
    """Return (the sub-dict holding metrics/cases for one run/mode, its name)."""
    if not isinstance(results, dict):
        return {}, "?"
    runs = results.get("runs")
    if isinstance(runs, dict) and runs:
        hk = results.get("headline_key")
        key = mode if mode in runs else (hk if hk in runs else next(iter(runs)))
        return runs[key], key
    for holder in ("modes", "results", "by_mode"):
        h = results.get(holder)
        if isinstance(h, dict) and any(k in h for k in MODE_KEYS):
            m = mode if mode in h else ("spec" if "spec" in h else next(iter(h)))
            return h[m], m
    for m in MODE_KEYS:
        if isinstance(results.get(m), dict) and (mode in (None, m)):
            return results[m], m
    return results, str(results.get("mode", "spec"))


def run_label(key: str, headline_key: Optional[str] = None) -> str:
    """'spec/no_passive' -> 'spec/no_passive - sensitivity: spec analysis years, no passive-voice flag (...)'."""
    if "/" not in key:
        return key
    mode, variant = key.split("/", 1)
    tag = "HEADLINE" if key == (headline_key or "spec/spec") else "sensitivity"
    bits = [RUN_LABELS.get(mode, mode)] + ([RUN_LABELS.get(variant, variant)] if variant != "spec" else [])
    return f"{key} - {tag}: " + ", ".join(bits)


def available_modes(results: dict) -> list[str]:
    runs = results.get("runs") if isinstance(results, dict) else None
    if isinstance(runs, dict) and runs:
        hk = results.get("headline_key")
        return ([hk] if hk in runs else []) + [k for k in runs if k != hk]
    out = []
    for holder in ("modes", "results", "by_mode"):
        h = results.get(holder) if isinstance(results, dict) else None
        if isinstance(h, dict):
            out += [k for k in h if k in MODE_KEYS]
    out += [m for m in MODE_KEYS if isinstance(results, dict) and isinstance(results.get(m), dict)]
    return list(dict.fromkeys(out)) or ([str(results.get("mode"))] if isinstance(results, dict) and results.get("mode") else [])


def _metric(block: dict, name: str, confusion: dict) -> dict:
    """-> {"value": float|None, "ci": (lo,hi)|None, "ci_source": "evaluator"|"computed by UI"|None, "n", "note"}"""
    metrics = _first(block, ("metrics", "headline", "headline_metrics"), block) or {}
    raw = _first(metrics, (name, name.upper(), name.lower(), {"fpr": "false_positive_rate"}.get(name, name)))
    if raw is None and name == "fpr":
        raw = _first(metrics, ("false_positive_rate", "FPR"))
    value, ci = None, None
    if isinstance(raw, dict):
        value = finite(_first(raw, ("value", "point", "estimate", "p", name)))
        lo = finite(_first(raw, ("ci_low", "lower", "lo", "low", "ci_lower")))
        hi = finite(_first(raw, ("ci_high", "upper", "hi", "high", "ci_upper")))
        arr = _first(raw, ("ci", "ci95", "wilson", "wilson_ci", "ci_95"))
        if isinstance(arr, (list, tuple)) and len(arr) == 2:
            lo, hi = finite(arr[0]), finite(arr[1])
        elif isinstance(arr, dict):
            lo = finite(_first(arr, ("low", "lo", "lower", "ci_low")))
            hi = finite(_first(arr, ("high", "hi", "upper", "ci_high")))
        if lo is not None and hi is not None:
            ci = (max(0.0, round(lo, 12)), min(1.0, round(hi, 12)))   # evaluator CIs carry ~1e-17 float noise at the 0/1 boundary
    else:
        value = finite(raw)
        arr = _first(metrics, (f"{name}_ci", f"{name}_ci95", f"{name}_wilson_ci"))
        if isinstance(arr, (list, tuple)) and len(arr) == 2 and finite(arr[0]) is not None and finite(arr[1]) is not None:
            ci = (float(arr[0]), float(arr[1]))
    src = "evaluator" if ci else None
    tp, fp, tn, fn = (confusion.get(k) for k in ("TP", "FP", "TN", "FN"))
    k_n = {"precision": (tp, (tp or 0) + (fp or 0) if tp is not None and fp is not None else None),
           "recall": (tp, (tp or 0) + (fn or 0) if tp is not None and fn is not None else None),
           "fpr": (fp, (fp or 0) + (tn or 0) if fp is not None and tn is not None else None)}.get(name, (None, None))
    if ci is None and value is not None and k_n[0] is not None and k_n[1]:
        w = wilson(int(k_n[0]), int(k_n[1]))
        if w:
            ci, src = w, "computed by UI from confusion counts"
    n_ = k_n[1]
    if isinstance(raw, dict) and isinstance(raw.get("den"), int) and not isinstance(raw.get("den"), bool):
        n_ = raw["den"]
    return {"value": value, "ci": ci, "ci_source": src, "n": n_, "note": raw.get("note") if isinstance(raw, dict) else None}


def confusion_of(block: dict) -> dict:
    c = _first(block, ("confusion_matrix", "confusion", "counts"), {}) or {}
    out = {}
    for k in ("TP", "FP", "TN", "FN"):
        v = _first(c, (k, k.lower()))
        out[k] = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


def headline(block: dict) -> dict:
    conf = confusion_of(block)
    return {"confusion": conf, **{n: _metric(block, n, conf) for n in ("precision", "recall", "f1", "fpr")}}


def cases_of(block: dict) -> list[dict]:
    rows = _first(block, ("cases", "case_results", "per_case", "rows", "case_rows"), []) or []
    if isinstance(rows, dict):
        rows = [dict(v, ticker=v.get("ticker", k)) if isinstance(v, dict) else {"ticker": k} for k, v in rows.items()]
    return [r for r in rows if isinstance(r, dict)]


def _fmt_first_detection(r: dict):
    fy = _first(r, ("first_detection_year", "first_detection"))
    if fy is None:
        return "none"
    filed = r.get("first_detection_filing_date")
    return f"FY{fy} (filed {filed})" if filed else fy


def case_view(r: dict) -> dict:
    gt = _first(r, ("ground_truth", "actual"))
    actual = ("Fraud" if gt in (1, True, "Fraud", "fraud", "1") else "Clean") if gt is not None else "n/a"
    pred = _first(r, ("predicted", "prediction", "predicted_label"))
    if isinstance(pred, bool) or pred in (0, 1):
        pred = "Fraud-risk (High/Critical)" if pred else "Not flagged"
    err = _first(r, ("error", "errors"))
    status = _first(r, ("status",))
    is_err = bool(err) or str(status).upper() == "ERROR"
    prv = r.get("pre_revelation_valid")
    year = _first(r, ("analysis_year", "year"))
    if r.get("used_strict_alt") and year is not None:
        year = f"{year} (strict alt filing, as_of {r.get('as_of')})"
    return {
        "Company": _first(r, ("label", "company", "company_name", "ticker"), "?") if not r.get("ticker") else
        f"{r.get('ticker')} ({_first(r, ('label', 'company', 'company_name'), '')})".replace(" ()", ""),
        "Year": year,
        "Predicted": "ERROR (excluded)" if is_err else (pred if pred is not None else "n/a"),
        "Actual": actual,
        "Outcome": r.get("outcome") or ("ERROR" if is_err else "n/a"),
        "Risk Grade": "ERROR" if is_err and not r.get("risk_grade") else _first(r, ("risk_grade", "grade"), "n/a"),
        "First Detection": _fmt_first_detection(r),
        "Pre-revelation valid": "n/a" if prv is None else ("yes" if prv else "NO - filing post-dates revelation"),
        "Key Signal": _first(r, ("key_signal", "key_finding", "top_signal"), "n/a") if not is_err else str(err)[:200],
    }


def months_lead(r: dict) -> Optional[float]:
    return finite(_first(r, ("months_before_revelation", "months_before_public_revelation", "detection_lead_months",
                             "months_before_public_revelation_date", "lead_months_revelation")))


def months_collapse(r: dict) -> Optional[float]:
    return finite(_first(r, ("months_before_collapse", "lead_months_collapse")))


def timing_of(block: dict, rows: list[dict]) -> dict:
    """Per-case detection timing.

    The average is computed HERE (not copied from the evaluator, whose own average also includes cases whose filing
    post-dates the revelation) and ONLY over detected fraud cases with a positive lead that are not known to be
    ``pre_revelation_valid=False``. ``invalid`` lists detected cases that are not a valid early-warning test.
    """
    t = _first(block, ("detection_timing", "timing"), {}) or {}
    per = _first(t, ("per_case", "cases", "rows"), None) if isinstance(t, dict) else None
    items = []
    src = per if isinstance(per, list) else rows
    valid_by_ticker = {r.get("ticker"): r.get("pre_revelation_valid") for r in rows if isinstance(r, dict)}
    for r in src:
        if not isinstance(r, dict):
            continue
        gt = _first(r, ("ground_truth", "actual"))
        if gt is not None and gt not in (1, True, "Fraud", "fraud", "1"):
            continue
        prv = r.get("pre_revelation_valid", valid_by_ticker.get(r.get("ticker")))
        items.append({"label": str(_first(r, ("ticker", "label", "case"), "?")), "months": months_lead(r),
                      "months_collapse": months_collapse(r), "valid": prv})
    detected = [i for i in items if i["months"] is not None]
    invalid = [i for i in detected if i["valid"] is False]
    valid = [i for i in detected if i["valid"] is not False]
    positive = [i for i in valid if i["months"] > 0]
    avg = sum(i["months"] for i in positive) / len(positive) if positive else None
    n_fraud = sum(1 for r in rows if _first(r, ("ground_truth", "actual")) in (1, True, "Fraud", "fraud", "1")) or len(items)
    return {"items": items, "detected": detected, "valid": valid, "invalid": invalid, "positive": positive, "average": avg,
            "n_fraud": n_fraud,
            "evaluator_average": finite(t.get("average_months_early_before_revelation")) if isinstance(t, dict) else None,
            "caveat": t.get("caveat") if isinstance(t, dict) else None}


def agent_contrib_of(block: dict) -> list[dict]:
    """-> [{"agent", "flagged_pct", "unique_pct", ...}] with None where the evaluator gave nothing."""
    a = _first(block, ("agent_contribution", "agent_contributions", "per_agent", "agents"), None)
    if a is None:
        c = block.get("contribution") if isinstance(block, dict) else None
        a = c.get("agents") if isinstance(c, dict) and isinstance(c.get("agents"), dict) else {}
    out = []
    if isinstance(a, dict):
        for name, v in a.items():
            if isinstance(v, dict) and ("flag_rate_fraud" in v or "unique_catch_pct_of_fraud" in v):
                def _v(key, v=v):
                    x = v.get(key)
                    x = finite(x.get("value") if isinstance(x, dict) else x)
                    return x * 100 if x is not None else None
                out.append({"agent": name, "flagged_pct": _v("flag_rate_fraud"), "unique_pct": _v("unique_catch_pct_of_fraud"),
                            "false_alarm_pct": _v("false_alarm_rate_clean"),
                            "flagged_cases": v.get("flagged_fraud_cases") or [], "unique_cases": v.get("unique_catches") or [],
                            "false_alarm_cases": v.get("flagged_clean_cases") or [],
                            "unavailable_cases": v.get("unavailable_cases") or []})
                continue
            if isinstance(v, dict):
                fl = finite(_first(v, ("flagged_pct", "pct_flagged", "recall_pct", "flag_rate_pct", "pct_of_fraud_cases_flagged")))
                un = finite(_first(v, ("unique_catch_pct", "unique_pct", "pct_unique", "unique_catches_pct", "unique_contribution_pct")))
                if fl is None:
                    f_ = finite(_first(v, ("flag_rate", "flagged_rate", "flagged_fraction")))
                    fl = f_ * 100 if f_ is not None and f_ <= 1 else f_
                if un is None:
                    u_ = finite(_first(v, ("unique_catch_rate", "unique_rate", "unique_fraction", "unique_catch")))
                    un = u_ * 100 if u_ is not None and u_ <= 1 else u_
            else:
                fl, un = None, finite(v)
                if un is not None and un <= 1:
                    un *= 100
            out.append({"agent": name, "flagged_pct": fl, "unique_pct": un})
    return out


def baselines_of(block: dict) -> list[dict]:
    """-> [{"name", "m": {precision, recall, f1, fpr, accuracy metric dicts}}] for the system and each baseline."""
    b = block.get("baselines") if isinstance(block, dict) else None
    if not isinstance(b, dict):
        return []
    names = {"always_clean": "Always predict 'clean' (trivial)", "beneish_only": "Beneish-only (M > -1.78 in the focus year)"}
    rows = []
    if isinstance(block.get("metrics"), dict):
        rows.append({"name": "This system (High/Critical = positive)", "m": block["metrics"]})
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(v.get("recall"), dict):
            rows.append({"name": names.get(k, k), "m": v})
    return rows


def fmt_metric(m: Any) -> str:
    """'50.0% (CI 18.8-81.2%, 3/6)' / 'undefined (0/0)' from an evaluator metric dict."""
    if not isinstance(m, dict):
        return "n/a"
    v = finite(m.get("value"))
    frac = f"{m.get('num')}/{m.get('den')}" if m.get("num") is not None and m.get("den") is not None else ""
    if v is None:
        return "undefined" + (f" ({frac})" if frac else "")
    lo, hi = finite(m.get("ci_low")), finite(m.get("ci_high"))
    ci = f"CI {max(lo, 0) * 100:.1f}-{hi * 100:.1f}%" if lo is not None and hi is not None else "CI n/a"
    return f"{v * 100:.1f}% ({ci}{', ' + frac if frac else ''})"


def result_lines(results: dict, run_key: str) -> list[str]:
    """The evaluator's RESULT verdict for one run, parsed from the report markdown (never re-derived here)."""
    md = results.get("report_markdown") if isinstance(results, dict) else None
    if not isinstance(md, str):
        return []
    hk = results.get("headline_key")
    lines = md.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if (run_key == hk and ln.startswith("## Headline")) or ln.strip() == f"### Sensitivity run {run_key}":
            start = i
            break
    if start is None:
        return []
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        t = ln.strip()
        if t.startswith("**RESULT") or ("ERRORED" in t and "EXCLUDED" in t):
            out.append(t)
    return out


def limitations_markdown(results: dict) -> Optional[str]:
    """The evaluator's own 'LIMITATIONS AND CONTAMINATION' section (up to the Disclaimer), verbatim, if the report is present."""
    md = results.get("report_markdown") if isinstance(results, dict) else None
    if not isinstance(md, str):
        return None
    i = md.find("## LIMITATIONS AND CONTAMINATION")
    if i < 0:
        return None
    j = md.find("\n## Disclaimer", i)
    return md[i:j if j > 0 else None].strip()


# ----------------------------------------------------------------------------------------------- result sets
# One entry per real result folder under evaluation/results/ (INVALID_* folders are deliberately absent). Role and version
# are properties of how the run was done (see docs/H2_AUDIT.md, docs/HOLDOUT_AUDIT.md), not of the JSON, so they live here.
RESULT_SETS: list[dict] = [
    {"id": "h2_v3", "dir": "h2_v3", "role": "sealed", "version": "v3", "n": 30,
     "label": "H2 sealed holdout (30 filings) - v3 (latest, default)"},
    {"id": "h2_v2", "dir": "h2_v2", "role": "sealed", "version": "v2", "n": 30,
     "label": "H2 sealed holdout (30 filings) - v2"},
    {"id": "h2_v1", "dir": "h2_v1", "role": "sealed", "version": "v1", "n": 30,
     "label": "H2 sealed holdout (30 filings) - v1"},
    {"id": "holdout_v2", "dir": "holdout_v2", "role": "sealed", "version": "v2", "n": 24,
     "label": "Holdout 1 (24 filings) - v2"},
    {"id": "holdout_v1", "dir": "holdout_v1", "role": "sealed", "version": "v1", "n": 24,
     "label": "Holdout 1 (24 filings) - v1"},
    {"id": "dev_v3", "dir": "v3_dev", "role": "development", "version": "v3", "n": 12,
     "label": "Development cases (12 filings) - v3 (NOT a performance estimate)"},
    {"id": "dev_v2", "dir": "", "role": "development", "version": "v2", "n": 12,
     "label": "Development cases (12 filings) - v2 (NOT a performance estimate)"},
    {"id": "dev_v1", "dir": "v1_dev_live_keys", "role": "development", "version": "v1", "n": 12,
     "label": "Development cases (12 filings) - v1 (NOT a performance estimate)"},
    {"id": "dev_v1_degraded", "dir": "degraded_run_no_keys", "role": "development", "version": "v1", "n": 12,
     "label": "Development cases (12 filings) - v1, DEGRADED run without API keys"},
]
AUDIT_DOCS = {"h2": "docs/H2_AUDIT.md", "holdout1": "docs/HOLDOUT_AUDIT.md"}


def set_audit_note(spec: dict) -> str:
    """Plain-text pointer to the audit write-ups relevant to a result set."""
    sid = spec.get("id", "")
    if sid.startswith("h2_"):
        return "Independent audit of this set and the v1 / v2 / v3 comparison: docs/H2_AUDIT.md (detail: docs/H2_AUDIT_A.md, docs/H2_AUDIT_B.md)."
    if sid.startswith("holdout_"):
        return "Independent audit of this set and the v1 / v2 comparison: docs/HOLDOUT_AUDIT.md (detail: docs/HOLDOUT_AUDIT_A.md, docs/HOLDOUT_AUDIT_B.md)."
    return "Why development numbers are not estimates, and the audited holdout results: docs/H2_AUDIT.md, docs/HOLDOUT_AUDIT.md, docs/EVAL_AUDIT.md."


def load_result_set(results_root, spec: dict) -> tuple[Optional[dict], Optional[str]]:
    """Read ``evaluation_results.json`` (+ ``evaluation_report.md`` as ``report_markdown``) of one result set directly from
    disk. Returns (results, None) or (None, reason); never raises and never invents data."""
    import json
    from pathlib import Path
    d = Path(results_root) / spec.get("dir", "")
    p = d / "evaluation_results.json"
    if not p.exists():
        return None, f"{p.as_posix()} not found"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"{p.name} unreadable: {type(exc).__name__}: {exc}"
    if not isinstance(data, dict) or not data:
        return None, f"{p.name} is empty or not a JSON object"
    rp = d / "evaluation_report.md"
    if rp.exists():
        try:
            data["report_markdown"] = rp.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return data, None


def paired_of(block: dict) -> Optional[dict]:
    """The evaluator's paired fraud-vs-matched-control metric (v3 rows only). None when absent or ``available`` is false."""
    p = block.get("paired") if isinstance(block, dict) else None
    if not isinstance(p, dict) or p.get("available") is False:
        return None
    if finite(p.get("n_pairs")) is None:
        return None
    pairs = [x for x in (p.get("pairs") or []) if isinstance(x, dict)]
    return {"n_pairs": int(p["n_pairs"]), "wins": p.get("wins"), "ties": p.get("ties"), "losses": p.get("losses"),
            "p": finite(p.get("sign_test_p_two_sided")), "n_non_tied": p.get("n_non_tied"), "auc": finite(p.get("paired_auc")),
            "auc_lo": finite(p.get("auc_ci_low")), "auc_hi": finite(p.get("auc_ci_high")),
            "resamples": (p.get("bootstrap") or {}).get("resamples") if isinstance(p.get("bootstrap"), dict) else None,
            "pairs": pairs}
