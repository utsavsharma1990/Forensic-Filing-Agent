"""Offline tests for evaluation/evaluator.py (injected analyze function + synthetic states; no network, no keys)."""
from __future__ import annotations

import json
import math

import pytest

from evaluation import evaluator as ev
from evaluation.fraud_cases import ALL_CASES, FRAUD_CASES, get_case


# ----------------------------------------------------------------------------------------------- helpers
def _res(severity="None", flags=0, by_year=None, unavailable=False, finding="nothing", beneish=None):
    r = {"severity": severity, "flags_fired": flags, "flags_by_year": by_year or {}, "key_finding": finding,
         "unavailable": unavailable}
    if beneish is not None:
        r["beneish_scores"] = beneish
    return r


def _state(grade="Low", sev=None, first=None, fdate=None, beneish_flag=None, year=2020, **extra):
    sev = sev or {}
    st = {"risk_grade": grade, "first_detection_year": first, "first_detection_filing_date": fdate,
          "forensic_timeline": [], "smoking_guns": extra.pop("smoking_guns", []), "smoking_gun_evidence": [],
          "degraded": extra.pop("degraded", []), "jev_available": extra.pop("jev", True), "error": extra.pop("error", "")}
    for a in ("quantitative", "language", "network", "peer", "temporal"):
        st[f"{a}_result"] = _res(severity=sev.get(a, "None"), finding=f"{a} finding")
    if beneish_flag is not None:
        st["quantitative_result"]["beneish_scores"] = {
            str(year): {"status": "ok", "score": -1.0 if beneish_flag else -2.5, "flag": beneish_flag}}
    st.update(extra)
    return st


def _case(ticker, truth, **kw):
    c = {"ticker": ticker, "company_name": ticker + " Inc", "cik": "0000000001", "analysis_year": 2020,
         "analysis_filing_date": "2021-03-01", "ground_truth": truth, "pre_revelation_valid": True,
         "fraud_nature": "financial_statement" if truth else "none", "strict_alt": None,
         "public_revelation_date": "2021-09-01" if truth else None, "collapse_date": "2021-12-01" if truth else None}
    c.update(kw)
    return c


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_cache_dir", lambda: tmp_path / "evalcache")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JEV_API_KEY", "jev-test")
    return tmp_path


def _run(analyze, cases, tmp_path, **kw):
    return ev.run_evaluation(cases=cases, analyze=analyze, results_dir=tmp_path / "res", **kw)


# ----------------------------------------------------------------------------------------------- math
def test_confusion_metrics_hand_computed():
    m = ev.compute_metrics(tp=3, fp=1, tn=5, fn=3)  # n=12
    assert m["precision"]["value"] == pytest.approx(0.75)
    assert m["recall"]["value"] == pytest.approx(0.5)
    assert m["fpr"]["value"] == pytest.approx(1 / 6)
    assert m["f1"]["value"] == pytest.approx(2 * 3 / (2 * 3 + 1 + 3))  # 0.6
    assert m["accuracy"]["value"] == pytest.approx(8 / 12)
    assert m["precision"]["num"] == 3 and m["precision"]["den"] == 4


def test_all_zero_denominators_are_none_not_errors():
    m = ev.compute_metrics(0, 0, 0, 0)
    for k in ("precision", "recall", "fpr", "f1", "accuracy"):
        assert m[k]["value"] is None
    m = ev.compute_metrics(0, 0, 6, 6)  # never predicts positive
    assert m["precision"]["value"] is None and m["precision"]["ci_low"] is None
    assert m["recall"]["value"] == 0.0 and m["fpr"]["value"] == 0.0
    assert m["f1"]["value"] == 0.0


@pytest.mark.parametrize("k,n,lo,hi", [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (10, 10, 0.7225, 1.0),
                                       (3, 6, 0.1876, 0.8124)])
def test_wilson_known_values(k, n, lo, hi):
    got = ev.wilson_interval(k, n)
    assert got[0] == pytest.approx(lo, abs=1e-4) and got[1] == pytest.approx(hi, abs=1e-4)


def test_wilson_matches_independent_formula_and_none_for_n0():
    assert ev.wilson_interval(0, 0) is None
    z = 1.959963984540054
    for n in range(1, 13):
        for k in range(n + 1):
            p = k / n
            # algebraically equivalent closed form: roots of (p-q)^2 n = z^2 q(1-q)
            a = n + z * z
            b = -(2 * n * p + z * z)
            c = n * p * p
            disc = math.sqrt(max(b * b - 4 * a * c, 0))
            lo, hi = (-b - disc) / (2 * a), (-b + disc) / (2 * a)
            got = ev.wilson_interval(k, n)
            assert got[0] == pytest.approx(max(lo, 0), abs=1e-9) and got[1] == pytest.approx(min(hi, 1), abs=1e-9)
    try:
        from statsmodels.stats.proportion import proportion_confint
    except Exception:
        return
    assert ev.wilson_interval(3, 6) == pytest.approx(proportion_confint(3, 6, method="wilson"), abs=1e-6)


# ----------------------------------------------------------------------------------------------- selection
def test_strict_case_selection_real_registry():
    by = {c["ticker"]: ev.case_params(c, "strict") for c in ALL_CASES}
    assert by["LK"]["include"] is False and "strict_alt is None" in by["LK"]["reason"]
    assert (by["NKLA"]["as_of"], by["NKLA"]["end_year"]) == ("2020-03-06", 2019)
    assert (by["RIDE"]["as_of"], by["RIDE"]["end_year"]) == ("2020-03-25", 2019)
    assert (by["SPCE"]["as_of"], by["SPCE"]["end_year"]) == ("2021-03-01", 2020)
    assert (by["ENRNQ"]["as_of"], by["ENRNQ"]["end_year"]) == ("2001-04-02", 2000)  # valid: unchanged
    assert (by["AAPL"]["as_of"], by["AAPL"]["end_year"]) == ("2020-10-30", 2020)    # clean: unchanged
    spec = {c["ticker"]: ev.case_params(c, "spec") for c in ALL_CASES}
    assert all(p["include"] for p in spec.values())
    assert (spec["LK"]["as_of"], spec["LK"]["end_year"]) == ("2021-06-30", 2019)


def test_strict_run_lists_excluded_case(tmp_path):
    cases = [get_case("LK"), get_case("ENRNQ"), get_case("AAPL")]
    seen = []

    async def an(ticker, years=5, **kw):
        seen.append((ticker, kw["as_of"], kw["end_year"]))
        return _state("Low")
    r = _run(an, cases, tmp_path, mode="strict")
    run = r["runs"]["strict/spec"]
    assert [e["ticker"] for e in run["excluded"]] == ["LK"]
    assert "LK" not in [s[0] for s in seen]
    assert run["metrics"]["n"] == 2
    assert "EXCLUDED" in r["report_markdown"]


# ----------------------------------------------------------------------------------------------- error handling
def test_error_and_unknown_excluded_not_negative(tmp_path):
    cases = [_case("F1", 1), _case("F2", 1), _case("C1", 0), _case("C2", 0)]

    async def an(ticker, years=5, **kw):
        if ticker == "F1":
            return _state("Unknown")
        if ticker == "C2":
            return _state("Low", error="company not found")
        return _state("High" if ticker == "F2" else "Low")
    r = _run(an, cases, tmp_path)
    h = r["headline"]
    assert h["metrics"]["n"] == 2 and (h["metrics"]["tp"], h["metrics"]["tn"], h["metrics"]["fn"], h["metrics"]["fp"]) == (1, 1, 0, 0)
    st = {c["ticker"]: c["status"] for c in h["cases"]}
    assert st == {"F1": "ERROR", "F2": "OK", "C1": "OK", "C2": "ERROR"}
    wc = h["worst_case_metrics"]  # errored fraud -> FN, errored clean -> FP
    assert (wc["tp"], wc["fn"], wc["fp"], wc["tn"]) == (1, 1, 1, 1)
    assert "ERRORED" in r["report_markdown"] or "Errored cases" in r["report_markdown"]


def test_one_case_failure_is_isolated(tmp_path):
    cases = [_case("A", 1), _case("B", 0), _case("C", 0)]

    async def an(ticker, years=5, **kw):
        if ticker == "B":
            raise RuntimeError("boom")
        return _state("Low")
    r = _run(an, cases, tmp_path)
    rows = {c["ticker"]: c for c in r["headline"]["cases"]}
    assert rows["B"]["status"] == "ERROR" and "boom" in rows["B"]["error"]
    assert rows["A"]["status"] == "OK" and rows["C"]["status"] == "OK"
    assert r["headline"]["metrics"]["n"] == 2


def test_sync_analyze_supported_and_concurrency_bounded(tmp_path):
    import threading
    cur = {"n": 0, "max": 0}
    lock = threading.Lock()

    async def an(ticker, years=5, **kw):
        import asyncio
        with lock:
            cur["n"] += 1
            cur["max"] = max(cur["max"], cur["n"])
        await asyncio.sleep(0.02)
        with lock:
            cur["n"] -= 1
        return _state("Low")
    _run(an, [_case(f"T{i}", 0) for i in range(8)], tmp_path)
    assert cur["max"] <= 2

    r = _run(lambda t, y=5, **kw: _state("Low"), [_case("S", 0)], tmp_path, use_cache=False)
    assert r["headline"]["cases"][0]["status"] == "OK"


# ----------------------------------------------------------------------------------------------- timing
def test_timing_sign_conventions_hand_dates():
    assert ev.months_between("2001-04-02", "2001-10-16") == 6.5   # 197 days
    assert ev.months_between("2001-04-02", "2001-12-02") == 8.0   # 244 days
    assert ev.months_between("2021-06-30", "2020-01-31") == -17.0  # after revelation -> negative
    assert ev.months_between(None, "2020-01-01") is None
    rows = [
        {"status": "OK", "outcome": "TP", "ticker": "E", "first_detection_filing_date": "2001-04-02",
         "first_detection_year": 2000, "public_revelation_date": "2001-10-16", "collapse_date": "2001-12-02",
         "pre_revelation_valid": True},
        {"status": "OK", "outcome": "TP", "ticker": "L", "first_detection_filing_date": "2021-06-30",
         "first_detection_year": 2019, "public_revelation_date": "2020-01-31", "collapse_date": "2020-07-13",
         "pre_revelation_valid": False},
        {"status": "OK", "outcome": "FN", "ticker": "X", "first_detection_filing_date": None,
         "public_revelation_date": "2020-01-31", "collapse_date": None},
    ]
    t = ev.detection_timing(rows)
    cases = {c["ticker"]: c for c in t["cases"]}
    assert set(cases) == {"E", "L"}
    assert cases["E"]["months_before_revelation"] == 6.5 and cases["E"]["early"] is True
    assert cases["L"]["months_before_revelation"] < 0 and cases["L"]["early"] is False
    assert cases["L"]["label"].startswith("not early")
    assert t["average_months_early_before_revelation"] == 6.5   # negative excluded from average
    assert t["average_months_early_before_collapse"] == 8.0
    assert t["n_not_early"] == 1


def test_timing_none_average_when_nothing_early():
    t = ev.detection_timing([{"status": "OK", "outcome": "TP", "ticker": "L", "first_detection_filing_date": "2021-06-30",
                              "public_revelation_date": "2020-01-31", "collapse_date": "2020-07-13"}])
    assert t["average_months_early_before_revelation"] is None


# ----------------------------------------------------------------------------------------------- contribution
def _crow(t, truth, outcome, sev):
    agents = {a: {"unavailable": False, "severity": sev.get(a, "None")} for a in ev.AGENTS}
    return {"status": "OK", "ticker": t, "ground_truth": truth, "outcome": outcome, "agents": agents}


def test_unique_catch_synthetic_matrix():
    rows = [
        _crow("A", 1, "TP", {"quantitative": "High"}),                                  # quant only
        _crow("B", 1, "TP", {"quantitative": "Medium", "language": "Medium"}),          # shared
        _crow("C", 1, "FN", {"peer": "Medium"}),                                        # peer only, but missed overall
        _crow("D", 1, "FN", {}),
        _crow("E", 0, "FP", {"network": "High", "temporal": "Medium"}),                 # false alarm
        _crow("F", 0, "TN", {}),
    ]
    c = ev.agent_contribution(rows)
    ag = c["agents"]
    assert ag["quantitative"]["unique_catches"] == ["A"]
    assert ag["language"]["unique_catches"] == []
    assert ag["peer"]["unique_catches"] == ["C"]
    assert ag["peer"]["unique_catches_detected"] == []              # C was not detected overall
    assert ag["quantitative"]["unique_catch_pct_of_fraud"]["value"] == pytest.approx(1 / 4)
    assert ag["quantitative"]["unique_catch_pct_of_detected"]["value"] == pytest.approx(1 / 2)
    assert ag["quantitative"]["flag_rate_fraud"]["value"] == pytest.approx(2 / 4)
    assert ag["network"]["false_alarm_rate_clean"]["value"] == pytest.approx(1 / 2)
    assert ag["temporal"]["unique_catches"] is None
    assert c["decisive"]["quantitative"] == {"count": 1, "of_true_positives": 2, "cases": ["A"]}


# ----------------------------------------------------------------------------------------------- baselines
def test_baselines_on_same_cases(tmp_path):
    cases = [_case("F1", 1), _case("F2", 1), _case("C1", 0), _case("C2", 0), _case("C3", 0)]
    flags = {"F1": True, "F2": None, "C1": True, "C2": False, "C3": None}
    grade = {"F1": "High", "F2": "Low", "C1": "Low", "C2": "Low", "C3": "Low"}

    async def an(ticker, years=5, **kw):
        return _state(grade[ticker], beneish_flag=flags[ticker], year=kw["end_year"])
    r = _run(an, cases, tmp_path)
    b = r["headline"]["baselines"]
    bo, ac = b["beneish_only"], b["always_clean"]
    assert (bo["tp"], bo["fn"], bo["fp"], bo["tn"]) == (1, 1, 1, 2)
    assert set(b["beneish_unavailable_cases"]) == {"F2", "C3"}
    assert (ac["tp"], ac["fp"], ac["tn"], ac["fn"]) == (0, 0, 3, 2)
    assert ac["precision"]["value"] is None and ac["recall"]["value"] == 0.0


# ----------------------------------------------------------------------------------------------- report / json
def test_report_has_contamination_degraded_and_disclaimer(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("tools.common.load_env", lambda: None)
    cases = [get_case(t) for t in ("ENRNQ", "LK", "AAPL")]

    async def an(ticker, years=5, **kw):
        return _state("High" if ticker != "AAPL" else "Low", sev={"quantitative": "High"}, first=2019,
                      fdate="2021-06-30", jev=False, degraded=["llm_explanations: ANTHROPIC_API_KEY not set"],
                      smoking_guns=["In FY2019, X showed 1.2"])
    r = _run(an, cases, tmp_path, mode="both", variants=("spec", "no_passive"))
    md = r["report_markdown"]
    assert "DEGRADED RUN" in md.split("## Headline")[0]
    assert "LIMITATIONS AND CONTAMINATION" in md
    assert "4 of 6 fraud filings post-date public revelation" in md
    assert "Tuning / contamination ledger" in md and "network_agent.py" in md  # ledger row reproduced
    assert "WorldCom FY2000" in md
    assert "not matched" in md
    assert ev.DISCLAIMER in md
    assert "no_passive" in md and "strict/spec" in md and "(sensitivity)" in md
    assert "spec/spec (HEADLINE)" in md
    assert "Company | Year | Predicted | Actual | Risk Grade | First Detection | Key Signal | status | degraded" in md
    assert set(r["runs"]) == {"spec/spec", "spec/no_passive", "strict/spec", "strict/no_passive"}
    assert (tmp_path / "res" / ev.REPORT_NAME).exists() and (tmp_path / "res" / ev.JSON_NAME).exists()
    assert "PARTIAL RUN" in md


def test_no_degraded_banner_when_clean_run(tmp_path):
    async def an(ticker, years=5, **kw):
        return _state("Low")
    r = _run(an, [_case("C1", 0)], tmp_path)
    assert r["degraded_banner"] is False
    assert "DEGRADED RUN" not in r["report_markdown"]


def test_bad_results_stated_plainly(tmp_path):
    cases = [_case("F1", 1), _case("F2", 1), _case("C1", 0), _case("C2", 0)]

    async def an(ticker, years=5, **kw):
        return _state("Low" if ticker.startswith("F") else "High")  # inverted: everything wrong
    r = _run(an, cases, tmp_path)
    assert "WEAK / BAD" in r["report_markdown"]


def test_variant_passes_exclude_flags_only_for_no_passive(tmp_path):
    seen = {}

    async def an(ticker, years=5, **kw):
        seen[kw.get("thread_id")] = kw.get("exclude_flags")
        return _state("Low")
    _run(an, [_case("C1", 0)], tmp_path, variants=("spec", "no_passive"))
    assert seen["eval-spec-spec-C1"] is None
    assert seen["eval-spec-no_passive-C1"] == ["language.passive_voice"]


def test_json_no_nan_and_roundtrip(tmp_path):
    async def an(ticker, years=5, **kw):
        st = _state("High", first=2019, fdate="2021-06-30")
        st["quantitative_result"]["flags_by_year"] = {2019: ["x"]}
        st["peer_result"]["key_finding"] = float("nan")
        return st
    r = _run(an, [_case("F1", 1), _case("C1", 0)], tmp_path)
    text = (tmp_path / "res" / ev.JSON_NAME).read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    data = json.loads(text)  # strict parse
    assert data["headline"]["metrics"]["tp"] == 1
    loaded = ev.load_last_results(tmp_path / "res")
    assert loaded["headline_key"] == "spec/spec" and "report_markdown" in loaded
    assert ev.load_last_results(tmp_path / "nowhere") is None


# ----------------------------------------------------------------------------------------------- cache
def test_cache_resume_and_use_cache_false(tmp_path):
    calls = []
    fail = {"B": True}

    async def an(ticker, years=5, **kw):
        calls.append(ticker)
        if ticker == "B" and fail["B"]:
            raise RuntimeError("interrupted")
        return _state("Low")
    cases = [_case("A", 0), _case("B", 0)]
    r1 = _run(an, cases, tmp_path)
    assert sorted(calls) == ["A", "B"]
    fail["B"] = False
    calls.clear()
    r2 = _run(an, cases, tmp_path)
    assert calls == ["B"]                      # A resumed from cache, failed B retried (errors are not cached)
    rows = {c["ticker"]: c for c in r2["headline"]["cases"]}
    assert rows["A"]["from_cache"] is True and rows["B"]["status"] == "OK"
    calls.clear()
    _run(an, cases, tmp_path, use_cache=False)
    assert sorted(calls) == ["A", "B"]         # forced fresh


def test_cache_key_depends_on_code_hash(tmp_path, monkeypatch):
    calls = []

    async def an(ticker, years=5, **kw):
        calls.append(ticker)
        return _state("Low")
    _run(an, [_case("A", 0)], tmp_path)
    monkeypatch.setattr(ev, "code_hash", lambda root=None: "different")
    _run(an, [_case("A", 0)], tmp_path)
    assert calls == ["A", "A"]


def test_code_hash_changes_with_content(tmp_path):
    (tmp_path / "agents").mkdir()
    f = tmp_path / "agents" / "x.py"
    f.write_text("a = 1", encoding="utf-8")
    h1 = ev.code_hash(tmp_path)
    f.write_text("a = 2", encoding="utf-8")
    assert ev.code_hash(tmp_path) != h1
    assert len(h1) == 64


def test_fraud_registry_sanity():
    assert len(FRAUD_CASES) == 6 and sum(1 for c in FRAUD_CASES if not c["pre_revelation_valid"]) == 4


# ============================================================================================ v3 L2: instrumentation
def _instrumented_state(grade="Medium", year=2020):
    st = _state(grade, sev={"quantitative": "Medium", "language": "Low"}, year=year)
    st["quantitative_result"]["flags_by_year"] = {2019: ["quantitative.dso_growth"], year: ["quantitative.accruals"]}
    st["language_result"]["flags_by_year"] = {year: ["language.new_legal"]}
    st["temporal_result"].update({
        "focus_signal_change": "Escalating", "signal_trajectory": "Volatile", "suspicion_score": 45,
        "timeline": [{"year": 2019, "suspicion_score": 10, "signal_change": "Stable"},
                     {"year": 2020, "suspicion_score": 45, "signal_change": "Escalating"}]})
    st["grade_inputs"] = {"focus_year": year, "agents_flagging": 1, "agents_high": 0, "escalation": True,
                          "focus_year_flagged": True, "jev_mean_confidence": None, "jev_available": False,
                          "agent_severity": {}}
    st["grade_rationale"] = "Medium rule fired: test."
    st["filing_entity_flags"] = {2018: {"is_shell": True, "spac_predecessor": False, "reason": "stub"}}
    st["prior_year_info"] = {"status": "ok", "year": 2019, "reason": "x"}
    st["prior_year_results"] = {"quantitative": {"severity": "Low", "flags_fired": 1}}
    st["pipeline_version"] = "v3"
    return st


def test_v3_row_persists_instrumentation_fields(tmp_path):
    r = _run(lambda t, y=5, **kw: _instrumented_state(), [_case("X", 1)], tmp_path, use_cache=False)
    row = r["headline"]["cases"][0]
    assert row["focus_signal_change"] == "Escalating" and row["signal_trajectory"] == "Volatile"
    assert row["flags_by_year"]["quantitative"] == {"2019": ["quantitative.dso_growth"], "2020": ["quantitative.accruals"]}
    assert row["flags_by_year"]["peer"] == {}
    assert row["focus_flags_by_agent"]["quantitative"] == ["quantitative.accruals"]
    assert row["focus_flags_by_agent"]["language"] == ["language.new_legal"]
    assert row["agents"]["language"]["focus_flags"] == ["language.new_legal"]
    assert row["grade_inputs"]["source"] == "state" and row["grade_inputs"]["agents_flagging"] == 1
    assert row["grade_inputs"]["escalation"] is True and row["grade_inputs"]["jev_mean_confidence"] is None
    assert row["grade_rationale"] == "Medium rule fired: test."
    assert row["suspicion_score"] == 45 and row["suspicion_by_year"] == {"2019": 10, "2020": 45}
    assert row["signal_change_by_year"] == {"2019": "Stable", "2020": "Escalating"}
    assert row["filing_entity_flags"]["2018"]["is_shell"] is True
    assert row["prior_year_summary"]["status"] == "ok" and row["prior_year_summary"]["agents"]["quantitative"]["severity"] == "Low"
    saved = json.loads((tmp_path / "res" / "evaluation_results.json").read_text(encoding="utf-8"))
    assert saved["headline"]["cases"][0]["flags_by_year"]["language"] == {"2020": ["language.new_legal"]}
    assert saved["headline"]["cases"][0]["focus_signal_change"] == "Escalating"


def test_v3_instrumentation_does_not_change_grade_outcome_or_metrics():
    plain = _state("High", sev={"quantitative": "High", "language": "Medium"})
    rich = _instrumented_state("High")
    for c, st in ((_case("A", 1), plain), (_case("B", 1), rich)):
        row = ev._row_from_state(c, ev.case_params(c, "spec"), "spec", "spec", st)
        assert row["risk_grade"] == "High" and row["outcome"] == "TP" and row["predicted"] is True and row["status"] == "OK"


def test_v3_grade_inputs_recomputed_for_states_without_them_and_agree_with_synthesis():
    from agents import synthesis_agent as sa
    st = _instrumented_state()
    st["quantitative_result"].update(severity="Medium")
    st.pop("grade_inputs")
    c = _case("X", 1)
    row = ev._row_from_state(c, ev.case_params(c, "spec"), "spec", "spec", st)
    gi = row["grade_inputs"]
    assert gi["source"] == "recomputed" and gi["agents_flagging"] == 1 and gi["agents_high"] == 0
    assert gi["escalation"] is True and gi["focus_year_flagged"] is True and gi["jev_available"] is False
    out = sa.run_synthesis(dict(st, analysis_years=[2019, 2020], focus_year=2020))
    assert out["grade_inputs"]["agents_flagging"] == gi["agents_flagging"] and out["grade_inputs"]["escalation"] == gi["escalation"]


def test_v3_instrumentation_failure_cannot_break_a_row(monkeypatch):
    monkeypatch.setattr(ev, "_instrumentation", lambda *a, **k: 1 / 0)
    c = _case("X", 0)
    row = ev._row_from_state(c, ev.case_params(c, "spec"), "spec", "spec", _state("Low"))
    assert row["status"] == "OK" and row["risk_grade"] == "Low"
    assert any("instrumentation failed" in d for d in row["degraded"])


# ============================================================================================ v3 L3: paired metric
def _prow(t, gt, score, partner=None, status="OK", beneish=False):
    return {"ticker": t, "ground_truth": gt, "suspicion_score": score, "match_partner": partner, "status": status,
            "beneish_available": beneish}


def _pairs(spec):
    rows = []
    for i, (f, c) in enumerate(spec):
        rows += [_prow(f"F{i}", 1, f, f"C{i}"), _prow(f"C{i}", 0, c, f"F{i}")]
    return rows


def test_sign_test_exact_values_hand_computed():
    assert ev.sign_test_p(0, 0) is None
    assert ev.sign_test_p(8, 1) == pytest.approx(2 * (1 + 9) / 512)        # 0.0390625
    assert ev.sign_test_p(2, 1) == pytest.approx(1.0)                      # 2 * (1 + 3) / 8 = 1
    assert ev.sign_test_p(5, 0) == pytest.approx(2 / 32)                   # 0.0625
    assert ev.sign_test_p(4, 4) == 1.0
    assert ev.sign_test_p(1, 5) == pytest.approx(2 * (1 + 6) / 64)         # 0.21875
    assert ev.sign_test_p(5, 1) == ev.sign_test_p(1, 5)


def test_paired_comparison_hand_computed_with_ties():
    pc = ev.paired_comparison(_pairs([(5, 3), (4, 4), (2, 6), (7, 1)]))
    assert (pc["n_pairs"], pc["wins"], pc["ties"], pc["losses"]) == (4, 2, 1, 1)
    assert pc["paired_auc"] == pytest.approx((2 + 0.5) / 4)                 # 0.625
    assert pc["sign_test_p_two_sided"] == pytest.approx(1.0) and pc["n_non_tied"] == 3
    assert pc["available"] is True and [p["result"] for p in pc["pairs"]] == ["win", "tie", "loss", "win"]
    # the holdout-1 audit shape: 8 wins / 3 ties / 1 loss
    pc2 = ev.paired_comparison(_pairs([(9, 1)] * 8 + [(5, 5)] * 3 + [(1, 9)]))
    assert (pc2["wins"], pc2["ties"], pc2["losses"]) == (8, 3, 1)
    assert pc2["paired_auc"] == pytest.approx(9.5 / 12) and pc2["sign_test_p_two_sided"] == pytest.approx(0.0390625)


def test_paired_bootstrap_ci_is_reproducible_and_hand_checkable():
    # one win + one loss: resampled AUC in {0, .5, 1} with P = (.25, .5, .25) => 2.5th pct 0, 97.5th pct 1
    pc = ev.paired_comparison(_pairs([(5, 1), (1, 5)]))
    assert pc["paired_auc"] == 0.5 and (pc["auc_ci_low"], pc["auc_ci_high"]) == (0.0, 1.0)
    # all wins: every resample is 1.0 => degenerate CI
    allw = ev.paired_comparison(_pairs([(9, 1), (8, 2), (7, 3)]))
    assert (allw["paired_auc"], allw["auc_ci_low"], allw["auc_ci_high"]) == (1.0, 1.0, 1.0)
    spec = [(5, 3), (4, 4), (2, 6), (7, 1), (6, 2), (3, 3), (8, 1)]
    a, b = ev.paired_comparison(_pairs(spec)), ev.paired_comparison(_pairs(spec))
    assert (a["auc_ci_low"], a["auc_ci_high"]) == (b["auc_ci_low"], b["auc_ci_high"])
    assert a["auc_ci_low"] <= a["paired_auc"] <= a["auc_ci_high"]
    assert a["bootstrap"]["resamples"] == 10_000 and a["bootstrap"]["seed"] == ev.BOOTSTRAP_SEED
    assert ev.bootstrap_auc_ci([1.0, -1.0], n_boot=10_000, seed=ev.BOOTSTRAP_SEED) == (0.0, 1.0)


def test_paired_not_available_without_match_partner_and_exclusions_are_listed():
    pc = ev.paired_comparison([_prow("A", 1, 30), _prow("B", 0, 10)])
    assert pc["available"] is False and pc["n_pairs"] == 0 and pc["paired_auc"] is None and pc["sign_test_p_two_sided"] is None
    assert "n/a" in pc["note"]
    rows = [_prow("F", 1, 30, "C"), _prow("C", 0, None, "F"), _prow("F2", 1, 20, "GONE"), _prow("OK2", 1, 5, "C2"),
            _prow("C2", 0, 9, "OK2", status="ERROR")]
    pc = ev.paired_comparison(rows)
    assert pc["n_pairs"] == 0
    reasons = {(e["fraud"], e["control"]): e["reason"] for e in pc["excluded_pairs"]}
    assert "no stored suspicion score" in reasons[("F", "C")] and "missing" in reasons[("F2", "GONE")]
    assert ("OK2", "C2") in reasons


def test_paired_pair_found_from_either_side_and_not_double_counted():
    pc = ev.paired_comparison([_prow("F", 1, 30), _prow("C", 0, 10, "F")])  # only the control names its partner
    assert pc["n_pairs"] == 1 and pc["wins"] == 1


def test_beneish_availability_rates_hand_computed():
    rows = [_prow("F1", 1, 1, beneish=True), _prow("F2", 1, 1), _prow("F3", 1, 1), _prow("F4", 1, 1, beneish=True),
            _prow("C1", 0, 1, beneish=True), _prow("C2", 0, 1, beneish=True), _prow("E", 1, 1, status="ERROR")]
    b = ev.beneish_availability(rows)
    assert (b["fraud"]["num"], b["fraud"]["den"], b["fraud"]["value"]) == (2, 4, 0.5)
    assert (b["clean"]["num"], b["clean"]["den"], b["clean"]["value"]) == (2, 2, 1.0)
    assert b["fraud"]["unavailable_cases"] == ["F2", "F3"]
    assert ev.beneish_availability([])["fraud"]["value"] is None


def test_paired_and_beneish_in_results_json_and_markdown(tmp_path):
    scores = {"F1": 50, "C1": 20, "F2": 30, "C2": 30, "F3": 10, "C3": 40}

    def an(ticker, years=5, **kw):
        st = _state("Medium", beneish_flag=False if ticker.startswith("F") else None)
        st["temporal_result"]["suspicion_score"] = scores[ticker]
        return st
    cases = [_case("F1", 1, match_partner="C1"), _case("C1", 0, match_partner="F1"),
             _case("F2", 1, match_partner="C2"), _case("C2", 0, match_partner="F2"),
             _case("F3", 1, match_partner="C3"), _case("C3", 0, match_partner="F3")]
    r = _run(an, cases, tmp_path, use_cache=False)
    pc = r["headline"]["paired"]
    assert (pc["wins"], pc["ties"], pc["losses"]) == (1, 1, 1) and pc["paired_auc"] == pytest.approx(0.5)
    ba = r["headline"]["beneish_availability"]
    assert ba["fraud"]["num"] == 3 and ba["clean"]["num"] == 0
    saved = json.loads((tmp_path / "res" / "evaluation_results.json").read_text(encoding="utf-8"))
    assert saved["headline"]["paired"]["n_pairs"] == 3 and saved["headline"]["paired"]["sign_test_p_two_sided"] == 1.0
    md = (tmp_path / "res" / "evaluation_report.md").read_text(encoding="utf-8")
    assert "paired suspicion-score comparison" in md and "1 wins / 1 ties / 1 losses" in md and "Beneish availability" in md


def test_paired_report_says_na_for_the_original_cases(tmp_path):
    r = _run(lambda t, y=5, **kw: _state("Low"), [_case("A", 0), _case("B", 1)], tmp_path, use_cache=False)
    assert r["headline"]["paired"]["available"] is False
    md = (tmp_path / "res" / "evaluation_report.md").read_text(encoding="utf-8")
    assert "**n/a**" in md and "no matched fraud/control pairs" in md


# ============================================================================================ v3: cache safety
def test_v3_injected_analyze_never_touches_the_real_cache_dir(tmp_path, monkeypatch):
    real = tmp_path / "REAL_CACHE"
    monkeypatch.setattr(ev, "_cache_dir", lambda: real)
    calls = []

    def fake(ticker, years=5, **kw):
        calls.append(ticker)
        return _state("High")
    cases = [_case("A", 0), _case("B", 1)]
    _run(fake, cases, tmp_path)                       # use_cache defaults to True
    assert not real.exists() or not any(real.iterdir()), "an injected analyzer wrote to the real cache"
    r2 = _run(fake, cases, tmp_path)                  # the in-memory cache still resumes for the SAME analyzer object
    assert calls == ["A", "B"] and all(c["from_cache"] for c in r2["headline"]["cases"])
    assert not real.exists() or not any(real.iterdir())


def test_v3_real_cached_rows_are_never_served_to_an_injected_analyzer(tmp_path, monkeypatch):
    real = tmp_path / "REAL_CACHE"
    monkeypatch.setattr(ev, "_cache_dir", lambda: real)
    c = _case("A", 0)
    p = ev.case_params(c, "spec")
    ev._cache_write(ev._cache_path(c, p, "spec", "spec", ev.code_hash()),
                    ev._row_from_state(c, p, "spec", "spec", _state("Critical")))
    r = _run(lambda t, y=5, **kw: _state("Low"), [c], tmp_path)
    assert r["headline"]["cases"][0]["risk_grade"] == "Low" and r["headline"]["cases"][0]["from_cache"] is False


def test_v3_other_injected_analyzer_does_not_reuse_in_memory_rows(tmp_path):
    c = [_case("A", 0)]
    r1 = _run(lambda t, y=5, **kw: _state("High"), c, tmp_path)
    r2 = _run(lambda t, y=5, **kw: _state("Low"), c, tmp_path)
    assert r1["headline"]["cases"][0]["risk_grade"] == "High" and r2["headline"]["cases"][0]["risk_grade"] == "Low"


def test_v3_real_analyzer_path_still_uses_the_disk_cache(tmp_path, monkeypatch):
    real = tmp_path / "REAL_CACHE"
    monkeypatch.setattr(ev, "_cache_dir", lambda: real)
    calls = []

    async def real_analyze(ticker, years=5, **kw):
        calls.append(ticker)
        return _state("Low")
    monkeypatch.setattr(ev, "_default_analyze", lambda: real_analyze)
    kw = dict(cases=[_case("A", 0)], results_dir=tmp_path / "res")
    ev.run_evaluation(**kw)
    r2 = ev.run_evaluation(**kw)
    assert calls == ["A"] and r2["headline"]["cases"][0]["from_cache"] is True and any(real.iterdir())


def test_v3_cache_key_covers_keys_code_schema_and_label(monkeypatch):
    c = _case("A", 0)
    p = ev.case_params(c, "spec")
    base = ev._cache_path(c, p, "spec", "spec", "h1")
    assert base != ev._cache_path(c, p, "spec", "spec", "h2")                         # code hash
    assert base != ev._cache_path(dict(c, ground_truth=1), p, "spec", "spec", "h1")   # label
    with monkeypatch.context() as m:
        m.setattr(ev, "ROW_SCHEMA", ev.ROW_SCHEMA + 1)
        assert base != ev._cache_path(c, p, "spec", "spec", "h1")                     # row schema
    with monkeypatch.context() as m:
        m.setenv("ANTHROPIC_API_KEY", "")
        m.setenv("JEV_API_KEY", "")
        m.setenv("TYPESAFE_API_KEY", "")
        m.setattr("tools.common.load_env", lambda: None)
        assert base != ev._cache_path(c, p, "spec", "spec", "h1")                     # key availability


# ============================================================================================ v3: CLI case modules
def test_v3_load_cases_from_module_and_file(tmp_path):
    cases = ev.load_cases_from("evaluation.holdout_cases", "HOLDOUT_CASES")
    assert len(cases) == 24 and all("match_partner" in c for c in cases)
    f = tmp_path / "mycases.py"
    f.write_text("MY = [{'ticker': 'ZZ', 'ground_truth': 0}]\nNOT = 3\n", encoding="utf-8")
    assert ev.load_cases_from(str(f), "MY") == [{"ticker": "ZZ", "ground_truth": 0}]
    with pytest.raises(ValueError):
        ev.load_cases_from(str(f), "NOT")
    assert len(ev.load_cases_from("evaluation.fraud_cases")) == 12


def test_v3_cli_cases_module_runs_and_reports_pairs(tmp_path, monkeypatch):
    f = tmp_path / "cases_mod.py"
    c1, c2 = _case("P1", 1, match_partner="P2"), _case("P2", 0, match_partner="P1")
    f.write_text(f"CASES = {[c1, c2]!r}\n", encoding="utf-8")

    async def an(ticker, years=5, **kw):
        st = _state("Low")
        st["temporal_result"]["suspicion_score"] = 40 if ticker == "P1" else 10
        return st
    monkeypatch.setattr(ev, "_default_analyze", lambda: an)
    rc = ev.main(["--cases-module", str(f), "--cases-var", "CASES", "--results-dir", str(tmp_path / "out"), "--no-cache"])
    assert rc == 0
    saved = json.loads((tmp_path / "out" / "evaluation_results.json").read_text(encoding="utf-8"))
    assert [c["ticker"] for c in saved["headline"]["cases"]] == ["P1", "P2"]
    assert saved["headline"]["paired"]["n_pairs"] == 1 and saved["headline"]["paired"]["wins"] == 1
