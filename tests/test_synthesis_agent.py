"""Tests for agents/synthesis_agent.py.

ALL agent-result fixtures here are SYNTHETIC, built from the contract shape (CONTRACTS section 4) with invented marker values
(they are not real company data). Assumed result fields: severity, unavailable, flags_fired, flags_by_year, focus_year,
key_finding, data_quality.unavailable, degraded, evidence[{flag, year, metric, value, display, numbers, peer_pct?}];
temporal: timeline[{year, suspicion_score, risk_level, signal_change}], signal_trajectory, first_detection_year.
Jev and the LLM are mocked; no network or keys are used.
"""

from __future__ import annotations

import pytest

from agents import synthesis_agent as sa
from prompts.templates import PATTERN_TABLE

FY = 2020


def ev(flag, metric="metric", value=1.5, display="1.50", year=FY, **kw):
    d = {"flag": flag, "year": year, "metric": metric, "value": value, "display": display, "numbers": [display]}
    d.update(kw)
    return d


def res(severity="None", flags=None, evidence=None, key="finding", **kw):
    flags = flags or {}
    r = {
        "severity": severity, "flags_by_year": flags, "flags_fired": sum(len(v) for v in flags.values()),
        "focus_year": FY, "key_finding": key, "data_quality": {"unavailable": {}}, "degraded": [],
        "evidence": evidence or [],
    }
    r.update(kw)
    return r


def unavailable(name):
    return {"error": "boom", "unavailable": True, "severity": "None", "flags_fired": 0, "flags_by_year": {},
            "key_finding": f"{name} unavailable: boom"}


def temporal(change="Stable", traj="Stable"):
    return {
        "timeline": [
            {"year": FY - 1, "suspicion_score": 10, "risk_level": "Low", "signal_change": "Stable"},
            {"year": FY, "suspicion_score": 45, "risk_level": "Medium", "signal_change": change},
        ],
        "signal_trajectory": traj, "first_detection_year": None, "years_of_elevated_risk": 1,
        "key_finding": "temporal finding", "severity": "None", "flags_by_year": {},
    }


def make_state(q=None, l=None, n=None, p=None, t=None, **extra):
    s = {
        "ticker": "TEST", "company_name": "Test Corp", "analysis_years": [FY - 1, FY], "focus_year": FY,
        "quantitative_result": q or res(), "language_result": l or res(), "network_result": n or res(),
        "peer_result": p or res(), "temporal_result": t or temporal(), "degraded": [],
    }
    s.update(extra)
    return s


def jev_ok(conf=90.0):
    return {a: {"evidence_strength": "Strong", "confidence_score": conf, "material_change": True,
                "jev_latency_ms": 5, "available": True, "error": None, "model": "m"} for a in sa.ALL_AGENTS}


def jev_off():
    return {a: {"evidence_strength": "Unavailable", "confidence_score": None, "material_change": None,
                "jev_latency_ms": 0, "available": False, "error": "JEV_API_KEY not set", "model": None}
            for a in sa.ALL_AGENTS}


@pytest.fixture(autouse=True)
def mocks(monkeypatch):
    """Default: Jev unavailable, no LLM. Tests override via the returned holder."""
    holder = {"jev": jev_off(), "llm": None, "llm_calls": []}
    monkeypatch.setattr(sa.jev_scorer, "score_agents", lambda *a, **k: holder["jev"])

    def fake_llm(tier, system, user, max_tokens=1500):
        holder["llm_calls"].append((tier, system, user))
        v = holder["llm"]
        return v(user) if callable(v) else v

    monkeypatch.setattr(sa, "llm_text", fake_llm)
    return holder


# --------------------------------------------------------------------------------------- compute_risk_grade
@pytest.mark.parametrize(
    "flagging,high,esc,jev,avail,flagged,grade,rule",
    [
        (3, 3, False, 85.0, True, True, "Critical", "Critical rule"),
        (3, 3, False, 80.0, True, True, "High", "Critical gate is not met"),  # not strictly > 80
        (4, 4, True, 99.0, True, True, "Critical", "Critical rule"),
        (3, 3, False, None, False, True, "High", "capped at High"),
        (2, 0, True, None, False, True, "High", "High rule"),
        (2, 2, False, None, False, True, "Medium", "Medium rule"),
        (1, 1, True, 95.0, True, True, "Medium", "Medium rule"),  # one agent only: not High even if escalating
        (1, 0, False, None, False, True, "Medium", "Medium rule"),
        (0, 0, True, None, False, True, "Medium", "focus-year escalation"),
        (0, 0, True, None, False, False, "Low", "Low"),
        (0, 0, False, 95.0, True, False, "Low", "Low"),
    ],
)
def test_compute_risk_grade_rules(flagging, high, esc, jev, avail, flagged, grade, rule):
    out = sa.compute_risk_grade(flagging, high, esc, jev, avail, flagged)
    assert out["grade"] == grade
    assert rule in out["rationale"]


def test_critical_blocked_note_only_when_jev_unavailable():
    assert "critical_blocked: Jev unavailable" in sa.compute_risk_grade(3, 3, False, None, False)["degraded"]
    assert sa.compute_risk_grade(3, 3, False, 70.0, True)["degraded"] == []
    assert sa.compute_risk_grade(1, 0, False, None, False)["degraded"] == []


# --------------------------------------------------------------------------------------- end-to-end grades
def test_grade_low_no_evidence(mocks):
    out = sa.run_synthesis(make_state())
    assert out["risk_grade"] == "Low"
    assert out["smoking_guns"] == [] and out["smoking_gun_evidence"] == []
    assert out["jev_available"] is False
    assert len(out["final_narrative"].split("\n\n")) == 3
    assert any(d.startswith("narrative: deterministic fallback") for d in out["degraded"])
    assert out["agent_trace"][0]["agent"] == "synthesis"


def test_grade_medium(mocks):
    q = res("Medium", {FY: ["quantitative.dso_growth", "quantitative.accruals"]})
    out = sa.run_synthesis(make_state(q=q))
    assert out["risk_grade"] == "Medium"
    assert out["agent_severity"]["quantitative"] == "Medium"


def test_grade_high_two_agents_plus_escalation(mocks):
    q = res("Medium", {FY: ["quantitative.dso_growth", "quantitative.accruals"]})
    n = res("Low", {FY: ["network.related_party"]})
    n["severity"] = "Medium"
    out = sa.run_synthesis(make_state(q=q, n=n, t=temporal("Escalating", "Escalating")))
    assert out["risk_grade"] == "High"
    assert "High rule" in out["grade_rationale"]


def test_two_agents_without_escalation_is_medium(mocks):
    q, n = res("Medium", {FY: ["a"]}), res("Medium", {FY: ["b"]})
    assert sa.run_synthesis(make_state(q=q, n=n))["risk_grade"] == "Medium"


def test_grade_critical_with_jev(mocks):
    mocks["jev"] = jev_ok(90.0)
    s = make_state(q=res("High", {FY: ["quantitative.beneish"]}), l=res("High", {FY: ["l"]}),
                   n=res("High", {FY: ["network.going_concern"]}))
    out = sa.run_synthesis(s)
    assert out["risk_grade"] == "Critical" and out["jev_available"] is True
    assert "critical_blocked: Jev unavailable" not in out["degraded"]


def test_jev_unavailable_caps_critical_at_high(mocks):
    s = make_state(q=res("High", {FY: ["quantitative.beneish"]}), l=res("High", {FY: ["l"]}),
                   n=res("High", {FY: ["network.going_concern"]}))
    out = sa.run_synthesis(s)
    assert out["risk_grade"] == "High"
    assert "critical_blocked: Jev unavailable" in out["degraded"]
    assert all(v["available"] is False for v in out["jev_scores"].values())


def test_jev_low_confidence_blocks_critical(mocks):
    mocks["jev"] = jev_ok(60.0)
    s = make_state(q=res("High", {FY: ["x"]}), l=res("High", {FY: ["l"]}), n=res("High", {FY: ["n"]}))
    assert sa.run_synthesis(s)["risk_grade"] == "High"


def test_jev_exception_never_crashes(monkeypatch, mocks):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(sa.jev_scorer, "score_agents", boom)
    events = []
    out = sa.run_synthesis(make_state(q=res("Medium", {FY: ["f"]})), progress_callback=events.append)
    assert out["risk_grade"] == "Medium" and out["jev_available"] is False
    assert set(out["jev_scores"]) >= set(sa.ALL_AGENTS)
    assert any(e.get("status") == "jev" and e.get("node") == "synthesis" for e in events)


def test_callback_exception_is_swallowed(mocks):
    def bad(_):
        raise ValueError("ui")

    assert sa.run_synthesis(make_state(), progress_callback=bad)["risk_grade"] == "Low"


def test_unavailable_agents_noted_and_not_counted(mocks):
    s = make_state(q=unavailable("quantitative"), l=unavailable("language"), n=unavailable("network"),
                   p=unavailable("peer"), t=unavailable("temporal"))
    out = sa.run_synthesis(s)
    assert out["risk_grade"] == "Low"
    assert any("agents unavailable" in d and "quantitative" in d for d in out["degraded"])
    assert "reflects missing evidence" in out["final_narrative"]
    assert out["agent_severity"]["quantitative"] == "Unavailable"


def test_missing_results_do_not_crash(mocks):
    out = sa.run_synthesis({"ticker": "X"})
    assert out["risk_grade"] == "Low"


def test_internal_error_returns_unknown(monkeypatch, mocks):
    monkeypatch.setattr(sa, "_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = sa.run_synthesis(make_state())
    assert out["risk_grade"] == "Unknown" and out["error"]


def test_conflicting_evidence_is_called_out(mocks):
    q = res("High", {FY: ["quantitative.beneish"]}, key="Beneish in manipulation zone")
    p = res("None", key="Peer metrics in line")
    out = sa.run_synthesis(make_state(q=q, p=p))
    assert out["risk_grade"] == "Medium"
    assert "Agents disagree" in out["final_narrative"]


def test_risk_changed(mocks):
    s = make_state(q=res("Medium", {FY: ["f"]}), previous_risk_grade="Low")
    assert sa.run_synthesis(s)["risk_changed"] is True
    s["previous_risk_grade"] = "Medium"
    assert sa.run_synthesis(s)["risk_changed"] is False
    s.pop("previous_risk_grade")
    assert sa.run_synthesis(s)["risk_changed"] is False


def test_timeline_passthrough(mocks):
    t = temporal()
    out = sa.run_synthesis(make_state(t=t))
    assert out["forensic_timeline"] == t["timeline"]


# --------------------------------------------------------------------------------------- smoking guns
def test_sentence_all_parts():
    e = ev("quantitative.dso_growth", metric="days sales outstanding", display="95.0 days", peer_pct=42.0)
    assert sa.format_smoking_gun(e) == (
        "In FY2020, days sales outstanding showed 95.0 days, which is 42% above the peer group average and consistent with "
        "receivables growth outpacing sales, a premature revenue recognition / channel-stuffing signature observed before "
        "the Sunbeam accounting fraud (1996-1998)."
    )


def test_sentence_without_peer_or_pattern():
    s = sa.format_smoking_gun(ev("language.hedging", metric="hedging ratio", display="0.031"))
    assert s == "In FY2020, hedging ratio showed 0.031."
    s2 = sa.format_smoking_gun(ev("language.hedging", metric="hedging ratio", display="0.031", peer_pct=-12.5))
    assert s2 == "In FY2020, hedging ratio showed 0.031, which is 12.5% below the peer group average."
    s3 = sa.format_smoking_gun(ev("network.related_party", metric="related-party disclosure", display="2x"))
    assert ", consistent with growth in related-party" in s3 and "peer group" not in s3


def test_pattern_metric_keyword_gate():
    assert sa.match_pattern("quantitative.beneish", "Beneish M-Score") is None
    assert sa.match_pattern("quantitative.beneish", "Beneish AQI component")["key"] == "worldcom_capitalised_costs"
    assert sa.match_pattern("quantitative.accruals", "accruals ratio") is None


def test_pattern_table_has_sources():
    assert PATTERN_TABLE
    for e in PATTERN_TABLE:
        assert e["source"].startswith(("SEC", "Enron")) and "http" in e["source"]
        assert e["confidence"] in ("high", "medium") and e["pattern"] and e["case"]


def test_ranking_hard_then_focus_then_magnitude_then_agent_order():
    cands = [
        {"agent": "language", "flag": "language.hedging", "year": FY, "metric": "m", "magnitude": 100, "display": "d"},
        {"agent": "peer", "flag": "peer.gm", "year": FY - 1, "metric": "m", "magnitude": 9999, "display": "d"},
        {"agent": "network", "flag": "network.going_concern", "year": FY - 1, "metric": "m", "value": 1, "display": "d"},
        {"agent": "quantitative", "flag": "quantitative.dso_growth", "year": FY, "metric": "m", "magnitude": 100, "display": "d"},
        {"agent": "peer", "flag": "peer.roa", "year": FY, "metric": "m", "magnitude": 5, "display": "d"},
    ]
    ranked = sa.rank_candidates(cands, FY)
    assert [c["flag"] for c in ranked] == [
        "network.going_concern",          # hard, even off focus year
        "quantitative.dso_growth",        # focus, magnitude tie 100 -> agent order quantitative first
        "language.hedging",
        "peer.roa",                       # focus, small magnitude
        "peer.gm",                        # non-focus
    ]
    assert sa.rank_candidates(list(reversed(cands)), FY) == ranked  # deterministic regardless of input order


def test_hard_combo_auditor_and_cfo_same_year():
    c = [
        {"agent": "network", "flag": "network.auditor_change", "year": FY, "metric": "m", "value": 1, "display": "d"},
        {"agent": "network", "flag": "network.cfo_change", "year": FY, "metric": "m", "value": 1, "display": "d"},
        {"agent": "language", "flag": "language.hedging", "year": FY, "metric": "m", "value": 50, "display": "d"},
    ]
    assert [x["agent"] for x in sa.rank_candidates(c, FY)][:2] == ["network", "network"]
    c2 = c[:1] + c[2:]
    assert sa.rank_candidates(c2, FY)[0]["agent"] == "language"  # auditor change alone is not hard


def test_selection_prefers_distinct_agents_then_flags_and_never_pads():
    def c(agent, flag, v):
        return {"agent": agent, "flag": flag, "year": FY, "metric": flag, "value": v, "display": "d"}

    ranked = sa.rank_candidates([c("quantitative", "q1", 10), c("quantitative", "q2", 9), c("quantitative", "q3", 8),
                                 c("network", "n1", 1), c("peer", "p1", 0.5)], FY)
    chosen = sa.select_smoking_guns(ranked)
    assert [x["flag"] for x in chosen] == ["q1", "n1", "p1"]
    only_one = sa.select_smoking_guns(sa.rank_candidates([c("peer", "p1", 1)], FY))
    assert len(only_one) == 1


def test_guns_end_to_end_and_structured_evidence(mocks):
    q = res("High", {FY: ["quantitative.dso_growth"]},
            evidence=[ev("quantitative.dso_growth", metric="DSO", display="95 days", peer_pct=30.0, value=95)])
    n = res("Medium", {FY: ["network.related_party"]},
            evidence=[ev("network.related_party", metric="related-party disclosure length", display="12,000 chars", value=12000)])
    out = sa.run_synthesis(make_state(q=q, n=n))
    assert len(out["smoking_guns"]) == 2
    assert out["smoking_guns"][0].startswith("In FY2020, DSO showed 95 days, which is 30% above")
    assert out["smoking_gun_evidence"][0]["agent"] == "quantitative"
    assert out["smoking_gun_evidence"][0]["text"] == out["smoking_guns"][0]


def test_candidates_without_value_or_year_are_dropped():
    r = {"quantitative": res(evidence=[{"flag": "f", "year": FY, "metric": "m"}, {"flag": "f", "metric": "m", "value": 1},
                                       ev("f", metric="ok")])}
    assert len(sa.collect_candidates(r)) == 1


# --------------------------------------------------------------------------------------- validate_numbers
@pytest.mark.parametrize(
    "text,allowed,bad",
    [
        ("DSO rose to 95.0 days", [95], []),
        ("ratio of 12.3", [12.30], []),
        ("ratio of 12.30", [12.3], []),
        ("ratio 12.3", [12.34], []),             # rounding to the written precision
        ("ratio of 12.4", [12.34], ["12.4"]),
        ("revenue of 1,234,567", [1234567], []),
        ("fell 5%", [-5.0], []),
        ("grew 40%", [0.4], []),                  # fraction shown as percent
        ("in FY2019 and 2020", [2019, 2020], []),
        ("in FY2018", [2019], ["2018"]),
        ("the 3rd flag", [3], []),
        ("filed on Form 10-K and 20-F", [], []),  # form names are not figures
        ("an invented 77% jump", [10, 20], ["77"]),
        ("1. First point\n2. Second", [], []),     # list markers ignored
        ("text with no numbers", [], []),
        ("ends sentence 45.", [45], []),
    ],
)
def test_validate_numbers(text, allowed, bad):
    assert sa.validate_numbers(text, allowed) == bad


def test_collect_numbers_from_nested_strings():
    nums = sa.collect_numbers({"a": [1, 2.5, "grew 40% in FY2019"], "b": {"2020": True}})
    assert 40.0 in nums and 2019.0 in nums and 2020.0 in nums and 2.5 in nums


# --------------------------------------------------------------------------------------- narrative LLM path
def _flagged_state():
    q = res("Medium", {FY: ["quantitative.dso_growth"]}, key="DSO rose",
            evidence=[ev("quantitative.dso_growth", metric="DSO", display="95 days", value=95, peer_pct=30.0)])
    return make_state(q=q)


GOOD = ("The grade is Medium for FY2020 with one agent flagging.\n\n"
        "DSO showed 95 days, which is 30% above the peer group average, a manipulation-type signal.\n\n"
        "Watch days sales outstanding in the next filing.")


def test_llm_narrative_used_when_numbers_valid(mocks):
    mocks["llm"] = GOOD
    out = sa.run_synthesis(_flagged_state())
    assert out["final_narrative"] == GOOD
    assert not any(d.startswith("narrative:") for d in out["degraded"])
    tier, system, user = mocks["llm_calls"][0]
    assert tier == "sonnet" and "NEVER INVENT" in system and "MANIPULATION RISK from BUSINESS DISTRESS" in system
    assert '"risk_grade": "Medium"' in user


def test_llm_invented_number_falls_back(mocks):
    mocks["llm"] = GOOD.replace("95 days", "123 days")
    out = sa.run_synthesis(_flagged_state())
    assert "123" not in out["final_narrative"]
    assert any(d.startswith("narrative: deterministic fallback") and "123" in d for d in out["degraded"])
    assert len(out["final_narrative"].split("\n\n")) == 3


def test_llm_wrong_paragraph_count_falls_back(mocks):
    mocks["llm"] = "Only one paragraph about FY2020."
    out = sa.run_synthesis(_flagged_state())
    assert any("expected 3" in d for d in out["degraded"])


def test_llm_exception_falls_back(monkeypatch, mocks):
    def boom(*a, **k):
        raise RuntimeError("api")

    monkeypatch.setattr(sa, "llm_text", boom)
    out = sa.run_synthesis(_flagged_state())
    assert any(d.startswith("narrative: deterministic fallback") for d in out["degraded"])


def test_deterministic_narrative_content(mocks):
    s = _flagged_state()
    s["network_result"] = res("None", {}, key="n")
    s["language_result"] = unavailable("language")
    out = sa.run_synthesis(s)
    p1, p2, p3 = out["final_narrative"].split("\n\n")
    assert "Medium" in p1 and "language" in p1 and "unavailable" in p1 and "Jev" in p1
    assert "In FY2020, DSO showed 95 days" in p2
    assert "days sales outstanding" in p3  # indicator derived from the open flag
    assert out["final_narrative"] == sa.run_synthesis(s)["final_narrative"]  # deterministic


def test_distress_vs_manipulation_labelled(mocks):
    q = res("Medium", {FY: ["quantitative.altman_distress"]})
    out = sa.run_synthesis(make_state(q=q))
    assert "distress" in out["final_narrative"]


# ------------------------------------------------- golden sentences per flag (displays mirror each agent's templates)
_GOLDEN = [
    ("quantitative.beneish", "beneish_m_score",
     "Beneish M-Score was -0.66 in FY2020, above the -1.78 manipulation threshold. Receivables index 1.5 drove it.",
     ["-0.66", "-1.78"]),
    ("quantitative.altman_distress", "altman_z",
     "Altman Z score was 1.20 in FY2020, inside the distress zone (below 1.81). This is a business-distress signal "
     "(solvency risk), not evidence of accounting manipulation.", ["1.20", "1.81"]),
    ("quantitative.revenue_quality", "revenue_quality_ocf_to_ni",
     "Operating cash flow was 0.50x net income in FY2020 and 0.40x in FY2019; below 0.8 in two consecutive years means "
     "reported profit is not converting into cash.", ["0.50", "0.40", "0.8"]),
    ("quantitative.dso_growth", "dso_yoy_change_pct",
     "DSO rose from 40.0 to 55.0 days (+37.5%) in FY2020, above the +20% threshold. Revenue grew 5.0% while net "
     "receivables grew 30.0% in FY2020.", ["40.0", "55.0", "37.5"]),
    ("quantitative.accruals", "accruals_ratio",
     "Accruals (net income minus operating cash flow) were 7.5% of total assets in FY2020, above the 5.0% threshold: "
     "earnings are running ahead of cash.", ["7.5", "5.0"]),
    ("language.hedging", "hedging_ratio", "Hedging-word ratio rose 40% to 1.2% of MD&A words in FY2020", ["40", "1.2"]),
    ("language.passive_voice", "passive_voice_pct", "28.5% of MD&A sentences were passive-voice in FY2020 (above 15%).",
     ["28.5", "15"]),
    ("language.risk_factor_growth", "risk_factor_chars", "Risk Factors section grew 55% to 120,000 characters in FY2020",
     ["55", "120,000"]),
    ("language.specificity", "specificity_score", "Specificity score fell from 7 to 4 in FY2020 (LLM-rated)", ["7", "4"]),
    ("language.new_legal", "new_legal_paragraphs",
     "2 materially new paragraph(s) in the FY2020 Legal Proceedings section vs FY2019", ["2"]),
    ("network.auditor_change", "auditor", "Auditor changed from Alpha LLP to Beta LLP in FY2020", ["2020"]),
    ("network.cfo_change", "cfo", "CFO changed from Ann Lee to Bo Wu in FY2020", ["2020"]),
    ("network.ceo_change", "ceo", "CEO changed from Ann Lee to Bo Wu in FY2020", ["2020"]),
    ("network.audit_fees", "audit_fees_yoy_pct",
     "Audit fees rose 45.0% in FY2020 ($1.0M to $1.5M) while revenue grew 5.0% (less than half the fee growth)", ["45.0", "5.0"]),
    ("network.restatement", "restatement_or_material_weakness",
     'FY2020 filing discloses restatement: "… of these individuals restated results. The board agreed …"', ["2020"]),
    ("network.related_party", "related_party_chars_yoy_pct",
     "Related-party disclosure grew 120% in FY2020 (4,000 to 8,800 characters)", ["120", "4,000", "8,800"]),
    ("network.going_concern", "going_concern",
     'FY2020 filing expresses going-concern doubt: "substantial doubt about its ability to continue."', ["2020"]),
]


@pytest.mark.parametrize("flag,metric,display,nums", _GOLDEN, ids=[g[0] for g in _GOLDEN])
def test_golden_clean_sentence_per_flag(flag, metric, display, nums):
    for extra in ({}, {"peer_pct": 12.5}):
        s = sa.format_smoking_gun(ev(flag, metric=metric, display=display, **extra))
        assert ".." not in s and s == s.strip() and "  " not in s
        assert s.endswith(".") and not s.endswith("..")
        assert "showed Beneish" not in s and " showed " not in s
        for n in nums:
            assert n in s
    assert "FY2020" in sa.format_smoking_gun(ev(flag, metric=metric, display=display))


def test_golden_exact_sentences():
    b = sa.format_smoking_gun(ev("quantitative.beneish", metric="beneish_m_score",
                                 display="Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold. X.", year=2000))
    assert b == "Beneish M-Score was -0.66 in FY2000, above the -1.78 manipulation threshold."
    a = sa.format_smoking_gun(ev("quantitative.altman_distress", metric="altman_z",
                                 display="Altman Z score was 1.20 in FY2020, inside the distress zone (below 1.81). Other."))
    assert a == ("Altman Z score was 1.20 in FY2020, inside the distress zone (below 1.81); "
                 "a business-distress signal, not evidence of accounting manipulation.")
    r = sa.format_smoking_gun(ev("network.restatement", metric="restatement_or_material_weakness",
                                 display='FY2020 filing discloses restatement: "… of these. The board agreed …"'))
    assert r == 'FY2020 filing discloses restatement: "… of these. The board agreed …".'
    assert sa.format_smoking_gun(ev("language.hedging", metric="x", display="Hedging words rose 10% in FY2020..  ")) == "Hedging words rose 10% in FY2020."


def _peer(metric, kind, company, mean, pct, label, shown_c, shown_m):
    return ev(f"peer.{metric}", metric=metric, value=company, year=2020, peer_pct=pct, unit_kind=kind,
              display=f"{label} {shown_c} vs peer mean {shown_m} (z=-3.1): below peers by more than 2 standard deviations",
              numbers=[company, mean, 0.01, -3.1, 8])


def test_peer_pp_metric_never_gets_percent_of_mean():
    e = _peer("receivables_vs_revenue_growth", "pp_difference", -0.01, 0.0011, -1029.2,
              "Receivables growth minus revenue growth", "-1.0 pp", "+0.1 pp")
    s = sa.format_smoking_gun(e)
    assert "1029" not in s and "%" not in s.replace("(z", "")
    assert s == ("In FY2020, receivables growth minus revenue growth was -1.0 pp, which is 1.1 pp below the peer mean "
                 "of 0.1 pp.")


def test_peer_level_metric_keeps_percent_and_small_mean_drops_it():
    e = _peer("gross_margin", "ratio_level", 0.30, 0.40, -25.0, "Gross margin", "30.0%", "40.0%")
    assert sa.format_smoking_gun(e) == "In FY2020, gross margin was 30.0%, which is 25% below the peer group average."
    tiny = _peer("roa", "ratio_level", 0.30, 0.001, 29900.0, "ROA", "30.0%", "0.1%")
    s = sa.format_smoking_gun(tiny)
    assert "29900" not in s and s.endswith(".") and ".." not in s
    d = _peer("dso", "days", 90.0, 0.4, 22400.0, "DSO", "90 days", "0 days")
    assert "which is 89.6 days above the peer mean of 0.4 days" in sa.format_smoking_gun(d)
    ok = _peer("dso", "days", 90.0, 45.0, 100.0, "DSO", "90 days", "45 days")
    assert "100% above the peer group average" in sa.format_smoking_gun(ok)


def test_peer_missing_unit_kind_defaults_safely():
    e = ev("peer.gross_margin", metric="gross_margin", display="Gross margin 30.0% vs peer mean 40.0% (z=-3.1)",
           peer_pct=-25.0, numbers=[0.3, 0.4, 0.01, -3.1, 8], value=0.3)
    assert "25% below the peer group average" in sa.format_smoking_gun(e)


def test_initials_do_not_end_the_sentence():
    s = sa.format_smoking_gun(ev("network.ceo_change", metric="ceo", display="CEO changed from Kenneth L. Lay to Jeffrey Skilling in FY2000. Extra.", year=2000))
    assert s == "CEO changed from Kenneth L. Lay to Jeffrey Skilling in FY2000."


# =============================================================================================== v2 (docs/V2_CHANGELOG_agents.md)
# B3: escalation is the FOCUS-YEAR signal change only; Medium-by-escalation needs a flag in the focus year.
def test_v2_escalation_ignores_series_trajectory():
    t = temporal("Stable", "Escalating")  # series trajectory Escalating, focus-year change Stable (BRK-B / VG pattern)
    assert sa._escalation(t, FY) is False
    t2 = temporal("Escalating", "Stable")
    assert sa._escalation(t2, FY) is True
    t3 = dict(temporal("Stable", "Escalating"), focus_signal_change="Escalating")  # explicit field wins
    assert sa._escalation(t3, FY) is True
    t4 = dict(temporal("Escalating", "Escalating"), focus_signal_change="Stable")
    assert sa._escalation(t4, FY) is False


def test_v2_escalation_missing_or_unavailable_is_false():
    assert sa._escalation(None, FY) is False
    assert sa._escalation({"unavailable": True}, FY) is False
    assert sa._escalation({"signal_trajectory": "Escalating"}, FY) is False  # no focus-year information at all


def test_v2_trajectory_only_escalation_no_longer_makes_high_or_medium(mocks):
    q, n = res("Medium", {FY: ["a"]}), res("Medium", {FY: ["b"]})
    out = sa.run_synthesis(make_state(q=q, n=n, t=temporal("Stable", "Escalating")))
    assert out["risk_grade"] == "Medium" and "High rule" not in out["grade_rationale"]
    out2 = sa.run_synthesis(make_state(l=res("Low", {FY - 1: ["language.hedging"]}), t=temporal("Stable", "Escalating")))
    assert out2["risk_grade"] == "Low"


def test_v2_medium_by_escalation_needs_flag_in_focus_year(mocks):
    # only a PRIOR-year flag + focus-year escalation: not Medium any more
    out = sa.run_synthesis(make_state(l=res("None", {FY - 1: ["language.hedging"]}), t=temporal("Escalating")))
    assert out["risk_grade"] == "Low"
    # a Low-severity (1 flag) focus-year flag + focus-year escalation: Medium
    out = sa.run_synthesis(make_state(l=res("Low", {FY: ["language.hedging"]}), t=temporal("Escalating")))
    assert out["risk_grade"] == "Medium"
    assert "focus-year escalation" in out["grade_rationale"]


@pytest.mark.parametrize("esc,focus_flag,grade", [(True, True, "Medium"), (True, False, "Low"), (False, True, "Low"),
                                                  (False, False, "Low")])
def test_v2_compute_risk_grade_medium_escalation_rule(esc, focus_flag, grade):
    assert sa.compute_risk_grade(0, 0, esc, None, False, focus_flag)["grade"] == grade


def test_v2_focus_year_flagged_helper():
    r = {"quantitative": res("None", {FY - 1: ["quantitative.accruals"]}), "language": res(), "network": res(),
         "peer": res()}
    assert sa._focus_year_flagged(r, FY) is False
    r["peer"] = res("Low", {FY: ["peer.roa"]})
    assert sa._focus_year_flagged(r, FY) is True
    r["peer"] = unavailable("peer")
    assert sa._focus_year_flagged(r, FY) is False


# informational flags never surface as smoking guns when a genuine flag exists
def test_v2_informational_evidence_not_a_smoking_gun_when_genuine_exists(mocks):
    p = res("None", {}, evidence=[ev("peer.roa", "roa", 0.177, "ROA 17.7% vs peer mean 7.4% (z=+2.6)", peer_pct=140.4,
                                     informational=True)])
    l = res("Low", {FY: ["language.passive_voice"]}, evidence=[ev("language.passive_voice", "passive_voice_pct", 31.0,
                                                                      "31.0% of MD&A sentences were passive-voice in FY2020")])
    q = res("Low", {FY: ["quantitative.accruals"]}, evidence=[ev("quantitative.accruals", "accruals_ratio", 0.06,
                                                                  "Accruals were 6.0% of total assets in FY2020, above the 5.0% threshold.")])
    out = sa.run_synthesis(make_state(q=q, l=l, p=p))
    flags = [g["flag"] for g in out["smoking_gun_evidence"]]
    assert flags == ["quantitative.accruals"]


def test_v2_informational_used_only_when_nothing_else(mocks):
    l = res("Low", {FY: ["language.passive_voice"]}, evidence=[ev("language.passive_voice", "passive_voice_pct", 31.0,
                                                                      "31.0% of MD&A sentences were passive-voice in FY2020")])
    out = sa.run_synthesis(make_state(l=l))
    assert [g["flag"] for g in out["smoking_gun_evidence"]] == ["language.passive_voice"]


def test_v2_absurd_peer_percentage_never_narrated():
    e = ev("peer.ocf_to_revenue", "ocf_to_revenue", -70.098, "OCF/revenue -7009.8% vs peer mean 16.5% (z=-608.0)",
           peer_pct=-42634.6, numbers=[-70.098, 0.165, 0.115, -608.0, 8])
    txt = sa.format_smoking_gun(dict(e, year=FY))
    assert "42634" not in txt and "42,634" not in txt


def test_v2_shell_year_evidence_is_never_a_smoking_gun(mocks):
    n = res("High", {FY - 1: ["network.going_concern"], FY: ["network.cfo_change"]}, evidence=[
        ev("network.going_concern", "going_concern", 1, "FY2019 filing expresses going-concern doubt", year=FY - 1),
        ev("network.cfo_change", "cfo", 1, "CFO changed from A to B in FY2020")])
    s = make_state(n=n, filing_entity_flags={FY - 1: {"is_shell": True, "spac_predecessor": True, "reason": "SPAC"}})
    out = sa.run_synthesis(s)
    assert [g["flag"] for g in out["smoking_gun_evidence"]] == ["network.cfo_change"]
    # without the flags (or with junk) both are candidates
    assert len(sa.run_synthesis(make_state(n=n))["smoking_gun_evidence"]) == 2
    assert len(sa.run_synthesis(make_state(n=n, filing_entity_flags="junk"))["smoking_gun_evidence"]) == 2


# ------------------------------------------------------------------ v3 L2: grade_inputs instrumentation (NO behaviour change)
def test_v3_grade_inputs_persisted_and_match_the_grade_rule(mocks):
    mocks["jev"] = jev_ok(90.0)
    q = res("High", {FY: ["quantitative.beneish"]})
    l_, n = res("High", {FY: ["language.x"]}), res("High", {FY: ["network.going_concern"]})
    out = sa.run_synthesis(make_state(q=q, l=l_, n=n, t=temporal("Escalating", "Escalating")))
    gi = out["grade_inputs"]
    assert gi == {"focus_year": FY, "agents_flagging": 3, "agents_high": 3, "escalation": True, "focus_year_flagged": True,
                  "jev_mean_confidence": 90.0, "jev_available": True,
                  "agent_severity": {"quantitative": "High", "language": "High", "network": "High", "peer": "None"}}
    # feeding the persisted inputs back into the pure rule reproduces the stored grade and rationale exactly
    again = sa.compute_risk_grade(gi["agents_flagging"], gi["agents_high"], gi["escalation"], gi["jev_mean_confidence"],
                                  gi["jev_available"], gi["focus_year_flagged"])
    assert again["grade"] == out["risk_grade"] == "Critical" and again["rationale"] == out["grade_rationale"]


@pytest.mark.parametrize("q,l_,t", [
    (res(), res(), temporal()),
    (res("Medium", {FY: ["a"]}), res(), temporal("Escalating", "Escalating")),
    (res("None", {FY: ["a"]}), res(), temporal("Escalating", "Stable")),
    (res("High", {FY: ["a"]}), res("Medium", {FY: ["b"]}), temporal("Escalating", "Escalating")),
])
def test_v3_grade_inputs_reproduce_grade_for_every_branch(mocks, q, l_, t):
    out = sa.run_synthesis(make_state(q=q, l=l_, t=t))
    gi = out["grade_inputs"]
    again = sa.compute_risk_grade(gi["agents_flagging"], gi["agents_high"], gi["escalation"], gi["jev_mean_confidence"],
                                  gi["jev_available"], gi["focus_year_flagged"])
    assert (again["grade"], again["rationale"]) == (out["risk_grade"], out["grade_rationale"])
    assert gi["jev_available"] is False and gi["jev_mean_confidence"] is None


def test_v3_grade_inputs_error_path_has_no_key_and_grade_unchanged(monkeypatch, mocks):
    monkeypatch.setattr(sa, "_run", lambda *a, **k: 1 / 0)
    out = sa.run_synthesis(make_state())
    assert out["risk_grade"] == "Unknown" and "grade_inputs" not in out
