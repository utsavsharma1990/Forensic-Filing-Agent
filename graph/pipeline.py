"""LangGraph assembly for forensic-filing-agent (CONTRACTS section 5, D6, D8; docs/PHASE2_NOTES.md).

::

    START -> fetch_data -+-(fatal error)-> handle_error -> END
                         |
                         +-> run_quantitative -+
                             run_language     -+-> run_temporal -> run_synthesis -> END
                             run_network      -+
                             run_peer         -+

* Agents 1-4 are sync functions; each node runs its agent with ``asyncio.to_thread`` so I/O truly overlaps
  (proved by ``state["node_timings"]`` / ``agent_trace`` overlap in the tests).
* ``fetch_data`` is the only node that touches the network for raw data. Everything is point-in-time (``as_of``).
* Flag exclusion (``tools.config``; pre-registered ``no_passive`` variant, docs/TUNING_LEDGER.md P2) is applied as
  a post-processing filter on each of the four agent results BEFORE ``run_temporal`` reads them. With no exclusions
  the agent result objects pass through untouched.
* ``progress_callback(event)`` receives ``{"node","status","message","elapsed_ms"[, "detail"]}``; ``status`` is
  ``start|done|error|jev``. It is always invoked on the event-loop thread (sub-events raised from worker threads are
  marshalled), and any exception it raises is swallowed.

Public API: ``pipeline`` (StateGraph), ``forensic_agent`` (compiled with MemorySaver),
``async analyze_company(...)``, ``analyze_company_sync(...)``.
"""
from __future__ import annotations

import asyncio
import collections
import inspect
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.quantitative_agent import run_quantitative
from agents.language_agent import run_language
from agents.network_agent import run_network
from agents.peer_agent import run_peer
from agents.state import ForensicAgentState, new_state
from agents.synthesis_agent import run_synthesis
from agents.temporal_agent import run_temporal
from tools import edgar_api, text_parser, xbrl_parser
from tools.common import get_logger, load_env, parse_date
from tools.config import apply_exclusions, get_excluded_flags, unpropagated_flags

log = get_logger("graph.pipeline")

# --------------------------------------------------------------------------------------- UI messages
UI_MESSAGES: dict[str, str] = {
    "fetch_data": "Fetching SEC EDGAR data...",
    "quantitative": "Running quantitative forensics...",
    "language": "Analyzing filing language...",
    "network": "Checking auditor and executive history...",
    "peer": "Comparing against peer group...",
    "temporal": "Building temporal intelligence...",
    "prior_year": "Re-running agents on the prior year (Jev material-change baseline)...",
    "jev": "Running Jev confidence scoring...",
    "synthesis": "Synthesizing final verdict...",
}
AGENT_NODES = ("quantitative", "language", "network", "peer")
_AGENT_FUNC = {"quantitative": "run_quantitative", "language": "run_language",
               "network": "run_network", "peer": "run_peer"}  # looked up in globals() at call time (patchable)

TEXT_WORKERS = 4
SHORT_TEXT_CHARS = 50_000          # warn (never change behaviour) when a filing's text is shorter than this
PIPELINE_VERSION = "v3"
PRIOR_YEAR_TIMEOUT_S = 120.0       # hard bound on the optional prior-year re-run (Jev material_change baseline)
PROXY_WINDOW_BEFORE_DAYS = 90      # DEF 14A matched to an annual report if filed within [-90, +180] days of it
PROXY_WINDOW_AFTER_DAYS = 180


# --------------------------------------------------------------------------------------- run context / callbacks
class _Ctx:
    def __init__(self, cb: Optional[Callable[[dict], Any]], loop: Optional[asyncio.AbstractEventLoop]):
        self.cb = cb
        self.loop = loop
        self.t0 = time.perf_counter()


_CTX: dict[str, _Ctx] = {}
_CTX_LOCK = threading.Lock()
_CHECKPOINTER = MemorySaver()


def _ctx_of(config: Any) -> Optional[_Ctx]:
    try:
        return _CTX.get((config or {}).get("configurable", {}).get("thread_id"))
    except Exception:
        return None


def _deliver(ctx: _Ctx, event: dict) -> None:
    """Call the user callback; never raises."""
    if ctx.cb is None:
        return
    try:
        res = ctx.cb(event)
        if inspect.isawaitable(res):
            try:
                asyncio.ensure_future(res)
            except RuntimeError:
                if inspect.iscoroutine(res):
                    res.close()
    except Exception as exc:  # a UI callback must never break the pipeline
        log.debug("progress_callback raised %r (ignored)", exc)


def _emit(ctx: Optional[_Ctx], node: str, status: str, detail: Optional[str] = None,
          message: Optional[str] = None) -> None:
    if ctx is None or ctx.cb is None:
        return
    ev = {"node": node, "status": status, "message": message or UI_MESSAGES.get(node, node),
          "elapsed_ms": int((time.perf_counter() - ctx.t0) * 1000)}
    if detail:
        ev["detail"] = detail
    _deliver(ctx, ev)


def _emit_threadsafe(ctx: Optional[_Ctx], node: str, status: str, detail: Optional[str] = None) -> None:
    """Emit from a worker thread: marshal onto the event loop so callbacks always run on one thread."""
    if ctx is None or ctx.cb is None:
        return
    if ctx.loop is not None and ctx.loop.is_running():
        try:
            ctx.loop.call_soon_threadsafe(_emit, ctx, node, status, detail)
            return
        except RuntimeError:
            pass
    _emit(ctx, node, status, detail)


# --------------------------------------------------------------------------------------- generic helpers
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timing(node: str, t_start: float, t_end: float) -> dict:
    return {"node": node, "start_ts": t_start, "end_ts": t_end, "duration_ms": int((t_end - t_start) * 1000)}


def _unavailable_agent_result(name: str, msg: str, focus_year: Any) -> dict:
    return {"error": msg, "unavailable": True, "severity": "None", "flags_fired": 0, "flags_by_year": {},
            "focus_year": focus_year, "evidence": [], "data_quality": {"unavailable": {name: msg}},
            "degraded": [f"{name}: {msg}"], "key_finding": f"{name} unavailable: {msg}"}


# --------------------------------------------------------------------------------------- shell / SPAC detection (v2, B2/B8)
# Everything below is computed from the FILING TEXT itself (no ticker lists, no hand-keyed company knowledge).
#
# Signals (a year is ``is_shell`` when ANY holds):
#   cover  - the cover-page "shell company (as defined in Rule 12b-2)" check box is marked Yes.
#   spac   - blank-check vocabulary prevalence ("blank check company", "Trust Account", "initial business combination":
#            >= SPAC_TERM_MIN occurrences in each of >= 2 of the 3 families) AND a "no operations / no revenue" statement.
#   stub   - text shorter than STUB_FLOOR_CHARS. A 10-K that contains Item 1 (business), Item 7 (MD&A) and Item 8
#            (statements) is never this short: the ENRON OREGON FY1996 "annual report" is 15,667 characters (cover page,
#            one-paragraph items, exhibit list); the shortest of the 130 filings in the local text cache that is NOT a stub is
#            60,252 characters and the smallest large-cap dev filing is 241,383. 25,000 sits in the empty gap, so it
#            generalises to any registrant whose "annual report" is a placeholder (wholly-owned finance subsidiaries,
#            co-registrant wrappers, ...). It would also catch a genuine micro-cap shell 10-K, which is correct (is_shell).
#   wrapper- text < WRAPPER_FLOOR_CHARS, cites Exhibit 13 / the annual report to shareholders >= 2 times and contains no
#            "total assets" line: the statements live in an exhibit the text does not include (10-K405 style wrapper).
# ``spac_predecessor`` = the filing is the SPAC's OWN pre-merger annual report: either the spac signal above fired, or a LATER
# filing of the same registrant says the SPAC Business Combination closed during the fiscal year after it (successor side).
# The successor rule needs all of: >= 10 capitalised "Business Combination", >= 3 completion phrases, any blank-check/Trust
# Account/SPAC/legacy vocabulary, the filing is not itself a shell, and a closing date (modal date near completion language)
# that falls INSIDE the filing's own fiscal year; the PRIOR fiscal year is then flagged.
STUB_FLOOR_CHARS = 25_000
WRAPPER_FLOOR_CHARS = 60_000
SPAC_TERM_MIN = 5
SUCCESSOR_MIN_CAP_BC = 10
SUCCESSOR_MIN_COMPLETIONS = 3
_COVER_SCAN_CHARS = 30_000

_GLYPHS = "xXoOqQ☒☑☐□■✔✓√¨þýÿ¡❏●"
_MARKED = set("xX☒☑✔✓√þýÿ■●")   # check-marked glyphs (incl. Wingdings via Latin-1)
_G = r"(?:\[\s*[xX]?\s*\]|[" + re.escape(_GLYPHS) + r"])"
_YES_NO = re.compile(r"(?:(?<!\w)(?P<b1>" + _G + r")\s+)?\b[Yy]es\b\s*(?:(?P<b2>" + _G + r")\s*)?\bNo\b(?:\s*(?P<b3>" + _G + r")(?=\s|$))?")
_BLANK_CHECK = re.compile(r"blank[\s-]+check\s+(?:company|companies|corporation|shell)", re.I)  # not 'blank check preferred stock'
_TRUST_ACCT = re.compile(r"\btrust\s+account\b", re.I)
_IBC = re.compile(r"\binitial\s+business\s+combination\b", re.I)
_SPAC_WORD = re.compile(r"special\s+purpose\s+acquisition|\bSPAC\b|\bblank[\s-]+check\b|\btrust\s+account\b|\bLegacy\s+[A-Z]\w+", re.I)
_NO_OPS = re.compile(r"(?:neither\s+engaged\s+in\s+any\s+operations\s+nor\s+generated|not\s+(?:yet\s+)?generated\s+any|no\s+operations\b|"
                     r"not\s+(?:yet\s+)?commenced\s+any\s+operations|no\s+operating\s+(?:business|revenue))", re.I)
_CAP_BC = re.compile(r"Business Combination")
_COMPLETION = re.compile(r"(?:consummat|complet|clos)\w*\s+(?:of\s+)?the\s+(?:\w+\s+){0,3}Business Combination|"
                         r"Business Combination\s+(?:was|were)\s+(?:consummated|completed|closed)")
_CLOSE_CTX = re.compile(r"(?:consummat|complet|clos)\w*[^.]{0,160}?(?:Business\s+Combination|[Mm]erger)|Closing\s+Date|"
                        r"(?:Business\s+Combination|[Mm]erger)[^.]{0,80}?(?:was|were)\s+(?:consummated|completed|closed)")
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_DATE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b")
_EX13 = re.compile(r"exhibit\s+13\b|annual\s+report\s+to\s+(?:share|stock)holders", re.I)
_INCORP = re.compile(r"incorporated\s+(?:herein\s+)?by\s+reference", re.I)


def cover_shell_checkbox(text: str) -> Optional[bool]:
    """Parse the cover-page 'shell company (as defined in Rule 12b-2)' Yes/No boxes.

    True = Yes marked, False = No marked, None = absent / unparseable / both or neither marked. Handles glyph-after-label
    ('Yes x No o', 'Yes [X] No [ ]'), glyph-before-label ('[X] Yes [ ] No') and Wingdings/Unicode box characters.
    """
    head = text[:_COVER_SCAN_CHARS]
    for m in re.finditer(r"shell\s+company", head, re.I):
        yn = _YES_NO.search(head[m.end(): m.end() + 260])
        if not yn:
            continue
        b1, b2, b3 = yn.group("b1"), yn.group("b2"), yn.group("b3")
        if b3 is not None:
            yes, no = b2, b3
        elif b1 is not None:
            yes, no = b1, b2
        else:
            continue
        ym = bool(yes) and (yes in _MARKED or bool(re.fullmatch(r"\[\s*[xX]\s*\]", yes)))
        nm = bool(no) and (no in _MARKED or bool(re.fullmatch(r"\[\s*[xX]\s*\]", no)))
        if ym and not nm:
            return True
        if nm and not ym:
            return False
        return None
    return None


def _parse_dm(m: "re.Match[str]") -> Optional[date]:
    try:
        return date(int(m.group(3)), _MONTHS.index(m.group(1)) + 1, int(m.group(2)))
    except (ValueError, TypeError):
        return None


def modal_closing_date(text: str) -> Optional[date]:
    """Most frequent date appearing in the same sentence-window as completion language ('consummated ... Business
    Combination', 'Closing Date'); ties go to the earliest. None when no date is found."""
    c: collections.Counter = collections.Counter()
    for m in _CLOSE_CTX.finditer(text):
        s = max(text.rfind(". ", 0, m.start()), m.start() - 250)
        for dm in _DATE.finditer(text[max(0, s): m.end() + 60]):
            d = _parse_dm(dm)
            if d:
                c[d] += 1
    if not c:
        return None
    top = max(c.values())
    return min(d for d, n in c.items() if n == top)


def _in_fiscal_year(d: date, report_date: Optional[str]) -> Optional[bool]:
    """Is ``d`` inside the fiscal year ending ``report_date`` ((FYE-1y, FYE])? None if report_date unusable."""
    fye = parse_date(report_date)
    if fye is None:
        return None
    try:
        start = fye.replace(year=fye.year - 1)
    except ValueError:
        start = fye - timedelta(days=365)
    return start < d <= fye


def detect_filing_entity(text: Optional[str]) -> dict:
    """Entity-type signals of ONE annual report text (pure; no network). Never raises.

    Returns ``{"is_shell", "spac_predecessor", "kind" ('' | 'shell' | 'spac' | 'stub' | 'wrapper'), "signals": [...],
    "reason", "chars", "cover_box", "spac_terms": {...}, "successor_of_spac": bool, "closing_date": iso|None}``.
    Empty/None text -> not flagged (unknown is not "shell").
    """
    out: dict[str, Any] = {"is_shell": False, "spac_predecessor": False, "kind": "", "signals": [], "reason": "",
                           "chars": 0, "cover_box": None, "spac_terms": {}, "successor_of_spac": False, "closing_date": None}
    try:
        if not text:
            return out
        n = len(text)
        out["chars"] = n
        sig: list[str] = []
        box = cover_shell_checkbox(text)
        out["cover_box"] = box
        terms = {"blank_check": len(_BLANK_CHECK.findall(text)), "trust_account": len(_TRUST_ACCT.findall(text)),
                 "initial_business_combination": len(_IBC.findall(text))}
        out["spac_terms"] = terms
        spac_vocab = sum(1 for v in terms.values() if v >= SPAC_TERM_MIN) >= 2
        no_ops = bool(_NO_OPS.search(text))
        spac = spac_vocab and no_ops
        if box is True:
            sig.append("cover shell-company box = Yes")
        if spac:
            sig.append(f"blank-check vocabulary ({terms['blank_check']} 'blank check company', {terms['trust_account']} 'Trust Account', "
                       f"{terms['initial_business_combination']} 'initial business combination') with a no-operations/no-revenue statement")
            if box is False:
                sig.append("contradicts cover box (No)")
        stub = n < STUB_FLOOR_CHARS
        if stub:
            sig.append(f"text only {n:,} characters (< stub floor {STUB_FLOOR_CHARS:,}): placeholder/stub annual report")
        wrapper = (not stub and n < WRAPPER_FLOOR_CHARS and len(_EX13.findall(text)) >= 2 and len(_INCORP.findall(text)) >= 2
                   and not re.search(r"total\s+assets", text, re.I))
        if wrapper:
            sig.append(f"exhibit-only wrapper ({n:,} characters, statements incorporated from Exhibit 13, no balance sheet in text)")
        is_shell = bool(box is True or spac or stub or wrapper)
        if spac or (box is True and spac_vocab):
            kind = "spac"
        elif stub:
            kind = "stub"
        elif wrapper:
            kind = "wrapper"
        else:
            kind = "shell" if box is True else ""
        out.update({"is_shell": is_shell, "spac_predecessor": kind == "spac", "kind": kind, "signals": sig})
        # successor side: this (operating) filing says a SPAC Business Combination closed in ITS fiscal year
        if (not is_shell and len(_CAP_BC.findall(text)) >= SUCCESSOR_MIN_CAP_BC
                and len(_COMPLETION.findall(text)) >= SUCCESSOR_MIN_COMPLETIONS and _SPAC_WORD.search(text)):
            out["successor_of_spac"] = True
            d = modal_closing_date(text)
            out["closing_date"] = d.isoformat() if d else None
        out["reason"] = "; ".join(sig)
    except Exception as exc:  # detection must never break fetch_data
        out["signals"] = [f"detection failed: {type(exc).__name__}: {exc}"]
        out["reason"] = out["signals"][0]
    return out


def compute_filing_entity_flags(texts: dict, filings: dict) -> dict:
    """``{fiscal_year: {"is_shell", "spac_predecessor", "reason", ...detail}}`` for every year with text.

    ``filings`` = {fiscal_year: Filing dict} (for ``report_date``). Adds the successor-side propagation: when year F's
    operating filing reports a SPAC Business Combination closing inside F, year F-1 (if present) gets
    ``spac_predecessor=True`` (it is the SPAC's own report: a different entity before the merger).
    """
    base = {int(y): detect_filing_entity(t) for y, t in (texts or {}).items()}
    flags: dict[int, dict] = {y: dict(r) for y, r in base.items()}
    for y, r in base.items():
        if not r.get("successor_of_spac"):
            continue
        cd = parse_date(r.get("closing_date"))
        inside = _in_fiscal_year(cd, (filings.get(y) or {}).get("report_date")) if cd else None
        if not inside:
            continue  # closing outside this fiscal year (older merger described in a later filing) or undated: ignore
        prev = y - 1
        if prev in flags:
            f = flags[prev]
            note = (f"successor FY{y} 10-K reports the SPAC Business Combination closed {r['closing_date']}: "
                    f"FY{prev} is the SPAC's own pre-merger report")
            f["spac_predecessor"] = True
            f["is_shell"] = True   # a different (pre-merger) entity: unusable as a YoY baseline
            f["kind"] = f.get("kind") or "spac"
            f["signals"] = list(f.get("signals") or []) + [note]
            f["reason"] = "; ".join(f["signals"])
    return {y: {**f} for y, f in sorted(flags.items())}


# --------------------------------------------------------------------------------------- fetch_data helpers
def select_years(filings: list[dict], years: int, end_year: Optional[int], as_of: str) -> dict:
    """Pure selection of fiscal years from the annual filings (all filed <= as_of, amendments already excluded).

    One ORIGINAL (earliest filed) annual report per fiscal year. Returns ``{"error"?, "original": {fy: Filing},
    "end_year", "analysis_years", "baseline_year", "facts_years", "warnings"}``.
    """
    warnings: list[str] = []
    by_fy: dict[int, list[dict]] = {}
    for f in filings:
        fy = f.get("fiscal_year")
        if fy is None:
            warnings.append(f"annual filing {f.get('accession')} ({f.get('form')}, {f.get('filing_date')}) has no report date; skipped")
            continue
        by_fy.setdefault(int(fy), []).append(f)
    original: dict[int, dict] = {}
    for fy, lst in by_fy.items():
        lst = sorted(lst, key=lambda f: (f.get("filing_date") or "", f.get("accession") or ""))
        original[fy] = lst[0]
        if len(lst) > 1:
            warnings.append(f"FY{fy}: {len(lst)} annual filings ({', '.join(x['form'] + ' ' + x['filing_date'] for x in lst)}); "
                            f"using the earliest ({lst[0]['accession']})")
    if not original:
        return {"error": f"no annual filings (10-K/10-K405/10-KSB/20-F/40-F) filed on or before {as_of}",
                "original": {}, "warnings": warnings}
    end = int(end_year) if end_year else max(original)
    if end not in original:
        return {"error": f"no annual filing for FY{end} filed on or before {as_of} (available fiscal years: "
                         f"{sorted(original)})", "original": original, "warnings": warnings}
    n = max(1, int(years))
    wanted = list(range(end - n + 1, end + 1))
    analysis = [y for y in wanted if y in original]
    first = min(original)
    for y in wanted:
        if y not in original and y > first:
            warnings.append(f"FY{y}: no annual filing filed on or before {as_of}; year not analysed")
    if len(analysis) < n:
        warnings.append(f"only {len(analysis)} of {n} requested fiscal years have annual filings as of {as_of}")
    baseline = analysis[0] - 1 if (analysis[0] - 1) in original else None
    facts_years = sorted(set(range(analysis[0] - 1, end + 1)))
    return {"original": original, "end_year": end, "analysis_years": analysis, "baseline_year": baseline,
            "facts_years": facts_years, "warnings": warnings}


def match_proxies(annual: dict[int, dict], proxies: list[dict]) -> dict[int, dict]:
    """Assign each DEF 14A (filed <= as_of) to at most one annual report: window [-90d, +180d] around the annual
    filing date, nearest first (greedy). Returns {fiscal_year: proxy_filing}."""
    pairs = []
    for fy, f in annual.items():
        d0 = parse_date(f.get("filing_date"))
        if d0 is None:
            continue
        for j, p in enumerate(proxies):
            d1 = parse_date(p.get("filing_date"))
            if d1 is None:
                continue
            delta = (d1 - d0).days
            if -PROXY_WINDOW_BEFORE_DAYS <= delta <= PROXY_WINDOW_AFTER_DAYS:
                pairs.append((abs(delta), fy, j))
    pairs.sort()
    out: dict[int, dict] = {}
    used: set[int] = set()
    for _, fy, j in pairs:
        if fy in out or j in used:
            continue
        out[fy] = proxies[j]
        used.add(j)
    return out


def _load_year(fy: int, filing: dict, proxy: Optional[dict]) -> dict:
    """Fetch one annual report's text, build its metadata (using the matched proxy only when audit fees need it)."""
    res: dict[str, Any] = {"fy": fy, "text": None, "meta": None, "warnings": [], "degraded": [], "proxy_used": None}
    try:
        text = edgar_api.fetch_filing_text(filing)
    except Exception as exc:
        msg = f"FY{fy}: could not fetch filing text ({type(exc).__name__}: {exc})"
        res["warnings"].append(msg)
        res["degraded"].append(f"fetch_data: {msg}")
        res["meta"] = text_parser.build_filing_metadata(filing, "")
        return res
    res["text"] = text
    if len(text) < SHORT_TEXT_CHARS:
        res["warnings"].append(f"FY{fy}: annual-report text is only {len(text):,} characters (< {SHORT_TEXT_CHARS:,}); "
                               "likely an abbreviated/shell filing or statements filed in an exhibit - text-based "
                               "signals for this year (and YoY comparisons against it) are unreliable")
    try:
        meta = text_parser.build_filing_metadata(filing, text)
        if meta.get("audit_fees") is None and proxy is not None:
            try:
                ptext = edgar_api.fetch_filing_text(proxy)
                meta2 = text_parser.build_filing_metadata(filing, text, proxy_text=ptext)
                meta = meta2
                meta["proxy_accession"] = proxy.get("accession")
                meta["proxy_filing_date"] = proxy.get("filing_date")
                res["proxy_used"] = {"accession": proxy.get("accession"), "filing_date": proxy.get("filing_date")}
                det = meta.get("audit_fee_detail") or {}
                if meta.get("audit_fees") is not None and det.get("year") not in (None, fy):
                    res["warnings"].append(f"FY{fy}: proxy audit fee refers to FY{det.get('year')}")
            except Exception as exc:
                res["warnings"].append(f"FY{fy}: proxy {proxy.get('accession')} could not be used ({type(exc).__name__}: {exc})")
        res["meta"] = meta
    except Exception as exc:
        res["warnings"].append(f"FY{fy}: build_filing_metadata failed ({type(exc).__name__}: {exc})")
        res["degraded"].append(f"fetch_data: FY{fy} metadata unavailable")
        res["meta"] = {"filing_date": filing.get("filing_date"), "form": filing.get("form"), "accession": filing.get("accession")}
    return res


def _load_texts_and_metadata(selected: dict[int, dict], cik: str, as_of: str) -> dict:
    t0 = time.perf_counter()
    warnings: list[str] = []
    degraded: list[str] = []
    proxies: list[dict] = []
    try:
        proxies = edgar_api.list_filings(cik, "DEF 14A", as_of)
    except Exception as exc:
        warnings.append(f"DEF 14A listing failed ({type(exc).__name__}: {exc}); audit fees only from the annual reports")
    proxy_for = match_proxies(selected, proxies)
    texts: dict[int, str] = {}
    metas: dict[int, dict] = {}
    proxies_used: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=TEXT_WORKERS) as ex:
        futs = {fy: ex.submit(_load_year, fy, f, proxy_for.get(fy)) for fy, f in selected.items()}
        for fy in sorted(futs):
            try:
                r = futs[fy].result()
            except Exception as exc:  # _load_year never raises; defensive
                warnings.append(f"FY{fy}: loader crashed ({type(exc).__name__}: {exc})")
                degraded.append(f"fetch_data: FY{fy} filing text unavailable")
                continue
            if r["text"] is not None:
                texts[fy] = r["text"]
            if r["meta"] is not None:
                metas[fy] = r["meta"]
            if r["proxy_used"]:
                proxies_used[fy] = r["proxy_used"]
            warnings += r["warnings"]
            degraded += r["degraded"]
    return {"texts": texts, "metas": metas, "warnings": warnings, "degraded": degraded,
            "proxies_used": proxies_used, "n_proxies_listed": len(proxies), "seconds": round(time.perf_counter() - t0, 2)}


def _load_facts(cik: str, facts_years: list[int], as_of: str) -> dict:
    t0 = time.perf_counter()
    raw = edgar_api.get_companyfacts(cik)
    annual = xbrl_parser.get_annual_facts(cik, facts_years, as_of=as_of, companyfacts=raw)
    compact = xbrl_parser.compact_companyfacts(raw) if raw else {}
    return {"annual_facts": annual, "xbrl_data": compact, "has_companyfacts": bool(raw),
            "seconds": round(time.perf_counter() - t0, 2)}


def _load_peers(cik: str, sic: str, as_of: str, focus_year: int) -> dict:
    from tools import peer_finder
    t0 = time.perf_counter()
    peers = peer_finder.find_peers(cik, sic or None, as_of, focus_year)
    return {"peers": [dict(p) for p in peers], "reason": getattr(peers, "reason", None),
            "seconds": round(time.perf_counter() - t0, 2)}


_FLAG_STATE_KEYS = ("is_shell", "spac_predecessor", "reason", "kind", "chars", "cover_box", "closing_date")


def _fatal(msg: str, warnings: Optional[list[str]] = None) -> dict:
    return {"error": msg, "warnings": list(warnings or []), "degraded": [f"fetch_data: {msg}"]}


async def _fetch_data_impl(state: dict) -> dict:
    """Heavy node body. Returns a partial state update; a fatal problem is reported via ``error``."""
    t_start = time.perf_counter()
    as_of = state.get("as_of") or date.today().isoformat()
    ticker = state.get("ticker") or ""
    try:
        comp = await asyncio.to_thread(edgar_api.resolve_company, ticker, state.get("cik") or None)
    except Exception as exc:
        return _fatal(f"company not found: {ticker!r} ({type(exc).__name__}: {exc})")
    cik = comp["cik"]
    try:
        annual_filings = await asyncio.to_thread(edgar_api.list_annual_filings, cik, as_of)
    except Exception as exc:
        return _fatal(f"could not list annual filings for CIK {cik}: {type(exc).__name__}: {exc}")
    sel = select_years(annual_filings, state.get("years_requested") or 5, state.get("focus_year") or None, as_of)
    if sel.get("error"):
        return _fatal(sel["error"], sel.get("warnings"))
    original: dict[int, dict] = sel["original"]
    analysis_years = sel["analysis_years"]
    baseline = sel["baseline_year"]
    end = sel["end_year"]
    selected_years = ([baseline] if baseline is not None else []) + analysis_years
    selected = {y: original[y] for y in selected_years}

    warnings: list[str] = list(sel["warnings"])
    degraded: list[str] = []

    facts_t = asyncio.to_thread(_load_facts, cik, sel["facts_years"], as_of)
    texts_t = asyncio.to_thread(_load_texts_and_metadata, selected, cik, as_of)
    peers_t = asyncio.to_thread(_load_peers, cik, comp.get("sic") or "", as_of, end)
    facts_r, texts_r, peers_r = await asyncio.gather(facts_t, texts_t, peers_t, return_exceptions=True)

    update: dict[str, Any] = {}
    info: dict[str, Any] = {"resolved": {k: comp.get(k) for k in ("ticker", "cik", "name", "sic", "sic_description", "fiscal_year_end")},
                            "selected_filings": {y: {k: f.get(k) for k in ("accession", "form", "filing_date", "report_date")}
                                                 for y, f in selected.items()},
                            "baseline_year": baseline, "facts_years": sel["facts_years"]}

    # --- facts
    if isinstance(facts_r, Exception):
        msg = f"annual facts unavailable ({type(facts_r).__name__}: {facts_r})"
        warnings.append(msg)
        degraded.append(f"fetch_data: {msg}")
        update["annual_facts"], update["xbrl_data"] = {}, {}
    else:
        af = facts_r["annual_facts"]
        update["annual_facts"], update["xbrl_data"] = af, facts_r["xbrl_data"]
        warnings += [f"annual_facts: {w}" for w in af.get("warnings", [])]
        info["source_by_year"] = af.get("source_by_year")
        info["facts_seconds"] = facts_r["seconds"]
        info["has_companyfacts"] = facts_r["has_companyfacts"]
        miss_src = [y for y in analysis_years if (af.get("source_by_year") or {}).get(y) in (None, "none")]
        if miss_src:
            degraded.append(f"fetch_data: no financial data extracted for FY{miss_src}")

    # --- texts + metadata
    if isinstance(texts_r, Exception):
        msg = f"filing texts unavailable ({type(texts_r).__name__}: {texts_r})"
        warnings.append(msg)
        degraded.append(f"fetch_data: {msg}")
        update["filing_texts"], update["filing_metadata"] = {}, {}
    else:
        update["filing_texts"], update["filing_metadata"] = texts_r["texts"], texts_r["metas"]
        warnings += texts_r["warnings"]
        degraded += texts_r["degraded"]
        info["proxies_used"] = texts_r["proxies_used"]
        info["n_def14a_listed"] = texts_r["n_proxies_listed"]
        info["texts_seconds"] = texts_r["seconds"]
        # --- v2: shell / SPAC-predecessor / stub detection from the filing text itself (kept in state, never dropped)
        try:
            t_ef = time.perf_counter()
            ef = await asyncio.to_thread(compute_filing_entity_flags, texts_r["texts"], {y: f for y, f in selected.items()})
            update["filing_entity_flags"] = {y: {k: v for k, v in f.items() if k in _FLAG_STATE_KEYS} for y, f in ef.items()}
            flagged = sorted(y for y, f in ef.items() if f.get("is_shell") or f.get("spac_predecessor"))
            for y in flagged:
                f = ef[y]
                role = "baseline year" if y == baseline else ("analysis year" if y in analysis_years else "year")
                warnings.append(f"FY{y} ({role}) flagged {f.get('kind') or 'shell'}{' / SPAC predecessor' if f.get('spac_predecessor') else ''}: "
                                f"{f.get('reason')}. Kept in state for transparency; agents must not use it as a YoY baseline.")
            info["entity_flags_summary"] = {
                "flagged_years": flagged,
                "baseline_year_flagged": bool(baseline is not None and baseline in flagged),
                "first_analysis_year_flagged": bool(analysis_years and analysis_years[0] in flagged),
                "seconds": round(time.perf_counter() - t_ef, 2)}
            if baseline is not None and baseline in flagged:
                warnings.append(f"the baseline year FY{baseline} (YoY baseline of the first analysis year FY{analysis_years[0]}) is a "
                                "shell/SPAC-predecessor/stub filing: first-year YoY signals are not comparable")
        except Exception as exc:  # detection is advisory; never breaks the fetch
            warnings.append(f"entity-flag detection failed ({type(exc).__name__}: {exc})")
            degraded.append("fetch_data: shell/SPAC detection failed")
            update["filing_entity_flags"] = {}

    # --- peers
    if isinstance(peers_r, Exception):
        msg = f"peer discovery failed ({type(peers_r).__name__}: {peers_r})"
        warnings.append(msg)
        degraded.append(f"fetch_data: {msg}")
        update["peer_companies"], update["peer_reason"] = [], msg
    else:
        update["peer_companies"] = peers_r["peers"]
        update["peer_reason"] = peers_r["reason"] or ""
        info["peers_seconds"] = peers_r["seconds"]
        if not peers_r["peers"]:
            why = peers_r["reason"] or "no peers found"
            warnings.append(f"peer discovery returned no peers: {why}")
            degraded.append(f"fetch_data: no peer group ({why})")

    info["fetch_seconds"] = round(time.perf_counter() - t_start, 2)
    update.update({
        "company_name": comp.get("name") or ticker,
        "cik": cik,
        "as_of": as_of,
        "analysis_years": analysis_years,
        "focus_year": end,
        "filings": [original[y] for y in selected_years],
        "fetch_info": info,
        "pipeline_version": PIPELINE_VERSION,
        "warnings": warnings,
        "degraded": degraded,
        "analysis_timestamp": _now_iso(),
        "error": "",
    })
    return update


# --------------------------------------------------------------------------------------- prior-year re-run (v2: Jev material_change)
def _trim_to_year(state: dict, y_end: int) -> dict:
    """Shallow copy of ``state`` restricted to data of fiscal years <= ``y_end`` (no look-ahead in the 'prior-year' snapshot)."""
    def _ykeep(d: Any) -> Any:
        if not isinstance(d, dict):
            return d
        out = {}
        for k, v in d.items():
            try:
                if int(k) > y_end:
                    continue
            except (TypeError, ValueError):
                pass
            out[k] = v
        return out
    s2 = dict(state)
    s2["filing_texts"] = _ykeep(state.get("filing_texts") or {})
    s2["filing_metadata"] = _ykeep(state.get("filing_metadata") or {})
    s2["filings"] = [f for f in (state.get("filings") or []) if (f.get("fiscal_year") is None or int(f["fiscal_year"]) <= y_end)]
    af = state.get("annual_facts")
    if isinstance(af, dict) and af:
        s2["annual_facts"] = {k: (_ykeep(v) if k in ("by_year", "missing", "period_end", "source_by_year") else v) for k, v in af.items()}
    s2["analysis_years"] = sorted(int(y) for y in (state.get("analysis_years") or []) if int(y) <= y_end)
    s2["focus_year"] = y_end
    return s2


def _usable_prior(res: Any) -> bool:
    return isinstance(res, dict) and bool(res) and not res.get("unavailable") and not res.get("error")


def compute_prior_year_results(state: dict, *, timeout_s: float = PRIOR_YEAR_TIMEOUT_S, force: bool = False,
                               on_start: Optional[Callable[[], Any]] = None) -> tuple[dict, dict]:
    """Re-run agents 1-4 (+ temporal) on ``analysis_years[:-1]`` with the SAME already-fetched data (no refetch).

    Returns ``(prior_year_results, info)``; ``info["status"]`` is ``ok | skipped | failed | timeout`` with a ``reason``.
    Optional and failure-tolerant: never raises. Skipped when there is no Jev key (nothing would consume the result;
    ``force=True`` overrides), fewer than 2 analysis years, ``FORENSIC_PRIOR_YEAR=0``, or the prior year is itself a
    flagged shell/SPAC-predecessor/stub year (a material-change question against another entity is meaningless).
    Bounded by ``timeout_s`` of wall time; LLM specificity calls are disk-cached so the language re-run is cheap.
    """
    t0 = time.perf_counter()
    info: dict[str, Any] = {"status": "skipped", "year": None, "agents": [], "seconds": 0.0, "reason": ""}

    def done(status: str, reason: str, res: Optional[dict] = None) -> tuple[dict, dict]:
        info.update({"status": status, "reason": reason, "seconds": round(time.perf_counter() - t0, 2),
                     "agents": sorted(res or {})})
        return (res or {}), info

    try:
        if os.environ.get("FORENSIC_PRIOR_YEAR", "").strip() == "0":
            return done("skipped", "disabled by FORENSIC_PRIOR_YEAR=0")
        ays = sorted(int(y) for y in (state.get("analysis_years") or []))
        if len(ays) < 2:
            return done("skipped", "fewer than 2 analysis years: no prior-year analysis exists")
        py = ays[-2]
        info["year"] = py
        if not force:
            from tools import jev_scorer
            if not jev_scorer.get_api_key():
                return done("skipped", "Jev key not set: nothing would consume prior-year results")
        fl = state.get("filing_entity_flags") or {}
        pf = fl.get(py) or fl.get(str(py)) or {}
        if pf.get("is_shell") or pf.get("spac_predecessor"):
            return done("skipped", f"FY{py} is a flagged shell/SPAC-predecessor/stub filing ({pf.get('kind') or 'shell'}): "
                                   "a year-over-year material-change comparison against it is not meaningful")
        if on_start is not None:
            try:
                on_start()
            except Exception:
                pass
        base = _trim_to_year(state, py)
        from tools.peer_finder import PeerList
        base["peer_companies"] = PeerList(state.get("peer_companies") or [], state.get("peer_reason") or None)
        excluded = get_excluded_flags(state.get("exclude_flags"))
        results: dict[str, dict] = {}
        ex = ThreadPoolExecutor(max_workers=len(AGENT_NODES), thread_name_prefix="prior")
        try:
            futs = {n: ex.submit(globals()[_AGENT_FUNC[n]], dict(base)) for n in AGENT_NODES}
            deadline = t0 + timeout_s
            for n, fut in futs.items():
                try:
                    upd = fut.result(timeout=max(0.1, deadline - time.perf_counter()))
                except FutureTimeout:
                    return done("timeout", f"agent {n} did not finish within {timeout_s:.0f}s", results)
                except Exception as exc:
                    info.setdefault("agent_errors", {})[n] = f"{type(exc).__name__}: {exc}"
                    continue
                r = upd.get(f"{n}_result") if isinstance(upd, dict) else None
                if _usable_prior(r):
                    results[n] = apply_exclusions(r, excluded) if excluded else r
                else:
                    info.setdefault("agent_errors", {})[n] = "unavailable prior-year result"
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        if results:
            try:
                tstate = dict(base)
                for n, r in results.items():
                    tstate[f"{n}_result"] = r
                tr = run_temporal(tstate)
                t_res = tr.get("temporal_result") if isinstance(tr, dict) else None
                if _usable_prior(t_res):
                    results["temporal"] = t_res
            except Exception as exc:
                info.setdefault("agent_errors", {})["temporal"] = f"{type(exc).__name__}: {exc}"
        if not results:
            return done("failed", "no agent produced a usable prior-year result")
        return done("ok", f"prior-year results for FY{py} from {len(results)} agents on the already-fetched data", results)
    except Exception as exc:  # optional step: never break the run
        return done("failed", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------------------- nodes
async def fetch_data(state: ForensicAgentState, config: RunnableConfig) -> dict:
    ctx = _ctx_of(config)
    _emit(ctx, "fetch_data", "start")
    t_start = time.time()
    try:
        upd = await _fetch_data_impl(state)  # module-level name resolved at call time (patchable in tests)
        status = "error" if upd.get("error") else "done"
        detail = upd.get("error") or f"{len(upd.get('analysis_years', []))} fiscal years, {len(upd.get('filing_texts', {}))} texts, {len(upd.get('peer_companies', []))} peers"
        _fl = ((upd.get("fetch_info") or {}).get("entity_flags_summary") or {}).get("flagged_years")
        if _fl and not upd.get("error"):
            detail += f"; shell/SPAC/stub-flagged years: {_fl}"
    except Exception as exc:  # defensive: a bug here becomes a clean fatal error, not a crash
        log.exception("fetch_data failed")
        msg = f"fetch_data crashed: {type(exc).__name__}: {exc}"
        upd, status, detail = _fatal(msg), "error", msg
    t_end = time.time()
    upd = dict(upd)
    upd["agent_trace"] = [{"agent": "fetch_data", "status": "error" if upd.get("error") else "ok",
                           "started": datetime.fromtimestamp(t_start, timezone.utc).isoformat(),
                           "duration_ms": int((t_end - t_start) * 1000), "summary": detail,
                           "degraded": list(upd.get("degraded", []))}]
    upd["node_timings"] = [_timing("fetch_data", t_start, t_end)]
    _emit(ctx, "fetch_data", status, detail)
    return upd


def _make_agent_node(name: str) -> Callable:
    key = f"{name}_result"

    async def node(state: ForensicAgentState, config: RunnableConfig) -> dict:
        ctx = _ctx_of(config)
        _emit(ctx, name, "start")
        t_start = time.time()
        fn = globals()[_AGENT_FUNC[name]]
        raised: Optional[str] = None
        try:
            agent_state = state
            if name == "peer":  # checkpointing turns PeerList into a plain list: restore .reason for the agent
                from tools.peer_finder import PeerList
                agent_state = {**state, "peer_companies": PeerList(state.get("peer_companies") or [], state.get("peer_reason") or None)}
            upd = await asyncio.to_thread(fn, agent_state)
            if not isinstance(upd, dict) or not isinstance(upd.get(key), dict):
                raise TypeError(f"{_AGENT_FUNC[name]} returned no {key!r} dict")
            upd = dict(upd)
        except Exception as exc:
            raised = f"{type(exc).__name__}: {exc}"
            log.warning("%s node failed: %s", name, raised)
            res = _unavailable_agent_result(name, raised, state.get("focus_year"))
            upd = {key: res, "degraded": list(res["degraded"]),
                   "agent_trace": [{"agent": name, "status": "error", "started": datetime.fromtimestamp(t_start, timezone.utc).isoformat(),
                                    "duration_ms": int((time.time() - t_start) * 1000), "summary": raised,
                                    "degraded": list(res["degraded"])}]}
        # flag exclusion (identity when nothing is excluded)
        excluded = get_excluded_flags(state.get("exclude_flags"))
        if excluded:
            filtered = apply_exclusions(upd[key], excluded)
            if filtered is not upd[key]:
                upd["warnings"] = list(upd.get("warnings", [])) + [
                    f"{name}: excluded flags removed from results: {filtered.get('removed_flags')} "
                    f"(severity {filtered.get('severity_before_exclusion')} -> {filtered.get('severity')})"]
                upd[key] = filtered
        t_end = time.time()
        upd["node_timings"] = [_timing(name, t_start, t_end)]
        res = upd[key]
        _emit(ctx, name, "error" if raised else "done", raised or res.get("key_finding"))
        return upd

    node.__name__ = f"run_{name}_node"
    return node


async def run_temporal_node(state: ForensicAgentState, config: RunnableConfig) -> dict:
    ctx = _ctx_of(config)
    _emit(ctx, "temporal", "start")
    t_start = time.time()
    raised = None
    try:
        upd = dict(await asyncio.to_thread(run_temporal, state))
    except Exception as exc:
        raised = f"{type(exc).__name__}: {exc}"
        res = _unavailable_agent_result("temporal", raised, state.get("focus_year"))
        res.update({"timeline": [], "first_detection_year": None, "first_detection_filing_date": None,
                    "signal_trajectory": "Unknown", "years_of_elevated_risk": 0})
        upd = {"temporal_result": res, "forensic_timeline": [], "suspicion_score": 0, "first_detection_year": None,
               "first_detection_filing_date": None, "degraded": list(res["degraded"]),
               "agent_trace": [{"agent": "temporal", "status": "error", "started": datetime.fromtimestamp(t_start, timezone.utc).isoformat(),
                                "duration_ms": int((time.time() - t_start) * 1000), "summary": raised, "degraded": list(res["degraded"])}]}
    t_end = time.time()
    upd["node_timings"] = [_timing("temporal", t_start, t_end)]
    _emit(ctx, "temporal", "error" if raised else "done", raised or (upd.get("temporal_result") or {}).get("key_finding"))
    return upd


async def run_synthesis_node(state: ForensicAgentState, config: RunnableConfig) -> dict:
    ctx = _ctx_of(config)
    _emit(ctx, "synthesis", "start")
    t_start = time.time()

    def sub_event(ev: dict) -> None:  # called from the worker thread by agents.synthesis_agent
        if not isinstance(ev, dict):
            return
        if ev.get("status") == "jev":
            _emit_threadsafe(ctx, "jev", "jev")
        # synthesis' own "done" event is replaced by the node-level event below

    # v2: optional prior-year baseline for Jev material_change (never breaks the run, bounded in time)
    prior: dict = {}
    pinfo: dict = {"status": "skipped", "reason": "not computed"}
    prior_trace: Optional[dict] = None
    if not state.get("prior_year_results"):
        t_p = time.time()
        try:   # events are emitted only when the step really runs (skips are silent: they stay in prior_year_info/trace)
            prior, pinfo = await asyncio.wait_for(
                asyncio.to_thread(compute_prior_year_results, dict(state),
                                  on_start=lambda: _emit_threadsafe(ctx, "prior_year", "start")),
                timeout=PRIOR_YEAR_TIMEOUT_S + 10)
        except Exception as exc:
            prior, pinfo = {}, {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        if pinfo.get("status") != "skipped":
            _emit(ctx, "prior_year", "done", f"{pinfo.get('status')}: {pinfo.get('reason')}")
        prior_trace = {"agent": "prior_year", "status": "ok" if pinfo.get("status") == "ok" else pinfo.get("status", "skipped"),
                       "started": datetime.fromtimestamp(t_p, timezone.utc).isoformat(),
                       "duration_ms": int((time.time() - t_p) * 1000), "summary": pinfo.get("reason", ""), "degraded": []}
    else:
        prior, pinfo = state["prior_year_results"], {"status": "ok", "reason": "supplied by caller"}
    synth_state = {**state, "prior_year_results": prior} if prior else state
    upd = dict(await asyncio.to_thread(run_synthesis, synth_state, sub_event))
    upd["prior_year_info"] = pinfo
    if prior:
        upd["prior_year_results"] = prior
    if prior_trace is not None:
        upd["agent_trace"] = list(upd.get("agent_trace") or []) + [prior_trace]
        if pinfo.get("status") in ("failed", "timeout"):
            upd["degraded"] = list(upd.get("degraded") or []) + [
                f"prior_year_results: {pinfo.get('status')}: {pinfo.get('reason')} (Jev material_change unavailable)"]
    t_end = time.time()
    upd["node_timings"] = [_timing("synthesis", t_start, t_end)]
    failed = bool(upd.get("error")) or upd.get("risk_grade") == "Unknown"
    _emit(ctx, "synthesis", "error" if failed else "done", upd.get("error") or upd.get("grade_rationale"))
    return upd


async def handle_error(state: ForensicAgentState, config: RunnableConfig) -> dict:
    err = state.get("error") or "unknown error"
    t = time.time()
    msg = f"Analysis could not be completed: {err}"
    return {
        "risk_grade": "Unknown",
        "grade_rationale": msg,
        "smoking_guns": [], "smoking_gun_evidence": [], "forensic_timeline": [],
        "final_narrative": msg + " No risk grade was assigned (Unknown is an error state, not Low).",
        "agent_severity": {}, "grade_inputs": {}, "jev_scores": {}, "jev_available": False, "suspicion_score": 0,
        "first_detection_year": None, "first_detection_filing_date": None, "risk_changed": False,
        "degraded": [f"pipeline: {err}"],
        "agent_trace": [{"agent": "handle_error", "status": "error", "started": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                         "duration_ms": 0, "summary": err, "degraded": [f"pipeline: {err}"]}],
        "node_timings": [_timing("handle_error", t, t)],
    }


def _route_after_fetch(state: ForensicAgentState):
    if state.get("error"):
        return "handle_error"
    return [f"run_{n}" for n in AGENT_NODES]


# --------------------------------------------------------------------------------------- graph
pipeline = StateGraph(ForensicAgentState)
pipeline.add_node("fetch_data", fetch_data)
for _n in AGENT_NODES:
    pipeline.add_node(f"run_{_n}", _make_agent_node(_n))
pipeline.add_node("run_temporal", run_temporal_node)
pipeline.add_node("run_synthesis", run_synthesis_node)
pipeline.add_node("handle_error", handle_error)
pipeline.add_edge(START, "fetch_data")
pipeline.add_conditional_edges("fetch_data", _route_after_fetch,
                               ["handle_error"] + [f"run_{n}" for n in AGENT_NODES])
pipeline.add_edge([f"run_{n}" for n in AGENT_NODES], "run_temporal")   # fan-in: waits for all four
pipeline.add_edge("run_temporal", "run_synthesis")
pipeline.add_edge("run_synthesis", END)
pipeline.add_edge("handle_error", END)

forensic_agent = pipeline.compile(checkpointer=_CHECKPOINTER)


# --------------------------------------------------------------------------------------- public API
async def analyze_company(
    ticker: str,
    years: int = 5,
    *,
    cik: Optional[str] = None,
    end_year: Optional[int] = None,
    as_of: Optional[str] = None,
    thread_id: Optional[str] = None,
    progress_callback: Optional[Callable[[dict], Any]] = None,
    previous_risk_grade: Optional[str] = None,
    watchlist_id: Optional[str] = None,
    exclude_flags: Optional[Any] = None,
) -> ForensicAgentState:
    """Run the full pipeline and return the final state.

    ``as_of`` (ISO date) = point-in-time information set (default: today). ``end_year`` = last fiscal year analysed
    (default: newest annual report filed <= as_of). Delisted tickers need ``cik=``. ``exclude_flags`` (list or
    comma string; ``None`` -> env ``FORENSIC_EXCLUDE_FLAGS``) removes flags from agents 1-4 (see tools.config).
    A fatal data problem returns a state with ``error`` set and ``risk_grade == "Unknown"``. Never raises for
    data problems. If ``thread_id`` is omitted a fresh one is used and its checkpoints are dropped afterwards.
    """
    load_env()
    t0 = time.perf_counter()
    excluded = get_excluded_flags(exclude_flags)
    state = new_state(ticker, years, cik=cik, end_year=end_year, as_of=as_of or date.today().isoformat(),
                      previous_risk_grade=previous_risk_grade, watchlist_id=watchlist_id)
    state["exclude_flags"] = excluded
    unprop = unpropagated_flags(excluded)
    if unprop:
        state["warnings"] = list(state["warnings"]) + [
            f"exclude_flags {unprop} are re-derived by the temporal agent from structured fields; "
            "the exclusion is NOT propagated to the temporal score for them"]
    own_thread = thread_id is None
    tid = thread_id or f"{state['ticker']}-{uuid.uuid4().hex[:10]}"
    ctx = _Ctx(progress_callback, asyncio.get_running_loop())
    with _CTX_LOCK:
        _CTX[tid] = ctx
    try:
        try:
            final = await forensic_agent.ainvoke(state, config={"configurable": {"thread_id": tid}})
            final = dict(final)
        except Exception as exc:  # graph-level crash: still return a well-formed error state
            log.exception("pipeline crashed")
            msg = f"pipeline crashed: {type(exc).__name__}: {exc}"
            final = dict(state)
            final.update({"error": msg, "risk_grade": "Unknown", "grade_rationale": msg, "final_narrative": msg,
                          "degraded": list(state.get("degraded", [])) + [f"pipeline: {msg}"]})
            _emit(ctx, "pipeline", "error", msg, message=msg)
    finally:
        with _CTX_LOCK:
            _CTX.pop(tid, None)
        if own_thread:
            try:
                _CHECKPOINTER.delete_thread(tid)
            except Exception:
                pass
    final["degraded"] = list(dict.fromkeys(final.get("degraded") or []))
    final["warnings"] = list(dict.fromkeys(final.get("warnings") or []))
    final["total_ms"] = int((time.perf_counter() - t0) * 1000)
    return final  # type: ignore[return-value]


def analyze_company_sync(*args: Any, **kwargs: Any) -> ForensicAgentState:
    """Blocking convenience wrapper around :func:`analyze_company` (safe inside a running event loop too)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(analyze_company(*args, **kwargs))
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["r"] = asyncio.run(analyze_company(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    th = threading.Thread(target=runner, daemon=True)
    th.start()
    th.join()
    if "e" in box:
        raise box["e"]
    return box["r"]
