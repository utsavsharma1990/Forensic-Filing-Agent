"""Shared foundation utilities for forensic-filing-agent.

Provides logging, model identifiers, environment loading, cache locations, date helpers,
risk-grade ordering and safe arithmetic. Every other module imports from here.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
"""Repository root (the directory that contains ``tools/``)."""


def _resolve_cache_dir() -> Path:
    override = os.environ.get("EDGAR_CACHE_DIR")
    if override:
        p = Path(override)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return PROJECT_ROOT / ".cache"


CACHE_DIR: Path = _resolve_cache_dir()
"""On-disk cache root (``.cache/`` unless ``EDGAR_CACHE_DIR`` is set)."""

MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-5-5"

RISK_ORDER: list[str] = ["Low", "Medium", "High", "Critical"]

#: Canonical financial line items shared by xbrl_parser / statement_parser / financial_metrics.
CANONICAL_ITEMS: list[str] = [
    "Revenue", "COGS", "GrossProfit", "SGA", "NetIncome", "OperatingIncome", "InterestExpense",
    "IncomeTaxExpense", "OperatingCashFlow", "Depreciation", "TotalAssets", "CurrentAssets",
    "CurrentLiabilities", "TotalLiabilities", "NetReceivables", "PPE", "LongTermDebt", "CurrentDebt",
    "RetainedEarnings", "StockholdersEquity", "CashAndEquivalents", "SharesOutstanding",
]

_env_loaded = False
_env_lock = threading.Lock()
_loggers_configured: set[str] = set()


def load_env() -> None:
    """Load ``.env`` from the project root (idempotent; silent if python-dotenv or the file is absent)."""
    global _env_loaded, CACHE_DIR
    with _env_lock:
        if _env_loaded:
            return
        _env_loaded = True
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8")
        except Exception:  # pragma: no cover - dotenv missing or unreadable file
            pass
        CACHE_DIR = _resolve_cache_dir()


def get_logger(name: str) -> logging.Logger:
    """Return a logger with a rich console handler (plain StreamHandler if rich is unavailable)."""
    logger = logging.getLogger(name)
    if name not in _loggers_configured:
        _loggers_configured.add(name)
        if not logger.handlers:
            try:
                from rich.logging import RichHandler

                handler: logging.Handler = RichHandler(show_path=False, markup=False, rich_tracebacks=False)
                handler.setFormatter(logging.Formatter("%(message)s"))
            except Exception:  # pragma: no cover
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
            logger.propagate = False
    return logger


def ISO(d: date | datetime | str | None) -> Optional[str]:  # noqa: N802 - name fixed by CONTRACTS
    """Format a date/datetime (or ISO-like string) as ``YYYY-MM-DD``; ``None`` stays ``None``."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    parsed = parse_date(str(d))
    return parsed.isoformat() if parsed else None


def parse_date(s: Any) -> Optional[date]:
    """Parse ``YYYY-MM-DD`` (optionally followed by a time part) into a ``date``; ``None`` on failure."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    text = str(s).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def fiscal_year_of(period_end: Any) -> Optional[int]:
    """Fiscal-year label of an annual period ending ``period_end`` (CONTRACTS D12).

    Rule: the calendar year of the period end, except that a period ending in January or in the first
    week of February (52/53-week retail calendars, e.g. FYE 2019-02-02) belongs to the PRIOR year.
    The SEC ``fy`` field of companyfacts is deliberately NOT used: it labels the filing, not the period.
    """
    d = parse_date(period_end)
    if d is None:
        return None
    if d.month == 1 or (d.month == 2 and d.day <= 7):
        return d.year - 1
    return d.year


def flatten_year(facts_for_year: Optional[Mapping[str, Any]]) -> dict[str, Optional[float]]:
    """Flatten ``{canonical: FactValue}`` to ``{canonical: float|None}``.

    All canonical items are present in the output; absent / non-finite values become ``None``.
    Already-flat values (plain numbers) are accepted too.
    """
    out: dict[str, Optional[float]] = {k: None for k in CANONICAL_ITEMS}
    for key, fv in (facts_for_year or {}).items():
        val = fv.get("value") if isinstance(fv, Mapping) else fv
        try:
            f = float(val) if val is not None else None
        except (TypeError, ValueError):
            f = None
        if f is not None and not math.isfinite(f):
            f = None
        out[key] = f
    return out


def risk_rank(grade: Optional[str]) -> int:
    """Index of ``grade`` in :data:`RISK_ORDER` (case-insensitive); -1 when unknown/None."""
    if not grade:
        return -1
    g = str(grade).strip().capitalize()
    return RISK_ORDER.index(g) if g in RISK_ORDER else -1


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """``a / b`` or ``None`` when either is None/non-finite or ``b`` is zero. Never raises, never NaN."""
    try:
        if a is None or b is None:
            return None
        a_f, b_f = float(a), float(b)
        if b_f == 0.0 or not math.isfinite(a_f) or not math.isfinite(b_f):
            return None
        r = a_f / b_f
        return r if math.isfinite(r) else None
    except (TypeError, ValueError):
        return None


load_env()
