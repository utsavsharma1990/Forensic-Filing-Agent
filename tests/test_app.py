"""UI tests for app.py using streamlit.testing.v1.AppTest, plus pure tests of app_components.

All state used here is SYNTHETIC (tests/fixtures/ui_state*.json: invented inputs run through the real agents; see
tests/fixtures/build_ui_state.py) or hand-built dicts with invented marker values. No network, no API keys, and the
pipeline / evaluator modules are replaced by stubs in sys.modules, so nothing here claims anything about a real company.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from app_components import charts as C  # noqa: E402
from app_components import eval_adapter as EA  # noqa: E402
from app_components import formatting as F  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
if not (FIX / "ui_state.json").exists():  # build on demand (deterministic, offline)
    import subprocess
    subprocess.run([sys.executable, str(FIX / "build_ui_state.py")], check=True, cwd=str(ROOT))


def load(name="ui_state.json") -> dict:
    return F.normalize_state(json.loads((FIX / name).read_text(encoding="utf-8")))


def at_for(page: str | None = None, **ss) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    if page:
        at.session_state["page"] = page
    for k, v in ss.items():
        at.session_state[k] = v
    return at


def analysis(state: dict, source="test"):
    return {"state": state, "source": source, "loaded_at": "now"}


def md(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHLIST_DB_PATH", str(tmp_path / "wl.db"))
    monkeypatch.setenv("FFA_DEMO_MODE", "0")                      # the original tests exercise the live-capable UI
    monkeypatch.delenv("FFA_ACCESS_CODE", raising=False)
    monkeypatch.setenv("FFA_ENV_FILE", str(tmp_path / "no.env"))  # never read the developer's real .env
    yield


# ======================================================================================= page 1
def test_page1_empty_state_renders():
    at = at_for().run()
    assert not at.exception
    assert at.title[0].value == "Forensic Filing Intelligence Agent"
    assert any("Multi-agent SEC filing analysis powered by LangGraph + Claude + Jev" in c.value for c in at.caption)
    assert at.text_input[0].label == "Enter ticker symbol (e.g. AAPL, ENRNQ)"
    assert at.number_input[0].label == "Years to analyze" and at.number_input[0].value == 5 and at.number_input[0].max == 10
    assert [b.label for b in at.button if b.proto.type == "primary"] == ["Run Forensic Analysis"]
    assert [r.label for r in at.sidebar.radio] == ["Navigation"]
    assert at.sidebar.radio[0].options == ["Forensic Analysis", "Watchlist", "Retrospective Validation"]


def test_page1_fixture_degraded_no_jev():
    st_ = load()
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    text = md(at)
    assert "HIGH" in text and "SYNTHETIC DATA" in "\n".join(w.value for w in at.warning)
    assert "DEGRADED RUN" in text and "Jev (confidence scoring)" in text
    assert text.count('class="gun"') == 3
    assert len(at.tabs) == 5 and [t.label for t in at.tabs] == ["Quantitative", "Language", "Network", "Peer", "Temporal"]
    side = "\n".join(w.value for w in at.sidebar.warning)
    assert "Jev unavailable" in side
    assert len(at.sidebar.get('progress')) == 0          # no invented confidence bars
    assert any("Grade rationale" in i.value for i in at.info)
    # specificity must say it needs the API key rather than show zeros
    assert any("ANTHROPIC_API_KEY" in i.value for i in at.info)
    # degraded expander lists the real degraded entries
    assert any("Degraded components" in e.label for e in at.expander)


def test_page1_with_jev_scores_shows_badges_bars_and_material_change():
    st_ = load("ui_state_jev.json")
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert len(at.sidebar.get('progress')) == 5
    side = "\n".join(m.value for m in at.sidebar.markdown) + "\n".join(c.value for c in at.sidebar.caption)
    assert "STRONG" in side and "DEFINITIVE" in side and "INSUFFICIENT" in side
    assert "Material change vs prior year: **YES**" in side and "No material change" in side
    assert not any("Jev unavailable" in w.value for w in at.sidebar.warning)


@pytest.mark.parametrize("grade", ["Low", "Medium", "High", "Critical"])
def test_badge_text_for_each_known_grade(grade):
    st_ = load()
    st_["risk_grade"] = grade
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert grade.upper() in md(at)


def test_unknown_grade_is_error_state_not_low():
    st_ = load()
    st_["risk_grade"] = "Unknown"
    st_["error"] = "synthesis exploded"
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert "UNKNOWN / ERROR" in md(at)
    assert any("not a Low-risk result" in e.value for e in at.error)
    assert 'aria-label="Risk grade LOW"' not in md(at)


def test_fewer_smoking_guns_are_not_padded():
    st_ = load()
    st_["smoking_guns"] = st_["smoking_guns"][:1]
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert md(at).count('class="gun"') == 1
    st_["smoking_guns"] = []
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception and md(at).count('class="gun"') == 0
    assert any("never padded" in i.value for i in at.info)


def test_pipeline_failure_state_without_agents_does_not_crash():
    bare = {"ticker": "ZZZ", "company_name": "", "risk_grade": "Unknown", "error": "company not found", "degraded": ["fetch_data: failed"],
            "quantitative_result": {}, "peer_result": {"unavailable": True, "reason": "no peers"}}
    at = at_for(analysis=analysis(bare)).run()
    assert not at.exception
    assert any("no peers" in w.value for w in at.warning)


def test_unavailable_beneish_year_shown_with_reason_not_blank():
    st_ = load()
    q = st_["quantitative_result"]
    q["beneish_scores"][2018] = {"status": "unavailable", "reason": "GMI: COGS tag not found"}
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    flat = json.dumps([df.value.to_dict() for df in at.dataframe], default=str)
    assert "unavailable: GMI: COGS tag not found" in flat


def test_peer_unavailable_tab_message():
    st_ = load()
    st_["peer_result"] = {"unavailable": True, "reason": "pre-XBRL focus year 2000", "severity": "None", "metric_zscores": {}, "peer_list": []}
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert any("pre-XBRL focus year 2000" in w.value for w in at.warning)


def test_no_first_detection_message():
    st_ = load()
    st_["temporal_result"]["first_detection_year"] = None
    st_["first_detection_year"] = None
    at = at_for(analysis=analysis(st_)).run()
    assert not at.exception
    assert any("No first-detection year" in i.value for i in at.info)


def test_load_saved_fixture_via_button():
    at = at_for().run()
    assert any("SYNTHETIC demo state" in o for o in at.selectbox[0].options)
    load_btn = [b for b in at.button if b.label == "Load saved analysis"][0]
    load_btn.click()
    at.run()
    assert not at.exception
    assert md(at).count('class="gun"') == 3


SAMPLES = ["enron_2000", "luckin_2019", "apple_2022"]


@pytest.mark.parametrize("name", SAMPLES)
def test_real_sample_analyses_load_and_render(name):
    """sample_analysis/*.json are REAL pipeline outputs (scripts/generate_samples.py); each must load and render."""
    p = ROOT / "sample_analysis" / f"{name}.json"
    assert p.exists(), "run scripts/generate_samples.py"
    raw = json.loads(p.read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(f"non-finite {c} in {p.name}"))
    assert raw["_meta"]["degraded"] in (True, False) and raw["_meta"]["generated_utc"] and raw["risk_grade"] in ("Low", "Medium", "High", "Critical")
    at = at_for().run()
    sb = at.selectbox[0]
    sb.set_value(f"sample_analysis/{name}.json")
    [b for b in at.button if b.label == "Load saved analysis"][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = md(at)
    assert f"saved file: sample_analysis/{name}.json" in " ".join(c.value for c in at.caption)
    assert F.GRADE_STYLE[raw["risk_grade"]]["word"] in text
    assert md(at).count('class="gun"') == len(raw["smoking_guns"][:3]) or md(at).count('class="gun"') >= 1
    if raw["_meta"]["degraded"]:
        assert "banner-degraded" in text


def test_progress_steps_with_real_pipeline_events():
    """tests/fixtures/real_pipeline_events.json = events captured from a real graph.pipeline run (AAPL), not a stub."""
    import app_components  # noqa: F401
    evs = json.loads((FIX / "real_pipeline_events.json").read_text(encoding="utf-8"))
    assert {e["node"] for e in evs} >= {"fetch_data", "quantitative", "language", "network", "peer", "temporal", "synthesis", "jev"}
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    ns: dict = {}
    # exercise the real step_states without importing the whole Streamlit script
    start, end = src.index("STEPS = ["), src.index("AGENTS = [")
    exec(src[start:end], ns)          # noqa: S102 - our own source
    s0 = src.index("def step_states"), src.index("def render_progress")
    exec(src[s0[0]:s0[1]], ns)        # noqa: S102
    st_all = ns["step_states"](evs)
    assert all(v["state"] == "done" for v in st_all.values()), st_all
    mid = ns["step_states"](evs[:5])
    assert mid["fetch_data"]["state"] == "done" and mid["language"]["state"] == "running" and mid["synthesis"]["state"] == "pending"
    crashed = ns["step_states"](evs[:3] + [{"node": "pipeline", "status": "error", "message": "pipeline crashed: X"}])
    assert crashed["peer"]["state"] == "error" and crashed["fetch_data"]["state"] == "done" and "crashed" in crashed["peer"]["message"]


def test_live_flow_replaying_real_event_stream(monkeypatch):
    """Stub pipeline that replays the REAL captured event stream through the app's own progress_callback."""
    evs = json.loads((FIX / "real_pipeline_events.json").read_text(encoding="utf-8"))
    state = load()

    async def analyze_company(ticker, years=5, *, progress_callback=None, **kw):
        for e in evs:
            progress_callback(dict(e))
        return copy.deepcopy(state)

    mod = types.ModuleType("graph.pipeline")
    mod.analyze_company = analyze_company
    monkeypatch.setitem(sys.modules, "graph.pipeline", mod)
    at = at_for().run()
    at.text_input[0].set_value("AAPL")
    [b for b in at.button if b.label == "Run Forensic Analysis"][0].click()
    at.run()
    for _ in range(40):
        if "analysis" in at.session_state:
            break
        at.run()
    at.run()
    assert not at.exception and "analysis" in at.session_state
    assert [e["node"] for e in at.session_state["analysis_job"].snapshot()] == [e["node"] for e in evs]


# ---- live-run flow with a stub pipeline (no network) --------------------------------------------------
def _stub_pipeline(monkeypatch, behaviour="ok"):
    state = load()

    async def analyze_company(ticker, years=5, *, progress_callback=None, **kw):
        for node in ("fetch_data", "quantitative", "language", "network", "peer", "temporal", "jev", "synthesis"):
            if progress_callback:
                progress_callback({"node": node, "status": "start", "message": node, "elapsed_ms": 0})
            await asyncio.sleep(0.01)
            if behaviour == "boom" and node == "peer":
                raise RuntimeError("EDGAR exploded")
            if progress_callback:
                progress_callback({"node": node, "status": "done", "message": node, "elapsed_ms": 10})
        out = copy.deepcopy(state)
        out["ticker"] = ticker.upper()
        out["_fixture_note"] = "SYNTHETIC stub pipeline output"
        out["_kwargs"] = kw
        return out

    mod = types.ModuleType("graph.pipeline")
    mod.analyze_company = analyze_company
    monkeypatch.setitem(sys.modules, "graph.pipeline", mod)


def test_run_analysis_flow_with_stub_pipeline(monkeypatch):
    _stub_pipeline(monkeypatch)
    at = at_for().run()
    at.text_input[0].set_value("synth")
    [b for b in at.button if b.label == "Run Forensic Analysis"][0].click()
    at.run()
    assert not at.exception
    # job result lands in session_state after polling reruns
    for _ in range(40):
        if "analysis" in at.session_state:
            break
        at.run()
    assert "analysis" in at.session_state
    at.run()
    assert not at.exception
    assert at.session_state["analysis"]["state"]["ticker"] == "SYNTH"
    assert md(at).count('class="gun"') == 3


def test_run_analysis_pipeline_exception_is_shown(monkeypatch):
    _stub_pipeline(monkeypatch, "boom")
    at = at_for().run()
    at.text_input[0].set_value("synth")
    [b for b in at.button if b.label == "Run Forensic Analysis"][0].click()
    at.run()
    for _ in range(40):
        if any("could not be completed" in e.value for e in at.error):
            break
        at.run()
    assert not at.exception
    assert any("EDGAR exploded" in e.value for e in at.error)


def test_broken_pipeline_import_does_not_break_launch(monkeypatch):
    monkeypatch.setitem(sys.modules, "graph.pipeline", None)   # import raises ImportError
    at = at_for().run()
    assert not at.exception
    at.text_input[0].set_value("AAPL")
    [b for b in at.button if b.label == "Run Forensic Analysis"][0].click()
    at.run()
    for _ in range(40):
        if any("could not be completed" in e.value for e in at.error):
            break
        at.run()
    assert any("could not be completed" in e.value for e in at.error)


def test_empty_ticker_rejected():
    at = at_for().run()
    [b for b in at.button if b.label == "Run Forensic Analysis"][0].click()
    at.run()
    assert any("Enter a ticker" in e.value for e in at.error)


# ======================================================================================= page 2
def _manager():
    from watchlist import manager
    return manager


def test_watchlist_empty_db():
    at = at_for("Watchlist").run()
    assert not at.exception
    assert at.title[0].value.startswith("Filing Watchlist")
    assert any("watchlist is empty" in i.value for i in at.info)
    assert "Alert threshold" in [s.label for s in at.selectbox]
    assert at.selectbox[0].options == ["Low", "Medium", "High", "Critical"]


def test_watchlist_with_rows_alerts_acknowledge_and_history():
    m = _manager()
    res = lambda t: {"name": f"{t} Test Co", "cik": "0000000001"}  # noqa: E731
    m.init_db()
    m.add_company("AAA", "Medium", resolver=res)
    m.add_company("BBB", "High", resolver=res)
    s1 = load(); s1["risk_grade"] = "Low"; s1["suspicion_score"] = 20
    s2 = load(); s2["risk_grade"] = "High"; s2["suspicion_score"] = 70
    m.record_analysis("AAA", s1)
    m.record_analysis("AAA", s2)
    m.create_alert("AAA", "Low", "High", "synthetic")
    at = at_for("Watchlist").run()
    assert not at.exception
    assert any("AAA Test Co risk elevated from Low to High" in w.value for w in at.warning)
    labels = [b.label for b in at.button]
    assert labels.count("Run Now") == 2 and labels.count("Remove") == 2 and labels.count("View History") == 2 and "Acknowledge" in labels
    text = md(at)
    assert "HIGH" in text and "↑ escalating" in text
    assert "not analyzed" in text           # BBB never analysed: shown as such, not as Low
    [b for b in at.button if b.label == "Acknowledge"][0].click()
    at.run()
    assert not at.exception and not any("risk elevated" in w.value for w in at.warning)
    assert m.list_alerts(True) == []
    # remove
    [b for b in at.button if b.label == "Remove"][1].click()
    at.run()
    assert [c["ticker"] for c in m.list_companies(active_only=True)] == ["AAA"]


def test_watchlist_add_error_for_unresolvable_ticker(monkeypatch):
    m = _manager()
    monkeypatch.setattr(m, "_default_resolver", lambda t: (_ for _ in ()).throw(RuntimeError("no such ticker")))
    at = at_for("Watchlist").run()
    at.text_input[0].set_value("NOPE")
    [b for b in at.button if b.label == "Add to Watchlist"][0].click()
    at.run()
    assert not at.exception
    assert any("Could not add" in e.value for e in at.error)


# ======================================================================================= page 3
SYNTH_EVAL = {  # SYNTHETIC: invented structure/values, mirrors CONTRACTS section 7 as understood by the adapter
    "mode": "spec",
    "metrics": {"precision": {"value": 0.75, "ci": [0.30, 0.95]}, "recall": {"value": 0.5, "ci_low": 0.19, "ci_high": 0.81},
                "f1": {"value": 0.6}, "false_positive_rate": {"value": 0.0, "ci": [0.0, 0.39]}},
    "confusion_matrix": {"TP": 3, "FP": 1, "TN": 5, "FN": 3},
    "cases": [
        {"ticker": "F1", "label": "Fraud One", "analysis_year": 2000, "ground_truth": 1, "predicted": "High", "risk_grade": "High", "first_detection_year": 1999, "months_before_revelation": 14.0, "key_signal": "x"},
        {"ticker": "F2", "label": "Fraud Two", "analysis_year": 2001, "ground_truth": 1, "risk_grade": "Critical", "first_detection_year": 2001, "months_before_revelation": 6.0},
        {"ticker": "F3", "label": "Fraud Three", "analysis_year": 2019, "ground_truth": 1, "risk_grade": "High", "first_detection_year": 2019, "months_before_revelation": -2.0},
        {"ticker": "F4", "label": "Fraud Four", "analysis_year": 2020, "ground_truth": 1, "risk_grade": "Low"},
        {"ticker": "C1", "label": "Clean One", "analysis_year": 2020, "ground_truth": 0, "risk_grade": "Low"},
        {"ticker": "C2", "label": "Clean Two", "analysis_year": 2020, "ground_truth": 0, "error": "EDGAR 404"},
    ],
    "agent_contribution": {"quantitative": {"flagged_pct": 50.0, "unique_catch_pct": 16.7}, "language": {"flagged_pct": 33.3, "unique_catch_pct": 0.0}},
    "run_metadata": {"keys_available": {"ANTHROPIC_API_KEY": False, "JEV_API_KEY": False}, "timestamp": "synthetic"},
}


def _stub_eval(monkeypatch, results=None, calls=None):
    """Replace evaluation.evaluator (only the live-run path imports it; saved results are read from disk)."""
    mod = types.ModuleType("evaluation.evaluator")

    def run_evaluation(mode="spec", progress_callback=None, **k):
        if calls is not None:
            calls.append({"mode": mode, **k})
        return results
    mod.run_evaluation = run_evaluation
    monkeypatch.setitem(sys.modules, "evaluation.evaluator", mod)


def _use_results_dir(monkeypatch, root: Path) -> None:
    monkeypatch.setenv("FFA_RESULTS_DIR", str(root))


def _dev_dir(tmp_path, results: dict, report: str | None = None) -> Path:
    """A results root whose top-level files (the 'development cases - v2' set) hold ``results``."""
    (tmp_path / "evaluation_results.json").write_text(json.dumps(results), encoding="utf-8")
    if report:
        (tmp_path / "evaluation_report.md").write_text(report, encoding="utf-8")
    return tmp_path


def eval_at(**ss) -> AppTest:
    return at_for("Retrospective Validation", **ss)


def test_eval_page_empty_state(monkeypatch, tmp_path):
    _use_results_dir(monkeypatch, tmp_path / "nothing_here")
    at = eval_at().run()
    assert not at.exception
    assert at.title[0].value == "Backtesting Results — Known Fraud vs Clean Companies"
    assert any("No saved result for this set" in i.value for i in at.info)
    assert [b.label for b in at.button if b.proto.type == "primary"] == ["Run live evaluation on the 12 development cases (~10-15 min)"]
    assert any(F_ for F_ in at.caption if "does not constitute investment advice" in F_.value)


def test_eval_page_with_results(monkeypatch, tmp_path):
    _use_results_dir(monkeypatch, _dev_dir(tmp_path, SYNTH_EVAL))
    at = eval_at(ev_set="dev_v2").run()
    assert not at.exception
    text = md(at)
    assert "75.0%" in text and "95% Wilson CI 30% - 95%" in text
    assert "undefined" not in text.split("False Positive Rate")[1][:200]      # FPR 0% is a value, not undefined
    # average only over positive leads: (14 + 6) / 2 = 10.0 ; the -2.0 case is excluded and stated
    assert "Average detection: **10.0 months** before public revelation" in text
    assert any("n = 2 fraud case(s)" in c.value and "Excluded from the average: F3" in c.value for c in at.caption)
    assert "DEGRADED EVALUATION" in text
    flat = json.dumps([df.value.to_dict() for df in at.dataframe], default=str)
    assert "ERROR (excluded)" in flat and "EDGAR 404" in flat
    assert any("does not constitute investment advice" in c.value for c in at.caption)


# ---- REAL evaluator output (copied verbatim from evaluation/results/, produced by the real run; degraded: no API keys)
def _real_eval() -> dict:
    d = json.loads((FIX / "eval_results_real.json").read_text(encoding="utf-8"))
    d["report_markdown"] = (FIX / "eval_report_real.md").read_text(encoding="utf-8")
    return d


def test_adapter_real_json_headline_and_runs():
    d = _real_eval()
    assert EA.available_modes(d) == ["spec/spec", "spec/no_passive", "strict/spec", "strict/no_passive"]
    block, key = EA.pick_mode(d, None)
    assert key == "spec/spec"
    h = EA.headline(block)
    assert h["confusion"] == {"TP": 3, "FP": 0, "TN": 6, "FN": 3}
    assert h["recall"]["value"] == 0.5 and h["recall"]["n"] == 6 and h["recall"]["ci_source"] == "evaluator"
    assert abs(h["recall"]["ci"][0] - 0.1876) < 1e-3 and abs(h["recall"]["ci"][1] - 0.8124) < 1e-3
    assert h["precision"]["n"] == 3 and h["f1"]["ci"] is None and "closed-form" in h["f1"]["note"]
    assert h["fpr"]["ci"][0] == 0.0                      # float noise 2.8e-17 clipped
    b2, k2 = EA.pick_mode(d, "strict/spec")
    assert k2 == "strict/spec" and b2["n_evaluable"] == 11
    assert len(EA.cases_of(block)) == 12


def test_adapter_real_json_timing_excludes_invalid_filings():
    d = _real_eval()
    block, _ = EA.pick_mode(d, None)
    tm = EA.timing_of(block, EA.cases_of(block))
    assert [i["label"] for i in tm["detected"]] == ["ENRNQ", "RIDE", "SPCE"]
    assert [i["label"] for i in tm["invalid"]] == ["RIDE", "SPCE"]
    assert [i["label"] for i in tm["positive"]] == ["ENRNQ"] and tm["average"] == 42.5
    assert tm["evaluator_average"] == 36.0 and tm["n_fraud"] == 6


def test_adapter_real_json_contribution_baselines_result_limits():
    d = _real_eval()
    block, _ = EA.pick_mode(d, None)
    c = {x["agent"]: x for x in EA.agent_contrib_of(block)}
    assert abs(c["network"]["flagged_pct"] - 83.33) < 0.01 and c["network"]["unique_cases"] == ["LK", "NKLA"]
    assert c["quantitative"]["flagged_cases"] == ["ENRNQ"]
    names = [b["name"] for b in EA.baselines_of(block)]
    assert len(names) == 3 and names[1].startswith("Always predict")
    assert "RESULT: WEAK / BAD" in EA.result_lines(d, "spec/spec")[0] and "recall is 50.0%" in EA.result_lines(d, "spec/spec")[0]
    assert "recall is 33.3%" in EA.result_lines(d, "spec/no_passive")[0]
    assert "recall is 40.0%" in EA.result_lines(d, "strict/spec")[0]
    assert any("EXCLUDED" in x for x in EA.result_lines(d, "strict/spec"))
    assert EA.limitations_markdown(d).count("post-date public revelation") >= 1
    assert EA.fmt_metric(block["metrics"]["recall"]) == "50.0% (CI 18.8-81.2%, 3/6)"


def _real_dev_root(monkeypatch, tmp_path) -> Path:
    d = _real_eval()
    rep = d.pop("report_markdown")
    root = _dev_dir(tmp_path, d, rep)
    _use_results_dir(monkeypatch, root)
    return root


def test_eval_page_real_results_headline(monkeypatch, tmp_path):
    _real_dev_root(monkeypatch, tmp_path)
    at = eval_at(ev_set="dev_v2").run()
    assert not at.exception
    text = md(at)
    assert "DEGRADED EVALUATION" in text and "ANTHROPIC_API_KEY, JEV_API_KEY" in text
    assert "RESULT: WEAK / BAD on this sample.** recall is 50.0%" in text
    # cards with Wilson CIs from the evaluator
    assert "95% Wilson CI 19% - 81%" in text and "95% Wilson CI 44% - 100%" in text and "95% Wilson CI 0% - 39%" in text
    assert any("no closed-form Wilson CI" in x for x in [text])
    # timing: only Enron counts; invalid cases are named and excluded; n shown
    assert "Average detection: **42.5 months** before public revelation" in text
    cap = " ".join(c.value for c in at.caption)
    assert "n = 1 fraud case(s)" in cap and "RIDE, SPCE" in cap and "not a valid early-warning test" in cap
    assert "36.0 months" in cap
    # radio offers all four runs, headline first
    r = at.radio(key="ev_view_dev_v2")
    assert len(r.options) == 4 and r.options[0].startswith("spec/spec - HEADLINE")
    flat = json.dumps([df.value.to_dict() for df in at.dataframe], default=str)
    assert "NO - filing post-dates revelation" in flat and "Pre-revelation valid" in flat
    assert "Beneish-only" in flat and "Always predict" in flat           # baselines table
    assert "FY1997 (filed 1998-03-31)" in flat
    assert "LK, NKLA" in flat                                           # network unique catches in contribution table
    assert "NOT clean out-of-sample evidence" in " ".join(w.value for w in at.warning)
    assert "Look-ahead: 4 of 6 fraud filings" in text
    assert any("does not constitute investment advice" in c.value for c in at.caption)


def test_eval_page_real_results_sensitivity_selector(monkeypatch, tmp_path):
    _real_dev_root(monkeypatch, tmp_path)
    at = eval_at(ev_set="dev_v2").run()
    r = at.radio(key="ev_view_dev_v2")
    r.set_value("strict/spec")
    at.run()
    assert not at.exception
    text = md(at)
    assert "recall is 40.0%" in text and "SENSITIVITY analysis" in " ".join(c.value for c in at.caption)
    assert any("were excluded from this run" in w.value and "LK" in w.value for w in at.warning)
    flat = json.dumps([df.value.to_dict() for df in at.dataframe], default=str)
    assert "strict alt filing" in flat
    at.radio(key="ev_view_dev_v2").set_value("spec/no_passive")
    at.run()
    assert not at.exception and "recall is 33.3%" in md(at)


def test_eval_run_button_writes_to_new_timestamped_folder(monkeypatch, tmp_path):
    calls: list = []
    _stub_eval(monkeypatch, SYNTH_EVAL, calls)
    live = tmp_path / "live"
    monkeypatch.setenv("FFA_LIVE_RUNS_DIR", str(live))
    _use_results_dir(monkeypatch, tmp_path / "nothing_here")
    at = eval_at().run()
    [b for b in at.button if b.proto.type == "primary"][0].click()
    at.run()
    for _ in range(20):
        if not at.exception and "eval_job" in at.session_state and at.session_state["eval_job"].finished:
            break
        at.run()
    at.run()
    assert not at.exception
    assert at.session_state["eval_job"].finished and at.session_state["eval_job"].error is None
    assert len(calls) == 1 and Path(calls[0]["results_dir"]).parent == live          # never evaluation/results itself
    assert "evaluation" + os.sep + "results" not in str(calls[0]["results_dir"])
    assert any("overwrites nothing under evaluation/results/" in c.value for c in at.caption)


# ---- the result-set selector, on REAL result files copied into tests/fixtures/results/
def real_root(monkeypatch) -> None:
    _use_results_dir(monkeypatch, FIX / "results")


def _flat(at) -> str:
    return json.dumps([df.value.to_dict() for df in at.dataframe], default=str)


def test_selector_lists_all_valid_sets_and_defaults_to_h2_v3(monkeypatch):
    real_root(monkeypatch)
    at = eval_at().run()
    assert not at.exception
    sb = at.selectbox(key="ev_set")
    assert sb.value == "h2_v3" and len(sb.options) == len(EA.RESULT_SETS) == 9
    assert any("Development cases (12 filings) - v3" in o for o in sb.options)
    assert sb.options[0] == "H2 sealed holdout (30 filings) - v3 (latest, default)"
    assert not any("INVALID" in o for o in sb.options)


def test_h2_v3_default_view_paired_metric_confusion_and_verdict(monkeypatch):
    real_root(monkeypatch)
    at = eval_at().run()
    assert not at.exception
    text = md(at)
    assert "SEALED HOLDOUT (out-of-sample)" in text and "Pipeline version:** v3" in text and "n:** 30 filings" in text
    assert "RESULT: WEAK / BAD on this sample.** recall is 13.3%" in text
    assert "95% Wilson CI 4% - 38%" in text and "95% Wilson CI 1% - 30%" in text      # recall 2/15, FPR 1/15
    caps = " ".join(c.value for c in at.caption)
    assert "TP = 2, FP = 1, TN = 14, FN = 13" in caps
    assert any("Paired score metric" in s.value for s in at.subheader)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Fraud scores higher"] == "11 of 15 pairs" and metrics["Sign test (two-sided)"] == "p = 0.057"
    assert metrics["Paired AUC"] == "0.77"
    flat = _flat(at)
    assert "Always predict" in flat and "Beneish-only" in flat
    assert "docs/H2_AUDIT.md" in caps
    assert not any("NOT PERFORMANCE ESTIMATES" in e.value for e in at.error)
    # live-key run with component fallbacks: milder note, not the "ran without keys" banner
    assert "DEGRADED EVALUATION" not in text and "Live Claude and Jev keys were available" in caps


def test_switch_sets_h2_v1_holdout_v2_and_dev(monkeypatch):
    real_root(monkeypatch)
    at = eval_at().run()
    at.selectbox(key="ev_set").set_value("h2_v1")
    at.run()
    assert not at.exception
    text = md(at)
    assert "Pipeline version:** v1" in text and "recall is 40.0%" in text
    assert not any("Paired score metric" in s.value for s in at.subheader)          # v1 rows: no paired block, no crash
    at.selectbox(key="ev_set").set_value("holdout_v2")
    at.run()
    assert not at.exception
    text = md(at)
    assert "n:** 24 filings" in text and "recall is 8.3%" in text
    assert any("docs/HOLDOUT_AUDIT.md" in c.value for c in at.caption)
    at.selectbox(key="ev_set").set_value("dev_v1")
    at.run()
    assert not at.exception
    assert "DEVELOPMENT SET" in md(at)
    assert any("NOT PERFORMANCE ESTIMATES" in e.value for e in at.error)
    assert any("NOT clean out-of-sample evidence" in w.value for w in at.warning)   # evaluator's own limitations, dev only
    at.selectbox(key="ev_set").set_value("dev_v2")
    at.run()
    assert not at.exception and "Pipeline version:** v2" in md(at)
    assert any("NOT PERFORMANCE ESTIMATES" in e.value for e in at.error)


def test_sealed_sets_do_not_show_the_dev_only_limitations_text(monkeypatch):
    real_root(monkeypatch)
    at = eval_at().run()
    warn = " ".join(w.value for w in at.warning)
    assert "best available out-of-sample numbers" in warn and "12 filings (6 fraud" not in md(at)


def test_missing_set_files_show_a_message_not_an_exception(monkeypatch, tmp_path):
    _use_results_dir(monkeypatch, tmp_path)
    (tmp_path / "h2_v3").mkdir()
    (tmp_path / "h2_v3" / "evaluation_results.json").write_text("{not json", encoding="utf-8")
    at = eval_at().run()
    assert not at.exception
    assert any("No saved result for this set" in i.value and "unreadable" in i.value for i in at.info)


def test_rows_missing_optional_keys_are_tolerated():
    for sid in ("h2_v1", "h2_v3", "holdout_v2"):
        spec = next(x for x in EA.RESULT_SETS if x["id"] == sid)
        d, err = EA.load_result_set(FIX / "results", spec)
        assert err is None and d["report_markdown"]
        block, _ = EA.pick_mode(d, None)
        for r in EA.cases_of(block):                    # strip everything optional from every row
            for k in list(r):
                if k not in ("ticker", "ground_truth"):
                    del r[k]
        assert len(EA.cases_of(block)) >= 24 and all(EA.case_view(r)["Company"] for r in EA.cases_of(block))
        EA.timing_of(block, EA.cases_of(block))
        EA.headline(block)
        block.pop("paired", None)
        assert EA.paired_of(block) is None
    assert EA.paired_of({"paired": {"available": False}}) is None and EA.paired_of({}) is None


def test_paired_only_in_v3_rows():
    for sid, expect in (("h2_v3", True), ("h2_v1", False), ("holdout_v2", False)):
        d, _ = EA.load_result_set(FIX / "results", next(x for x in EA.RESULT_SETS if x["id"] == sid))
        p = EA.paired_of(EA.pick_mode(d, None)[0])
        assert (p is not None) == expect
        if p:
            assert (p["wins"], p["ties"], p["losses"], p["n_pairs"]) == (11, 1, 3, 15) and len(p["pairs"]) == 15


def test_status_note_on_page1_and_sidebar():
    at = at_for().run()
    assert not at.exception
    assert any("research prototype" in i.value and "README.md" in i.value for i in at.info)
    assert any("Status: research prototype" in m.value for m in at.sidebar.markdown)


# ======================================================================================= pure units
def test_finite_never_turns_missing_into_zero():
    assert F.finite(None) is None and F.finite(float("nan")) is None and F.finite("x") is None and F.finite(True) is None
    assert F.finite(0) == 0.0 and F.fmt_num(None) == "n/a" and F.fmt_pct(float("inf")) == "n/a"


def test_normalize_state_int_keys_and_wrapper():
    s = F.normalize_state({"state": {"risk_grade": "Low", "x": {"2019": {"2020": 1}, "abc": 2}}})
    assert s["x"][2019][2020] == 1 and s["x"]["abc"] == 2


def test_degraded_summary_detects_components():
    d = F.degraded_summary({"degraded": ["llm_explanations: ANTHROPIC_API_KEY not set"], "jev_available": False})
    assert d["claude"] and d["jev"]
    d = F.degraded_summary({"degraded": [], "jev_available": True, "jev_scores": {"quantitative": {"available": True}}})
    assert not d["claude"] and not d["jev"]


def test_wilson_matches_known_value():
    lo, hi = EA.wilson(3, 4)
    assert lo == pytest.approx(0.3006, abs=2e-3) and hi == pytest.approx(0.9544, abs=2e-3)
    assert EA.wilson(0, 0) is None


def test_adapter_ci_computed_only_when_missing_and_labelled():
    h = EA.headline({"metrics": {"precision": 0.75}, "confusion_matrix": {"TP": 3, "FP": 1, "TN": 5, "FN": 3}})
    assert h["precision"]["ci_source"].startswith("computed by UI")
    assert h["f1"]["value"] is None            # not reported -> not invented
    h = EA.headline({"metrics": {"precision": None}, "confusion_matrix": {"TP": 0, "FP": 0, "TN": 5, "FN": 3}})
    assert h["precision"]["value"] is None and h["precision"]["ci"] is None


def test_timing_average_only_positive_leads():
    t = EA.timing_of(SYNTH_EVAL, EA.cases_of(SYNTH_EVAL))
    assert t["average"] == 10.0 and len(t["positive"]) == 2 and len(t["detected"]) == 3 and t["n_fraud"] == 4
    assert EA.timing_of({"cases": [{"ticker": "F", "ground_truth": 1}]}, [{"ticker": "F", "ground_truth": 1}])["average"] is None


def test_timeline_chart_zones_and_flag_markers():
    st_ = load()
    fig = C.timeline_chart(st_["forensic_timeline"], st_["first_detection_year"], "light")
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert [(r.y0, r.y1) for r in rects] == [(0, 30), (30, 60), (60, 80), (80, 100)]
    names = [t.name for t in fig.data]
    assert "Suspicion score" in names and "Year with new flags" in names
    assert fig.layout.yaxis.range == (0, 100)
    assert list(fig.data[0].x) == [r["year"] for r in st_["forensic_timeline"]]
    # empty timeline degrades to a message, no crash
    assert len(C.timeline_chart([], None, "dark").layout.annotations) >= 1


def test_radar_needs_three_metrics_and_clips_with_note():
    z = {m: {"z_score": zz, "company_value": 1.0, "peer_mean": 0.5, "flag": abs(zz) > 2} for m, zz in
         (("gross_margin", 0.5), ("dso", 118.2), ("roa", -1.0))}
    fig, notes = C.radar_chart(z, "dark")
    assert fig.data and any("display clip" in n for n in notes)
    fig2, _ = C.radar_chart({"dso": z["dso"], "roa": z["roa"]}, "light")
    assert not fig2.data
    z["roa"]["z_score"] = None                      # undefined z is omitted, never plotted as 0
    fig3, _ = C.radar_chart(z, "light")
    assert not fig3.data


def test_banded_line_leaves_gaps_for_unavailable():
    fig = C.banded_line("t", [2018, 2019, 2020], [1.0, None, 2.0], [(None, 1.5, "a", "#0ca30c"), (1.5, None, "b", "#d03b3b")], "z", [False, False, True])
    assert list(fig.data[0].y) == [1.0, None, 2.0]


def test_risk_history_skips_missing_scores():
    fig, skipped = C.risk_history_chart([{"analysis_date": "2026-01-01", "suspicion_score": None, "risk_grade": "Low"},
                                         {"analysis_date": "2026-02-01", "suspicion_score": 40, "risk_grade": "Medium", "flags_fired": 3}])
    assert skipped == 1 and list(fig.data[0].y) == [40.0]


# ======================================================================================= demo mode + access gate
from app_components import demo as D  # noqa: E402

DEMO_BADGE_TEXT = "DEMO MODE: read-only, saved results only"


def _demo_at(page: str | None = None, **ss) -> AppTest:
    os.environ["FFA_DEMO_MODE"] = "1"
    return at_for(page, **ss)


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("YES", True), ("0", False), ("false", False), ("No", False)])
def test_demo_flag_explicit(monkeypatch, val, expected):
    monkeypatch.setenv("FFA_DEMO_MODE", val)
    monkeypatch.setenv("SEC_USER_AGENT", "Real App real.person@corp.org" if expected else "your@email")  # explicit flag wins
    assert D.demo_mode() is expected


@pytest.mark.parametrize("ua,expected", [
    (None, True), ("", True), ("YourApp your@email.com", True), ("Forensic Agent me@example.com", True), ("NoContactApp", True),
    ("ForensicAgent jane.doe@acme-research.org", False)])
def test_demo_auto_resolution(monkeypatch, ua, expected):
    monkeypatch.delenv("FFA_DEMO_MODE", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    if ua is not None:
        monkeypatch.setenv("SEC_USER_AGENT", ua)
    assert D.demo_mode() is expected


def test_demo_auto_reads_dotenv_without_importing_tools(monkeypatch, tmp_path):
    monkeypatch.delenv("FFA_DEMO_MODE", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    env = tmp_path / "x.env"
    env.write_text('# c\nSEC_USER_AGENT="ForensicAgent jane.doe@acme-research.org"\n', encoding="utf-8")
    monkeypatch.setenv("FFA_ENV_FILE", str(env))
    assert D.demo_mode() is False
    env.write_text("SEC_USER_AGENT=YourApp your@email.com\n", encoding="utf-8")
    assert D.demo_mode() is True


def test_check_code():
    assert D.check_code("anything", None) is True
    assert D.check_code("s3cret", "s3cret") is True
    assert D.check_code("wrong", "s3cret") is False
    assert D.check_code("", "s3cret") is False


def test_demo_page1_no_live_controls_and_samples_load():
    at = _demo_at().run()
    assert not at.exception
    assert at.text_input == [] and at.number_input == []
    assert "Run Forensic Analysis" not in [b.label for b in at.button]
    assert any("disabled in this public demo" in w.value for w in at.warning)
    assert any(DEMO_BADGE_TEXT in e.value for e in at.sidebar.error)
    assert any("research prototype" in m.value for m in at.sidebar.markdown)
    opts = at.selectbox(key="in_saved").options
    assert opts and all(o.startswith("sample_analysis/") for o in opts), opts
    assert [b.label for b in at.button if b.proto.type == "primary"] == ["Load saved analysis"]
    at.button(key="btn_load").click().run()
    assert not at.exception
    assert at.session_state["analysis"]["source"].startswith("saved file: sample_analysis/")
    assert any("Smoking guns" in s.value for s in at.subheader)


def test_demo_page2_read_only_and_no_db(tmp_path):
    at = _demo_at("Watchlist").run()
    assert not at.exception
    assert any("read-only in this public demo" in i.value for i in at.info)
    assert at.button == [] and at.text_input == [] and at.selectbox == []
    assert not (tmp_path / "wl.db").exists() and not list(tmp_path.glob("*.db"))


def test_demo_page3_selector_and_no_live_run():
    at = _demo_at("Retrospective Validation").run()
    assert not at.exception
    assert "Run live evaluation on the 12 development cases (~10-15 min)" not in [b.label for b in at.button]
    assert not any("Advanced: run a NEW live evaluation" in e.label for e in at.expander)
    assert any("running a new live evaluation is disabled" in c.value for c in at.caption)
    sel = at.selectbox(key="ev_set")
    assert len(sel.options) >= 3
    seen = {at.session_state["ev_set"]}
    for other in sel.options[1:3]:
        at.selectbox(key="ev_set").select(other).run()
        assert not at.exception
        assert any("Role:" in m.value for m in at.markdown)
        seen.add(at.session_state["ev_set"])
    assert len(seen) == 3


def test_demo_no_heavy_imports_subprocess(tmp_path):
    """Run all three pages in a fresh interpreter in demo mode; none of the live-only modules may get imported."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys, json\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from streamlit.testing.v1 import AppTest\n"
        f"at = AppTest.from_file({str(ROOT / 'app.py')!r}, default_timeout=90)\n"
        "at.run(); at.button(key='btn_load').click().run()\n"
        "assert not at.exception, at.exception\n"
        "for p in ('Watchlist', 'Retrospective Validation', 'Forensic Analysis'):\n"
        "    at.session_state['page'] = p; at.run(); assert not at.exception, (p, at.exception)\n"
        "bad = ('tools', 'graph', 'watchlist', 'agents', 'evaluation', 'langgraph', 'langchain', 'langchain_core', 'langchain_anthropic',\n"
        "       'anthropic', 'typesafe_sdk', 'spacy', 'apscheduler', 'bs4', 'lxml', 'dotenv', 'truststore')\n"
        "hit = sorted(m for m in sys.modules if m.split('.')[0] in bad)\n"
        "print('IMPORTED=' + json.dumps(hit))\n", encoding="utf-8")
    env = dict(os.environ, FFA_DEMO_MODE="1", WATCHLIST_DB_PATH=str(tmp_path / "wl.db"), FFA_ENV_FILE=str(tmp_path / "no.env"))
    import subprocess
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=240)
    assert r.returncode == 0, r.stderr[-2000:]
    line = next(l for l in r.stdout.splitlines() if l.startswith("IMPORTED="))
    assert json.loads(line[len("IMPORTED="):]) == [], line
    assert not (tmp_path / "wl.db").exists() and not list(tmp_path.glob("*.db"))


# ---- access gate (live mode)
def test_gate_absent_without_code():
    at = at_for().run()
    assert not at.exception
    assert not any("Unlock" in b.label for b in at.sidebar.button)
    assert at.text_input(key="in_ticker").disabled is False
    assert at.button(key="btn_run").disabled is False


def test_gate_wrong_code_blocks_then_right_code_unlocks(monkeypatch):
    monkeypatch.setenv("FFA_ACCESS_CODE", "open-sesame")
    at = at_for().run()
    assert not at.exception
    assert at.button(key="btn_run").disabled is True and at.text_input(key="in_ticker").disabled is True
    at.sidebar.text_input(key="gate_code").input("nope")
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert not at.session_state.filtered_state.get("ffa_unlocked")
    assert at.button(key="btn_run").disabled is True
    assert any("Wrong access code" in e.value for e in at.sidebar.error)
    at.sidebar.text_input(key="gate_code").input("open-sesame")
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert at.session_state["ffa_unlocked"] is True
    assert at.button(key="btn_run").disabled is False


def test_gate_locks_watchlist_and_eval_until_unlocked(monkeypatch, tmp_path):
    monkeypatch.setenv("FFA_ACCESS_CODE", "open-sesame")
    at = at_for("Watchlist").run()
    assert not at.exception
    assert any("locked" in w.value for w in at.warning)
    assert not (tmp_path / "wl.db").exists()
    at = at_for("Retrospective Validation").run()
    assert at.button(key="btn_eval").disabled is True
    at = at_for("Retrospective Validation", ffa_unlocked=True).run()
    assert at.button(key="btn_eval").disabled is False


def test_gate_ignored_in_demo_mode(monkeypatch):
    monkeypatch.setenv("FFA_ACCESS_CODE", "open-sesame")
    at = _demo_at().run()
    assert not at.exception
    assert len(at.sidebar.text_input) == 0
