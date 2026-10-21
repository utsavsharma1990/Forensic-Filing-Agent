"""Tests for tools/jev_scorer.py (mocked SystemOneResponse; live test only if a key is set)."""

from __future__ import annotations

import json
import os
from unittest import mock

import httpx2
import pytest
from typesafe_sdk import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeRateLimitError,
    Usage,
)

from tools import jev_scorer as js

_LIVE_KEY = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
LEGEND0 = {0: "no basis", 1: "weak", 2: "moderate", 3: "high", 4: "overwhelming"}
LEGEND1 = {1: "no basis", 2: "weak", 3: "moderate", 4: "high", 5: "overwhelming"}


def make_response(choice="Strong", score=3.0, legend=None, noul=0.8, drop=()):
    answers = {
        "evidence_strength": ChoiceAnswer(choice=choice, confidence=0.7, probabilities={choice: 0.7}),
        "confidence": ScoreAnswer(
            score=score, confidence=0.6, legend=legend or LEGEND0, probabilities={0: 0.1, 1: 0.9}
        ),
        "material_change": NoulAnswer(noul=noul),
    }
    for d in drop:
        answers.pop(d)
    return SystemOneResponse(model="jev-test", usage=Usage(), answers=answers)


def api_error(cls, status):
    return cls(status, {}, httpx2.Headers(), "boom")


QUANT = {
    "severity": "High",
    "flags_fired": 3,
    "focus_year": 2019,
    "flags_by_year": {2018: ["quantitative.accruals"], 2019: ["quantitative.beneish", "quantitative.dso_growth"]},
    "key_finding": "Beneish M-score above -1.78 in FY2019.",
    "beneish_scores": {2018: {"score": -2.5, "flag": False}, 2019: {"score": -1.2, "zone": "manipulator", "flag": True}},
    "data_quality": {"unavailable": {"altman": "market cap missing"}},
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(js, "_load_env", None)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def with_client(response=None, exc=None):
    client = mock.Mock()
    if exc is not None:
        client.system_one.side_effect = exc
    else:
        client.system_one.return_value = response
    return client, mock.patch.object(js, "_make_client", return_value=client)


# ---- normalisation


@pytest.mark.parametrize(
    "score,legend,expected",
    [
        (0, LEGEND0, 0.0), (2, LEGEND0, 50.0), (4, LEGEND0, 100.0), (3.0, LEGEND0, 75.0),
        (1, LEGEND1, 0.0), (3, LEGEND1, 50.0), (5, LEGEND1, 100.0), (4.5, LEGEND1, 87.5),
        (9, LEGEND0, 100.0), (-3, LEGEND1, 0.0),  # clamped
        (2, {"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"}, 50.0),  # str keys
    ],
)
def test_normalize_score(score, legend, expected):
    assert js.normalize_score(score, legend) == expected


@pytest.mark.parametrize("score,legend", [(2, {}), (2, None), (2, {1: "x"}), (None, LEGEND0), (float("nan"), LEGEND0), ("a", LEGEND0)])
def test_normalize_score_unusable(score, legend):
    assert js.normalize_score(score, legend) is None


def test_noul_to_bool():
    assert js.noul_to_bool(0.5) is True and js.noul_to_bool(0.49) is False
    assert js.noul_to_bool(None) is None and js.noul_to_bool(float("nan")) is None


# ---- state & questions


def test_state_compact_and_no_text():
    state = js.build_state("quantitative", QUANT, {"severity": "Low", "flags_by_year": {}, "key_finding": "x"})
    blob = json.dumps(state)
    assert len(blob.encode()) <= js.MAX_STATE_BYTES
    assert state["prior_year_available"] is True and "prior_year" in state
    assert state["current"]["headline"]["beneish_scores"]["year"] == 2019
    assert state["current"]["headline"]["beneish_scores"]["score"] == -1.2
    assert state["current"]["flags_by_year"]["2019"] == ["quantitative.beneish", "quantitative.dso_growth"]
    assert state["current"]["unavailable_metrics"] == ["altman"]


def test_state_without_prior():
    state = js.build_state("quantitative", QUANT, None)
    assert state["prior_year_available"] is False and "prior_year" not in state


def test_state_truncates_huge_input():
    big = dict(QUANT, key_finding="x" * 50000, flags_by_year={y: [f"f{i}" for i in range(50)] for y in range(1990, 2030)})
    assert len(json.dumps(js.build_state("quantitative", big, big)).encode()) <= js.MAX_STATE_BYTES


def test_questions_shape_and_prior_wording():
    q = js.build_questions("network", True)
    assert set(q) == {"evidence_strength", "confidence", "material_change"}
    assert list(q["evidence_strength"].criteria) == list(js.EVIDENCE_LEVELS)
    assert len(q["confidence"].criteria) == 5
    assert "unavailable" in js.build_questions("peer", False)["material_change"].instructions
    texts = {a: js.build_questions(a, True)["evidence_strength"].instructions for a in js.AGENT_NAMES}
    assert len(set(texts.values())) == 5  # agent-specific wording


# ---- single-agent paths


def test_success_zero_based():
    client, p = with_client(make_response(score=3.0, legend=LEGEND0, noul=0.9))
    with p:
        r = js.score_one("quantitative", QUANT, {"severity": "Low"}, api_key="k")
    assert r == {
        "evidence_strength": "Strong", "confidence_score": 75.0, "material_change": True,
        "jev_latency_ms": r["jev_latency_ms"], "available": True, "error": None, "model": "jev-test",
    }
    assert r["jev_latency_ms"] >= 0
    kwargs = client.system_one.call_args.kwargs
    assert set(kwargs["questions"]) == {"evidence_strength", "confidence", "material_change"}
    assert isinstance(kwargs["state"], dict)


def test_success_one_based_and_no_prior_gives_none_material_change():
    _, p = with_client(make_response(choice="definitive", score=5.0, legend=LEGEND1, noul=0.99))
    with p:
        r = js.score_one("language", QUANT, None, api_key="k")
    assert r["evidence_strength"] == "Definitive" and r["confidence_score"] == 100.0
    assert r["material_change"] is None and r["available"] is True and r["error"] is None


def test_partial_answers():
    _, p = with_client(make_response(drop=("confidence", "material_change")))
    with p:
        r = js.score_one("peer", QUANT, {"severity": "None"}, api_key="k")
    assert r["available"] is True and r["evidence_strength"] == "Strong"
    assert r["confidence_score"] is None and r["material_change"] is None
    assert "partial response" in r["error"]


def test_only_score_answered_is_available_with_unavailable_evidence():
    _, p = with_client(make_response(drop=("evidence_strength",)))
    with p:
        r = js.score_one("peer", QUANT, None, api_key="k")
    assert r["available"] is True and r["evidence_strength"] == "Unavailable" and r["confidence_score"] == 75.0


def test_unknown_choice_label_and_degenerate_legend():
    _, p = with_client(make_response(choice="Maybe", legend={0: "x"}))
    with p:
        r = js.score_one("peer", QUANT, None, api_key="k")
    assert r["available"] is False and r["evidence_strength"] == "Unavailable"
    assert "unrecognised" in r["error"]


def test_empty_answers_malformed():
    resp = SystemOneResponse(model="m", usage=Usage(), answers={})
    _, p = with_client(resp)
    with p:
        r = js.score_one("peer", QUANT, None, api_key="k")
    assert r["available"] is False and "no answers" in r["error"]
    _, p = with_client(object())
    with p:
        assert js.score_one("peer", QUANT, None, api_key="k")["available"] is False


@pytest.mark.parametrize(
    "exc,needle",
    [
        (api_error(TypeSafeAuthenticationError, 401), "authentication"),
        (api_error(TypeSafeRateLimitError, 429), "rate limit"),
        (TypeSafeAPITimeoutError(15.0), "timed out"),
        (RuntimeError("weird"), "weird"),
    ],
)
def test_error_classes(exc, needle):
    _, p = with_client(exc=exc)
    with p:
        r = js.score_one("temporal", QUANT, None, api_key="k")
    assert r["available"] is False and r["evidence_strength"] == "Unavailable"
    assert r["confidence_score"] is None and r["material_change"] is None
    assert needle in r["error"].lower()
    assert isinstance(r["jev_latency_ms"], int)


def test_client_construction_failure_never_raises():
    with mock.patch.object(js, "_make_client", side_effect=ValueError("bad")):
        r = js.score_one("peer", QUANT, None, api_key="k")
    assert r["available"] is False and "bad" in r["error"]


def test_empty_and_unavailable_agent_results():
    assert js.score_one("peer", {}, None, api_key="k")["available"] is False
    assert js.score_one("peer", None, None, api_key="k")["available"] is False
    r = js.score_one("peer", {"unavailable": True, "error": "no peers"}, None, api_key="k")
    assert r["available"] is False and "no peers" in r["error"]


# ---- no key / sdk missing / concurrency


def test_no_key_is_deterministic():
    out = js.score_agents({"quantitative": QUANT, "language": QUANT})
    assert set(out) == {"quantitative", "language"}
    for r in out.values():
        assert r["available"] is False and r["evidence_strength"] == "Unavailable"
        assert r["error"] == "JEV_API_KEY not set" and r["model"] is None
    assert out == js.score_agents({"quantitative": QUANT, "language": QUANT})


def test_typesafe_key_alias(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", " abc ")
    assert js.get_api_key() == "abc"
    monkeypatch.setenv("JEV_API_KEY", "jev")
    assert js.get_api_key() == "jev"


def test_sdk_missing(monkeypatch):
    monkeypatch.setattr(js, "_SDK_ERROR", "typesafe-sdk not importable")
    monkeypatch.setenv("JEV_API_KEY", "k")
    out = js.score_agents({"peer": QUANT})
    assert out["peer"]["available"] is False and "not importable" in out["peer"]["error"]


def test_score_agents_concurrent_mixed(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k")

    def fake_client(_key):
        c = mock.Mock()

        def system_one(state, questions):
            if state["agent"] == "network":
                raise TypeSafeAPITimeoutError(15.0)
            return make_response(choice="Suggestive", score=2.0)

        c.system_one.side_effect = system_one
        return c

    monkeypatch.setattr(js, "_make_client", fake_client)
    results = {a: QUANT for a in js.AGENT_NAMES}
    out = js.score_agents(results, {"quantitative": {"severity": "Low"}})
    assert list(out) == list(js.AGENT_NAMES)
    assert out["network"]["available"] is False
    assert out["quantitative"]["material_change"] is True  # prior supplied
    assert out["language"]["material_change"] is None  # no prior
    assert all(out[a]["available"] for a in js.AGENT_NAMES if a != "network")
    assert out["peer"]["confidence_score"] == 50.0


def test_score_agents_garbage_inputs():
    assert js.score_agents({}) == {}
    assert js.score_agents(None) == {}  # type: ignore[arg-type]


# ---- summarize


def _s(ev, conf, avail=True):
    return {"evidence_strength": ev, "confidence_score": conf, "material_change": None,
            "jev_latency_ms": 1, "available": avail, "error": None, "model": "m"}


def test_summarize():
    summ = js.summarize_jev({
        "quantitative": _s("Strong", 80.0), "language": _s("Suggestive", 40.0),
        "network": _s("Definitive", None), "peer": _s("Unavailable", None, avail=False),
    })
    assert summ == {"mean_confidence": 60.0, "available_count": 3, "any_available": True,
                    "strong_agents": ["quantitative", "network"]}
    assert js.summarize_jev({}) == {"mean_confidence": None, "available_count": 0,
                                    "any_available": False, "strong_agents": []}
    assert js.summarize_jev(None)["any_available"] is False


# ---- live (only with a key)


@pytest.mark.skipif(not _LIVE_KEY,
                    reason="no Jev key: live call not tested")
def test_live_single_call(monkeypatch):  # pragma: no cover - requires network + key
    monkeypatch.setenv("JEV_API_KEY", _LIVE_KEY)
    monkey = js.score_one("quantitative", QUANT, {"severity": "Low", "key_finding": "none"})
    print("LIVE:", monkey)
    assert monkey["available"] is True
    assert 0 <= (monkey["confidence_score"] or 0) <= 100
