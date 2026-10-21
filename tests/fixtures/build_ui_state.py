"""Build tests/fixtures/ui_state.json (+ a Jev variant) for the Streamlit UI tests.

SYNTHETIC: every input here is invented ("SYNTH Corp", marker numbers, filler prose). The agent OUTPUTS are produced by
running the real agents (run_quantitative, run_language, run_network, run_peer, run_temporal, run_synthesis) over those
inputs, so the structure is exact. Nothing in the file describes a real company. No LLM key and no Jev key are used, so the
main fixture is a DEGRADED run (no Claude, no Jev) exactly as the app would see it today. A separate `ui_state_jev.json`
injects SYNTHETIC Jev scores purely to exercise the Jev rendering.

Run:  python tests/fixtures/build_ui_state.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents import language_agent as la, peer_agent as pa, synthesis_agent as sa  # noqa: E402
from agents.network_agent import run_network  # noqa: E402
from agents.quantitative_agent import run_quantitative  # noqa: E402
from agents.language_agent import run_language  # noqa: E402
from agents.state import to_jsonable  # noqa: E402
from agents.temporal_agent import run_temporal  # noqa: E402
from tools import llm  # noqa: E402

NEUTRAL = ("Revenue increased because customers purchased additional units during the period and the "
           "business continued to open new locations in existing markets across several regions.")
HEDGY = "We believe revenue may increase and we expect approximately stable demand, subject to change."


def para(n_neutral, n_hedgy):
    return " ".join([NEUTRAL] * n_neutral + [HEDGY] * n_hedgy)


def filing(mdna, risk, legal="None."):
    return (
        "Item 1. Business\n\nWe sell goods. " + "Business text here. " * 20 + "\n\n"
        "Item 1A. Risk Factors\n\n" + risk + "\n\nItem 1B. Unresolved Staff Comments\n\nNone.\n\n"
        "Item 2. Properties\n\nWe lease offices.\n\nItem 3. Legal Proceedings\n\n" + legal + "\n\n"
        "Item 4. Mine Safety Disclosures\n\nNot applicable.\n\nPART II\n\n"
        "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations\n\n" + mdna +
        "\n\nItem 7A. Quantitative and Qualitative Disclosures About Market Risk\n\nNot material.\n\n"
        "Item 8. Financial Statements and Supplementary Data\n\nSee attached.\n\nItem 9. Changes in and Disagreements\n\nNone.\n")


def risk(chars):
    unit = "Our results could suffer if competitors introduce rival products or if suppliers raise their prices. "
    return (unit * (chars // len(unit) + 2))[:chars]


def fv(v):
    return {"value": float(v), "tag": "SYNTH", "unit": "USD", "source": "xbrl", "comparative": False}


def annual(by_year):
    return {"by_year": {y: {k: fv(v) for k, v in d.items()} for y, d in by_year.items()}, "missing": {}, "period_end": {},
            "source_by_year": {y: "xbrl" for y in by_year}, "unit": "USD", "warnings": []}


def year_facts(rev, cogs, sga, ni, ocf, ar, ta, ca, ppe, cl, ltd, re_, eq, dep=50):
    return dict(Revenue=rev, COGS=cogs, SGA=sga, NetIncome=ni, OperatingCashFlow=ocf, Depreciation=dep, TotalAssets=ta,
                CurrentAssets=ca, PPE=ppe, NetReceivables=ar, LongTermDebt=ltd, CurrentLiabilities=cl, RetainedEarnings=re_,
                OperatingIncome=ni * 1.4, StockholdersEquity=eq)


YEARS = [2016, 2017, 2018, 2019, 2020]
FACTS = {
    2015: year_facts(1000, 600, 100, 100, 110, 100, 1000, 400, 400, 200, 200, 300, 500),
    2016: year_facts(1050, 630, 105, 105, 112, 106, 1060, 420, 405, 205, 205, 330, 520),
    2017: year_facts(1110, 664, 110, 112, 108, 118, 1130, 450, 410, 215, 210, 370, 545),
    2018: year_facts(1200, 735, 118, 130, 90, 160, 1250, 520, 415, 235, 240, 410, 575, 45),
    2019: year_facts(1320, 820, 130, 190, 70, 260, 1350, 600, 410, 270, 270, 450, 600, 42),
    2020: year_facts(1500, 960, 150, 300, 50, 420, 1500, 720, 400, 300, 300, 500, 620, 40),
}
LEGAL_NEW = "A purported class action was filed against the company in 2020 alleging misstatements."
TEXTS = {y: filing(para(60, h), risk(r), "None." if y < 2020 else LEGAL_NEW)
         for y, h, r in [(2015, 1, 20000), (2016, 1, 20500), (2017, 2, 21000), (2018, 4, 24000), (2019, 8, 31000),
                         (2020, 14, 46000)]}
META = {
    2015: dict(auditor="Alpha Audit LLP", cfo="Pat Quinn", ceo="Sam Rivers", audit_fees=1000000.0, related_party_chars=2000),
    2016: dict(auditor="Alpha Audit LLP", cfo="Pat Quinn", ceo="Sam Rivers", audit_fees=1050000.0, related_party_chars=2100),
    2017: dict(auditor="Alpha Audit LLP", cfo="Pat Quinn", ceo="Sam Rivers", audit_fees=1100000.0, related_party_chars=2200),
    2018: dict(auditor="Alpha Audit LLP", cfo="Lee Moran", ceo="Sam Rivers", audit_fees=1500000.0, related_party_chars=4000),
    2019: dict(auditor="Beta Partners LLP", cfo="Lee Moran", ceo="Sam Rivers", audit_fees=2100000.0, related_party_chars=7000),
    2020: dict(auditor="Beta Partners LLP", cfo="Kim Alvarez", ceo="Sam Rivers", audit_fees=2900000.0, related_party_chars=12000),
}
for m in META.values():
    m.update(audit_fee_source="filing", signatures_found=True)


def _peer(i):
    return {"ticker": f"SYNP{i}", "name": f"Synthetic Peer {i}", "cik": f"{1000 + i:010d}", "fiscal_year": 2020, "tier": 4,
            "year_offset": 0}


def _peer_facts(i):
    def y(r, a):
        return {"Revenue": r, "COGS": r * (0.58 + 0.01 * i), "NetReceivables": a, "OperatingCashFlow": r * (0.15 + 0.005 * i),
                "LongTermDebt": 200, "CurrentDebt": 0, "StockholdersEquity": 400 + 10 * i, "NetIncome": r * (0.08 + 0.004 * i),
                "TotalAssets": 1000}
    return annual({2019: y(950, 95 + 5 * i), 2020: y(1000, 100 + 5 * i)})


def build():
    llm.llm_available = lambda: False
    llm.llm_json = lambda *a, **k: None
    state = {"ticker": "SYNTH", "company_name": "SYNTH Corp (synthetic demo data, not a real company)", "cik": "0000000001",
             "analysis_years": YEARS, "focus_year": 2020, "as_of": "2021-03-01",
             "analysis_timestamp": "2021-03-01T00:00:00+00:00",
             "annual_facts": annual(FACTS), "filing_texts": TEXTS, "filing_metadata": META,
             "peer_companies": [_peer(i) for i in range(6)], "degraded": [], "warnings": ["SYNTHETIC fixture"],
             "agent_trace": [], "previous_risk_grade": "", "risk_changed": False, "error": ""}

    def merge(upd):
        for k, v in upd.items():
            if k in ("degraded", "agent_trace", "warnings"):
                state[k] = list(state.get(k, [])) + list(v)
            else:
                state[k] = v

    for fn in (run_quantitative, run_language, run_network):
        merge(fn(state))
    pa._facts_for = lambda cik, years, as_of: (annual(FACTS) if cik == "0000000001" else _peer_facts(int(cik) - 1000))
    merge(pa.run_peer(state))
    merge(run_temporal(state))
    off = {a_: {"evidence_strength": "Unavailable", "confidence_score": None, "material_change": None, "jev_latency_ms": 0,
                "available": False, "error": "JEV_API_KEY not set", "model": None} for a_ in sa.ALL_AGENTS}
    sa.jev_scorer.score_agents = lambda *a, **k: off
    sa.llm_text = lambda *a, **k: None
    merge(sa.run_synthesis(state))
    state["annual_facts"] = {"note": "omitted from UI fixture (large)"}
    state["filing_texts"] = {}
    return state


def main():
    out = Path(__file__).parent
    s = build()
    js = to_jsonable(s)
    js["_fixture_note"] = "SYNTHETIC: invented inputs run through the real agents (no LLM, no Jev). Not a real company."
    (out / "ui_state.json").write_text(json.dumps(js, indent=1, default=str), encoding="utf-8")
    j = copy.deepcopy(js)
    j["jev_available"] = True
    j["jev_scores"] = {a: {"evidence_strength": st, "confidence_score": c, "material_change": mc, "jev_latency_ms": 420,
                           "available": True, "error": None, "model": "SYNTHETIC"}
                       for a, st, c, mc in [("quantitative", "Strong", 86.0, True), ("language", "Suggestive", 58.0, True),
                                            ("network", "Definitive", 92.0, False), ("peer", "Insufficient", 31.0, False),
                                            ("temporal", "Strong", 77.0, True)]}
    j["_fixture_note"] += " Jev scores in this variant are INVENTED for rendering tests."
    (out / "ui_state_jev.json").write_text(json.dumps(j, indent=1, default=str), encoding="utf-8")
    print("grade", s.get("risk_grade"), "| guns", len(s.get("smoking_guns", [])), "| degraded", s.get("degraded"))


if __name__ == "__main__":
    main()
