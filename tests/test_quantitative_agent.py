"""Tests for agents/quantitative_agent.py.

* Real-data tests (marked ``network``; served from the on-disk EDGAR cache, auto-skipped if SEC is unreachable and
  nothing is cached) build point-in-time AnnualFacts with ``tools.xbrl_parser.get_annual_facts`` using each case's
  ``analysis_filing_date`` from ``evaluation/fraud_cases.py``.
* Synthetic tests use INVENTED arithmetic inputs (structure/logic only, labelled SYNTH) - no claim about any company.
* LLM behaviour is tested with mocks of ``tools.llm.llm_available`` / ``tools.llm.llm_json``.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents import quantitative_agent as qa  # noqa: E402
from agents.quantitative_agent import (FLAG_ACCRUALS, FLAG_ALTMAN, FLAG_BENEISH, FLAG_DSO,  # noqa: E402
                                       numerals_valid, run_quantitative)
from tools import llm  # noqa: E402


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """Default: no LLM key (deterministic path). Individual tests override."""
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    monkeypatch.setattr(llm, "llm_json", lambda *a, **k: None)


def _fv(v, **kw):
    d = {"value": float(v), "tag": "SYNTH", "unit": "USD", "source": "xbrl", "comparative": False}
    d.update(kw)
    return d


def synth_annual(by_year: dict, unit="USD", **extra):
    out = {"by_year": {y: {k: _fv(v, unit=unit) for k, v in d.items()} for y, d in by_year.items()},
           "missing": {}, "period_end": {}, "source_by_year": {y: "xbrl" for y in by_year},
           "unit": unit, "warnings": []}
    out.update(extra)
    return out


# SYNTH inputs: invented numbers. PREV benign, CUR engineered to trip Beneish / DSO / accruals.
SYNTH_PREV = dict(Revenue=1000, COGS=600, SGA=100, NetIncome=100, OperatingCashFlow=110, Depreciation=50,
                  TotalAssets=1000, CurrentAssets=400, PPE=400, NetReceivables=100, LongTermDebt=200,
                  CurrentLiabilities=200, RetainedEarnings=300, OperatingIncome=140, StockholdersEquity=500)
SYNTH_CUR = dict(Revenue=1400, COGS=1000, SGA=150, NetIncome=300, OperatingCashFlow=50, Depreciation=40,
                 TotalAssets=1400, CurrentAssets=700, PPE=400, NetReceivables=400, LongTermDebt=300,
                 CurrentLiabilities=300, RetainedEarnings=400, OperatingIncome=250, StockholdersEquity=600)


def synth_flagging_state():
    return {"annual_facts": synth_annual({2019: SYNTH_PREV, 2020: SYNTH_CUR}), "analysis_years": [2019, 2020],
            "focus_year": 2020}


def _res(state):
    out = run_quantitative(state)
    assert set(out) == {"quantitative_result", "agent_trace", "degraded"}
    return out["quantitative_result"]


# ------------------------------------------------------------------ real data
def _real_state(ticker, years, analysis_years=None):
    from evaluation.fraud_cases import get_case
    from tools.xbrl_parser import get_annual_facts
    c = get_case(ticker)
    a = get_annual_facts(c["cik"], years, as_of=c["analysis_filing_date"])
    ay = analysis_years or years
    return {"ticker": ticker, "cik": c["cik"], "annual_facts": a, "analysis_years": ay, "focus_year": max(ay),
            "as_of": c["analysis_filing_date"]}


@pytest.mark.network
def test_aapl_no_beneish_flag():
    r = _res(_real_state("AAPL", list(range(2015, 2021)), list(range(2016, 2021))))
    assert r["unit"] == "USD"
    for y in range(2016, 2021):
        b = r["beneish_scores"][y]
        assert b["status"] == "ok" and b["flag"] is False and b["zone"] == "unlikely" and b["imputed"] == []
        assert FLAG_BENEISH not in r["flags_by_year"][y]
        # Altman Z' grey zone must never be called distress
        a = r["altman_scores"][y]
        assert a["variant"] == "Z-prime" and a["zone"] == "grey" and a["flag"] is False
    assert r["severity"] in ("None", "Low")
    assert r["focus_year"] == 2020 and r["highest_risk_year"] in range(2016, 2021)
    assert r["data_quality"]["unavailable"] == {}
    assert r["evidence"] == []
    # value anchored to the integration run (FY2019->20 M = -3.068)
    assert r["beneish_scores"][2020]["score"] == pytest.approx(-3.068, abs=0.001)


@pytest.mark.network
def test_enron_statement_path_flags_beneish_with_imputed_sgai():
    r = _res(_real_state("ENRNQ", [1998, 1999, 2000]))
    b = r["beneish_scores"][2000]
    assert b["flag"] is True and b["zone"] == "manipulator" and b["imputed"] == ["SGAI"]
    assert b["score"] == pytest.approx(-0.657, abs=0.002)
    assert FLAG_BENEISH in r["flags_by_year"][2000]
    assert r["severity"] == "High" and r["highest_risk_year"] == 2000
    # FY1999 is grey (recorded, NOT flagged) and FY1998 has no prior
    assert r["beneish_scores"][1999]["zone"] == "grey" and r["beneish_scores"][1999]["flag"] is False
    assert r["beneish_scores"][1998]["status"] == "unavailable"
    assert "FY1997" in r["beneish_scores"][1998]["reason"]
    ev = [e for e in r["evidence"] if e["flag"] == FLAG_BENEISH][0]
    assert ev["year"] == 2000 and ev["value"] == pytest.approx(b["score"])
    assert "imputed" in ev["display"] and "SGAI" in ev["display"]
    assert "receivables" in ev["display"].lower()
    for n in ev["numbers"]:
        assert any(abs(n) == pytest.approx(abs(x), abs=0.06) for x in _nums(ev["display"]))
    assert "SGAI" in r["key_finding"]


def _nums(text):
    return qa._numerals(text)


@pytest.mark.network
def test_worldcom_no_beneish_flag_but_distress_labelled_as_business_distress():
    r = _res(_real_state("WCOM", [1999, 2000, 2001], [2000, 2001]))
    for y in (2000, 2001):
        assert r["beneish_scores"][y]["flag"] is False and r["beneish_scores"][y]["zone"] == "unlikely"
        assert r["beneish_scores"][y]["imputed"] == []
        assert FLAG_BENEISH not in r["flags_by_year"][y]
    assert r["beneish_scores"][2001]["score"] == pytest.approx(-3.012, abs=0.002)
    assert r["severity"] != "High"
    # Z' book-equity variant puts WorldCom in distress; it must be labelled as business distress, not manipulation
    for e in r["evidence"]:
        assert e["flag"] == FLAG_ALTMAN and e["signal_type"] == "business_distress"
        assert "not evidence of accounting manipulation" in e["display"]
    assert "not evidence of manipulation" in r["key_finding"]


@pytest.mark.network
def test_luckin_beneish_unavailable_altman_present_cny():
    r = _res(_real_state("LK", [2018, 2019]))
    assert r["unit"] == "CNY" and "CNY" in r["data_quality"]["unit_note"]
    b = r["beneish_scores"][2019]
    assert b["status"] == "unavailable" and "COGS" in b["reason"] and "SGA" in b["reason"]
    assert "DSRI" in b["reason"]  # FY2018 receivables = 0 -> undefined denominator named
    assert "beneish:2019" in r["data_quality"]["unavailable"]
    a = r["altman_scores"][2019]
    assert a["status"] == "ok" and a["variant"] == "Z-prime" and a["unit"] == "CNY"
    assert a["score"] == pytest.approx(-0.610, abs=0.002) and a["flag"] is True
    assert a["signal_type"] == "business_distress"
    # zero prior receivables: DSO growth undefined, not a flag, not a crash
    d = r["dso_trend"][2019]
    assert d["status"] == "ok" and d["yoy_change_pct"] is None and d["flag"] is False and d["note"]
    assert r["beneish_scores"][2019].get("score") is None
    assert "CNY" in r["key_finding"]
    json.dumps(r, default=str, allow_nan=False)


# ------------------------------------------------------------------ synthetic / edge
def test_synth_flagging_state_full_structure():
    r = _res(synth_flagging_state())
    b = r["beneish_scores"][2020]
    assert b["status"] == "ok" and b["flag"] is True and b["score"] > -1.78 and b["imputed"] == []
    assert r["beneish_scores"][2019]["status"] == "unavailable"  # first year: no prior
    assert FLAG_BENEISH in r["flags_by_year"][2020] and FLAG_DSO in r["flags_by_year"][2020]
    assert FLAG_ACCRUALS in r["flags_by_year"][2020]
    assert r["severity"] == "High" and r["flags_fired"] == len(r["flags_by_year"][2020]) + len(r["flags_by_year"][2019])
    for key in ("beneish_scores", "altman_scores", "revenue_quality", "dso_trend", "accruals_ratio", "flags_fired",
                "highest_risk_year", "key_finding", "severity", "flags_by_year", "focus_year", "data_quality",
                "degraded", "evidence"):
        assert key in r
    assert r["highest_risk_year"] == 2020
    flagged = {(e["flag"], e["year"]) for e in r["evidence"]}
    assert flagged == {(f, y) for y, fl in r["flags_by_year"].items() for f in fl}
    for e in r["evidence"]:
        assert isinstance(e["value"], float) and e["display"] and e["numbers"]
        assert set(e["numbers"]) == set(_nums(e["display"]))
    dso_ev = [e for e in r["evidence"] if e["flag"] == FLAG_DSO][0]
    assert "Revenue grew 40.0% while net receivables grew 300.0%" in dso_ev["display"]
    # Deterministic no-key template + degraded label
    assert any("ANTHROPIC_API_KEY" in d for d in r["degraded"])
    assert "channel-stuffing" in b["explanation"]
    json.dumps(r, default=str, allow_nan=False)


def test_synth_first_year_has_no_beneish_but_other_metrics():
    st = {"annual_facts": synth_annual({2020: SYNTH_CUR}), "analysis_years": [2020], "focus_year": 2020}
    r = _res(st)
    assert r["beneish_scores"][2020] == {"status": "unavailable", "reason": r["beneish_scores"][2020]["reason"]}
    assert "prior-year" in r["beneish_scores"][2020]["reason"]
    assert r["accruals_ratio"][2020]["status"] == "ok" and r["accruals_ratio"][2020]["flag"] is True
    assert r["dso_trend"][2020]["yoy_change_pct"] is None and r["dso_trend"][2020]["flag"] is False
    assert r["severity"] == "Low" and r["flags_by_year"][2020] == [FLAG_ACCRUALS]


def test_unavailable_metric_is_not_zero_and_names_missing_items():
    cur = {k: v for k, v in SYNTH_CUR.items() if k not in ("COGS", "NetReceivables")}
    st = {"annual_facts": synth_annual({2019: SYNTH_PREV, 2020: cur}), "analysis_years": [2019, 2020],
          "focus_year": 2020}
    st["annual_facts"]["missing"] = {2020: {"COGS": "tried tags ['CostOfRevenue']; none present"}}
    r = _res(st)
    b = r["beneish_scores"][2020]
    assert b["status"] == "unavailable" and "score" not in b and "COGS" in b["reason"]
    assert "tried tags ['CostOfRevenue']" in b["reason"]
    assert r["dso_trend"][2020]["status"] == "unavailable" and "NetReceivables" in r["dso_trend"][2020]["reason"]
    assert "beneish:2020" in r["data_quality"]["unavailable"] and "dso:2020" in r["data_quality"]["unavailable"]


def test_beneish_grey_zone_recorded_not_flagged(monkeypatch):
    from tools import financial_metrics as fm
    real = fm.beneish_m_score

    def fake(cur, prev, **kw):
        r = real(cur, prev, **kw)
        r.update(m_score=-2.0, **fm.classify_beneish(-2.0))
        return r

    monkeypatch.setattr(qa.fm, "beneish_m_score", fake)
    r = _res(synth_flagging_state())
    b = r["beneish_scores"][2020]
    assert b["zone"] == "grey" and b["grey_zone"] is True and b["flag"] is False
    assert FLAG_BENEISH not in r["flags_by_year"][2020]


def test_altman_distress_flag_only_in_distress_zone_and_labelled():
    bad = dict(SYNTH_PREV, RetainedEarnings=-900, OperatingIncome=-300, StockholdersEquity=-400, CurrentAssets=100)
    st = {"annual_facts": synth_annual({2019: SYNTH_PREV, 2020: bad}), "analysis_years": [2019, 2020],
          "focus_year": 2020}
    r = _res(st)
    a = r["altman_scores"][2020]
    assert a["zone"] == "distress" and a["flag"] is True and a["signal_type"] == "business_distress"
    ev = [e for e in r["evidence"] if e["flag"] == FLAG_ALTMAN]
    assert ev and ev[0]["signal_type"] == "business_distress" and "not evidence of accounting manipulation" in ev[0]["display"]


def test_market_cap_dict_switches_variant_only_if_complete():
    st = synth_flagging_state()
    st["market_cap"] = {2020: 5000.0}  # missing 2019 -> must stay Z' for all years (never mix)
    r = _res(st)
    assert {v["variant"] for v in r["altman_scores"].values() if v["status"] == "ok"} == {"Z-prime"}
    st["market_cap"] = {2019: 5000.0, 2020: 6000.0}
    r = _res(st)
    assert {v["variant"] for v in r["altman_scores"].values() if v["status"] == "ok"} == {"Z"}


def test_pre_revenue_and_empty_inputs():
    pre = dict(Revenue=0, NetIncome=-50, OperatingCashFlow=-40, TotalAssets=500, CurrentAssets=300)
    st = {"annual_facts": synth_annual({2019: pre, 2020: dict(pre, NetIncome=-70)}), "analysis_years": [2019, 2020],
          "focus_year": 2020}
    r = _res(st)
    assert r["beneish_scores"][2020]["status"] in ("unavailable", "not_meaningful")  # v2: zero revenue = immaterial
    assert r["dso_trend"][2020]["status"] == "unavailable"
    assert r["revenue_quality"][2020]["status"] in ("unavailable", "not_meaningful")
    assert "score" not in r["beneish_scores"][2020]
    json.dumps(r, default=str, allow_nan=False)

    for empty in ({}, {"annual_facts": {"by_year": {}, "missing": {}}},
                  {"annual_facts": synth_annual({}), "analysis_years": [2020]}):
        out = run_quantitative(empty)
        r = out["quantitative_result"]
        assert r["severity"] == "None" and r["flags_fired"] == 0
        assert out["agent_trace"][0]["agent"] == "quantitative"


@pytest.mark.parametrize("bad", [None, 5, "x", [], {"annual_facts": "junk"}, {"annual_facts": {"by_year": {"a": 1}}},
                                 {"annual_facts": {"by_year": {2020: "oops"}}, "analysis_years": ["x"]},
                                 {"xbrl_data": {"facts": 3}, "analysis_years": [2020]}])
def test_malformed_state_never_raises(bad):
    out = run_quantitative(bad)
    r = out["quantitative_result"]
    assert r["severity"] in ("None", "Low", "Medium", "High") and "key_finding" in r
    assert out["agent_trace"][0]["status"] in ("ok", "degraded", "unavailable", "error")


def test_comparative_only_year_is_caveated():
    st = synth_flagging_state()
    st["annual_facts"]["by_year"][2019]["Revenue"]["comparative"] = True
    st["annual_facts"]["filing_by_year"] = {2020: {"n_annual_filings_for_year": 1},
                                            2019: {"n_annual_filings_for_year": 0}}
    r = _res(st)
    assert 2019 in r["data_quality"]["comparative_filled"]
    assert any("FY2019" in c and "comparative" in c for c in r["data_quality"]["caveats"])


def test_fallback_to_xbrl_data_when_no_annual_facts(monkeypatch):
    import tools.xbrl_parser as xp
    seen = {}

    def fake_extract(cf, years, as_of=None, **kw):
        seen.update(cf=cf, years=list(years), as_of=as_of)
        return synth_annual({2019: SYNTH_PREV, 2020: SYNTH_CUR})

    monkeypatch.setattr(xp, "extract_annual_facts", fake_extract)
    st = {"xbrl_data": {"cik": "1", "facts": {}}, "analysis_years": [2020], "as_of": "2021-01-01"}
    r = _res(st)
    assert seen["years"] == [2019, 2020] and seen["as_of"] == "2021-01-01"
    assert r["beneish_scores"][2020]["flag"] is True
    assert any("rebuilt from xbrl_data" in d for d in r["degraded"])


# ------------------------------------------------------------------ LLM (mocked)
def _enable_llm(monkeypatch, reply):
    calls = []
    monkeypatch.setattr(llm, "llm_available", lambda: True)

    def fake(tier, system, user, **kw):
        calls.append((tier, system, user))
        return reply(user) if callable(reply) else reply

    monkeypatch.setattr(llm, "llm_json", fake)
    return calls


def test_llm_reword_accepted_when_numerals_valid(monkeypatch):
    text = ("In FY2020 revenue rose 40.0% but net receivables jumped 300.0%, a classic channel-stuffing pattern; "
            "the Beneish score is above the -1.78 cut-off.")
    calls = _enable_llm(monkeypatch, {"explanation": text})
    r = _res(synth_flagging_state())
    assert r["beneish_scores"][2020]["explanation"] == text
    assert calls and calls[0][0] == "haiku"
    assert json.loads(calls[0][2])["FACTS"]["receivables_growth_pct"] == pytest.approx(300.0)
    assert not any("ANTHROPIC_API_KEY" in d for d in r["degraded"])
    assert r["evidence"][0]["display"]  # evidence display stays deterministic


def test_llm_invented_number_falls_back_to_template(monkeypatch):
    _enable_llm(monkeypatch, {"explanation": "Revenue grew 40.0% while receivables grew 91.7% in FY2020."})
    r = _res(synth_flagging_state())
    e = r["beneish_scores"][2020]["explanation"]
    assert "91.7" not in e and "300.0%" in e and "channel-stuffing" in e
    assert any("numeric validation failed" in d for d in r["degraded"])


@pytest.mark.parametrize("reply", [None, {}, {"explanation": ""}, {"explanation": 7}, "garbage"])
def test_llm_bad_replies_fall_back(monkeypatch, reply):
    _enable_llm(monkeypatch, reply)
    r = _res(synth_flagging_state())
    assert "channel-stuffing" in r["beneish_scores"][2020]["explanation"]


def test_llm_exception_never_propagates(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm, "llm_json", boom)
    r = _res(synth_flagging_state())
    assert "channel-stuffing" in r["beneish_scores"][2020]["explanation"]
    assert any("LLM error" in d for d in r["degraded"])


def test_numerals_valid_unit():
    facts = {"revenue_growth_pct": 40.04, "receivables_growth_pct": 300.0, "gross_margin_cur": 0.2857}
    assert numerals_valid("Revenue up 40.0%, receivables up 300%, margin 28.6%", facts, [])
    assert numerals_valid("M-Score -1.20 in FY2020", facts, [-1.2, 2020.0])
    assert not numerals_valid("Revenue up 41%", facts, [])
    assert not numerals_valid("In FY2019 revenue up 40.0%", facts, [2020.0])


def test_llm_not_called_without_flag(monkeypatch):
    calls = _enable_llm(monkeypatch, {"explanation": "x"})
    st = {"annual_facts": synth_annual({2019: SYNTH_PREV, 2020: SYNTH_PREV}), "analysis_years": [2019, 2020],
          "focus_year": 2020}
    r = _res(st)
    assert calls == [] and r["flags_by_year"][2020] == []
    assert r["severity"] == "None"


# ============================================================================ v2 B6 (docs/V2_CHANGELOG_agents.md)
def test_v2_revenue_materiality_boundaries():
    m = qa.revenue_materiality
    assert m({"Revenue": 10.0, "TotalAssets": 1000.0})[0] is True       # exactly 1%: material
    assert m({"Revenue": 9.9, "TotalAssets": 1000.0})[0] is False
    ok, why = m({"Revenue": 0.0, "TotalAssets": 1000.0})
    assert ok is False and "not meaningful" in why
    assert m({"Revenue": 5.0, "TotalAssets": None})[0] is True           # cannot judge -> not suppressed
    assert m({"Revenue": None, "TotalAssets": 1000.0})[0] is True
    assert m(None)[0] is True


def test_v2_tiny_revenue_year_beneish_and_dso_not_meaningful():
    # SYNTH: revenue collapses from 1000 to 8 on assets of 1400 (0.57%): SGI/DSRI would be absurd
    cur = dict(SYNTH_CUR, Revenue=8, COGS=6, NetReceivables=40)
    st = {"annual_facts": synth_annual({2019: SYNTH_PREV, 2020: cur}), "analysis_years": [2019, 2020], "focus_year": 2020}
    r = _res(st)
    b = r["beneish_scores"][2020]
    assert b["status"] == "not_meaningful" and "not meaningful" in b["reason"] and "score" not in b
    assert FLAG_BENEISH not in r["flags_by_year"][2020]
    d = r["dso_trend"][2020]
    assert d["status"] == "not_meaningful" and FLAG_DSO not in r["flags_by_year"][2020]
    assert not any(e["flag"] in (FLAG_BENEISH, FLAG_DSO) for e in r["evidence"])
    assert "beneish:2020" in r["data_quality"]["unavailable"] or "beneish:2020" in str(r["data_quality"]["unavailable"])
    # no absurd percentage anywhere in the narrated text
    assert "%" not in " ".join(str(e["display"]) for e in r["evidence"] if "dso" in e["flag"])
    json.dumps(r, default=str, allow_nan=False)


def test_v2_tiny_prior_year_revenue_also_blocks_beneish_and_dso_yoy():
    prev = dict(SYNTH_PREV, Revenue=5, COGS=3, NetReceivables=1)   # prior revenue 0.5% of assets
    st = {"annual_facts": synth_annual({2019: prev, 2020: SYNTH_CUR}), "analysis_years": [2019, 2020], "focus_year": 2020}
    r = _res(st)
    assert r["beneish_scores"][2020]["status"] == "not_meaningful"
    assert "FY2019" in r["beneish_scores"][2020]["reason"]
    d = r["dso_trend"][2020]
    assert d["status"] == "ok" and d["yoy_change_pct"] is None and d["flag"] is False and "FY2019" in d["note"]


def test_v2_material_revenue_unchanged():
    r = _res(synth_flagging_state())
    assert r["beneish_scores"][2020]["status"] == "ok" and FLAG_BENEISH in r["flags_by_year"][2020]
    assert FLAG_DSO in r["flags_by_year"][2020]


# ------------------------------------------------------------------ v3: prior-year comparability + imputed inputs
_FLOW_TAGS = {"Revenue": "Revenues", "COGS": "CostOfRevenue", "SGA": "SellingGeneralAndAdministrativeExpense",
              "NetIncome": "NetIncomeLoss", "OperatingCashFlow": "NetCashProvidedByUsedInOperatingActivities",
              "Depreciation": "DepreciationDepletionAndAmortization"}
_INST_TAGS = {"TotalAssets": "Assets", "CurrentAssets": "AssetsCurrent", "PPE": "PropertyPlantAndEquipmentNet",
              "NetReceivables": "AccountsReceivableNetCurrent", "LongTermDebt": "LongTermDebtNoncurrent",
              "CurrentLiabilities": "LiabilitiesCurrent"}


def _synth_companyfacts(filings: dict) -> dict:
    """SYNTH companyfacts. ``filings`` = {accn: (filed, {year: values-dict})}; the first year of each is the filing's own FY."""
    facts: dict = {}

    def add(tag, val, end, start, accn, filed):
        facts.setdefault(tag, {"units": {"USD": []}})["units"]["USD"].append(
            {"end": end, "val": float(val), "accn": accn, "fy": int(filed[:4]), "fp": "FY", "form": "10-K", "filed": filed,
             **({"start": start} if start else {})})

    for accn, (filed, years) in filings.items():
        for y, vals in years.items():
            for item, v in vals.items():
                if item in _FLOW_TAGS:
                    add(_FLOW_TAGS[item], v, f"{y}-12-31", f"{y}-01-01", accn, filed)
                elif item in _INST_TAGS:
                    add(_INST_TAGS[item], v, f"{y}-12-31", None, accn, filed)
    return {"cik": 1, "entityName": "SYNTH", "facts": {"us-gaap": facts}}


def _restated_state(prev_restated: dict, cur: dict = SYNTH_CUR, orig_prev: dict = SYNTH_PREV, with_xbrl: bool = True):
    from tools import xbrl_parser as xp
    cf = _synth_companyfacts({"K19": ("2020-02-20", {2019: orig_prev}), "K20": ("2021-02-20", {2020: cur, 2019: prev_restated})})
    af = xp.extract_annual_facts(cf, [2019, 2020], as_of="2021-02-20")
    st = {"annual_facts": af, "analysis_years": [2019, 2020], "focus_year": 2020, "as_of": "2021-02-20"}
    if with_xbrl:
        st["xbrl_data"] = xp.compact_companyfacts(cf)
    return st


def _prev_divested(**over):
    """SYNTH: the FY2019 comparative restated for a divestiture (revenue, COGS, receivables, assets all smaller)."""
    d = dict(SYNTH_PREV, Revenue=800, COGS=480, SGA=80, NetReceivables=80, TotalAssets=900, CurrentAssets=350, PPE=380)
    d.update(over)
    return d


def test_v3_beneish_uses_prior_year_as_reported_in_current_filing():
    from tools import financial_metrics as fm
    st = _restated_state(_prev_divested())
    r = _res(st)
    b = r["beneish_scores"][2020]
    assert b["status"] == "ok" and b["prior_year_basis"] == "as_reported_in_current_filing"
    restated = fm.beneish_m_score(SYNTH_CUR, _prev_divested())["m_score"]
    original = fm.beneish_m_score(SYNTH_CUR, SYNTH_PREV)["m_score"]
    assert b["score"] == pytest.approx(restated) and abs(restated - original) > 0.05
    pb = r["data_quality"]["prior_year_basis"][2020]
    assert pb["basis"] == "as_reported_in_current_filing" and pb["prior_year"] == 2019 and "K20" in pb["comparative_source"]
    assert pb["changed_items"]["Revenue"] == {"original": 1000.0, "comparative": 800.0}
    # Altman / accruals use year t only: identical with and without the comparative basis
    st2 = _restated_state(_prev_divested(), with_xbrl=False)
    r2 = _res(st2)
    assert r["altman_scores"][2020] == r2["altman_scores"][2020]
    assert r["accruals_ratio"][2020] == r2["accruals_ratio"][2020]


def test_v3_dso_and_revenue_quality_use_the_same_prior_basis():
    st = _restated_state(_prev_divested(NetIncome=50, OperatingCashFlow=90))
    r = _res(st)
    assert r["dso_trend"][2020]["prior_dso_days"] == pytest.approx(80 / 800 * 365)          # restated, not 100/1000
    assert r["revenue_quality"][2020]["prior_ratio"] == pytest.approx(90 / 50)


def test_v3_without_comparatives_falls_back_to_originally_filed_and_flags_it():
    st = _restated_state(_prev_divested(), with_xbrl=False)
    r = _res(st)
    b = r["beneish_scores"][2020]
    assert b["prior_year_basis"] == "originally_filed"
    assert r["data_quality"]["prior_year_basis"][2020]["basis"] == "originally_filed"
    assert "no comparative column available" in r["data_quality"]["prior_year_basis"][2020]["reason"]
    assert any("originally filed" in c for c in b["caveats"])
    from tools import financial_metrics as fm
    assert b["score"] == pytest.approx(fm.beneish_m_score(SYNTH_CUR, SYNTH_PREV)["m_score"])


def test_v3_comparative_missing_core_item_uses_original_year_wholesale():
    prev = {k: v for k, v in _prev_divested().items() if k != "NetReceivables"}     # core item absent from the comparative
    st = _restated_state(prev)
    r = _res(st)
    pb = r["data_quality"]["prior_year_basis"][2020]
    assert pb["basis"] == "originally_filed" and "NetReceivables" in pb["reason"]
    assert r["beneish_scores"][2020]["status"] == "ok"


def test_v3_noncore_item_missing_from_comparative_is_filled_from_original_and_listed():
    prev = {k: v for k, v in _prev_divested().items() if k != "Depreciation"}
    st = _restated_state(prev)
    pb = _res(st)["data_quality"]["prior_year_basis"][2020]
    assert pb["basis"] == "mixed" and pb["filled_from_original"] == ["Depreciation"]


def test_v3_income_statement_block_is_never_mixed_between_bases():
    prev = {k: v for k, v in _prev_divested().items() if k != "SGA"}                # SGA absent from the comparative
    st = _restated_state(prev)
    r = _res(st)
    b = r["beneish_scores"][2020]
    # restated revenue is NOT combined with the originally filed SG&A: SGAI is imputed neutral instead
    assert b["status"] == "ok" and "SGAI" in b["imputed"]


def test_v3_imputed_long_term_debt_is_reported_in_data_quality_and_caveats():
    st = _restated_state(_prev_divested())
    for y in (2019, 2020):
        st["annual_facts"]["by_year"][y]["LongTermDebt"] = _fv(0.0, imputed=True, derived=True, source="statement-table",
                                                              tag="derived: no long-term debt line")
    st["annual_facts"]["imputed_by_year"] = {2020: {"LongTermDebt": "imputed 0: no debt-like row"},
                                             2019: {"LongTermDebt": "imputed 0: no debt-like row"}}
    st["annual_facts"]["item_fallback_by_year"] = {2020: {"LongTermDebt": "derived: no long-term debt line"}}
    r = _res(st)
    dq = r["data_quality"]
    assert set(dq["imputed_inputs"][2020]["LongTermDebt"]) == {"current", "prior"}
    assert dq["statement_table_items"][2020] == {"LongTermDebt": "derived: no long-term debt line"}
    b = r["beneish_scores"][2020]
    assert b["input_imputations"]["LongTermDebt"]["current"].startswith("imputed 0")
    assert any("LongTermDebt=0" in c for c in b["caveats"])


def test_v3_statement_table_comparatives_are_used_when_no_xbrl():
    st = synth_flagging_state()
    comp = {k: _fv(v, comparative=True, source="statement-table") for k, v in _prev_divested().items()}
    st["annual_facts"]["comparative_by_year"] = {2019: comp}
    r = _res(st)
    pb = r["data_quality"]["prior_year_basis"][2020]
    assert pb["basis"] == "as_reported_in_current_filing" and "statement-table comparatives" in pb["comparative_source"]
    assert pb["changed_items"]["Revenue"]["comparative"] == 800.0
