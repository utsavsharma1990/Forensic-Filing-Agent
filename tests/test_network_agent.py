"""Tests for agents/network_agent.py.

Real-data tests build ``filing_metadata`` / ``filing_texts`` from REAL SEC filings through
``tools.edgar_api`` (disk-cached) and ``tools.text_parser.build_filing_metadata`` - exactly what the
pipeline's fetch_data does.  They skip (never fake) when a filing is neither cached nor downloadable.
Synthetic tests use obviously artificial metadata dicts (labelled) to exercise rules/edge cases only; no
real-company numbers are typed in.  Assertions on real data state what the parsers extracted from the
filing text (auditor/CFO names, which flags fire); expected values were read from the filings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.network_agent import run_network  # noqa: E402
from tools import edgar_api as ea  # noqa: E402
from tools import text_parser as tp  # noqa: E402

CIK = {
    "ENRON": "0001024401", "WCOM": "0000723527", "AAPL": "0000320193", "MSFT": "0000789019",
    "JNJ": "0000200406", "PG": "0000080424", "MMM": "0000066740", "BRKB": "0001067983",
    "LUCKIN": "0001767582", "NIKOLA": "0001731289", "BBBY": "0000886158",
    "KHC": "0001637459", "SMCI": "0001375365",
}

_MEMO: dict = {}


def company_state(cik: str, years: list[int], proxy: bool = False, as_of: str | None = None) -> dict:
    """Build the raw-state fields the network agent reads, from real filings (cached)."""
    key = (cik, tuple(years), proxy, as_of)
    if key in _MEMO:
        return _MEMO[key]
    try:
        filings = ea.list_annual_filings(cik, as_of=as_of)
        by_year: dict[int, dict] = {}
        for f in filings:                       # newest first -> keep the newest filing per FY
            by_year.setdefault(f["fiscal_year"], f)
        proxies = ea.list_filings(cik, ["DEF 14A"], as_of=as_of) if proxy else []
        meta, texts = {}, {}
        for y in years:
            f = by_year.get(y)
            if not f:
                continue
            text = ea.fetch_filing_text(f)
            ptxt = None
            if proxy:
                later = sorted((p for p in proxies if p["filing_date"] > f["filing_date"]), key=lambda p: p["filing_date"])
                if later:
                    ptxt = ea.fetch_filing_text(later[0])
            meta[y] = tp.build_filing_metadata(f, text, ptxt)
            texts[y] = text
    except Exception as exc:  # offline and not cached
        pytest.skip(f"real filings unavailable for {cik}: {exc!r}")
    state = {"filing_metadata": meta, "filing_texts": texts, "analysis_years": sorted(meta)}
    _MEMO[key] = state
    return state


def run(state: dict) -> dict:
    out = run_network(state)
    assert set(out) == {"network_result", "agent_trace", "degraded"}
    json.dumps(out["network_result"], default=str)          # serialisable
    return out["network_result"]


def _flags(res: dict, year: int) -> list[str]:
    return res["flags_by_year"].get(year, [])


# --------------------------------------------------------------------------------------
# Synthetic edge cases (artificial placeholder data)
# --------------------------------------------------------------------------------------

def _m(auditor="Alpha Audit LLP", cfo="Pat Quinn", ceo="Sam Rivers", fees=None, rpt=0, **kw):
    d = {"auditor": auditor, "cfo": cfo, "ceo": ceo, "audit_fees": fees, "related_party_chars": rpt,
         "audit_fee_source": "filing" if fees else None, "signatures_found": True}
    d.update(kw)
    return d


def _st(meta: dict, texts: dict | None = None, years=None, **extra) -> dict:
    return {"filing_metadata": meta, "filing_texts": texts if texts is not None else {y: "plain text." for y in meta},
            "analysis_years": years or sorted(meta), **extra}


def test_contract_shape_and_never_raises():
    out = run_network(_st({2019: _m(), 2020: _m()}))
    r = out["network_result"]
    for k in ("auditor_history", "executive_changes", "audit_fees", "restatements", "related_party_flags",
              "going_concern", "flags_fired", "key_finding", "severity", "flags_by_year", "focus_year",
              "data_quality", "degraded", "evidence"):
        assert k in r
    assert r["focus_year"] == 2020 and r["severity"] == "None" and r["flags_fired"] == 0
    assert out["agent_trace"][0]["agent"] == "network"
    for garbage in ({}, {"filing_metadata": None}, {"analysis_years": [2020]}, {"filing_metadata": {2020: None}, "analysis_years": [2020]},
                    {"filing_metadata": "x", "filing_texts": 5, "analysis_years": "abc"}):
        o = run_network(garbage)
        assert "network_result" in o and "agent_trace" in o


def test_unavailable_result_shape_when_no_data():
    r = run_network({})["network_result"]
    assert r["unavailable"] is True and r["severity"] == "None" and r["flags_fired"] == 0 and r["flags_by_year"] == {}


def test_first_year_no_change_not_unavailable():
    r = run(_st({2020: _m()}))
    assert r["auditor_history"][2020]["changed"] is False
    assert r["auditor_history"][2020]["status"] == "first_year"
    assert r["executive_changes"][2020]["cfo_changed"] is False


def test_auditor_change_detected_with_exact_evidence():
    r = run(_st({2019: _m(auditor="Alpha Audit LLP"), 2020: _m(auditor="Beta Partners LLP")}))
    assert r["auditor_history"][2020]["changed"] is True
    assert "network.auditor_change" in _flags(r, 2020)
    ev = [e for e in r["evidence"] if e["flag"] == "network.auditor_change"][0]
    assert ev["display"] == "Auditor changed from Alpha Audit LLP to Beta Partners LLP in FY2020"
    assert ev["year"] == 2020 and 2020.0 in ev["numbers"]
    assert r["severity"] == "Low"


@pytest.mark.parametrize("a,b", [
    ("PricewaterhouseCoopers LLP", "PricewaterhouseCoopers"),
    ("ERNST & YOUNG LLP", "Ernst & Young LLP"),
    ("  Ernst   &  Young  LLP ", "ernst & young llp"),
    ("BDO USA, LLP", "BDO USA, P.C."),
    ("Ernst & Young LLP", "Ernst & Young Hua Ming LLP"),
    ("Deloitte & Touche LLP", "DELOITTE & TOUCHE LLP"),
])
def test_rebranding_whitespace_case_not_an_auditor_change(a, b):
    r = run(_st({2019: _m(auditor=a), 2020: _m(auditor=b)}))
    assert r["auditor_history"][2020]["changed"] is False
    assert "network.auditor_change" not in _flags(r, 2020)


def test_real_auditor_switch_between_big_firms_detected():
    r = run(_st({2019: _m(auditor="Ernst & Young LLP"), 2020: _m(auditor="KPMG LLP")}))
    assert "network.auditor_change" in _flags(r, 2020)


def test_unknown_auditor_is_never_a_change():
    r = run(_st({2019: _m(auditor="Alpha Audit LLP"), 2020: _m(auditor=None)}))
    assert r["auditor_history"][2020]["changed"] is False
    assert r["auditor_history"][2020]["status"] == "unknown"
    assert "auditor_FY2020" in r["data_quality"]["unavailable"]
    assert "network.auditor_change" not in _flags(r, 2020)


def test_unknown_year_between_two_known_compares_across_gap():
    meta = {2018: _m(auditor="Alpha Audit LLP"), 2019: _m(auditor=None), 2020: _m(auditor="Beta Partners LLP")}
    r = run(_st(meta))
    assert r["auditor_history"][2019]["changed"] is False
    h = r["auditor_history"][2020]
    assert h["changed"] is True and h["compared_to"] == 2018 and h["gap_years"] == 1
    assert "across 1 year" in h["note"]
    ev = [e for e in r["evidence"] if e["flag"] == "network.auditor_change"][0]
    assert "auditor unknown in between" in ev["display"]
    # same auditor on both sides of the gap -> no change
    meta[2020]["auditor"] = "ALPHA AUDIT LLP"
    assert run(_st(meta))["auditor_history"][2020]["changed"] is False


def test_missing_metadata_year_is_unknown_not_changed():
    r = run(_st({2018: _m(), 2020: _m()}, years=[2018, 2019, 2020], texts={2018: "x", 2019: "x", 2020: "x"}))
    assert r["auditor_history"][2019]["status"] == "unknown"
    assert r["auditor_history"][2019]["changed"] is False
    assert r["executive_changes"][2019]["cfo_changed"] is False


def test_baseline_year_before_analysis_window_is_used():
    meta = {2018: _m(auditor="Alpha Audit LLP"), 2019: _m(auditor="Beta Partners LLP")}
    r = run(_st(meta, years=[2019]))
    assert r["auditor_history"][2019]["changed"] is True
    assert 2018 not in r["auditor_history"]            # baseline only, not reported


def test_cfo_and_ceo_change():
    meta = {2019: _m(cfo="Pat Quinn", ceo="Sam Rivers"), 2020: _m(cfo="Lee Morgan", ceo="Sam Rivers")}
    r = run(_st(meta))
    assert r["executive_changes"][2020] == {**r["executive_changes"][2020], "cfo_changed": True, "ceo_changed": False}
    assert _flags(r, 2020) == ["network.cfo_change"]
    meta[2020]["ceo"] = "Jo Park"
    r = run(_st(meta))
    assert "network.ceo_change" in _flags(r, 2020) and r["severity"] == "Medium"


@pytest.mark.parametrize("a,b", [("Pat Quinn", "PAT A. QUINN"), ("Pat Quinn", "Quinn, Pat"), ("Pat  Quinn Jr.", "pat quinn")])
def test_same_cfo_name_variants_not_a_change(a, b):
    r = run(_st({2019: _m(cfo=a), 2020: _m(cfo=b)}))
    assert r["executive_changes"][2020]["cfo_changed"] is False


def test_repeated_name_artefact_in_signature_block_not_a_change():
    # parser artefact seen in a real filing: leading name repeated at the end of the extracted string
    r = run(_st({2019: _m(ceo="Pat Q. Quinn PAT Q."), 2020: _m(ceo="Pat Q. Quinn")}))
    assert r["executive_changes"][2020]["ceo_changed"] is False


def test_unknown_or_single_token_cfo_not_a_change():
    for cfo in (None, "", "Quinn"):
        r = run(_st({2019: _m(cfo="Pat Quinn"), 2020: _m(cfo=cfo)}))
        assert r["executive_changes"][2020]["cfo_changed"] is False
        assert r["executive_changes"][2020]["cfo_status"] == "unknown"


def test_auditor_and_cfo_change_same_year_is_hard_flag_high():
    meta = {2019: _m(), 2020: _m(auditor="Beta Partners LLP", cfo="Lee Morgan")}
    r = run(_st(meta))
    assert set(_flags(r, 2020)) == {"network.auditor_change", "network.cfo_change"}
    assert r["severity"] == "High"
    assert "Auditor changed" in r["key_finding"] and "CFO changed" in r["key_finding"]


def test_severity_uses_focus_year_only():
    meta = {2018: _m(), 2019: _m(cfo="Lee Morgan"), 2020: _m(cfo="Lee Morgan")}
    r = run(_st(meta))
    assert r["flags_fired"] == 1 and _flags(r, 2019) == ["network.cfo_change"] and r["severity"] == "None"
    assert "2019" in r["key_finding"]


def test_audit_fee_flag_requires_no_corresponding_revenue_growth():
    meta = {2019: _m(fees=1000.0), 2020: _m(fees=1400.0)}       # +40%
    # revenue +10% (< 20% = fee growth/2): flagged, normal confidence
    r = run(_st(meta, annual_facts={"by_year": {2019: {"Revenue": {"value": 100.0}}, 2020: {"Revenue": {"value": 110.0}}}}))
    assert r["audit_fees"][2020]["flag"] is True and r["audit_fees"][2020]["confidence"] == "normal"
    assert r["audit_fees"][2020]["yoy_change_pct"] == 40.0 and r["audit_fees"][2020]["revenue_growth_pct"] == 10.0
    # revenue +20% (== fee growth/2): corresponding -> not flagged
    r = run(_st(meta, annual_facts={"by_year": {2019: {"Revenue": 100.0}, 2020: {"Revenue": 120.0}}}))
    assert r["audit_fees"][2020]["flag"] is False
    # revenue +50% -> not flagged ; str keys (post-JSON) accepted
    r = run(_st(meta, annual_facts={"by_year": {"2019": {"Revenue": {"value": 100.0}}, "2020": {"Revenue": {"value": 150.0}}}}))
    assert r["audit_fees"][2020]["flag"] is False
    # revenue falling -> flagged
    r = run(_st(meta, annual_facts={"by_year": {2019: {"Revenue": 100.0}, 2020: {"Revenue": 90.0}}}))
    assert r["audit_fees"][2020]["flag"] is True


def test_audit_fee_threshold_is_strict_30_percent():
    r = run(_st({2019: _m(fees=1000.0), 2020: _m(fees=1300.0)}))
    assert r["audit_fees"][2020]["flag"] is False and r["audit_fees"][2020]["yoy_change_pct"] == 30.0
    r = run(_st({2019: _m(fees=1000.0), 2020: _m(fees=1301.0)}))
    assert r["audit_fees"][2020]["flag"] is True


def test_audit_fee_without_revenue_flags_low_confidence():
    r = run(_st({2019: _m(fees=1000.0), 2020: _m(fees=2000.0)}))
    f = r["audit_fees"][2020]
    assert f["flag"] is True and f["confidence"] == "low"
    ev = [e for e in r["evidence"] if e["flag"] == "network.audit_fees"][0]
    assert ev["confidence"] == "low" and "low confidence" in ev["display"]
    assert any(k.startswith("revenue_growth") for k in r["data_quality"]["unavailable"])


def test_audit_fee_missing_year_unavailable_no_flag():
    r = run(_st({2018: _m(fees=1000.0), 2019: _m(fees=None), 2020: _m(fees=5000.0)}))
    assert r["audit_fees"][2020]["flag"] is False and r["audit_fees"][2020]["status"] == "no_prior"
    assert r["audit_fees"][2019]["status"] == "unavailable"


def test_audit_fee_non_consecutive_fee_years_refused():
    meta = {2019: _m(fees=1000.0, audit_fee_detail={"year": 2019}), 2020: _m(fees=3000.0, audit_fee_detail={"year": 2021})}
    r = run(_st(meta))
    assert r["audit_fees"][2020]["flag"] is False and "non-consecutive" in r["audit_fees"][2020]["reason"]


def test_related_party_growth_and_floor():
    r = run(_st({2019: _m(rpt=4000), 2020: _m(rpt=6100)}))               # +52.5%, >= floor
    assert r["related_party_flags"][2020]["detected"] is True and "network.related_party" in _flags(r, 2020)
    r = run(_st({2019: _m(rpt=4000), 2020: _m(rpt=6000)}))               # exactly +50%: not flagged
    assert r["related_party_flags"][2020]["detected"] is False
    r = run(_st({2019: _m(rpt=500), 2020: _m(rpt=2000)}))                # +300% but below floor
    assert r["related_party_flags"][2020]["detected"] is False
    r = run(_st({2019: _m(rpt=0), 2020: _m(rpt=9000)}))                  # prior not found: new disclosure, not flagged
    assert r["related_party_flags"][2020]["detected"] is False and r["related_party_flags"][2020]["new_disclosure"] is True


GC_TEXT = ("These conditions raise substantial doubt about our ability to continue as a going concern. "
           "Management plans to raise capital.")
MW_TEXT = "Management identified a material weakness in internal control over financial reporting as of year end."
RS_TEXT = "On March 1 the Audit Committee concluded that the previously issued financial statements should be restated because of errors."


def test_going_concern_text_hard_flag():
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "All fine.", 2020: GC_TEXT}))
    assert r["going_concern"][2020]["detected"] is True and r["going_concern"][2019]["detected"] is False
    assert "network.going_concern" in _flags(r, 2020) and r["severity"] == "High"
    assert "going-concern" in r["key_finding"]


def test_negated_going_concern_not_flagged():
    t = "Management has concluded there is no substantial doubt about the Company's ability to continue as a going concern."
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: t, 2020: t}))
    assert not r["going_concern"][2020]["detected"]


def test_restatement_and_material_weakness_flag():
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: RS_TEXT, 2020: MW_TEXT}))
    assert r["restatements"][2019]["restatement_detected"] is True and "network.restatement" in _flags(r, 2019)
    assert r["restatements"][2020]["material_weakness_detected"] is True and "network.restatement" in _flags(r, 2020)
    assert r["severity"] == "High"


def test_boilerplate_and_negation_not_flagged():
    t = ("Prior period amounts were restated to conform to the current year presentation. "
         "Amended and Restated Bylaws are filed as an exhibit. "
         "We did not identify any material weakness in our internal control.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: t, 2020: t}))
    assert r["flags_fired"] == 0 and r["restatements"][2020]["detected"] is False


def test_significant_deficiency_only_recorded_not_flagged():
    t = "The auditors identified a significant deficiency in the accounting for leases, which was remediated."
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "ok", 2020: t}))
    assert r["restatements"][2020]["significant_deficiency_detected"] is True
    assert r["restatements"][2020]["detected"] is False and "network.restatement" not in _flags(r, 2020)


def test_missing_filing_text_is_unavailable_not_clean():
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "ok"}))
    assert r["restatements"][2020].get("status") == "unavailable"
    assert "text_signals_FY2020" in r["data_quality"]["unavailable"]
    assert any("FY2020" in d for d in r["degraded"])


def test_str_keys_after_json_roundtrip():
    st = _st({2019: _m(), 2020: _m(auditor="Beta Partners LLP")})
    st = json.loads(json.dumps({k: ({str(a): b for a, b in v.items()} if isinstance(v, dict) else v) for k, v in st.items()}))
    r = run(st)
    assert r["auditor_history"][2020]["changed"] is True


def test_accounting_adoption_restatement_and_exhibit_titles_not_flagged():
    t = ("We will adopt the standard using the full retrospective method to restate each prior reporting period presented. "
         "Amendment and Restatement of the Directors Plan is filed herewith as Exhibit 10.24.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: t, 2020: t}))
    assert not r["restatements"][2020]["detected"], r["restatements"][2020]


def test_asu_going_concern_description_not_flagged():
    t = ("The standard requires management to evaluate, for each annual and interim reporting period, whether there are "
         "conditions that raise substantial doubt about an entity's ability to continue as a going concern.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: t, 2020: t}))
    assert not r["going_concern"][2020]["detected"]


def test_implausible_fee_ratio_is_unit_error_not_signal():
    r = run(_st({2019: _m(fees=42560.0), 2020: _m(fees=41550000.0)}))
    assert r["audit_fees"][2020]["flag"] is False and "implausible" in r["audit_fees"][2020]["reason"]


def test_space_split_name_artefact_not_a_change():
    r = run(_st({2019: _m(cfo="Marc D. Hamburg"), 2020: _m(cfo="M. Arc D. H. Amburg")}))
    assert r["executive_changes"][2020]["cfo_changed"] is False


def test_deterministic():
    st = _st({2019: _m(fees=1.0), 2020: _m(fees=9.0, auditor="Beta Partners LLP")}, texts={2019: "x", 2020: GC_TEXT})
    a, b = run(st), run(st)
    assert json.dumps(a, default=str, sort_keys=True) == json.dumps(b, default=str, sort_keys=True)


# --------------------------------------------------------------------------------------
# Real cached filings
# --------------------------------------------------------------------------------------

@pytest.mark.network
def test_enron_fy1999_fy2000():
    st = company_state(CIK["ENRON"], [1998, 1999, 2000])
    st["analysis_years"] = [1999, 2000]
    r = run(st)
    # Arthur Andersen both years -> no auditor change
    assert r["auditor_history"][1999]["name"] == "Arthur Andersen LLP"
    assert r["auditor_history"][2000]["name"] == "Arthur Andersen LLP"
    assert r["auditor_history"][2000]["changed"] is False
    # CEO changed Lay -> Skilling in the FY2000 10-K signatures; CFO (Fastow) unchanged
    assert r["executive_changes"][2000]["cfo_changed"] is False
    assert r["executive_changes"][2000]["ceo_changed"] is True
    assert "network.ceo_change" in _flags(r, 2000)
    # related-party / SPE disclosure present in the notes and growing
    assert r["related_party_flags"][2000]["chars"] > 3000
    assert r["related_party_flags"][2000]["detected"] is True, r["related_party_flags"]
    assert "network.related_party" in _flags(r, 2000)
    # nothing restated / no going concern in the ORIGINAL filings
    assert not r["restatements"][2000]["detected"] and not r["going_concern"][2000]["detected"]
    assert r["severity"] == "Medium" and r["flags_fired"] == 2
    ev = [e for e in r["evidence"] if e["flag"] == "network.related_party"][0]
    assert ev["year"] == 2000 and "Related-party disclosure grew" in ev["display"]


@pytest.mark.network
def test_worldcom_fy2000_fy2001():
    st = company_state(CIK["WCOM"], [1999, 2000, 2001])
    st["analysis_years"] = [2000, 2001]
    r = run(st)
    assert r["auditor_history"][2000]["name"] == r["auditor_history"][2001]["name"] == "Arthur Andersen LLP"
    assert r["auditor_history"][2001]["changed"] is False
    assert r["executive_changes"][2001]["cfo_changed"] is False and r["executive_changes"][2001]["ceo_changed"] is False
    assert not r["restatements"][2001]["detected"] and not r["going_concern"][2001]["detected"]
    # FY2000: previous related-party section not found (0/short chars) -> recorded, never invented
    assert r["related_party_flags"][2000]["chars"] > 3000
    assert r["severity"] in ("None", "Low")


@pytest.mark.network
def test_aapl_fy2016_2020_no_changes():
    st = company_state(CIK["AAPL"], [2015, 2016, 2017, 2018, 2019, 2020], proxy=True)
    st["analysis_years"] = [2016, 2017, 2018, 2019, 2020]
    r = run(st)
    for y in st["analysis_years"]:
        assert r["auditor_history"][y]["name"] == "Ernst & Young LLP"
        assert r["auditor_history"][y]["changed"] is False
        assert r["executive_changes"][y]["ceo_changed"] is False
    assert "network.auditor_change" not in sum(r["flags_by_year"].values(), [])
    assert not any(r["going_concern"][y]["detected"] for y in st["analysis_years"])
    # CFO changed Peter Oppenheimer->Luca Maestri before FY2016? only assert what the filings show
    cfo = {y: r["executive_changes"][y]["cfo"] for y in st["analysis_years"]}
    assert cfo[2019] == cfo[2020] and "Maestri" in cfo[2020]
    # audit-fee series from proxies: growth far below 30% in every year
    fees = [r["audit_fees"][y] for y in st["analysis_years"]]
    assert all(not f["flag"] for f in fees)
    assert any(f["amount"] for f in fees)


@pytest.mark.network
def test_luckin_20f_auditor_in_filing():
    st = company_state(CIK["LUCKIN"], [2019, 2020])
    assert st["filing_metadata"], "no Luckin 20-F"
    r = run(st)
    y0 = st["analysis_years"][0]
    name = r["auditor_history"][y0]["name"]
    assert name and ("Centurion" in name or "Ernst" in name), name
    # only two 20-Fs filed in 2021: auditor change across them is reported by the data, not asserted blindly
    assert r["restatements"][y0]["detected"] is True      # restatement / material weakness text in the FY2019 20-F
    assert "network.restatement" in _flags(r, y0) and r["severity"] == "High"
    print("LUCKIN", {y: (r["auditor_history"][y]["name"], r["auditor_history"][y]["changed"], _flags(r, y)) for y in st["analysis_years"]})


@pytest.mark.network
def test_nikola_fy2020_original_10k_vs_10ka_visibility():
    """The restatement note is in the 10-K/A (filed May 2021), NOT in the original 10-K.

    The pipeline lists only original annual filings (amendments excluded, PHASE1 gap 6), so the network agent
    sees an original FY2020 10-K with no restatement.  We document both what it can and cannot see."""
    st = company_state(CIK["NIKOLA"], [2020])
    r = run(st)
    assert r["restatements"][2020]["restatement_detected"] is False, "original 10-K should carry no restatement"
    assert r["restatements"][2020]["material_weakness_detected"] is False
    assert r["going_concern"][2020]["detected"] is False
    # Feeding the 10-K/A text (what a watchlist re-run could do) makes the same rules fire.
    fl = [f for f in ea.list_filings(CIK["NIKOLA"], ["10-K/A"]) if f["filing_date"].startswith("2021-")]
    if not fl:
        pytest.skip("Nikola 10-K/A not listed")
    try:
        ta = ea.fetch_filing_text(sorted(fl, key=lambda f: f["filing_date"])[-1])
    except Exception as exc:
        pytest.skip(f"10-K/A unavailable: {exc!r}")
    meta = tp.build_filing_metadata({"form": "10-K/A"}, ta)
    r2 = run({"filing_metadata": {2020: meta}, "filing_texts": {2020: ta}, "analysis_years": [2020]})
    assert r2["restatements"][2020]["detected"] is True and "network.restatement" in _flags(r2, 2020)


@pytest.mark.network
def test_going_concern_real_filing_bbby():
    st = company_state(CIK["BBBY"], [2023])      # FYE 2023-02-25 10-K, filed 2023-06-14 (accession 0000886158-23-000059)
    assert st["filing_metadata"][2023]["accession"] == "0000886158-23-000059"
    r = run(st)
    assert r["going_concern"][2023]["detected"] is True and "network.going_concern" in _flags(r, 2023)
    assert r["severity"] == "High"
    assert "going-concern" in r["key_finding"]


@pytest.mark.network
def test_material_weakness_real_filing_khc_and_smci():
    st = company_state(CIK["KHC"], [2018])
    r = run(st)
    assert r["restatements"][2018]["material_weakness_detected"] is True
    assert "network.restatement" in _flags(r, 2018) and r["severity"] == "High"
    st = company_state(CIK["SMCI"], [2024])
    r = run(st)
    assert r["restatements"][2024]["material_weakness_detected"] is True
    assert "network.restatement" in _flags(r, 2024)


# --------------------------------------------------------------------------------------
# Base rates (report only, never tuned)
# --------------------------------------------------------------------------------------

BASE_RATE_COMPANIES = ["AAPL", "MSFT", "JNJ", "PG", "MMM", "BRKB"]
BASE_YEARS = [2015, 2016, 2017, 2018, 2019, 2020]


def compute_base_rates() -> tuple[dict, dict]:
    counts: dict[str, int] = {}
    per_company: dict[str, dict] = {}
    for name in BASE_RATE_COMPANIES:
        st = company_state(CIK[name], BASE_YEARS, proxy=True)
        st["analysis_years"] = [y for y in range(2016, 2021) if y in st["filing_metadata"]]
        r = run(st)
        per_company[name] = {y: _flags(r, y) for y in st["analysis_years"]}
        for y in st["analysis_years"]:
            for f in _flags(r, y):
                counts[f] = counts.get(f, 0) + 1
    return counts, per_company


@pytest.mark.network
def test_base_rate_table_report_only(capsys):
    counts, per_company = compute_base_rates()
    n_obs = sum(len(v) for v in per_company.values())
    with capsys.disabled():
        print(f"\nBASE RATES ({n_obs} company-years, FY2016-2020, AAPL MSFT JNJ PG MMM BRK-B)")
        for f in ("network.auditor_change", "network.cfo_change", "network.ceo_change", "network.audit_fees",
                  "network.restatement", "network.related_party", "network.going_concern"):
            print(f"  {f:28s} {counts.get(f, 0)}")
        for c, d in per_company.items():
            print("  ", c, {y: v for y, v in d.items() if v})
    assert n_obs > 0


# ---------------------------------------------------------------- excerpt trimming (synthetic strings)
def test_trim_excerpt_drops_leading_fragment_and_marks_ellipsis():
    from agents.network_agent import trim_excerpt
    out = trim_excerpt("ess of these individuals restated the financial statements for 1999 and then", 320)
    assert out.startswith("… of these") and "ess of" not in out
    assert out.endswith("…") and not out.endswith("and then...")  # trailing partial clause cut to a word


def test_trim_excerpt_long_cut_at_word_boundary():
    from agents.network_agent import trim_excerpt
    text = "aaa " + " ".join(["restatement"] * 50)
    out = trim_excerpt(text, 40, cut_start=False)
    assert out.endswith("restatement …") and len(out) <= 42


def test_trim_excerpt_keeps_doc_start_and_full_sentence():
    from agents.network_agent import trim_excerpt
    assert trim_excerpt("We restated our results.", 320, cut_start=False) == "We restated our results."
    assert trim_excerpt("", 10) == ""


# ======================================================================================
# v2 (docs/V2_CHANGELOG_text_network.md): B1 / B9 / B10 / B12 on synthetic AND real cached dev filings
# ======================================================================================

CIK.update({"VG": "0001706946", "LORDSTOWN": "0001759546"})

_FORWARD_PREFACE = ("Forward-looking statements include: our ability to timely and effectively remediate material weaknesses and maintain "
                    "effective internal control over financial reporting and disclosure and procedures; and our ability to protect our IP. "
                    "A material weakness is a deficiency, or a combination of deficiencies, in internal control over financial reporting, such "
                    "that there is a reasonable possibility that a material misstatement will not be prevented or detected on a timely basis. "
                    "Exhibit 10.4 Amended and Restated Registration Rights Agreement.")


def _tenk(preface="", rf="", item9a="", extra=""):
    return ("FORM 10-K\nFor the fiscal year ended December 31, 2020\n" + preface +
            "\nPART I\nItem 1. Business\nWe sell widgets. " + "Steady business. " * 20 + "\nItem 1A. Risk Factors\n" + rf +
            "\nItem 1B. Unresolved Staff Comments\nNone.\nPART II\nItem 9. Changes in and Disagreements\nNone.\n"
            "Item 9A. Controls and Procedures\n" + item9a + "\nItem 9B. Other Information\nNone.\n" + extra)


# ---- B1 / B12 synthetic ----------------------------------------------------------------------

def test_b1_forward_looking_boilerplate_and_definitions_do_not_flag():
    t = _tenk(preface=_FORWARD_PREFACE, item9a="Management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: t, 2020: t}))
    assert r["flags_by_year"][2020] == [] and r["severity"] == "None"
    rec = r["restatements"][2020]
    assert rec["detected"] is False and rec["n_forward_looking_ignored"] >= 1 and rec["icfr_effective"] is True


def test_b1_remediated_history_is_recorded_but_not_flagged():
    t = _tenk(item9a="In 2019 we identified two material weaknesses. During 2020 we completed the remediation of these material weaknesses and "
                     "management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "plain.", 2020: t}))
    rec = r["restatements"][2020]
    assert rec["detected"] is False and rec["remediated_history_detected"] is True and rec["n_remediated_history_hits"] >= 1
    assert "network.restatement" not in _flags(r, 2020) and "completed the remediation" in rec["remediated_history_text"]


def test_b1_b12_reported_weakness_flags_with_item_9a_evidence_and_location():
    t = _tenk(preface="Explanatory note. We identified a material weakness, as described in Item 9A.",
              rf="We may identify material weaknesses in the future.",
              item9a="Management concluded that our internal control over financial reporting was not effective as of December 31, 2020 because we "
                     "identified a material weakness in controls over revenue recognition.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "plain.", 2020: t}))
    assert "network.restatement" in _flags(r, 2020) and r["severity"] == "High"
    rec = r["restatements"][2020]
    assert rec["material_weakness_detected"] is True and rec["evidence_section"] == "item9a" and rec["icfr_not_effective"] is True
    ev = [e for e in r["evidence"] if e["flag"] == "network.restatement"][0]
    assert "Item 9A controls section" in ev["display"] and "% into the document" in ev["display"] and ev["section"] == "item9a"
    assert "Explanatory note" not in rec["text"]            # excerpt is from Item 9A, not the preface


def test_b1_restated_previously_issued_and_non_reliance_flag_but_amended_restated_does_not():
    flagged = _tenk(extra="We restated previously issued financial statements for 2018 and 2019 to correct errors. Item 4.02 non-reliance was reported.")
    r = run(_st({2019: _m(), 2020: _m()}, texts={2019: "plain.", 2020: flagged}))
    assert r["restatements"][2020]["restatement_detected"] is True and "network.restatement" in _flags(r, 2020)
    benign = _tenk(extra="Exhibit 3.1 Amended and Restated Certificate of Incorporation. Amended and Restated Registration Rights Agreement.")
    r2 = run(_st({2019: _m(), 2020: _m()}, texts={2019: "plain.", 2020: benign}))
    assert r2["restatements"][2020]["restatement_detected"] is False and _flags(r2, 2020) == []


# ---- B9 synthetic -----------------------------------------------------------------------------

def _mr(chars, source, **kw):
    return _m(rpt=chars, related_party_source=source, **kw)


def test_b9_pointer_versus_inline_is_unavailable_not_a_percentage():
    r = run(_st({2019: _mr(180, "pointer"), 2020: _mr(8219, "item13")}))
    rp = r["related_party_flags"][2020]
    assert rp["detected"] is False and rp["yoy_change_pct"] is None and rp["status"] == "pointer"
    assert "related_party_yoy_FY2020" in r["data_quality"]["unavailable"] and "network.related_party" not in _flags(r, 2020)


def test_b9_source_mismatch_is_unavailable():
    r = run(_st({2019: _mr(30000, "item13"), 2020: _mr(4000, "note")}))
    rp = r["related_party_flags"][2020]
    assert rp["status"] == "source_mismatch" and rp["yoy_change_pct"] is None and rp["detected"] is False
    assert rp["source"] == "note" and rp["prior_source"] == "item13"


def test_b9_same_source_growth_still_flags_and_threshold_unchanged():
    r = run(_st({2019: _mr(4000, "note"), 2020: _mr(6100, "note")}))               # +52.5%, >= 3,000
    rp = r["related_party_flags"][2020]
    assert rp["detected"] is True and rp["status"] == "ok" and rp["yoy_change_pct"] == 52.5 and "network.related_party" in _flags(r, 2020)
    r2 = run(_st({2019: _mr(4000, "note"), 2020: _mr(5900, "note")}))               # +47.5%: below the 50% rule
    assert r2["related_party_flags"][2020]["detected"] is False
    assert r2["thresholds"]["related_party_growth"] == 0.5 and r2["thresholds"]["related_party_min_chars"] == 3000


def test_b9_legacy_metadata_without_source_keeps_old_behaviour():
    r = run(_st({2019: _m(rpt=4000), 2020: _m(rpt=6100)}))
    assert r["related_party_flags"][2020]["detected"] is True


# ---- B10 synthetic ----------------------------------------------------------------------------

def _shell_flags(*years):
    return {y: {"is_shell": True, "spac_predecessor": True, "reason": "synthetic SPAC predecessor"} for y in years}


def test_b10_shell_year_is_never_a_baseline_for_auditor_ceo_cfo():
    meta = {2019: _m(auditor="Alpha Audit LLP", cfo="Pat Quinn", ceo="Sam Rivers"),
            2020: _m(auditor="Beta Partners LLP", cfo="Lee Moore", ceo="Kim Ford"),
            2021: _m(auditor="Beta Partners LLP", cfo="Lee Moore", ceo="Kim Ford")}
    r = run(_st(meta, filing_entity_flags=_shell_flags(2019)))
    assert r["auditor_history"][2019]["status"] == "shell" and r["executive_changes"][2019]["cfo_status"] == "shell"
    assert r["auditor_history"][2020]["status"] == "first_year" and r["auditor_history"][2020]["changed"] is False
    assert r["executive_changes"][2020]["cfo_status"] == "first_year" and r["executive_changes"][2020]["ceo_changed"] is False
    assert r["flags_by_year"][2020] == [] and r["severity"] == "None"
    # the comparison resumes normally once an operating baseline exists
    assert r["auditor_history"][2021]["status"] == "unchanged" and r["executive_changes"][2021]["cfo_status"] == "unchanged"
    # ... and a real change after the merger year IS flagged
    meta[2021] = _m(auditor="Gamma LLP", cfo="Lee Moore", ceo="Kim Ford")
    r2 = run(_st(meta, filing_entity_flags=_shell_flags(2019)))
    assert "network.auditor_change" in _flags(r2, 2021)


def test_b10_without_flags_the_shell_is_recognised_from_its_text():
    meta = {2019: _m(auditor="Alpha Audit LLP", cfo="Pat Quinn"), 2020: _m(auditor="Beta Partners LLP", cfo="Lee Moore")}
    spac = ("We are a blank check company formed to effect a merger. We have neither engaged in any operations nor generated any revenue to date. "
            + "Funds in the trust account are invested in treasury bills. " * 8)
    r = run(_st(meta, texts={2019: spac, 2020: "Operating company annual report."}))
    assert r["entity_context"][2019]["is_shell"] is True and r["entity_context"][2019]["source"] == "text"
    assert r["auditor_history"][2020]["status"] == "first_year" and _flags(r, 2020) == []


def test_b10_state_flags_win_over_text_and_absent_flags_are_tolerated():
    meta = {2019: _m(auditor="Alpha Audit LLP"), 2020: _m(auditor="Beta Partners LLP")}
    spac = ("We are a blank check company. We have neither engaged in any operations nor generated any revenue. " + "trust account " * 8)
    r = run(_st(meta, texts={2019: spac, 2020: "x"}, filing_entity_flags={2019: {"is_shell": False, "spac_predecessor": False, "reason": ""}}))
    assert r["auditor_history"][2020]["changed"] is True                       # the pipeline said "not a shell": trusted
    for bad in (None, "x", {}, {2019: None}, {"2019": {"is_shell": True}}, {2019: {}}):
        o = run_network(_st(meta, filing_entity_flags=bad))
        assert "network_result" in o and not o["network_result"].get("unavailable")


def test_b10_going_concern_in_a_shell_year_is_recorded_not_flagged():
    meta = {2019: _m(), 2020: _m()}
    gc = "The mandatory liquidation and subsequent dissolution of the Company raises substantial doubt about the Company's ability to continue as a going concern."
    r = run(_st(meta, texts={2019: gc, 2020: "plain."}, filing_entity_flags=_shell_flags(2019)))
    g = r["going_concern"][2019]
    assert g["detected"] is False and g["shell_context_detected"] is True and g["context"] == "shell"
    assert "network.going_concern" not in _flags(r, 2019)
    r2 = run(_st(meta, texts={2019: "plain.", 2020: gc}))                       # same sentence in an operating year still flags
    assert "network.going_concern" in _flags(r2, 2020)


def test_b10_related_party_shell_year_is_not_a_baseline():
    meta = {2019: _mr(9000, "note"), 2020: _mr(20000, "note")}
    r = run(_st(meta, filing_entity_flags=_shell_flags(2019)))
    assert r["related_party_flags"][2019]["status"] == "shell"
    assert r["related_party_flags"][2020]["status"] == "no_prior" and r["related_party_flags"][2020]["detected"] is False


MERGER_TEXT = ("Item 14. Withum, our independent registered public accounting firm prior to the Business Combination, was replaced by Beta Partners "
               "LLP, which audited only the accounts of the pre-merger special purpose acquisition company. Mr. Moore served as Legacy Widget's "
               "Chief Financial Officer from 2019 until the closing. The Business Combination was consummated on October 23, 2020; on October 23, 2020 "
               "(the Closing Date) the Business Combination closed.")


def test_b10_auditor_plus_cfo_change_in_a_merger_year_is_recorded_not_hard():
    meta = {2019: _m(auditor="Withum LLP", cfo="Pat Quinn", ceo="Sam Rivers"), 2020: _m(auditor="Beta Partners LLP", cfo="Lee Moore", ceo="Sam Rivers")}
    r = run(_st(meta, texts={2019: "operating.", 2020: MERGER_TEXT}, filing_entity_flags={2019: {"is_shell": False}}))
    a, e = r["auditor_history"][2020], r["executive_changes"][2020]
    assert a["changed"] is False and a["observed_change"] is True and a["context"] == "merger" and a["status"] == "merger_context"
    assert e["cfo_changed"] is False and e["cfo_observed_change"] is True and e["cfo_context"] == "merger"
    assert _flags(r, 2020) == [] and r["severity"] == "None" and r["flags_fired"] == 0
    kinds = sorted(c["kind"] for c in r["merger_context_changes"][2020])
    assert kinds == ["auditor", "cfo"]
    # the same two changes WITHOUT merger language remain the hard combination (v1 behaviour preserved)
    r2 = run(_st(meta, texts={2019: "operating.", 2020: "Quiet annual report."}))
    assert {"network.auditor_change", "network.cfo_change"} <= set(_flags(r2, 2020)) and r2["severity"] == "High"


def test_b10_a_later_year_that_merely_retells_the_merger_does_not_suppress_changes():
    retell = ("The Business Combination was consummated on October 23, 2020; on October 23, 2020 (the Closing Date) the Business Combination "
              "closed. Prior to the Business Combination, Legacy Widget's Chief Financial Officer was Pat Quinn.")
    meta = {2020: _m(auditor="Alpha Audit LLP", cfo="Pat Quinn"), 2021: _m(auditor="Beta Partners LLP", cfo="Lee Moore")}
    r = run(_st(meta, texts={2020: "x", 2021: retell}))
    assert "network.auditor_change" in _flags(r, 2021)            # the auditor change is not near any merger language and the closing year is not 2021/2022


# ---- Real cached dev filings ------------------------------------------------------------------

@pytest.mark.network
def test_real_vg_b1_forward_looking_and_remediated_history_do_not_flag_but_fy2019_does():
    st = company_state(CIK["VG"], [2017, 2018, 2019, 2020, 2021])
    r = run(st)
    # FY2021: the only 'material weakness' phrases are forward-looking boilerplate / the auditor definition; ICFR was effective
    rec21 = r["restatements"][2021]
    assert rec21["detected"] is False and rec21["material_weakness_detected"] is False
    assert rec21["n_forward_looking_ignored"] >= 1 and rec21["icfr_effective"] is True
    assert "network.restatement" not in _flags(r, 2021)
    # FY2020: remediation completed in 2020 -> recorded history, not flagged
    rec20 = r["restatements"][2020]
    assert rec20["detected"] is False and rec20["remediated_history_detected"] is True
    assert "network.restatement" not in _flags(r, 2020)
    # FY2019: a genuine reported weakness, evidence from Item 9A
    rec19 = r["restatements"][2019]
    assert rec19["material_weakness_detected"] is True and rec19["evidence_section"] == "item9a"
    assert "network.restatement" in _flags(r, 2019)
    # no 'Amended and Restated' agreement made it a restatement in any year
    assert not any(r["restatements"][y]["restatement_detected"] for y in (2017, 2018, 2019, 2020, 2021))


@pytest.mark.network
def test_real_vg_b10_spac_history_and_merger_year_comparisons():
    st = company_state(CIK["VG"], [2017, 2018, 2019, 2020, 2021])
    r = run(st)
    assert r["entity_context"][2017]["is_shell"] and r["entity_context"][2018]["is_shell"]       # Social Capital Hedosophia SPAC years
    assert 2019 not in r["entity_context"]
    assert r["auditor_history"][2018]["status"] == "shell" and r["auditor_history"][2019]["status"] == "first_year"
    assert r["executive_changes"][2019]["cfo_status"] == "first_year"
    assert not ({"network.auditor_change", "network.cfo_change", "network.ceo_change"} & set(_flags(r, 2019)))
    assert "network.cfo_change" not in _flags(r, 2018)                      # a CFO change inside the shell
    # operating-company years are still compared (real CEO / CFO transitions remain visible)
    assert r["executive_changes"][2020]["cfo_status"] == "unchanged"


@pytest.mark.network
def test_real_lordstown_and_nikola_spac_predecessor_is_not_a_baseline():
    for name, years in (("LORDSTOWN", [2019, 2020]), ("NIKOLA", [2018, 2019, 2020])):
        st = company_state(CIK[name], years)
        st["analysis_years"] = years
        r = run(st)
        assert r["entity_context"][2019]["is_shell"] is True, name
        a, e = r["auditor_history"][2020], r["executive_changes"][2020]
        assert a["status"] == "first_year" and a["changed"] is False, name
        assert e["cfo_status"] == "first_year" and e["ceo_status"] == "first_year", name
        assert _flags(r, 2020) == [] and r["severity"] == "None", name
        assert r["going_concern"][2019]["detected"] is False and r["going_concern"][2019].get("shell_context_detected") is True, name
        assert "network.going_concern" not in _flags(r, 2019), name


@pytest.mark.network
def test_real_lordstown_merger_language_marks_changes_when_the_pipeline_says_not_shell():
    """Counterfactual: even if the FY2019 filing were NOT recognised as a shell, the FY2020 text itself ('prior to the Business
    Combination', 'Legacy Lordstown's Chief Financial Officer') marks the auditor / CFO / CEO changes as merger mechanics."""
    st = company_state(CIK["LORDSTOWN"], [2019, 2020])
    st["analysis_years"] = [2019, 2020]
    st["filing_entity_flags"] = {2019: {"is_shell": False, "spac_predecessor": False, "reason": ""},
                                 2020: {"is_shell": False, "spac_predecessor": False, "reason": ""}}
    r = run(st)
    a = r["auditor_history"][2020]
    assert a["observed_change"] is True and a["context"] == "merger" and a["changed"] is False
    assert r["executive_changes"][2020]["cfo_observed_change"] is True and r["executive_changes"][2020]["cfo_context"] == "merger"
    assert not ({"network.auditor_change", "network.cfo_change", "network.ceo_change"} & set(_flags(r, 2020)))
    assert r["severity"] == "None"


@pytest.mark.network
def test_real_worldcom_b9_pointer_vs_inline_and_note_sources():
    st = company_state(CIK["WCOM"], [1997, 1998, 1999, 2000, 2001])
    r = run(st)
    for y in (1998, 1999, 2000):                           # Item 13 is a pointer in FY1998/FY1999; FY2000 is note vs pointer
        rp = r["related_party_flags"][y]
        assert rp["yoy_change_pct"] is None and rp["detected"] is False and rp["status"] in ("pointer", "source_mismatch"), (y, rp)
    assert r["related_party_flags"][2000]["source"] == "note"
    rp01 = r["related_party_flags"][2001]
    assert rp01["status"] == "ok" and rp01["source"] == rp01["prior_source"] == "note" and rp01["yoy_change_pct"] < 0   # note vs note
    flagged = [pct for y in (1998, 1999, 2000) for pct in [r["related_party_flags"][y]["yoy_change_pct"]] if pct and pct > 1000]
    assert flagged == []                                    # the v1 +4466% / +1876% artefacts are gone


@pytest.mark.network
def test_real_enron_b9_note_vs_note_growth_is_still_flagged():
    st = company_state(CIK["ENRON"], [1998, 1999, 2000])
    st["analysis_years"] = [1999, 2000]
    r = run(st)
    rp = r["related_party_flags"][2000]
    assert rp["source"] == rp["prior_source"] == "note" and rp["status"] == "ok" and rp["detected"] is True
    assert r["related_party_flags"][1999]["status"] == "pointer"        # FY1998 Item 13 was a pointer: no 940% claim for FY1999


@pytest.mark.network
@pytest.mark.parametrize("key,years", [("ENRON", [1998, 1999, 2000]), ("VG", [2019, 2020, 2021]), ("LORDSTOWN", [2019, 2020]),
                                       ("WCOM", [1999, 2000, 2001]), ("MMM", [2018, 2019, 2020])])
def test_real_results_have_no_replacement_glyphs_or_c1_controls(key, years):
    st = company_state(CIK[key], years)
    blob = json.dumps(run(st), default=str, ensure_ascii=False)
    assert "�" not in blob and not any("\x80" <= c <= "\x9f" for c in blob)


# ======================================================================================
# v3 (docs/V3_CHANGELOG_text_network.md): false-positive guards, synthetic + real dev text
# ======================================================================================

def _v3_pair(t):
    return _st({2019: _m(), 2020: _m()}, texts={2019: "plain.", 2020: t})


def test_v3_going_concern_pronouncement_and_no_doubt_do_not_flag_but_genuine_does():
    for s in ("In August 2014, the FASB issued ASU 2014-15, which is intended to define management's responsibility to evaluate whether there is substantial doubt about an organization's ability to continue as a going concern.",
              "Management assessed the Company's ability to continue as a going concern and concluded there were no conditions that gave rise to substantial doubt about the ability to continue as a going concern."):
        r = run(_v3_pair(s))
        assert not r["going_concern"][2020]["detected"] and "network.going_concern" not in _flags(r, 2020), s
    r = run(_v3_pair("Recurring losses and negative cash flows raise substantial doubt about the Company's ability to continue as a going concern."))
    assert r["going_concern"][2020]["detected"] and "network.going_concern" in _flags(r, 2020)


def test_v3_certification_investee_immaterial_and_recently_remediated_do_not_flag():
    cert = ("I have disclosed, based on my most recent evaluation of internal control over financial reporting, to the registrant's auditors: "
            "all significant deficiencies and material weaknesses in the design or operation of internal control over financial reporting.")
    investee = "In November 2003, Vail again restated its financial statements; the Company chose to reflect the impact rather than restate its previously reported financial statements."
    immaterial = "The errors were immaterial to previously issued financial statements, which have been revised; this revision is not a restatement."
    remediated = ("Although we have recently remediated a material weakness in our internal control over financial reporting, if we are unable to maintain "
                  "effective controls our stock price could decline.")
    for s in (cert, investee, immaterial, remediated):
        r = run(_v3_pair(s))
        assert "network.restatement" not in _flags(r, 2020), (s, r["restatements"][2020])


def test_v3_genuine_signals_still_flag():
    r = run(_v3_pair(MW_TEXT))
    assert "network.restatement" in _flags(r, 2020)
    r = run(_v3_pair(RS_TEXT))
    assert "network.restatement" in _flags(r, 2020)
    r = run(_v3_pair("Non-reliance: the Audit Committee concluded that the Company's previously issued financial statements should no longer be relied upon."))
    assert "network.restatement" in _flags(r, 2020)


def test_v3_item_9a_effective_overrides_weakness_mention_in_risk_factors():
    t = _tenk(rf="We identified a material weakness at an acquired business that has not been remediated.",
              item9a="Management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    r = run(_v3_pair(t))
    assert "network.restatement" not in _flags(r, 2020) and r["restatements"][2020]["remediated_history_detected"] is True


# ---- real dev filings (cached; skip when unavailable) --------------------------------------------

DEV_CIK = {"SNCR": "0001131554", "GVA": "0000861459", "EPAM": "0001352010", "BAND": "0001514416", "RAH": "0001029506", "OSIR": "0001360886",
           "USAT": "0000896429", "TEUM": "0001084384", "NSTG": "0001401708", "MITK": "0000807863"}


@pytest.mark.network
@pytest.mark.parametrize("tkr,asof,yrs", [
    ("SNCR", "2017-02-27", [2014, 2016]), ("GVA", "2019-02-22", [2016]), ("EPAM", "2017-03-01", [2014, 2015]), ("BAND", "2019-02-15", [2017]),
])
def test_v3_real_dev_asu_going_concern_text_no_longer_flags(tkr, asof, yrs):
    st = company_state(DEV_CIK[tkr], yrs, as_of=asof)
    r = run(st)
    for y in yrs:
        if y in st["filing_metadata"]:
            assert "network.going_concern" not in _flags(r, y), (tkr, y)


@pytest.mark.network
def test_v3_real_dev_investee_and_remediated_weakness_do_not_flag_but_teum_still_does():
    st = company_state(DEV_CIK["RAH"], [2003, 2004], as_of="2004-12-14")
    r = run(st)
    assert all("network.restatement" not in _flags(r, y) for y in (2003, 2004))
    st = company_state(DEV_CIK["OSIR"], [2014], as_of="2015-03-20")
    assert "network.restatement" not in _flags(run(st), 2014)
    st = company_state(DEV_CIK["USAT"], [2015, 2017], as_of="2017-08-23")
    r = run(st)
    assert "network.restatement" in _flags(r, 2015) and "network.restatement" not in _flags(r, 2017)
    st = company_state(DEV_CIK["TEUM"], [2014, 2018], as_of="2019-03-18")
    r = run(st)
    assert "network.restatement" in _flags(r, 2014) and "network.going_concern" in _flags(r, 2014) and "network.restatement" in _flags(r, 2018)
