"""Tests for agents/temporal_agent.py. All inputs are SYNTHETIC structure fixtures (flag names from CONTRACTS
section 4); expected numbers are worked out by hand in the comments."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.temporal_agent import (  # noqa: E402
    build_timeline,
    classify_trajectory,
    compute_temporal,
    flag_points,
    resolve_filing_date,
    risk_level,
    run_temporal,
    score_flags,
)

B, ALT, AUD, GC, CFO, CEO = (
    "quantitative.beneish",
    "quantitative.altman_distress",
    "network.auditor_change",
    "network.going_concern",
    "network.cfo_change",
    "network.ceo_change",
)


def _res(flags_by_year, **extra):
    d = {"severity": "Low", "flags_fired": 0, "flags_by_year": flags_by_year, "key_finding": "x"}
    d.update(extra)
    return d


# ---------------------------------------------------------------- scoring, worked examples

@pytest.mark.parametrize(
    "flags,expected",
    [
        ([], 0),
        (["quantitative.dso_growth"], 10),
        ([B], 30),  # 10 flag + 20 zone
        ([ALT], 25),  # 10 + 15
        ([AUD], 25),
        ([GC], 35),  # 10 + 25
        ([CFO], 20),  # 10 + 10
        ([CEO], 0),  # recorded, weight 0
        ([B, "quantitative.accruals", CFO], 60),  # 30 + 10 + 20 (docstring example)
        ([B, ALT, AUD, GC], 100),  # 30+25+25+35 = 115 -> cap
        (["language.hedging", "language.passive_voice", "language.specificity"], 30),
        (["peer.gross_margin", "peer.dso"], 20),
    ],
)
def test_score_table(flags, expected):
    assert score_flags(flags)[0] == expected


def test_cap_flagged_and_duplicates_not_double_counted():
    s, bd, capped = score_flags([B, ALT, AUD, GC])
    assert (s, capped) == (100, True) and sum(x["points"] for x in bd) == 115
    assert score_flags([B, B, B])[0] == 30  # a flag is a set member
    assert flag_points(GC) == 35 and flag_points(CEO) == 0


@pytest.mark.parametrize("score,lvl", [(0, "Low"), (29, "Low"), (30, "Medium"), (59, "Medium"),
                                       (60, "High"), (79, "High"), (80, "Critical"), (100, "Critical")])
def test_risk_level_thresholds(score, lvl):
    assert risk_level(score) == lvl


# ---------------------------------------------------------------- timeline / signal_change

def _tl(spec):
    fb = {y: set(f) for y, f in spec.items()}
    return build_timeline(sorted(spec), fb, set(spec))


def test_first_year_never_escalating_but_counts_new_flags():
    tl = _tl({2019: [B, GC]})
    e = tl[0]
    assert e["new_flags_this_year"] == sorted([B, GC])  # against the empty set
    assert e["signal_change"] == "Stable"
    assert e["suspicion_score"] == 65 and e["risk_level"] == "High"


def test_escalating_stable_improving():
    tl = _tl({
        2018: ["quantitative.accruals"],                     # 10
        2019: ["quantitative.accruals", B],                  # 40: new flag + score up -> Escalating
        2020: ["quantitative.accruals", B],                  # same -> Stable
        2021: ["quantitative.accruals"],                     # 10: fell 30 -> Improving
        2022: ["quantitative.accruals"],                     # Stable
    })
    assert [e["signal_change"] for e in tl] == ["Stable", "Escalating", "Stable", "Improving", "Stable"]
    assert tl[1]["new_flags_this_year"] == [B]
    assert tl[3]["new_flags_this_year"] == []


def test_improving_when_flag_count_falls_even_if_small_drop():
    tl = _tl({2018: ["language.hedging", "language.passive_voice"], 2019: ["language.hedging"]})
    assert tl[1]["signal_change"] == "Improving"  # score fell 10 and count fell


def test_swapped_flag_with_same_score_is_stable_not_escalating():
    tl = _tl({2018: ["language.hedging"], 2019: ["language.passive_voice"]})
    assert tl[1]["new_flags_this_year"] == ["language.passive_voice"]
    assert tl[1]["signal_change"] == "Stable"  # new flag but score did not rise


def test_ceo_change_is_flag_but_zero_points():
    tl = _tl({2018: [], 2019: [CEO]})
    assert tl[1]["suspicion_score"] == 0 and tl[1]["flags_fired"] == 1
    assert tl[1]["signal_change"] == "Stable"  # score did not rise


# ---------------------------------------------------------------- trajectory

@pytest.mark.parametrize(
    "scores,expected",
    [
        ([], "Unknown"),
        ([50], "Stable"),
        ([0, 10, 25, 40], "Escalating"),
        ([40, 30, 10], "Improving"),
        ([20, 20, 25], "Stable"),
        ([0, 40, 10, 50], "Volatile"),      # 2 reversals, range 50
        ([0, 10, 0, 10], "Stable"),         # 2 reversals but range 10 < 20, net 10 -> Escalating? see below
    ],
)
def test_trajectory(scores, expected):
    got = classify_trajectory(scores)
    if scores == [0, 10, 0, 10]:
        assert got == "Escalating"  # net +10, not volatile because amplitude < 20
    else:
        assert got == expected


def test_trajectory_zero_changes_ignored_for_reversals():
    assert classify_trajectory([0, 30, 30, 0, 30]) == "Volatile"


# ---------------------------------------------------------------- end to end (compute / run)

def _state(**kw):
    s = {
        "analysis_years": [2018, 2019, 2020, 2021, 2022],
        "focus_year": 2022,
        "filings": [
            {"fiscal_year": y, "filing_date": f"{y + 1}-02-{10 + i:02d}", "form": "10-K"}
            for i, y in enumerate([2018, 2019, 2020, 2021, 2022])
        ],
    }
    s.update(kw)
    return s


def test_full_run_inflection_and_filing_date():
    state = _state(
        quantitative_result=_res(
            {2018: [], 2019: ["quantitative.accruals"], 2020: ["quantitative.accruals", B], 2021: [B], 2022: [B]},
            beneish_scores={2020: {"zone": "manipulator", "flag": True}, 2019: {"zone": "grey", "flag": False}},
            altman_scores={2018: {"zone": "safe"}},
        ),
        language_result=_res({2018: [], 2019: [], 2020: ["language.hedging"], 2021: [], 2022: []}),
        network_result=_res(
            {2018: [], 2019: [], 2020: [AUD], 2021: [], 2022: []},
            auditor_history={2020: {"name": "X", "changed": True}},
            executive_changes={2021: {"cfo_changed": True, "ceo_changed": False}},
            going_concern={2022: {"detected": True}},
        ),
        peer_result=_res({2022: ["peer.dso", "peer.gross_margin"]}, outlier_metrics=["dso", "gross_margin"]),
    )
    out = run_temporal(state)
    r = out["temporal_result"]
    tl = {e["year"]: e for e in r["timeline"]}
    # 2018: 0 ; 2019: accruals 10 ; 2020: accruals 10 + beneish 30 + hedging 10 + auditor 25 = 75
    assert [tl[y]["suspicion_score"] for y in (2018, 2019, 2020)] == [0, 10, 75]
    # 2021: beneish 30 + cfo_change 20 (structured only, flag derived) = 50 ; 2022: beneish 30 + GC 35 + 2 peer 20 = 85
    assert tl[2021]["suspicion_score"] == 50 and tl[2022]["suspicion_score"] == 85
    assert tl[2020]["signal_change"] == "Escalating" and tl[2020]["risk_level"] == "High"
    assert tl[2021]["signal_change"] == "Improving"  # 75 -> 50 falls 25
    assert tl[2022]["risk_level"] == "Critical" and tl[2022]["signal_change"] == "Escalating"
    assert r["first_detection_year"] == 2020 and out["first_detection_year"] == 2020
    # 2020's own filing = fiscal_year 2020 -> index 2 -> 2021-02-12
    assert out["first_detection_filing_date"] == "2021-02-12" and r["filing_date_is_proxy"] is False
    assert out["suspicion_score"] == 85 == r["suspicion_score"]
    assert r["years_of_elevated_risk"] == 3  # 75, 50, 85
    assert r["inputs_available"] == {"quantitative": True, "language": True, "network": True, "peer": True}
    assert out["forensic_timeline"] == r["timeline"]
    assert "FY2020" in r["key_finding"]
    assert out["agent_trace"][0]["agent"] == "temporal" and out["agent_trace"][0]["status"] == "ok"
    assert out["degraded"] == []


def test_peer_flags_attach_to_focus_year_only():
    out = compute_temporal(_state(peer_result=_res({2020: ["peer.dso"]}, outlier_metrics=["dso"])))
    tl = {e["year"]: e for e in out["timeline"]}
    assert tl[2022]["flags"] == ["peer.dso"] and tl[2020]["flags"] == []


def test_missing_inputs_degrade_not_crash():
    out = run_temporal(_state(network_result=_res({2020: [GC]}, going_concern={2020: {"detected": True}})))
    r = out["temporal_result"]
    assert r["inputs_available"] == {"quantitative": False, "language": False, "network": True, "peer": False}
    tl = {e["year"]: e for e in r["timeline"]}
    assert tl[2020]["suspicion_score"] == 35  # not double counted: flag + structured field
    assert tl[2019]["data_available"] is False  # no network row for 2019 -> no data
    assert len(out["degraded"]) == 3 and out["agent_trace"][0]["status"] == "degraded"
    assert "Scored without" in r["key_finding"]


def test_all_missing_or_unavailable():
    out = run_temporal({"analysis_years": [2020, 2021], "focus_year": 2021,
                        "quantitative_result": {"unavailable": True, "error": "x", "flags_by_year": {}}})
    r = out["temporal_result"]
    assert out["suspicion_score"] == 0 and r["signal_trajectory"] == "Unknown"
    assert out["first_detection_year"] is None and r["years_of_elevated_risk"] == 0
    assert "unavailable" in r["key_finding"].lower()
    assert all(not e["data_available"] for e in r["timeline"])


def test_empty_state_and_garbage_never_raise():
    for st in ({}, {"quantitative_result": "junk", "network_result": [1, 2], "focus_year": "abc"},
               {"language_result": {"flags_by_year": {"x": 5, "2020": None}}, "filings": "nope"}):
        out = run_temporal(st)
        assert out["temporal_result"] is not None and "agent_trace" in out


def test_internal_exception_is_contained(monkeypatch):
    import agents.temporal_agent as ta

    monkeypatch.setattr(ta, "compute_temporal", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    out = ta.run_temporal({})
    assert out["temporal_result"]["unavailable"] is True and out["agent_trace"][0]["status"] == "error"
    assert out["suspicion_score"] == 0


def test_no_inflection_when_never_escalating_to_40():
    out = compute_temporal(_state(language_result=_res({2018: [], 2019: ["language.hedging"], 2020: ["language.hedging"],
                                                        2021: [], 2022: []})))
    assert out["first_detection_year"] is None and out["first_detection_filing_date"] is None
    assert "No year" in out["key_finding"]


def test_first_year_over_40_is_not_inflection():
    out = compute_temporal(_state(network_result=_res({2018: [GC, AUD], 2019: [GC, AUD]})))
    # 2018 scores 60 but is the first year (cannot be Escalating); 2019 same flags -> Stable
    assert out["first_detection_year"] is None


def test_string_keys_accepted_and_json_serialisable():
    out = run_temporal(_state(
        quantitative_result=_res({"2018": [], "2019": [B]}),
        network_result=_res({"2019": [CFO]}),
    ))
    assert out["first_detection_year"] == 2019  # 0 -> 50 with new flags
    json.dumps(out, allow_nan=False)  # int keys are fine (coerced by json)
    json.dumps(out["temporal_result"], allow_nan=False)


# ---------------------------------------------------------------- filing date resolution

def test_filing_date_own_vs_proxy_vs_none():
    filings = [{"fiscal_year": 2019, "filing_date": "2020-03-01"}, {"fiscal_year": 2021, "filing_date": "2022-03-05"}]
    assert resolve_filing_date(2019, filings, {})[:2] == ("2020-03-01", False)
    assert resolve_filing_date(2020, filings, {})[:2] == ("2022-03-05", True)  # comparative-filled -> next filing
    assert resolve_filing_date(2022, filings, {})[:2] == (None, False)


def test_filing_date_metadata_fallback_when_no_filings():
    meta = {2020: {"date": "2021-02-20"}, 2021: {"filing_date": "2022-02-21"}}
    assert resolve_filing_date(2020, [], meta)[:2] == ("2021-02-20", False)
    assert resolve_filing_date(2019, [], meta)[:2] == ("2021-02-20", True)


def test_inflection_year_without_own_filing_marks_proxy():
    state = _state(network_result=_res({2018: [], 2019: [GC, AUD]}))
    state["filings"] = [f for f in state["filings"] if f["fiscal_year"] != 2019]
    out = run_temporal(state)
    assert out["first_detection_year"] == 2019
    assert out["temporal_result"]["filing_date_is_proxy"] is True
    assert out["first_detection_filing_date"] == "2021-02-12"  # FY2020's filing
    assert any("proxy" in d for d in out["degraded"])


# ============================================================================ v2 (docs/V2_CHANGELOG_agents.md B5, B8/B2)
def test_v2_peer_only_new_flags_do_not_make_the_year_escalating():
    # peer flags exist only for the focus year (absent earlier), so they are always "new" - they must not set Escalating
    fb = {2019: {"language.hedging"}, 2020: {"language.hedging", "peer.dso", "peer.roa"}}
    tl = build_timeline([2019, 2020], fb, {2019, 2020})
    e = tl[1]
    assert e["suspicion_score"] == 30 and tl[0]["suspicion_score"] == 10  # peer flags still ADD to the score
    assert e["new_flags_this_year"] == ["peer.dso", "peer.roa"]            # still displayed
    assert e["signal_change"] == "Stable"


def test_v2_real_new_flag_plus_peer_flag_still_escalates():
    fb = {2019: set(), 2020: {CFO, "peer.dso"}}
    tl = build_timeline([2019, 2020], fb, {2019, 2020})
    assert tl[1]["signal_change"] == "Escalating"


def test_v2_peer_only_run_not_escalating_end_to_end():
    st = _state(peer_result=_res({2022: ["peer.dso"]}, outlier_metrics=["dso"]))
    r = compute_temporal(st)
    tl = {e["year"]: e for e in r["timeline"]}
    assert tl[2022]["signal_change"] != "Escalating" and r["focus_signal_change"] != "Escalating"


def _shell_state(entity_flags, **kw):
    s = _state(
        network_result=_res({2018: [GC], 2019: [AUD, CFO], 2020: []},
                            auditor_history={2019: {"changed": True}}, executive_changes={2019: {"cfo_changed": True}},
                            going_concern={2018: {"detected": True}}),
        language_result=_res({2018: [], 2019: [], 2020: []}),
        quantitative_result=_res({2018: [], 2019: [], 2020: []}),
        analysis_years=[2018, 2019, 2020], focus_year=2020,
    )
    s["filing_entity_flags"] = entity_flags
    s.update(kw)
    return s


def test_v2_shell_year_is_not_a_baseline_and_never_a_detection():
    # 2018 = SPAC shell (going concern clause), 2019 = first operating filing (auditor + CFO "changed" vs shell)
    st = _shell_state({2018: {"is_shell": True, "spac_predecessor": False, "reason": "blank check"}})
    r = compute_temporal(st)
    tl = {e["year"]: e for e in r["timeline"]}
    assert tl[2018]["data_available"] is False and tl[2018]["excluded_shell"] is True and tl[2018]["suspicion_score"] == 0
    assert "blank check" in tl[2018]["exclusion_reason"]
    assert tl[2019]["signal_change"] == "Stable"   # no valid prior year: first operating year can never be Escalating
    assert r["first_detection_year"] is None
    assert r["excluded_entity_years"] == {2018: "blank check"}
    # without the flags the shell comparison escalates and is detected
    r0 = compute_temporal(_shell_state({}))
    assert {e["year"]: e for e in r0["timeline"]}[2019]["signal_change"] == "Escalating"
    assert r0["first_detection_year"] == 2019


def test_v2_spac_predecessor_flag_also_excludes_and_string_keys_ok():
    st = _shell_state({"2018": {"is_shell": False, "spac_predecessor": True, "reason": "SPAC"}})
    r = compute_temporal(st)
    assert r["excluded_entity_years"] == {2018: "SPAC"}
    json.dumps(r, default=str)


def test_v2_shell_year_excluded_from_trajectory_and_elevated_count():
    st = _shell_state({2018: {"is_shell": True, "spac_predecessor": False, "reason": "shell"}})
    r = compute_temporal(st)
    assert r["years_of_elevated_risk"] == 1  # only 2019 (auditor 25 + cfo 20 = 45); the shell's 35 is not counted


def test_v2_missing_or_malformed_entity_flags_are_tolerated():
    for bad in (None, {}, "x", {2018: None}, {2018: "oops"}, {"abc": {"is_shell": True}}, []):
        r = compute_temporal(_shell_state(bad))
        assert r["excluded_entity_years"] == {}
    assert compute_temporal({k: v for k, v in _shell_state({}).items() if k != "filing_entity_flags"})["timeline"]
