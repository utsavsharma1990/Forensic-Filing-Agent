"""Agent 4: SIC-peer comparison (deterministic, no LLM).

For the focus year the company's six ratios are compared with the same ratios of the point-in-time SIC peers found by
:mod:`tools.peer_finder`: ``z = (company - mean(peers)) / std(peers, ddof=1)``; a metric is flagged when ``|z| > 2.0``
and at least 3 peers have the metric. Unavailable data is reported explicitly (never zero). Independent of agents 1-3.

v2 (docs/V2_CHANGELOG_agents.md B4/B5/B6)
-----------------------------------------
DIRECTION.  The z-test stays two-sided and every outlier is displayed, but only an outlier in the MANIPULATION-CONSISTENT
direction is a risk flag (counts toward severity, ``flags_by_year``, ``outlier_metrics`` and the synthesis/temporal
logic).  An outlier in the opposite direction is recorded as ``informational`` (``informational_outliers``, evidence items
with ``informational=True``).  The direction table :data:`ADVERSE_DIRECTION` is fixed a priori from the earnings-quality /
manipulation literature, not from any evaluation outcome:

* ``receivables_vs_revenue_growth`` ABOVE peers: receivables outgrowing sales is the Beneish (1999) DSRI pattern and the
  premature-revenue-recognition / channel-stuffing signature (Dechow, Sloan & Sweeney 1996; Dechow, Ge, Larson & Sloan
  2011 use abnormal changes in receivables as a misstatement predictor). Receivables falling faster than sales is not.
* ``dso`` ABOVE peers: the level counterpart of the same pattern (Beneish DSRI; DSO stretching). A LOW DSO is faster
  collection - not a manipulation indicator.
* ``ocf_to_revenue`` BELOW peers: earnings/revenue not converting to cash is the accrual-anomaly signature
  (Sloan 1996; Dechow & Dichev 2002 earnings quality; Beneish TATA). Cash conversion ABOVE peers is benign.
* ``gross_margin`` ABOVE peers and ``roa`` ABOVE peers: performance "too good to be true" relative to the industry
  (Dechow et al. 2011 find unusually high performance among misstating firms; Schilit's "Financial Shenanigans" and the
  Beneish GMI logic treat margins that diverge from industry economics as a warning). These two are the weakest
  directions (high margins are often real: brands, patents), which is why a single such outlier is only Low severity.
* ``debt_to_equity`` ABOVE peers: leverage is an incentive for manipulation (debt-covenant hypothesis; Beneish LVGI;
  Dechow et al. 1996 external-financing motive). Low leverage is not.

SEVERITY is the count of manipulation-consistent outliers (>= 3 High / 2 Medium / 1 Low), unchanged otherwise.

MATERIALITY (B6).  Ratios with revenue in the denominator (gross margin, DSO, receivables-minus-revenue growth,
OCF/revenue) are ``not_meaningful`` for a company (or peer) whose revenue is below 1% of total assets in the year
(:func:`agents.quantitative_agent.revenue_materiality`; receivables-vs-revenue growth also needs the prior year to pass).
ROA and debt/equity do not use revenue and are unaffected. A ``peer_pct`` beyond +/-1000% is a tiny-denominator artefact
and is reported as ``None`` ("n/m"), never narrated.
"""
from __future__ import annotations

import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from agents.quantitative_agent import revenue_materiality
from tools import common, edgar_api, financial_metrics as fm, xbrl_parser

log = common.get_logger("peer_agent")

Z_THRESHOLD = 2.0
MIN_PEERS = 3
HARD_OUTLIER_COUNT = 3
MIN_XBRL_YEAR = 2009

# metric -> (label, kind). kinds: pct (fraction shown as %), days, pp (fraction shown as percentage points), x (ratio)
METRICS: dict[str, tuple[str, str]] = {
    "gross_margin": ("Gross margin", "pct"),
    "dso": ("DSO", "days"),
    "receivables_vs_revenue_growth": ("Receivables growth minus revenue growth", "pp"),
    "ocf_to_revenue": ("OCF/revenue", "pct"),
    "debt_to_equity": ("Debt/equity", "x"),
    "roa": ("ROA", "pct"),
}

# v2 (B4): the direction in which a peer outlier is MANIPULATION-CONSISTENT (see module docstring for the rationale/citations).
ADVERSE_DIRECTION: dict[str, str] = {
    "gross_margin": "above",
    "dso": "above",
    "receivables_vs_revenue_growth": "above",
    "ocf_to_revenue": "below",
    "debt_to_equity": "above",
    "roa": "above",
}
REVENUE_DENOMINATED = ("gross_margin", "dso", "receivables_vs_revenue_growth", "ocf_to_revenue")  # B6
MAX_PEER_PCT = 1000.0  # beyond this a percent-vs-peer-mean is a tiny-denominator artefact (B6)


# ------------------------------------------------------------------ pure computation
def compute_metrics(cur: dict, prev: Optional[dict]) -> tuple[dict[str, Optional[float]], dict[str, str]]:
    """{metric: value|None}, {metric: reason} from flattened year dicts. Never raises."""
    vals: dict[str, Optional[float]] = {}
    why: dict[str, str] = {}
    prev = prev or {}

    def take(name: str, res: dict, key: str) -> None:
        v = res.get("value" if key == "value" else key) if isinstance(res, dict) else None
        if res.get("status") == "ok" and isinstance(v, (int, float)) and math.isfinite(v):
            vals[name] = float(v)
        else:
            vals[name] = None
            why[name] = (res.get("explanation") or res.get("status") or "unavailable")[:200]

    try:
        take("gross_margin", fm.gross_margin(cur), "value")
        take("dso", fm.dso(cur, prev), "dso_days")
        take("receivables_vs_revenue_growth", fm.receivables_vs_revenue_growth(cur, prev), "difference")
        take("ocf_to_revenue", fm.ocf_to_revenue(cur), "value")
        take("debt_to_equity", fm.debt_to_equity(cur), "value")
        take("roa", fm.roa(cur), "value")
    except Exception as exc:  # defensive: metrics are documented never to raise
        for m in METRICS:
            vals.setdefault(m, None)
            why.setdefault(m, f"computation error {type(exc).__name__}")
    # B6: revenue-denominated ratios are not meaningful when revenue is immaterial (current; prior too for the growth gap)
    mat_c, why_c = revenue_materiality(cur)
    mat_p, why_p = revenue_materiality(prev) if prev else (True, "")
    for m in REVENUE_DENOMINATED:
        bad = None
        if not mat_c:
            bad = why_c
        elif m == "receivables_vs_revenue_growth" and not mat_p:
            bad = "prior-year " + why_p
        if bad:
            vals[m] = None
            why[m] = "not_meaningful: " + bad
    return vals, why


def zscore(company: float, peers: list[float]) -> dict:
    """Sample (ddof=1) z-score. ``std == 0`` -> z is None (undefined) except company == mean -> 0.0."""
    n = len(peers)
    mean = statistics.fmean(peers)
    std = statistics.stdev(peers) if n >= 2 else None
    if std is None:
        return {"z_score": None, "peer_mean": mean, "peer_std": None, "n_peers": n}
    if std == 0 or std < 1e-12 * max(1.0, abs(mean)):
        z = 0.0 if abs(company - mean) <= 1e-12 * max(1.0, abs(mean)) else None
        return {"z_score": z, "peer_mean": mean, "peer_std": std, "n_peers": n, "zero_dispersion": True}
    return {"z_score": (company - mean) / std, "peer_mean": mean, "peer_std": std, "n_peers": n}


def _fmt(v: float, kind: str) -> str:
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "days":
        return f"{v:.0f} days"
    if kind == "pp":
        return f"{v * 100:+.1f} pp"
    return f"{v:.2f}x"


def interpret(metric: str, company: float, zinfo: dict) -> str:
    label, kind = METRICS[metric]
    mean, z = zinfo["peer_mean"], zinfo["z_score"]
    if z is None:
        return (f"{label} {_fmt(company, kind)} vs peer mean {_fmt(mean, kind)}: peers have zero dispersion "
                f"(std=0) so z is undefined; not flagged.")
    word = label if kind != "days" else "DSO"
    txt = f"{word} {_fmt(company, kind)} vs peer mean {_fmt(mean, kind)} (z={z:+.1f})"
    if abs(z) > Z_THRESHOLD:
        txt += f": {'above' if z > 0 else 'below'} peers by more than {Z_THRESHOLD:g} standard deviations"
    return txt


def _peer_pct(company: float, mean: float) -> Optional[float]:
    if mean == 0:
        return None
    pct = round((company - mean) / abs(mean) * 100.0, 1)
    return None if abs(pct) > MAX_PEER_PCT else pct  # B6: tiny-denominator artefact -> n/m


def compare(company_vals: dict, peer_vals: list[dict]) -> tuple[dict, dict]:
    """-> (metric_zscores, unavailable{metric: reason}) from company metric values and per-peer metric dicts."""
    out: dict[str, dict] = {}
    unavailable: dict[str, str] = {}
    for m, (label, kind) in METRICS.items():
        cv = company_vals.get(m)
        if cv is None:
            unavailable[m] = "company value unavailable"
            continue
        pv = [p[m] for p in peer_vals if p.get(m) is not None]
        if len(pv) < MIN_PEERS:
            unavailable[m] = f"only {len(pv)} peers with {label} (need >= {MIN_PEERS})"
            continue
        zi = zscore(cv, pv)
        flag = zi["z_score"] is not None and abs(zi["z_score"]) > Z_THRESHOLD
        direction = None if zi["z_score"] is None else ("above" if zi["z_score"] > 0 else "below")
        raw_pct = None if zi["peer_mean"] == 0 else round((cv - zi["peer_mean"]) / abs(zi["peer_mean"]) * 100.0, 1)
        risk = bool(flag and direction == ADVERSE_DIRECTION[m])
        out[m] = {"z_score": None if zi["z_score"] is None else round(zi["z_score"], 4), "company_value": cv,
                  "peer_mean": zi["peer_mean"], "peer_std": zi["peer_std"], "n_peers": zi["n_peers"], "flag": flag,
                  "risk_flag": risk, "informational": bool(flag and not risk),
                  "adverse_direction": ADVERSE_DIRECTION[m],
                  "peer_pct": _peer_pct(cv, zi["peer_mean"]),
                  "peer_pct_not_meaningful": bool(raw_pct is not None and abs(raw_pct) > MAX_PEER_PCT),
                  "direction": direction, "interpretation": interpret(m, cv, zi)}
    return out, unavailable


# ------------------------------------------------------------------ data access
def _flat(af: dict, year: int) -> Optional[dict]:
    by = (af.get("by_year") or {})
    block = by.get(year) if year in by else by.get(str(year))
    if not block:
        return None
    return common.flatten_year(block)


def _facts_for(cik: str, years: list[int], as_of: Optional[str]) -> dict:
    """XBRL path directly when companyfacts exist (identical to the facade, but never triggers a slow filing parse
    for a peer); otherwise the facade (statement-table path for pre-XBRL years)."""
    cf = edgar_api.get_companyfacts(cik)
    if cf and cf.get("facts"):
        return xbrl_parser.extract_annual_facts(cf, years, as_of=as_of)
    return xbrl_parser.get_annual_facts(cik, years, as_of=as_of)


def _unavailable(reason: str, focus_year: Optional[int], peers: list[dict], degraded: list[str],
                 unit: Optional[str] = None) -> dict:
    return {"unavailable": True, "reason": reason, "severity": "None", "flags_fired": 0, "flags_by_year": {},
            "focus_year": focus_year, "peer_list": [{"ticker": p.get("ticker"), "name": p.get("name"), "cik": p.get("cik")}
                                                    for p in peers],
            "metric_zscores": {}, "outlier_metrics": [], "informational_outliers": [], "evidence": [],
            "key_finding": f"peer comparison unavailable: {reason}",
            "data_quality": {"unavailable": {"peer_comparison": reason}, "unit": unit}, "degraded": degraded}


# ------------------------------------------------------------------ agent
def _analyse(state: dict, degraded: list[str]) -> dict:
    years = [int(y) for y in (state.get("analysis_years") or [])]
    focus = state.get("focus_year") or (max(years) if years else None)
    if not focus:
        return _unavailable("no focus year", None, [], degraded)
    focus = int(focus)
    as_of = state.get("as_of") or None
    cik = str(state.get("cik") or "")
    peers_in = [p for p in (state.get("peer_companies") or []) if p.get("cik") and edgar_api.pad_cik(p["cik"]) != (edgar_api.pad_cik(cik) if cik else "")]
    reason = getattr(state.get("peer_companies"), "reason", None)
    if focus < MIN_XBRL_YEAR:
        return _unavailable(f"pre-XBRL focus year {focus}: peer facts do not exist", focus, peers_in, degraded)
    if not peers_in:
        return _unavailable(reason or "no peer companies supplied (peer discovery found none: pre-XBRL, "
                            "non-USD, or no SIC peers within the size band)", focus, [], degraded)
    if len(peers_in) < MIN_PEERS:
        return _unavailable(f"only {len(peers_in)} peers supplied (need >= {MIN_PEERS})", focus, peers_in, degraded)

    # company side
    af = state.get("annual_facts")
    if not af or _flat(af, focus) is None:
        af = _facts_for(cik, [focus - 1, focus], as_of) if cik else {}
    cur, prev = _flat(af, focus) if af else None, (_flat(af, focus - 1) if af else None)
    unit = (af or {}).get("unit")
    if not cur:
        return _unavailable(f"no company annual facts for FY{focus} as of {as_of or 'now'}", focus, peers_in, degraded, unit)
    company_vals, company_why = compute_metrics(cur, prev)

    # peers (parallel; companyfacts are disk cached)
    def one(p: dict) -> tuple[dict, Optional[dict], Optional[str]]:
        py = int(p.get("fiscal_year") or focus)
        try:
            paf = _facts_for(p["cik"], [py - 1, py], as_of)
            pcur = _flat(paf, py)
            if not pcur:
                return p, None, f"no FY{py} facts"
            vals, _ = compute_metrics(pcur, _flat(paf, py - 1))
            return p, vals, None
        except Exception as exc:
            return p, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, peers_in))
    used, peer_vals = [], []
    for p, vals, err in results:
        if vals is None:
            degraded.append(f"peer_data: {p.get('ticker') or p.get('cik')} skipped ({err})")
        else:
            used.append(p)
            peer_vals.append(vals)
    if len(used) < MIN_PEERS:
        return _unavailable(f"only {len(used)} peers with usable FY data (need >= {MIN_PEERS})", focus, used, degraded, unit)

    zs, unavailable = compare(company_vals, peer_vals)
    for m, r in company_why.items():
        unavailable[m] = r
    all_outliers = [m for m, z in zs.items() if z["flag"]]
    outliers = [m for m in all_outliers if zs[m]["risk_flag"]]          # manipulation-consistent: count
    informational = [m for m in all_outliers if not zs[m]["risk_flag"]]  # recorded, never a risk flag
    flags = [f"peer.{m}" for m in outliers]
    sev = "High" if len(outliers) >= HARD_OUTLIER_COUNT else {2: "Medium", 1: "Low"}.get(len(outliers), "None")

    evidence = []
    for m in all_outliers:
        z = zs[m]
        item = {"flag": f"peer.{m}", "year": focus, "metric": m, "value": z["company_value"],
                "display": z["interpretation"],
                "numbers": [z["company_value"], z["peer_mean"], z["peer_std"], z["z_score"], z["n_peers"]],
                "peer_pct": z["peer_pct"],
                "unit_kind": {"days": "days", "pp": "pp_difference"}.get(METRICS[m][1], "ratio_level")}
        if not z["risk_flag"]:
            item["informational"] = True
        evidence.append(item)
    nm = sorted(m for m, r in unavailable.items() if str(r).startswith("not_meaningful"))
    if outliers:
        kf = f"FY{focus} peer outliers vs {len(used)} SIC peers: " + "; ".join(zs[m]["interpretation"].split(":")[0] for m in outliers)
        if informational:
            kf += f" (plus {len(informational)} outlier(s) in the non-manipulation direction, recorded as informational)"
    elif informational:
        kf = (f"No manipulation-consistent peer outliers in FY{focus}; {len(informational)} outlier(s) in the opposite "
              f"direction recorded as informational: " + "; ".join(zs[m]["interpretation"].split(":")[0] for m in informational))
    elif zs:
        kf = f"No peer outliers in FY{focus}: all {len(zs)} comparable metrics within {Z_THRESHOLD:g} standard deviations of {len(used)} SIC peers"
    else:
        kf = f"No metric had enough peer data in FY{focus}"
    offsets = sorted({int(p.get("year_offset") or 0) for p in used})
    dq: dict[str, Any] = {"unavailable": unavailable, "n_peers": len(used), "unit": unit,
                          "peer_year_offsets": offsets, "min_peers": MIN_PEERS, "not_meaningful": nm}
    if any(offsets):
        dq["note"] = ("some peers' latest annual report available at as_of is for the prior fiscal year (point-in-time); "
                      "company FY%d is compared with their FY%d" % (focus, focus - 1))
    if any(p.get("band_widened") for p in used):
        dq["size_band_widened"] = True
    if any(int(p.get("tier") or 4) < 4 for p in used):
        dq["sic_tiers"] = sorted({int(p.get("tier") or 4) for p in used}, reverse=True)
    return {"peer_list": [{"ticker": p.get("ticker"), "name": p.get("name"), "cik": p.get("cik"),
                           "fiscal_year": p.get("fiscal_year"), "tier": p.get("tier")} for p in used],
            "metric_zscores": zs, "outlier_metrics": outliers, "informational_outliers": informational,
            "flags_fired": len(outliers),
            "flags_by_year": {focus: flags} if flags else {}, "key_finding": kf, "severity": sev,
            "focus_year": focus, "evidence": evidence, "data_quality": dq, "degraded": degraded,
            "company_values": company_vals, "unavailable": False}


def run_peer(state: dict) -> dict:
    """Sync, never raises. Returns {"peer_result", "agent_trace", "degraded"}."""
    t0 = time.perf_counter()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    degraded: list[str] = []
    try:
        result = _analyse(state, degraded)
        status = "unavailable" if result.get("unavailable") else "ok"
    except Exception as exc:
        log.warning("peer agent failed: %s", exc)
        result = {"error": f"{type(exc).__name__}: {exc}", "unavailable": True, "severity": "None", "flags_fired": 0,
                  "flags_by_year": {}, "focus_year": state.get("focus_year"), "metric_zscores": {},
                  "outlier_metrics": [], "peer_list": [], "evidence": [],
                  "key_finding": f"peer unavailable: {type(exc).__name__}: {exc}",
                  "data_quality": {"unavailable": {"peer_comparison": str(exc)}}, "degraded": degraded}
        status = "error"
    trace = {"agent": "peer", "status": status, "started": started,
             "duration_ms": int((time.perf_counter() - t0) * 1000), "summary": result.get("key_finding", ""),
             "degraded": list(degraded)}
    return {"peer_result": result, "agent_trace": [trace], "degraded": degraded}
