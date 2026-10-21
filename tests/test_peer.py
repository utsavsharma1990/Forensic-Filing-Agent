"""Tests for tools.peer_finder and agents.peer_agent.

Live tests (``network`` marker) use real SEC data through the cached EdgarClient. Offline tests use SYNTHETIC,
structure-only numbers (hand-computed expectations are derived in the test body, not copied from any company).
"""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents import peer_agent as pa  # noqa: E402
from tools import edgar_api, peer_finder as pf, xbrl_parser  # noqa: E402
from tools import financial_metrics as fm  # noqa: E402

AAPL, MSFT, ENRON, LUCKIN = "0000320193", "0000789019", "0001024401", "0001767582"
AAPL_ASOF, MSFT_ASOF = "2020-10-30", "2020-08-01"


@pytest.fixture(scope="module")
def aapl_peers():
    edgar_api.set_client(None)
    r = pf.find_peers(AAPL, as_of=AAPL_ASOF, focus_year=2020)
    edgar_api.set_client(None)
    return r


@pytest.fixture(scope="module")
def msft_peers():
    edgar_api.set_client(None)
    r = pf.find_peers(MSFT, as_of=MSFT_ASOF, focus_year=2020)
    edgar_api.set_client(None)
    return r


# ----------------------------------------------------------------------------- peer_finder: live
@pytest.mark.network
def test_aapl_peers_live(aapl_peers):
    assert len(aapl_peers) >= 3, aapl_peers.reason
    ciks = [p["cik"] for p in aapl_peers]
    assert AAPL not in ciks and len(set(ciks)) == len(ciks)
    for p in aapl_peers:
        assert set(p) >= {"ticker", "name", "cik", "sic", "assets"}
        assert p["sic"].startswith("35") or p["tier"] == 2 or p["sic"][:2] == "35", p
        assert p["filing_date"] <= AAPL_ASOF
        assert p["fiscal_year"] in (2019, 2020)
        assert 0.1 / 5 <= p["assets"] / 323_888_000_000 <= 10 * 5
    # ordering contract: tier descending quality (4 then 3 then 2), then closest log-assets
    keys = [(-p["tier"], abs(math.log(p["assets_ratio"])), p["cik"]) for p in aapl_peers]
    assert keys == sorted(keys)


@pytest.mark.network
def test_msft_peers_live(msft_peers):
    assert len(msft_peers) >= 3, msft_peers.reason
    assert MSFT not in [p["cik"] for p in msft_peers]
    for p in msft_peers:
        assert p["filing_date"] <= MSFT_ASOF
        assert p["fiscal_year"] in (2019, 2020)  # Dec-FYE peers have no FY2020 10-K by 2020-08-01 -> prior year


@pytest.mark.network
def test_determinism_and_no_http_second_time(aapl_peers):
    c = edgar_api.get_client()
    before = c.http_calls
    again = pf.find_peers(AAPL, as_of=AAPL_ASOF, focus_year=2020)
    assert list(again) == list(aapl_peers)
    assert c.http_calls == before, "second call must be served from cache"
    # even bypassing the result cache the recomputation uses only the EDGAR disk cache
    before = c.http_calls
    third = pf.find_peers(AAPL, as_of=AAPL_ASOF, focus_year=2020, use_cache=False)
    assert [p["cik"] for p in third] == [p["cik"] for p in aapl_peers]
    assert c.http_calls == before


@pytest.mark.network
def test_no_look_ahead_earlier_as_of():
    early, late = "2019-12-31", AAPL_ASOF
    p_early = pf.find_peers(AAPL, as_of=early, focus_year=2019)
    p_late = pf.find_peers(AAPL, as_of=late, focus_year=2019)
    assert len(p_early) >= 3, p_early.reason
    for p in p_early:
        assert p["filing_date"] <= early, p
        # facts used must have been filed by the early as_of too
        af = xbrl_parser.extract_annual_facts(edgar_api.get_companyfacts(p["cik"]), [p["fiscal_year"]], as_of=early)
        filed = [fv["filed"] for fv in af["by_year"][p["fiscal_year"]].values() if fv.get("filed")]
        assert filed and max(filed) <= early
    # peers whose FY2019 10-K was filed after the early as_of must not show a FY2019 filing in the early set
    for p in p_early:
        if p["fiscal_year"] == 2019:
            assert p["filing_date"] <= early
    late_new = [p for p in p_late if p["fiscal_year"] == 2019 and p["filing_date"] > early]
    early_ciks = {p["cik"]: p for p in p_early}
    for p in late_new:  # filed only after `early`: if present in the early set it must be a prior-year row
        if p["cik"] in early_ciks:
            assert early_ciks[p["cik"]]["fiscal_year"] == 2018


def test_pre_xbrl_enron_returns_empty_with_reason():
    r = pf.find_peers(ENRON, focus_year=2000)
    assert list(r) == [] and isinstance(r, list)
    assert "pre-XBRL" in r.reason


@pytest.mark.network
def test_pre_xbrl_enron_auto_focus_year():
    r = pf.find_peers(ENRON, as_of="2001-06-01")
    assert list(r) == []
    assert r.reason and "pre-XBRL" in r.reason


@pytest.mark.network
def test_non_usd_luckin_returns_empty_with_unit_reason():
    r = pf.find_peers(LUCKIN, as_of="2021-12-31", focus_year=2019)
    assert list(r) == []
    assert "CNY" in r.reason and "ratios" in r.reason


def test_find_peers_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(pf, "_find", boom)
    r = pf.find_peers("0000000001", focus_year=2020, use_cache=False)
    assert list(r) == [] and "error" in r.reason


def test_quarter_ends():
    assert pf._quarter_ends(2020, 6) == [(2020, 2), (2020, 1), (2019, 4), (2019, 3)]
    assert pf._quarter_ends(2019, 9)[0] == (2019, 3)


# ----------------------------------------------------------------------------- peer_agent: statistics (synthetic)
def test_zscore_hand_computed():
    z = pa.zscore(7.0, [1, 2, 3, 4, 5])  # mean 3, sample std sqrt(2.5)
    assert z["peer_mean"] == 3 and z["peer_std"] == pytest.approx(math.sqrt(2.5))
    assert z["z_score"] == pytest.approx(4 / math.sqrt(2.5)) and z["z_score"] == pytest.approx(2.5298, abs=1e-4)
    assert pa.zscore(1.0, [1, 2, 3, 4, 5])["z_score"] == pytest.approx(-2 / math.sqrt(2.5))


def _peers_for(metric, values):
    return [{m: (values[i] if m == metric else 0.5) for m in pa.METRICS} for i in range(len(values))]


def test_threshold_is_strictly_greater_than_two():
    peers = _peers_for("roa", [0.0, 2.0, 4.0])  # mean 2, std 2
    zs, _ = pa.compare({**{m: 0.5 for m in pa.METRICS}, "roa": 6.0}, peers)
    assert zs["roa"]["z_score"] == pytest.approx(2.0) and zs["roa"]["flag"] is False
    zs, _ = pa.compare({**{m: 0.5 for m in pa.METRICS}, "roa": 6.01}, peers)
    assert zs["roa"]["flag"] is True and zs["roa"]["direction"] == "above"
    zs, _ = pa.compare({**{m: 0.5 for m in pa.METRICS}, "roa": -2.01}, peers)
    assert zs["roa"]["flag"] is True and zs["roa"]["direction"] == "below"


def test_zero_std_handled():
    peers = _peers_for("dso", [40.0, 40.0, 40.0])
    base = {m: 0.5 for m in pa.METRICS}
    zs, _ = pa.compare({**base, "dso": 40.0}, peers)
    assert zs["dso"]["z_score"] == 0.0 and zs["dso"]["flag"] is False
    zs, _ = pa.compare({**base, "dso": 61.0}, peers)
    assert zs["dso"]["z_score"] is None and zs["dso"]["flag"] is False
    assert "std=0" in zs["dso"]["interpretation"]


def test_metric_needs_three_peers():
    peers = _peers_for("roa", [0.1, 0.2, 0.3])
    peers[2]["roa"] = None  # only 2 usable
    zs, un = pa.compare({m: 0.5 for m in pa.METRICS}, peers)
    assert "roa" not in zs and "only 2 peers" in un["roa"]


def test_interpretation_text_format():
    zi = pa.zscore(61.0, [30.0, 38.0, 46.0])  # mean 38 std 8 -> z=2.875
    txt = pa.interpret("dso", 61.0, zi)
    assert txt.startswith("DSO 61 days vs peer mean 38 days (z=+2.9)")
    assert "above" in txt


# ----------------------------------------------------------------------------- peer_agent: flow with fake facts
def _fv(v):
    return {"value": float(v), "tag": "synthetic", "unit": "USD"}


def _facts(rev, cogs, ar, ocf, debt, eq, ni, ta, ar_prev, rev_prev):
    def year(r, a):
        return {"Revenue": _fv(r), "COGS": _fv(cogs * r / rev), "NetReceivables": _fv(a), "OperatingCashFlow": _fv(ocf * r / rev),
                "LongTermDebt": _fv(debt), "CurrentDebt": _fv(0), "StockholdersEquity": _fv(eq), "NetIncome": _fv(ni * r / rev),
                "TotalAssets": _fv(ta)}
    return {"by_year": {2019: year(rev_prev, ar_prev), 2020: year(rev, ar)}, "unit": "USD"}


def _peer(i):
    return {"ticker": f"P{i}", "name": f"Peer {i}", "cik": f"{1000 + i:010d}", "fiscal_year": 2020, "tier": 4, "year_offset": 0}


def _fake_env(monkeypatch, peer_facts, company_facts=None, fail=()):
    def facts_for(cik, years, as_of):
        if cik in fail:
            raise RuntimeError("fetch failed")
        return company_facts if cik == "0000000001" and company_facts else peer_facts[cik]
    monkeypatch.setattr(pa, "_facts_for", facts_for)


def test_agent_three_outliers_is_high_and_hand_z(monkeypatch):
    peers = [_peer(i) for i in range(5)]
    # peers vary slightly in each ratio; company: very high DSO, margin, ROA relative to them
    pf_ = {}
    for i, p in enumerate(peers):
        pf_[p["cik"]] = _facts(rev=1000, cogs=600 + 10 * i, ar=100 + 5 * i, ocf=150 + 5 * i, debt=200, eq=400 + 10 * i,
                               ni=80 + 4 * i, ta=1000, ar_prev=95 + 5 * i, rev_prev=950)
    company = _facts(rev=1000, cogs=300, ar=400, ocf=150, debt=200, eq=400, ni=300, ta=1000, ar_prev=95, rev_prev=950)
    _fake_env(monkeypatch, pf_, company)
    state = {"cik": "0000000001", "focus_year": 2020, "analysis_years": [2019, 2020], "as_of": "2021-01-01",
             "peer_companies": peers}
    out = pa.run_peer(state)
    r = out["peer_result"]
    assert not r.get("unavailable"), r
    # hand-computed DSO z
    peer_dso = [(100 + 5 * i) / 1000 * 365 for i in range(5)]
    exp_z = (400 / 1000 * 365 - statistics.mean(peer_dso)) / statistics.stdev(peer_dso)
    assert r["metric_zscores"]["dso"]["z_score"] == pytest.approx(exp_z, abs=1e-3)
    assert {"dso", "gross_margin", "roa"} <= set(r["outlier_metrics"])
    assert r["severity"] == "High" and r["flags_fired"] == len(r["outlier_metrics"]) >= 3
    assert set(r["flags_by_year"]) == {2020} and "peer.dso" in r["flags_by_year"][2020]
    ev = {e["metric"]: e for e in r["evidence"]}
    assert ev["dso"]["flag"] == "peer.dso" and ev["dso"]["year"] == 2020
    assert ev["dso"]["peer_pct"] == pytest.approx((146 - statistics.mean(peer_dso)) / statistics.mean(peer_dso) * 100, abs=0.1)
    assert "DSO 146 days vs peer mean" in ev["dso"]["display"]
    assert ev["dso"]["unit_kind"] == "days"
    assert all(e["unit_kind"] in ("ratio_level", "pp_difference", "days") for e in r["evidence"])
    assert "DSO 146 days" in r["key_finding"]
    assert out["agent_trace"][0]["agent"] == "peer" and out["degraded"] == []


def test_agent_fewer_than_three_peers_is_explicitly_unavailable():
    out = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": [_peer(1), _peer(2)]})
    r = out["peer_result"]
    assert r["unavailable"] is True and r["severity"] == "None" and r["flags_fired"] == 0
    assert "need >= 3" in r["reason"]
    out = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": []})
    assert out["peer_result"]["unavailable"] is True and out["peer_result"]["metric_zscores"] == {}


def test_agent_pre_xbrl_focus_year_unavailable():
    r = pa.run_peer({"cik": "0001024401", "focus_year": 2000, "peer_companies": [_peer(i) for i in range(4)]})["peer_result"]
    assert r["unavailable"] is True and "pre-XBRL" in r["reason"]


def test_agent_mocked_fetch_failures_degrade_not_crash(monkeypatch):
    peers = [_peer(i) for i in range(6)]
    pf_ = {p["cik"]: _facts(1000, 600 + 10 * i, 100 + 5 * i, 150, 200, 400, 80 + i, 1000, 95, 950) for i, p in enumerate(peers)}
    company = _facts(1000, 600, 100, 150, 200, 400, 80, 1000, 95, 950)
    _fake_env(monkeypatch, pf_, company, fail={peers[0]["cik"], peers[1]["cik"]})
    out = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": peers})
    r = out["peer_result"]
    assert not r.get("unavailable") and r["data_quality"]["n_peers"] == 4
    assert len([d for d in out["degraded"] if d.startswith("peer_data:")]) == 2
    # all fail -> explicit unavailable
    _fake_env(monkeypatch, pf_, company, fail={p["cik"] for p in peers})
    r = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": peers})["peer_result"]
    assert r["unavailable"] is True and "usable" in r["reason"]


def test_agent_company_fetch_failure_and_garbage_state_never_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("edgar down")
    monkeypatch.setattr(pa, "_facts_for", boom)
    out = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": [_peer(i) for i in range(4)]})
    assert out["peer_result"]["unavailable"] is True and out["peer_result"]["severity"] == "None"
    assert out["peer_result"].get("error")
    assert pa.run_peer({})["peer_result"]["unavailable"] is True
    assert pa.run_peer({"focus_year": "x", "peer_companies": 7})["peer_result"]["unavailable"] is True


def test_agent_missing_metric_is_unavailable_not_zero(monkeypatch):
    peers = [_peer(i) for i in range(4)]
    pf_ = {p["cik"]: _facts(1000, 600 + 10 * i, 100 + 5 * i, 150, 200, 400, 80 + i, 1000, 95, 950) for i, p in enumerate(peers)}
    company = _facts(1000, 600, 100, 150, 200, 400, 80, 1000, 95, 950)
    del company["by_year"][2020]["COGS"]  # gross margin cannot be computed for the company
    _fake_env(monkeypatch, pf_, company)
    r = pa.run_peer({"cik": "0000000001", "focus_year": 2020, "peer_companies": peers})["peer_result"]
    assert "gross_margin" not in r["metric_zscores"] and "gross_margin" in r["data_quality"]["unavailable"]


# ----------------------------------------------------------------------------- peer_agent: live
@pytest.mark.network
def test_peer_agent_aapl_real_data(aapl_peers):
    state = {"cik": AAPL, "ticker": "AAPL", "as_of": AAPL_ASOF, "focus_year": 2020, "analysis_years": [2018, 2019, 2020],
             "peer_companies": list(aapl_peers)}
    out = pa.run_peer(state)
    r = out["peer_result"]
    assert not r.get("unavailable"), r
    assert r["data_quality"]["n_peers"] >= 3 and set(r["metric_zscores"]) <= set(pa.METRICS)
    # company side independent check: Apple gross margin from raw XBRL
    af = xbrl_parser.extract_annual_facts(edgar_api.get_companyfacts(AAPL), [2020], as_of=AAPL_ASOF)["by_year"][2020]
    gm = (af["Revenue"]["value"] - af["COGS"]["value"]) / af["Revenue"]["value"] if "COGS" in af else \
        af["GrossProfit"]["value"] / af["Revenue"]["value"]
    assert r["metric_zscores"]["gross_margin"]["company_value"] == pytest.approx(gm)
    for m, z in r["metric_zscores"].items():
        assert z["n_peers"] >= 3
        if z["z_score"] is not None:
            assert z["flag"] == (abs(z["z_score"]) > 2.0)
    print("\nAAPL FY2020 peers:", [p["ticker"] for p in r["peer_list"]])
    for m, z in r["metric_zscores"].items():
        print(f"  {m}: z={z['z_score']} flag={z['flag']} :: {z['interpretation']}")
    print("  severity:", r["severity"], "|", r["key_finding"])


@pytest.mark.network
def test_peer_agent_msft_real_data(msft_peers):
    out = pa.run_peer({"cik": MSFT, "as_of": MSFT_ASOF, "focus_year": 2020, "analysis_years": [2019, 2020],
                       "peer_companies": list(msft_peers)})
    r = out["peer_result"]
    assert not r.get("unavailable"), r
    print("\nMSFT FY2020 peers:", [p["ticker"] for p in r["peer_list"]])
    for m, z in r["metric_zscores"].items():
        print(f"  {m}: z={z['z_score']} flag={z['flag']} :: {z['interpretation']}")
    print("  severity:", r["severity"], "|", r["key_finding"])


# ============================================================================ v2 (docs/V2_CHANGELOG_agents.md B4/B5/B6)
def test_v2_direction_table_is_complete_and_documented():
    assert set(pa.ADVERSE_DIRECTION) == set(pa.METRICS)
    assert pa.ADVERSE_DIRECTION["ocf_to_revenue"] == "below"
    for m in ("gross_margin", "dso", "receivables_vs_revenue_growth", "debt_to_equity", "roa"):
        assert pa.ADVERSE_DIRECTION[m] == "above"
    assert "Beneish" in pa.__doc__ and "Dechow" in pa.__doc__


def test_v2_compare_marks_risk_vs_informational():
    peers = _peers_for("dso", [30.0, 40.0, 50.0])  # mean 40 sd 10
    base = {m: 0.5 for m in pa.METRICS}
    hi, _ = pa.compare({**base, "dso": 70.0}, peers)
    lo, _ = pa.compare({**base, "dso": 5.0}, peers)
    assert hi["dso"]["flag"] and hi["dso"]["risk_flag"] is True and hi["dso"]["informational"] is False
    assert lo["dso"]["flag"] and lo["dso"]["risk_flag"] is False and lo["dso"]["informational"] is True
    assert lo["dso"]["direction"] == "below"
    # OCF/revenue is adverse BELOW peers
    peers = _peers_for("ocf_to_revenue", [0.10, 0.15, 0.20])
    lowc, _ = pa.compare({**base, "ocf_to_revenue": -0.5}, peers)
    highc, _ = pa.compare({**base, "ocf_to_revenue": 0.9}, peers)
    assert lowc["ocf_to_revenue"]["risk_flag"] is True and highc["ocf_to_revenue"]["risk_flag"] is False
    assert highc["ocf_to_revenue"]["informational"] is True


def _env_with_company(monkeypatch, comp_kw, peer_kw_fn, n=5):
    peers = [_peer(i) for i in range(n)]
    pf_ = {p["cik"]: _facts(**peer_kw_fn(i)) for i, p in enumerate(peers)}
    company = _facts(**comp_kw)
    _fake_env(monkeypatch, pf_, company)
    return {"cik": "0000000001", "focus_year": 2020, "analysis_years": [2019, 2020], "as_of": "2021-01-01",
            "peer_companies": peers}


def _pk(i):
    return dict(rev=1000, cogs=600 + 10 * i, ar=100 + 5 * i, ocf=150 + 5 * i, debt=200, eq=400 + 10 * i, ni=80 + 4 * i,
                ta=1000, ar_prev=95 + 5 * i, rev_prev=950)


def test_v2_opposite_direction_outlier_is_informational_not_a_flag(monkeypatch):
    # company DSO far BELOW peers (favourable) -> recorded, not counted
    state = _env_with_company(monkeypatch, dict(_pk(2), ar=10, ar_prev=10), _pk)
    r = pa.run_peer(state)["peer_result"]
    assert not r.get("unavailable"), r
    assert "dso" in r["informational_outliers"] and "dso" not in r["outlier_metrics"]
    assert "peer.dso" not in sum(r["flags_by_year"].values(), [])
    assert r["metric_zscores"]["dso"]["flag"] is True  # two-sided display retained
    assert r["severity"] in ("None", "Low")
    inf = [e for e in r["evidence"] if e["metric"] == "dso"]
    assert inf and inf[0]["informational"] is True
    assert r["flags_fired"] == len(r["outlier_metrics"])


def test_v2_adverse_direction_outlier_counts(monkeypatch):
    state = _env_with_company(monkeypatch, dict(_pk(2), ar=400), _pk)
    r = pa.run_peer(state)["peer_result"]
    assert "dso" in r["outlier_metrics"] and "peer.dso" in r["flags_by_year"][2020]
    ev = [e for e in r["evidence"] if e["metric"] == "dso"][0]
    assert ev.get("informational") in (None, False)


def test_v2_three_informational_outliers_do_not_make_high(monkeypatch):
    # favourable on DSO (low), margin (low), ROA (low): three outliers, none manipulation-consistent
    state = _env_with_company(monkeypatch, dict(rev=1000, cogs=900, ar=10, ocf=150, debt=200, eq=400, ni=1, ta=1000,
                                                ar_prev=10, rev_prev=950), _pk)
    r = pa.run_peer(state)["peer_result"]
    assert len(r["informational_outliers"]) >= 3
    assert r["severity"] == "None" and r["flags_by_year"] == {}


# B6 materiality
def test_v2_revenue_materiality_function():
    ok, why = pa.revenue_materiality({"Revenue": 3_292_000.0, "TotalAssets": 900_000_000.0})
    assert ok is False and "1%" in why
    assert pa.revenue_materiality({"Revenue": 50.0, "TotalAssets": 1000.0})[0] is True  # exactly 5%
    assert pa.revenue_materiality({"Revenue": 10.0, "TotalAssets": 1000.0})[0] is True  # exactly 1%: material
    assert pa.revenue_materiality({"Revenue": 9.99, "TotalAssets": 1000.0})[0] is False
    assert pa.revenue_materiality({"Revenue": 100.0, "TotalAssets": None})[0] is True  # cannot judge: not suppressed
    assert pa.revenue_materiality({"Revenue": None, "TotalAssets": 1000.0})[0] is True


def test_v2_tiny_revenue_company_ratios_are_not_meaningful(monkeypatch):
    # revenue 3 on assets 1000 (0.3%): revenue-denominated metrics suppressed, ROA/leverage still computed
    state = _env_with_company(monkeypatch, dict(rev=3, cogs=1, ar=1, ocf=-230, debt=200, eq=400, ni=-250, ta=1000,
                                                ar_prev=1, rev_prev=2), _pk)
    r = pa.run_peer(state)["peer_result"]
    un = r["data_quality"]["unavailable"]
    for m in ("gross_margin", "dso", "ocf_to_revenue", "receivables_vs_revenue_growth"):
        assert m not in r["metric_zscores"] and un[m].startswith("not_meaningful"), (m, un)
    assert set(r["data_quality"]["not_meaningful"]) >= {"gross_margin", "dso", "ocf_to_revenue"}
    assert not any(e["metric"] in ("ocf_to_revenue", "dso", "gross_margin") for e in r["evidence"])
    assert "roa" in r["metric_zscores"]


def test_v2_tiny_revenue_peers_are_excluded_from_the_distribution(monkeypatch):
    def pk(i):
        d = _pk(i)
        if i < 3:  # 3 of 5 peers are pre-commercial: revenue-based metrics not comparable
            d.update(rev=2, cogs=1, ar=0.5, ocf=-300, ar_prev=0.4, rev_prev=1)
        return d
    state = _env_with_company(monkeypatch, _pk(2), pk)
    r = pa.run_peer(state)["peer_result"]
    assert "ocf_to_revenue" not in r["metric_zscores"]  # only 2 comparable peers left (< 3)
    assert "only 2 peers" in r["data_quality"]["unavailable"]["ocf_to_revenue"]


def test_v2_absurd_peer_pct_is_none():
    peers = _peers_for("ocf_to_revenue", [-0.004, -0.003, -0.002])  # mean -0.003
    zs, _ = pa.compare({**{m: 0.5 for m in pa.METRICS}, "ocf_to_revenue": -1.5}, peers)
    z = zs["ocf_to_revenue"]
    assert z["peer_pct"] is None and z["peer_pct_not_meaningful"] is True
    assert "below" not in str(z["peer_pct"])  # relative percentage is suppressed; only levels are displayed
