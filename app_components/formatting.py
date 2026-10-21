"""Pure formatting / normalisation helpers for the Streamlit UI (no Streamlit import, unit-testable)."""
from __future__ import annotations

import html
import math
import re
from typing import Any, Optional

# ---- risk grade palette (status colours from the dataviz reference palette; text always accompanies colour) ----
GRADE_STYLE = {
    "Critical": {"bg": "#d03b3b", "fg": "#ffffff", "icon": "●", "word": "CRITICAL"},
    "High": {"bg": "#ec835a", "fg": "#14110f", "icon": "▲", "word": "HIGH"},
    "Medium": {"bg": "#fab219", "fg": "#14110f", "icon": "■", "word": "MEDIUM"},
    "Low": {"bg": "#0ca30c", "fg": "#06150a", "icon": "✓", "word": "LOW"},
}
UNKNOWN_STYLE = {"bg": "#5f5f5a", "fg": "#ffffff", "icon": "?", "word": "UNKNOWN / ERROR"}

# Plotly zone colours for the 0-100 suspicion scale (spec: green 0-30 / yellow 30-60 / orange 60-80 / red 80-100)
ZONES = [(0, 30, "Low", "#0ca30c"), (30, 60, "Medium", "#fab219"), (60, 80, "High", "#ec835a"), (80, 100, "Critical", "#d03b3b")]

FLAG_LABELS = {
    "quantitative.beneish": "Beneish M-Score in manipulator zone",
    "quantitative.altman_distress": "Altman Z in distress zone (business-distress signal)",
    "quantitative.revenue_quality": "Low operating cash flow vs net income (2 yrs)",
    "quantitative.dso_growth": "Days sales outstanding up >20% YoY",
    "quantitative.accruals": "High accruals ratio (>5% of assets)",
    "language.hedging": "Hedging language up >25% YoY",
    "language.passive_voice": "Passive-voice share rose >25% year over year",
    "language.risk_factor_growth": "Risk-factor section grew >40% YoY",
    "language.specificity": "MD&A specificity low / dropping",
    "language.new_legal": "New legal proceedings",
    "network.auditor_change": "Auditor change",
    "network.cfo_change": "CFO change",
    "network.ceo_change": "CEO change",
    "network.audit_fees": "Audit fees up >30% without matching revenue",
    "network.restatement": "Restatement / material weakness",
    "network.related_party": "Related-party disclosures grew",
    "network.going_concern": "Going-concern doubt",
}
AGENT_LABELS = {"quantitative": "Quantitative", "language": "Language", "network": "Network", "peer": "Peer",
                "temporal": "Temporal"}
PEER_METRIC_LABELS = {
    "gross_margin": "Gross margin", "dso": "DSO (days)", "receivables_vs_revenue_growth": "Receivables vs revenue growth",
    "ocf_to_revenue": "OCF / revenue", "debt_to_equity": "Debt / equity", "roa": "Return on assets",
}


def esc(text: Any) -> str:
    """HTML-escape any value for safe use inside unsafe_allow_html blocks."""
    return html.escape("" if text is None else str(text), quote=True)


def md_escape(text: Any) -> str:
    """Escape characters that Streamlit markdown would treat as LaTeX / emphasis surprises ($ mainly)."""
    return ("" if text is None else str(text)).replace("$", "\\$")


def flag_label(flag: str) -> str:
    if flag in FLAG_LABELS:
        return FLAG_LABELS[flag]
    if flag.startswith("peer."):
        m = flag.split(".", 1)[1]
        return f"Peer outlier: {PEER_METRIC_LABELS.get(m, m.replace('_', ' '))}"
    return flag.replace(".", ": ").replace("_", " ")


def agent_of_flag(flag: str) -> str:
    return flag.split(".", 1)[0] if "." in flag else "other"


def grade_style(grade: Any) -> dict:
    return GRADE_STYLE.get(str(grade), UNKNOWN_STYLE)


def is_known_grade(grade: Any) -> bool:
    return str(grade) in GRADE_STYLE


def risk_level_for_score(score: Optional[float]) -> str:
    if score is None:
        return "Unknown"
    return "Low" if score < 30 else "Medium" if score < 60 else "High" if score < 80 else "Critical"


def badge_html(grade: Any, large: bool = False) -> str:
    st_ = grade_style(grade)
    label = st_["word"] if is_known_grade(grade) else UNKNOWN_STYLE["word"]
    size = "2.2rem" if large else "0.85rem"
    pad = "0.5rem 1.4rem" if large else "0.15rem 0.6rem"
    return (f'<span style="display:inline-block;background:{st_["bg"]};color:{st_["fg"]};font-weight:800;'
            f'letter-spacing:.06em;font-size:{size};padding:{pad};border-radius:8px;" '
            f'role="img" aria-label="Risk grade {esc(label)}">{st_["icon"]} {esc(label)}</span>')


def finite(x: Any) -> Optional[float]:
    """float(x) if x is a real finite number else None (NaN/inf/None/str -> None). Never turns missing into 0."""
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def fmt_num(x: Any, nd: int = 2, suffix: str = "") -> str:
    v = finite(x)
    return "n/a" if v is None else f"{v:,.{nd}f}{suffix}"


def fmt_pct(x: Any, nd: int = 1, scale: float = 100.0) -> str:
    v = finite(x)
    return "n/a" if v is None else f"{v * scale:.{nd}f}%"


def fmt_money(x: Any, unit: str = "") -> str:
    v = finite(x)
    if v is None:
        return "n/a"
    a = abs(v)
    for div, s in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v / div:,.2f}{s} {unit}".strip()
    return f"{v:,.0f} {unit}".strip()


def _intify(k: Any) -> Any:
    if isinstance(k, str) and re.fullmatch(r"\d{4}", k):
        return int(k)
    return k


def intkeys(obj: Any) -> Any:
    """Recursively convert 4-digit numeric string dict keys to int (JSON round trip of year-keyed dicts)."""
    if isinstance(obj, dict):
        return {_intify(k): intkeys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [intkeys(v) for v in obj]
    return obj


def normalize_state(obj: Any) -> dict:
    """Accept a live state or a saved JSON (possibly wrapped as {"state": ...}); return a year-int-keyed dict."""
    if not isinstance(obj, dict):
        return {}
    if "risk_grade" not in obj and isinstance(obj.get("state"), dict):
        obj = obj["state"]
    return intkeys(obj)


def years_sorted(d: Any) -> list[int]:
    if not isinstance(d, dict):
        return []
    out = []
    for k in d:
        k2 = _intify(k)
        if isinstance(k2, int):
            out.append(k2)
    return sorted(out)


def yget(d: Any, year: int) -> Any:
    """d[year] tolerant of int/str keys."""
    if not isinstance(d, dict):
        return None
    if year in d:
        return d[year]
    return d.get(str(year))


def degraded_summary(state: dict) -> dict:
    """Which headline components were degraded in this run: {'claude': bool, 'jev': bool, 'other': [str]}."""
    items = [str(x) for x in (state.get("degraded") or [])]
    for k in ("quantitative_result", "language_result", "network_result", "peer_result", "temporal_result"):
        r = state.get(k)
        if isinstance(r, dict):
            items.extend(str(x) for x in (r.get("degraded") or []))
    items = list(dict.fromkeys(items))
    low = [i.lower() for i in items]
    claude = any("anthropic" in i or "llm" in i or "narrative" in i or "claude" in i for i in low)
    jev_scores = state.get("jev_scores") or {}
    jev_avail = state.get("jev_available")
    jev = (jev_avail is False) or any("jev" in i for i in low) or (
        isinstance(jev_scores, dict) and jev_scores and not any(
            isinstance(v, dict) and v.get("available") for v in jev_scores.values()))
    return {"claude": claude, "jev": bool(jev), "items": items}


def jev_overall_available(state: dict) -> bool:
    js = state.get("jev_scores")
    return isinstance(js, dict) and any(isinstance(v, dict) and v.get("available") for v in js.values())
