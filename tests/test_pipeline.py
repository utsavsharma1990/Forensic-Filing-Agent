"""Tests for graph/pipeline.py and tools/config.py.

Offline tests use STUBBED fetch/agents (synthetic structure-only fixtures: flag names from CONTRACTS section 4,
arbitrary dates/ids, nothing resembling real financial data). ``network``-marked tests run the REAL pipeline against
cached/live SEC EDGAR data (AAPL, Enron, Luckin) and assert structural invariants, not evaluation outcomes.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph import pipeline as pl  # noqa: E402
from tools import config as cfg  # noqa: E402
from tools.edgar_api import EdgarNotFound  # noqa: E402

pytestmark = []


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "JEV_API_KEY", "TYPESAFE_API_KEY", "FORENSIC_EXCLUDE_FLAGS"):
        monkeypatch.delenv(k, raising=False)


# ----------------------------------------------------------------------------------------- stubs
def _filing(fy, filed=None, form="10-K"):
    return {"accession": f"0000000000-{fy % 100:02d}-000001", "form": form, "filing_date": filed or f"{fy + 1}-02-15",
            "report_date": f"{fy}-12-31", "fiscal_year": fy, "primary_document": "x.htm", "cik": "0000000001",
            "document_url": "https://example.invalid/x.htm"}


async def _stub_fetch(state):
    years = [2018, 2019, 2020]
    return {"company_name": "Stub Co", "cik": "0000000001", "as_of": "2021-06-30", "analysis_years": years,
            "focus_year": 2020, "annual_facts": {}, "xbrl_data": {}, "filing_texts": {y: "t" for y in [2017] + years},
            "filing_metadata": {y: {"filing_date": f"{y + 1}-02-15"} for y in [2017] + years},
            "filings": [_filing(y) for y in [2017] + years], "peer_companies": [], "peer_reason": "stub",
            "fetch_info": {}, "warnings": ["fetch: stub warning"], "degraded": ["fetch_data: stub degraded"],
            "analysis_timestamp": "2021-06-30T00:00:00+00:00", "error": ""}


def _stub_agent(name, flags_by_year, sleep=0.0, severity="Low", extra_degraded=()):
    def fn(state):
        started = time.time()
        time.sleep(sleep)
        res = {"severity": severity, "flags_fired": sum(len(v) for v in flags_by_year.values()),
               "flags_by_year": copy.deepcopy(flags_by_year), "focus_year": state.get("focus_year"),
               "key_finding": f"{name} stub finding", "evidence": [
                   {"flag": f, "year": y, "metric": f.split(".")[1], "value": 1.0, "display": f"{f} fired", "numbers": [1.0]}
                   for y, fl in flags_by_year.items() for f in fl],
               "data_quality": {"unavailable": {}}, "degraded": list(extra_degraded)}
        return {f"{name}_result": res, "degraded": [f"{name}: stub degraded"] + list(extra_degraded),
                "agent_trace": [{"agent": name, "status": "ok", "started": started, "duration_ms": int((time.time() - started) * 1000),
                                 "summary": "stub", "degraded": []}]}
    return fn


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(pl, "_fetch_data_impl", _stub_fetch)

    def install(sleep=0.0, flags=None):
        flags = flags or {}
        for n in pl.AGENT_NODES:
            monkeypatch.setattr(pl, pl._AGENT_FUNC[n], _stub_agent(n, flags.get(n, {}), sleep), raising=True)
    install()
    return install


def run(**kw):
    return asyncio.run(pl.analyze_company("STUB", 3, **kw))


# ----------------------------------------------------------------------------------------- graph structure
def test_graph_exports_and_node_names():
    g = pl.forensic_agent.get_graph()
    names = set(g.nodes)
    assert {"fetch_data", "run_quantitative", "run_language", "run_network", "run_peer", "run_temporal",
            "run_synthesis", "handle_error"} <= names
    assert pl.pipeline is not None and hasattr(pl.forensic_agent, "ainvoke")
    edges = {(e.source, e.target) for e in g.edges}
    for n in ("run_quantitative", "run_language", "run_network", "run_peer"):
        assert ("fetch_data", n) in edges and (n, "run_temporal") in edges
    assert ("run_temporal", "run_synthesis") in edges and ("run_synthesis", "__end__") in edges
    assert ("fetch_data", "handle_error") in edges and ("handle_error", "__end__") in edges


# ----------------------------------------------------------------------------------------- parallelism & reducers
def test_agents_1_to_4_run_in_parallel(stubbed):
    stubbed(sleep=0.4)
    t0 = time.time()
    st = run()
    wall = time.time() - t0
    timings = {t["node"]: t for t in st["node_timings"]}
    four = [timings[n] for n in pl.AGENT_NODES]
    # all four intervals overlap: latest start < earliest end
    assert max(t["start_ts"] for t in four) < min(t["end_ts"] for t in four)
    # the agents' own trace entries overlap too (started + duration_ms)
    tr = {t["agent"]: t for t in st["agent_trace"] if t["agent"] in pl.AGENT_NODES}
    assert len(tr) == 4
    assert max(t["started"] for t in tr.values()) < min(t["started"] + t["duration_ms"] / 1000 for t in tr.values())
    assert wall < 1.3  # serial execution of the four 0.4 s agents alone would take >= 1.6 s
    # temporal starts only after the slowest agent finished; synthesis after temporal
    assert timings["temporal"]["start_ts"] >= max(t["end_ts"] for t in four) - 1e-3
    assert timings["synthesis"]["start_ts"] >= timings["temporal"]["end_ts"] - 1e-3


def test_reducers_merge_lists(stubbed):
    st = run()
    agents = [t["agent"] for t in st["agent_trace"]]
    assert agents[0] == "fetch_data"
    assert {"quantitative", "language", "network", "peer", "temporal", "synthesis"} <= set(agents)
    for n in pl.AGENT_NODES:
        assert f"{n}: stub degraded" in st["degraded"]
    assert "fetch_data: stub degraded" in st["degraded"]
    assert "fetch: stub warning" in st["warnings"]
    assert len(st["degraded"]) == len(set(st["degraded"]))          # de-duplicated for the caller
    assert st["analysis_years"] == [2018, 2019, 2020] and st["focus_year"] == 2020
    assert st["risk_grade"] in ("Low", "Medium", "High", "Critical")
    assert st["total_ms"] > 0 and st["error"] == ""


def test_full_stubbed_run_uses_real_temporal_and_synthesis(stubbed):
    stubbed(flags={"quantitative": {2019: ["quantitative.dso_growth"], 2020: ["quantitative.dso_growth", "quantitative.accruals"]},
                   "network": {2020: ["network.cfo_change", "network.audit_fees"]}})
    st = run()
    assert st["temporal_result"]["timeline"] and st["forensic_timeline"]
    assert [e["year"] for e in st["forensic_timeline"]][-1] == 2020
    assert st["suspicion_score"] == st["temporal_result"]["suspicion_score"]
    assert st["agent_severity"].keys() >= {"quantitative", "network"}
    assert st["grade_rationale"]


# ----------------------------------------------------------------------------------------- errors
def test_fatal_fetch_error_routes_to_handle_error(monkeypatch):
    async def bad(state):
        return {"error": "company not found: 'ZZZZ'", "warnings": [], "degraded": ["fetch_data: company not found"]}
    monkeypatch.setattr(pl, "_fetch_data_impl", bad)
    called = []
    for n in pl.AGENT_NODES:
        monkeypatch.setattr(pl, pl._AGENT_FUNC[n], lambda s, n=n: called.append(n) or {}, raising=True)
    st = run()
    assert st["risk_grade"] == "Unknown" and "company not found" in st["error"]
    assert called == []                                           # no agent ran
    assert st["smoking_guns"] == [] and st["forensic_timeline"] == []
    assert any(t["agent"] == "handle_error" for t in st["agent_trace"])
    assert "temporal_result" not in st or not st.get("temporal_result")


def test_fetch_crash_becomes_clean_fatal_error(monkeypatch):
    async def boom(state):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(pl, "_fetch_data_impl", boom)
    st = run()
    assert st["risk_grade"] == "Unknown" and "kaboom" in st["error"]


def test_agent_exception_does_not_abort(stubbed, monkeypatch):
    def explode(state):
        raise ValueError("agent bug")
    monkeypatch.setattr(pl, "run_language", explode)
    st = run()
    assert st["language_result"]["unavailable"] is True and "agent bug" in st["language_result"]["error"]
    assert st["risk_grade"] in ("Low", "Medium", "High", "Critical")
    assert any("language" in d for d in st["degraded"])
    assert any(t["agent"] == "language" and t["status"] == "error" for t in st["agent_trace"])


def test_agent_returning_garbage_is_unavailable(stubbed, monkeypatch):
    monkeypatch.setattr(pl, "run_peer", lambda s: {"nothing": 1})
    st = run()
    assert st["peer_result"]["unavailable"] is True


def test_company_not_found_end_to_end_offline(monkeypatch):
    def nf(*a, **k):
        raise EdgarNotFound("no such ticker")
    monkeypatch.setattr(pl.edgar_api, "resolve_company", nf)
    st = asyncio.run(pl.analyze_company("NOSUCH"))
    assert st["risk_grade"] == "Unknown" and "company not found" in st["error"]


def test_no_annual_filings_before_as_of_is_fatal(monkeypatch):
    monkeypatch.setattr(pl.edgar_api, "resolve_company", lambda t, c=None: {"ticker": t, "cik": "0000000001", "name": "X", "sic": "1000"})
    monkeypatch.setattr(pl.edgar_api, "list_annual_filings", lambda cik, as_of=None: [])
    st = asyncio.run(pl.analyze_company("XXX", as_of="1999-01-01"))
    assert st["risk_grade"] == "Unknown" and "no annual filings" in st["error"]


def test_requested_end_year_without_filing_is_fatal(monkeypatch):
    monkeypatch.setattr(pl.edgar_api, "resolve_company", lambda t, c=None: {"ticker": t, "cik": "0000000001", "name": "X", "sic": "1000"})
    monkeypatch.setattr(pl.edgar_api, "list_annual_filings", lambda cik, as_of=None: [_filing(2019), _filing(2018)])
    st = asyncio.run(pl.analyze_company("XXX", end_year=2021, as_of="2022-01-01"))
    assert st["risk_grade"] == "Unknown" and "FY2021" in st["error"]


def test_partial_failures_are_warnings_not_fatal(monkeypatch):
    """Real fetch_data with every I/O function stubbed: one year's text fails, peers empty, facts raise."""
    fl = [_filing(2020), _filing(2019), _filing(2018), _filing(2017)]
    monkeypatch.setattr(pl.edgar_api, "resolve_company", lambda t, c=None: {"ticker": t, "cik": "0000000001", "name": "Stub Inc", "sic": "3571"})
    monkeypatch.setattr(pl.edgar_api, "list_annual_filings", lambda cik, as_of=None: fl)
    monkeypatch.setattr(pl.edgar_api, "list_filings", lambda cik, forms, as_of=None: [])

    def txt(f, max_chars=None):
        if f["fiscal_year"] == 2019:
            raise RuntimeError("timeout")
        return "Some filing text."
    monkeypatch.setattr(pl.edgar_api, "fetch_filing_text", txt)
    monkeypatch.setattr(pl.edgar_api, "get_companyfacts", lambda cik: (_ for _ in ()).throw(RuntimeError("facts down")))
    import tools.peer_finder as pf

    class _PL(list):
        reason = "stubbed: no peers"
    monkeypatch.setattr(pf, "find_peers", lambda *a, **k: _PL())
    for n in pl.AGENT_NODES:
        monkeypatch.setattr(pl, pl._AGENT_FUNC[n], _stub_agent(n, {}), raising=True)
    st = asyncio.run(pl.analyze_company("STUB", 3, end_year=2020, as_of="2021-06-30"))
    assert not st["error"] and st["risk_grade"] != "Unknown"
    assert st["analysis_years"] == [2018, 2019, 2020] and st["fetch_info"]["baseline_year"] == 2017
    assert 2019 not in st["filing_texts"] and {2017, 2018, 2020} <= set(st["filing_texts"])
    assert 2019 in st["filing_metadata"]                           # minimal metadata keeps the filing date
    assert any("FY2019" in w and "timeout" in w for w in st["warnings"])
    assert any("facts down" in w for w in st["warnings"]) and any("no peers" in w for w in st["warnings"])
    assert st["peer_companies"] == [] and st["peer_reason"] == "stubbed: no peers"
    assert any("no peer group" in d for d in st["degraded"])


# ----------------------------------------------------------------------------------------- callbacks
EXPECTED = {"fetch_data": "Fetching SEC EDGAR data...", "quantitative": "Running quantitative forensics...",
            "language": "Analyzing filing language...", "network": "Checking auditor and executive history...",
            "peer": "Comparing against peer group...", "temporal": "Building temporal intelligence...",
            "jev": "Running Jev confidence scoring...", "synthesis": "Synthesizing final verdict..."}


def test_progress_events_and_messages(stubbed):
    events, threads = [], set()

    def cb(ev):
        events.append(ev)
        threads.add(threading.get_ident())
    async def go():
        main = threading.get_ident()
        st = await pl.analyze_company("STUB", 3, progress_callback=cb)
        return st, main
    st, main = asyncio.run(go())
    assert threads == {main}                                        # always delivered on the event-loop thread
    for ev in events:
        assert set(ev) >= {"node", "status", "message", "elapsed_ms"}
        assert ev["status"] in ("start", "done", "error", "jev")
        assert ev["message"] == EXPECTED[ev["node"]]
    by = {(e["node"], e["status"]) for e in events}
    for n in EXPECTED:
        if n == "jev":
            assert ("jev", "jev") in by
        else:
            assert (n, "start") in by and (n, "done") in by
    ms = [e["elapsed_ms"] for e in events]
    assert ms == sorted(ms)
    order = [e["node"] for e in events if e["status"] == "start"]
    assert order[0] == "fetch_data" and order[-2:] == ["temporal", "synthesis"]


def test_callback_exceptions_are_swallowed(stubbed):
    def bad(ev):
        raise RuntimeError("ui exploded")
    st = run(progress_callback=bad)
    assert st["risk_grade"] in ("Low", "Medium", "High", "Critical") and not st["error"]


def test_fatal_error_emits_error_event(monkeypatch):
    async def bad(state):
        return {"error": "x", "warnings": [], "degraded": []}
    monkeypatch.setattr(pl, "_fetch_data_impl", bad)
    evs = []
    run(progress_callback=evs.append)
    assert ("fetch_data", "error") in {(e["node"], e["status"]) for e in evs}


def test_async_callback_is_tolerated(stubbed):
    seen = []

    async def acb(ev):
        seen.append(ev["node"])
    run(progress_callback=acb)
    assert "fetch_data" in seen


def test_sync_wrapper_inside_running_loop(stubbed):
    async def inner():
        return pl.analyze_company_sync("STUB", 3)
    st = asyncio.run(inner())
    assert st["risk_grade"] in ("Low", "Medium", "High", "Critical")
    assert pl.analyze_company_sync("STUB", 3)["focus_year"] == 2020


def test_explicit_thread_id_keeps_checkpoints(stubbed):
    st = asyncio.run(pl.analyze_company("STUB", 3, thread_id="keep-me"))
    snap = pl.forensic_agent.get_state({"configurable": {"thread_id": "keep-me"}})
    assert snap.values["risk_grade"] == st["risk_grade"]


# ----------------------------------------------------------------------------------------- pure fetch helpers
def test_select_years_defaults_and_baseline():
    fl = [_filing(y) for y in range(2012, 2021)]
    s = pl.select_years(fl, 5, None, "2021-12-31")
    assert s["end_year"] == 2020 and s["analysis_years"] == [2016, 2017, 2018, 2019, 2020]
    assert s["baseline_year"] == 2015 and s["facts_years"] == [2015, 2016, 2017, 2018, 2019, 2020]


def test_select_years_end_year_and_short_history():
    fl = [_filing(2019), _filing(2018)]
    s = pl.select_years(fl, 5, 2019, "2021-12-31")
    assert s["analysis_years"] == [2018, 2019] and s["baseline_year"] is None
    assert s["facts_years"] == [2017, 2018, 2019]                   # facts still ask for the comparative year
    assert any("only 2 of 5" in w for w in s["warnings"])
    assert pl.select_years(fl, 5, 2022, "2021-12-31")["error"]
    assert pl.select_years([], 5, None, "2021-12-31")["error"]


def test_select_years_one_original_per_fiscal_year_and_gaps():
    a, b = _filing(2019, "2020-02-01"), _filing(2019, "2020-06-01", form="10-K405")
    b["accession"] = "0000000000-20-000009"
    s = pl.select_years([b, a, _filing(2017)], 3, 2019, "2021-12-31")
    assert s["original"][2019]["accession"] == a["accession"]       # earliest filed wins
    assert s["analysis_years"] == [2017, 2019]
    assert any("FY2018" in w for w in s["warnings"]) and any("2 annual filings" in w for w in s["warnings"])


def test_match_proxies_window_and_exclusivity():
    ann = {2019: {"filing_date": "2019-10-31"}, 2020: {"filing_date": "2020-10-30"}}
    prox = [{"accession": "p1", "filing_date": "2020-01-10"}, {"accession": "p2", "filing_date": "2021-01-05"},
            {"accession": "p3", "filing_date": "2016-01-01"}]
    m = pl.match_proxies(ann, prox)
    assert m[2019]["accession"] == "p1" and m[2020]["accession"] == "p2" and len(m) == 2
    assert pl.match_proxies({2019: {"filing_date": "2019-10-31"}}, [{"accession": "x", "filing_date": "2021-01-05"}]) == {}


# ----------------------------------------------------------------------------------------- tools.config
def test_get_excluded_flags_env_and_override(monkeypatch):
    assert cfg.get_excluded_flags() == []
    monkeypatch.setenv("FORENSIC_EXCLUDE_FLAGS", " language.passive_voice, peer.roa ,,language.passive_voice")
    assert cfg.get_excluded_flags() == ["language.passive_voice", "peer.roa"]
    assert cfg.get_excluded_flags(["x.y"]) == ["x.y"]
    assert cfg.get_excluded_flags([]) == []                         # explicit empty override beats the env
    assert cfg.get_excluded_flags("a.b, c.d") == ["a.b", "c.d"]


@pytest.mark.parametrize("flags,expected", [
    ([], "None"), (["language.hedging"], "Low"), (["language.hedging", "language.specificity"], "Medium"),
    (["a.1", "a.2", "a.3"], "High"), (["quantitative.beneish"], "High"), (["network.going_concern"], "High"),
    (["network.restatement"], "High"), (["network.auditor_change"], "Low"),
    (["network.auditor_change", "network.cfo_change"], "High"), (["network.cfo_change", "network.audit_fees"], "Medium"),
    (["peer.roa", "peer.dso"], "Medium"), (["peer.roa", "peer.dso", "peer.gross_margin"], "High"),
])
def test_recompute_severity_truth_table(flags, expected):
    assert cfg.recompute_severity({"focus_year": 2020, "flags_by_year": {2019: ["quantitative.beneish"], 2020: flags}}) == expected
    assert cfg.recompute_severity({"focus_year": "2020", "flags_by_year": {"2020": flags}}) == expected   # str keys too


def test_recompute_severity_unavailable_and_malformed():
    assert cfg.recompute_severity({"unavailable": True, "focus_year": 2020, "flags_by_year": {2020: ["quantitative.beneish"]}}) == "None"
    assert cfg.recompute_severity({}) == "None" and cfg.recompute_severity(None) == "None"


def test_apply_exclusions_identity_when_nothing_to_remove():
    res = {"severity": "Low", "flags_fired": 1, "flags_by_year": {2020: ["language.hedging"]}, "focus_year": 2020,
           "evidence": [{"flag": "language.hedging"}], "key_finding": "k"}
    snapshot = json.dumps(res, sort_keys=True)
    assert cfg.apply_exclusions(res, []) is res
    assert cfg.apply_exclusions(res, ["language.passive_voice"]) is res          # flag absent -> same object
    assert cfg.apply_exclusions({"unavailable": True}, ["language.passive_voice"]) == {"unavailable": True}
    assert json.dumps(res, sort_keys=True) == snapshot


def test_apply_exclusions_removes_and_recomputes():
    res = {"severity": "High", "flags_fired": 4, "focus_year": 2020, "key_finding": "k",
           "flags_by_year": {2019: ["language.passive_voice"], 2020: ["language.passive_voice", "language.hedging", "language.new_legal"]},
           "evidence": [{"flag": "language.passive_voice", "year": 2020}, {"flag": "language.hedging", "year": 2020}]}
    orig = copy.deepcopy(res)
    out = cfg.apply_exclusions(res, ["language.passive_voice"])
    assert res == orig                                                # input untouched
    assert out["flags_by_year"] == {2019: [], 2020: ["language.hedging", "language.new_legal"]}
    assert out["flags_fired"] == 2 and out["severity"] == "Medium" and out["severity_before_exclusion"] == "High"
    assert [e["flag"] for e in out["evidence"]] == ["language.hedging"]
    assert out["removed_flags"] == {2019: ["language.passive_voice"], 2020: ["language.passive_voice"]}
    assert "excluded by configuration" in out["key_finding"]


def test_apply_exclusions_peer_outliers():
    res = {"severity": "High", "flags_fired": 3, "focus_year": 2020, "outlier_metrics": ["roa", "dso", "gross_margin"],
           "flags_by_year": {2020: ["peer.roa", "peer.dso", "peer.gross_margin"]}, "evidence": [], "key_finding": "k"}
    out = cfg.apply_exclusions(res, ["peer.roa"])
    assert out["outlier_metrics"] == ["dso", "gross_margin"] and out["flags_fired"] == 2 and out["severity"] == "Medium"


def test_pipeline_default_leaves_results_identical_and_exclusion_flows_to_temporal(stubbed):
    flags = {"language": {2019: ["language.passive_voice"], 2020: ["language.passive_voice", "language.hedging"]}}
    stubbed(flags=flags)
    base = run()
    base_json = json.dumps(base["language_result"], sort_keys=True, default=str)
    assert base["language_result"]["flags_by_year"][2020] == ["language.passive_voice", "language.hedging"]
    assert "excluded_flags" not in base["language_result"]
    assert run(exclude_flags=[])["language_result"] == base["language_result"]           # explicit empty == default
    ex = run(exclude_flags=["language.passive_voice"])
    lr = ex["language_result"]
    assert lr["flags_by_year"][2020] == ["language.hedging"] and lr["severity"] == "Low"
    assert ex["exclude_flags"] == ["language.passive_voice"]
    # temporal read the FILTERED result: 10 points per remaining flag instead of 20 in FY2020
    t_base = {e["year"]: e for e in base["forensic_timeline"]}
    t_ex = {e["year"]: e for e in ex["forensic_timeline"]}
    assert t_base[2020]["suspicion_score"] == 20 and t_ex[2020]["suspicion_score"] == 10
    assert t_base[2019]["suspicion_score"] == 10 and t_ex[2019]["suspicion_score"] == 0
    assert any("excluded flags removed" in w for w in ex["warnings"])
    # the other three agents are untouched
    assert ex["quantitative_result"] == base["quantitative_result"]
    assert json.dumps(base["language_result"], sort_keys=True, default=str) == base_json


def test_pipeline_env_var_exclusion(stubbed, monkeypatch):
    stubbed(flags={"language": {2020: ["language.passive_voice"]}})
    monkeypatch.setenv("FORENSIC_EXCLUDE_FLAGS", "language.passive_voice")
    st = run()
    assert st["language_result"]["flags_by_year"][2020] == [] and st["language_result"]["severity"] == "None"
    assert run(exclude_flags=[])["language_result"]["severity"] == "Low"                 # per-call override beats env


def test_structural_flag_exclusion_is_warned(stubbed):
    st = run(exclude_flags=["quantitative.beneish"])
    assert any("NOT propagated" in w for w in st["warnings"])


# ----------------------------------------------------------------------------------------- live (cached) integration
CASES = {
    "AAPL": dict(ticker="AAPL", as_of="2020-10-30", end_year=2020),
    "ENRON": dict(ticker="ENRNQ", cik="0001024401", as_of="2001-04-02", end_year=2000),
    "LUCKIN": dict(ticker="LKNCY", cik="0001767582", as_of="2021-06-30", end_year=2019),
}
GRADES = ("Low", "Medium", "High", "Critical")


@pytest.fixture(scope="module")
def live_results():
    cache: dict = {}

    def get(name):
        if name not in cache:
            kw = dict(CASES[name])
            t = kw.pop("ticker")
            evs: list = []
            t0 = time.time()
            st = asyncio.run(pl.analyze_company(t, 5, progress_callback=evs.append, **kw))
            cache[name] = (st, evs, time.time() - t0)
        return cache[name]
    return get


def _common_invariants(st, evs):
    assert not st["error"], st["error"]
    assert st["risk_grade"] in GRADES
    assert st["grade_rationale"] and st["final_narrative"]
    assert set(st["agent_severity"]) == {"quantitative", "language", "network", "peer"}
    assert all(st[f"{a}_result"] for a in ("quantitative", "language", "network", "peer", "temporal"))
    assert st["forensic_timeline"] and st["forensic_timeline"][-1]["year"] == st["focus_year"]
    assert st["jev_available"] is False and any(d.startswith("jev:") for d in st["degraded"])
    assert any("ANTHROPIC_API_KEY" in d for d in st["degraded"])
    assert len(st["degraded"]) == len(set(st["degraded"]))
    assert {e["node"] for e in evs} >= {"fetch_data", "quantitative", "language", "network", "peer", "temporal", "jev", "synthesis"}
    json.dumps(st, default=str)                                       # state is serialisable
    for y in st["analysis_years"]:                                    # point-in-time: nothing filed after as_of
        assert st["filing_metadata"][y]["filing_date"] <= st["as_of"]
    assert all(f["filing_date"] <= st["as_of"] for f in st["filings"])


@pytest.mark.network
def test_live_aapl_2020(live_results):
    st, evs, _ = live_results("AAPL")
    _common_invariants(st, evs)
    assert st["analysis_years"] == [2016, 2017, 2018, 2019, 2020] and st["focus_year"] == 2020
    assert st["fetch_info"]["baseline_year"] == 2015 or st["fetch_info"]["baseline_year"] is None
    assert st["company_name"].upper().startswith("APPLE")
    assert len(st["peer_companies"]) >= 3
    assert st["filing_metadata"][2020]["auditor"] and "Ernst" in st["filing_metadata"][2020]["auditor"]


@pytest.mark.network
def test_live_enron_2000_pre_xbrl(live_results):
    st, evs, _ = live_results("ENRON")
    _common_invariants(st, evs)
    assert st["focus_year"] == 2000 and 2000 in st["analysis_years"]
    assert st["xbrl_data"] == {} and st["fetch_info"]["has_companyfacts"] is False
    assert st["annual_facts"]["source_by_year"][2000] == "statement-table"
    assert st["peer_companies"] == [] and st["peer_reason"]
    assert st["peer_result"]["unavailable"] is True
    assert "Andersen" in (st["filing_metadata"][2000]["auditor"] or "")


@pytest.mark.network
def test_live_luckin_2019_20f_cny(live_results):
    st, evs, _ = live_results("LUCKIN")
    _common_invariants(st, evs)
    assert st["focus_year"] == 2019 and st["analysis_years"] == [2019]
    assert st["annual_facts"]["unit"] == "CNY"
    assert st["filings"][-1]["form"] == "20-F"
    assert st["peer_result"]["unavailable"] is True


@pytest.mark.network
@pytest.mark.parametrize("case", ["AAPL", "ENRON", "LUCKIN"])
def test_live_recompute_severity_matches_agents_and_exclusion_identity(live_results, case):
    st, _, _ = live_results(case)
    for a in ("quantitative", "language", "network", "peer"):
        res = st[f"{a}_result"]
        assert cfg.recompute_severity(res) == res["severity"], (case, a, res["flags_by_year"], res["severity"])
        assert cfg.apply_exclusions(res, []) is res
        assert json.dumps(cfg.apply_exclusions(res, ["no.such_flag"]), sort_keys=True, default=str) == json.dumps(res, sort_keys=True, default=str)


@pytest.mark.network
def test_live_aapl_no_passive_variant_changes_only_language(live_results):
    base, _, _ = live_results("AAPL")
    kw = dict(CASES["AAPL"])
    t = kw.pop("ticker")
    ex = asyncio.run(pl.analyze_company(t, 5, exclude_flags=["language.passive_voice"], **kw))
    assert ex["exclude_flags"] == ["language.passive_voice"]
    for a in ("quantitative", "network", "peer"):
        assert json.dumps(ex[f"{a}_result"], sort_keys=True, default=str) == json.dumps(base[f"{a}_result"], sort_keys=True, default=str)
    lb, le = base["language_result"], ex["language_result"]
    assert all("language.passive_voice" not in v for v in le["flags_by_year"].values())
    assert le["severity"] == cfg.recompute_severity(le)
    assert le["flags_fired"] == lb["flags_fired"] - sum("language.passive_voice" in v for v in lb["flags_by_year"].values())


def test_peer_node_restores_peer_reason(monkeypatch, stubbed):
    seen = {}

    def peer(state):
        seen["reason"] = getattr(state.get("peer_companies"), "reason", None)
        return _stub_agent("peer", {})(state)
    monkeypatch.setattr(pl, "run_peer", peer)
    run()
    assert seen["reason"] == "stub"


def test_short_filing_text_warns(monkeypatch):
    monkeypatch.setattr(pl.edgar_api, "fetch_filing_text", lambda f, max_chars=None: "tiny")
    r = pl._load_year(1996, _filing(1996), None)
    assert r["text"] == "tiny" and any("only 4 characters" in w for w in r["warnings"])


# ============================================================================================ v2: shell / SPAC detection
# Synthetic cover pages / bodies only (structure, no real company data). Glyph styles seen in real filings: ASCII x/o,
# Unicode ballot boxes, Latin-1 Wingdings (\xfe checked, \xa8 unchecked), bracketed [X] / [ ].
def _cover(yes, no, style="after"):
    head = ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 10-K Indicate by check mark whether the registrant is a shell "
            "company (as defined in Rule 12b-2 of the Exchange Act). ")
    if style == "before":
        return head + f"{yes} Yes {no} No The aggregate market value of the voting stock was $1."
    return head + f"Yes {yes} No {no} The aggregate market value of the voting stock was $1."


@pytest.mark.parametrize("yes,no,style,expected", [
    ("x", "o", "after", True), ("o", "x", "after", False),
    ("☒", "☐", "after", True), ("☐", "☒", "after", False),
    ("\xa8", "\xfe", "after", False), ("\xfe", "\xa8", "after", True),
    ("[X]", "[ ]", "after", True), ("[ ]", "[X]", "after", False),
    ("[X]", "[ ]", "before", True), ("☐", "☒", "before", False),
    ("☐", "☐", "after", None), ("☒", "☒", "after", None),
])
def test_cover_shell_checkbox_styles(yes, no, style, expected):
    assert pl.cover_shell_checkbox(_cover(yes, no, style)) is expected


def test_cover_shell_checkbox_absent_or_beyond_cover():
    assert pl.cover_shell_checkbox("no cover here") is None
    assert pl.cover_shell_checkbox("x" * 40_000 + _cover("x", "o")) is None   # only the cover page is scanned


def _long(extra="", n=60_000):
    return ("Item 1. Business. The company sells products. Total assets were reported. " * 10 + extra).ljust(n, " ")


SPAC_BODY = ("We are a blank check company formed for an initial business combination. Funds held in the Trust Account. " * 8
             + "We have neither engaged in any operations nor generated any revenues to date. ")


def test_detect_spac_by_cover_and_vocabulary():
    r = pl.detect_filing_entity(_cover("x", "o") + _long(SPAC_BODY, 80_000))
    assert r["is_shell"] and r["spac_predecessor"] and r["kind"] == "spac" and r["cover_box"] is True
    assert "cover shell-company box = Yes" in r["reason"]


def test_detect_spac_by_vocabulary_alone_when_box_unparseable():
    r = pl.detect_filing_entity("Cover without box. " + _long(SPAC_BODY, 80_000))
    assert r["is_shell"] and r["spac_predecessor"] and r["cover_box"] is None


def test_vocabulary_without_no_operations_statement_is_not_enough():
    body = "blank check company initial business combination Trust Account " * 8
    r = pl.detect_filing_entity(_cover("o", "x") + _long(body, 80_000))
    assert not r["is_shell"] and not r["spac_predecessor"]


def test_blank_check_preferred_stock_boilerplate_is_not_a_spac():
    body = "Our board may issue blank check preferred stock. " * 30 + "We have no operations in Antarctica. "
    r = pl.detect_filing_entity(_cover("o", "x") + _long(body, 80_000))
    assert not r["is_shell"] and r["spac_terms"]["blank_check"] == 0


def test_real_shell_without_spac_vocabulary_is_shell_not_spac():
    r = pl.detect_filing_entity(_cover("x", "o") + _long("", 80_000))
    assert r["is_shell"] and not r["spac_predecessor"] and r["kind"] == "shell"


def test_stub_floor_boundaries_and_enron_oregon_class():
    assert pl.STUB_FLOOR_CHARS == 25_000
    stub = "FORM 10-K ENRON OREGON CORP. 1,000 shares owned by the parent. " + "Item 1. Business. See parent.\n" * 40
    assert len(stub) < 25_000
    r = pl.detect_filing_entity(stub)
    assert r["is_shell"] and r["kind"] == "stub" and not r["spac_predecessor"] and "stub floor" in r["reason"]
    assert not pl.detect_filing_entity(_long("", pl.STUB_FLOOR_CHARS))["is_shell"]          # exactly at the floor: not a stub
    assert pl.detect_filing_entity(_long("", pl.STUB_FLOOR_CHARS - 1))["is_shell"]


def test_exhibit_13_wrapper_is_marked_but_a_statement_bearing_short_filing_is_not():
    wrap = ("Item 8 incorporated by reference to Exhibit 13. Item 7 incorporated herein by reference to Exhibit 13 annual report to "
            "shareholders. ") * 4
    wrap = wrap.ljust(40_000, " ")
    r = pl.detect_filing_entity(wrap)
    assert r["is_shell"] and r["kind"] == "wrapper"
    assert not pl.detect_filing_entity(wrap + " Total assets 100 ")["is_shell"]
    assert not pl.detect_filing_entity(wrap.ljust(70_000, " "))["is_shell"]


def test_empty_text_is_unknown_not_shell():
    for t in (None, ""):
        r = pl.detect_filing_entity(t)
        assert not r["is_shell"] and not r["spac_predecessor"]


def test_detection_never_raises(monkeypatch):
    monkeypatch.setattr(pl, "cover_shell_checkbox", lambda t: 1 / 0)
    r = pl.detect_filing_entity("x" * 100_000)
    assert not r["is_shell"] and "detection failed" in r["reason"]


SUCCESSOR_BODY = ("On June 3, 2021 (the “Closing Date”), we consummated the merger contemplated by the Business Combination "
                  "Agreement. Following the closing of the Business Combination, Legacy Widget became our subsidiary. "
                  "The consummation of the Business Combination was a reverse recapitalization, and the completion of the "
                  "Business Combination ended the SPAC era. " + "Business Combination. " * 12)


def _successor_filings():
    return {2020: {"report_date": "2020-12-31"}, 2021: {"report_date": "2021-12-31"}, 2022: {"report_date": "2022-12-31"}}


def test_successor_marks_prior_year_as_spac_predecessor():
    texts = {2020: "Cover. " + _long("Operating text without the vocabulary.", 80_000),
             2021: "Cover. " + _long(SUCCESSOR_BODY, 80_000)}
    fl = pl.compute_filing_entity_flags(texts, _successor_filings())
    assert fl[2021]["closing_date"] == "2021-06-03" and not fl[2021]["is_shell"]
    assert fl[2020]["spac_predecessor"] and fl[2020]["is_shell"] and "successor FY2021" in fl[2020]["reason"]


def test_successor_closing_outside_own_fiscal_year_is_ignored():
    """A later filing (FY2022) that merely describes the 2021 merger must not re-flag FY2021 as a SPAC predecessor."""
    texts = {2020: _long("op", 80_000), 2021: _long(SUCCESSOR_BODY, 80_000), 2022: _long(SUCCESSOR_BODY, 80_000)}
    fl = pl.compute_filing_entity_flags(texts, _successor_filings())
    assert fl[2021]["spac_predecessor"] is False and fl[2022]["is_shell"] is False and fl[2020]["spac_predecessor"]


def test_ordinary_acquirer_asc805_language_is_not_a_successor():
    body = "In the business combination accounting under ASC 805 the Business Combination was complete. " * 2
    fl = pl.compute_filing_entity_flags({2020: _long("", 80_000), 2021: _long(body, 80_000)}, _successor_filings())
    assert not any(f["is_shell"] or f["spac_predecessor"] for f in fl.values())


def test_undated_successor_does_not_flag():
    body = "We consummated the Business Combination. " * 6 + "Business Combination " * 8 + "Trust Account. "
    fl = pl.compute_filing_entity_flags({2020: _long("", 80_000), 2021: _long(body, 80_000)}, _successor_filings())
    assert fl[2021]["successor_of_spac"] and fl[2021]["closing_date"] is None and not fl[2020]["spac_predecessor"]


def _fetch_patches(monkeypatch, texts):
    years = sorted(texts)
    filings = [{**_filing(y, form="10-K405" if y == years[0] else "10-K"), "report_date": f"{y}-12-31"} for y in years]
    monkeypatch.setattr(pl.edgar_api, "resolve_company", lambda t, c=None: {"cik": "0000000001", "ticker": t, "name": "Stub Co", "sic": "1000"})
    monkeypatch.setattr(pl.edgar_api, "list_annual_filings", lambda cik, as_of: list(reversed(filings)))
    monkeypatch.setattr(pl, "_load_facts", lambda cik, fy, as_of: {"annual_facts": {"warnings": [], "source_by_year": {y: "xbrl" for y in years}},
                                                                  "xbrl_data": {}, "has_companyfacts": True, "seconds": 0})
    monkeypatch.setattr(pl, "_load_texts_and_metadata", lambda sel, cik, as_of: {
        "texts": {y: texts[y] for y in sel}, "metas": {y: {} for y in sel}, "warnings": [], "degraded": [], "proxies_used": {},
        "n_proxies_listed": 0, "seconds": 0})
    monkeypatch.setattr(pl, "_load_peers", lambda cik, sic, as_of, fy: {"peers": [{"ticker": "P"}], "reason": "", "seconds": 0})


def test_fetch_data_records_flags_warnings_and_baseline_marking(monkeypatch):
    texts = {1996: "STUB " * 100, 1997: _long("", 80_000), 1998: _long("", 80_000)}
    _fetch_patches(monkeypatch, texts)
    upd = asyncio.run(pl._fetch_data_impl({"ticker": "STUB", "as_of": "2000-01-01", "years_requested": 2, "focus_year": 1998}))
    assert not upd.get("error")
    assert upd["analysis_years"] == [1997, 1998] and upd["fetch_info"]["baseline_year"] == 1996
    ef = upd["filing_entity_flags"]
    assert ef[1996]["is_shell"] and not ef[1997]["is_shell"] and not ef[1998]["is_shell"]
    assert set(ef[1996]) >= {"is_shell", "spac_predecessor", "reason"} and ef[1996]["reason"]
    assert 1996 in upd["filing_texts"]                                     # kept for transparency, not dropped
    summ = upd["fetch_info"]["entity_flags_summary"]
    assert summ["flagged_years"] == [1996] and summ["baseline_year_flagged"] is True and summ["first_analysis_year_flagged"] is False
    assert any("FY1996" in w and "baseline year" in w and "stub" in w for w in upd["warnings"])
    assert any("baseline year FY1996" in w and "not comparable" in w for w in upd["warnings"])
    assert upd["pipeline_version"] == "v3"


def test_fetch_data_clean_filings_get_no_flags(monkeypatch):
    texts = {y: _long("", 80_000) for y in (2018, 2019, 2020)}
    _fetch_patches(monkeypatch, texts)
    upd = asyncio.run(pl._fetch_data_impl({"ticker": "STUB", "as_of": "2021-06-30", "years_requested": 2, "focus_year": 2020}))
    assert upd["fetch_info"]["entity_flags_summary"]["flagged_years"] == []
    assert not any(v["is_shell"] or v["spac_predecessor"] for v in upd["filing_entity_flags"].values())
    assert not any("shell" in w for w in upd["warnings"])


def test_fetch_data_detection_failure_is_a_warning(monkeypatch):
    _fetch_patches(monkeypatch, {y: _long("", 80_000) for y in (2018, 2019, 2020)})
    monkeypatch.setattr(pl, "compute_filing_entity_flags", lambda t, f: 1 / 0)
    upd = asyncio.run(pl._fetch_data_impl({"ticker": "STUB", "as_of": "2021-06-30", "years_requested": 2, "focus_year": 2020}))
    assert not upd.get("error") and upd["filing_entity_flags"] == {}
    assert any("entity-flag detection failed" in w for w in upd["warnings"])
    assert "fetch_data: shell/SPAC detection failed" in upd["degraded"]


def test_fetch_trace_summary_lists_flagged_years(monkeypatch):
    async def fake(state):
        return {**await _stub_fetch(state), "fetch_info": {"entity_flags_summary": {"flagged_years": [2017]}}}
    monkeypatch.setattr(pl, "_fetch_data_impl", fake)
    out = asyncio.run(pl.fetch_data({}, {}))
    assert "flagged years: [2017]" in out["agent_trace"][0]["summary"]


# ============================================================================================ v2: plumbing / versions
def test_new_state_and_final_state_carry_pipeline_version(stubbed):
    from agents.state import new_state
    s = new_state("X", 3)
    assert s["pipeline_version"] == "v3" and s["filing_entity_flags"] == {} and s["prior_year_info"] == {}
    st = run()
    assert st["pipeline_version"] == "v3"
    assert "prior_year" in pl.UI_MESSAGES


def test_analyze_company_signature_is_backwards_compatible():
    import inspect
    params = list(inspect.signature(pl.analyze_company).parameters)
    assert params[:2] == ["ticker", "years"]
    assert {"cik", "end_year", "as_of", "thread_id", "progress_callback", "previous_risk_grade", "watchlist_id", "exclude_flags"} <= set(params)


# ============================================================================================ v2: prior-year re-run (Jev material_change)
def _prior_state(**over):
    ays = [2018, 2019, 2020]
    s = {"ticker": "X", "analysis_years": ays, "focus_year": 2020, "exclude_flags": [],
         "filing_texts": {y: f"text{y}" for y in [2017] + ays}, "filing_metadata": {y: {"y": y} for y in [2017] + ays},
         "filings": [_filing(y) for y in [2017] + ays],
         "annual_facts": {"by_year": {y: {"Revenue": 1} for y in [2017] + ays}, "missing": {}, "period_end": {}, "source_by_year": {}, "unit": "USD"},
         "peer_companies": [{"ticker": "P"}], "peer_reason": "", "filing_entity_flags": {}}
    s.update(over)
    return s


@pytest.fixture
def prior_agents(monkeypatch):
    seen = {}

    def mk(name):
        def fn(state):
            seen[name] = {"focus": state.get("focus_year"), "ays": list(state["analysis_years"]),
                          "text_years": sorted(state["filing_texts"]), "meta_years": sorted(state["filing_metadata"]),
                          "fact_years": sorted(state["annual_facts"]["by_year"]), "filing_years": sorted(f["fiscal_year"] for f in state["filings"])}
            return {f"{name}_result": {"severity": "Low", "flags_by_year": {state["focus_year"]: []}, "focus_year": state["focus_year"],
                                       "flags_fired": 0, "evidence": [], "key_finding": f"prior {name}"}}
        return fn
    for n in pl.AGENT_NODES:
        monkeypatch.setattr(pl, pl._AGENT_FUNC[n], mk(n), raising=True)
    monkeypatch.setattr(pl, "run_temporal", lambda st: {"temporal_result": {"severity": "Low", "focus_year": st["focus_year"], "key_finding": "t",
                                                                             "seen": sorted(k for k in st if k.endswith("_result"))}})
    return seen


def test_prior_year_reuses_fetched_data_with_no_lookahead(prior_agents):
    res, info = pl.compute_prior_year_results(_prior_state(), force=True)
    assert info["status"] == "ok" and info["year"] == 2019
    assert set(res) == {"quantitative", "language", "network", "peer", "temporal"}
    for n in pl.AGENT_NODES:
        v = prior_agents[n]
        assert v["focus"] == 2019 and v["ays"] == [2018, 2019]
        assert max(v["text_years"]) == 2019 and 2017 in v["text_years"]                     # baseline year kept, FY2020 removed
        assert max(v["meta_years"]) == 2019 and max(v["fact_years"]) == 2019 and max(v["filing_years"]) == 2019
    assert res["temporal"]["seen"] == ["language_result", "network_result", "peer_result", "quantitative_result"]
    assert res["language"]["focus_year"] == 2019


def test_prior_year_peer_list_keeps_reason(monkeypatch, prior_agents):
    got = {}
    monkeypatch.setattr(pl, "run_peer", lambda st: (got.setdefault("reason", getattr(st["peer_companies"], "reason", None)),
                                                    {"peer_result": {"severity": "Low", "focus_year": 2019}})[1])
    pl.compute_prior_year_results(_prior_state(peer_reason="why"), force=True)
    assert got["reason"] == "why"


def test_prior_year_skipped_without_jev_key_or_disabled(prior_agents, monkeypatch):
    res, info = pl.compute_prior_year_results(_prior_state())
    assert res == {} and info["status"] == "skipped" and "Jev key" in info["reason"] and prior_agents == {}
    monkeypatch.setenv("FORENSIC_PRIOR_YEAR", "0")
    assert pl.compute_prior_year_results(_prior_state(), force=True)[1]["reason"].startswith("disabled")


def test_prior_year_skipped_for_single_year_and_for_shell_prior_year(prior_agents):
    assert pl.compute_prior_year_results(_prior_state(analysis_years=[2020]), force=True)[1]["status"] == "skipped"
    for flag in ({"is_shell": True, "spac_predecessor": False, "kind": "stub"}, {"is_shell": False, "spac_predecessor": True, "kind": "spac"}):
        res, info = pl.compute_prior_year_results(_prior_state(filing_entity_flags={2019: flag}), force=True)
        assert res == {} and info["status"] == "skipped" and "FY2019" in info["reason"] and prior_agents == {}
    # string keys (JSON round-trip) are honoured too
    assert pl.compute_prior_year_results(_prior_state(filing_entity_flags={"2019": {"is_shell": True}}), force=True)[0] == {}
    # a flagged OLDER year (the baseline) does not block the prior-year run
    assert pl.compute_prior_year_results(_prior_state(filing_entity_flags={2017: {"is_shell": True}}), force=True)[1]["status"] == "ok"


def test_prior_year_failure_tolerant(monkeypatch, prior_agents):
    def boom(state):
        raise RuntimeError("agent broke")
    monkeypatch.setattr(pl, "run_network", boom)
    monkeypatch.setattr(pl, "run_peer", lambda st: {"peer_result": {"unavailable": True, "focus_year": 2019}})
    res, info = pl.compute_prior_year_results(_prior_state(), force=True)
    assert info["status"] == "ok" and "network" not in res and "peer" not in res and set(info["agent_errors"]) == {"network", "peer"}
    for n in pl.AGENT_NODES:
        monkeypatch.setattr(pl, pl._AGENT_FUNC[n], boom, raising=True)
    res, info = pl.compute_prior_year_results(_prior_state(), force=True)
    assert res == {} and info["status"] == "failed"
    assert pl.compute_prior_year_results({"analysis_years": "bad"}, force=True)[1]["status"] == "failed"   # malformed state never raises


def test_prior_year_timeout_is_bounded(monkeypatch, prior_agents):
    monkeypatch.setattr(pl, "run_language", lambda st: (time.sleep(3), {"language_result": {"severity": "Low"}})[1])
    t0 = time.time()
    res, info = pl.compute_prior_year_results(_prior_state(), timeout_s=0.5, force=True)
    assert time.time() - t0 < 2.5 and info["status"] == "timeout" and "language" in info["reason"]


def test_prior_year_applies_flag_exclusions(monkeypatch, prior_agents):
    monkeypatch.setattr(pl, "run_language", lambda st: {"language_result": {
        "severity": "Medium", "flags_fired": 2, "focus_year": 2019, "evidence": [], "key_finding": "k",
        "flags_by_year": {2019: ["language.passive_voice", "language.hedging"]}}})
    res, _ = pl.compute_prior_year_results(_prior_state(exclude_flags=["language.passive_voice"]), force=True)
    assert res["language"]["flags_by_year"][2019] == ["language.hedging"] and res["language"]["severity"] == "Low"


def test_synthesis_node_passes_prior_results_and_records_trace(monkeypatch, stubbed):
    monkeypatch.setenv("JEV_API_KEY", "dummy-not-used")
    captured = {}

    def fake_synth(state, cb=None):
        captured["prior"] = state.get("prior_year_results")
        return {"risk_grade": "Low", "grade_rationale": "r", "final_narrative": "n", "degraded": ["synthesis: stub"]}
    monkeypatch.setattr(pl, "run_synthesis", fake_synth)
    def fake_prior(st, **kw):
        kw["on_start"]()
        return {"quantitative": {"severity": "Low", "focus_year": 2019}}, {"status": "ok", "reason": "fake", "year": 2019}
    monkeypatch.setattr(pl, "compute_prior_year_results", fake_prior)
    evs = []
    st = asyncio.run(pl.analyze_company("STUB", 3, progress_callback=evs.append))
    assert captured["prior"] == {"quantitative": {"severity": "Low", "focus_year": 2019}}
    assert st["prior_year_results"]["quantitative"]["focus_year"] == 2019 and st["prior_year_info"]["status"] == "ok"
    tr = [t for t in st["agent_trace"] if t["agent"] == "prior_year"]
    assert len(tr) == 1 and tr[0]["status"] == "ok"
    assert [e["status"] for e in evs if e["node"] == "prior_year"] == ["start", "done"]
    assert not any("prior_year_results" in d for d in st["degraded"])


@pytest.mark.parametrize("mode", ["raise", "failed", "timeout"])
def test_synthesis_node_never_breaks_when_prior_year_step_fails(monkeypatch, stubbed, mode):
    monkeypatch.setattr(pl, "run_synthesis", lambda state, cb=None: {"risk_grade": "Low", "grade_rationale": "r", "final_narrative": "n"})

    def prior(st, **kw):
        if mode == "raise":
            raise RuntimeError("kaboom")
        return {}, {"status": mode, "reason": "simulated"}
    monkeypatch.setattr(pl, "compute_prior_year_results", prior)
    st = asyncio.run(pl.analyze_company("STUB", 3))
    assert st["risk_grade"] == "Low" and not st["error"]
    assert st["prior_year_results"] == {} and st["prior_year_info"]["status"] in ("failed", "timeout")
    assert any(d.startswith("prior_year_results:") for d in st["degraded"])


def test_caller_supplied_prior_results_are_not_recomputed(monkeypatch):
    monkeypatch.setattr(pl, "run_synthesis", lambda state, cb=None: {"risk_grade": "Low", "grade_rationale": "r", "final_narrative": "n"})
    monkeypatch.setattr(pl, "compute_prior_year_results", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    node = asyncio.run(pl.run_synthesis_node({"focus_year": 2020, "analysis_years": [2019, 2020],
                                              "prior_year_results": {"quantitative": {"focus_year": 2019}}}, {}))
    assert node["prior_year_info"]["reason"] == "supplied by caller" and not any(t["agent"] == "prior_year" for t in node.get("agent_trace", []))


# ============================================================================================ v2: live dev-case checks (cached EDGAR)
DEV_ENTITY_CASES = {
    "ENRON": dict(ticker="ENRNQ", cik="0001024401", as_of="2001-04-02", focus_year=2000),
    "NKLA": dict(ticker="NKLA", cik="0001731289", as_of="2021-02-25", focus_year=2020),
    "RIDE": dict(ticker="RIDE", cik="0001759546", as_of="2021-03-25", focus_year=2020),
    "SPCE": dict(ticker="SPCE", as_of="2022-02-28", focus_year=2021),
    "AAPL": dict(ticker="AAPL", as_of="2020-10-30", focus_year=2020),
    "MSFT": dict(ticker="MSFT", as_of="2020-07-30", focus_year=2020),
    "JNJ": dict(ticker="JNJ", as_of="2021-02-22", focus_year=2020),
}


@pytest.fixture(scope="module")
def dev_flags():
    cache: dict = {}

    def get(name):
        if name not in cache:
            kw = dict(DEV_ENTITY_CASES[name])
            kw["years_requested"] = 5
            cache[name] = asyncio.run(pl._fetch_data_impl(kw))
        return cache[name]
    return get


def _flagged(upd):
    return sorted(y for y, f in upd["filing_entity_flags"].items() if f["is_shell"] or f["spac_predecessor"])


@pytest.mark.network
def test_live_dev_enron_fy1996_stub_flagged(dev_flags):
    u = dev_flags("ENRON")
    assert not u.get("error") and _flagged(u) == [1996]
    f = u["filing_entity_flags"][1996]
    assert f["kind"] == "stub" and not f["spac_predecessor"] and f["chars"] < pl.STUB_FLOOR_CHARS
    assert 1996 in u["filing_texts"] and any("FY1996" in w and "stub" in w for w in u["warnings"])


@pytest.mark.network
@pytest.mark.parametrize("name,flagged", [("NKLA", [2018, 2019]), ("RIDE", [2019]), ("SPCE", [2017, 2018])])
def test_live_dev_spac_predecessors_flagged(dev_flags, name, flagged):
    u = dev_flags(name)
    assert _flagged(u) == flagged
    assert all(u["filing_entity_flags"][y]["spac_predecessor"] for y in flagged)


@pytest.mark.network
@pytest.mark.parametrize("name", ["AAPL", "MSFT", "JNJ"])
def test_live_dev_operating_controls_have_no_false_shell_flags(dev_flags, name):
    u = dev_flags(name)
    assert _flagged(u) == [] and len(u["filing_entity_flags"]) >= 5


@pytest.mark.network
def test_live_dev_successor_side_finds_closing_dates(dev_flags):
    assert dev_flags("NKLA")["filing_entity_flags"][2020]["closing_date"] == "2020-06-03"
    assert dev_flags("RIDE")["filing_entity_flags"][2020]["closing_date"] == "2020-10-23"
    assert dev_flags("SPCE")["filing_entity_flags"][2019]["closing_date"] == "2019-10-25"


# ============================================================================================ v3 L2: grade inputs survive the graph
def test_v3_final_state_carries_grade_inputs_consistent_with_grade(stubbed):
    from agents.synthesis_agent import compute_risk_grade
    st = run()
    gi = st["grade_inputs"]
    assert set(gi) >= {"focus_year", "agents_flagging", "agents_high", "escalation", "focus_year_flagged",
                       "jev_mean_confidence", "jev_available", "agent_severity"}
    again = compute_risk_grade(gi["agents_flagging"], gi["agents_high"], gi["escalation"], gi["jev_mean_confidence"],
                               gi["jev_available"], gi["focus_year_flagged"])
    assert again["grade"] == st["risk_grade"] and again["rationale"] == st["grade_rationale"]


def test_v3_error_state_has_empty_grade_inputs():
    from agents.state import new_state
    assert new_state("X", 3)["grade_inputs"] == {}
