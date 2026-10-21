"""Tests for tools.xbrl_parser.

Offline tests use SYNTHETIC companyfacts built by ``Builder`` (values are arbitrary markers, not real
financials). ``@pytest.mark.network`` tests cross-check XBRL values against the figures printed in
Apple's own 10-K text fetched from EDGAR (independent source) and exercise a 20-F filer and a
pre-XBRL filer.
"""
from __future__ import annotations

import re
from collections import defaultdict

import pytest

from tools import edgar_api as e
from tools import xbrl_parser as x
from tools.common import flatten_year, fiscal_year_of


class Builder:
    """Assemble a companyfacts-shaped dict. ``filing`` tags every fact with the FILING's fy/fp/form/filed/accn."""

    def __init__(self) -> None:
        self.facts: dict = defaultdict(lambda: defaultdict(lambda: {"units": defaultdict(list)}))

    def add(self, tag: str, val: float, end: str, *, start: str | None = None, accn: str, form: str = "10-K",
            filed: str, unit: str = "USD", tax: str = "us-gaap", fy: int | None = None, fp: str = "FY") -> "Builder":
        f = {"end": end, "val": val, "accn": accn, "fy": fy if fy is not None else int(filed[:4]), "fp": fp,
             "form": form, "filed": filed}
        if start:
            f["start"] = start
        self.facts[tax][tag]["units"][unit].append(f)
        return self

    def build(self) -> dict:
        return {"cik": 1, "entityName": "Synthetic", "facts": {t: {k: {"units": dict(v["units"])} for k, v in tags.items()}
                                                              for t, tags in self.facts.items()}}


def _fiscal_filing(b: Builder, accn: str, filed: str, start: str, end: str, rev: float, assets: float, prior: dict | None = None,
                   rev_tag: str = "Revenues", form: str = "10-K", unit: str = "USD") -> None:
    b.add(rev_tag, rev, end, start=start, accn=accn, filed=filed, form=form, unit=unit)
    b.add("Assets", assets, end, accn=accn, filed=filed, form=form, unit=unit)
    for p in (prior or {}).values():
        b.add(rev_tag, p["rev"], p["end"], start=p["start"], accn=accn, filed=filed, form=form, unit=unit)
        b.add("Assets", p["assets"], p["end"], accn=accn, filed=filed, form=form, unit=unit)


# ----------------------------------------------------------------------------- fiscal-year assignment
def test_fiscal_year_of_rules():
    assert fiscal_year_of("2020-09-26") == 2020      # non-calendar FYE (Apple-style)
    assert fiscal_year_of("2021-01-02") == 2020      # 52/53-week year ending just after New Year
    assert fiscal_year_of("2019-02-02") == 2018      # retail calendar
    assert fiscal_year_of("2019-12-28") == 2019
    assert fiscal_year_of("2019-03-31") == 2019
    assert fiscal_year_of("garbage") is None


def test_fy_label_comes_from_period_end_not_filing_fy_field():
    """Non-calendar FYE (late Sept). Every fact carries fy=<filing's year>; comparatives must not be mislabelled."""
    b = Builder()
    # FY2018 (ended 2018-09-29), filed Nov 2018, tagged fy=2018 (a filing attribute)
    _fiscal_filing(b, "A18", "2018-11-05", "2017-10-01", "2018-09-29", 180.0, 1800.0,
                   prior={"2017": {"rev": 170.0, "assets": 1700.0, "start": "2016-10-01", "end": "2017-09-30"}})
    # FY2019 filed Oct 2019 re-reports FY2018 as a (restated) comparative -> same fy tag 2019 as FY2019 current
    _fiscal_filing(b, "A19", "2019-10-31", "2018-10-01", "2019-09-28", 190.0, 1900.0,
                   prior={"2018": {"rev": 181.0, "assets": 1801.0, "start": "2017-10-01", "end": "2018-09-29"}})
    cf = b.build()
    a = x.extract_annual_facts(cf, [2017, 2018, 2019])
    assert a["period_end"] == {2017: "2017-09-30", 2018: "2018-09-29", 2019: "2019-09-28"}
    assert a["by_year"][2019]["Revenue"]["value"] == 190.0
    # as originally reported: FY2018 from the FY2018 filing, not the restated 181 comparative in the FY2019 filing
    assert a["by_year"][2018]["Revenue"]["value"] == 180.0 and a["by_year"][2018]["Revenue"]["accn"] == "A18"
    assert a["by_year"][2018]["TotalAssets"]["value"] == 1800.0
    latest = x.extract_annual_facts(cf, [2018], basis="latest")
    assert latest["by_year"][2018]["Revenue"]["value"] == 181.0 and latest["by_year"][2018]["Revenue"]["accn"] == "A19"


def test_52_53_week_durations_accepted_and_quarterly_ytd_rejected():
    b = Builder()
    # 53-week fiscal year (371 days) and a 52-week year (364 days)
    b.add("Revenues", 53.0, "2017-09-30", start="2016-09-25", accn="K17", filed="2017-11-03")
    b.add("Revenues", 52.0, "2018-09-29", start="2017-10-01", accn="K18", filed="2018-11-05")
    # distractors inside the 10-K: a Q4 (91 days) and 9-month YTD (273 days) fact ending on the same date, larger values
    b.add("Revenues", 999.0, "2018-09-29", start="2018-06-30", accn="K18", filed="2018-11-05")
    b.add("Revenues", 888.0, "2018-09-29", start="2017-12-31", accn="K18", filed="2018-11-05")
    # an 18-month transition-like duration must be rejected as well
    b.add("Revenues", 777.0, "2018-09-29", start="2017-03-31", accn="K18", filed="2018-11-05")
    b.add("Assets", 5.0, "2017-09-30", accn="K17", filed="2017-11-03")
    b.add("Assets", 6.0, "2018-09-29", accn="K18", filed="2018-11-05")
    a = x.extract_annual_facts(b.build(), [2017, 2018])
    assert a["by_year"][2017]["Revenue"]["value"] == 53.0
    assert a["by_year"][2018]["Revenue"]["value"] == 52.0
    assert a["by_year"][2017]["Revenue"]["start"] == "2016-09-25"


def test_quarterly_only_company_year_is_missing_not_guessed():
    b = Builder()
    b.add("Revenues", 10.0, "2019-06-29", start="2019-03-31", accn="Q", filed="2019-08-01", form="10-Q")
    b.add("Revenues", 77.0, "2019-12-31", start="2019-10-01", accn="K19", filed="2020-02-20")  # Q4-only duration in a 10-K
    b.add("Assets", 1.0, "2019-12-31", accn="K19", filed="2020-02-20")
    a = x.extract_annual_facts(b.build(), [2019])
    assert "Revenue" not in a["by_year"][2019]
    assert "tried tags" in a["missing"][2019]["Revenue"] and "Revenues" in a["missing"][2019]["Revenue"]


def test_january_fye_labelled_prior_year():
    b = Builder()
    b.add("Revenues", 1.0, "2019-02-02", start="2018-02-04", accn="R", filed="2019-03-20")
    b.add("Assets", 2.0, "2019-02-02", accn="R", filed="2019-03-20")
    a = x.extract_annual_facts(b.build(), [2018, 2019])
    assert 2018 in a["by_year"] and a["by_year"][2018]["Revenue"]["value"] == 1.0
    assert 2019 not in a["by_year"]


# ----------------------------------------------------------------------------- point in time
def _two_year_restated() -> dict:
    b = Builder()
    _fiscal_filing(b, "K19", "2020-02-20", "2019-01-01", "2019-12-31", 100.0, 500.0)
    # FY2020 filing restates FY2019 comparative (90 / 450) and is filed later
    _fiscal_filing(b, "K20", "2021-02-20", "2020-01-01", "2020-12-31", 120.0, 600.0,
                   prior={"2019": {"rev": 90.0, "assets": 450.0, "start": "2019-01-01", "end": "2019-12-31"}})
    return b.build()


def test_as_of_excludes_later_filings_and_uses_original_values():
    cf = _two_year_restated()
    a = x.extract_annual_facts(cf, [2019, 2020], as_of="2020-12-31")
    assert 2020 not in a["by_year"] and a["source_by_year"][2020] == "none"
    assert "filed by 2020-12-31" in a["missing"][2020]["Revenue"]
    assert a["by_year"][2019]["Revenue"]["value"] == 100.0
    assert max(v["filed"] for v in a["by_year"][2019].values()) <= "2020-12-31"
    # boundary: as_of equal to the filing date includes it
    assert 2019 in x.extract_annual_facts(cf, [2019], as_of="2020-02-20")["by_year"]
    assert 2019 not in x.extract_annual_facts(cf, [2019], as_of="2020-02-19")["by_year"]
    full = x.extract_annual_facts(cf, [2019, 2020])
    assert full["by_year"][2019]["Revenue"]["value"] == 100.0 and full["by_year"][2020]["Revenue"]["value"] == 120.0
    assert x.extract_annual_facts(cf, [2019], basis="latest")["by_year"][2019]["Revenue"]["value"] == 90.0


def test_as_of_never_leaks_restated_comparative_even_if_original_missing_item():
    """If the original filing lacks an item, a later comparative may be used ONLY when it was filed <= as_of."""
    b = Builder()
    b.add("Revenues", 10.0, "2019-12-31", start="2019-01-01", accn="K19", filed="2020-02-01")
    b.add("Assets", 5.0, "2019-12-31", accn="K19", filed="2020-02-01")
    b.add("Revenues", 11.0, "2020-12-31", start="2020-01-01", accn="K20", filed="2021-02-01")
    b.add("Assets", 6.0, "2020-12-31", accn="K20", filed="2021-02-01")
    b.add("NetIncomeLoss", 3.0, "2019-12-31", start="2019-01-01", accn="K20", filed="2021-02-01")  # comparative only in K20
    early = x.extract_annual_facts(b.build(), [2019], as_of="2020-06-30")
    assert "NetIncome" not in early["by_year"][2019]
    late = x.extract_annual_facts(b.build(), [2019], as_of="2021-06-30")
    assert late["by_year"][2019]["NetIncome"]["value"] == 3.0
    assert any("not in original filing" in w for w in late["warnings"])


# ----------------------------------------------------------------------------- units, tags, derivations
def test_single_unit_chosen_consistently():
    b = Builder()
    _fiscal_filing(b, "K1", "2020-03-01", "2019-01-01", "2019-12-31", 700.0, 7000.0, unit="CNY")
    b.add("NetIncomeLoss", -50.0, "2019-12-31", start="2019-01-01", accn="K1", filed="2020-03-01", unit="CNY")
    b.add("OperatingIncomeLoss", -40.0, "2019-12-31", start="2019-01-01", accn="K1", filed="2020-03-01", unit="CNY")
    # convenience-translation USD facts for a couple of items (fewer) must NOT be mixed in
    b.add("Revenues", 100.0, "2019-12-31", start="2019-01-01", accn="K1", filed="2020-03-01", unit="USD")
    b.add("CostOfRevenue", 60.0, "2019-12-31", start="2019-01-01", accn="K1", filed="2020-03-01", unit="USD")
    a = x.extract_annual_facts(b.build(), [2019])
    assert a["unit"] == "CNY"
    assert {v["unit"] for v in a["by_year"][2019].values() if v["unit"] != "shares"} == {"CNY"}
    assert a["by_year"][2019]["Revenue"]["value"] == 700.0
    assert "COGS" not in a["by_year"][2019]                      # only USD COGS exists -> unavailable, not mixed
    assert any("multiple currency units" in w for w in a["warnings"])


def test_tag_variants_across_taxonomy_years():
    b = Builder()
    b.add("SalesRevenueNet", 10.0, "2012-12-31", start="2012-01-01", accn="K12", filed="2013-02-01")
    b.add("CostOfGoodsSold", 6.0, "2012-12-31", start="2012-01-01", accn="K12", filed="2013-02-01")
    b.add("ReceivablesNetCurrent", 2.0, "2012-12-31", accn="K12", filed="2013-02-01")
    b.add("RevenueFromContractWithCustomerExcludingAssessedTax", 20.0, "2019-12-31", start="2019-01-01", accn="K19", filed="2020-02-01")
    b.add("CostOfRevenue", 12.0, "2019-12-31", start="2019-01-01", accn="K19", filed="2020-02-01")
    b.add("AccountsReceivableNetCurrent", 4.0, "2019-12-31", accn="K19", filed="2020-02-01")
    b.add("PropertyPlantAndEquipmentNet", 9.0, "2019-12-31", accn="K19", filed="2020-02-01")
    b.add("DepreciationDepletionAndAmortization", 1.5, "2019-12-31", start="2019-01-01", accn="K19", filed="2020-02-01")
    b.add("LongTermDebtNoncurrent", 3.0, "2019-12-31", accn="K19", filed="2020-02-01")
    a = x.extract_annual_facts(b.build(), [2012, 2019])
    assert a["by_year"][2012]["Revenue"]["tag"] == "SalesRevenueNet"
    assert a["by_year"][2012]["COGS"]["tag"] == "CostOfGoodsSold"
    assert a["by_year"][2012]["NetReceivables"]["tag"] == "ReceivablesNetCurrent"
    assert a["by_year"][2019]["Revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert a["by_year"][2019]["COGS"]["tag"] == "CostOfRevenue"
    assert a["by_year"][2019]["NetReceivables"]["tag"] == "AccountsReceivableNetCurrent"
    assert a["by_year"][2019]["PPE"]["value"] == 9.0 and a["by_year"][2019]["LongTermDebt"]["value"] == 3.0
    assert a["by_year"][2019]["Depreciation"]["value"] == 1.5


def test_ifrs_tags_for_20f_filer():
    b = Builder()
    acc, filed = "F20", "2021-04-30"
    for tag, val, dur in [("Revenue", 300.0, True), ("CostOfSales", 200.0, True), ("ProfitLoss", 10.0, True),
                          ("ProfitLossFromOperatingActivities", 15.0, True), ("CashFlowsFromUsedInOperatingActivities", 22.0, True),
                          ("Assets", 900.0, False), ("CurrentAssets", 400.0, False), ("CurrentLiabilities", 300.0, False),
                          ("Liabilities", 500.0, False), ("Equity", 400.0, False), ("TradeAndOtherCurrentReceivables", 50.0, False),
                          ("PropertyPlantAndEquipment", 250.0, False), ("RetainedEarnings", 120.0, False)]:
        b.add(tag, val, "2020-12-31", start="2020-01-01" if dur else None, accn=acc, form="20-F", filed=filed, unit="EUR", tax="ifrs-full")
    a = x.extract_annual_facts(b.build(), [2020])
    d = a["by_year"][2020]
    assert a["unit"] == "EUR"
    assert d["Revenue"]["value"] == 300.0 and d["COGS"]["tag"] == "CostOfSales" and d["NetIncome"]["tag"] == "ProfitLoss"
    assert d["OperatingIncome"]["value"] == 15.0 and d["OperatingCashFlow"]["value"] == 22.0
    assert d["NetReceivables"]["value"] == 50.0 and d["PPE"]["value"] == 250.0 and d["StockholdersEquity"]["value"] == 400.0
    assert d["Revenue"]["form"] == "20-F" and d["Revenue"]["taxonomy"] == "ifrs-full"


def test_derived_items_are_flagged_and_documented():
    b = Builder()
    acc, f = "K", "2020-03-01"
    b.add("Revenues", 100.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    b.add("GrossProfit", 40.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    b.add("Assets", 500.0, "2019-12-31", accn=acc, filed=f)
    b.add("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 200.0, "2019-12-31", accn=acc, filed=f)
    b.add("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", 30.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    b.add("InterestExpense", 5.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    b.add("SellingAndMarketingExpense", 7.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    b.add("GeneralAndAdministrativeExpense", 3.0, "2019-12-31", start="2019-01-01", accn=acc, filed=f)
    d = x.extract_annual_facts(b.build(), [2019])["by_year"][2019]
    assert d["COGS"]["value"] == 60.0 and d["COGS"]["derived"] and d["COGS"]["tag"] == "derived:Revenue-GrossProfit"
    assert d["TotalLiabilities"]["value"] == 300.0 and d["TotalLiabilities"]["derived"] and d["TotalLiabilities"]["source"] == "derived"
    assert d["OperatingIncome"]["value"] == 35.0 and d["OperatingIncome"]["derived"]
    assert d["SGA"]["value"] == 10.0 and d["SGA"]["derived"]
    assert d["Revenue"]["derived"] is False


def test_g_and_a_alone_is_not_sga():
    b = Builder()
    b.add("Revenues", 1.0, "2019-12-31", start="2019-01-01", accn="K", filed="2020-03-01")
    b.add("GeneralAndAdministrativeExpense", 3.0, "2019-12-31", start="2019-01-01", accn="K", filed="2020-03-01")
    a = x.extract_annual_facts(b.build(), [2019])
    assert "SGA" not in a["by_year"][2019] and "SGA" in a["missing"][2019]


def test_total_liabilities_not_derived_when_mezzanine_ambiguous():
    b = Builder()
    f = "2020-03-01"
    b.add("Revenues", 1.0, "2019-12-31", start="2019-01-01", accn="K", filed=f)
    b.add("Assets", 500.0, "2019-12-31", accn="K", filed=f)
    b.add("StockholdersEquity", 100.0, "2019-12-31", accn="K", filed=f)
    b.add("TemporaryEquityCarryingAmountAttributableToParent", 50.0, "2019-12-31", accn="K", filed=f)
    a = x.extract_annual_facts(b.build(), [2019])
    assert "TotalLiabilities" not in a["by_year"][2019]


def test_missing_reports_tags_tried_and_never_crashes_on_garbage():
    assert x.extract_annual_facts({}, [2019])["by_year"] == {}
    assert x.extract_annual_facts({"facts": {}}, [2019])["source_by_year"][2019] == "none"
    junk = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"end": "bad", "val": 1, "accn": "a", "form": "10-K", "filed": "2020-01-01"}]}}}}}
    a = x.extract_annual_facts(junk, [2019])
    assert a["by_year"] == {} and 2019 in a["missing"]
    with pytest.raises(ValueError):
        x.extract_annual_facts({}, [2019], basis="nonsense")


def test_flatten_and_compact_roundtrip():
    cf = _two_year_restated()
    # add noise that compaction must drop
    cf["facts"]["us-gaap"]["SomethingIrrelevant"] = {"units": {"USD": [{"end": "2019-12-31", "val": 1, "accn": "z", "form": "10-K", "filed": "2020-01-01"}]}}
    cf["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append({"start": "2019-01-01", "end": "2019-03-31", "val": 1.0, "accn": "q", "fy": 2019,
                                                              "fp": "Q1", "form": "10-Q", "filed": "2019-05-01", "frame": "CY2019Q1"})
    comp = x.compact_companyfacts(cf)
    assert "SomethingIrrelevant" not in comp["facts"]["us-gaap"]
    assert all(f["form"] in x.ANNUAL_FORMS_X for u in comp["facts"]["us-gaap"]["Revenues"]["units"].values() for f in u)
    assert comp["entityName"] == "Synthetic"
    a1 = x.extract_annual_facts(cf, [2019, 2020])
    a2 = x.extract_annual_facts(comp, [2019, 2020])
    assert {y: {k: v["value"] for k, v in d.items()} for y, d in a1["by_year"].items()} == \
           {y: {k: v["value"] for k, v in d.items()} for y, d in a2["by_year"].items()}
    flat = flatten_year(a1["by_year"][2019])
    assert flat["Revenue"] == 100.0 and flat["COGS"] is None
    assert x.flatten_annual(a1)[2020]["TotalAssets"] == 600.0
    assert x.compact_companyfacts({}) == {}


def test_facade_without_statement_parser_degrades_gracefully(monkeypatch):
    cf = _two_year_restated()
    import sys
    monkeypatch.setitem(sys.modules, "tools.statement_parser", None)  # simulate import failure
    res = x.get_annual_facts("0000000001", [2019, 1990], as_of="2020-12-31", companyfacts=cf)
    assert res["by_year"][2019]["Revenue"]["value"] == 100.0 and res["source_by_year"][2019] == "xbrl"
    assert res["source_by_year"][1990] == "none"
    assert any("statement_parser" in w for w in res["warnings"])


def test_facade_uses_statement_parser_for_uncovered_year(monkeypatch):
    cf = _two_year_restated()
    fake_filing = {"accession": "0000000001-00-000001", "form": "10-K", "filing_date": "2000-03-01", "report_date": "1999-12-31",
                   "fiscal_year": 1999, "document_url": "u", "cik": "0000000001"}
    monkeypatch.setattr(e, "list_annual_filings", lambda cik, as_of=None, forms=None: [fake_filing])
    monkeypatch.setattr(e, "fetch_filing_html", lambda f: "<legacy filing text>")

    class FakeSP:
        @staticmethod
        def extract_statements(text, fy, form):
            assert text == "<legacy filing text>" and fy == 1999 and form == "10-K"
            return {"values": {"Revenue": {"value": 1.0, "tag": "Total revenues", "unit": "USD", "form": "10-K", "filed": "2000-03-01",
                                           "accn": "0000000001-00-000001", "start": None, "end": "1999-12-31", "derived": False,
                                           "source": "statement-table"}},
                    "missing": {"COGS": "no row"}, "checks": {}, "warnings": ["w1"]}

    import sys
    import types
    mod = types.ModuleType("tools.statement_parser")
    mod.extract_statements = FakeSP.extract_statements  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools.statement_parser", mod)
    import tools
    monkeypatch.setattr(tools, "statement_parser", mod, raising=False)
    res = x.get_annual_facts("0000000001", [1999, 2019], companyfacts=cf)
    assert res["source_by_year"] == {1999: "statement-table", 2019: "xbrl"}
    assert res["by_year"][1999]["Revenue"]["source"] == "statement-table"
    assert res["filing_by_year"][1999]["filing_date"] == "2000-03-01"


def test_facade_fills_missing_item_from_next_year_comparative(monkeypatch):
    """Synthetic structure-only test: a gap in FY1998's own filing is filled from FY1999 filing's prior column, flagged."""
    def fv(v, comparative=False):
        d = {"value": v, "tag": "row", "unit": "USD", "form": "10-K", "filed": None, "accn": None, "start": None,
             "end": None, "derived": False, "source": "statement-table"}
        if comparative:
            d["comparative"] = True
        return d
    f98 = {"accession": "A98", "form": "10-K", "filing_date": "1999-03-01", "report_date": "1998-12-31", "fiscal_year": 1998}
    f99 = {"accession": "A99", "form": "10-K", "filing_date": "2000-03-01", "report_date": "1999-12-31", "fiscal_year": 1999}
    monkeypatch.setattr(e, "list_annual_filings", lambda cik, as_of=None, forms=None: [f99, f98])
    monkeypatch.setattr(e, "fetch_filing_html", lambda f: f["accession"])

    def fake_extract(text, fy, form):
        if text == "A98":
            return {"values": {"Revenue": fv(1.0)}, "missing": {"OperatingCashFlow": "no row"}, "warnings": []}
        return {"values": {"Revenue": fv(2.0)}, "missing": {}, "warnings": [],
                "prior_values": {"Revenue": fv(9.0, True), "OperatingCashFlow": fv(5.0, True)}}

    import sys
    import types
    mod = types.ModuleType("tools.statement_parser")
    mod.extract_statements = fake_extract  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools.statement_parser", mod)
    res = x.get_annual_facts("0000000001", [1998, 1999], companyfacts={})
    assert res["by_year"][1998]["Revenue"]["value"] == 1.0              # own filing wins over comparative
    assert res["by_year"][1998]["OperatingCashFlow"]["value"] == 5.0    # gap filled from the FY1999 comparative
    assert res["by_year"][1998]["OperatingCashFlow"]["comparative"] is True
    assert "OperatingCashFlow" not in res["missing"][1998]
    assert any("comparative column of the FY1999 filing" in w for w in res["warnings"])


# ----------------------------------------------------------------------------- live SEC cross-checks
def _text_row(txt: str, label_regex: str) -> list[float]:
    """Numbers (in the filing's presentation unit) of the first table row whose label matches ``label_regex``."""
    m = re.search(rf"^{label_regex}[^\n|]*\|([^\n]*)$", txt, re.M)
    assert m, f"row {label_regex!r} not found in filing text"
    nums = []
    for cell in m.group(1).split("|"):
        c = cell.strip().replace("$", "").replace(",", "")
        neg = c.startswith("(")
        c = c.strip("()")
        if re.fullmatch(r"\d+(\.\d+)?", c):
            nums.append(-float(c) if neg else float(c))
    return nums


@pytest.fixture(scope="module")
def aapl_cf():
    e.set_client(None)
    return e.get_companyfacts("0000320193")


@pytest.fixture(scope="module")
def aapl_filings():
    e.set_client(None)
    return {f["fiscal_year"]: f for f in e.list_annual_filings("0000320193")}


@pytest.mark.network
@pytest.mark.parametrize("fy", [2020, 2019])
def test_live_apple_xbrl_matches_10k_text(aapl_cf, aapl_filings, fy):
    """XBRL vs the numbers printed in the 10-K itself (USD millions in the filing's tables)."""
    txt = e.fetch_filing_text(aapl_filings[fy])
    d = x.extract_annual_facts(aapl_cf, [fy], as_of=aapl_filings[fy]["filing_date"])["by_year"][fy]
    checks = {
        "Revenue": r"Total net sales", "NetIncome": r"Net income", "TotalAssets": r"Total assets",
        "NetReceivables": r"Accounts receivable, net", "OperatingCashFlow": r"Cash generated by operating activities",
        "CurrentAssets": r"Total current assets", "RetainedEarnings": r"Retained earnings",
    }
    for item, label in checks.items():
        printed = _text_row(txt, label)[0]            # first column = current fiscal year in Apple's tables
        assert d[item]["value"] == printed * 1e6, (fy, item, d[item]["value"], printed)


@pytest.mark.network
def test_live_apple_fy2016_2022_non_calendar_and_53_week(aapl_cf):
    a = x.extract_annual_facts(aapl_cf, range(2016, 2023))
    assert sorted(a["by_year"]) == list(range(2016, 2023))
    assert a["unit"] == "USD"
    assert a["period_end"][2016] == "2016-09-24" and a["period_end"][2019] == "2019-09-28" and a["period_end"][2022] == "2022-09-24"
    # FY2017 was a 53-week year (371 days) and must still be accepted as annual
    assert a["period_end"][2017] == "2017-09-30"
    assert a["by_year"][2017]["Revenue"]["start"] == "2016-09-25"
    for y in range(2016, 2023):
        assert not a["missing"][y], (y, list(a["missing"][y]))
        assert a["by_year"][y]["Revenue"]["end"] == a["period_end"][y]
    # tag variants across taxonomy years
    assert a["by_year"][2016]["Revenue"]["tag"] == "SalesRevenueNet"
    assert a["by_year"][2020]["Revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


@pytest.mark.network
def test_live_apple_point_in_time_excludes_fy2020_and_is_as_originally_reported(aapl_cf, aapl_filings):
    a = x.extract_annual_facts(aapl_cf, [2018, 2019, 2020], as_of="2019-12-31")
    assert sorted(a["by_year"]) == [2018, 2019] and 2020 in a["missing"]
    assert all(v["filed"] <= "2019-12-31" for d in a["by_year"].values() for v in d.values())
    txt19 = e.fetch_filing_text(aapl_filings[2019])
    assert a["by_year"][2019]["Revenue"]["value"] == _text_row(txt19, r"Total net sales")[0] * 1e6
    # FY2017 operating cash flow was later re-presented (restricted cash, ASU 2016-18): original must differ from latest
    orig = x.extract_annual_facts(aapl_cf, [2017], as_of="2019-12-31")["by_year"][2017]["OperatingCashFlow"]
    latest = x.extract_annual_facts(aapl_cf, [2017], as_of="2019-12-31", basis="latest")["by_year"][2017]["OperatingCashFlow"]
    assert orig["accn"] != latest["accn"] and orig["filed"] < latest["filed"]
    assert x.available_years("0000320193", as_of="2019-12-31", companyfacts=aapl_cf)[-1] == 2019


@pytest.mark.network
def test_live_get_annual_facts_facade_and_compact_equivalence(aapl_cf):
    comp = x.compact_companyfacts(aapl_cf)
    import json
    assert len(json.dumps(comp)) < len(json.dumps(aapl_cf)) / 4
    f1 = x.get_annual_facts("0000320193", [2019, 2020], companyfacts=aapl_cf)
    f2 = x.get_annual_facts("0000320193", [2019, 2020], companyfacts=comp)
    assert {y: {k: v["value"] for k, v in d.items()} for y, d in f1["by_year"].items()} == \
           {y: {k: v["value"] for k, v in d.items()} for y, d in f2["by_year"].items()}


@pytest.mark.network
def test_live_enron_pre_xbrl_returns_empty_without_raising():
    cf = e.get_companyfacts("0001024401")
    assert cf == {}
    a = x.extract_annual_facts(cf, [2000])
    assert a["by_year"] == {} and a["source_by_year"][2000] == "none"


@pytest.mark.network
def test_live_luckin_20f_uses_single_cny_unit():
    cik = "0001767582"   # verified via company_tickers.json: Luckin Coffee Inc. (spec CIK 0001767380 returns 404)
    assert e.resolve_company("LKNCY")["cik"] == cik
    cf = e.get_companyfacts(cik)
    a = x.extract_annual_facts(cf, [2019, 2020, 2021])
    assert a["unit"] == "CNY"
    for y in (2019, 2020, 2021):
        d = a["by_year"][y]
        assert d["Revenue"]["form"] == "20-F" and {v["unit"] for k, v in d.items() if k != "SharesOutstanding"} == {"CNY"}
        assert d["TotalAssets"]["value"] > 0


# ----------------------------------------------------------------------------- v2: forward-looking facts must not move the period of report
def test_forward_looking_duration_fact_does_not_shift_period_end():
    """PG regression: a FY2019 10-K (FYE Jun-30, filed Aug) carries a fact for 2019-07-01..2020-06-30 (next year's
    run-off). It must not make the FY2019 filing look like the FY2020 report."""
    b = Builder()
    _fiscal_filing(b, "A-18", "2018-08-07", "2017-07-01", "2018-06-30", 100.0, 500.0)
    _fiscal_filing(b, "A-19", "2019-08-06", "2018-07-01", "2019-06-30", 110.0, 520.0,
                   prior={"p": {"rev": 100.0, "assets": 500.0, "start": "2017-07-01", "end": "2018-06-30"}})
    b.add("UnrecognizedTaxBenefitsDecreasesResultingFromSettlementsWithTaxingAuthorities", 1.0, "2020-06-30",
          start="2019-07-01", accn="A-19", filed="2019-08-06")
    _fiscal_filing(b, "A-20", "2020-08-06", "2019-07-01", "2020-06-30", 120.0, 540.0,
                   prior={"p": {"rev": 110.0, "assets": 520.0, "start": "2018-07-01", "end": "2019-06-30"}})
    # the original share count of FY2020 must come from the FY2020 filing, not the FY2019 one
    b.add("EntityCommonStockSharesOutstanding", 1000.0, "2019-07-31", accn="A-19", filed="2019-08-06", unit="shares", tax="dei")
    b.add("EntityCommonStockSharesOutstanding", 990.0, "2020-07-31", accn="A-20", filed="2020-08-06", unit="shares", tax="dei")
    r = x.extract_annual_facts(b.build(), [2018, 2019, 2020], as_of="2020-08-06")
    fb = r["filing_by_year"]
    assert (fb[2019]["accession"], fb[2019]["period_end"], fb[2019]["n_annual_filings_for_year"]) == ("A-19", "2019-06-30", 1)
    assert (fb[2020]["accession"], fb[2020]["filing_date"], fb[2020]["period_end"]) == ("A-20", "2020-08-06", "2020-06-30")
    assert r["by_year"][2020]["Revenue"]["value"] == 120.0 and r["by_year"][2020]["Revenue"]["accn"] == "A-20"
    assert r["by_year"][2020]["SharesOutstanding"]["value"] == 990.0
    assert r["by_year"][2019]["SharesOutstanding"]["value"] == 1000.0
    assert not [w for w in r["warnings"] if "annual filings" in w]
    # point-in-time: as of 2020-01-01 FY2020 does not exist yet
    r2 = x.extract_annual_facts(b.build(), [2019, 2020], as_of="2020-01-01")
    assert r2["filing_by_year"][2019]["accession"] == "A-19" and 2020 not in r2["filing_by_year"]


# Expected (accession, filing_date, period_end) per fiscal year, read from EDGAR submissions via edgar_api
# (documented in docs/V2_CHANGELOG_xbrl.md); the tests below ALSO cross-check against live list_annual_filings.
_REAL = {
    "PG": ("0000080424", "2020-08-06", {2019: ("0000080424-19-000050", "2019-08-06", "2019-06-30"),
                                         2020: ("0000080424-20-000053", "2020-08-06", "2020-06-30")}),
    "MSFT": ("0000789019", "2020-07-30", {2019: ("0001564590-19-027952", "2019-08-01", "2019-06-30"),
                                           2020: ("0001564590-20-034944", "2020-07-30", "2020-06-30")}),
    "AAPL": ("0000320193", "2020-10-30", {2019: ("0000320193-19-000119", "2019-10-31", "2019-09-28"),
                                           2020: ("0000320193-20-000096", "2020-10-30", "2020-09-26")}),
    "JNJ": ("0000200406", "2021-02-22", {2019: ("0000200406-20-000010", "2020-02-18", "2019-12-29"),
                                          2020: ("0000200406-21-000008", "2021-02-22", "2021-01-03")}),
}


@pytest.mark.network
@pytest.mark.parametrize("name", list(_REAL))
def test_live_original_filing_matches_edgar_submissions(name):
    cik, as_of, expected = _REAL[name]
    a = x.get_annual_facts(cik, sorted(expected), as_of=as_of)
    listing = {f["fiscal_year"]: f for f in e.list_annual_filings(cik, as_of=as_of)}
    for y, (accn, filed, pend) in expected.items():
        fb = a["filing_by_year"][y]
        assert (fb["accession"], fb["filing_date"], fb["period_end"]) == (accn, filed, pend), (name, y)
        assert fb["n_annual_filings_for_year"] == 1
        # independent source: EDGAR submissions list
        lf = listing[y]
        assert (lf["accession"], lf["filing_date"], lf["report_date"]) == (accn, filed, pend), (name, y)
        assert a["period_end"][y] == pend
        assert a["by_year"][y]["Revenue"]["accn"] == accn          # value taken from the original filing
    assert not [w for w in a["warnings"] if "annual filings for" in w or "annual filings (" in w]


@pytest.mark.network
def test_live_pg_fy2020_values_and_shares_from_fy2020_10k():
    a = x.get_annual_facts("0000080424", [2019, 2020], as_of="2020-08-06")
    assert round(a["by_year"][2020]["Revenue"]["value"] / 1e9, 2) == 70.95
    assert a["by_year"][2020]["SharesOutstanding"]["accn"] == "0000080424-20-000053"
    assert a["by_year"][2019]["SharesOutstanding"]["accn"] == "0000080424-19-000050"


@pytest.mark.network
@pytest.mark.parametrize("name,cik,as_of", [("WMT", "0000104169", "2021-03-30"), ("HD", "0000354950", "2021-03-30"),
                                            ("MMM", "0000066740", "2021-02-04")])
def test_live_other_fye_conventions_one_filing_per_year(name, cik, as_of):
    years = list(range(2015, 2021))
    a = x.get_annual_facts(cik, years, as_of=as_of)
    listing = {f["fiscal_year"]: f for f in e.list_annual_filings(cik, as_of=as_of)}
    for y in years:
        fb = a["filing_by_year"][y]
        assert fb["n_annual_filings_for_year"] == 1
        assert (fb["accession"], fb["period_end"]) == (listing[y]["accession"], listing[y]["report_date"]), (name, y)


# ----------------------------------------------------------------------------- v3: prior-year comparability basis
def test_basis_current_filing_reads_prior_year_from_next_filings_comparative():
    cf = _two_year_restated()      # FY2019 original 100 / 500; the FY2020 10-K restates FY2019 to 90 / 450
    a = x.extract_annual_facts(cf, [2019, 2020], basis="as_reported_in_current_filing")
    assert a["by_year"][2019]["Revenue"]["value"] == 90.0 and a["by_year"][2019]["Revenue"]["accn"] == "K20"
    assert a["by_year"][2019]["TotalAssets"]["value"] == 450.0
    assert a["by_year"][2020]["Revenue"]["value"] == 120.0       # newest year: the filing itself
    assert a["comparative_basis"][2019]["basis_used"] == "comparative" and a["comparative_basis"][2019]["from_accession"] == "K20"
    assert a["comparative_basis"][2020]["basis_used"] == "original" and "no annual filing for FY2021" in a["comparative_basis"][2020]["reason"]
    # the default basis is untouched
    assert x.extract_annual_facts(cf, [2019])["by_year"][2019]["Revenue"]["value"] == 100.0


def test_basis_current_filing_no_look_ahead_and_fallback_flagged():
    cf = _two_year_restated()
    early = x.extract_annual_facts(cf, [2019], as_of="2020-12-31", basis="as_reported_in_current_filing")
    # the FY2020 10-K (filed 2021-02-20) is not yet public at as_of: original value, flagged
    assert early["by_year"][2019]["Revenue"]["value"] == 100.0
    assert early["comparative_basis"][2019]["basis_used"] == "original" and early["comparative_basis"][2019]["from_accession"] is None
    late = x.extract_annual_facts(cf, [2019], as_of="2021-02-20", basis="as_reported_in_current_filing")
    assert late["by_year"][2019]["Revenue"]["value"] == 90.0


def test_basis_current_filing_item_missing_in_comparative_falls_back_to_original_and_is_flagged():
    b = Builder()
    _fiscal_filing(b, "K19", "2020-02-20", "2019-01-01", "2019-12-31", 100.0, 500.0)
    b.add("NetIncomeLoss", 7.0, "2019-12-31", start="2019-01-01", accn="K19", filed="2020-02-20")   # original only
    _fiscal_filing(b, "K20", "2021-02-20", "2020-01-01", "2020-12-31", 120.0, 600.0,
                   prior={"2019": {"rev": 90.0, "assets": 450.0, "start": "2019-01-01", "end": "2019-12-31"}})
    a = x.extract_annual_facts(b.build(), [2019, 2020], basis="as_reported_in_current_filing")
    cb = a["comparative_basis"][2019]
    assert a["by_year"][2019]["Revenue"]["value"] == 90.0
    assert a["by_year"][2019]["NetIncome"]["value"] == 7.0 and a["by_year"][2019]["NetIncome"]["comparative_fallback"] is True
    assert cb["basis_used"] == "mixed" and cb["fallback_items"] == ["NetIncome"]
    assert any("originally filed values used" in w for w in a["warnings"])


def test_unknown_basis_rejected():
    with pytest.raises(ValueError):
        x.extract_annual_facts({}, [2019], basis="nonsense")


# ----------------------------------------------------------------------------- v3: per-item statement-table fallback
def _fv(v, tag="row", derived=False):
    return {"value": v, "tag": tag, "unit": "USD", "form": "10-K", "filed": "2020-02-20", "accn": "K19", "start": None,
            "end": "2019-12-31", "derived": derived, "source": "statement-table", "comparative": False}


def _install_fake_parser(monkeypatch, by_year, scale=1.0, evidence=None):
    import sys
    import types
    f19 = {"accession": "K19", "form": "10-K", "filing_date": "2020-02-20", "report_date": "2019-12-31", "fiscal_year": 2019,
           "document_url": "u", "cik": "0000000001"}
    monkeypatch.setattr(e, "list_annual_filings", lambda cik, as_of=None, forms=None: [f19])
    monkeypatch.setattr(e, "fetch_filing_html", lambda f: "<html/>")
    mod = types.ModuleType("tools.statement_parser")
    mod.extract_statements = lambda text, fy, form: {"values": by_year.get(fy, {}), "missing": {}, "prior_values": {},
                                                     "by_year": by_year, "scale": scale, "warnings": [],
                                                     "no_debt_evidence": evidence or {}}
    monkeypatch.setitem(sys.modules, "tools.statement_parser", mod)
    import tools
    monkeypatch.setattr(tools, "statement_parser", mod, raising=False)


def _xbrl_without_cogs():
    b = Builder()
    _fiscal_filing(b, "K19", "2020-02-20", "2019-01-01", "2019-12-31", 100.0, 500.0)
    return b.build()


def test_item_fallback_fills_missing_beneish_item_from_tables_with_provenance(monkeypatch):
    _install_fake_parser(monkeypatch, {2019: {"TotalAssets": _fv(500.0, "Total assets"), "Revenue": _fv(100.0, "Net sales"),
                                              "COGS": _fv(60.0, "Cost of products sold")}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    c = res["by_year"][2019]["COGS"]
    assert c["value"] == 60.0 and c["source"] == "statement-table" and c["tag"] == "Cost of products sold"
    assert c["fallback"].startswith("statement-table")
    assert res["item_fallback_by_year"][2019]["COGS"] == "Cost of products sold"
    assert res["source_by_year"][2019] == "xbrl+statement-table"
    assert res["by_year"][2019]["Revenue"]["source"] == "xbrl"            # XBRL value is never replaced
    assert "COGS" not in res["missing"][2019]


def test_item_fallback_refused_when_table_disagrees_with_xbrl_anchor(monkeypatch):
    # table total assets 5,000 vs XBRL 500: wrong table or scale -> nothing is taken from it
    _install_fake_parser(monkeypatch, {2019: {"TotalAssets": _fv(5000.0), "Revenue": _fv(100.0), "COGS": _fv(60.0)}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    assert "COGS" not in res["by_year"][2019] and res["source_by_year"][2019] == "xbrl"
    assert any("refused" in w and "TotalAssets" in w for w in res["warnings"])


def test_item_fallback_refused_without_any_anchor(monkeypatch):
    _install_fake_parser(monkeypatch, {2019: {"COGS": _fv(60.0)}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    assert "COGS" not in res["by_year"][2019]
    assert any("no anchor item" in w for w in res["warnings"])


def test_item_fallback_can_be_disabled(monkeypatch):
    _install_fake_parser(monkeypatch, {2019: {"TotalAssets": _fv(500.0), "COGS": _fv(60.0)}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs(), item_fallback=False)
    assert "COGS" not in res["by_year"][2019]


def test_long_term_debt_imputed_zero_only_with_balance_sheet_evidence(monkeypatch):
    ev_ok = {"ok": True, "reason": "no debt-like row between Total current liabilities and Total liabilities; the rows reconcile to the gap",
             "rows": ["Other liabilities"], "total_liabilities": 40.0, "current_liabilities": 38.0}
    tables = {2019: {"TotalAssets": _fv(500.0), "COGS": _fv(60.0)}}
    _install_fake_parser(monkeypatch, tables, evidence={2019: ev_ok})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    ltd = res["by_year"][2019]["LongTermDebt"]
    assert ltd["value"] == 0.0 and ltd["imputed"] is True and ltd["derived"] is True
    assert ltd["tag"] == "derived: no long-term debt line" and "imputed 0" in ltd["note"]
    assert "LongTermDebt" in res["imputed_by_year"][2019] and "LongTermDebt" in res["item_fallback_by_year"][2019]
    # evidence not ok (a debt-like row exists): stays missing, never guessed
    _install_fake_parser(monkeypatch, tables, evidence={2019: {"ok": False, "reason": "debt-like non-current liability row(s)"}})
    res2 = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    assert "LongTermDebt" not in res2["by_year"][2019] and not res2["imputed_by_year"]


def test_xbrl_value_for_long_term_debt_is_never_overridden_by_imputation(monkeypatch):
    b = Builder()
    _fiscal_filing(b, "K19", "2020-02-20", "2019-01-01", "2019-12-31", 100.0, 500.0)
    b.add("LongTermDebtNoncurrent", 25.0, "2019-12-31", accn="K19", filed="2020-02-20")
    _install_fake_parser(monkeypatch, {2019: {"TotalAssets": _fv(500.0)}}, evidence={2019: {"ok": True, "reason": "r", "rows": []}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=b.build())
    assert res["by_year"][2019]["LongTermDebt"]["value"] == 25.0 and not res["imputed_by_year"]


def test_item_fallback_finds_the_matching_column_when_year_is_labelled_by_calendar_year(monkeypatch):
    # January year-end filers label the column 2020 for fiscal 2019: the XBRL anchors identify the right column
    _install_fake_parser(monkeypatch, {2019: {"TotalAssets": _fv(300.0), "Revenue": _fv(70.0), "COGS": _fv(1.0)},
                                       2020: {"TotalAssets": _fv(500.0), "Revenue": _fv(100.0), "COGS": _fv(60.0)}})
    res = x.get_annual_facts("0000000001", [2019], as_of="2020-12-31", companyfacts=_xbrl_without_cogs())
    assert res["by_year"][2019]["COGS"]["value"] == 60.0
    assert any("labelled 2020" in w for w in res["warnings"])
