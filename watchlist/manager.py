"""SQLite-backed watchlist storage (CONTRACTS section 8).

Thread-safe by design: every call opens a short-lived connection (WAL mode, busy timeout) and closes it,
so the APScheduler thread and the Streamlit thread never share a connection. All SQL is parameterised.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from tools.common import PROJECT_ROOT, RISK_ORDER, get_logger

log = get_logger("watchlist.manager")

DEFAULT_DB_PATH = Path(PROJECT_ROOT) / "watchlist" / "watchlist.db"
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
TREND_ARROWS = {"up": "↑", "flat": "→", "down": "↓", None: ""}

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL UNIQUE, company_name TEXT, cik TEXT, added_date TEXT, last_analyzed TEXT, last_risk_grade TEXT, alert_threshold TEXT DEFAULT 'Medium', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS risk_history (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, analysis_date TEXT, risk_grade TEXT, flags_fired INTEGER, smoking_gun_1 TEXT, suspicion_score INTEGER);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, alert_date TEXT, previous_grade TEXT, new_grade TEXT, trigger_reason TEXT, acknowledged INTEGER DEFAULT 0);
"""


class WatchlistError(ValueError):
    """Invalid input or unknown company (message is user-presentable)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_ticker(ticker: Any) -> str:
    t = str(ticker or "").strip().upper().replace("/", "-")
    if not _TICKER_RE.match(t):
        raise WatchlistError(f"invalid ticker {ticker!r}")
    return t


def validate_threshold(threshold: Any) -> str:
    s = str(threshold or "").strip().capitalize()
    if s not in RISK_ORDER:
        raise WatchlistError(f"alert_threshold must be one of {RISK_ORDER}, got {threshold!r}")
    return s


def _db_path(path: Optional[str | Path] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("WATCHLIST_DB_PATH")
    return Path(env) if env else DEFAULT_DB_PATH


@contextmanager
def _connect(path: Optional[str | Path] = None) -> Iterator[sqlite3.Connection]:
    p = _db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30, isolation_level=None)  # autocommit; explicit BEGIN in _tx
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)  # idempotent: safe even if init_db was never called
        yield conn
    finally:
        conn.close()


@contextmanager
def _tx(path: Optional[str | Path] = None) -> Iterator[sqlite3.Connection]:
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def init_db(path: Optional[str | Path] = None) -> Path:
    """Create the database/tables if missing (idempotent). Returns the resolved path."""
    with _connect(path):
        pass
    return _db_path(path)


def _default_resolver(ticker: str) -> dict:
    from tools.edgar_api import resolve_company
    return resolve_company(ticker)


def add_company(ticker: str, alert_threshold: str = "Medium", *, db_path: Optional[str | Path] = None,
                resolver: Optional[Callable[[str], dict]] = None) -> dict:
    """Add (or reactivate) a ticker. Resolves name/CIK via EDGAR; unknown ticker -> WatchlistError."""
    t = normalize_ticker(ticker)
    thr = validate_threshold(alert_threshold)
    try:
        info = (resolver or _default_resolver)(t) or {}
    except Exception as e:  # EdgarNotFound, network errors, ...
        raise WatchlistError(f"could not resolve ticker {t!r} on SEC EDGAR: {e}") from e
    name, cik = info.get("name") or "", info.get("cik") or ""
    with _tx(db_path) as c:
        row = c.execute("SELECT id FROM watchlist WHERE ticker=?", (t,)).fetchone()
        if row is None:
            c.execute("INSERT INTO watchlist (ticker, company_name, cik, added_date, alert_threshold, active) "
                      "VALUES (?,?,?,?,?,1)", (t, name, cik, _now(), thr))
        else:  # re-adding reactivates and refreshes threshold/identity; history is kept
            c.execute("UPDATE watchlist SET active=1, alert_threshold=?, "
                      "company_name=COALESCE(NULLIF(?, ''), company_name), cik=COALESCE(NULLIF(?, ''), cik) "
                      "WHERE ticker=?", (thr, name, cik, t))
    return get_company(t, db_path=db_path)  # type: ignore[return-value]


def get_company(ticker: str, *, db_path: Optional[str | Path] = None) -> Optional[dict]:
    t = normalize_ticker(ticker)
    with _connect(db_path) as c:
        row = c.execute("SELECT * FROM watchlist WHERE ticker=?", (t,)).fetchone()
    return dict(row) if row else None


def remove_company(ticker: str, *, db_path: Optional[str | Path] = None) -> bool:
    """Soft-remove (active=0) so history is preserved; add_company reactivates. True if a row changed."""
    return set_active(ticker, False, db_path=db_path)


def set_active(ticker: str, active: bool, *, db_path: Optional[str | Path] = None) -> bool:
    t = normalize_ticker(ticker)
    with _tx(db_path) as c:
        cur = c.execute("UPDATE watchlist SET active=? WHERE ticker=?", (1 if active else 0, t))
        return cur.rowcount > 0


def _trend(scores: list) -> Optional[str]:
    """scores newest first. up = suspicion rose (worse), down = fell (improving)."""
    if len(scores) < 2 or scores[0] is None or scores[1] is None:
        return None
    return "up" if scores[0] > scores[1] else "down" if scores[0] < scores[1] else "flat"


def list_companies(active_only: bool = False, *, db_path: Optional[str | Path] = None) -> list[dict]:
    """Companies joined with latest risk_history: last_grade, flags_fired, suspicion_score, trend, trend_arrow."""
    q = "SELECT * FROM watchlist" + (" WHERE active=1" if active_only else "") + " ORDER BY ticker"
    out = []
    with _connect(db_path) as c:
        for w in c.execute(q).fetchall():
            d = dict(w)
            hist = c.execute("SELECT * FROM risk_history WHERE ticker=? ORDER BY id DESC LIMIT 2",
                             (d["ticker"],)).fetchall()
            latest = hist[0] if hist else None
            d["last_grade"] = latest["risk_grade"] if latest else d.get("last_risk_grade")
            d["flags_fired"] = latest["flags_fired"] if latest else None
            d["suspicion_score"] = latest["suspicion_score"] if latest else None
            d["smoking_gun_1"] = latest["smoking_gun_1"] if latest else ""
            d["trend"] = _trend([h["suspicion_score"] for h in hist])
            d["trend_arrow"] = TREND_ARROWS[d["trend"]]
            out.append(d)
    return out


def _total_flags(state: dict) -> int:
    total = 0
    for k in ("quantitative_result", "language_result", "network_result", "peer_result"):
        r = state.get(k) or {}
        try:
            total += int(r.get("flags_fired") or 0)
        except (TypeError, ValueError):
            pass
    return total


def record_analysis(ticker: str, state: dict, *, db_path: Optional[str | Path] = None) -> dict:
    """Write a risk_history row from a ForensicAgentState; update watchlist.last_analyzed/last_risk_grade."""
    t = normalize_ticker(ticker)
    grade = state.get("risk_grade") or ""
    guns = state.get("smoking_guns") or []
    gun = str(guns[0]) if guns else ""
    score = state.get("suspicion_score")
    score = int(score) if isinstance(score, (int, float)) and score == score else None
    flags = _total_flags(state)
    now = _now()
    with _tx(db_path) as c:
        c.execute("INSERT INTO risk_history (ticker, analysis_date, risk_grade, flags_fired, smoking_gun_1, "
                  "suspicion_score) VALUES (?,?,?,?,?,?)", (t, now, grade, flags, gun, score))
        c.execute("UPDATE watchlist SET last_analyzed=?, last_risk_grade=? WHERE ticker=?", (now, grade or None, t))
    return {"ticker": t, "analysis_date": now, "risk_grade": grade, "flags_fired": flags,
            "smoking_gun_1": gun, "suspicion_score": score}


def get_risk_history(ticker: str, *, db_path: Optional[str | Path] = None) -> list[dict]:
    """Oldest first (chart order)."""
    t = normalize_ticker(ticker)
    with _connect(db_path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM risk_history WHERE ticker=? ORDER BY id", (t,))]


def list_alerts(unacknowledged_only: bool = True, *, db_path: Optional[str | Path] = None) -> list[dict]:
    q = "SELECT * FROM alerts" + (" WHERE acknowledged=0" if unacknowledged_only else "") + " ORDER BY id DESC"
    with _connect(db_path) as c:
        return [dict(r) for r in c.execute(q)]


def create_alert(ticker: str, previous_grade: str, new_grade: str, trigger_reason: str = "", *,
                 db_path: Optional[str | Path] = None) -> int:
    t = normalize_ticker(ticker)
    with _tx(db_path) as c:
        cur = c.execute("INSERT INTO alerts (ticker, alert_date, previous_grade, new_grade, trigger_reason, "
                        "acknowledged) VALUES (?,?,?,?,?,0)", (t, _now(), previous_grade, new_grade, trigger_reason))
        return int(cur.lastrowid)


def acknowledge_alert(alert_id: int, *, db_path: Optional[str | Path] = None) -> bool:
    with _tx(db_path) as c:
        return c.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (int(alert_id),)).rowcount > 0
