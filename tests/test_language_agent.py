"""Tests for agents/language_agent.py (AGENT 2, language forensics).

* Real-filing tests (marked ``network``; cached under .cache so reruns are offline-fast) use AAPL FY2016-2020,
  Enron FY1999/2000 (.txt), Luckin FY2019-2021 (20-F) and Nikola FY2020 (10-K), fetched through
  tools.edgar_api (the same cached path the pipeline uses).
* Mechanics tests use SYNTHETIC, structure-only filings (clearly built in ``_filing`` below: filler prose,
  controlled hedge-word / character counts). They carry no financial figures.
* The LLM is always mocked (no API key exists in this environment).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agents.language_agent as la  # noqa: E402
from agents.language_agent import run_language  # noqa: E402
from agents.state import to_jsonable  # noqa: E402

# --------------------------------------------------------------------------------------------------
# Synthetic filing builder
# --------------------------------------------------------------------------------------------------
NEUTRAL = ("Revenue increased because customers purchased additional units during the period and the "
           "business continued to open new locations in existing markets across several regions.")  # 27 words, 0 hedges
HEDGY = "We believe revenue may increase and we expect approximately stable demand."  # hedges: believe, may, expect, approximately = 4; 10 words


def _para(n_neutral: int, n_hedgy: int) -> str:
    return " ".join([NEUTRAL] * n_neutral + [HEDGY] * n_hedgy)


def _filing(mdna: str, risk: str = "", legal: str = "None.") -> str:
    """A minimal 10-K whose Items the real text_parser can find."""
    return (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\n\nTable of Contents\n"
        "Item 1A. Risk Factors 5\nItem 3. Legal Proceedings 9\nItem 7. Management's Discussion and Analysis 12\n\n"
        "PART I\n\nItem 1. Business\n\nWe sell goods. " + "Business text here. " * 20 + "\n\n"
        "Item 1A. Risk Factors\n\n" + (risk or "Not applicable.") + "\n\n"
        "Item 1B. Unresolved Staff Comments\n\nNone.\n\n"
        "Item 2. Properties\n\nWe lease offices.\n\n"
        "Item 3. Legal Proceedings\n\n" + legal + "\n\n"
        "Item 4. Mine Safety Disclosures\n\nNot applicable.\n\n"
        "PART II\n\nItem 5. Market for Registrant's Common Equity\n\nOur stock trades.\n\n"
        "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations\n\n"
        + mdna + "\n\n"
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk\n\nNot material.\n\n"
        "Item 8. Financial Statements and Supplementary Data\n\nSee attached.\n\n"
        "Item 9. Changes in and Disagreements with Accountants\n\nNone.\n"
    )


def _risk(chars: int) -> str:
    unit = "Our results could suffer if competitors introduce rival products or if suppliers raise their prices. "
    return (unit * (chars // len(unit) + 2))[:chars]


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """Default: no LLM key (this environment has none). Tests that need the LLM re-patch."""
    monkeypatch.setattr(la.llm, "llm_available", lambda: False)


def _run(texts: dict, years: list[int], **extra) -> dict:
    out = run_language({"filing_texts": texts, "analysis_years": years, **extra})
    assert set(out) == {"language_result", "agent_trace", "degraded"}
    return out


# --------------------------------------------------------------------------------------------------
# 1. Hedging
# --------------------------------------------------------------------------------------------------
def test_hedging_ratio_hand_computed():
    # words: s1 = We believe that results may vary and could be subject to change = 12 ; s2 = We expect approximately
    # ten percent growth which is uncertain = 9  -> 21 words. hedges: believe, may, could, subject to, expect,
    # approximately, uncertain = 7 ("subject to" is ONE hedge).
    text = ("We believe that results may vary and could be subject to change. "
            "We expect approximately ten percent growth, which is uncertain.")
    h = la.hedging_counts(text)
    assert h["words"] == 21
    assert h["count"] == 7
    assert h["ratio"] == pytest.approx(7 / 21)
    assert h["by_term"]["subject to"] == 1


def test_hedging_word_boundaries_case_and_months():
    base = "The mayor planned the planetary exhibit and expected visitors to estimate the crowd size accurately today."
    assert la.hedging_counts(base)["count"] == 0  # mayor/planned/planetary/expected/estimate are not the listed words
    up = "WE BELIEVE results MAY vary, and we Could be Subject\nTo changes in demand across the many markets we serve."
    assert la.hedging_counts(up)["count"] == 4  # believe, MAY, Could, Subject To (across a line wrap)
    month = "Sales were stronger in May 2019 than in May 2018 because of the new products launched in the spring season."
    assert la.hedging_counts(month)["count"] == 0  # capitalised month, not the modal verb
    modal = "Results may differ from those reported in the prior year because the underlying conditions might change."
    assert la.hedging_counts(modal)["count"] == 2


def test_hedging_ignores_table_rows():
    table = "Net sales | $ | 1,200 | 1,100 may could expect plan\nCost of sales | 800 | 700\nGross margin | 400 | 400"
    assert la.hedging_counts(table)["words"] == 0  # tables are not prose


S_H = "We may see revenue increase across all of our main markets next year. "   # 13 words, 1 hedge
S_N = "We will see revenue increase across all of our main markets next year. "   # 13 words, 0 hedges


def _hedge_year(n_hedge: int, total: int = 200) -> str:
    return _filing(S_H * n_hedge + S_N * (total - n_hedge))


def test_hedging_yoy_flag_boundary_exact_25pct():
    # identical word totals (2600) so the ratio change equals the hedge-count change exactly
    r80 = la.hedging_counts(S_H * 80 + S_N * 120)
    assert (r80["count"], r80["words"]) == (80, 2600)
    exact = _run({2019: _hedge_year(80), 2020: _hedge_year(100)}, [2020])["language_result"]["hedging_trend"][2020]
    assert exact["yoy_change"] == pytest.approx(0.25) and exact["flag"] is False  # +25% is NOT > +25%
    over = _run({2019: _hedge_year(80), 2020: _hedge_year(101)}, [2020])["language_result"]
    assert over["hedging_trend"][2020]["flag"] is True
    assert la.FLAG_HEDGING in over["flags_by_year"][2020]
    assert over["flags_fired"] == 1


def test_hedging_decrease_and_flat_do_not_flag():
    r = _run({2019: _hedge_year(80), 2020: _hedge_year(80)}, [2020])["language_result"]
    assert r["hedging_trend"][2020]["yoy_change"] == pytest.approx(0.0) and r["hedging_trend"][2020]["flag"] is False
    r = _run({2019: _hedge_year(80), 2020: _hedge_year(40)}, [2020])["language_result"]
    assert r["hedging_trend"][2020]["yoy_change"] == pytest.approx(-0.5) and r["hedging_trend"][2020]["flag"] is False


def test_hedging_evidence_numbers_are_code_computed():
    texts = {2019: _hedge_year(50), 2020: _hedge_year(90)}
    r = _run(texts, [2020])["language_result"]
    h = r["hedging_trend"][2020]
    ev = [e for e in r["evidence"] if e["flag"] == la.FLAG_HEDGING]
    assert len(ev) == 1
    up = round(h["yoy_change_pct"])
    pct = round(100 * h["ratio"], 1)
    assert ev[0]["display"] == f"Hedging-word ratio rose {up}% to {pct}% of MD&A words in FY2020"
    assert ev[0]["numbers"] == [up, pct, 2020]
    assert ev[0]["year"] == 2020 and ev[0]["metric"] == "hedging_ratio"
    assert r["flags_fired"] == 1 and r["severity"] == "Low"


def test_first_year_has_no_yoy_and_no_flag():
    r = _run({2020: _filing(_para(40, 12))}, [2020])["language_result"]
    h = r["hedging_trend"][2020]
    assert h["ratio"] is not None and h["flag"] is False and h["yoy_change"] is None
    assert "hedging_trend.2020.yoy" in r["data_quality"]["unavailable"]


def test_short_mdna_is_unavailable_not_zero():
    r = _run({2020: _filing("Short MD&A. " * 10)}, [2020])["language_result"]
    h = r["hedging_trend"][2020]
    assert h["ratio"] is None and h["flag"] is False and h["reason"].startswith("unavailable")
    assert "hedging_trend.2020" in r["data_quality"]["unavailable"]
    assert r["passive_voice"][2020]["pct"] is None


# --------------------------------------------------------------------------------------------------
# 2. Passive voice
# --------------------------------------------------------------------------------------------------
PASSIVE_SENTENCES = [
    "The report was written by the committee and reviewed carefully.",
    "Costs were increased by higher volumes of shipments.",
    "Revenue is expected to grow during the next fiscal year.",
    "The company has been named in several lawsuits.",
]
ACTIVE_SENTENCES = [
    "The committee wrote the report and reviewed it carefully.",
    "We increased prices across all of our product lines.",
    "Customers purchased more units during the quarter.",
    "Management expects growth to continue next year.",
]


def test_passive_rule_based_on_hand_written_sentences():
    for s in PASSIVE_SENTENCES:
        assert la.passive_rule_based(s) is True, s
    for s in ACTIVE_SENTENCES:
        assert la.passive_rule_based(s) is False, s


def test_passive_rule_based_percentage_hand_computed():
    text = " ".join(PASSIVE_SENTENCES[:1] + ACTIVE_SENTENCES[:3])  # 1 passive of 4 sentences
    st = la.passive_stats(text, None)
    assert st["sentences"] == 4 and st["passive_sentences"] == 1
    assert st["pct"] == pytest.approx(25.0)
    assert st["method"] == "rule-based"


@pytest.fixture(scope="module")
def nlp():
    n = la.get_nlp()
    if n is None:
        pytest.skip("spaCy model en_core_web_sm not installed")
    return n


def test_passive_spacy_on_hand_written_sentences(nlp):
    for s in PASSIVE_SENTENCES:
        st = la.passive_stats(s + " " + ACTIVE_SENTENCES[0], nlp)  # >= 12 words of prose
        assert st["passive_sentences"] == 1, s
    for s in ACTIVE_SENTENCES:
        st = la.passive_stats(s + " " + ACTIVE_SENTENCES[1], nlp)
        assert st["passive_sentences"] == 0, s


def test_passive_spacy_percentage(nlp):
    text = " ".join(PASSIVE_SENTENCES[:2] + ACTIVE_SENTENCES[:2])  # 2 of 4
    st = la.passive_stats(text, nlp)
    assert (st["sentences"], st["passive_sentences"]) == (4, 2)
    assert st["pct"] == pytest.approx(50.0)
    assert st["method"].startswith("spacy:")


def _passive_mdna(n_pass: int, n_act: int) -> str:
    # one sentence per line group -> 1 paragraph of sentences; enough words for the 1000-word guard via filler
    sents = [PASSIVE_SENTENCES[i % 4] for i in range(n_pass)] + [ACTIVE_SENTENCES[i % 4] for i in range(n_act)]
    return " ".join(sents)


def _passive_year(n_pass, total):
    """Synthetic MD&A: n_pass passive sentences among `total` sentences (rule-based detector; the rest are active)."""
    return _filing(" ".join([_passive_mdna(n_pass, 0)] + [NEUTRAL] * (total - n_pass)))


def test_passive_pct_measured_and_reported_rule_based(monkeypatch):
    monkeypatch.setattr(la, "get_nlp", lambda: None)
    out = _run({2020: _passive_year(15, 100)}, [2020])
    r = out["language_result"]["passive_voice"][2020]
    assert r["sentences"] == 100 and r["passive_sentences"] == 15 and r["pct"] == pytest.approx(15.0)
    assert r["method"] == "rule-based" and any("rule-based" in d for d in out["degraded"])


# ------------------------------------------------------------------ v2 B7: passive voice is a YoY-increase flag (like hedging)
def test_v2_passive_fixed_cutoff_is_gone_a_flat_high_level_never_flags(monkeypatch):
    monkeypatch.setattr(la, "get_nlp", lambda: None)
    r = _run({2019: _passive_year(30, 100), 2020: _passive_year(30, 100)}, [2020])["language_result"]
    p = r["passive_voice"][2020]
    assert p["pct"] == pytest.approx(30.0) and p["flag"] is False and p["yoy_change_pct"] == pytest.approx(0.0)
    assert la.FLAG_PASSIVE not in r["flags_by_year"][2020]
    assert la.PASSIVE_YOY_THRESHOLD == 0.25 and not hasattr(la, "PASSIVE_PCT_THRESHOLD")


def test_v2_passive_yoy_boundary_exactly_25pct_is_not_a_flag(monkeypatch):
    monkeypatch.setattr(la, "get_nlp", lambda: None)
    r = _run({2019: _passive_year(8, 100), 2020: _passive_year(10, 100)}, [2020])["language_result"]  # 8% -> 10% = +25.0%
    assert r["passive_voice"][2020]["flag"] is False
    r = _run({2019: _passive_year(8, 100), 2020: _passive_year(11, 100)}, [2020])["language_result"]  # +37.5%
    p = r["passive_voice"][2020]
    assert p["flag"] is True and p["yoy_change_pct"] == pytest.approx(37.5) and p["pct"] == pytest.approx(11.0)
    assert la.FLAG_PASSIVE in r["flags_by_year"][2020]
    ev = [e for e in r["evidence"] if e["flag"] == la.FLAG_PASSIVE][0]
    assert ev["numbers"] == [38, 11.0, 2020] and "rose" in ev["display"] and "11.0%" in ev["display"]


def test_v2_passive_decrease_and_first_year_do_not_flag(monkeypatch):
    monkeypatch.setattr(la, "get_nlp", lambda: None)
    r = _run({2019: _passive_year(20, 100), 2020: _passive_year(10, 100)}, [2020])["language_result"]
    assert r["passive_voice"][2020]["flag"] is False
    r = _run({2020: _passive_year(40, 100)}, [2020])["language_result"]
    assert r["passive_voice"][2020]["flag"] is False and r["passive_voice"][2020]["pct"] == pytest.approx(40.0)


# ------------------------------------------------------------------ v2 B8/B2: shell / SPAC predecessor years are not baselines
SHELL_2019 = {2019: {"is_shell": True, "spac_predecessor": True, "reason": "blank-check company before business combination"}}


def test_v2_hedging_flag_needs_a_valid_baseline_year():
    mdna_lo, mdna_hi = _para(60, 3), _para(60, 20)
    texts = {2019: _filing(mdna_lo), 2020: _filing(mdna_hi)}
    assert la.FLAG_HEDGING in _run(texts, [2020])["language_result"]["flags_by_year"][2020]
    r = _run(texts, [2020], filing_entity_flags=SHELL_2019)["language_result"]
    assert la.FLAG_HEDGING not in r["flags_by_year"][2020]
    assert r["hedging_trend"][2020]["yoy_change"] is None and "shell" in r["hedging_trend"][2020]["yoy_note"]
    assert r["excluded_entity_years"] == {2019: "blank-check company before business combination"}


def test_v2_shell_year_itself_never_flags():
    mdna_lo, mdna_hi = _para(60, 3), _para(60, 20)
    texts = {2018: _filing(mdna_lo), 2019: _filing(mdna_hi), 2020: _filing(mdna_lo)}
    r = _run(texts, [2019, 2020], filing_entity_flags=SHELL_2019)["language_result"]
    assert r["flags_by_year"][2019] == []


def test_v2_risk_factor_growth_and_legal_need_valid_baseline():
    mdna = _para(60, 0)
    texts = {2019: _filing(mdna, _risk(10_000), LEGAL_A), 2020: _filing(mdna, _risk(20_000), LEGAL_A + "\n\n" + NEW_PARA)}
    ok = _run(texts, [2020])["language_result"]
    assert {la.FLAG_RISK, la.FLAG_LEGAL} <= set(ok["flags_by_year"][2020])
    r = _run(texts, [2020], filing_entity_flags=SHELL_2019)["language_result"]
    assert la.FLAG_RISK not in r["flags_by_year"][2020] and la.FLAG_LEGAL not in r["flags_by_year"][2020]
    assert r["new_legal_proceedings"][2020]["status"] == "no_prior_year"
    assert "shell" in r["new_legal_proceedings"][2020]["reason"]


def test_v2_specificity_drop_needs_valid_baseline_but_level_test_remains(monkeypatch):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    scores = {2019: 9, 2020: 6}
    monkeypatch.setattr(la, "_score_specificity", lambda y, m: {"score": scores[y], "reason": "r", "flag": False})
    mdna = _para(60, 0)
    texts = {2019: _filing(mdna), 2020: _filing(mdna)}
    assert _run(texts, [2020])["language_result"]["specificity_scores"][2020]["flag"] is True       # drop of 3
    r = _run(texts, [2020], filing_entity_flags=SHELL_2019)["language_result"]
    assert r["specificity_scores"][2020]["flag"] is False                                          # 6 >= 5 and no baseline
    scores[2020] = 4
    r = _run(texts, [2020], filing_entity_flags=SHELL_2019)["language_result"]
    assert r["specificity_scores"][2020]["flag"] is True                                           # level test < 5 still applies


def test_v2_malformed_entity_flags_tolerated():
    mdna = _para(60, 3)
    for bad in (None, "x", [], {"a": 1}, {2019: None}, {2019: "oops"}):
        r = _run({2019: _filing(mdna), 2020: _filing(mdna)}, [2020], filing_entity_flags=bad)["language_result"]
        assert r["excluded_entity_years"] == {}


# ------------------------------------------------------------------ v2 B11 (consumer): legal_note when Item 3 only points to a note
POINTER = "See Note 12, Commitments and Contingencies, in the Notes to Consolidated Financial Statements for information."


def _with_legal_note(monkeypatch, notes: dict):
    real = la.extract_sections

    def wrapped(text, form=None):
        secs = real(text, form)
        for marker, note in notes.items():
            if marker in text:
                secs = dict(secs, legal_note=note)
        return secs
    monkeypatch.setattr(la, "extract_sections", wrapped)


def test_v2_legal_note_used_when_item3_is_a_pointer(monkeypatch):
    mdna = _para(60, 0)
    _with_legal_note(monkeypatch, {"MARK2019": LEGAL_A, "MARK2020": LEGAL_A + "\n\n" + NEW_PARA})
    texts = {2019: _filing(mdna, legal=POINTER + " MARK2019"), 2020: _filing(mdna, legal=POINTER + " MARK2020")}
    r = _run(texts, [2020])["language_result"]
    L = r["new_legal_proceedings"][2020]
    assert L["detected"] is True and L["source"] == "legal_note" and la.FLAG_LEGAL in r["flags_by_year"][2020]
    assert r["new_legal_proceedings"][2019]["source"] == "legal_note"


def test_v2_without_legal_note_pointer_stays_low_confidence():
    mdna = _para(60, 0)
    texts = {2019: _filing(mdna, legal=POINTER), 2020: _filing(mdna, legal=POINTER)}
    L = _run(texts, [2020])["language_result"]["new_legal_proceedings"][2020]
    assert L["detected"] is False and L["status"] == "incorporated_by_reference"


def test_v2_inline_item3_is_preferred_over_note(monkeypatch):
    mdna = _para(60, 0)
    _with_legal_note(monkeypatch, {"MARKX": LEGAL_A + "\n\n" + NEW_PARA})
    texts = {2019: _filing(mdna, legal=LEGAL_A), 2020: _filing(mdna, legal=LEGAL_A + " MARKX")}
    L = _run(texts, [2020])["language_result"]["new_legal_proceedings"][2020]
    assert L["detected"] is False and L["source"] == "item3"


def test_v2_mixed_sources_between_years_are_not_compared(monkeypatch):
    mdna = _para(60, 0)
    _with_legal_note(monkeypatch, {"MARKN": LEGAL_A + "\n\n" + NEW_PARA})
    texts = {2019: _filing(mdna, legal=LEGAL_A), 2020: _filing(mdna, legal=POINTER + " MARKN")}
    L = _run(texts, [2020])["language_result"]["new_legal_proceedings"][2020]
    assert L["detected"] is False and L["status"] == "source_changed" and L["confidence"] == "low"


def test_passive_degrades_to_rule_based_when_model_missing(monkeypatch):
    monkeypatch.setattr(la, "get_nlp", lambda: None)
    out = _run({2020: _filing(_para(60, 5))}, [2020])
    assert any(d.startswith("language_passive_voice:") and "rule-based" in d for d in out["degraded"])
    assert out["language_result"]["methodology"]["passive_method"] == "rule-based"
    assert out["agent_trace"][0]["status"] == "degraded"


# --------------------------------------------------------------------------------------------------
# 3. Risk factor length
# --------------------------------------------------------------------------------------------------
def test_risk_factor_growth_boundary_40pct():
    mdna = _para(60, 0)
    base = _run({2019: _filing(mdna, _risk(10_000)), 2020: _filing(mdna, _risk(14_000))}, [2020])["language_result"]
    r = base["risk_factor_length"][2020]
    assert r["chars"] == len(_risk(14_000).strip()) or abs(r["chars"] - 14_000) < 5
    assert r["yoy_change"] == pytest.approx((r["chars"] - r["prior_chars"]) / r["prior_chars"])
    over = _run({2019: _filing(mdna, _risk(10_000)), 2020: _filing(mdna, _risk(14_300))}, [2020])["language_result"]
    assert over["risk_factor_length"][2020]["flag"] is True
    ev = [e for e in over["evidence"] if e["flag"] == la.FLAG_RISK][0]
    pct = round(over["risk_factor_length"][2020]["yoy_change_pct"])
    assert ev["display"].startswith(f"Risk Factors section grew {pct}% to ")
    under = _run({2019: _filing(mdna, _risk(10_000)), 2020: _filing(mdna, _risk(13_800))}, [2020])["language_result"]
    assert under["risk_factor_length"][2020]["flag"] is False


def test_risk_factor_stub_is_unavailable_not_growth():
    mdna = _para(60, 0)
    r = _run({2019: _filing(mdna, "See Item 1 - Business - Risk Factors."), 2020: _filing(mdna, _risk(20_000))},
             [2020])["language_result"]
    assert r["risk_factor_length"][2019]["chars"] is None
    assert r["risk_factor_length"][2020]["yoy_change"] is None and r["risk_factor_length"][2020]["flag"] is False
    assert "risk_factor_length.2020.yoy" in r["data_quality"]["unavailable"]


# --------------------------------------------------------------------------------------------------
# 4. Specificity (mocked LLM)
# --------------------------------------------------------------------------------------------------
def _texts2():
    return {2019: _filing(_para(60, 2)), 2020: _filing(_para(60, 2))}


def test_specificity_no_key_is_none_with_degraded_entry():
    out = _run(_texts2(), [2020])
    s = out["language_result"]["specificity_scores"][2020]
    assert s == {"score": None, "reason": "unavailable: no ANTHROPIC_API_KEY", "flag": False}
    assert any(d.startswith("language_specificity:") and "ANTHROPIC_API_KEY" in d for d in out["degraded"])
    assert la.FLAG_SPECIFICITY not in out["language_result"]["flags_by_year"][2020]


def test_specificity_valid_json_flags_low_score_and_drop(monkeypatch):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    seen = []

    def fake(tier, system, user, *, max_tokens=800):
        seen.append((tier, system, user))
        return {"score": 8, "reason": "concrete"} if "Fiscal year 2019" in user else {"score": 4, "reason": "vague"}

    monkeypatch.setattr(la.llm, "llm_json", fake)
    r = _run(_texts2(), [2020])["language_result"]
    s = r["specificity_scores"][2020]
    assert s["score"] == 4 and s["reason"] == "vague" and s["flag"] is True and s["drop"] == 4
    assert la.FLAG_SPECIFICITY in r["flags_by_year"][2020]
    assert all(t == "haiku" and sy is la.SPECIFICITY_SYSTEM_PROMPT for t, sy, _ in seen)
    ev = [e for e in r["evidence"] if e["flag"] == la.FLAG_SPECIFICITY][0]
    assert ev["source"] == "llm" and 4 in ev["numbers"] and 8 in ev["numbers"] and 2020 in ev["numbers"]


@pytest.mark.parametrize("prev,cur,flag", [(8, 5, True), (7, 5, False), (9, 4, True), (5, 5, False), (4, 7, True)])
def test_specificity_flag_rules(monkeypatch, prev, cur, flag):
    # drop > 2 flags (8->5 drop 3: yes; 7->5 drop 2: no); score < 5 flags (9->4, and 4 -> 7 flags only the 2019 year)
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    monkeypatch.setattr(la.llm, "llm_json",
                        lambda t, s, u, **k: {"score": prev if "Fiscal year 2019" in u else cur, "reason": "x"})
    r = _run(_texts2(), [2020])["language_result"]
    if prev == 4 and cur == 7:
        assert r["specificity_scores"][2020]["flag"] is False  # 2019's low score is the baseline year, not analysed
    else:
        assert r["specificity_scores"][2020]["flag"] is flag


def test_specificity_mdna_truncated_to_12k(monkeypatch):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    users = []
    monkeypatch.setattr(la.llm, "llm_json", lambda t, s, u, **k: users.append(u) or {"score": 6, "reason": "ok"})
    _run({2020: _filing(_para(900, 0))}, [2020])  # ~ 24k chars of MD&A
    assert users and all(len(u) <= la.MDNA_LLM_MAX_CHARS + 200 for u in users)
    assert len(users[0]) > 10_000  # but it really sent the (truncated) MD&A


@pytest.mark.parametrize("bad", [None, {}, {"score": "high"}, {"score": 11}, {"score": 0}, {"score": True}, {"reason": "x"}, ["x"]])
def test_specificity_malformed_llm_output_never_crashes(monkeypatch, bad):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    monkeypatch.setattr(la.llm, "llm_json", lambda *a, **k: bad)
    out = _run(_texts2(), [2020])
    s = out["language_result"]["specificity_scores"][2020]
    assert s["score"] is None and s["flag"] is False and s["reason"].startswith("unavailable")
    assert any(d.startswith("language_specificity:") for d in out["degraded"])


def test_specificity_llm_exception_never_crashes(monkeypatch):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(la.llm, "llm_json", boom)
    out = _run(_texts2(), [2020])
    s = out["language_result"]["specificity_scores"][2020]
    assert s["score"] is None and "RuntimeError" in s["reason"]
    assert "error" not in out["language_result"]


def test_specificity_float_score_is_rounded(monkeypatch):
    monkeypatch.setattr(la.llm, "llm_available", lambda: True)
    monkeypatch.setattr(la.llm, "llm_json", lambda *a, **k: {"score": 6.4, "reason": "ok"})
    assert _run(_texts2(), [2020])["language_result"]["specificity_scores"][2020]["score"] == 6


# --------------------------------------------------------------------------------------------------
# 5. New legal proceedings
# --------------------------------------------------------------------------------------------------
LEGAL_A = (
    "Smith v. Acme Holdings Corp. In March 2017, a putative class action was filed in the United States District "
    "Court for the Southern District of New York alleging violations of the securities laws. The company believes "
    "the claims are without merit and intends to defend vigorously. Damages of $12 million are sought.\n\n"
    "Environmental Matter. The company received a notice from the state environmental agency regarding remediation "
    "of a former manufacturing site and has accrued $3 million for the estimated cost of cleanup work."
)
LEGAL_A_REDATED = LEGAL_A.replace("March 2017", "April 2017").replace("$12 million", "$15 million").replace("$3 million", "$4.5 million")
NEW_PARA = ("Jones v. Beta Industries Inc. A former distributor filed a complaint in the Superior Court of California "
            "alleging breach of an exclusive distribution agreement and seeking unspecified damages and injunctive relief "
            "against the company's subsidiary in connection with the termination of the agreement.")


def test_legal_identical_text_is_not_new():
    r = la.compare_legal(LEGAL_A, LEGAL_A)
    assert r["detected"] is False and r["text"] == "" and r["n_units"] == 2


def test_legal_ignores_dates_and_dollar_amounts():
    assert la.compare_legal(LEGAL_A, LEGAL_A_REDATED)["detected"] is False


def test_legal_new_paragraph_detected_with_excerpt():
    r = la.compare_legal(LEGAL_A, LEGAL_A + "\n\n" + NEW_PARA)
    assert r["detected"] is True and r["new_units"] == 1 and r["confidence"] == "high"
    assert r["text"].startswith("Jones v. Beta Industries") and len(r["text"]) <= la.EXCERPT_MAX_CHARS


def test_legal_excerpt_is_capped_at_400_chars():
    long_new = NEW_PARA + " " + "Additional detail about the dispute and its procedural history. " * 12
    r = la.compare_legal(LEGAL_A, LEGAL_A + "\n\n" + long_new)
    assert r["detected"] and len(r["text"]) <= 400 and r["text"].endswith("...")


def test_legal_boilerplate_not_a_party_is_not_a_proceeding():
    nothing = "We are not a party to any material legal proceedings."
    r = la.compare_legal(nothing, "We are not currently a party to any material pending legal proceedings.")
    assert r["detected"] is False and r["status"] == "none_disclosed"
    # boilerplate -> real proceeding IS new
    r2 = la.compare_legal(nothing, LEGAL_A)
    assert r2["detected"] is True and r2["new_units"] == 2


def test_legal_incorporation_by_reference_is_low_confidence_not_zero():
    ptr = ("Discussion of legal matters is incorporated by reference from Part II, Item 8, Note 16, "
           "Commitments and Contingencies, of this document.")
    r = la.compare_legal(ptr, ptr)
    assert r["detected"] is False and r["confidence"] == "low" and r["status"] == "incorporated_by_reference"
    r2 = la.compare_legal(ptr, LEGAL_A)
    assert r2["detected"] is False and r2["confidence"] == "low" and r2["status"] == "prior_year_by_reference"


def test_legal_flag_through_agent_and_evidence():
    mdna = _para(60, 0)
    texts = {2019: _filing(mdna, legal=LEGAL_A), 2020: _filing(mdna, legal=LEGAL_A + "\n\n" + NEW_PARA)}
    out = _run(texts, [2020])
    r = out["language_result"]
    assert r["new_legal_proceedings"][2020]["detected"] is True
    assert la.FLAG_LEGAL in r["flags_by_year"][2020]
    ev = [e for e in r["evidence"] if e["flag"] == la.FLAG_LEGAL][0]
    assert ev["numbers"] == [1, 2020, 2019] and ev["text"].startswith("Jones v. Beta")
    assert r["key_finding"].startswith("A materially new legal proceeding appeared in the FY2020")
    assert r["new_legal_proceedings"][2019]["status"] == "no_prior_year"


def test_legal_ongoing_matter_update_with_same_parties_not_new():
    upd = LEGAL_A.replace("The company believes the claims are without merit and intends to defend vigorously.",
                          "The court granted in part the motion to dismiss, and the company continues to defend the "
                          "Smith v. Acme Holdings Corp. matter vigorously.")
    assert la.compare_legal(LEGAL_A, upd)["detected"] is False


# --------------------------------------------------------------------------------------------------
# Contract / robustness
# --------------------------------------------------------------------------------------------------
def test_result_contract_fields_and_json_serialisable():
    texts = {2019: _filing(_para(60, 2), _risk(8000), LEGAL_A), 2020: _filing(_para(60, 4), _risk(9000), LEGAL_A)}
    out = _run(texts, [2019, 2020], focus_year=2020)
    r = out["language_result"]
    for key in ("hedging_trend", "passive_voice", "risk_factor_length", "specificity_scores", "new_legal_proceedings",
                "flags_fired", "key_finding", "severity", "flags_by_year", "focus_year", "data_quality", "degraded",
                "evidence"):
        assert key in r, key
    assert r["severity"] in {"None", "Low", "Medium", "High"} and r["focus_year"] == 2020
    assert isinstance(r["key_finding"], str) and r["key_finding"].count("\n") == 0
    assert set(r["flags_by_year"]) == {2019, 2020}
    assert r["flags_fired"] == sum(len(v) for v in r["flags_by_year"].values())
    json.dumps(to_jsonable(out), allow_nan=False)  # int keys/NaN handled by the shared helper
    tr = out["agent_trace"][0]
    assert tr["agent"] == "language" and {"status", "started", "duration_ms", "summary", "degraded"} <= set(tr)


def test_severity_ladder():
    mdna_lo, mdna_hi = _para(60, 3), _para(60, 20)
    legal_new = LEGAL_A + "\n\n" + NEW_PARA
    one = _run({2019: _filing(mdna_lo, _risk(10_000)), 2020: _filing(mdna_hi, _risk(10_000))}, [2020])["language_result"]
    assert la.FLAG_HEDGING in one["flags_by_year"][2020]
    base_flags = set(one["flags_by_year"][2020])
    two = _run({2019: _filing(mdna_lo, _risk(10_000), LEGAL_A), 2020: _filing(mdna_hi, _risk(10_000), legal_new)},
               [2020])["language_result"]
    three = _run({2019: _filing(mdna_lo, _risk(10_000), LEGAL_A), 2020: _filing(mdna_hi, _risk(20_000), legal_new)},
                 [2020])["language_result"]
    exp = {0: "None", 1: "Low", 2: "Medium"}
    for res in (one, two, three):
        n = len(res["flags_by_year"][2020])
        assert res["severity"] == ("High" if n >= 3 else exp[n])
    assert len(three["flags_by_year"][2020]) >= 3 and three["severity"] == "High"
    assert len(two["flags_by_year"][2020]) >= 2 and two["severity"] in ("Medium", "High")
    assert base_flags


def test_sections_missing_everything_unavailable_no_flags():
    garbage = "This is just prose without any item headings at all. " * 300
    out = _run({2019: garbage, 2020: garbage}, [2020])
    r = out["language_result"]
    assert r["flags_fired"] == 0 and r["severity"] == "None"
    assert r["hedging_trend"][2020]["ratio"] is None
    assert r["passive_voice"][2020]["pct"] is None
    assert r["risk_factor_length"][2020]["chars"] is None
    assert r["new_legal_proceedings"][2020]["status"] in ("unavailable", "no_prior_year")
    un = r["data_quality"]["unavailable"]
    assert {"hedging_trend.2020", "passive_voice.2020", "risk_factor_length.2020"} <= set(un)
    assert "unavailable" in r["key_finding"] or "No language" in r["key_finding"]


@pytest.mark.parametrize("state", [
    {}, {"filing_texts": None}, {"filing_texts": {}}, {"filing_texts": {2020: ""}}, {"filing_texts": {2020: None}},
    {"filing_texts": {2020: 12345}}, {"filing_texts": {"2020": "x"}, "analysis_years": ["2020"]},
    {"filing_texts": {2020: "\x00�" * 5000}, "analysis_years": [2020]}, {"analysis_years": [2020]},
    {"filing_texts": {2020: "Item 7. Management's Discussion\n" * 50, 2019: "Item 3. Legal Proceedings\n"}, "analysis_years": [2019, 2020]},
])
def test_garbage_input_never_raises(state):
    out = run_language(state)
    assert "language_result" in out and out["agent_trace"][0]["agent"] == "language"
    r = out["language_result"]
    assert r["severity"] in {"None", "Low", "Medium", "High"} and isinstance(r["flags_fired"], int)
    assert r["flags_fired"] == 0
    json.dumps(to_jsonable(out), allow_nan=False)


def test_non_dict_state_never_raises():
    out = run_language(None)  # type: ignore[arg-type]
    assert out["language_result"]["flags_fired"] == 0


def test_internal_failure_returns_contract_error_result(monkeypatch):
    def boom(state):
        raise ValueError("kaboom")

    monkeypatch.setattr(la, "_analyse", boom)
    out = run_language({"filing_texts": {2020: "x"}})
    r = out["language_result"]
    assert r["unavailable"] is True and r["severity"] == "None" and r["flags_fired"] == 0
    assert r["flags_by_year"] == {} and "kaboom" in r["error"] and r["key_finding"].startswith("language unavailable")
    assert out["agent_trace"][0]["status"] == "error"


def test_str_year_keys_are_accepted():
    out = _run({"2019": _filing(_para(60, 2)), "2020": _filing(_para(60, 12))}, ["2020"])
    assert 2020 in out["language_result"]["hedging_trend"]


def test_agent_does_not_read_other_agents_results():
    texts = {2020: _filing(_para(60, 2))}
    a = run_language({"filing_texts": texts, "analysis_years": [2020]})["language_result"]
    b = run_language({"filing_texts": texts, "analysis_years": [2020],
                      "quantitative_result": {"flags_fired": 99}, "network_result": {"x": 1}})["language_result"]
    assert json.dumps(to_jsonable(a), sort_keys=True) == json.dumps(to_jsonable(b), sort_keys=True)


# --------------------------------------------------------------------------------------------------
# Real filings (cached SEC data via tools.edgar_api)
# --------------------------------------------------------------------------------------------------
def _real_texts(ticker: str, years: list[int], cik: str | None = None) -> tuple[dict[int, str], list[dict]]:
    from tools import edgar_api as E

    try:
        c = E.resolve_company(ticker, cik=cik)
        filings = {f["fiscal_year"]: f for f in E.list_annual_filings(c["cik"]) if f["fiscal_year"] in years}
        texts = {y: E.fetch_filing_text(filings[y]) for y in years if y in filings}
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"SEC data unavailable: {exc}")
    if not texts:
        pytest.skip(f"no filings for {ticker}")
    return texts, [filings[y] for y in texts]


@pytest.fixture(scope="module")
def aapl():
    return _real_texts("AAPL", [2015, 2016, 2017, 2018, 2019, 2020])


@pytest.mark.network
def test_real_aapl_five_years(aapl):
    texts, filings = aapl
    t0 = time.perf_counter()
    out = run_language({"filing_texts": texts, "analysis_years": [2016, 2017, 2018, 2019, 2020], "filings": filings})
    elapsed = time.perf_counter() - t0
    r = out["language_result"]
    assert elapsed < 30, f"5-year analysis took {elapsed:.1f}s (budget 30s)"
    for y in range(2016, 2021):
        h = r["hedging_trend"][y]
        assert h["ratio"] is not None and 0.001 < h["ratio"] < 0.03, (y, h["ratio"])
        assert h["count"] > 20 and h["words"] > 2000
        p = r["passive_voice"][y]
        assert 5 < p["pct"] < 60 and p["sentences"] > 100
        assert r["risk_factor_length"][y]["chars"] > 40_000  # Apple's Item 1A is ~52-61k chars
    # YoY arithmetic is internally consistent
    h20, h19 = r["hedging_trend"][2020], r["hedging_trend"][2019]
    assert h20["yoy_change"] == pytest.approx((h20["ratio"] - h19["ratio"]) / h19["ratio"])
    rf = r["risk_factor_length"]
    assert rf[2020]["yoy_change"] == pytest.approx((rf[2020]["chars"] - rf[2019]["chars"]) / rf[2019]["chars"])
    # no key: specificity unavailable, honestly
    assert all(r["specificity_scores"][y]["score"] is None for y in range(2016, 2021))
    assert any("ANTHROPIC_API_KEY" in d for d in out["degraded"])
    # Apple's Item 3 only points at a note in later years: v2 (B11) compares the referenced contingencies note when the
    # parser supplies it; otherwise it stays low-confidence, never "no new proceedings" with high confidence
    L20 = r["new_legal_proceedings"][2020]
    assert (L20["source"] == "legal_note" and L20["confidence"] == "high") or L20["confidence"] == "low"
    assert r["flags_by_year"][2016] is not None
    json.dumps(to_jsonable(out), allow_nan=False)


@pytest.mark.network
def test_real_aapl_risk_factor_length_matches_text_parser(aapl):
    from tools.text_parser import extract_sections

    texts, _ = aapl
    r = run_language({"filing_texts": {2020: texts[2020]}, "analysis_years": [2020]})["language_result"]
    assert r["risk_factor_length"][2020]["chars"] == len(extract_sections(texts[2020], "10-K")["risk_factors"])


@pytest.mark.network
def test_real_msft_truncated_parser_sections_are_recovered():
    texts, _ = _real_texts("MSFT", [2018, 2019])
    r = run_language({"filing_texts": texts, "analysis_years": [2019]})["language_result"]
    # text_parser truncates MSFT's MD&A / Risk Factors at running page headers (3-4k chars); the supplement recovers them
    assert r["sections"][2019]["mdna_chars"] > 30_000 and r["sections"][2019]["risk_factor_chars"] > 40_000
    assert r["sections"][2019]["risk_method"] == "language_agent-heading-supplement"
    assert r["hedging_trend"][2019]["ratio"] is not None


@pytest.fixture(scope="module")
def enron():
    return _real_texts("ENRNQ", [1999, 2000], cik="0001024401")


@pytest.mark.network
def test_real_enron_pre2005_risk_factors_unavailable_not_zero(enron):
    texts, filings = enron
    out = run_language({"filing_texts": texts, "analysis_years": [1999, 2000], "filings": filings})
    r = out["language_result"]
    for y in (1999, 2000):
        rf = r["risk_factor_length"][y]
        assert rf["chars"] is None and rf["flag"] is False and "FY2005" in rf["reason"]
        assert f"risk_factor_length.{y}" in r["data_quality"]["unavailable"]
        assert r["hedging_trend"][y]["ratio"] is not None  # MD&A exists in the old .txt
        assert r["passive_voice"][y]["pct"] is not None
        assert r["new_legal_proceedings"][y]["status"] in ("ok", "no_prior_year")
    assert r["hedging_trend"][2000]["yoy_change"] is not None
    assert la.FLAG_RISK not in r["flags_by_year"][2000]
    assert r["focus_year"] == 2000


@pytest.fixture(scope="module")
def luckin():
    return _real_texts("LKNCY", [2019, 2020], cik="0001767582")


@pytest.mark.network
def test_real_luckin_20f(luckin):
    texts, filings = luckin
    out = run_language({"filing_texts": texts, "analysis_years": [2019, 2020], "filings": filings})
    r = out["language_result"]
    assert r["sections"][2020]["mdna_chars"] > 50_000  # 20-F Item 5
    assert r["risk_factor_length"][2019]["chars"] > 150_000 and r["risk_factor_length"][2020]["chars"] > 150_000
    assert r["risk_factor_length"][2020]["yoy_change"] == pytest.approx(
        (r["risk_factor_length"][2020]["chars"] - r["risk_factor_length"][2019]["chars"]) / r["risk_factor_length"][2019]["chars"])
    assert r["new_legal_proceedings"][2020]["status"] == "ok"
    assert r["hedging_trend"][2020]["ratio"] is not None


@pytest.fixture(scope="module")
def nikola():
    return _real_texts("NKLA", [2020, 2021], cik="0001731289")


@pytest.mark.network
def test_real_nikola_fy2020(nikola):
    texts, filings = nikola
    out = run_language({"filing_texts": texts, "analysis_years": [2020, 2021], "filings": filings})
    r = out["language_result"]
    assert r["risk_factor_length"][2020]["chars"] > 50_000
    assert r["hedging_trend"][2020]["ratio"] is not None and r["passive_voice"][2020]["pct"] is not None
    # Nikola's Item 3 only points at the notes: must be reported low-confidence, never as a confident "no new proceedings"
    L21 = r["new_legal_proceedings"][2021]  # v2 (B11): the referenced contingencies note is compared when the parser supplies it
    assert (L21["source"] == "legal_note" and L21["confidence"] == "high") or L21["confidence"] == "low"
    assert r["flags_fired"] == sum(len(v) for v in r["flags_by_year"].values())


def test_legal_excerpt_trims_to_word_boundary():
    from agents.language_agent import _trim_legal_excerpt
    txt = "The Company is a defendant in a lawsuit " + "alleging infringement " * 30
    out = _trim_legal_excerpt(txt, 100)
    assert out.endswith("...") and len(out) <= 100
    assert out[:-3].split(" ")[-1] in ("alleging", "infringement")  # whole word, no fragment
    assert _trim_legal_excerpt("Short paragraph.", 100) == "Short paragraph."


# --------------------------------------------------------------------------------------------------
# v3 L1: identifier-based new_legal (docs/V3_CHANGELOG_lang_eval.md). Reworded boilerplate is NOT a new proceeding.
# --------------------------------------------------------------------------------------------------
SEC_PRIOR = (
    "In the fall of last year the Company received a subpoena from the Securities and Exchange Commission requesting "
    "documents about its revenue recognition practices. The Company is cooperating fully with the SEC staff."
)
SEC_REWORDED = (
    "The SEC staff issued a subpoena to the Company seeking records relating to how it recognises revenue; the "
    "Company continues to cooperate with the Securities and Exchange Commission and has produced documents."
)
DOCKET_PRIOR = (
    "Rivera v. Northwind Logistics, Inc., Case No. 3:17-cv-01234, pending in the United States District Court for the "
    "Northern District of Texas, is a putative class action alleging wage and hour violations. Briefing continues."
)


def test_v3_reworded_known_matters_are_not_new():
    reworded = (
        "The putative securities class action captioned Smith v. Acme Holdings Corp. remains pending before the United "
        "States District Court for the Southern District of New York; the Company disputes the allegations and "
        "expects to continue its defence. A state agency also sent the Company a notice about cleanup of an old plant."
    )
    r = la.compare_legal(LEGAL_A, reworded)
    assert r["detected"] is False, r


def test_v3_ordinary_course_boilerplate_reworded_is_not_new():
    prior = ("From time to time we are involved in litigation arising in the ordinary course of our business. "
             "We do not believe any pending matter will have a material adverse effect on our financial condition.")
    cur = ("In the ordinary course of business, we are a defendant in several legal proceedings arising out of the conduct "
           "of our business, including claims for property damage or personal injury incurred in connection with our "
           "services. Although there can be no assurance as to the ultimate disposition of these proceedings, we do not "
           "believe the outcome will have a material adverse effect on our financial position or results of operations.")
    r = la.compare_legal(prior, cur)
    assert r["detected"] is False, r


def test_v3_sec_subpoena_reworded_not_new_but_first_appearance_is_new():
    assert la.compare_legal(SEC_PRIOR, SEC_REWORDED)["detected"] is False
    r = la.compare_legal(LEGAL_A, LEGAL_A + "\n\n" + SEC_PRIOR)
    assert r["detected"] is True and "agency:sec:subpoena" in r["new_identifiers"], r


def test_v3_new_docket_number_is_new_known_docket_is_not():
    same = DOCKET_PRIOR.replace("Briefing continues.", "The court heard argument on a motion to dismiss.")
    assert la.compare_legal(DOCKET_PRIOR, same)["detected"] is False
    other = ("Alvarez v. Northwind Logistics, Inc., Case No. 4:18-cv-05678, was filed in the United States District Court for "
             "the Southern District of Texas, alleging misclassification of drivers.")
    r = la.compare_legal(DOCKET_PRIOR, DOCKET_PRIOR + "\n\n" + other)
    assert r["detected"] is True and any(i.startswith(("docket:", "caption:")) for i in r["new_identifiers"])


def test_v3_procedural_update_without_identifiers_is_not_new():
    cur = LEGAL_A + ("\n\nOn the plaintiffs' appeal the appellate court consolidated the two appeals for all purposes, and oral "
                     "argument was held before the panel; no decision has been rendered as of the date of this report.")
    assert la.compare_legal(LEGAL_A, cur)["detected"] is False


def test_v3_new_suit_in_unseen_court_is_new_even_without_caption():
    cur = LEGAL_A + ("\n\nA former supplier filed a complaint against the Company in the United States District Court for the "
                     "District of Delaware alleging breach of a long-term purchase agreement and seeking damages.")
    r = la.compare_legal(LEGAL_A, cur)
    assert r["detected"] is True and r["new_units"] == 1
    assert any(i.startswith("court:") for i in r["new_identifiers"])


def test_v3_no_identifier_fallback_is_strict_and_documented():
    assert la.LEGAL_FALLBACK_JACCARD == 0.30 and la.LEGAL_FALLBACK_CONTAIN == 0.70  # fixed a priori, never tuned
    vague = "Management continues to evaluate several unrelated operational and contractual disagreements with counterparties."
    assert la.compare_legal(LEGAL_A, LEGAL_A + "\n\n" + vague)["detected"] is False  # no initiation language => never new
    init = ("A former employee filed a complaint against the Company alleging improper termination following the "
            "restructuring of the warehouse operations, seeking reinstatement and back pay.")
    r = la.compare_legal(LEGAL_A, LEGAL_A + "\n\n" + init)
    assert r["detected"] is True and r["new_identifiers"] == ["text:no-identifier-fallback"]


def test_v3_dates_and_amounts_never_create_identifiers():
    a = "Smith v. Acme Holdings Corp. is a putative class action in which damages of $12 million are sought as of March 3, 2017."
    b = "Smith v. Acme Holdings Corp. is a putative class action in which damages of $45 million are sought as of June 9, 2018."
    assert la.compare_legal(a, b)["detected"] is False


def test_v3_legal_ids_extraction():
    ids = la._legal_ids(DOCKET_PRIOR + " " + SEC_PRIOR)
    assert any("cv01234" in d for d in ids["dockets"])
    assert "sec:subpoena" in ids["agency_matters"]
    assert any("northern district of texas" in c for c in ids["courts"])
    assert any("rivera" in c and "northwind" in c for c in ids["captions"])


# ---- real cached dev text -------------------------------------------------------------------
def _real_legal(ticker: str, years: list[int], cik: str | None = None) -> dict[int, str]:
    texts, filings = _real_texts(ticker, years, cik)
    out = {}
    for f in filings:
        y = f["fiscal_year"]
        s = la.extract_sections(texts[y], f.get("form"))
        info = {"legal": s.get("legal_proceedings") or "", "legal_note": s.get("legal_note") or "", "legal_ibr": False, "error": None}
        out[y] = la._effective_legal(info)[0]
    return out


@pytest.mark.network
def test_v3_real_rrts_ordinary_course_reworded_not_new_but_class_actions_are():
    leg = _real_legal("RRTS", [2014, 2015], cik="0001440024")
    r = la.compare_legal(leg[2014], leg[2015])
    # FY2014 says "no material proceeding"; FY2015 adds five purported California wage class actions: the ONLY new matter.
    assert r["detected"] is True and r["new_units"] == 1 and r["new_identifiers"] == ["matter:class_action"], r
    assert "ordinary course of business, we are a defendant" not in r["text"]


@pytest.mark.network
def test_v3_real_usat_procedural_update_and_mmm_enron_not_new():
    usat = _real_legal("USAT", [2016, 2017], cik="0000896429")
    assert la.compare_legal(usat[2016], usat[2017])["detected"] is False  # "oral argument was held ..." (HOLDOUT_AUDIT_B)
    mmm = _real_legal("MMM", [2019, 2020])
    assert la.compare_legal(mmm[2019], mmm[2020])["detected"] is False
    enron = _real_legal("ENRNQ", [1999, 2000], cik="0001024401")
    assert la.compare_legal(enron[1999], enron[2000])["detected"] is False  # Vidal explosion text reworded, same matter


@pytest.mark.network
def test_v3_real_nikola_new_suits_and_sec_subpoena_identifiers():
    leg = _real_legal("NKLA", [2020, 2021], cik="0001731289")
    ids = la._legal_ids(leg[2020])
    assert ids["dockets"] and ids["captions"]
    assert la.compare_legal(leg[2020], leg[2020])["detected"] is False
    r = la.compare_legal(leg[2020], leg[2021])  # FY2021 adds the Milton arbitration demand and new Delaware dockets
    assert r["detected"] is True and r["new_identifiers"]
    # a prior year with the subpoena sentences removed makes the regulator subpoena a new matter again
    stripped = " ".join(s for s in la._SENT_SPLIT_RE.split(" ".join(leg[2020].split())) if "subpoena" not in s.lower())
    assert la.compare_legal(stripped, leg[2020])["detected"] is True
