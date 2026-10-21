"""Agent 1 - Quantitative forensics (Beneish, Altman, revenue quality, DSO, accruals).

``run_quantitative(state) -> dict`` is synchronous and never raises.  It reads only raw state
(``annual_facts`` or ``xbrl_data``), never other agents' results.  All numbers are computed in code
(``tools.financial_metrics``); the LLM (Haiku) may only reword a deterministic explanation and every
numeral in its text is validated against the structured facts - otherwise the template is used.

Honesty notes
* Beneish flag = M > -1.78 only; the grey zone is recorded, never flagged (CONTRACTS section 4).
* Beneish SGAI/DEPI may be neutral-imputed by ``financial_metrics`` (reported in ``imputed``).
* Altman uses Z' (book equity) unless a point-in-time market cap is supplied for EVERY analysed year in
  USD; the Altman distress flag is a BUSINESS-DISTRESS signal, not evidence of manipulation.
* Unavailable metrics are ``{"status": "unavailable", "reason": ...}``, never zeros.

v2 (docs/V2_CHANGELOG_agents.md, B6) - MATERIALITY OF THE REVENUE DENOMINATOR.  Beneish's DSRI/GMI/SGI/SGAI indices, DSO and
OCF/revenue all divide by revenue (or by last year's revenue).  When revenue is immaterial relative to the balance sheet
(pre-commercial company, grounded fleet, shell) the ratios explode (SGI of 11x, DSO +1,500%) without carrying any manipulation
information.  :func:`revenue_materiality` defines "immaterial" a priori as ``Revenue < 1% of TotalAssets`` of the SAME year
(unit-free, so it works for any currency); the Beneish M-Score and the DSO flag are then ``not_meaningful`` for a year
whose current OR prior-year revenue is immaterial, and nothing is narrated or flagged from them.

v3 (docs/V3_CHANGELOG_data.md) - PRIOR-YEAR COMPARABILITY.  The prior-year (t-1) values behind Beneish, DSO and OCF/NI are
taken from the comparative columns of the year-t filing (``basis="as_reported_in_current_filing"``: restated for divestitures
and reclassifications, filed <= as_of, so no look-ahead) instead of the originally filed t-1 report, so that t and t-1 are on
the same basis.  :func:`_prior_year_basis` records per year which basis was used (``data_quality.prior_year_basis``), any item
that had to come from the originally filed year, and every item whose comparative value differs from the original.  When the
comparative columns are not available (no XBRL in state, no later filing, core items missing) the originally filed prior year
is used and flagged.  Altman, accruals and the current-year OCF/NI ratio use year t only and are unchanged.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from tools import financial_metrics as fm
from tools import llm
from tools.common import get_logger

log = get_logger(__name__)

FLAG_BENEISH = "quantitative.beneish"
FLAG_ALTMAN = "quantitative.altman_distress"
FLAG_RQ = "quantitative.revenue_quality"
FLAG_DSO = "quantitative.dso_growth"
FLAG_ACCRUALS = "quantitative.accruals"

NO_KEY_NOTE = "llm_explanations: ANTHROPIC_API_KEY not set (deterministic templates used)"
MATERIALITY_REVENUE_TO_ASSETS = 0.01  # B6: revenue below 1% of total assets => revenue-denominated ratios are not meaningful
UNSTABLE_SGI = 3.0   # fixed a priori: revenue more than tripled -> Beneish indices unstable (caveat only, never changes a flag)

_PATTERN_NOTE = ("receivables outpacing sales is the classic channel-stuffing / premature-revenue-recognition "
                 "pattern")


# --------------------------------------------------------------------------- helpers
def revenue_materiality(d: Optional[dict]) -> tuple[bool, str]:
    """``(is_material, reason)`` for one flattened year dict.

    Revenue is IMMATERIAL when ``Revenue < MATERIALITY_REVENUE_TO_ASSETS * TotalAssets`` (1%, same year; revenue <= 0
    included).  Why 1% of assets: asset turnover (revenue/assets) of operating businesses is typically 0.05 (banks,
    insurers, REITs) to 2+ (retail); a company at < 0.01 is pre-commercial, dormant, a shell or in an abrupt revenue
    collapse, where a ratio with revenue in the denominator measures the denominator, not behaviour.  Relative to assets,
    the rule is unit- and currency-free.  When revenue or assets is missing nothing can be judged: ``(True, "")`` (the
    ordinary missing-data handling then applies).
    """
    if not isinstance(d, dict):
        return True, ""
    rev, ta = d.get("Revenue"), d.get("TotalAssets")
    if rev is None or ta is None or ta <= 0:
        return True, ""
    if rev < MATERIALITY_REVENUE_TO_ASSETS * ta:
        return False, (f"revenue is below {MATERIALITY_REVENUE_TO_ASSETS:.0%} of total assets "
                       f"({rev / ta:.2%}), so ratios with revenue in the denominator are not meaningful")
    return True, ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _f(x: Any, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def _numerals(text: str) -> list[float]:
    """Numbers quoted in a display string (fiscal-year tokens removed, signs kept)."""
    t = re.sub(r"\bFY\s?\d{4}\b", " ", text)
    out = []
    for m in re.finditer(r"(?<![\w.])(-?)(\d[\d,]*(?:\.\d+)?)", t):
        try:
            v = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        out.append(-v if m.group(1) else v)
    return out


def _has_data(d: Optional[dict]) -> bool:
    return bool(d) and any(v is not None for v in d.values())


def _missing_reason(res: dict, annual_missing: dict) -> str:
    """Reason text naming the missing canonical items and XBRL concepts."""
    parts = []
    base = (res.get("explanation") or "").strip()
    if base:
        parts.append(base)
    miss = res.get("missing") or []
    extra = [f"{k}: {annual_missing[k]}" for k in miss if k in annual_missing]
    if extra:
        parts.append("source detail: " + " | ".join(extra))
    return " ".join(parts) or "unavailable (no reason reported by financial_metrics)"


# --------------------------------------------------------------------------- explanations
def _beneish_body(y: int, facts: dict) -> str:
    rg, ag = facts.get("revenue_growth_pct"), facts.get("receivables_growth_pct")
    parts: list[str] = []
    if rg is not None and ag is not None:
        s = f"Revenue grew {_f(rg)}% while net receivables grew {_f(ag)}% in FY{y}"
        s += f" - {_PATTERN_NOTE}" if ag > rg else " - receivables did not outpace sales"
        parts.append(s)
    elif rg is not None:
        parts.append(f"Revenue grew {_f(rg)}% in FY{y} (receivables growth not computable)")
    gc, gp, gd = (facts.get("gross_margin_cur"), facts.get("gross_margin_prev"),
                  facts.get("gross_margin_change_pp"))
    if gc is not None and gp is not None and gd is not None:
        parts.append(f"gross margin moved from {_f(gp * 100)}% to {_f(gc * 100)}% ({gd:+.1f} percentage points)")
    ta = facts.get("accrual_to_assets")
    if ta is not None and ta > 0:
        parts.append(f"net income less operating cash flow was {_f(ta * 100)}% of total assets")
    return "; ".join(parts) if parts else f"Beneish component indices elevated in FY{y}"


def _beneish_template(y: int, m: float, facts: dict, imputed: list[str]) -> str:
    text = _beneish_body(y, facts)
    text += f". Beneish M-Score {_f(m, 2)} is above the -1.78 manipulation cut-off"
    if imputed:
        text += f" (neutral value 1.0 imputed for {', '.join(imputed)}: input not available)"
    return text + "."


def _allowed_numbers(facts: dict, extra: list[float]) -> set[float]:
    vals: set[float] = set()

    def add(x: float) -> None:
        for nd in (0, 1, 2, 3):
            vals.add(round(abs(x), nd))
            vals.add(round(abs(x) * 100, nd))

    def walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)) and math.isfinite(o):
            add(float(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(facts)
    for e in extra:
        vals.add(round(abs(e), 2))
        vals.add(round(abs(e), 1))
        vals.add(round(abs(e)))
    return vals


def numerals_valid(text: str, facts: dict, extra: list[float]) -> bool:
    """True iff every numeral in ``text`` is traceable to ``facts`` (or fixed constants / years in ``extra``)."""
    allowed = _allowed_numbers(facts, extra)
    for v in _numerals(text):
        if abs(v) not in allowed and round(abs(v), 2) not in allowed and round(abs(v), 1) not in allowed:
            return False
    # bare year tokens such as FY2000 are removed by _numerals; any other 4-digit year must be allowed explicitly
    for yy in re.findall(r"\bFY\s?(\d{4})\b", text):
        if float(yy) not in allowed:
            return False
    return True


_LLM_SYSTEM = (
    "You are an editor for a forensic-accounting report. Rewrite the given deterministic explanation in clear, "
    "plain English (1-3 sentences). HARD RULES: change wording only; never add, compute, round differently or "
    "infer any number; every numeral you write must already appear in FACTS or TEMPLATE; do not claim fraud "
    "or intent, only describe the pattern. Return JSON exactly like {\"explanation\": \"...\"}."
)


def _llm_reword(y: int, template: str, facts: dict, extra: list[float], degraded: list[str]) -> str:
    """Haiku rewrite validated numerically; returns the template when unavailable/invalid."""
    try:
        if not llm.llm_available():
            return template
        user = json.dumps({"fiscal_year": y, "FACTS": facts, "TEMPLATE": template}, default=str, sort_keys=True)
        out = llm.llm_json("haiku", _LLM_SYSTEM, user, max_tokens=400)
        text = out.get("explanation") if isinstance(out, dict) else None
        if not isinstance(text, str) or not text.strip():
            degraded.append(f"llm_explanations: FY{y} LLM returned no usable text; deterministic template used")
            return template
        allowed_extra = list(extra) + [float(y), float(y - 1), 1.78, 2.22, 0.8, 20.0, 5.0]
        # numerals of the template itself are traceable by construction
        allowed_extra += [abs(v) for v in _numerals(template)]
        if not numerals_valid(text, facts, allowed_extra):
            degraded.append(f"llm_explanations: FY{y} numeric validation failed; deterministic template used")
            return template
        return text.strip()
    except Exception as exc:  # never raise
        degraded.append(f"llm_explanations: FY{y} LLM error ({type(exc).__name__}); deterministic template used")
        return template


# --------------------------------------------------------------------------- core
def _resolve_annual(state: dict, years: list[int], degraded: list[str]) -> Optional[dict]:
    annual = state.get("annual_facts")
    if isinstance(annual, dict) and annual.get("by_year") is not None:
        return annual
    xb = state.get("xbrl_data")
    if isinstance(xb, dict) and xb:
        try:
            from tools.xbrl_parser import extract_annual_facts
            ys = sorted(set(years) | ({min(years) - 1} if years else set()))
            degraded.append("annual_facts: not in state; rebuilt from xbrl_data (XBRL filers only, no statement-table path)")
            return extract_annual_facts(xb, ys, as_of=state.get("as_of"))
        except Exception as exc:
            degraded.append(f"annual_facts: rebuild from xbrl_data failed ({type(exc).__name__}: {exc})")
    return None


def _unavailable_result(reason: str, focus_year: Optional[int], degraded: list[str]) -> dict:
    return {"error": reason, "unavailable": True, "severity": "None", "flags_fired": 0, "flags_by_year": {},
            "focus_year": focus_year, "key_finding": f"Quantitative analysis unavailable: {reason}",
            "beneish_scores": {}, "altman_scores": {}, "revenue_quality": {}, "dso_trend": {},
            "accruals_ratio": {}, "highest_risk_year": None, "evidence": [],
            "data_quality": {"unavailable": {"all": reason}}, "degraded": list(degraded)}


#: Income-statement items taken ONLY from the comparative column when it is used (mixing a restated revenue with an
#: originally filed cost line would manufacture a margin change).
_PRIOR_IS_BLOCK = ("Revenue", "COGS", "GrossProfit", "SGA")
#: Items without which the comparative column is not used at all (the whole prior year falls back to the original filing).
_PRIOR_CORE = ("Revenue", "NetReceivables", "CurrentAssets", "PPE", "TotalAssets")


def _prior_year_basis(state: dict, annual: dict, years: list[int], flat: dict[int, dict],
                      degraded: list[str]) -> tuple[dict[int, dict], dict[int, dict]]:
    """Prior-year (t-1) value dicts for each analysed year t, plus the per-year basis record.

    Returns ``(prev_by_year, info_by_year)``.  ``prev_by_year[t]`` is a flattened dict for fiscal year t-1 taken from the
    comparative columns of the year-t filing when possible (XBRL comparatives from ``state['xbrl_data']`` or, for
    statement-table years, ``annual_facts['comparative_by_year']``), else the originally filed t-1 values (``flat[t-1]``).
    The income-statement block (Revenue, COGS, GrossProfit, SGA) is never mixed between the two bases; other items missing
    from the comparative column are filled from the original year and listed (``basis`` = ``"mixed"``).
    """
    from tools.common import flatten_year
    cmp_xbrl: Optional[dict] = None
    cmp_flat: dict[int, dict] = {}
    xb = state.get("xbrl_data")
    if isinstance(xb, dict) and xb and years:
        try:
            from tools.xbrl_parser import extract_annual_facts, flatten_annual
            ys = sorted(set(years) | {min(years) - 1})
            cmp_xbrl = extract_annual_facts(xb, ys, as_of=state.get("as_of"), basis="as_reported_in_current_filing")
            cmp_flat = flatten_annual(cmp_xbrl)
        except Exception as exc:
            degraded.append(f"prior_year_basis: comparative extraction failed ({type(exc).__name__}: {exc}); "
                            "originally filed prior years used")
            cmp_xbrl = None
    tbl = annual.get("comparative_by_year") or {}
    prev_by: dict[int, dict] = {}
    info: dict[int, dict] = {}
    for y in years:
        py = y - 1
        orig = dict(flat.get(py) or {})
        rec: dict[str, Any] = {"prior_year": py, "basis": "originally_filed", "comparative_source": None,
                               "filled_from_original": [], "changed_items": {}, "reason": ""}
        comp: dict[str, Optional[float]] = {}
        src_desc = None
        cb = ((cmp_xbrl or {}).get("comparative_basis") or {}).get(py) or {}
        if cmp_xbrl is not None and cb.get("from_accession") and cb.get("basis_used") in ("comparative", "mixed"):
            skip = set(cb.get("fallback_items") or [])
            comp = {k: v for k, v in (cmp_flat.get(py) or {}).items() if v is not None and k not in skip}
            src_desc = f"XBRL comparatives of filing {cb['from_accession']}"
        if not comp:
            tb = tbl.get(py) or tbl.get(str(py))
            if tb:
                comp = {k: v for k, v in flatten_year(tb).items() if v is not None}
                src_desc = f"statement-table comparatives of the FY{y} filing"
        if not comp:
            rec["reason"] = ("no comparative column available ("
                             + (cb.get("reason") or "no XBRL comparatives / statement-table comparatives in state")
                             + "); originally filed prior year used")
            prev_by[y], info[y] = orig, rec
            continue
        have_cogs = comp.get("COGS") is not None or comp.get("GrossProfit") is not None
        core_missing = [k for k in _PRIOR_CORE if comp.get(k) is None] + ([] if have_cogs else ["COGS|GrossProfit"])
        if core_missing:
            rec["reason"] = (f"comparative column lacks core items {core_missing}; originally filed prior year used "
                             "(restatements, if any, are not reflected)")
            prev_by[y], info[y] = orig, rec
            continue
        merged = {k: v for k, v in orig.items() if k not in _PRIOR_IS_BLOCK}
        filled = sorted(k for k, v in merged.items() if v is not None and comp.get(k) is None)
        merged.update(comp)
        for k in _PRIOR_IS_BLOCK:
            merged.setdefault(k, None)
        changed = {}
        for k, v in comp.items():
            o = orig.get(k)
            if o is not None and abs(v - o) > 0.005 * max(abs(o), abs(v), 1.0):
                changed[k] = {"original": o, "comparative": v}
        rec.update({"basis": "mixed" if filled else "as_reported_in_current_filing", "comparative_source": src_desc,
                    "filled_from_original": filled, "changed_items": changed,
                    "reason": ("items not in the comparative column taken from the originally filed year: " + ", ".join(filled))
                    if filled else ""})
        prev_by[y], info[y] = merged, rec
    return prev_by, info


def _imputed_inputs(annual: dict, y: int) -> dict[str, dict]:
    """Beneish inputs of year y that were imputed upstream (LongTermDebt = 0 with balance-sheet evidence), by role."""
    out: dict[str, dict] = {}
    for yy, role in ((y, "current"), (y - 1, "prior")):
        for k, note in ((annual.get("imputed_by_year") or {}).get(yy) or {}).items():
            out.setdefault(k, {})[role] = note
    return out


def _normalise_by_year(annual: dict) -> dict[int, dict]:
    from tools.xbrl_parser import flatten_annual
    flat = flatten_annual(annual)
    return {int(y): v for y, v in flat.items()}


def _analyse(state: dict, degraded: list[str]) -> dict:
    years_in = [int(y) for y in (state.get("analysis_years") or [])]
    annual = _resolve_annual(state, years_in, degraded)
    if annual is None:
        return _unavailable_result("no annual_facts or xbrl_data in state", state.get("focus_year"), degraded)

    flat = _normalise_by_year(annual)
    amiss: dict[int, dict] = {int(k): v for k, v in (annual.get("missing") or {}).items()}
    years = sorted(years_in) if years_in else sorted(y for y, d in flat.items() if _has_data(d))
    if not years:
        return _unavailable_result("no fiscal years with data", state.get("focus_year"), degraded)
    focus = int(state.get("focus_year") or max(years))
    unit = annual.get("unit") or "unknown"
    warnings = list(annual.get("warnings") or [])

    # market cap policy: only a dict covering every analysed year in USD switches to the original Z
    mc = state.get("market_cap")
    mc_by_year: Optional[dict[int, float]] = None
    altman_note = "Altman Z' (book-equity variant) used: no point-in-time market cap supplied"
    if isinstance(mc, dict) and unit == "USD":
        try:
            cand = {int(k): float(v) for k, v in mc.items() if v is not None}
            if all(y in cand and cand[y] > 0 for y in years if _has_data(flat.get(y))):
                mc_by_year = cand
                altman_note = "Altman Z (public-company variant) used with supplied market caps"
        except Exception:
            mc_by_year = None
    elif mc is not None:
        altman_note = ("Altman Z' (book-equity variant) used: market cap ignored (must be a per-year dict for "
                       "every analysed year, in the same currency as the filings)")

    beneish: dict[int, dict] = {}
    altman: dict[int, dict] = {}
    rq: dict[int, dict] = {}
    dso_t: dict[int, dict] = {}
    accr: dict[int, dict] = {}
    flags_by_year: dict[int, list[str]] = {y: [] for y in years}
    evidence: list[dict] = []
    unavailable: dict[str, str] = {}
    comparative_years: dict[int, list[str]] = {}
    caveats: list[str] = []
    llm_used_years: list[int] = []

    fv_by_year = annual.get("by_year") or {}
    filing_by_year = annual.get("filing_by_year") or {}
    prev_basis_vals, prior_info = _prior_year_basis(state, annual, years, flat, degraded)
    imputed_inputs: dict[int, dict] = {}

    def unavail(metric: str, y: int, reason: str, container: dict) -> None:
        container[y] = {"status": "unavailable", "reason": reason}
        unavailable[f"{metric}:{y}"] = reason

    for y in years:
        cur = flat.get(y)
        prev = prev_basis_vals.get(y)   # v3: year t-1 as reported in the year-t filing (flagged fallback: originally filed)
        prev_ok = _has_data(prev)
        am = amiss.get(y, {})
        fvs = fv_by_year.get(y) or fv_by_year.get(str(y)) or {}
        comp_items = sorted(k for k, v in fvs.items() if isinstance(v, dict) and v.get("comparative"))
        if comp_items:
            comparative_years[y] = comp_items
        if not _has_data(cur):
            reason = f"no data for FY{y}: no annual filing/XBRL facts found as of the as_of date"
            for metric, cont in (("beneish", beneish), ("altman", altman), ("revenue_quality", rq),
                                 ("dso", dso_t), ("accruals", accr)):
                unavail(metric, y, reason, cont)
            continue
        own = (filing_by_year.get(y) or filing_by_year.get(str(y)) or {})
        if own.get("n_annual_filings_for_year") == 0 or (filing_by_year and y not in filing_by_year
                                                            and str(y) not in filing_by_year):
            caveats.append(f"FY{y}: no annual filing of its own in the data; values come from comparative columns "
                           "of later filings (not the first public disclosure of that year)")

        # ---- Beneish
        try:
            mat_c, why_c = revenue_materiality(cur)
            mat_p, why_p = revenue_materiality(prev) if prev_ok else (True, "")
            if not prev_ok:
                unavail("beneish", y, f"no prior-year (FY{y - 1}) data: Beneish needs two consecutive years", beneish)
            elif not (mat_c and mat_p):
                unavail("beneish", y, "not meaningful: " + (f"FY{y} " + why_c if not mat_c else f"FY{y - 1} " + why_p)
                        + " (Beneish DSRI/GMI/SGI/SGAI)", beneish)
                beneish[y]["status"] = "not_meaningful"
            else:
                r = fm.beneish_m_score(cur, prev)
                if r.get("status") != "ok" or r.get("m_score") is None:
                    unavail("beneish", y, _missing_reason(r, am), beneish)
                else:
                    m = float(r["m_score"])
                    facts = fm.beneish_explanation_facts(r["components"], cur, prev)
                    imputed = list(r.get("imputed") or [])
                    zone = r.get("zone")
                    flag = bool(r.get("flag"))
                    template = _beneish_template(y, m, facts, imputed) if flag else (
                        f"Beneish M-Score {_f(m, 2)} in FY{y}: {zone} zone"
                        + (" (between -2.22 and -1.78: recorded, not flagged)" if zone == "grey" else "") + ".")
                    explanation = template
                    if flag:
                        explanation = _llm_reword(y, template, facts, [m], degraded)
                        if explanation != template:
                            llm_used_years.append(y)
                    inp_imp = _imputed_inputs(annual, y)
                    if inp_imp:
                        imputed_inputs[y] = inp_imp
                    entry = {"status": "ok", "score": m, "zone": zone, "flag": flag,
                             "flag_level": r.get("flag_level"), "grey_zone": zone == "grey",
                             "explanation": explanation, "imputed": imputed,
                             "imputed_reasons": r.get("imputed_reasons") or {},
                             "components": r.get("components"), "top_drivers": facts.get("top_drivers"),
                             "prior_year_basis": (prior_info.get(y) or {}).get("basis"),
                             "input_imputations": inp_imp, "caveats": []}
                    sgi = (r.get("components") or {}).get("SGI")
                    if sgi is not None and sgi > UNSTABLE_SGI:
                        entry["caveats"].append(
                            f"revenue grew {_f((sgi - 1) * 100, 0)}% in one year: Beneish indices are unstable on a "
                            "rapidly changing revenue base (caveat only; the flag is unchanged)")
                    if imputed:
                        entry["caveats"].append("neutral 1.0 imputed for " + ", ".join(imputed)
                                                + "; result is lower-confidence")
                    if inp_imp:
                        entry["caveats"].append("input imputed from balance-sheet evidence: " + ", ".join(
                            f"{k}=0 (no such line on the balance sheet)" for k in sorted(inp_imp)))
                    if (prior_info.get(y) or {}).get("basis") == "originally_filed":
                        entry["caveats"].append("prior year is the originally filed one (no comparative column): "
                                                + ((prior_info.get(y) or {}).get("reason") or "restatements not reflected"))
                    beneish[y] = entry
                    if flag:
                        flags_by_year[y].append(FLAG_BENEISH)
                        disp = (f"Beneish M-Score was {_f(m, 2)} in FY{y}, above the -1.78 manipulation "
                                f"threshold. {_beneish_body(y, facts)}.")
                        if imputed:
                            disp += f" Neutral value 1.0 was imputed for {', '.join(imputed)}."
                        evidence.append({"flag": FLAG_BENEISH, "year": y, "metric": "beneish_m_score",
                                         "value": m, "display": disp, "numbers": _numerals(disp),
                                         "signal_type": "manipulation", "imputed": imputed})
        except Exception as exc:
            unavail("beneish", y, f"internal error: {type(exc).__name__}: {exc}", beneish)

        # ---- Altman
        try:
            mcap = mc_by_year.get(y) if mc_by_year else None
            r = fm.altman_z(cur, market_cap=mcap)
            if r.get("status") != "ok" or r.get("score") is None:
                unavail("altman", y, _missing_reason(r, am), altman)
            else:
                z, zone, variant = float(r["score"]), r.get("zone"), r.get("variant")
                flag = zone == "distress"
                altman[y] = {"status": "ok", "score": z, "zone": zone, "variant": variant, "flag": flag,
                             "signal_type": "business_distress", "unit": unit,
                             "components": r.get("components"), "derived": r.get("derived") or [],
                             "note": ("BUSINESS-DISTRESS signal, not evidence of manipulation. " + altman_note
                                      + (". Grey zone is not distress." if zone == "grey" else "."))}
                if flag:
                    flags_by_year[y].append(FLAG_ALTMAN)
                    cut = 1.81 if variant == "Z" else 1.23
                    disp = (f"Altman {variant} score was {_f(z, 2)} in FY{y}, inside the distress zone (below {cut}). "
                            "This is a business-distress signal (solvency risk), not evidence of accounting manipulation.")
                    evidence.append({"flag": FLAG_ALTMAN, "year": y, "metric": "altman_z", "value": z,
                                     "display": disp, "numbers": _numerals(disp),
                                     "signal_type": "business_distress", "variant": variant})
        except Exception as exc:
            unavail("altman", y, f"internal error: {type(exc).__name__}: {exc}", altman)

        # ---- revenue quality
        try:
            r = fm.revenue_quality(cur, prev if prev_ok else None)
            if r.get("status") == "unavailable":
                unavail("revenue_quality", y, _missing_reason(r, am), rq)
            elif r.get("status") == "not_meaningful" or r.get("ratio") is None:
                unavail("revenue_quality", y, "not meaningful: net income <= 0 so OCF/NI is not a quality signal", rq)
                rq[y]["status"] = "not_meaningful"
                unavailable.pop(f"revenue_quality:{y}", None)
                unavailable[f"revenue_quality:{y}"] = rq[y]["reason"]
            else:
                flag = bool(r.get("flag"))
                rq[y] = {"status": "ok", "ratio": float(r["ratio"]), "prior_ratio": r.get("prior_ratio"),
                         "flag": flag, "flag_evaluable": bool(r.get("flag_evaluable")),
                         "note": None if r.get("flag_evaluable") else
                         "prior-year ratio unavailable or not meaningful: the two-year flag could not be evaluated"}
                if flag:
                    flags_by_year[y].append(FLAG_RQ)
                    disp = (f"Operating cash flow was {_f(r['ratio'], 2)}x net income in FY{y} and "
                            f"{_f(r['prior_ratio'], 2)}x in FY{y - 1}; below 0.8 in two consecutive years means "
                            "reported profit is not converting into cash.")
                    evidence.append({"flag": FLAG_RQ, "year": y, "metric": "revenue_quality_ocf_to_ni",
                                     "value": float(r["ratio"]), "display": disp, "numbers": _numerals(disp),
                                     "signal_type": "manipulation"})
        except Exception as exc:
            unavail("revenue_quality", y, f"internal error: {type(exc).__name__}: {exc}", rq)

        # ---- DSO
        try:
            mat_c, why_c = revenue_materiality(cur)
            mat_p, why_p = revenue_materiality(prev) if prev_ok else (True, "")
            r = fm.dso(cur, prev if prev_ok else None)
            if r.get("status") == "ok" and r.get("dso_days") is not None and not mat_c:
                unavail("dso", y, f"not meaningful: FY{y} " + why_c, dso_t)
                dso_t[y]["status"] = "not_meaningful"
            elif r.get("status") == "ok" and r.get("dso_days") is not None and not mat_p:
                dso_t[y] = {"status": "ok", "dso_days": float(r["dso_days"]), "prior_dso_days": None,
                            "yoy_change_pct": None, "flag": False,
                            "note": f"not meaningful: FY{y - 1} " + why_p + ": YoY flag not evaluated"}
                unavailable[f"dso_yoy:{y}"] = dso_t[y]["note"]
            elif r.get("status") != "ok" or r.get("dso_days") is None:
                unavail("dso", y, _missing_reason(r, am), dso_t)
            else:
                flag = bool(r.get("flag"))
                note = None
                if r.get("yoy_change_pct") is None:
                    note = ("no usable prior-year DSO (first year, missing data, or prior-year receivables = 0 so "
                            "growth is undefined): YoY flag not evaluated")
                dso_t[y] = {"status": "ok", "dso_days": float(r["dso_days"]),
                            "prior_dso_days": r.get("prior_dso_days"), "yoy_change_pct": r.get("yoy_change_pct"),
                            "flag": flag, "note": note}
                if flag:
                    flags_by_year[y].append(FLAG_DSO)
                    facts = fm.beneish_explanation_facts({}, cur, prev) if prev_ok else {}
                    disp = (f"DSO rose from {_f(r['prior_dso_days'])} to {_f(r['dso_days'])} days "
                            f"(+{_f(r['yoy_change_pct'])}%) in FY{y}, above the +20% threshold.")
                    rg, ag = facts.get("revenue_growth_pct"), facts.get("receivables_growth_pct")
                    if rg is not None and ag is not None:
                        disp += (f" Revenue grew {_f(rg)}% while net receivables grew {_f(ag)}% in FY{y}"
                                 + (f" - {_PATTERN_NOTE}." if ag > rg else "."))
                    evidence.append({"flag": FLAG_DSO, "year": y, "metric": "dso_yoy_change_pct",
                                     "value": float(r["yoy_change_pct"]), "display": disp,
                                     "numbers": _numerals(disp), "signal_type": "manipulation"})
        except Exception as exc:
            unavail("dso", y, f"internal error: {type(exc).__name__}: {exc}", dso_t)

        # ---- accruals
        try:
            r = fm.accruals_ratio(cur)
            if r.get("status") != "ok" or r.get("ratio") is None:
                unavail("accruals", y, _missing_reason(r, am), accr)
            else:
                flag = bool(r.get("flag"))
                accr[y] = {"status": "ok", "ratio": float(r["ratio"]), "flag": flag}
                if flag:
                    flags_by_year[y].append(FLAG_ACCRUALS)
                    disp = (f"Accruals (net income minus operating cash flow) were {_f(r['ratio'] * 100)}% of total "
                            f"assets in FY{y}, above the 5.0% threshold: earnings are running ahead of cash.")
                    evidence.append({"flag": FLAG_ACCRUALS, "year": y, "metric": "accruals_ratio",
                                     "value": float(r["ratio"]), "display": disp, "numbers": _numerals(disp),
                                     "signal_type": "manipulation"})
        except Exception as exc:
            unavail("accruals", y, f"internal error: {type(exc).__name__}: {exc}", accr)

    # ---- aggregate
    flags_fired = sum(len(v) for v in flags_by_year.values())
    focus_flags = flags_by_year.get(focus, [])
    if FLAG_BENEISH in focus_flags or len(focus_flags) >= 3:
        severity = "High"
    elif len(focus_flags) == 2:
        severity = "Medium"
    elif len(focus_flags) == 1:
        severity = "Low"
    else:
        severity = "None"

    def risk_key(y: int) -> tuple:
        b = beneish.get(y, {})
        return (len(flags_by_year[y]), b.get("score") if b.get("status") == "ok" else -1e9, y)

    scored = [y for y in years if flags_by_year[y] or beneish.get(y, {}).get("status") == "ok"]
    highest = max(scored, key=risk_key) if scored else None

    key_finding = _key_finding(years, focus, beneish, altman, flags_by_year, evidence, unit, unavailable)
    n_unavail = len(unavailable)

    data_quality: dict[str, Any] = {"unavailable": unavailable, "unit": unit,
                                    "source_by_year": {int(k): v for k, v in (annual.get("source_by_year") or {}).items()},
                                    "comparative_filled": comparative_years, "caveats": caveats,
                                    "prior_year_basis": {int(y): v for y, v in prior_info.items()},
                                    "imputed_inputs": imputed_inputs,
                                    "statement_table_items": {int(k): v for k, v in (annual.get("item_fallback_by_year") or {}).items()},
                                    "altman_variant_note": altman_note}
    if unit not in ("USD", "unknown"):
        data_quality["unit_note"] = (f"Figures are in {unit}; all ratios/scores are unit-free so results are "
                                     "comparable, but absolute amounts are not USD and no FX conversion is applied.")
    if warnings:
        data_quality["upstream_warnings"] = warnings[:10]

    return {
        "beneish_scores": beneish, "altman_scores": altman, "revenue_quality": rq, "dso_trend": dso_t,
        "accruals_ratio": accr, "flags_fired": flags_fired, "highest_risk_year": highest,
        "key_finding": key_finding, "severity": severity, "flags_by_year": flags_by_year,
        "focus_year": focus, "unit": unit, "data_quality": data_quality, "evidence": evidence,
        "degraded": list(degraded), "n_unavailable_metrics": n_unavail, "analysed_years": years,
    }


def _key_finding(years, focus, beneish, altman, flags_by_year, evidence, unit, unavailable) -> str:
    def ev(flag: str, prefer: Optional[int] = None) -> Optional[dict]:
        items = [e for e in evidence if e["flag"] == flag]
        if not items:
            return None
        items.sort(key=lambda e: (e["year"] == prefer, e["year"]), reverse=True)
        return items[0]

    b = ev(FLAG_BENEISH, focus)
    if b:
        return f"Beneish M-Score {_f(b['value'], 2)} in FY{b['year']} is in the manipulator zone (> -1.78)" + \
               (f" (SGAI/DEPI imputed: {', '.join(b['imputed'])})." if b.get("imputed") else ".")
    others = [e for e in evidence if e["flag"] != FLAG_ALTMAN and e["year"] == focus]
    if others:
        e = others[0]
        return e["display"].split(". ")[0].rstrip(".") + "."
    if any(e["flag"] != FLAG_ALTMAN for e in evidence):
        e = sorted((e for e in evidence if e["flag"] != FLAG_ALTMAN), key=lambda e: e["year"], reverse=True)[0]
        return e["display"].split(". ")[0].rstrip(".") + "."
    a = ev(FLAG_ALTMAN, focus)
    if a:
        cur = f" (figures in {unit})" if unit not in ("USD", "unknown") else ""
        return (f"Altman {a.get('variant')} {_f(a['value'], 2)} in FY{a['year']} is in the distress zone{cur}: "
                "a business-distress signal, not evidence of manipulation; Beneish "
                + ("unavailable." if not any(v.get("status") == "ok" for v in beneish.values()) else "not flagged."))
    ok = [y for y in years if beneish.get(y, {}).get("status") == "ok"]
    if ok:
        y = max(ok)
        return (f"No quantitative manipulation flags fired; latest Beneish M-Score {_f(beneish[y]['score'], 2)} "
                f"(FY{y}, {beneish[y]['zone']} zone).")
    if altman.get(focus, {}).get("status") == "ok":
        return (f"Beneish unavailable (see data_quality); Altman {altman[focus]['variant']} "
                f"{_f(altman[focus]['score'], 2)} in FY{focus} ({altman[focus]['zone']} zone); no manipulation flags.")
    return "Quantitative metrics largely unavailable for the analysed years (see data_quality.unavailable)."


# --------------------------------------------------------------------------- public API
def run_quantitative(state: dict) -> dict:
    """Run agent 1. Returns ``{"quantitative_result", "agent_trace", "degraded"}``; never raises."""
    started = _now()
    t0 = time.perf_counter()
    degraded: list[str] = []
    try:
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        if not llm.llm_available():
            degraded.append(NO_KEY_NOTE)
        result = _analyse(state, degraded)
        result["degraded"] = list(dict.fromkeys(degraded))
        degraded = result["degraded"]
        status = "unavailable" if result.get("unavailable") else ("degraded" if degraded else "ok")
        summary = (f"severity={result.get('severity')} flags={result.get('flags_fired')} "
                   f"focus={result.get('focus_year')}: {result.get('key_finding')}")
    except Exception as exc:  # absolute last resort
        log.warning("quantitative agent failed: %s", exc)
        msg = f"{type(exc).__name__}: {exc}"
        fy = state.get("focus_year") if isinstance(state, dict) else None
        degraded.append(f"quantitative: internal failure ({msg})")
        result = _unavailable_result(msg, fy, degraded)
        status, summary = "error", msg
    trace = {"agent": "quantitative", "status": status, "started": started,
             "duration_ms": int((time.perf_counter() - t0) * 1000), "summary": summary,
             "degraded": list(degraded)}
    return {"quantitative_result": result, "agent_trace": [trace], "degraded": list(degraded)}
