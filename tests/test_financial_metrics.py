"""Unit tests for tools.financial_metrics.

Inputs below are SYNTHETIC arithmetic fixtures (round numbers chosen so hand arithmetic is easy), not company
data.  Expected values are recomputed in each test from the raw inputs with the arithmetic written out
independently of the module under test.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tools import financial_metrics as fm

PREV = {"Revenue": 1000.0, "COGS": 600.0, "SGA": 150.0, "NetReceivables": 100.0, "CurrentAssets": 400.0,
        "PPE": 300.0, "TotalAssets": 1000.0, "Depreciation": 30.0, "LongTermDebt": 200.0,
        "CurrentLiabilities": 150.0, "NetIncome": 80.0, "OperatingCashFlow": 90.0}
CUR = {"Revenue": 1200.0, "COGS": 760.0, "SGA": 200.0, "NetReceivables": 180.0, "CurrentAssets": 450.0,
       "PPE": 350.0, "TotalAssets": 1200.0, "Depreciation": 30.0, "LongTermDebt": 260.0,
       "CurrentLiabilities": 190.0, "NetIncome": 100.0, "OperatingCashFlow": 70.0}

# hand arithmetic from the raw inputs above
DSRI = (180 / 1200) / (100 / 1000)                       # 0.15 / 0.10 = 1.5
GMI = ((1000 - 600) / 1000) / ((1200 - 760) / 1200)      # 0.4 / 0.366667 = 1.090909
AQI = (1 - (450 + 350) / 1200) / (1 - (400 + 300) / 1000)  # 0.333333 / 0.3 = 1.111111
SGI = 1200 / 1000                                        # 1.2
DEPI = (30 / (300 + 30)) / (30 / (350 + 30))             # 0.090909 / 0.078947 = 1.151515
SGAI = (200 / 1200) / (150 / 1000)                       # 0.166667 / 0.15 = 1.111111
LVGI = ((260 + 190) / 1200) / ((200 + 150) / 1000)       # 0.375 / 0.35 = 1.071429
TATA = (100 - 70) / 1200                                 # 0.025


def test_literal_hand_values():
    assert DSRI == pytest.approx(1.5)
    assert GMI == pytest.approx(12 / 11)
    assert AQI == pytest.approx(10 / 9)
    assert DEPI == pytest.approx(380 / 330)
    assert LVGI == pytest.approx(0.375 / 0.35)


def test_each_beneish_component():
    r = fm.beneish_m_score(CUR, PREV)
    assert r["status"] == "ok" and r["imputed"] == []
    c = r["components"]
    assert c["DSRI"] == pytest.approx(DSRI)
    assert c["GMI"] == pytest.approx(GMI)
    assert c["AQI"] == pytest.approx(AQI)
    assert c["SGI"] == pytest.approx(SGI)
    assert c["DEPI"] == pytest.approx(DEPI)
    assert c["SGAI"] == pytest.approx(SGAI)
    assert c["LVGI"] == pytest.approx(LVGI)
    assert c["TATA"] == pytest.approx(TATA)


def test_beneish_m_total_and_zone():
    expected = (-4.84 + 0.920 * DSRI + 0.528 * GMI + 0.404 * AQI + 0.892 * SGI + 0.115 * DEPI
                - 0.172 * SGAI + 4.679 * TATA - 0.327 * LVGI)
    r = fm.beneish_m_score(CUR, PREV)
    assert r["m_score"] == pytest.approx(expected, abs=1e-9)
    assert r["zone"] == "manipulator" and r["flag_level"] == "HIGH" and r["flag"] is True
    assert expected > -1.78


def test_gross_profit_derives_cogs():
    cur = {k: v for k, v in CUR.items() if k != "COGS"} | {"GrossProfit": 440.0}
    prev = {k: v for k, v in PREV.items() if k != "COGS"} | {"GrossProfit": 400.0}
    assert fm.beneish_m_score(cur, prev)["components"]["GMI"] == pytest.approx(GMI)


def test_tata_sign_higher_accruals_raise_m():
    base = fm.beneish_m_score(CUR, PREV)["m_score"]
    hi = dict(CUR, OperatingCashFlow=CUR["OperatingCashFlow"] - 100)   # NI - OCF larger
    lo = dict(CUR, OperatingCashFlow=CUR["OperatingCashFlow"] + 100)
    m_hi = fm.beneish_m_score(hi, PREV)["m_score"]
    m_lo = fm.beneish_m_score(lo, PREV)["m_score"]
    assert m_hi > base > m_lo
    # exactly 4.679 * 100/1200 per 100 of OCF
    assert m_hi - base == pytest.approx(4.679 * 100 / 1200)
    # NI > OCF -> positive TATA
    assert fm.beneish_m_score(CUR, PREV)["components"]["TATA"] > 0


def test_beneish_sample_means_sanity():
    non = fm.BENEISH_SAMPLE_MEANS["non_manipulators"]
    man = fm.BENEISH_SAMPLE_MEANS["manipulators"]
    m_non = fm.beneish_m_from_components(non)
    m_man = fm.beneish_m_from_components(man)
    # hand arithmetic for non-manipulator means
    exp_non = (-4.84 + 0.920 * 1.031 + 0.528 * 1.014 + 0.404 * 1.039 + 0.892 * 1.134 + 0.115 * 1.001
               - 0.172 * 1.054 + 4.679 * 0.018 - 0.327 * 1.037)
    exp_man = (-4.84 + 0.920 * 1.465 + 0.528 * 1.193 + 0.404 * 1.254 + 0.892 * 1.607 + 0.115 * 1.077
               - 0.172 * 1.041 + 4.679 * 0.031 - 0.327 * 1.111)
    assert m_non == pytest.approx(exp_non) and m_man == pytest.approx(exp_man)
    assert -2.30 < m_non < -2.20          # about -2.25: non-manipulator mean vector
    assert -1.25 < m_man < -1.15          # about -1.20: manipulator mean vector
    assert fm.classify_beneish(m_non)["zone"] == "unlikely"   # -2.246 < -2.22
    assert fm.classify_beneish(m_man)["zone"] == "manipulator"


def test_beneish_boundaries():
    assert fm.classify_beneish(-1.78)["zone"] == "grey"
    assert fm.classify_beneish(-1.7799)["zone"] == "manipulator"
    assert fm.classify_beneish(-1.7801)["zone"] == "grey"
    assert fm.classify_beneish(-2.22)["zone"] == "grey"
    assert fm.classify_beneish(-2.2201)["zone"] == "unlikely"
    assert fm.classify_beneish(-2.2199)["flag_level"] == "MEDIUM"
    assert fm.classify_beneish(-3.0) == {"zone": "unlikely", "flag_level": "LOW", "flag": False}


def test_beneish_boundary_via_full_function():
    """Shift TATA so M lands just above/below -1.78 using the exact coefficient (4.679)."""
    base = fm.beneish_m_score(CUR, PREV)
    m0 = base["m_score"]
    ta = CUR["TotalAssets"]
    for target, zone in ((-1.7799, "manipulator"), (-1.7801, "grey")):
        d_accr = (target - m0) / 4.679 * ta  # change in (NI - OCF)
        cur = dict(CUR, OperatingCashFlow=CUR["OperatingCashFlow"] - d_accr)
        r = fm.beneish_m_score(cur, PREV)
        assert r["m_score"] == pytest.approx(target, abs=1e-9)
        assert r["zone"] == zone


def test_imputation_only_sgai_depi():
    cur = {k: v for k, v in CUR.items() if k != "SGA"}
    r = fm.beneish_m_score(cur, PREV)
    assert r["status"] == "ok" and r["imputed"] == ["SGAI"] and r["components"]["SGAI"] == 1.0
    assert "SGA" in r["missing"] and "SGA" in r["missing_xbrl_hints"]
    expected = (-4.84 + 0.920 * DSRI + 0.528 * GMI + 0.404 * AQI + 0.892 * SGI + 0.115 * DEPI
                - 0.172 * 1.0 + 4.679 * TATA - 0.327 * LVGI)
    assert r["m_score"] == pytest.approx(expected)
    # DEPI imputed when depreciation missing in the prior year
    prev = {k: v for k, v in PREV.items() if k != "Depreciation"}
    r2 = fm.beneish_m_score(CUR, prev)
    assert r2["imputed"] == ["DEPI"] and r2["components"]["DEPI"] == 1.0
    # both
    r3 = fm.beneish_m_score({k: v for k, v in cur.items() if k != "Depreciation"}, PREV)
    assert sorted(r3["imputed"]) == ["DEPI", "SGAI"]
    # imputation disabled -> unavailable
    r4 = fm.beneish_m_score(cur, PREV, impute_neutral=())
    assert r4["status"] == "unavailable" and r4["m_score"] is None and r4["imputed"] == []


@pytest.mark.parametrize("key", ["NetReceivables", "Revenue", "TotalAssets", "NetIncome", "OperatingCashFlow",
                                 "CurrentAssets", "PPE", "LongTermDebt", "CurrentLiabilities"])
def test_non_imputable_missing_is_unavailable(key):
    cur = dict(CUR)
    cur[key] = None
    r = fm.beneish_m_score(cur, PREV)
    assert r["status"] == "unavailable" and r["m_score"] is None and r["zone"] is None
    assert key in r["missing"]
    assert key in r["explanation"]
    assert "XBRL" in r["explanation"]


def test_cogs_missing_unavailable():
    cur = {k: v for k, v in CUR.items() if k != "COGS"}
    r = fm.beneish_m_score(cur, PREV)
    assert r["status"] == "unavailable" and "COGS" in r["missing"]
    assert "CostOfRevenue" in r["explanation"]


def test_zero_denominators_and_degenerate_inputs():
    # zero prior receivables -> DSRI undefined -> unavailable (not imputable), no exception
    r = fm.beneish_m_score(CUR, dict(PREV, NetReceivables=0.0))
    assert r["status"] == "unavailable" and "DSRI" in r["undefined"]
    # zero revenue
    r = fm.beneish_m_score(dict(CUR, Revenue=0.0), PREV)
    assert r["status"] == "unavailable"
    # zero current depreciation -> DEPI undefined -> neutral imputation, reported
    r = fm.beneish_m_score(dict(CUR, Depreciation=0.0), PREV)
    assert r["status"] == "ok" and r["imputed"] == ["DEPI"]
    # empty / None inputs
    for a, b in (({}, {}), (None, None), (CUR, None), (None, PREV)):
        assert fm.beneish_m_score(a, b)["status"] == "unavailable"


def test_factvalue_dict_inputs_accepted():
    cur = {k: {"value": v, "tag": "x"} for k, v in CUR.items()}
    assert fm.beneish_m_score(cur, PREV)["m_score"] == pytest.approx(fm.beneish_m_score(CUR, PREV)["m_score"])


def test_explanation_facts():
    r = fm.beneish_m_score(CUR, PREV)
    f = fm.beneish_explanation_facts(r["components"], CUR, PREV)
    assert f["revenue_growth_pct"] == pytest.approx((1200 / 1000 - 1) * 100)
    assert f["receivables_growth_pct"] == pytest.approx((180 / 100 - 1) * 100)
    assert f["gross_margin_cur"] == pytest.approx((1200 - 760) / 1200)
    assert f["gross_margin_prev"] == pytest.approx((1000 - 600) / 1000)
    assert f["gross_margin_change_pp"] == pytest.approx(((1200 - 760) / 1200 - (1000 - 600) / 1000) * 100)
    assert f["accrual_amount"] == pytest.approx(30.0)
    assert f["accrual_to_assets"] == pytest.approx(0.025)
    assert f["accrual_pct_of_net_income"] == pytest.approx(30.0)
    assert f["asset_quality_cur"] == pytest.approx(1 - 800 / 1200)
    assert f["top_drivers"][0] == "DSRI"  # 0.920 * 0.5 = 0.46 is the largest push above neutral
    assert f["contributions"]["TATA"] == pytest.approx(4.679 * 0.025)
    # missing data never raises
    g = fm.beneish_explanation_facts({}, {}, {})
    assert g["revenue_growth_pct"] is None and g["top_drivers"] == []


# ------------------------------------------------------------------------------------------ Altman
AL = {"CurrentAssets": 500.0, "CurrentLiabilities": 300.0, "TotalAssets": 1000.0, "RetainedEarnings": 250.0,
      "OperatingIncome": 120.0, "Revenue": 900.0, "TotalLiabilities": 600.0, "StockholdersEquity": 400.0}


def test_altman_z_original_with_market_cap():
    x1, x2, x3, x4, x5 = (500 - 300) / 1000, 250 / 1000, 120 / 1000, 800 / 600, 900 / 1000
    exp = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5   # 0.24+0.35+0.396+0.8+0.9 = 2.686
    r = fm.altman_z(AL, market_cap=800.0)
    assert r["status"] == "ok" and r["variant"] == "Z"
    assert r["score"] == pytest.approx(exp) and exp == pytest.approx(2.686)
    assert r["zone"] == "grey"
    assert r["components"]["X4"] == pytest.approx(800 / 600)


def test_altman_zprime_fallback_without_market_cap():
    x1, x2, x3, x4, x5 = 0.2, 0.25, 0.12, 400 / 600, 0.9
    exp = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
    for mc in (None, 0.0, -5.0, float("nan")):
        r = fm.altman_z(AL, market_cap=mc)
        assert r["variant"] == "Z-prime" and r["score"] == pytest.approx(exp)
    assert "Z'" in fm.altman_z(AL)["explanation"]


def test_altman_zdoubleprime():
    exp = 6.56 * 0.2 + 3.26 * 0.25 + 6.72 * 0.12 + 1.05 * (400 / 600)
    r = fm.altman_z_double_prime(AL)
    assert r["score"] == pytest.approx(exp) and r["variant"] == "Z-double-prime"
    assert r["zone"] == "safe"  # exp = 3.5 approx > 2.6


def test_altman_derived_items_and_ebit_fallback():
    d = {k: v for k, v in AL.items() if k not in ("TotalLiabilities", "OperatingIncome")}
    d.update(NetIncome=70.0, IncomeTaxExpense=30.0, InterestExpense=20.0)
    r = fm.altman_z(d)
    assert r["status"] == "ok"
    assert r["components"]["X3"] == pytest.approx(120 / 1000)       # 70+30+20
    assert r["components"]["X4"] == pytest.approx(400 / (1000 - 400))
    assert len(r["derived"]) == 2
    assert fm.altman_z(AL)["score"] == pytest.approx(r["score"])


def test_altman_boundaries():
    for variant, lo, hi in (("Z", 1.81, 2.99), ("Z-prime", 1.23, 2.90), ("Z-double-prime", 1.10, 2.60)):
        assert fm.classify_altman(lo, variant) == "grey"
        assert fm.classify_altman(lo - 1e-6, variant) == "distress"
        assert fm.classify_altman(hi, variant) == "grey"
        assert fm.classify_altman(hi + 1e-6, variant) == "safe"


def test_altman_boundary_end_to_end():
    """Tune RetainedEarnings so Z' hits just below/above 1.23 using the exact X2 coefficient."""
    base = fm.altman_z(AL)["score"]
    for target, zone in ((1.2299, "distress"), (1.2301, "grey")):
        re_ = AL["RetainedEarnings"] + (target - base) / 0.847 * AL["TotalAssets"]
        r = fm.altman_z(dict(AL, RetainedEarnings=re_))
        assert r["score"] == pytest.approx(target, abs=1e-9) and r["zone"] == zone


def test_altman_missing_and_zero():
    r = fm.altman_z({k: v for k, v in AL.items() if k != "RetainedEarnings"})
    assert r["status"] == "unavailable" and "RetainedEarnings" in r["missing"] and r["score"] is None
    r = fm.altman_z(dict(AL, TotalAssets=0.0))
    assert r["status"] == "unavailable"
    r = fm.altman_z(dict(AL, TotalLiabilities=0.0))
    assert r["status"] == "unavailable"
    r = fm.altman_z({k: v for k, v in AL.items() if k not in ("StockholdersEquity", "TotalLiabilities")})
    assert r["status"] == "unavailable" and {"TotalLiabilities", "StockholdersEquity"} <= set(r["missing"])
    # original Z does not need equity when TL is present
    r = fm.altman_z({k: v for k, v in AL.items() if k != "StockholdersEquity"}, market_cap=100.0)
    assert r["status"] == "ok"
    assert fm.altman_z({})["status"] == "unavailable"


def test_altman_negative_values_ok():
    r = fm.altman_z(dict(AL, RetainedEarnings=-400.0, OperatingIncome=-50.0, StockholdersEquity=-100.0))
    assert r["status"] == "ok" and r["zone"] == "distress"


# ---------------------------------------------------------------------------------- earnings quality
def test_revenue_quality_two_consecutive_years():
    cur = {"OperatingCashFlow": 60.0, "NetIncome": 100.0}   # 0.6
    prev = {"OperatingCashFlow": 70.0, "NetIncome": 100.0}  # 0.7
    r = fm.revenue_quality(cur, prev)
    assert r["status"] == "ok" and r["ratio"] == pytest.approx(0.6) and r["prior_ratio"] == pytest.approx(0.7)
    assert r["consecutive_low"] is True and r["flag"] is True and r["flag_evaluable"] is True
    # prior year fine -> no flag
    r = fm.revenue_quality(cur, {"OperatingCashFlow": 95.0, "NetIncome": 100.0})
    assert r["flag"] is False and r["consecutive_low"] is False
    # exactly 0.8 is not low
    r = fm.revenue_quality({"OperatingCashFlow": 80.0, "NetIncome": 100.0}, prev)
    assert r["low"] is False and r["flag"] is False
    # prior missing -> ratio reported, flag not evaluable
    r = fm.revenue_quality(cur, None)
    assert r["status"] == "ok" and r["flag"] is False and r["flag_evaluable"] is False and r["consecutive_low"] is None
    r = fm.revenue_quality(cur, {"OperatingCashFlow": 5.0, "NetIncome": -10.0})
    assert r["flag_evaluable"] is False and r["flag"] is False


def test_revenue_quality_not_meaningful_and_missing():
    r = fm.revenue_quality({"OperatingCashFlow": 10.0, "NetIncome": -5.0}, PREV)
    assert r["status"] == "not_meaningful" and r["flag"] is False and r["ratio"] is None
    assert fm.revenue_quality({"OperatingCashFlow": 10.0, "NetIncome": 0.0}, PREV)["status"] == "not_meaningful"
    r = fm.revenue_quality({"NetIncome": 5.0}, PREV)
    assert r["status"] == "unavailable" and r["missing"] == ["OperatingCashFlow"]


def test_dso():
    r = fm.dso(CUR, PREV)
    d_c, d_p = 180 / 1200 * 365, 100 / 1000 * 365
    assert r["dso_days"] == pytest.approx(d_c) and r["prior_dso_days"] == pytest.approx(d_p)
    assert r["yoy_change_pct"] == pytest.approx((d_c / d_p - 1) * 100)   # +50%
    assert r["flag"] is True
    # +20% exactly: not flagged (strictly greater)
    r = fm.dso({"NetReceivables": 120.0, "Revenue": 1000.0}, {"NetReceivables": 100.0, "Revenue": 1000.0})
    assert r["yoy_change_pct"] == pytest.approx(20.0) and r["flag"] is False
    r = fm.dso({"NetReceivables": 121.0, "Revenue": 1000.0}, {"NetReceivables": 100.0, "Revenue": 1000.0})
    assert r["flag"] is True
    r = fm.dso(CUR, None)
    assert r["status"] == "ok" and r["yoy_change_pct"] is None and r["flag"] is False
    assert fm.dso({"Revenue": 0.0, "NetReceivables": 5.0}, PREV)["status"] == "unavailable"
    assert fm.dso({"Revenue": 5.0}, PREV)["missing"] == ["NetReceivables"]
    # zero prior DSO -> yoy undefined, no crash
    assert fm.dso(CUR, dict(PREV, NetReceivables=0.0))["yoy_change_pct"] is None


def test_accruals_ratio():
    r = fm.accruals_ratio(CUR)
    assert r["ratio"] == pytest.approx((100 - 70) / 1200) and r["flag"] is False
    r = fm.accruals_ratio({"NetIncome": 160.0, "OperatingCashFlow": 100.0, "TotalAssets": 1000.0})
    assert r["ratio"] == pytest.approx(0.06) and r["flag"] is True
    r = fm.accruals_ratio({"NetIncome": 150.0, "OperatingCashFlow": 100.0, "TotalAssets": 1000.0})
    assert r["flag"] is False  # exactly 0.05
    assert fm.accruals_ratio({"NetIncome": 1.0})["status"] == "unavailable"
    assert fm.accruals_ratio({"NetIncome": 1.0, "OperatingCashFlow": 1.0, "TotalAssets": 0.0})["status"] == "unavailable"
    # negative accruals (cash > income) never flag
    assert fm.accruals_ratio({"NetIncome": 10.0, "OperatingCashFlow": 90.0, "TotalAssets": 100.0})["flag"] is False


def test_peer_ratios():
    assert fm.gross_margin(CUR)["value"] == pytest.approx((1200 - 760) / 1200)
    assert fm.gross_margin({"Revenue": 100.0, "GrossProfit": 30.0})["value"] == pytest.approx(0.3)
    assert fm.gross_margin({"Revenue": 100.0})["missing"] == ["COGS"]
    assert fm.gross_margin({"Revenue": 0.0, "COGS": 1.0})["status"] == "unavailable"
    assert fm.ocf_to_revenue(CUR)["value"] == pytest.approx(70 / 1200)
    assert fm.ocf_to_revenue({"OperatingCashFlow": 5.0})["status"] == "unavailable"
    d = {"LongTermDebt": 200.0, "CurrentDebt": 50.0, "StockholdersEquity": 500.0}
    r = fm.debt_to_equity(d)
    assert r["value"] == pytest.approx((200 + 50) / 500) and r["partial"] is False
    r = fm.debt_to_equity({"LongTermDebt": 200.0, "StockholdersEquity": 500.0})
    assert r["status"] == "ok" and r["partial"] is True and r["missing"] == ["CurrentDebt"]
    assert r["value"] == pytest.approx(0.4)
    assert fm.debt_to_equity({"LongTermDebt": 1.0, "StockholdersEquity": -5.0})["status"] == "not_meaningful"
    assert fm.debt_to_equity({"StockholdersEquity": 5.0})["status"] == "unavailable"
    assert fm.roa(CUR)["value"] == pytest.approx(100 / 1200)
    assert fm.roa({"NetIncome": -5.0, "TotalAssets": 50.0})["value"] == pytest.approx(-0.1)
    assert fm.roa({"NetIncome": 1.0, "TotalAssets": 0.0})["status"] == "unavailable"


def test_receivables_vs_revenue_growth():
    r = fm.receivables_vs_revenue_growth(CUR, PREV)
    rg, ag = 1200 / 1000 - 1, 180 / 100 - 1
    assert r["revenue_growth"] == pytest.approx(rg) and r["receivables_growth"] == pytest.approx(ag)
    assert r["difference"] == pytest.approx(ag - rg)             # 0.8 - 0.2 = 0.6
    assert r["ratio"] == pytest.approx((1 + ag) / (1 + rg))
    assert r["ratio"] == pytest.approx(DSRI)  # identical to DSRI
    assert fm.receivables_vs_revenue_growth(CUR, dict(PREV, NetReceivables=0.0))["status"] == "unavailable"
    assert fm.receivables_vs_revenue_growth(CUR, {})["missing"] == ["NetReceivables", "Revenue"]


# ------------------------------------------------------------------------------------ no NaN / inf
def _all_results(cur, prev):
    return [
        fm.beneish_m_score(cur, prev), fm.beneish_m_score(cur, prev, impute_neutral=()),
        fm.altman_z(cur), fm.altman_z(cur, market_cap=cur.get("Revenue") if isinstance(cur, dict) else None),
        fm.altman_z_double_prime(cur), fm.revenue_quality(cur, prev), fm.dso(cur, prev), fm.accruals_ratio(cur),
        fm.gross_margin(cur), fm.ocf_to_revenue(cur), fm.debt_to_equity(cur), fm.roa(cur),
        fm.receivables_vs_revenue_growth(cur, prev),
    ]


def test_no_nan_inf_random_inputs():
    rng = np.random.default_rng(20260421)
    keys = sorted(set(fm.CANONICAL_TO_XBRL_HINT))
    specials = [None, 0.0, -0.0, float("nan"), float("inf"), -float("inf"), 1e308, -1e308, 1e-308, "abc", True]

    def rand_year():
        d = {}
        for k in keys:
            u = rng.random()
            if u < 0.15:
                continue
            if u < 0.30:
                d[k] = specials[int(rng.integers(len(specials)))]
            else:
                d[k] = float(rng.normal(0, 1) * 10.0 ** int(rng.integers(-2, 9)))
        return d

    statuses = set()
    for _ in range(1500):
        cur, prev = rand_year(), rand_year()
        for res in _all_results(cur, prev):
            assert res["status"] in ("ok", "unavailable", "not_meaningful")
            assert isinstance(res["missing"], list) and isinstance(res["explanation"], str) and res["explanation"]
            json.dumps(res, allow_nan=False)      # raises on NaN/inf
            statuses.add(res["status"])
        json.dumps(fm.beneish_explanation_facts(fm.beneish_m_score(cur, prev)["components"], cur, prev),
                   allow_nan=False)
    assert "ok" in statuses and "unavailable" in statuses


def test_no_nan_with_well_formed_random_inputs_gives_ok_often():
    rng = np.random.default_rng(7)
    ok = 0
    for _ in range(300):
        def year():
            rev = float(rng.uniform(100, 5000))
            ta = float(rng.uniform(200, 8000))
            return {"Revenue": rev, "COGS": rev * float(rng.uniform(0.3, 0.9)), "SGA": rev * float(rng.uniform(0.05, 0.3)),
                    "NetReceivables": rev * float(rng.uniform(0.05, 0.3)), "CurrentAssets": ta * float(rng.uniform(0.2, 0.5)),
                    "PPE": ta * float(rng.uniform(0.1, 0.4)), "TotalAssets": ta, "Depreciation": ta * float(rng.uniform(0.01, 0.05)),
                    "LongTermDebt": ta * float(rng.uniform(0, 0.4)), "CurrentLiabilities": ta * float(rng.uniform(0.05, 0.3)),
                    "NetIncome": rev * float(rng.uniform(-0.05, 0.2)), "OperatingCashFlow": rev * float(rng.uniform(-0.05, 0.25))}
        r = fm.beneish_m_score(year(), year())
        if r["status"] == "ok":
            ok += 1
            assert math.isfinite(r["m_score"])
            json.dumps(r, allow_nan=False)
    assert ok >= 290
