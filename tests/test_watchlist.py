"""Watchlist tests: temp DB + fakes, no network, no LLM."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from watchlist import manager, scheduler


def fake_resolver(t):
    if t == "NOPE":
        raise RuntimeError("not found")
    return {"ticker": t, "cik": "0000000001", "name": f"{t} Corp"}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "w.db"
    manager.init_db(p)
    return p


def add(db, t, thr="Medium"):
    return manager.add_company(t, thr, db_path=db, resolver=fake_resolver)


def state(grade, score=10, guns=("gun A", "gun B"), flags=(1, 2, 0, 1)):
    return {"risk_grade": grade, "suspicion_score": score, "smoking_guns": list(guns),
            "quantitative_result": {"flags_fired": flags[0]}, "language_result": {"flags_fired": flags[1]},
            "network_result": {"flags_fired": flags[2]}, "peer_result": {"flags_fired": flags[3]}}


def test_add_remove_reactivate_list(db):
    c = add(db, " aapl ", "High")
    assert c["ticker"] == "AAPL" and c["company_name"] == "AAPL Corp" and c["active"] == 1
    manager.remove_company("AAPL", db_path=db)
    assert manager.list_companies(active_only=True, db_path=db) == []
    assert manager.list_companies(db_path=db)[0]["active"] == 0
    add(db, "AAPL", "Low")
    rows = manager.list_companies(db_path=db)
    assert len(rows) == 1 and rows[0]["active"] == 1 and rows[0]["alert_threshold"] == "Low"
    assert manager.set_active("AAPL", False, db_path=db) and manager.set_active("ZZZ", False, db_path=db) is False


def test_threshold_and_unknown_ticker(db):
    with pytest.raises(manager.WatchlistError):
        add(db, "AAPL", "Severe")
    with pytest.raises(manager.WatchlistError):
        add(db, "NOPE")
    assert manager.list_companies(db_path=db) == []


def test_sql_injection_ticker(db):
    add(db, "AAPL")
    with pytest.raises(manager.WatchlistError):
        add(db, "AAPL'; DROP TABLE watchlist;--")
    with pytest.raises(manager.WatchlistError):
        manager.get_risk_history("x' OR '1'='1", db_path=db)
    assert len(manager.list_companies(db_path=db)) == 1
    # even a resolver-returned malicious name is stored inertly
    manager.add_company("MSFT", db_path=db, resolver=lambda t: {"cik": "1", "name": "x'); DROP TABLE alerts;--"})
    assert manager.list_alerts(db_path=db) == []


def test_wal_mode(db):
    assert sqlite3.connect(str(db)).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_record_analysis_and_trend(db):
    add(db, "AAPL")
    assert manager.list_companies(db_path=db)[0]["trend"] is None
    r = manager.record_analysis("AAPL", state("Low", 10), db_path=db)
    assert r["flags_fired"] == 4 and r["smoking_gun_1"] == "gun A"
    manager.record_analysis("AAPL", state("Medium", 40), db_path=db)
    c = manager.list_companies(db_path=db)[0]
    assert c["trend"] == "up" and c["trend_arrow"] == "↑"
    assert c["last_grade"] == "Medium" and c["last_risk_grade"] == "Medium" and c["last_analyzed"]
    assert c["suspicion_score"] == 40 and c["flags_fired"] == 4
    manager.record_analysis("AAPL", state("Medium", 40, guns=()), db_path=db)
    assert manager.list_companies(db_path=db)[0]["trend"] == "flat"
    manager.record_analysis("AAPL", state("Low", 5), db_path=db)
    assert manager.list_companies(db_path=db)[0]["trend"] == "down"
    h = manager.get_risk_history("aapl", db_path=db)
    assert [x["suspicion_score"] for x in h] == [10, 40, 40, 5] and h[2]["smoking_gun_1"] == ""


def test_alert_crud(db):
    i = manager.create_alert("AAPL", "Low", "High", "why", db_path=db)
    assert len(manager.list_alerts(db_path=db)) == 1
    assert manager.acknowledge_alert(i, db_path=db)
    assert manager.list_alerts(db_path=db) == []
    assert len(manager.list_alerts(False, db_path=db)) == 1


FILING = lambda cik, as_of=None: [{"filing_date": "2999-01-01", "form": "10-K"}]  # noqa: E731


def run(db, grade, **kw):
    return scheduler.run_watchlist_check(db_path=db, analyze=lambda **k: state(grade),
                                         list_filings=kw.pop("list_filings", FILING), **kw)


@pytest.mark.parametrize("prev,new,thr,alert", [
    ("Low", "Medium", "Medium", True),
    ("Medium", "Low", "Medium", False),
    ("High", "High", "Medium", False),
    ("Low", "Medium", "High", False),
    ("Low", "Critical", "Medium", True),
    ("Low", "Critical", "High", True),
])
def test_alert_logic(db, prev, new, thr, alert):
    add(db, "AAPL", thr)
    manager.record_analysis("AAPL", state(prev), db_path=db)
    res = run(db, new)
    assert res[0]["status"] in ("alert", "analyzed") and res[0]["error"] is None
    assert (len(manager.list_alerts(db_path=db)) == 1) is alert
    assert res[0]["risk_changed"] is alert
    assert manager.get_company("AAPL", db_path=db)["last_risk_grade"] == new
    if alert:
        reason = manager.list_alerts(db_path=db)[0]["trigger_reason"]
        assert "gun A" in reason and new in reason


def test_first_run_analyses_once_no_alert(db):
    add(db, "AAPL", "Low")
    res = run(db, "Critical")
    assert res[0]["analyzed"] and res[0]["alert_id"] is None  # no previous grade -> nothing to compare
    assert manager.list_alerts(db_path=db) == []
    # second run: filing date 2999 > last_analyzed would be "new"; use an old filing instead
    res2 = run(db, "Critical", list_filings=lambda c, a=None: [{"filing_date": "2001-01-01"}])
    assert res2[0]["status"] == "no_new_filing" and not res2[0]["analyzed"]


def test_force_and_previous_grade_passed(db):
    add(db, "AAPL")
    manager.record_analysis("AAPL", state("Low"), db_path=db)
    seen = {}

    def an(**k):
        seen.update(k)
        return state("Low")
    old = lambda c, a=None: [{"filing_date": "2001-01-01"}]  # noqa: E731
    assert scheduler.run_watchlist_check(db_path=db, analyze=an, list_filings=old)[0]["status"] == "no_new_filing"
    assert seen == {}
    r = scheduler.run_watchlist_check(force=True, db_path=db, analyze=an, list_filings=old)
    assert r[0]["analyzed"] and seen["previous_risk_grade"] == "Low" and seen["ticker"] == "AAPL"


def test_failure_isolation_and_async_analyze(db):
    for t in ("AAA", "BBB", "CCC"):
        add(db, t)

    async def an(**k):
        if k["ticker"] == "BBB":
            raise RuntimeError("boom")
        return state("Low")
    res = scheduler.run_watchlist_check(db_path=db, analyze=an, list_filings=FILING)
    by = {r["ticker"]: r for r in res}
    assert by["BBB"]["status"] == "error" and "boom" in by["BBB"]["error"]
    assert by["AAA"]["analyzed"] and by["CCC"]["analyzed"]
    # error state dict and filing-list failure are also isolated
    res = scheduler.run_watchlist_check(db_path=db, force=True, analyze=lambda **k: {"error": "x"})
    assert all(r["status"] == "error" for r in res)

    def bad_list(c, a=None):
        raise OSError("net")
    res = scheduler.run_watchlist_check(db_path=db, analyze=lambda **k: state("Low"), list_filings=bad_list)
    assert all(r["status"] == "error" for r in res)


def test_inactive_skipped(db):
    add(db, "AAPL")
    manager.remove_company("AAPL", db_path=db)
    assert run(db, "Low") == []


def test_concurrent_writes(db):
    add(db, "AAPL")
    errs = []

    def work(n):
        try:
            for i in range(15):
                manager.record_analysis("AAPL", state("Low", i), db_path=db)
                manager.create_alert("AAPL", "Low", "High", f"t{n}", db_path=db)
        except Exception as e:  # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=work, args=(n,)) for n in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    assert len(manager.get_risk_history("AAPL", db_path=db)) == 30
    assert len(manager.list_alerts(db_path=db)) == 30


def test_scheduler_start_stop(db):
    s = scheduler.start_scheduler(interval_hours=1, db_path=db)
    try:
        job = s.get_job("watchlist_check")
        assert job.max_instances == 1 and job.coalesce is True
        assert scheduler.start_scheduler() is s
    finally:
        scheduler.stop_scheduler()
    assert not s.running
    scheduler.stop_scheduler()  # idempotent


def test_cli_add_list_remove(tmp_path, monkeypatch, capsys):
    import watchlist_monitor
    monkeypatch.setenv("WATCHLIST_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr(manager, "_default_resolver", fake_resolver)
    assert watchlist_monitor.main(["--add", "ZZZ:High", "--list"]) == 0
    assert "ZZZ" in capsys.readouterr().out
    assert watchlist_monitor.main(["--remove", "ZZZ", "--list"]) == 0
    assert [c["ticker"] for c in manager.list_companies(active_only=True)] == []
    assert watchlist_monitor.main(["--remove", "NOSUCH"]) == 1
