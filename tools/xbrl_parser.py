"""XBRL companyfacts -> canonical annual financial line items, point-in-time and unit-consistent.

Why this is not a naive ``fy == year`` lookup
---------------------------------------------
In SEC ``companyfacts`` the ``fy``/``fp`` fields describe the FILING that carried the fact, not the
period the fact measures (a FY2018 10-K also reports FY2017 and FY2016 comparatives, all tagged
``fy=2018``). This module therefore:

1. identifies each annual filing (form 10-K / 10-K405 / 10-KSB / 20-F / 40-F, amendments excluded) by
   accession number and derives its fiscal period end as the latest end date among its annual-duration
   (350-380 day) facts that ends on or before its filing date - comparatives always end earlier, and
   forward-looking facts (periods ending after the filing date, e.g. PG's FY2019 10-K carries a
   2019-07-01..2020-06-30 tax-benefit run-off fact) are ignored;
2. labels the fiscal year from the period end via :func:`tools.common.fiscal_year_of` (CONTRACTS D12;
   ``DocumentFiscalYearFocus`` is not present in companyfacts for most filers, so it cannot be relied on);
3. accepts duration facts only when ``350 <= (end - start) <= 380`` days (52/53-week years are 364/371
   days; quarterly and YTD facts are discarded);
4. ignores every fact with ``filed > as_of`` (no look-ahead) and, with
   ``basis="as_originally_reported"``, reads each fiscal year's value from the EARLIEST annual filing
   for that year, never from later (possibly restated) comparatives (v3: ``basis="as_reported_in_current_filing"`` is the
   opposite, deliberately: year t-1 is read from the comparative columns of the year-t filing, see :func:`extract_annual_facts`);
5. chooses ONE currency unit per company (the unit covering the most (item, period) pairs, ``USD`` on ties)
   and never mixes units across items or years.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from typing import Any, Iterable, Optional

from tools import common
from tools.common import fiscal_year_of, flatten_year, get_logger

log = get_logger("xbrl_parser")

ANNUAL_FORMS_X = frozenset({"10-K", "10-K405", "10-KSB", "20-F", "40-F"})
BASES = ("as_originally_reported", "latest", "as_reported_in_current_filing")
#: Canonical items that the Beneish M-Score reads (docs/V3_CHANGELOG_data.md); when XBRL lacks one of them for a year whose
#: filing is available, :func:`get_annual_facts` tries that filing's own statement tables (with identity/anchor safeguards).
BENEISH_ITEMS = ("Revenue", "COGS", "SGA", "NetReceivables", "CurrentAssets", "PPE", "TotalAssets", "Depreciation",
                 "LongTermDebt", "CurrentLiabilities", "NetIncome", "OperatingCashFlow")
#: Items whose agreement with the XBRL value of the same year proves that the statement table is the right table / scale / period.
ANCHOR_ITEMS = ("TotalAssets", "Revenue", "NetIncome", "CurrentAssets", "CurrentLiabilities")
FY_MIN_DAYS, FY_MAX_DAYS = 350, 380

#: Ordered candidate concepts per canonical line item (bare concept names; us-gaap, ifrs-full and,
#: for shares, dei are searched in that order). Legacy names (SalesRevenueNet ...) cover older taxonomies.
CANONICAL_CONCEPTS: dict[str, list[str]] = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense",
                "Revenue", "RevenueFromContractsWithCustomers"],
    "COGS": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
             "CostOfSales"],
    "GrossProfit": ["GrossProfit"],
    # G&A alone is NOT accepted as SG&A (it would understate the line); see AUX "SellingAndMarketing"+"GeneralAndAdmin".
    "SGA": ["SellingGeneralAndAdministrativeExpense", "SellingGeneralAndAdministrativeExpenses"],
    "NetIncome": ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss",
                  "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "OperatingIncome": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "InterestExpense": ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense", "InterestExpenseNonoperating",
                        "FinanceCosts"],
    "IncomeTaxExpense": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities",
                          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                          "CashFlowsFromUsedInOperatingActivities"],
    "Depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                     "DepreciationAndAmortization", "DepreciationAmortizationAndOther", "Depreciation",
                     "DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense"],
    "TotalAssets": ["Assets"],
    "CurrentAssets": ["AssetsCurrent", "CurrentAssets"],
    "CurrentLiabilities": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "TotalLiabilities": ["Liabilities"],
    "NetReceivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "AccountsAndNotesReceivableNetCurrent",
                       "AccountsReceivableNet", "TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    "PPE": ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
            "PropertyPlantAndEquipment"],
    "LongTermDebt": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermNotesPayable",
                     "ConvertibleNotesPayableNoncurrent", "NoncurrentPortionOfNoncurrentLoansReceived",
                     "LongtermBorrowings", "NoncurrentPortionOfLongtermBorrowings", "NoncurrentPortionOfNoncurrentBorrowings"],
    "CurrentDebt": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                    "CurrentBorrowings", "CurrentPortionOfLongtermBorrowings"],
    "RetainedEarnings": ["RetainedEarningsAccumulatedDeficit", "DevelopmentStageEnterpriseDeficitAccumulatedDuringDevelopmentStage",
                         "RetainedEarnings"],
    "StockholdersEquity": ["StockholdersEquity", "EquityAttributableToOwnersOfParent",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"],
    "CashAndEquivalents": ["CashAndCashEquivalentsAtCarryingValue",
                           "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalents"],
    "SharesOutstanding": ["CommonStockSharesOutstanding", "NumberOfSharesOutstanding", "EntityCommonStockSharesOutstanding"],
}

#: Auxiliary concepts used only by documented derivations (not exposed as canonical items).
AUX_CONCEPTS: dict[str, list[str]] = {
    "Pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
               "ProfitLossBeforeTax"],
    "LiabilitiesNoncurrent": ["LiabilitiesNoncurrent", "NoncurrentLiabilities"],
    "SellingAndMarketing": ["SellingAndMarketingExpense", "SellingExpense", "DistributionCosts"],
    "GeneralAndAdmin": ["GeneralAndAdministrativeExpense", "AdministrativeExpense"],
    "TotalEquityInclNCI": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"],
    "MinorityInterest": ["MinorityInterest", "NoncontrollingInterests"],
    "TemporaryEquity": ["TemporaryEquityCarryingAmountAttributableToParent",
                        "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests",
                        "RedeemableNoncontrollingInterestEquityCarryingAmount", "TemporaryEquityCarryingAmount"],
}

#: Balance-sheet (point-in-time) items; everything else is an annual-duration flow item.
INSTANT_ITEMS = frozenset({"TotalAssets", "CurrentAssets", "CurrentLiabilities", "TotalLiabilities", "NetReceivables",
                           "PPE", "LongTermDebt", "CurrentDebt", "RetainedEarnings", "StockholdersEquity",
                           "CashAndEquivalents", "SharesOutstanding"})
_AUX_INSTANT = frozenset({"LiabilitiesNoncurrent", "TotalEquityInclNCI", "MinorityInterest", "TemporaryEquity"})
SHARE_ITEMS = frozenset({"SharesOutstanding"})
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_TAXONOMIES = ("us-gaap", "ifrs-full", "dei")


@lru_cache(maxsize=65536)
def _days(start: str, end: str) -> Optional[int]:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return None


def _all_concept_names() -> set[str]:
    names: set[str] = set()
    for lst in list(CANONICAL_CONCEPTS.values()) + list(AUX_CONCEPTS.values()):
        names.update(lst)
    return names


def compact_companyfacts(raw: dict) -> dict:
    """Shrink raw companyfacts to what the pipeline needs (CONTRACTS D7).

    Keeps ``cik``/``entityName``, only concepts listed in :data:`CANONICAL_CONCEPTS` / :data:`AUX_CONCEPTS`,
    only facts reported in annual forms (amendments dropped) and only the fields
    ``start,end,val,accn,fy,fp,form,filed``. The result is accepted by :func:`extract_annual_facts`.
    """
    if not raw:
        return {}
    names = _all_concept_names()
    out_facts: dict[str, dict] = {}
    for tax, concepts in (raw.get("facts") or {}).items():
        if tax not in _TAXONOMIES:
            continue
        for tag, body in concepts.items():
            if tag not in names or (tax == "dei" and tag != "EntityCommonStockSharesOutstanding"):
                continue
            units_out: dict[str, list] = {}
            for unit, facts in (body.get("units") or {}).items():
                keep = [{k: f[k] for k in ("start", "end", "val", "accn", "fy", "fp", "form", "filed") if k in f}
                        for f in facts if f.get("form") in ANNUAL_FORMS_X]
                if keep:
                    units_out[unit] = keep
            if units_out:
                out_facts.setdefault(tax, {})[tag] = {"units": units_out}
    return {"cik": raw.get("cik"), "entityName": raw.get("entityName", ""), "compact": True, "facts": out_facts}


class _Index:
    """Pre-processed annual facts: filings by accession, facts grouped by (tag, unit, end)."""

    def __init__(self, companyfacts: dict, as_of: Optional[str]) -> None:
        self.as_of = as_of
        self.filings: dict[str, dict] = {}
        self.by_key: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        self.dei_by_accn: dict[tuple[str, str], list[dict]] = defaultdict(list)
        names = _all_concept_names()
        dur_end: dict[str, str] = {}
        inst_end: dict[str, str] = {}
        for tax in _TAXONOMIES:
            for tag, body in ((companyfacts.get("facts") or {}).get(tax) or {}).items():
                for unit, facts in (body.get("units") or {}).items():
                    for f in facts:
                        form = f.get("form")
                        filed = f.get("filed") or ""
                        if form not in ANNUAL_FORMS_X or not filed or (as_of and filed > as_of):
                            continue
                        accn = f.get("accn") or ""
                        end = f.get("end") or ""
                        rec = self.filings.setdefault(accn, {"accn": accn, "form": form, "filed": filed})
                        # A report cannot describe a period that ends after it was filed: forward-looking facts
                        # (e.g. tax-benefit run-off over the NEXT fiscal year) must not define the period of report.
                        if tax != "dei" and end and end <= filed:
                            start = f.get("start")
                            if start:
                                d = _days(start, end)
                                if d is not None and FY_MIN_DAYS <= d <= FY_MAX_DAYS and end > dur_end.get(accn, ""):
                                    dur_end[accn] = end
                            elif end > inst_end.get(accn, ""):
                                inst_end[accn] = end
                        if tag in names:
                            fact = dict(f, tax=tax, unit=unit, tag=tag)
                            if tax == "dei":
                                self.dei_by_accn[(tag, accn)].append(fact)
                            else:
                                self.by_key[(tag, unit, end)].append(fact)
        for accn, rec in self.filings.items():
            rec["period_end"] = dur_end.get(accn) or inst_end.get(accn)
        self.dur_end_accns = set(dur_end)

    # fiscal year -> filings (earliest filed first)
    def filings_by_fy(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = defaultdict(list)
        for rec in self.filings.values():
            pe = rec.get("period_end")
            # require an annual-duration fact so that a stray instant cannot define a period
            if pe and rec["accn"] in self.dur_end_accns:
                fy = fiscal_year_of(pe)
                if fy is not None:
                    out[fy].append(rec)
        for fy in out:
            out[fy].sort(key=lambda r: (r["filed"], r["accn"]))
        return out


def _fact_value(f: dict, derived: bool = False, source: str = "xbrl", tag: Optional[str] = None) -> dict:
    return {"value": float(f["val"]), "tag": tag or f["tag"], "unit": f["unit"], "form": f["form"], "filed": f["filed"],
            "accn": f["accn"], "start": f.get("start"), "end": f["end"], "derived": derived, "source": source,
            "taxonomy": f.get("tax", "")}


def _choose_unit(idx: _Index) -> tuple[str, dict[str, int]]:
    """Pick the currency unit covering the most distinct (monetary item, period-end) pairs; USD wins ties."""
    cov: dict[str, set] = defaultdict(set)
    tag_to_item = {t: item for item, tags in CANONICAL_CONCEPTS.items() if item not in SHARE_ITEMS for t in tags}
    for (tag, unit, end), facts in idx.by_key.items():
        item = tag_to_item.get(tag)
        if item and _CURRENCY_RE.match(unit):
            cov[unit].add((item, end))
    counts = {u: len(s) for u, s in cov.items()}
    if not counts:
        return "USD", counts
    best = max(counts, key=lambda u: (counts[u], u == "USD"))
    return best, counts


def _pick(idx: _Index, tags: Iterable[str], instant: bool, unit: str, end: str, accn: Optional[str],
          basis: str, shares: bool = False, prefer_accn: Optional[str] = None) -> Optional[tuple[dict, bool]]:
    """Choose the fact for one item/period. Returns (fact, from_original_filing) or None.

    Pass 1 only considers the period's original annual filing (``accn``); pass 2 (any annual filing filed
    <= as_of) is the fallback for years whose original filing carries no XBRL for this item. With
    ``basis="latest"`` the most recently filed fact wins instead.
    """
    def ok(f: dict) -> bool:
        if instant:
            return not f.get("start") or f["tax"] == "dei"
        d = _days(f["start"], f["end"]) if f.get("start") else None
        return d is not None and FY_MIN_DAYS <= d <= FY_MAX_DAYS

    def best(cands: list[dict]) -> Optional[dict]:
        cands = [c for c in cands if ok(c)]
        if not cands:
            return None
        if basis == "latest":
            return max(cands, key=lambda c: (c["filed"], c["accn"]))
        return min(cands, key=lambda c: (c["filed"], c["accn"], abs((_days(c["start"], c["end"]) or 365) - 365) if c.get("start") else 0))

    units = ("shares",) if shares else (unit,)
    tag_list = list(tags)
    if prefer_accn:   # basis="as_reported_in_current_filing": the comparative column of the NEXT year's filing wins
        for tag in tag_list:
            if tag == "EntityCommonStockSharesOutstanding":
                continue
            for u in units:
                c = best([f for f in idx.by_key.get((tag, u, end), []) if f["accn"] == prefer_accn])
                if c:
                    return c, True
    if basis != "latest" and accn:
        for tag in tag_list:
            if tag == "EntityCommonStockSharesOutstanding":
                c = best(idx.dei_by_accn.get((tag, accn), []))
                if c:
                    return c, True
                continue
            for u in units:
                c = best([f for f in idx.by_key.get((tag, u, end), []) if f["accn"] == accn])
                if c:
                    return c, True
    for tag in tag_list:
        if tag == "EntityCommonStockSharesOutstanding":
            continue
        for u in units:
            c = best(idx.by_key.get((tag, u, end), []))
            if c:
                return c, False
    return None


def _derive(by: dict[str, dict], aux: dict[str, dict], unit: str) -> None:
    """Fill gaps via documented accounting identities; every derived value is flagged ``derived=True``."""

    def mk(tag: str, value: float, parts: list[dict]) -> dict:
        ref = max(parts, key=lambda p: (p["filed"], p["accn"]))
        return {"value": value, "tag": tag, "unit": unit, "form": ref["form"], "filed": ref["filed"], "accn": ref["accn"],
                "start": ref.get("start"), "end": ref["end"], "derived": True, "source": "derived", "taxonomy": "derived"}

    rev, cogs, gp = by.get("Revenue"), by.get("COGS"), by.get("GrossProfit")
    if gp is None and rev and cogs:
        by["GrossProfit"] = mk("derived:Revenue-COGS", rev["value"] - cogs["value"], [rev, cogs])
    if cogs is None and rev and gp:
        by["COGS"] = mk("derived:Revenue-GrossProfit", rev["value"] - gp["value"], [rev, gp])
    if "SGA" not in by and aux.get("SellingAndMarketing") and aux.get("GeneralAndAdmin"):
        a, b = aux["SellingAndMarketing"], aux["GeneralAndAdmin"]
        by["SGA"] = mk("derived:SellingAndMarketing+GeneralAndAdministrative", a["value"] + b["value"], [a, b])
    if "OperatingIncome" not in by and aux.get("Pretax") and by.get("InterestExpense"):
        a, b = aux["Pretax"], by["InterestExpense"]
        by["OperatingIncome"] = mk("derived:EBIT-proxy(PretaxIncome+InterestExpense)", a["value"] + b["value"], [a, b])
    if "TotalLiabilities" not in by:
        cl, ncl, ta = by.get("CurrentLiabilities"), aux.get("LiabilitiesNoncurrent"), by.get("TotalAssets")
        if cl and ncl:
            by["TotalLiabilities"] = mk("derived:LiabilitiesCurrent+LiabilitiesNoncurrent", cl["value"] + ncl["value"], [cl, ncl])
        elif ta:
            eq = aux.get("TotalEquityInclNCI")
            ambiguous = (aux.get("TemporaryEquity") and abs(aux["TemporaryEquity"]["value"]) > 0) or (
                eq is None and aux.get("MinorityInterest") and abs(aux["MinorityInterest"]["value"]) > 0)
            if not eq and not ambiguous:
                eq = by.get("StockholdersEquity")
            if eq and not ambiguous:
                by["TotalLiabilities"] = mk("derived:Assets-Equity", ta["value"] - eq["value"], [ta, eq])


def extract_annual_facts(companyfacts: dict, years: Iterable[int], as_of: Optional[str] = None,
                         basis: str = "as_originally_reported") -> dict:
    """Extract canonical annual line items for the requested fiscal years (see module docstring).

    Parameters
    ----------
    companyfacts : raw or compact (:func:`compact_companyfacts`) SEC companyfacts JSON; ``{}`` is allowed.
    years : fiscal years to extract (D12 labelling).
    as_of : ISO date; facts filed after it are ignored (point-in-time).
    basis : ``"as_originally_reported"`` (value from the annual filing for that fiscal year; the default and
        the only look-ahead-safe choice for backtests), ``"latest"`` (most recent filing <= as_of, i.e.
        restated comparatives) or ``"as_reported_in_current_filing"`` (v3): the value of fiscal year ``y`` is read from
        the comparative column of the EARLIEST annual filing for fiscal year ``y + 1`` (so year t-1 of a year-t analysis is
        stated on the same basis as year t: restated for divestitures / reclassifications), provided that filing was filed
        <= ``as_of`` (it is the filing being analysed, so there is no look-ahead).  Items that filing does not carry, and
        the newest year (which has no later filing), fall back to the originally filed value; both are recorded in
        ``comparative_basis[y]`` (``basis_used`` = ``"comparative"`` / ``"original"``, ``fallback_items``).

    Returns ``AnnualFacts`` per docs/CONTRACTS.md section 2 (plus ``filing_by_year``, ``basis``, ``as_of``).
    """
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, got {basis!r}")
    years = sorted({int(y) for y in years})
    res: dict[str, Any] = {"by_year": {}, "missing": {}, "period_end": {}, "source_by_year": {}, "unit": "USD",
                           "warnings": [], "filing_by_year": {}, "basis": basis, "as_of": as_of,
                           "comparative_basis": {}}
    asof_txt = as_of or "latest"
    if not companyfacts or not companyfacts.get("facts"):
        res["warnings"].append("no XBRL companyfacts available (pre-XBRL filer or 404)")
        for y in years:
            res["source_by_year"][y] = "none"
            res["missing"][y] = {c: f"no XBRL companyfacts for this company (filings filed by {asof_txt})" for c in CANONICAL_CONCEPTS}
        return res

    idx = _Index(companyfacts, as_of)
    unit, unit_counts = _choose_unit(idx)
    res["unit"] = unit
    if len([u for u, n in unit_counts.items() if n > 0]) > 1:
        res["warnings"].append(f"multiple currency units present {unit_counts}; using '{unit}' consistently (most coverage)")
    fy_filings = idx.filings_by_fy()

    # period ends for years lacking an annual filing in the data: infer from comparatives
    inferred: dict[int, str] = {}
    missing_years = [y for y in years if y not in fy_filings]
    if missing_years:
        ends: dict[int, Counter] = defaultdict(Counter)
        for (tag, u, end), facts in idx.by_key.items():
            if u != unit or tag not in ("Revenues", "Assets", "NetIncomeLoss", "SalesRevenueNet", "Revenue",
                                        "RevenueFromContractWithCustomerExcludingAssessedTax", "ProfitLoss"):
                continue
            fy = fiscal_year_of(end)
            if fy in missing_years:
                ends[fy][end] += len(facts)
        for fy, ctr in ends.items():
            inferred[fy] = max(ctr, key=lambda e: (ctr[e], e))

    for y in years:
        recs = fy_filings.get(y)
        if recs:
            orig = recs[0]
            end = orig["period_end"]
            accn: Optional[str] = orig["accn"]
            res["filing_by_year"][y] = {"accession": orig["accn"], "form": orig["form"], "filing_date": orig["filed"],
                                        "period_end": end, "n_annual_filings_for_year": len(recs)}
            if len(recs) > 1:
                res["warnings"].append(f"FY{y}: {len(recs)} annual filings ({[r['accn'] for r in recs]}); original {orig['accn']} used")
        elif y in inferred:
            end, accn = inferred[y], None
            res["warnings"].append(f"FY{y}: no annual filing with XBRL filed by {asof_txt}; period {end} inferred from later-filed comparatives")
        else:
            res["source_by_year"][y] = "none"
            res["missing"][y] = {c: f"no annual filing/period found for FY{y} among filings filed by {asof_txt}"
                                 for c in CANONICAL_CONCEPTS}
            continue

        by: dict[str, dict] = {}
        miss: dict[str, str] = {}
        pref: Optional[str] = None
        cmp_fallback: list[str] = []
        if basis == "as_reported_in_current_filing":
            nxt_recs = fy_filings.get(y + 1)
            pref = nxt_recs[0]["accn"] if nxt_recs else None
            res["comparative_basis"][y] = {"from_accession": pref, "from_filing_date": nxt_recs[0]["filed"] if nxt_recs else None,
                                           "basis_used": "comparative" if pref else "original", "fallback_items": cmp_fallback,
                                           "reason": "" if pref else f"no annual filing for FY{y + 1} filed by {asof_txt}"}
        for item, tags in CANONICAL_CONCEPTS.items():
            got = _pick(idx, tags, item in INSTANT_ITEMS, unit, end, accn, basis, shares=item in SHARE_ITEMS, prefer_accn=pref)
            if got:
                by[item] = _fact_value(got[0])
                if pref and got[0]["accn"] != pref:
                    cmp_fallback.append(item)
                    by[item]["comparative_fallback"] = True
                elif not pref and not got[1] and accn:
                    res["warnings"].append(f"FY{y} {item}: not in original filing; taken from later filing {got[0]['accn']} (may be restated)")
        aux: dict[str, dict] = {}
        for name, tags in AUX_CONCEPTS.items():
            got = _pick(idx, tags, name in _AUX_INSTANT, unit, end, accn, basis)
            if got:
                aux[name] = _fact_value(got[0])
        _derive(by, aux, unit)
        if pref and cmp_fallback:
            res["comparative_basis"][y]["basis_used"] = "mixed" if len(cmp_fallback) < len(by) else "original"
            res["warnings"].append(f"FY{y}: basis as_reported_in_current_filing: {sorted(cmp_fallback)} not in the FY{y + 1} "
                                   f"filing's comparatives; originally filed values used for those items")
        for item, tags in CANONICAL_CONCEPTS.items():
            if item not in by:
                miss[item] = f"tried tags {tags}; none present in filings filed by {asof_txt}"
        res["by_year"][y] = by
        res["missing"][y] = miss
        res["period_end"][y] = end
        res["source_by_year"][y] = "xbrl" if by else "none"
    return res


def available_years(cik: Any, as_of: Optional[str] = None, companyfacts: Optional[dict] = None) -> list[int]:
    """Fiscal years with an annual XBRL filing filed on or before ``as_of`` (ascending)."""
    from tools import edgar_api

    cf = companyfacts if companyfacts is not None else edgar_api.get_companyfacts(cik)
    if not cf:
        return []
    return sorted(_Index(cf, as_of).filings_by_fy())


def _agrees(x: float, t: float, scale: float = 1.0) -> bool:
    """Two values of the same item agree within 0.5 % (or two units of the statement's rounding scale)."""
    return abs(x - t) <= max(0.005 * max(abs(x), abs(t)), 2.0 * scale)


def _impute_no_ltd(res: dict, y: int, values: dict, missing: dict, parsed: dict, filing: Optional[dict],
                   col: Optional[int] = None) -> bool:
    """Set ``values['LongTermDebt'] = 0`` (flagged ``imputed``) iff the parsed balance sheet proves there is no long-term debt.

    The evidence is the filing's own balance-sheet column for fiscal year ``y`` (current or comparative); see
    :func:`tools.statement_parser.no_long_term_debt_evidence` for the conditions.  Returns True when the value was set.
    """
    if not parsed or not filing or "LongTermDebt" in values:
        return False
    col = y if col is None else col     # column label of the table that matched year y
    ev = (parsed.get("no_debt_evidence") or {}).get(col)
    if not ev or not ev.get("ok"):
        return False
    comparative = col != int(filing["fiscal_year"])
    note = ("imputed 0: " + ev["reason"] + f"; non-current rows: {ev.get('rows')}; total liabilities "
            f"{ev.get('total_liabilities', 0):,.0f} = current liabilities {ev.get('current_liabilities', 0):,.0f} + those rows "
            "(Beneish LVGI is defined on total long-term debt; a balance sheet with no debt line has none)")
    values["LongTermDebt"] = {
        "value": 0.0, "tag": "derived: no long-term debt line", "unit": res.get("unit") or "USD", "form": filing["form"],
        "filed": filing["filing_date"], "accn": filing["accession"], "start": None,
        "end": None if comparative else filing.get("report_date"), "derived": True, "source": "statement-table",
        "imputed": True, "comparative": comparative, "note": note, "evidence": ev}
    missing.pop("LongTermDebt", None)
    res.setdefault("imputed_by_year", {}).setdefault(y, {})["LongTermDebt"] = note
    return True


def get_annual_facts(cik: Any, years: Iterable[int], as_of: Optional[str] = None,
                     companyfacts: Optional[dict] = None, basis: str = "as_originally_reported",
                     item_fallback: bool = True) -> dict:
    """Facade: XBRL for years it covers, otherwise ``tools.statement_parser`` over the filing's own tables.

    ``source_by_year`` records ``"xbrl"``, ``"statement-table"``, ``"xbrl+statement-table"`` or ``"none"`` per year. If
    ``tools.statement_parser`` is not importable the uncovered years stay ``"none"`` with a warning.

    v3 per-item fallback (``item_fallback=True``): when XBRL covers a year but lacks a Beneish input (:data:`BENEISH_ITEMS`)
    and the year's filing is available (<= ``as_of``), that item is read from the filing's statement tables.  Safeguards: (1)
    the statement parser already withholds tables that fail its identity checks; (2) the table must AGREE with the XBRL
    value of the same year on at least one anchor item (:data:`ANCHOR_ITEMS`) and contradict none, otherwise nothing is
    taken from it (wrong table / scale / restated column); (3) every filled value keeps ``source="statement-table"`` and
    the printed row label as ``tag`` and is listed in ``item_fallback_by_year[y]``.  ``LongTermDebt`` that no tag and no
    row provides is set to 0 ONLY when the balance sheet proves there is no long-term debt (see
    :func:`tools.statement_parser.no_long_term_debt_evidence`); that value is marked ``imputed=True`` with the evidence and
    listed in ``imputed_by_year[y]`` (Beneish's LVGI is defined on total long-term debt: none is a zero, not a gap).
    ``comparative_by_year[y]`` carries, for statement-table years, the comparative column of the FY y+1 filing.
    """
    from tools import edgar_api

    years = sorted({int(y) for y in years})
    cf = companyfacts if companyfacts is not None else edgar_api.get_companyfacts(cik)
    res = extract_annual_facts(cf, years, as_of=as_of, basis=basis)
    res.setdefault("item_fallback_by_year", {})
    res.setdefault("imputed_by_year", {})
    res.setdefault("comparative_by_year", {})
    todo = [y for y in years if not res["by_year"].get(y)]
    need: dict[int, list[str]] = {}
    if item_fallback:
        for y in years:
            have = res["by_year"].get(y)
            if have:
                miss_items = [i for i in BENEISH_ITEMS if i not in have]
                if miss_items:
                    need[y] = miss_items
    if not todo and not need:
        return res
    try:
        import importlib
        statement_parser = importlib.import_module("tools.statement_parser")  # honours sys.modules[...] = None
    except Exception as exc:
        res["warnings"].append(f"statement_parser unavailable ({type(exc).__name__}); FY{todo} left unavailable")
        return res
    try:
        filings = edgar_api.list_annual_filings(cik, as_of=as_of)
    except Exception as exc:
        res["warnings"].append(f"could not list filings for statement-table fallback: {exc}")
        return res
    parsed_cache: dict[str, dict] = {}

    def _parse(filing: dict) -> dict:
        key = filing["accession"]
        if key not in parsed_cache:
            try:
                raw = edgar_api.fetch_filing_html(filing)
                parsed_cache[key] = statement_parser.extract_statements(raw, int(filing["fiscal_year"]), filing["form"])
            except Exception as exc:
                res["warnings"].append(f"FY{filing.get('fiscal_year')}: statement_parser failed ({type(exc).__name__}: {exc})")
                parsed_cache[key] = {}
        return parsed_cache[key]

    def _first_filing(year: int) -> Optional[dict]:
        cands = sorted([f for f in filings if f.get("fiscal_year") == year], key=lambda f: (f["filing_date"], f["accession"]))
        return cands[0] if cands else None

    for y in todo:
        filing = _first_filing(y)
        values: dict = {}
        parsed: dict = {}
        if filing:
            parsed = _parse(filing)
            values = dict(parsed.get("values") or {})
        missing = dict(parsed.get("missing") or {})
        # Fill items still missing from the comparative column of the NEXT year's filing (filed <= as_of
        # because list_annual_filings is point-in-time). Provenance is kept: comparative=True on the FactValue.
        nxt = _first_filing(y + 1)
        if nxt:
            nparsed = _parse(nxt)
            prior = nparsed.get("prior_values") or {}
            if prior:
                res["comparative_by_year"][y] = {k: v for k, v in prior.items() if v and v.get("value") is not None}
            filled = [k for k, v in prior.items() if k not in values and v and v.get("value") is not None]
            for k in filled:
                values[k] = prior[k]
                missing.pop(k, None)
            if filled:
                res["warnings"].append(f"FY{y}: {sorted(filled)} taken from the comparative column of the FY{y + 1} filing "
                                       f"({nxt['accession']}, filed {nxt['filing_date']})")
        if not values:
            continue
        # v3: LongTermDebt = 0 only when a balance sheet of this period proves there is none
        if "LongTermDebt" not in values:
            if not _impute_no_ltd(res, y, values, missing, parsed, filing) and nxt:
                _impute_no_ltd(res, y, values, missing, _parse(nxt), nxt)
        src = filing or nxt
        res["by_year"][y] = values
        res["missing"][y] = missing
        res["period_end"][y] = (filing or {}).get("report_date") or ""
        res["source_by_year"][y] = "statement-table"
        res["filing_by_year"][y] = {"accession": src["accession"], "form": src["form"],
                                    "filing_date": src["filing_date"], "period_end": src.get("report_date"),
                                    "n_annual_filings_for_year": 1 if filing else 0}
        for w in parsed.get("warnings") or []:
            res["warnings"].append(f"FY{y} statement_parser: {w}")

    # ---- v3 per-item fallback for years that XBRL covers only partly
    unit = res.get("unit") or "USD"
    for y, items in need.items():
        have = res["by_year"][y]
        in_next = res.get("basis") == "as_reported_in_current_filing" and bool(
            (res.get("comparative_basis", {}).get(y) or {}).get("from_accession"))
        filing = _first_filing(y + 1) if in_next else _first_filing(y)
        if not filing:
            continue
        parsed = _parse(filing)
        scale = float(parsed.get("scale") or 1.0)
        # safeguard (2): find the table column whose anchor items agree with the XBRL values of year y.  The column label
        # is tried first; other printed columns are tried because some filers label a January year-end by its calendar
        # year (the label then points one fiscal year off).  No agreeing column -> nothing is taken from the table.
        col_year, cols, compared, bad = None, {}, [], []
        by_cols = parsed.get("by_year") or {}
        for cy in [y] + sorted((c_ for c_ in by_cols if c_ != y), reverse=True):
            cv = by_cols.get(cy) or {}
            cmp_ = [(k, have[k]["value"], cv[k]["value"]) for k in ANCHOR_ITEMS
                    if k in have and k in cv and cv[k].get("value") is not None]
            bad_ = [k for k, xv, tv in cmp_ if not _agrees(xv, tv, scale)]
            if cmp_ and not bad_:
                col_year, cols, compared, bad = cy, cv, cmp_, bad_
                break
            if cy == y:
                compared, bad = cmp_, bad_
        if col_year is None:
            res["warnings"].append(f"FY{y}: statement-table fallback for {items} refused: " + (
                f"no table column agrees with XBRL (column {y} disagrees on {bad})" if bad
                else "no anchor item (TotalAssets/Revenue/NetIncome/...) to compare"))
            continue
        if col_year != y:
            res["warnings"].append(f"FY{y}: statement-table column labelled {col_year} matched the XBRL anchors (period labelled by calendar year)")
        filled: dict[str, str] = {}
        for k in items:
            fv = cols.get(k)
            if fv and fv.get("value") is not None and k not in have:
                if k == "SGA" and not re.search(r"selling|marketing|sales", fv.get("tag") or "", re.I):
                    continue   # G&A alone is not SG&A (same rule as the XBRL mapping)
                have[k] = dict(fv, fallback="statement-table (XBRL item missing)")
                filled[k] = fv.get("tag") or ""
                res["missing"].get(y, {}).pop(k, None)
        if "LongTermDebt" not in have and _impute_no_ltd(res, y, have, res["missing"].setdefault(y, {}), parsed, filing, col=col_year):
            filled["LongTermDebt"] = have["LongTermDebt"]["tag"]
        if filled:
            res["item_fallback_by_year"][y] = filled
            res["source_by_year"][y] = "xbrl+statement-table"
            res["warnings"].append(f"FY{y}: {sorted(filled)} not in XBRL; taken from the filing's statement tables "
                                   f"({filing['accession']}; anchors agree: {[k for k, _, _ in compared]})")
    return res


def flatten_annual(annual: dict) -> dict[int, dict[str, Optional[float]]]:
    """``AnnualFacts`` -> ``{year: {canonical: float|None}}`` for :mod:`tools.financial_metrics`."""
    return {y: flatten_year(v) for y, v in (annual.get("by_year") or {}).items()}
