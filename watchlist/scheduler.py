"""Watchlist checks and the APScheduler wrapper (CONTRACTS section 8)."""
from __future__ import annotations

import asyncio
import inspect
import os
import threading
from typing import Any, Callable, Optional

from tools.common import get_logger, risk_rank
from watchlist import manager

log = get_logger("watchlist.scheduler")

_scheduler = None
_lock = threading.Lock()


def _run_analyze(analyze: Callable, **kwargs) -> Any:
    """Call a sync or async analyze_company-style callable from a plain (non-event-loop) thread."""
    res = analyze(**kwargs)
    if inspect.isawaitable(res):
        async def _wrap():
            return await res
        res = asyncio.run(_wrap())
    return res


def _default_analyze(**kwargs):
    from graph.pipeline import analyze_company  # lazy: pipeline may not exist at import time
    return analyze_company(**kwargs)


def _default_list_filings(cik, as_of=None):
    from tools.edgar_api import list_annual_filings
    return list_annual_filings(cik, as_of)


def should_alert(previous: Optional[str], new: Optional[str], threshold: str) -> bool:
    """Alert iff grade worsened AND new grade rank >= threshold rank. Unknown/empty previous never alerts."""
    p, n = risk_rank(previous), risk_rank(new)
    return p >= 0 and n > p and n >= risk_rank(threshold)


def _reason(prev: str, state: dict) -> str:
    new = state.get("risk_grade", "")
    sev = state.get("agent_severity") or {}
    sev_txt = ", ".join(f"{k}={v}" for k, v in sev.items()) if isinstance(sev, dict) and sev else "n/a"
    guns = state.get("smoking_guns") or []
    gun = guns[0] if guns else "none reported"
    return f"Risk grade rose from {prev} to {new}. Agent severities: {sev_txt}. Top smoking gun: {gun}"


def run_watchlist_check(force: bool = False, db_path=None, analyze: Optional[Callable] = None,
                        list_filings: Optional[Callable] = None) -> list[dict]:
    """Check every active company; never raises. Returns one result dict per company.

    New filing = annual filing with filing_date > last_analyzed (date part). A never-analysed company is
    analysed once if it has any annual filing. ``force`` analyses regardless of filings.
    """
    try:
        manager.init_db(db_path)
        companies = manager.list_companies(active_only=True, db_path=db_path)
    except Exception as e:
        log.error("watchlist check could not read the database: %s", e)
        return [{"ticker": None, "status": "error", "error": f"database: {e}"}]
    analyze = analyze or _default_analyze
    list_filings = list_filings or _default_list_filings
    results: list[dict] = []
    for comp in companies:
        t = comp["ticker"]
        res: dict[str, Any] = {"ticker": t, "status": "skipped", "new_filing": False, "analyzed": False,
                               "previous_grade": comp.get("last_risk_grade"), "new_grade": None,
                               "alert_id": None, "risk_changed": False, "error": None}
        try:
            last = comp.get("last_analyzed")
            last_date = last[:10] if last else None
            if force:
                res["new_filing"] = True
            else:
                filings = list_filings(comp.get("cik") or t, None) or []
                dates = sorted(f.get("filing_date", "") for f in filings if f.get("filing_date"))
                newest = dates[-1] if dates else None
                res["latest_filing_date"] = newest
                if newest is None:
                    res["status"] = "no_filings"
                    results.append(res)
                    continue
                res["new_filing"] = last_date is None or newest > last_date
                if not res["new_filing"]:
                    res["status"] = "no_new_filing"
                    log.info("%s: no new annual filing since %s", t, last_date)
                    results.append(res)
                    continue
            prev = comp.get("last_risk_grade") or None
            state = _run_analyze(analyze, ticker=t, cik=comp.get("cik") or None, previous_risk_grade=prev,
                                 watchlist_id=str(comp["id"]))
            if not isinstance(state, dict) or state.get("error") or not state.get("risk_grade"):
                why = state.get("error") if isinstance(state, dict) else state
                raise RuntimeError(f"analysis failed: {why or 'no risk_grade returned'}")
            new_grade = state["risk_grade"]
            res.update(analyzed=True, status="analyzed", new_grade=new_grade,
                       suspicion_score=state.get("suspicion_score"))
            if should_alert(prev, new_grade, comp.get("alert_threshold") or "Medium"):
                reason = _reason(prev, state)
                res["alert_id"] = manager.create_alert(t, prev, new_grade, reason, db_path=db_path)
                res.update(risk_changed=True, trigger_reason=reason, status="alert")
                state["risk_changed"] = True
                log.warning("ALERT %s: %s -> %s", t, prev, new_grade)
            manager.record_analysis(t, state, db_path=db_path)
        except Exception as e:  # per-company isolation: never propagate
            log.exception("watchlist check failed for %s", t)
            res.update(status="error", error=f"{type(e).__name__}: {e}")
        results.append(res)
    return results


def start_scheduler(interval_hours: Optional[float] = None, db_path=None):
    """Start (or return the running) BackgroundScheduler running run_watchlist_check every N hours."""
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    hours = interval_hours
    if hours is None:
        try:
            hours = float(os.environ.get("WATCHLIST_CHECK_INTERVAL_HOURS", "24"))
        except ValueError:
            hours = 24.0
    if hours <= 0:
        hours = 24.0
    with _lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler
        sched = BackgroundScheduler(daemon=True)
        sched.add_job(run_watchlist_check, "interval", hours=hours, kwargs={"db_path": db_path},
                      id="watchlist_check", max_instances=1, coalesce=True,
                      misfire_grace_time=3600, replace_existing=True)
        sched.start()
        _scheduler = sched
        log.info("watchlist scheduler started (every %s h)", hours)
        return sched


def stop_scheduler(wait: bool = False) -> None:
    """Graceful shutdown helper (idempotent)."""
    global _scheduler
    with _lock:
        if _scheduler is not None:
            try:
                if _scheduler.running:
                    _scheduler.shutdown(wait=wait)
            except Exception as e:  # pragma: no cover
                log.warning("scheduler shutdown: %s", e)
            _scheduler = None
