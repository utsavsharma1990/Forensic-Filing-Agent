"""Forensic financial metrics: Beneish M-Score, Altman Z / Z' / Z'', and supporting ratios.

Pure functions over *flattened year dicts* (``{canonical_item: float | None}``, see CONTRACTS.md
section 2).  No I/O, no network, no global state.  Every public function

* returns a ``dict`` with at least ``status`` (``"ok"`` | ``"unavailable"`` | ``"not_meaningful"``),
  ``missing`` (canonical item names that were needed but absent) and ``explanation`` (plain text);
* never raises (any internal failure becomes ``status="unavailable"``);
* never emits NaN or +/-inf (non-finite values are replaced by ``None``);
* never invents numbers.  The only imputation is the documented neutral value 1.0 for the Beneish
  SGAI and DEPI indices, and every imputation is listed under ``imputed``.

Inputs may also be FactValue dicts (``{"value": 1.0, ...}``); the ``value`` is used.

Published formulas and sources
------------------------------
Beneish (1999), "The Detection of Earnings Manipulation", Financial Analysts Journal 55(5), 24-36
(eight-variable probit model; coefficients and definitions cross-checked against several secondary
sources, e.g. https://en.wikipedia.org/wiki/Beneish_M-score):

    DSRI = (Receivables_t / Sales_t) / (Receivables_t-1 / Sales_t-1)
    GMI  = [(Sales_t-1 - COGS_t-1) / Sales_t-1] / [(Sales_t - COGS_t) / Sales_t]
    AQI  = [1 - (CurrentAssets_t + PPE_t + Securities_t) / TA_t] / [same for t-1]
    SGI  = Sales_t / Sales_t-1
    DEPI = [Dep_t-1 / (PPE_t-1 + Dep_t-1)] / [Dep_t / (PPE_t + Dep_t)]
    SGAI = (SGA_t / Sales_t) / (SGA_t-1 / Sales_t-1)
    LVGI = [(CurrentLiabilities_t + TotalLongTermDebt_t) / TA_t] / [same for t-1]
    TATA = (Income from continuing operations_t - Cash flow from operations_t) / TA_t
    M    = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI
           - 0.172*SGAI + 4.679*TATA - 0.327*LVGI

* TATA sign (decision D2 in CONTRACTS.md): total accruals are NET INCOME MINUS OPERATING CASH FLOW,
  scaled by total assets.  The SPEC text writes (OCF - NI)/TA, which would invert the signal given
  the positive 4.679 coefficient (higher accruals must RAISE M).  This module uses (NI - OCF)/TA.
* AQI: Beneish includes "securities" in the numerator.  The canonical vocabulary has no securities
  item, so AQI uses (CurrentAssets + PPE)/TotalAssets exactly as the SPEC states; securities held
  outside current assets are therefore counted as "non-current other assets".
* LVGI: uses (LongTermDebt + CurrentLiabilities)/TotalAssets as in the SPEC.
* Cut-offs: the SPEC/CONTRACTS use M > -1.78 manipulator (the 8-variable-model cut-off usually
  quoted for Beneish 1999), -2.22 < M <= -1.78 grey, M < -2.22 unlikely.  -2.22 is a widely quoted
  lower cut-off for the Beneish model (secondary sources attribute it to the original paper; the
  primary table could not be retrieved, so the grey-zone lower bound is a SPEC parameter, not a
  re-derived value).  Exactly -1.78 is grey; exactly -2.22 is grey.
* Sample means sanity vector (Beneish 1999 Table, as reproduced by a secondary source,
  Siregar et al. 2023, J. Systems & Management Sciences 13(6), https://www.aasmr.org/jsms/Vol13/No.6/Vol.13%20No.6.36.pdf):
  see ``BENEISH_SAMPLE_MEANS``.

Altman Z-score family (Altman 1968, "Financial Ratios, Discriminant Analysis and the Prediction of
Corporate Bankruptcy", Journal of Finance 23(4); Z' and Z'' from Altman 1983/1993/Altman & Hotchkiss,
as tabulated e.g. at https://www.truedata.in/blog/altman-z-score-formula-calculation-meaning):

    X1 = WorkingCapital/TA, X2 = RetainedEarnings/TA, X3 = EBIT/TA, X5 = Sales/TA
    Z   = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 (MarketCap/TL)    + 1.0   X5   zones <1.81 / 1.81-2.99 / >2.99
    Z'  = 0.717 X1 + 0.847 X2 + 3.107 X3 + 0.420 (BookEquity/TL) + 0.998 X5   zones <1.23 / 1.23-2.90 / >2.90
    Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 (BookEquity/TL)                 zones <1.10 / 1.10-2.60 / >2.60

Altman's 1968 paper prints the sales coefficient as 0.999 (with ratios in percent for X1-X4); the
widely used rounded form 1.2/1.4/3.3/0.6/1.0 (which the SPEC prescribes) is used for Z.  Z'' is
used here without the +3.25 emerging-market constant, so the 1.10/2.60 zones apply.  CONTRACTS D3:
``altman_z`` uses the original Z when a positive ``market_cap`` is supplied, otherwise the Z' book
equity variant; each result carries ``variant`` and variants must not be mixed in one analysis.

Other metrics (formulas in each docstring): revenue quality OCF/NI, DSO, accruals ratio, gross margin,
OCF/revenue, debt/equity, ROA, receivables-vs-revenue growth.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "CANONICAL_TO_XBRL_HINT", "BENEISH_COEFFS", "BENEISH_INTERCEPT", "BENEISH_SAMPLE_MEANS",
    "BENEISH_HIGH_CUTOFF", "BENEISH_LOW_CUTOFF", "classify_beneish", "classify_altman",
    "beneish_m_from_components", "beneish_m_score", "beneish_explanation_facts",
    "altman_z", "altman_z_double_prime", "revenue_quality", "dso", "accruals_ratio",
    "gross_margin", "ocf_to_revenue", "debt_to_equity", "roa", "receivables_vs_revenue_growth",
]

# --------------------------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------------------------

CANONICAL_TO_XBRL_HINT: dict[str, list[str]] = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "COGS": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    "GrossProfit": ["GrossProfit"],
    "SGA": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
    "NetIncome": ["NetIncomeLoss", "ProfitLoss", "IncomeLossFromContinuingOperations"],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "InterestExpense": ["InterestExpense", "InterestExpenseNonoperating"],
    "IncomeTaxExpense": ["IncomeTaxExpenseBenefit"],
    "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities",
                          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "Depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "Depreciation"],
    "TotalAssets": ["Assets"],
    "CurrentAssets": ["AssetsCurrent"],
    "CurrentLiabilities": ["LiabilitiesCurrent"],
    "TotalLiabilities": ["Liabilities"],
    "NetReceivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "AccountsReceivableNet"],
    "PPE": ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "LongTermDebt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermNotesPayable"],
    "CurrentDebt": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"],
    "RetainedEarnings": ["RetainedEarningsAccumulatedDeficit"],
    "StockholdersEquity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "CashAndEquivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "SharesOutstanding": ["EntityCommonStockSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
}
"""Canonical item -> XBRL concept names to cite when explaining a missing input (hints, not a tag list)."""

BENEISH_INTERCEPT = -4.84
BENEISH_COEFFS: dict[str, float] = {
    "DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892,
    "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327,
}
BENEISH_HIGH_CUTOFF = -1.78
BENEISH_LOW_CUTOFF = -2.22

BENEISH_SAMPLE_MEANS: dict[str, dict[str, float]] = {
    "manipulators": {"DSRI": 1.465, "GMI": 1.193, "AQI": 1.254, "SGI": 1.607,
                     "DEPI": 1.077, "SGAI": 1.041, "TATA": 0.031, "LVGI": 1.111},
    "non_manipulators": {"DSRI": 1.031, "GMI": 1.014, "AQI": 1.039, "SGI": 1.134,
                         "DEPI": 1.001, "SGAI": 1.054, "TATA": 0.018, "LVGI": 1.037},
}
"""Beneish (1999) sample means (secondary-source reproduction).  Non-manipulator SGAI is the least
certain entry (one secondary source garbles it); its effect on M is only 0.172 * delta."""

_ALTMAN_Z = {"X1": 1.2, "X2": 1.4, "X3": 3.3, "X4": 0.6, "X5": 1.0}
_ALTMAN_ZP = {"X1": 0.717, "X2": 0.847, "X3": 3.107, "X4": 0.420, "X5": 0.998}
_ALTMAN_ZPP = {"X1": 6.56, "X2": 3.26, "X3": 6.72, "X4": 1.05}
_ALTMAN_CUTS = {"Z": (1.81, 2.99), "Z-prime": (1.23, 2.90), "Z-double-prime": (1.10, 2.60)}

_DSO_FLAG_PCT = 20.0
_RQ_LOW = 0.8
_ACCRUALS_FLAG = 0.05

# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


def _num(x: Any) -> Optional[float]:
    """Coerce to a finite float, else ``None`` (handles None, bool, str, NaN, inf, FactValue dicts)."""
    if isinstance(x, Mapping):
        x = x.get("value")
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _flat(d: Any) -> dict[str, Optional[float]]:
    """Normalise a year dict to ``{name: finite float | None}``."""
    if not isinstance(d, Mapping):
        return {}
    return {str(k): _num(v) for k, v in d.items()}


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """a / b, or None when either is missing, b == 0, or the quotient is not finite."""
    if a is None or b is None or b == 0:
        return None
    try:
        q = a / b
    except (ZeroDivisionError, OverflowError):
        return None
    return q if math.isfinite(q) else None


def _fin(x: Optional[float]) -> Optional[float]:
    return x if (x is not None and math.isfinite(x)) else None


def _sanitize(obj: Any) -> Any:
    """Recursively replace non-finite floats by None so results are strict-JSON safe."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _hint_text(missing: list[str]) -> str:
    parts = []
    for m in missing:
        hints = CANONICAL_TO_XBRL_HINT.get(m)
        parts.append(f"{m} (XBRL: {', '.join(hints[:3])})" if hints else m)
    return "; ".join(parts)


def _result(status: str, missing: Optional[list[str]] = None, explanation: str = "", **extra: Any) -> dict:
    miss = sorted(set(missing or []))
    out: dict[str, Any] = {"status": status, "missing": miss, "explanation": explanation}
    out["missing_xbrl_hints"] = {m: CANONICAL_TO_XBRL_HINT[m] for m in miss if m in CANONICAL_TO_XBRL_HINT}
    out.update(extra)
    return _sanitize(out)


def _unavailable(name: str, missing: list[str], extra_reason: str = "", **extra: Any) -> dict:
    why = f"{name} unavailable"
    if missing:
        why += f": required input(s) not found: {_hint_text(sorted(set(missing)))}"
    if extra_reason:
        why += f"{'; ' if missing else ': '}{extra_reason}"
    return _result("unavailable", missing, why + ".", **extra)


def _guard(name: str) -> Callable:
    """Decorator: a public function must never raise or leak NaN/inf."""
    def deco(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> dict:
            try:
                return _sanitize(fn(*args, **kwargs))
            except Exception as exc:  # defensive: pure maths on arbitrary dicts
                return _result("unavailable", [], f"{name} unavailable: internal error ({type(exc).__name__}).")
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco


def _cogs(d: Mapping[str, Optional[float]]) -> Optional[float]:
    """COGS, else Revenue - GrossProfit (identity), else None."""
    c = d.get("COGS")
    if c is not None:
        return c
    r, gp = d.get("Revenue"), d.get("GrossProfit")
    return r - gp if (r is not None and gp is not None) else None


def _total_liabilities(d: Mapping[str, Optional[float]]) -> tuple[Optional[float], bool]:
    """(TotalLiabilities, derived?) - falls back to TotalAssets - StockholdersEquity (accounting identity)."""
    tl = d.get("TotalLiabilities")
    if tl is not None:
        return tl, False
    ta, eq = d.get("TotalAssets"), d.get("StockholdersEquity")
    if ta is not None and eq is not None:
        return ta - eq, True
    return None, False


def _ebit(d: Mapping[str, Optional[float]]) -> tuple[Optional[float], str]:
    """(EBIT, source): OperatingIncome, else NetIncome + IncomeTaxExpense + InterestExpense."""
    oi = d.get("OperatingIncome")
    if oi is not None:
        return oi, "OperatingIncome"
    ni, tx, ie = d.get("NetIncome"), d.get("IncomeTaxExpense"), d.get("InterestExpense")
    if ni is not None and tx is not None and ie is not None:
        return ni + tx + ie, "NetIncome+IncomeTaxExpense+InterestExpense"
    return None, ""


# --------------------------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------------------------


def classify_beneish(m: float) -> dict[str, Any]:
    """Zone for a Beneish M: ``M > -1.78`` manipulator/HIGH; ``M < -2.22`` unlikely/LOW; else grey/MEDIUM.

    The boundaries themselves (-1.78 and -2.22) are grey.  Returns ``{"zone","flag_level","flag"}``.
    """
    if m > BENEISH_HIGH_CUTOFF:
        return {"zone": "manipulator", "flag_level": "HIGH", "flag": True}
    if m < BENEISH_LOW_CUTOFF:
        return {"zone": "unlikely", "flag_level": "LOW", "flag": False}
    return {"zone": "grey", "flag_level": "MEDIUM", "flag": False}


def classify_altman(score: float, variant: str = "Z") -> str:
    """Zone ``"distress" | "grey" | "safe"``: strictly below the low cut-off is distress, strictly above the
    high cut-off is safe, the boundaries are grey.  ``variant`` is ``Z`` (1.81/2.99), ``Z-prime`` (1.23/2.90)
    or ``Z-double-prime`` (1.10/2.60)."""
    lo, hi = _ALTMAN_CUTS[variant]
    if score < lo:
        return "distress"
    if score > hi:
        return "safe"
    return "grey"


# --------------------------------------------------------------------------------------------
# Beneish
# --------------------------------------------------------------------------------------------


def beneish_m_from_components(components: Mapping[str, Any]) -> Optional[float]:
    """M = -4.84 + sum(coef * component) for the eight components; ``None`` if any is missing/non-finite."""
    total = BENEISH_INTERCEPT
    for k, c in BENEISH_COEFFS.items():
        v = _num(components.get(k))
        if v is None:
            return None
        total += c * v
    return _fin(total)


def _beneish_components(c: dict, p: dict) -> tuple[dict, dict, dict, dict]:
    """Return (components, missing_detail{cur,prev}, undefined{component: reason}, used_inputs)."""
    comps: dict[str, Optional[float]] = {k: None for k in BENEISH_COEFFS}
    md: dict[str, set] = {"cur": set(), "prev": set()}
    undefined: dict[str, str] = {}

    def need(keys: list[str], which: str, getter: Optional[Callable] = None) -> bool:
        d = c if which == "cur" else p
        ok = True
        for k in keys:
            val = getter(d) if (getter and k == "COGS") else d.get(k)
            if val is None:
                md[which].add(k)
                ok = False
        return ok

    def have(keys: list[str]) -> bool:
        a = need(keys, "cur", _cogs)
        b = need(keys, "prev", _cogs)
        return a and b

    # DSRI
    if have(["NetReceivables", "Revenue"]):
        v = _div(_div(c["NetReceivables"], c["Revenue"]), _div(p["NetReceivables"], p["Revenue"]))
        comps["DSRI"] = v
        if v is None:
            undefined["DSRI"] = "zero revenue or zero prior-year receivables"
    # GMI
    if have(["Revenue", "COGS"]):
        gm_c = _div(c["Revenue"] - _cogs(c), c["Revenue"])
        gm_p = _div(p["Revenue"] - _cogs(p), p["Revenue"])
        v = _div(gm_p, gm_c)
        comps["GMI"] = v
        if v is None:
            undefined["GMI"] = "zero revenue or zero current-year gross margin"
    # AQI
    if have(["CurrentAssets", "PPE", "TotalAssets"]):
        aq_c = _div(c["CurrentAssets"] + c["PPE"], c["TotalAssets"])
        aq_p = _div(p["CurrentAssets"] + p["PPE"], p["TotalAssets"])
        v = _div(None if aq_c is None else 1 - aq_c, None if aq_p is None else 1 - aq_p)
        comps["AQI"] = v
        if v is None:
            undefined["AQI"] = "zero total assets or prior-year (CurrentAssets+PPE)/TotalAssets equal to 1"
    # SGI
    if have(["Revenue"]):
        v = _div(c["Revenue"], p["Revenue"])
        comps["SGI"] = v
        if v is None:
            undefined["SGI"] = "zero prior-year revenue"
    # DEPI
    if have(["Depreciation", "PPE"]):
        if c["Depreciation"] < 0 or p["Depreciation"] < 0:
            undefined["DEPI"] = "negative depreciation value (sign convention not reliable)"
        else:
            r_p = _div(p["Depreciation"], p["PPE"] + p["Depreciation"])
            r_c = _div(c["Depreciation"], c["PPE"] + c["Depreciation"])
            v = _div(r_p, r_c)
            comps["DEPI"] = v
            if v is None:
                undefined["DEPI"] = "zero current-year depreciation rate or zero PPE+depreciation"
    # SGAI
    if have(["SGA", "Revenue"]):
        v = _div(_div(c["SGA"], c["Revenue"]), _div(p["SGA"], p["Revenue"]))
        comps["SGAI"] = v
        if v is None:
            undefined["SGAI"] = "zero revenue or zero prior-year SG&A"
    # LVGI
    if have(["LongTermDebt", "CurrentLiabilities", "TotalAssets"]):
        lv_c = _div(c["LongTermDebt"] + c["CurrentLiabilities"], c["TotalAssets"])
        lv_p = _div(p["LongTermDebt"] + p["CurrentLiabilities"], p["TotalAssets"])
        v = _div(lv_c, lv_p)
        comps["LVGI"] = v
        if v is None:
            undefined["LVGI"] = "zero total assets or zero prior-year leverage"
    # TATA = (NI - OCF) / TA  (CONTRACTS D2)
    if need(["NetIncome", "OperatingCashFlow", "TotalAssets"], "cur"):
        v = _div(c["NetIncome"] - c["OperatingCashFlow"], c["TotalAssets"])
        comps["TATA"] = v
        if v is None:
            undefined["TATA"] = "zero total assets"

    used_keys = ["Revenue", "COGS", "GrossProfit", "SGA", "NetReceivables", "CurrentAssets", "PPE", "TotalAssets",
                 "Depreciation", "LongTermDebt", "CurrentLiabilities", "NetIncome", "OperatingCashFlow"]
    used = {"cur": {k: c.get(k) for k in used_keys}, "prev": {k: p.get(k) for k in used_keys}}
    return comps, {k: sorted(v) for k, v in md.items()}, undefined, used


@_guard("Beneish M-Score")
def beneish_m_score(cur: Mapping[str, Any], prev: Mapping[str, Any],
                    impute_neutral: tuple[str, ...] = ("SGAI", "DEPI")) -> dict:
    """Beneish (1999) eight-variable M-Score for fiscal year ``cur`` against prior year ``prev``.

    ``M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA
    - 0.327 LVGI`` with ``TATA = (NetIncome - OperatingCashFlow) / TotalAssets`` (CONTRACTS D2).

    Only the indices named in ``impute_neutral`` AND restricted to SGAI/DEPI may be imputed (neutral 1.0, i.e.
    "no change"); each imputation is listed in ``imputed`` with the reason in ``imputed_reasons``.  Any other
    gap (or a zero denominator) makes the status ``"unavailable"`` and ``m_score`` ``None``.

    Returns ``{status, m_score, components, imputed, imputed_reasons, zone, flag_level, flag, missing,
    missing_detail{cur,prev}, undefined, inputs{cur,prev}, explanation}`` where ``zone`` is
    ``manipulator|grey|unlikely`` (``None`` when unavailable) and ``flag`` is ``M > -1.78``.
    """
    c, p = _flat(cur), _flat(prev)
    comps, md, undefined, used = _beneish_components(c, p)
    allowed = {k for k in impute_neutral if k in ("SGAI", "DEPI")}
    imputed: list[str] = []
    reasons: dict[str, str] = {}
    blocked: list[str] = []
    for k in BENEISH_COEFFS:
        if comps[k] is not None:
            continue
        if k in allowed:
            comps[k] = 1.0
            imputed.append(k)
        else:
            blocked.append(k)
    # missing items attributable only to indices that remained blocked or were imputed (imputed ones still
    # reported so callers can show what was absent)
    needed_by = {"DSRI": {"NetReceivables", "Revenue"}, "GMI": {"Revenue", "COGS"},
                 "AQI": {"CurrentAssets", "PPE", "TotalAssets"}, "SGI": {"Revenue"},
                 "DEPI": {"Depreciation", "PPE"}, "SGAI": {"SGA", "Revenue"},
                 "LVGI": {"LongTermDebt", "CurrentLiabilities", "TotalAssets"},
                 "TATA": {"NetIncome", "OperatingCashFlow", "TotalAssets"}}
    allmiss = set(md["cur"]) | set(md["prev"])
    # fix imputed reasons now that needed_by is known (precise per-index wording)
    for k in imputed:
        gone = sorted(n for n in needed_by[k] if n in allmiss)
        reasons[k] = (f"missing {', '.join(gone)}" if gone else undefined.get(k, "undefined ratio"))
    missing = sorted(allmiss)
    base = dict(components=comps, imputed=imputed, imputed_reasons=reasons, missing_detail=md,
                undefined=undefined, inputs=used)
    if blocked:
        reason_bits = []
        for k in blocked:
            gone = sorted(n for n in needed_by[k] if n in allmiss)
            reason_bits.append(f"{k}: " + (f"missing {', '.join(gone)}" if gone else undefined.get(k, "undefined")))
        return _unavailable("Beneish M-Score", [m for m in missing],
                            "cannot compute " + "; ".join(reason_bits),
                            m_score=None, zone=None, flag_level=None, flag=False, **base)
    m = beneish_m_from_components(comps)
    if m is None:
        return _unavailable("Beneish M-Score", missing, "non-finite result", m_score=None, zone=None,
                            flag_level=None, flag=False, **base)
    cls = classify_beneish(m)
    text = f"Beneish M-Score {m:.2f} ({cls['zone']} zone, {cls['flag_level']})."
    if imputed:
        text += " Neutral value 1.0 imputed for " + ", ".join(f"{k} ({reasons[k]})" for k in imputed) + "."
    return _result("ok", missing, text, m_score=m, zone=cls["zone"], flag_level=cls["flag_level"],
                   flag=cls["flag"], **base)


def beneish_explanation_facts(components: Mapping[str, Any], cur: Mapping[str, Any],
                              prev: Mapping[str, Any]) -> dict:
    """Raw numeric facts a deterministic explanation template can quote (all computed here, never by an LLM).

    Keys (``None`` when not computable): ``revenue_growth_pct``, ``receivables_growth_pct``,
    ``gross_margin_cur``, ``gross_margin_prev``, ``gross_margin_change_pp`` (percentage points),
    ``sga_pct_revenue_change_pp``, ``accrual_amount`` (NI - OCF), ``accrual_to_assets`` (TATA),
    ``accrual_pct_of_net_income``, ``asset_quality_cur/prev``, ``leverage_cur/prev``, ``components`` (the eight
    values), and ``contributions`` = coefficient * (value - 1) for the seven indices and coefficient * TATA,
    sorted by descending contribution (descriptive: how far each term pushes M above its "no change" level),
    plus ``top_drivers`` (names of up to three positive contributors).
    """
    c, p = _flat(cur), _flat(prev)
    comps = {k: _num(components.get(k)) for k in BENEISH_COEFFS} if isinstance(components, Mapping) else {}
    rev_g = _div(c.get("Revenue"), p.get("Revenue"))
    ar_g = _div(c.get("NetReceivables"), p.get("NetReceivables"))
    gm_c = _div(None if _cogs(c) is None or c.get("Revenue") is None else c["Revenue"] - _cogs(c), c.get("Revenue"))
    gm_p = _div(None if _cogs(p) is None or p.get("Revenue") is None else p["Revenue"] - _cogs(p), p.get("Revenue"))
    sga_c, sga_p = _div(c.get("SGA"), c.get("Revenue")), _div(p.get("SGA"), p.get("Revenue"))
    ni, ocf = c.get("NetIncome"), c.get("OperatingCashFlow")
    acc = ni - ocf if (ni is not None and ocf is not None) else None
    aq = lambda d: (lambda x: None if x is None else 1 - x)(  # noqa: E731
        _div(None if d.get("CurrentAssets") is None or d.get("PPE") is None else d["CurrentAssets"] + d["PPE"],
             d.get("TotalAssets")))
    lv = lambda d: _div(None if d.get("LongTermDebt") is None or d.get("CurrentLiabilities") is None  # noqa: E731
                        else d["LongTermDebt"] + d["CurrentLiabilities"], d.get("TotalAssets"))
    contrib: dict[str, float] = {}
    for k, coef in BENEISH_COEFFS.items():
        v = comps.get(k)
        if v is not None:
            contrib[k] = coef * (v if k == "TATA" else v - 1.0)
    ordered = dict(sorted(contrib.items(), key=lambda kv: kv[1], reverse=True))
    facts = {
        "revenue_growth_pct": None if rev_g is None else (rev_g - 1) * 100,
        "receivables_growth_pct": None if ar_g is None else (ar_g - 1) * 100,
        "gross_margin_cur": gm_c, "gross_margin_prev": gm_p,
        "gross_margin_change_pp": None if gm_c is None or gm_p is None else (gm_c - gm_p) * 100,
        "sga_pct_revenue_change_pp": None if sga_c is None or sga_p is None else (sga_c - sga_p) * 100,
        "accrual_amount": acc,
        "accrual_to_assets": _div(acc, c.get("TotalAssets")),
        "accrual_pct_of_net_income": None if _div(acc, None if ni is None else abs(ni)) is None
        else _div(acc, abs(ni)) * 100,
        "asset_quality_cur": aq(c), "asset_quality_prev": aq(p),
        "leverage_cur": lv(c), "leverage_prev": lv(p),
        "components": comps, "contributions": ordered,
        "top_drivers": [k for k, v in ordered.items() if v > 0][:3],
    }
    return _sanitize(facts)


# --------------------------------------------------------------------------------------------
# Altman
# --------------------------------------------------------------------------------------------


def _altman_inputs(d: dict) -> tuple[dict, list[str], list[str], str]:
    """Shared X1, X2, X3, X5 inputs; returns (values, missing, derived_notes, ebit_source)."""
    miss: list[str] = []
    notes: list[str] = []
    ta = d.get("TotalAssets")
    ca, cl = d.get("CurrentAssets"), d.get("CurrentLiabilities")
    re_ = d.get("RetainedEarnings")
    ebit, esrc = _ebit(d)
    rev = d.get("Revenue")
    for name, v in (("TotalAssets", ta), ("CurrentAssets", ca), ("CurrentLiabilities", cl),
                    ("RetainedEarnings", re_), ("Revenue", rev)):
        if v is None:
            miss.append(name)
    if ebit is None:
        miss.append("OperatingIncome")
    elif esrc != "OperatingIncome":
        notes.append(f"EBIT derived as {esrc}")
    return {"ta": ta, "ca": ca, "cl": cl, "re": re_, "ebit": ebit, "rev": rev}, miss, notes, esrc


@_guard("Altman Z-score")
def altman_z(cur: Mapping[str, Any], market_cap: Optional[float] = None) -> dict:
    """Altman Z-score for one fiscal year (CONTRACTS D3).

    With a positive finite ``market_cap``: original (1968) ``Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5``,
    ``X4 = MarketCap / TotalLiabilities``, zones ``<1.81`` distress, ``1.81-2.99`` grey, ``>2.99`` safe.
    Otherwise the book-equity variant ``Z' = 0.717 X1 + 0.847 X2 + 3.107 X3 + 0.420 X4 + 0.998 X5`` with
    ``X4 = StockholdersEquity / TotalLiabilities``, zones ``<1.23`` / ``1.23-2.90`` / ``>2.90``.
    ``X1 = (CurrentAssets - CurrentLiabilities)/TA``, ``X2 = RetainedEarnings/TA``, ``X3 = EBIT/TA``
    (EBIT = OperatingIncome, else NetIncome + IncomeTaxExpense + InterestExpense), ``X5 = Revenue/TA``.
    TotalLiabilities falls back to TotalAssets - StockholdersEquity (noted in ``derived``).

    Returns ``{status, score, zone (distress|grey|safe), variant ("Z"|"Z-prime"), components{X1..X5},
    derived, missing, explanation}``.  Never mix variants within one analysis: pass the same
    ``market_cap`` policy for every year.
    """
    d = _flat(cur)
    mc = _num(market_cap)
    use_z = mc is not None and mc > 0
    variant = "Z" if use_z else "Z-prime"
    vals, miss, notes, _ = _altman_inputs(d)
    tl, tl_derived = _total_liabilities(d)
    if tl is None:
        miss.append("TotalLiabilities")
    elif tl_derived:
        notes.append("TotalLiabilities derived as TotalAssets - StockholdersEquity")
    eq = d.get("StockholdersEquity")
    if not use_z and eq is None:
        miss.append("StockholdersEquity")
    if miss:
        return _unavailable("Altman Z-score", miss, variant=variant, score=None, zone=None,
                            components={}, derived=notes)
    ta = vals["ta"]
    if ta == 0 or tl == 0:
        why = "zero " + ("TotalAssets" if ta == 0 else "TotalLiabilities")
        return _unavailable("Altman Z-score", [], why, variant=variant, score=None, zone=None,
                            components={}, derived=notes)
    x1 = (vals["ca"] - vals["cl"]) / ta
    x2 = vals["re"] / ta
    x3 = vals["ebit"] / ta
    x4 = (mc if use_z else eq) / tl
    x5 = vals["rev"] / ta
    co = _ALTMAN_Z if use_z else _ALTMAN_ZP
    score = _fin(co["X1"] * x1 + co["X2"] * x2 + co["X3"] * x3 + co["X4"] * x4 + co["X5"] * x5)
    comps = {"X1": x1, "X2": x2, "X3": x3, "X4": x4, "X5": x5}
    if score is None or any(not math.isfinite(v) for v in comps.values()):
        return _unavailable("Altman Z-score", [], "non-finite result", variant=variant, score=None, zone=None,
                            components={}, derived=notes)
    zone = classify_altman(score, variant)
    lo, hi = _ALTMAN_CUTS[variant]
    text = (f"Altman {variant} = {score:.2f} ({zone}; cut-offs {lo}/{hi})."
            + ("" if use_z else " Market cap not supplied: book-equity Z' variant used (not comparable with Z).")
            + (" " + "; ".join(notes) + "." if notes else ""))
    return _result("ok", [], text, score=score, zone=zone, variant=variant, components=comps, derived=notes)


@_guard("Altman Z''-score")
def altman_z_double_prime(cur: Mapping[str, Any]) -> dict:
    """Altman Z'' (non-manufacturer / emerging-market form, no sales term, no +3.25 constant).

    ``Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4`` with ``X4 = BookEquity/TotalLiabilities``; zones
    ``<1.10`` distress, ``1.10-2.60`` grey, ``>2.60`` safe.  Same inputs/derivations as :func:`altman_z`
    minus Revenue.  Returns the same shape with ``variant="Z-double-prime"``.
    """
    d = _flat(cur)
    vals, miss, notes, _ = _altman_inputs(d)
    miss = [m for m in miss if m != "Revenue"]
    tl, tl_derived = _total_liabilities(d)
    if tl is None:
        miss.append("TotalLiabilities")
    elif tl_derived:
        notes.append("TotalLiabilities derived as TotalAssets - StockholdersEquity")
    eq = d.get("StockholdersEquity")
    if eq is None:
        miss.append("StockholdersEquity")
    if miss:
        return _unavailable("Altman Z''-score", miss, variant="Z-double-prime", score=None, zone=None,
                            components={}, derived=notes)
    ta = vals["ta"]
    if ta == 0 or tl == 0:
        return _unavailable("Altman Z''-score", [], "zero " + ("TotalAssets" if ta == 0 else "TotalLiabilities"),
                            variant="Z-double-prime", score=None, zone=None, components={}, derived=notes)
    x1, x2, x3, x4 = (vals["ca"] - vals["cl"]) / ta, vals["re"] / ta, vals["ebit"] / ta, eq / tl
    c = _ALTMAN_ZPP
    score = _fin(c["X1"] * x1 + c["X2"] * x2 + c["X3"] * x3 + c["X4"] * x4)
    if score is None:
        return _unavailable("Altman Z''-score", [], "non-finite result", variant="Z-double-prime", score=None,
                            zone=None, components={}, derived=notes)
    zone = classify_altman(score, "Z-double-prime")
    return _result("ok", [], f"Altman Z'' = {score:.2f} ({zone}; cut-offs 1.10/2.60).", score=score, zone=zone,
                   variant="Z-double-prime", components={"X1": x1, "X2": x2, "X3": x3, "X4": x4}, derived=notes)


# --------------------------------------------------------------------------------------------
# earnings-quality ratios
# --------------------------------------------------------------------------------------------


def _ocf_ni(d: dict) -> tuple[Optional[float], list[str], str]:
    """OCF/NI for one year -> (ratio, missing, state) with state in ok|missing|not_meaningful."""
    miss = [k for k in ("OperatingCashFlow", "NetIncome") if d.get(k) is None]
    if miss:
        return None, miss, "missing"
    if d["NetIncome"] <= 0:
        return None, [], "not_meaningful"
    return _div(d["OperatingCashFlow"], d["NetIncome"]), [], "ok"


@_guard("Revenue quality")
def revenue_quality(cur: Mapping[str, Any], prev: Optional[Mapping[str, Any]] = None) -> dict:
    """Revenue (earnings) quality = ``OperatingCashFlow / NetIncome``; flag when ``< 0.8`` in two consecutive years.

    ``NetIncome <= 0`` in the current year gives ``status="not_meaningful"`` (no flag).  The flag needs both
    years: if the prior year is missing or has ``NetIncome <= 0`` the current ratio is still reported
    (``status="ok"``) but ``flag=False`` and ``flag_evaluable=False``.
    Returns ``{status, ratio, prior_ratio, low, prior_low, consecutive_low, flag, flag_evaluable, missing, explanation}``.
    """
    c = _flat(cur)
    ratio, miss, state = _ocf_ni(c)
    if state == "missing":
        return _unavailable("Revenue quality (OCF/NI)", miss, ratio=None, prior_ratio=None, low=None,
                            prior_low=None, consecutive_low=None, flag=False, flag_evaluable=False)
    if state == "not_meaningful":
        return _result("not_meaningful", [], "Revenue quality not meaningful: NetIncome <= 0 (OCF/NI undefined as a quality signal).",
                       ratio=None, prior_ratio=None, low=None, prior_low=None, consecutive_low=None, flag=False,
                       flag_evaluable=False)
    if ratio is None:
        return _unavailable("Revenue quality (OCF/NI)", [], "non-finite ratio", ratio=None, prior_ratio=None, low=None,
                            prior_low=None, consecutive_low=None, flag=False, flag_evaluable=False)
    low = ratio < _RQ_LOW
    pr, pmiss, pstate = _ocf_ni(_flat(prev)) if prev is not None else (None, [], "missing")
    evaluable = pstate == "ok" and pr is not None
    plow = (pr < _RQ_LOW) if evaluable else None
    consecutive = (low and plow) if evaluable else None
    flag = bool(consecutive)
    text = f"OCF/NI = {ratio:.2f}"
    if evaluable:
        text += f" (prior year {pr:.2f}); " + ("below 0.8 in two consecutive years: FLAG." if flag else "not below 0.8 in two consecutive years.")
    else:
        text += "; prior-year ratio unavailable so the two-year flag cannot be evaluated."
        if pmiss:
            text += f" Missing prior-year: {_hint_text(pmiss)}."
    return _result("ok", [], text, ratio=ratio, prior_ratio=pr, low=low, prior_low=plow,
                   consecutive_low=consecutive, flag=flag, flag_evaluable=evaluable,
                   prior_missing=sorted(pmiss))


def _dso_one(d: dict) -> tuple[Optional[float], list[str]]:
    miss = [k for k in ("NetReceivables", "Revenue") if d.get(k) is None]
    if miss:
        return None, miss
    if d["Revenue"] <= 0:
        return None, []
    r = _div(d["NetReceivables"], d["Revenue"])
    return (None if r is None else r * 365.0), []


@_guard("DSO")
def dso(cur: Mapping[str, Any], prev: Optional[Mapping[str, Any]] = None) -> dict:
    """Days sales outstanding ``= NetReceivables / Revenue * 365``; flag when DSO grew more than 20% YoY.

    ``yoy_change_pct = (DSO_t / DSO_t-1 - 1) * 100`` (``None`` without a usable prior year or when prior DSO
    is 0).  Returns ``{status, dso_days, prior_dso_days, yoy_change_pct, flag, missing, explanation}``.
    """
    c = _flat(cur)
    d, miss = _dso_one(c)
    if d is None:
        extra = "Revenue <= 0 (DSO undefined)" if not miss else ""
        return _unavailable("DSO", miss, extra, dso_days=None, prior_dso_days=None, yoy_change_pct=None, flag=False)
    pd, pmiss = (None, []) if prev is None else _dso_one(_flat(prev))
    yoy = None
    if pd is not None and pd > 0:
        yoy = (d / pd - 1.0) * 100.0
        yoy = _fin(yoy)
    flag = bool(yoy is not None and yoy > _DSO_FLAG_PCT)
    text = f"DSO {d:.1f} days"
    if yoy is not None:
        text += f", {yoy:+.1f}% vs prior year ({pd:.1f} days)" + ("; exceeds the +20% threshold: FLAG." if flag else ".")
    else:
        text += "; no usable prior-year DSO so the YoY flag cannot be evaluated."
    return _result("ok", [], text, dso_days=d, prior_dso_days=pd, yoy_change_pct=yoy, flag=flag,
                   prior_missing=sorted(pmiss))


@_guard("Accruals ratio")
def accruals_ratio(cur: Mapping[str, Any]) -> dict:
    """Accruals ratio ``= (NetIncome - OperatingCashFlow) / TotalAssets``; flag when ``> 0.05`` (SPEC; same
    definition as Beneish TATA).  Returns ``{status, ratio, accrual_amount, flag, missing, explanation}``."""
    c = _flat(cur)
    miss = [k for k in ("NetIncome", "OperatingCashFlow", "TotalAssets") if c.get(k) is None]
    if miss:
        return _unavailable("Accruals ratio", miss, ratio=None, accrual_amount=None, flag=False)
    acc = c["NetIncome"] - c["OperatingCashFlow"]
    r = _div(acc, c["TotalAssets"])
    if r is None:
        return _unavailable("Accruals ratio", [], "zero TotalAssets", ratio=None, accrual_amount=_fin(acc), flag=False)
    flag = r > _ACCRUALS_FLAG
    return _result("ok", [], f"Accruals ratio {r:.3f}" + ("; above 0.05: FLAG." if flag else "; at or below 0.05."),
                   ratio=r, accrual_amount=acc, flag=flag)


# --------------------------------------------------------------------------------------------
# peer-comparison ratios
# --------------------------------------------------------------------------------------------


@_guard("Gross margin")
def gross_margin(cur: Mapping[str, Any]) -> dict:
    """Gross margin ``= (Revenue - COGS) / Revenue`` (COGS may be derived as Revenue - GrossProfit)."""
    c = _flat(cur)
    miss = []
    if c.get("Revenue") is None:
        miss.append("Revenue")
    cogs = _cogs(c)
    if cogs is None:
        miss.append("COGS")
    if miss:
        return _unavailable("Gross margin", miss, value=None)
    if c["Revenue"] <= 0:
        return _unavailable("Gross margin", [], "Revenue <= 0", value=None)
    v = _div(c["Revenue"] - cogs, c["Revenue"])
    return _result("ok", [], f"Gross margin {v * 100:.1f}%.", value=v)


@_guard("OCF/Revenue")
def ocf_to_revenue(cur: Mapping[str, Any]) -> dict:
    """Operating cash flow margin ``= OperatingCashFlow / Revenue``."""
    c = _flat(cur)
    miss = [k for k in ("OperatingCashFlow", "Revenue") if c.get(k) is None]
    if miss:
        return _unavailable("OCF/Revenue", miss, value=None)
    if c["Revenue"] <= 0:
        return _unavailable("OCF/Revenue", [], "Revenue <= 0", value=None)
    v = _div(c["OperatingCashFlow"], c["Revenue"])
    return _result("ok", [], f"OCF/Revenue {v * 100:.1f}%.", value=v)


@_guard("Debt/Equity")
def debt_to_equity(cur: Mapping[str, Any]) -> dict:
    """Debt/equity ``= (LongTermDebt + CurrentDebt) / StockholdersEquity``.

    ``LongTermDebt`` and ``StockholdersEquity`` are required.  If ``CurrentDebt`` is absent the ratio uses
    long-term debt only and ``partial=True`` with ``CurrentDebt`` listed in ``missing`` (status stays ``ok``).
    ``StockholdersEquity <= 0`` -> ``not_meaningful``.
    """
    c = _flat(cur)
    miss = [k for k in ("LongTermDebt", "StockholdersEquity") if c.get(k) is None]
    if miss:
        return _unavailable("Debt/Equity", miss, value=None, partial=False)
    if c["StockholdersEquity"] <= 0:
        return _result("not_meaningful", [], "Debt/Equity not meaningful: StockholdersEquity <= 0.",
                       value=None, partial=False)
    partial = c.get("CurrentDebt") is None
    debt = c["LongTermDebt"] + (0.0 if partial else c["CurrentDebt"])
    v = _div(debt, c["StockholdersEquity"])
    text = f"Debt/Equity {v:.2f}." + (" CurrentDebt missing: long-term debt only." if partial else "")
    return _result("ok", ["CurrentDebt"] if partial else [], text, value=v, partial=partial)


@_guard("ROA")
def roa(cur: Mapping[str, Any]) -> dict:
    """Return on assets ``= NetIncome / TotalAssets`` (year-end assets)."""
    c = _flat(cur)
    miss = [k for k in ("NetIncome", "TotalAssets") if c.get(k) is None]
    if miss:
        return _unavailable("ROA", miss, value=None)
    if c["TotalAssets"] <= 0:
        return _unavailable("ROA", [], "TotalAssets <= 0", value=None)
    v = _div(c["NetIncome"], c["TotalAssets"])
    return _result("ok", [], f"ROA {v * 100:.1f}%.", value=v)


@_guard("Receivables vs revenue growth")
def receivables_vs_revenue_growth(cur: Mapping[str, Any], prev: Mapping[str, Any]) -> dict:
    """Revenue growth vs receivables growth.

    ``revenue_growth = Revenue_t/Revenue_t-1 - 1``; ``receivables_growth = AR_t/AR_t-1 - 1`` (fractions);
    ``difference = receivables_growth - revenue_growth`` (fraction, positive = receivables outpacing sales);
    ``ratio = (1 + receivables_growth) / (1 + revenue_growth)`` (equals DSRI).  Prior values must be > 0.
    """
    c, p = _flat(cur), _flat(prev)
    miss = [k for k in ("Revenue", "NetReceivables") if c.get(k) is None or p.get(k) is None]
    if miss:
        return _unavailable("Receivables vs revenue growth", miss, revenue_growth=None, receivables_growth=None,
                            difference=None, ratio=None)
    if p["Revenue"] <= 0 or p["NetReceivables"] <= 0 or c["Revenue"] <= 0:
        return _unavailable("Receivables vs revenue growth", [], "non-positive revenue or prior-year receivables",
                            revenue_growth=None, receivables_growth=None, difference=None, ratio=None)
    rg = c["Revenue"] / p["Revenue"] - 1.0
    ag = c["NetReceivables"] / p["NetReceivables"] - 1.0
    ratio = _div(1.0 + ag, 1.0 + rg)
    return _result("ok", [], f"Revenue grew {rg * 100:.1f}% while receivables grew {ag * 100:.1f}%.",
                   revenue_growth=rg, receivables_growth=ag, difference=ag - rg, ratio=ratio)
