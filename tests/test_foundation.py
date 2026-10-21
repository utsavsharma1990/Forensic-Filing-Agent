"""Tests for tools.common, tools.llm (mocked; no API key needed) and agents.state."""
from __future__ import annotations

import json
import math

import pytest

from agents import state as st
from tools import common, llm


# ------------------------------------------------------------------ common
def test_safe_div_never_raises_or_returns_nan():
    assert common.safe_div(1, 2) == 0.5
    for a, b in [(None, 1), (1, None), (1, 0), (float("nan"), 1), (1, float("inf")), ("x", 1)]:
        assert common.safe_div(a, b) is None


def test_risk_rank_and_order():
    assert common.RISK_ORDER == ["Low", "Medium", "High", "Critical"]
    assert [common.risk_rank(g) for g in ("Low", "medium", "HIGH", "Critical", None, "weird")] == [0, 1, 2, 3, -1, -1]


def test_dates():
    from datetime import date, datetime
    assert common.ISO(date(2020, 9, 26)) == "2020-09-26"
    assert common.ISO(datetime(2020, 9, 26, 5, 0)) == "2020-09-26"
    assert common.ISO("2020-09-26T10:00:00Z") == "2020-09-26"
    assert common.ISO(None) is None and common.ISO("nope") is None
    assert common.parse_date("2020-09-26") == date(2020, 9, 26) and common.parse_date("") is None


def test_flatten_year():
    flat = common.flatten_year({"Revenue": {"value": 5.0}, "COGS": {"value": float("nan")}, "NetIncome": 3})
    assert flat["Revenue"] == 5.0 and flat["COGS"] is None and flat["NetIncome"] == 3.0 and flat["TotalAssets"] is None
    assert set(common.CANONICAL_ITEMS) <= set(flat)
    assert all(v is None or math.isfinite(v) for v in flat.values())


def test_constants_and_paths():
    assert common.MODEL_HAIKU == "claude-haiku-4-5-20251001" and common.MODEL_SONNET == "claude-sonnet-5-5"
    assert (common.PROJECT_ROOT / "tools" / "common.py").exists()
    assert common.CACHE_DIR.name == ".cache" or "EDGAR_CACHE_DIR" in __import__("os").environ


# ------------------------------------------------------------------ llm
@pytest.fixture
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "CACHE_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_llm_no_key_is_deterministic_none(llm_env):
    assert llm.llm_available() is False
    assert llm.llm_json("haiku", "sys", "user") is None
    assert llm.llm_text("sonnet", "sys", "user") is None


def test_llm_placeholder_key_is_not_a_key(llm_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key")
    assert llm.llm_available() is False


def test_llm_json_parse_repair_cache_and_retry(llm_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    calls = {"n": 0}

    def fake(model, system, user, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        if calls["n"] == 2:
            return "no json here"
        return 'Sure!\n```json\n{"score": 7, "reason": "specific",}\n```'

    monkeypatch.setattr(llm, "_call_model", fake)
    out = llm.llm_json("haiku", "sys", "user")
    assert out == {"score": 7, "reason": "specific"} and calls["n"] == 3
    # cached: no further calls, and works even if the key disappears (deterministic reruns)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm.llm_json("haiku", "sys", "user") == {"score": 7, "reason": "specific"} and calls["n"] == 3
    assert list((llm_env / "llm").glob("*.json"))
    # different model tier -> different cache key
    assert llm.llm_json("sonnet", "sys", "user") is None


def test_llm_never_raises_when_everything_fails(llm_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "_call_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert llm.llm_json("haiku", "s", "u") is None
    assert llm.llm_text("haiku", "s", "u") is None


def test_llm_text_cached(llm_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    n = {"c": 0}
    monkeypatch.setattr(llm, "_call_model", lambda *a, **k: (n.__setitem__("c", n["c"] + 1) or "  hello  "))
    assert llm.llm_text("haiku", "s", "u") == "hello" and llm.llm_text("haiku", "s", "u") == "hello" and n["c"] == 1


# ------------------------------------------------------------------ state
def test_new_state_defaults_and_reducers():
    s = st.new_state("aapl", 5, end_year=2022, as_of="2022-12-31")
    assert s["ticker"] == "AAPL" and s["analysis_years"] == [2018, 2019, 2020, 2021, 2022] and s["focus_year"] == 2022
    assert s["agent_trace"] == [] and s["degraded"] == [] and s["warnings"] == [] and s["risk_changed"] is False
    hints = st.ForensicAgentState.__annotations__
    for k in ("agent_trace", "degraded", "warnings"):
        assert "Annotated" in str(hints[k]) or hasattr(hints[k], "__metadata__")
    for k in ("as_of", "focus_year", "filings", "degraded", "warnings", "jev_available", "agent_severity", "smoking_gun_evidence",
              "suspicion_score", "first_detection_year", "first_detection_filing_date", "quantitative_result", "temporal_result"):
        assert k in hints


def test_json_roundtrip_int_keys():
    s = st.new_state("X", 3, end_year=2020)
    s["filing_texts"] = {2019: "a", 2020: "b"}
    s["quantitative_result"] = {"beneish_scores": {2019: {"score": float("nan")}, 2020: {"score": -1.5}}, "flags_by_year": {2020: ["q"]}}
    j = st.to_jsonable(s)
    text = json.dumps(j)                       # must be strictly serialisable
    assert "NaN" not in text
    assert set(j["filing_texts"]) == {"2019", "2020"}
    back = st.from_jsonable(json.loads(text))
    assert back["filing_texts"] == {2019: "a", 2020: "b"}
    assert back["quantitative_result"]["flags_by_year"] == {2020: ["q"]}
    assert back["quantitative_result"]["beneish_scores"][2019]["score"] is None


def test_state_works_in_a_langgraph_parallel_fanout():
    from langgraph.graph import END, START, StateGraph

    def mk(name):
        return lambda s: {"agent_trace": [{"agent": name}], "degraded": [f"{name}: x"]}

    g = StateGraph(st.ForensicAgentState)
    for n in ("a", "b", "c"):
        g.add_node(n, mk(n))
        g.add_edge(START, n)
        g.add_edge(n, "join")
    g.add_node("join", lambda s: {"final_narrative": "ok"})
    g.add_edge("join", END)
    out = g.compile().invoke(st.new_state("T", 1))
    assert sorted(t["agent"] for t in out["agent_trace"]) == ["a", "b", "c"]
    assert len(out["degraded"]) == 3 and out["final_narrative"] == "ok"
