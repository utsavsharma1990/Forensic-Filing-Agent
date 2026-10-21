"""Agent 3 - Network forensics (deterministic, no LLM).

``run_network(state) -> dict`` is a synchronous, never-raising LangGraph node.  It reads ONLY raw state
fields (``filing_metadata``, ``filing_texts``, ``analysis_years``, optional ``annual_facts``) and returns
``{"network_result": {...}, "agent_trace": [...], "degraded": [...]}``.

Rules (fixed before any evaluation; see docs/CONTRACTS.md section 4)
--------------------------------------------------------------------
* Auditor change (``network.auditor_change``): audit *network* differs from the most recent earlier year
  with a known auditor (``tools.text_parser.auditor_changed``: legal-form / rebranding / member-firm
  differences such as "PricewaterhouseCoopers" vs "PricewaterhouseCoopers LLP" are NOT changes).  An
  unknown auditor in a year is "unknown", never "changed"; a single unknown year between two known ones is
  bridged (the comparison is made across the gap and the gap is noted).  The first analysed year is
  compared with the nearest earlier year in ``filing_metadata`` if one exists (the pipeline fetches one
  extra year), otherwise ``changed=False`` / status ``first_year`` (nothing to compare, not "unavailable").
* CFO change (``network.cfo_change``) / CEO change (``network.ceo_change``): the signing CFO/CEO differs
  (``same_person``) from the most recent earlier year with a known, full (>= 2 tokens) name.  Unknown names
  are never changes.  CEO change is recorded and flagged but has weight 0 in the temporal score.
* v2 context rules (docs/V2_CHANGELOG_text_network.md):
  - SHELL / SPAC predecessor years (``state["filing_entity_flags"][year] = {"is_shell", "spac_predecessor", "reason"}`` from the
    pipeline; if absent for a year, ``tools.text_parser.detect_shell_filing`` on that year's text) are NEVER a baseline for
    the auditor / CEO / CFO / related-party comparisons: the first operating year after a shell has status ``first_year`` (baseline
    unknown), the shell year itself is recorded with status ``shell`` and no change flags, and a going-concern doubt in a shell
    year (SPAC mandatory-liquidation language) is recorded with ``context: shell`` but not flagged.
  - MERGER context: an auditor / CEO / CFO change whose evidence text (windows around the new and the previous name) shows a
    business combination ("prior to the Business Combination", "Legacy <Company>'s Chief Financial Officer", "pre-merger special
    purpose acquisition company") is RECORDED (``observed_change``, ``context: "merger"``) but is not a counted change: ``changed``
    stays False, no flag, no severity, no hard "auditor + CFO" combination.
* Audit fees (``network.audit_fees``): fees up MORE than 30% vs the immediately preceding fiscal year
  WITHOUT corresponding revenue growth.  "Corresponding" is defined precisely as
  ``revenue_growth >= fee_growth / 2`` (revenue growth at least half as fast as the fee growth explains it).
  The flag fires when ``fee_growth > 30%`` and ``revenue_growth < fee_growth / 2``.  If revenue is not
  available for the pair, the flag fires on fees alone with ``confidence="low"`` (stated in the evidence).
  Both years' fees must be present and consecutive; fees of different years of a proxy are never mixed.
* Restatement (``network.restatement``): fires for a REPORTED restatement of previously issued financial
  statements / non-reliance / Item 4.02 (``detect_restatement``: kinds ``non_reliance`` and ``restated_previously_issued``;
  "Amended and Restated" agreements, accounting-standard recasts and hypothetical risk-factor language are not) OR a
  REPORTED material weakness (``detect_material_weakness``: management's / the auditor's conclusion language - "we identified a
  material weakness", ICFR "was not effective", adverse ICFR opinion).  Forward-looking boilerplate ("our ability to remediate
  material weaknesses"), the auditor-report definition and remediated / prior-period history (recorded under
  ``remediated_*`` keys) do NOT fire.  Significant-deficiency-only text is recorded (``significant_deficiency_detected``) but
  NOT flagged.  The evidence excerpt is taken from Item 9A / the filing body in preference to the forward-looking preface or
  risk factors, and the result says which section and how far into the document it is (B12).
* Related-party growth (``network.related_party``): ``related_party_chars`` grew by more than 50% YoY AND the current size
  is at least 3,000 characters (about a page: below that the change is wording noise).  v2 (B9): the two years must be measured
  on the SAME source (``related_party_source`` = ``note`` | ``item13``; a ``pointer`` - Item 13 merely incorporating the proxy by
  reference - is not a disclosure size).  Different sources between the years, or a pointer, give status ``source_mismatch`` /
  ``pointer`` and growth ``None`` (unavailable), never a percentage.  A prior year with 0 characters means "section not found"
  (could be an extraction miss), so growth is undefined: recorded as ``new_disclosure`` but NOT flagged.
* Going concern (``network.going_concern``): ``detect_going_concern`` (substantial doubt wording, negation
  aware).

Hard flags / severity follow CONTRACTS section 4 (focus-year flags only).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from tools import text_parser as tp
from tools.common import get_logger

log = get_logger("network_agent")

AGENT = "network"

# ---- fixed thresholds -------------------------------------------------------------------
FEE_GROWTH_THRESHOLD = 0.30        # fees up more than 30% YoY ...
REVENUE_COVERAGE_RATIO = 0.5       # ... unless revenue growth >= fee_growth * 0.5
RPT_GROWTH_THRESHOLD = 0.50        # related-party section grew more than 50% YoY ...
RPT_MIN_CHARS = 3000               # ... and is at least this large (characters)
FEE_IMPLAUSIBLE_RATIO = 10.0       # a >10x (or <0.1x) fee jump is treated as a unit-parse error, not a signal
EXCERPT_CHARS = 320

FLAG_AUDITOR = "network.auditor_change"
FLAG_CFO = "network.cfo_change"
FLAG_CEO = "network.ceo_change"
FLAG_FEES = "network.audit_fees"
FLAG_RESTATE = "network.restatement"
FLAG_RPT = "network.related_party"
FLAG_GC = "network.going_concern"
HARD_FLAGS = {FLAG_RESTATE, FLAG_GC}

# order used to pick the key finding (most serious first)
_KEY_ORDER = [FLAG_GC, FLAG_RESTATE, "auditor+cfo", FLAG_AUDITOR, FLAG_CFO, FLAG_FEES, FLAG_RPT, FLAG_CEO]

_NUM_RX = re.compile(r"\d[\d,]*(?:\.\d+)?")


# ---- helpers ------------------------------------------------------------------------------
def _intkey(k: Any) -> Optional[int]:
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _int_dict(d: Any) -> dict[int, Any]:
    out: dict[int, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            ik = _intkey(k)
            if ik is not None:
                out[ik] = v
    return out


def _numbers_in(text: str) -> list[float]:
    nums: list[float] = []
    for m in _NUM_RX.finditer(text or ""):
        try:
            nums.append(float(m.group(0).replace(",", "").rstrip(".")))
        except ValueError:
            continue
    return nums


def _clean_str(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = re.sub(r"\s+", " ", v).strip()
    return s or None


def _strip_repeated_tail(s: str) -> str:
    """Drop a signature-block artefact where the leading name is repeated at the end
    ("Timothy D. Cook TIMOTHY D." -> "Timothy D. Cook")."""
    toks = s.split()
    for k in range(1, len(toks) // 2 + 1):
        head = [t.lower().strip(".,") for t in toks[:k]]
        tail = [t.lower().strip(".,") for t in toks[-k:]]
        if head == tail and len(toks) - k >= 2:
            return " ".join(toks[:-k])
    return s


def _alnum(s: str) -> str:
    """Letters only, lower case: equal for 'M. Arc D. H. Amburg' vs 'Marc D. Hamburg' (space-split artefacts)."""
    return re.sub(r"[^a-z]", "", s.lower())


def _full_name(v: Any) -> Optional[str]:
    """A person name usable for change detection (at least first + last token), else None."""
    s = _clean_str(v)
    if not s:
        return None
    s = _strip_repeated_tail(s)
    return s if tp.normalize_person_name(s) and " " in (tp.normalize_person_name(s) or "") else None


def _firm_ok(v: Any) -> Optional[str]:
    s = _clean_str(v)
    if not s:
        return None
    return s if tp.normalize_firm_name(s) and tp.firm_network(s) else None


def _revenue_by_year(annual_facts: Any) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(annual_facts, dict):
        return out
    by_year = _int_dict(annual_facts.get("by_year"))
    for y, items in by_year.items():
        if not isinstance(items, dict):
            continue
        rev = items.get("Revenue")
        val = rev.get("value") if isinstance(rev, dict) else rev
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val == val and abs(val) != float("inf"):
            out[y] = float(val)
    return out


# A restatement hit counts when text_parser classified it as a REPORTED restatement (``non_reliance`` or
# ``restated_previously_issued``) and it is not an accounting-standard adoption recast, an exhibit-list title
# ("Amendment and Restatement of ... Plan") or a mere "assessing" remark.  (v1 additionally required an error cue inside the
# excerpt; the kind classification in text_parser now carries that distinction, so "restated previously issued financial
# statements" counts without the word "error" - B1.)
_RESTATE_REJECT = re.compile(r"amendment\s+and\s+restatement|exhibit|incorporated\s+by\s+reference|adoption\s+of|adopt\s+the\s+standard|"
                             r"full\s+retrospective|modified\s+retrospective|accounting\s+standards?\s+update|\bASU\b|retroactive\s+restatement\s+methodology", re.I)
# the sentence in ASU 2014-15 summaries ("requires management to evaluate ... substantial doubt") is not a doubt
_GC_REJECT = re.compile(r"requires?\s+management\s+to\s+evaluate|for\s+each\s+annual\s+and\s+interim\s+reporting\s+period", re.I)
_REPORTED_RESTATE_KINDS = {"non_reliance", "restated_previously_issued"}


def _error_restatement_hits(hits: list[dict]) -> list[dict]:
    out = []
    for h in hits:
        ex = h.get("excerpt") or ""
        kind = h.get("kind")
        if kind is not None and kind not in _REPORTED_RESTATE_KINDS:
            continue
        if _RESTATE_REJECT.search(ex) and not re.search(r"\bnon-?reliance\b|item\s+4\.02|should\s+(?:no\s+longer\s+|not\s+)be\s+relied", ex, re.I):
            continue
        out.append(h)
    return out


def _real_going_concern_hits(hits: list[dict]) -> list[dict]:
    return [h for h in hits if not _GC_REJECT.search(h.get("excerpt") or "")]


_SECTION_LABEL = {"item9a": "Item 9A controls section", "body": "filing body", "risk_factors": "risk factors",
                  "preface": "forward-looking / explanatory preface"}


def _where(hit: dict) -> str:
    """'Item 9A controls section, ~66% into the document' (B12: say where the excerpt comes from)."""
    sec = hit.get("section")
    pct = hit.get("pct_of_document")
    if not sec:
        return ""
    lab = _SECTION_LABEL.get(sec, sec)
    return f"{lab}, ~{pct:.0f}% into the document" if isinstance(pct, (int, float)) else lab


def _excerpt(hits: list[dict]) -> str:
    if not hits:
        return ""
    ex = (_clean_str(hits[0].get("excerpt")) or "").replace("\ufffd", "")
    return trim_excerpt(ex, EXCERPT_CHARS, cut_start=(hits[0].get("start", 1) or 0) > 0)


def trim_excerpt(ex: str, max_chars: int, cut_start: bool = True) -> str:
    """Trim a raw text window to whole words with "..." markers.

    ``cut_start``: the window may begin mid-word (hit not at document start), so the first token is dropped and a
    leading "..." added.  The tail is cut back to the last whole word when the window is over ``max_chars`` or does
    not end at sentence punctuation; a trailing "..." marks the cut.
    """
    ex = " ".join((ex or "").split())
    if not ex:
        return ""
    lead = ""
    if cut_start and " " in ex:
        ex = ex.split(" ", 1)[1].lstrip()
        lead = "… "
    tail = ""
    if len(ex) > max_chars:
        ex = ex[:max_chars]
        ex = ex.rsplit(" ", 1)[0] if " " in ex else ex
        tail = " …"
    elif ex and ex[-1] not in ".!?\"')" and " " in ex:
        ex = ex.rsplit(" ", 1)[0]
        tail = " …"
    ex = ex.rstrip(" ,;:-")
    return f"{lead}{ex}{tail}" if ex else ""


def _fmt_money(x: float) -> str:
    return f"{x:,.0f}"


# ---- entity / merger context (B10) ---------------------------------------------------------
def _entity_context(years: list[int], texts: dict[int, Any], flags_in: dict[int, Any]) -> dict[int, dict]:
    """Per year: is the filing a shell / SPAC predecessor's own annual report?  The pipeline's
    ``filing_entity_flags`` wins; a year without flags is judged from its text (``detect_shell_filing``)."""
    out: dict[int, dict] = {}
    for y in years:
        f = flags_in.get(y)
        if isinstance(f, dict) and ("is_shell" in f or "spac_predecessor" in f):
            sh = bool(f.get("is_shell") or f.get("spac_predecessor"))
            out[y] = {"is_shell": sh, "source": "state", "reason": _clean_str(f.get("reason")) or ("shell / SPAC predecessor" if sh else "")}
            continue
        txt = texts.get(y)
        if isinstance(txt, str) and txt.strip():
            try:
                det = tp.detect_shell_filing(txt)
            except Exception:  # pragma: no cover - parser never raises
                det = {"is_shell": False, "cues": []}
            out[y] = {"is_shell": bool(det.get("is_shell")), "source": "text",
                      "reason": ("blank-check / SPAC self-description: " + "; ".join(det.get("cues", []))) if det.get("is_shell") else ""}
        else:
            out[y] = {"is_shell": False, "source": None, "reason": ""}
    return out


def _merger_evidence(text: Any, needles: list[str], radius: int = 600, cap: int = 40) -> dict[str, Any]:
    """Merger / business-combination language in windows around the names involved in a change (the new and the previous
    auditor / executive).  Local windows, not the whole filing, so a later-year 10-K that merely retells the SPAC history does
    not blanket-suppress an unrelated change."""
    if not isinstance(text, str) or not text.strip():
        return {"detected": False, "cues": [], "excerpt": ""}
    t = tp._prepare(text)
    wins: list[str] = []
    for nd in needles:
        nd = (nd or "").strip()
        if len(nd) < 4:
            continue
        for m in re.finditer(re.escape(nd), t, re.I):
            wins.append(t[max(0, m.start() - radius): m.end() + radius])
            if len(wins) >= cap:
                break
    if not wins:
        return {"detected": False, "cues": [], "excerpt": ""}
    return tp.detect_merger_context("\n".join(wins))


def _name_needles(name: Optional[str], is_firm: bool) -> list[str]:
    if not name:
        return []
    if is_firm:
        norm = tp.normalize_firm_name(name) or name
        first = re.split(r"[\s,&]+", norm.strip())[0]
        return [norm, first]
    toks = [t for t in re.split(r"\s+", name.strip()) if len(t.strip(".")) > 2]
    return [name.strip()] + ([toks[-1].strip(".,")] if toks else [])


def _empty_result(reason: str, focus_year: Optional[int] = None) -> dict[str, Any]:
    return {
        "error": reason,
        "unavailable": True,
        "severity": "None",
        "flags_fired": 0,
        "flags_by_year": {},
        "focus_year": focus_year,
        "key_finding": f"Network forensics unavailable: {reason}",
        "data_quality": {"unavailable": {"network": reason}},
        "degraded": [f"network: {reason}"],
        "evidence": [],
        "auditor_history": {},
        "executive_changes": {},
        "audit_fees": {},
        "restatements": {},
        "related_party_flags": {},
        "going_concern": {},
        "entity_context": {},
        "merger_context_changes": {},
    }


# ---- core analysis -----------------------------------------------------------------------
def _analyse(state: dict) -> dict[str, Any]:
    meta_all = _int_dict(state.get("filing_metadata"))
    texts = _int_dict(state.get("filing_texts"))
    years_in = sorted({y for y in (_intkey(v) for v in (state.get("analysis_years") or [])) if y is not None})
    if not years_in:
        years_in = sorted(meta_all)
    if not years_in:
        return _empty_result("no analysis years / filing metadata in state")
    focus_year = _intkey(state.get("focus_year")) or years_in[-1]
    revenue = _revenue_by_year(state.get("annual_facts"))
    revenue_available = bool(revenue)

    # baseline years: metadata years before the first analysed year (used only as comparison anchors)
    baseline_years = sorted(y for y in meta_all if y < years_in[0])
    obs_years = baseline_years + years_in

    unavailable: dict[str, str] = {}
    degraded: list[str] = []
    evidence: list[dict] = []
    flags_by_year: dict[int, list[str]] = {y: [] for y in years_in}

    auditor_history: dict[int, dict] = {}
    executive_changes: dict[int, dict] = {}
    audit_fees: dict[int, dict] = {}
    restatements: dict[int, dict] = {}
    related_party_flags: dict[int, dict] = {}
    going_concern: dict[int, dict] = {}

    def add_flag(year: int, flag: str, metric: str, value: Any, display: str) -> None:
        if flag not in flags_by_year[year]:
            flags_by_year[year].append(flag)
        evidence.append({"flag": flag, "year": year, "metric": metric, "value": value,
                         "display": display, "numbers": _numbers_in(display)})

    # --- entity context: shell / SPAC predecessor years are never a comparison baseline (B10) -----------
    entity = _entity_context(obs_years, texts, _int_dict(state.get("filing_entity_flags")))
    shell_years = sorted(y for y, e in entity.items() if e["is_shell"])
    entity_context: dict[int, dict] = {y: e for y, e in entity.items() if e["is_shell"]}
    merger_changes: dict[int, list[dict]] = {}
    doc_merger: dict[int, dict] = {}

    def merger_check(y: int, kind: str, prev_name: Optional[str], cur_name: Optional[str]) -> Optional[dict]:
        """Is the change observed in year *y* explained by a business combination described in the filing itself?"""
        is_firm = kind == "auditor"
        ev = _merger_evidence(texts.get(y), _name_needles(prev_name, is_firm) + _name_needles(cur_name, is_firm))
        if ev.get("detected"):
            return {**ev, "scope": "near_names"}
        # whole-document context: the filing itself says the combination closed in this fiscal year (or just after it)
        if y not in doc_merger:
            txt = texts.get(y)
            doc_merger[y] = tp.detect_merger_context(txt) if isinstance(txt, str) and txt.strip() else {"detected": False}
        dm = doc_merger[y]
        if dm.get("detected") and dm.get("closing_year") in (y, y + 1):
            return {**dm, "scope": f"document (combination closed {dm.get('closing_year')})"}
        return None

    def note_merger_change(y: int, kind: str, prev_name: Any, cur_name: Any, ev: dict) -> None:
        merger_changes.setdefault(y, []).append({"kind": kind, "from": prev_name, "to": cur_name, "cues": ev.get("cues", []),
                                                 "scope": ev.get("scope"), "excerpt": ev.get("excerpt", "")})

    # --- auditor & executives (walk forward with "last known" anchors) -------------------
    last_aud: Optional[tuple[int, str]] = None
    last_cfo: Optional[tuple[int, str]] = None
    last_ceo: Optional[tuple[int, str]] = None
    after_shell: Optional[int] = None      # most recent shell year that reset the anchors
    for y in obs_years:
        md = meta_all.get(y) or {}
        in_scope = y in flags_by_year
        aud = _firm_ok(md.get("auditor"))
        cfo = _full_name(md.get("cfo"))
        ceo = _full_name(md.get("ceo"))
        had_meta = y in meta_all and isinstance(md, dict) and bool(md)
        is_shell = entity.get(y, {}).get("is_shell", False)

        if is_shell:
            # the shell's own report: record who signed, never compare, never use as a later baseline
            last_aud = last_cfo = last_ceo = None
            after_shell = y
            why = entity[y].get("reason") or "shell / SPAC predecessor filing"
            if in_scope:
                auditor_history[y] = {"name": tp.normalize_firm_name(aud) if aud else None, "changed": False, "status": "shell",
                                      "compared_to": None, "gap_years": 0, "context": "shell",
                                      "note": f"shell / SPAC predecessor year ({why}); not a baseline for any comparison"}
                executive_changes[y] = {"cfo": cfo, "ceo": ceo, "cfo_changed": False, "ceo_changed": False,
                                        "cfo_status": "shell", "ceo_status": "shell", "context": "shell",
                                        "note": f"shell / SPAC predecessor year ({why}); not a baseline for any comparison"}
            continue

        # auditor
        rec: dict[str, Any] = {"name": tp.normalize_firm_name(aud) if aud else None, "changed": False,
                               "status": "unknown", "compared_to": None, "gap_years": 0}
        if aud is None:
            rec["status"] = "unknown"
            rec["note"] = ("no filing metadata for this year" if not had_meta
                           else "auditor not extracted from the filing; never treated as a change")
            if in_scope:
                unavailable[f"auditor_FY{y}"] = rec["note"]
        elif last_aud is None:
            rec["status"] = "first_year" if y == obs_years[0] or in_scope and y == years_in[0] or after_shell is not None else "first_known"
            rec["note"] = ("baseline unknown: the earlier year(s) were a shell / SPAC predecessor" if after_shell is not None
                           else "no earlier auditor on record to compare with; changed=False")
        else:
            py, pname = last_aud
            ch = tp.auditor_changed(pname, aud)
            rec["compared_to"] = py
            rec["gap_years"] = y - py - 1
            if ch is None:
                rec["status"] = "unknown"
            else:
                rec["changed"] = bool(ch)
                rec["status"] = "changed" if ch else "unchanged"
            if rec["gap_years"] > 0:
                rec["note"] = (f"compared with FY{py} across {rec['gap_years']} year(s) with unknown auditor; "
                               f"the change cannot be dated more precisely than FY{py + 1}-FY{y}")
            if ch:
                rec["previous_name"] = tp.normalize_firm_name(pname)
                ev = merger_check(y, "auditor", pname, aud)
                if ev is not None:
                    # recorded, not counted: the change is part of a business combination (B10)
                    rec.update({"changed": False, "observed_change": True, "status": "merger_context", "context": "merger",
                                "context_cues": ev.get("cues", []), "context_excerpt": ev.get("excerpt", "")})
                    if in_scope:
                        note_merger_change(y, "auditor", rec["previous_name"], rec["name"], ev)
        if aud is not None:
            last_aud = (y, aud)
        if in_scope:
            auditor_history[y] = rec
            if rec["changed"]:
                prev_n, cur_n = rec.get("previous_name"), rec["name"]
                disp = f"Auditor changed from {prev_n} to {cur_n} in FY{y}"
                if rec["gap_years"] > 0:
                    disp += f" (compared with FY{rec['compared_to']}; auditor unknown in between)"
                add_flag(y, FLAG_AUDITOR, "auditor", {"from": prev_n, "to": cur_n, "compared_to": rec["compared_to"]}, disp)

        # executives
        ex: dict[str, Any] = {"cfo": cfo, "ceo": ceo, "cfo_changed": False, "ceo_changed": False,
                              "cfo_status": "unknown", "ceo_status": "unknown"}
        for role, name, last in (("cfo", cfo, last_cfo), ("ceo", ceo, last_ceo)):
            if name is None:
                ex[f"{role}_status"] = "unknown"
                if in_scope:
                    unavailable[f"{role}_FY{y}"] = ("no filing metadata" if not had_meta else
                                                    f"{role.upper()} not identified on the signature page (or only a single-token name)")
            elif last is None:
                ex[f"{role}_status"] = "first_year" if (y == years_in[0] or after_shell is not None) else "first_known"
                if after_shell is not None:
                    ex[f"{role}_note"] = "baseline unknown: the earlier year(s) were a shell / SPAC predecessor"
            else:
                py, pname = last
                same = tp.same_person(pname, name) or _alnum(pname) == _alnum(name)
                ex[f"{role}_changed"] = not same
                ex[f"{role}_status"] = "unchanged" if same else "changed"
                ex[f"{role}_previous"] = pname
                ex[f"{role}_compared_to"] = py
                if y - py > 1:
                    ex[f"{role}_note"] = f"compared with FY{py} across {y - py - 1} year(s) with unknown {role.upper()}"
                if not same:
                    ev = merger_check(y, role, pname, name)
                    if ev is not None:
                        ex.update({f"{role}_changed": False, f"{role}_observed_change": True, f"{role}_status": "merger_context",
                                   f"{role}_context": "merger", f"{role}_context_cues": ev.get("cues", []),
                                   f"{role}_context_excerpt": ev.get("excerpt", "")})
                        if in_scope:
                            note_merger_change(y, role, pname, name, ev)
        if cfo is not None:
            last_cfo = (y, cfo)
        if ceo is not None:
            last_ceo = (y, ceo)
        if in_scope:
            executive_changes[y] = ex
            if ex["cfo_changed"]:
                add_flag(y, FLAG_CFO, "cfo", {"from": ex["cfo_previous"], "to": cfo, "compared_to": ex["cfo_compared_to"]},
                         f"CFO changed from {ex['cfo_previous']} to {cfo} in FY{y}")
            if ex["ceo_changed"]:
                add_flag(y, FLAG_CEO, "ceo", {"from": ex["ceo_previous"], "to": ceo, "compared_to": ex["ceo_compared_to"]},
                         f"CEO changed from {ex['ceo_previous']} to {ceo} in FY{y}")

    # --- audit fees -----------------------------------------------------------------------
    def fee_of(y: int) -> Optional[float]:
        v = (meta_all.get(y) or {}).get("audit_fees")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None

    def fee_year_of(y: int) -> Optional[int]:
        d = (meta_all.get(y) or {}).get("audit_fee_detail")
        return _intkey(d.get("year")) if isinstance(d, dict) else None

    for y in years_in:
        cur = fee_of(y)
        rec = {"amount": cur, "yoy_change_pct": None, "flag": False, "confidence": None,
               "revenue_growth_pct": None, "source": (meta_all.get(y) or {}).get("audit_fee_source"), "status": "ok"}
        if cur is None:
            rec["status"] = "unavailable"
            rec["reason"] = "audit fees not extracted (not in the filing and no proxy text, or not parseable)"
            unavailable[f"audit_fees_FY{y}"] = rec["reason"]
        else:
            prev = fee_of(y - 1) if (y - 1) in meta_all else None
            if prev is None:
                rec["status"] = "no_prior"
                rec["reason"] = f"no audit fee for FY{y - 1} to compare with"
                unavailable.setdefault(f"audit_fee_yoy_FY{y}", rec["reason"])
            else:
                fy_c, fy_p = fee_year_of(y), fee_year_of(y - 1)
                if fy_c is not None and fy_p is not None and fy_c - fy_p != 1:
                    rec["status"] = "unavailable"
                    rec["reason"] = f"fee tables refer to non-consecutive years ({fy_p}, {fy_c})"
                    unavailable[f"audit_fee_yoy_FY{y}"] = rec["reason"]
                elif cur / prev > FEE_IMPLAUSIBLE_RATIO or cur / prev < 1.0 / FEE_IMPLAUSIBLE_RATIO:
                    rec["status"] = "unavailable"
                    rec["reason"] = (f"fee ratio {cur / prev:.4g}x between FY{y - 1} and FY{y} is implausible "
                                     "(likely a currency-unit parsing error); not used")
                    unavailable[f"audit_fee_yoy_FY{y}"] = rec["reason"]
                else:
                    g = round(cur / prev - 1.0, 9)   # avoid float noise at the exact threshold
                    rec["yoy_change_pct"] = round(g * 100, 2)
                    rec["prior_amount"] = prev
                    rg = None
                    if revenue.get(y) is not None and revenue.get(y - 1) not in (None, 0):
                        rg = round(revenue[y] / revenue[y - 1] - 1.0, 9)
                        rec["revenue_growth_pct"] = round(rg * 100, 2)
                    if g > FEE_GROWTH_THRESHOLD:
                        if rg is not None:
                            if rg < g * REVENUE_COVERAGE_RATIO:
                                rec["flag"], rec["confidence"] = True, "normal"
                        else:
                            rec["flag"], rec["confidence"] = True, "low"
                            rec["reason"] = ("revenue growth unavailable"
                                             + ("" if revenue_available else " (no annual_facts revenue)")
                                             + "; flagged on fee growth alone, LOW confidence")
                            unavailable[f"revenue_growth_FY{y}"] = rec["reason"]
                    if rec["flag"]:
                        disp = (f"Audit fees rose {rec['yoy_change_pct']:.1f}% in FY{y} "
                                f"({_fmt_money(prev)} to {_fmt_money(cur)})")
                        if rg is not None:
                            disp += f" while revenue grew {rg * 100:.1f}% (less than half the fee growth)"
                        else:
                            disp += "; revenue growth unavailable, low confidence"
                        add_flag(y, FLAG_FEES, "audit_fees_yoy_pct", rec["yoy_change_pct"], disp)
                        evidence[-1]["confidence"] = rec["confidence"]
        audit_fees[y] = rec

    # --- text based signals ---------------------------------------------------------------
    def rpt_of(y: int) -> Optional[dict[str, Any]]:
        """related-party measure of year y as a comparable (chars, source) record, or None when the year is a shell / unknown."""
        if y in shell_years:
            return {"chars": None, "source": "shell", "year": y}
        md_y = meta_all.get(y)
        if not isinstance(md_y, dict):
            return None
        c = md_y.get("related_party_chars")
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            return None
        return {"chars": int(c), "source": md_y.get("related_party_source"), "year": y}

    for y in years_in:
        txt = texts.get(y)
        md = meta_all.get(y) or {}
        form = md.get("form") if isinstance(md, dict) else None
        has_text = isinstance(txt, str) and bool(txt.strip())
        if has_text:
            try:
                rs = tp.detect_restatement(txt, form)
                rs_raw_n = len(rs["hits"])
                rs = {**rs, "hits": _error_restatement_hits(rs["hits"])}
                rs["detected"] = bool(rs["hits"])
                mw = tp.detect_material_weakness(txt, form)
                sd_hits = [h for h in tp.keyword_hits(txt, tp.MATERIAL_WEAKNESS_PATTERNS[1:], negations=True) if not h["negated"]]
                gc = tp.detect_going_concern(txt)
                gc = {**gc, "hits": _real_going_concern_hits(gc["hits"])}
                gc["detected"] = bool(gc["hits"])
            except Exception as exc:  # defensive: text parser never raises, but be safe
                has_text = False
                degraded.append(f"network: text analysis failed for FY{y}: {exc!r}")
                unavailable[f"text_signals_FY{y}"] = f"text analysis failed: {exc!r}"
        else:
            unavailable[f"text_signals_FY{y}"] = "filing text not available; restatement / material weakness / going concern unknown"
            degraded.append(f"network: filing text missing for FY{y}; text-based signals unavailable")
        if has_text:
            flagged = bool(rs["detected"] or mw["detected"])
            # best evidence first: restatement hits (non-reliance first) if any, else the material-weakness hits; both are
            # already ordered Item 9A / body first, preface / risk factors last (B12)
            src_hits = sorted((rs["hits"] if rs["detected"] else []) + (mw["hits"] if mw["detected"] else []),
                              key=lambda h: (tp._SECTION_RANK.get(h.get("section", "body"), 1), h.get("kind_rank", 5), h.get("start", 0)))
            best = src_hits[0] if src_hits else None
            kinds = [k for k, d in (("restatement", rs["detected"]), ("material weakness", mw["detected"])) if d]
            rem_hits = mw.get("remediated_hits", [])
            restatements[y] = {
                "detected": flagged,
                "text": _excerpt(src_hits if src_hits else sd_hits),
                "restatement_detected": bool(rs["detected"]),
                "material_weakness_detected": bool(mw["detected"]),
                "significant_deficiency_detected": bool(sd_hits),
                "n_restatement_hits": len(rs["hits"]),
                "n_restatement_hits_rejected_non_error": rs_raw_n - len(rs["hits"]),
                "n_material_weakness_hits": len(mw["hits"]),
                "negated_hits_ignored": len(rs["negated_hits"]) + len(mw["negated_hits"]),
                "evidence_section": best.get("section") if best else None,
                "evidence_pct_of_document": best.get("pct_of_document") if best else None,
                "evidence_kind": best.get("kind") if best else None,
                "icfr_not_effective": bool(mw.get("icfr_not_effective")),
                "icfr_effective": bool(mw.get("icfr_effective")),
                "auditor_adverse_opinion": bool(mw.get("auditor_adverse_opinion")),
                # recorded, never flagged: remediated / prior-period / history-with-effective-ICFR weakness language
                "remediated_history_detected": bool(rem_hits),
                "n_remediated_history_hits": len(rem_hits),
                "remediated_history_text": _excerpt(rem_hits) if rem_hits else "",
                "n_forward_looking_ignored": len(mw.get("forward_looking_hits", [])),
            }
            if flagged:
                where = _where(best) if best else ""
                disp = (f"FY{y} filing discloses {' and '.join(kinds)}"
                        + (f" ({where})" if where else "") + f": \"{_excerpt(src_hits)}\"")
                add_flag(y, FLAG_RESTATE, "restatement_or_material_weakness", kinds, disp)
                if best is not None:
                    evidence[-1].update({"section": best.get("section"), "pct_of_document": best.get("pct_of_document")})
            going_concern[y] = {"detected": bool(gc["detected"]), "text": _excerpt(gc["hits"]),
                                "n_hits": len(gc["hits"])}
            if gc["detected"] and entity.get(y, {}).get("is_shell"):
                # a SPAC's "mandatory liquidation ... substantial doubt" is structural, not a business going-concern signal
                going_concern[y].update({"detected": False, "context": "shell", "shell_context_detected": True,
                                         "note": "going-concern language in a shell / SPAC predecessor filing; recorded, not flagged"})
            elif gc["detected"]:
                add_flag(y, FLAG_GC, "going_concern", True,
                         f"FY{y} filing expresses going-concern doubt: \"{_excerpt(gc['hits'])}\"")
        else:
            restatements[y] = {"detected": False, "text": "", "restatement_detected": None,
                               "material_weakness_detected": None, "significant_deficiency_detected": None,
                               "status": "unavailable"}
            going_concern[y] = {"detected": False, "text": "", "status": "unavailable"}

        # related party (B9: like with like; shell / pointer / source-mismatch years are never compared)
        cur = rpt_of(y)
        chars = cur["chars"] if cur else None
        src = cur["source"] if cur else None
        rp = {"detected": False, "chars": chars, "yoy_change_pct": None, "new_disclosure": False, "source": src}
        if y in shell_years:
            rp["status"] = "shell"
            rp["context"] = "shell"
        elif chars is None:
            rp["status"] = "unavailable"
            unavailable[f"related_party_FY{y}"] = "related_party_chars not in metadata"
        else:
            prior_rec = rpt_of(y - 1) if (y - 1) in meta_all or (y - 1) in shell_years else None
            if prior_rec is None:
                rp["status"] = "no_prior"
                unavailable.setdefault(f"related_party_yoy_FY{y}", f"related_party_chars for FY{y - 1} not available")
            elif prior_rec["source"] == "shell":
                rp["status"] = "no_prior"
                rp["note"] = f"FY{y - 1} was a shell / SPAC predecessor filing; not a baseline"
                unavailable.setdefault(f"related_party_yoy_FY{y}", rp["note"])
            else:
                prior, psrc = prior_rec["chars"], prior_rec["source"]
                rp["prior_source"] = psrc
                have_sources = src is not None or psrc is not None   # old metadata without related_party_source: legacy behaviour
                if have_sources and (src == "pointer" or psrc == "pointer"):
                    rp["status"] = "pointer"
                    rp["prior_chars"] = prior
                    rp["note"] = ("Item 13 only points to another document in "
                                  + ", ".join(f"FY{yy}" for yy, ss in ((y, src), (y - 1, psrc)) if ss == "pointer")
                                  + "; its length is not a disclosure size, growth unavailable")
                    unavailable[f"related_party_yoy_FY{y}"] = rp["note"]
                elif prior == 0:
                    rp["status"] = "prior_not_found"
                    rp["new_disclosure"] = chars >= RPT_MIN_CHARS
                    rp["prior_chars"] = 0
                elif have_sources and src != psrc:
                    rp["status"] = "source_mismatch"
                    rp["prior_chars"] = prior
                    rp["note"] = (f"related-party text measured on different sources (FY{y - 1}: {psrc or 'none'}, FY{y}: {src or 'none'}); "
                                  "like-for-like growth unavailable")
                    unavailable[f"related_party_yoy_FY{y}"] = rp["note"]
                elif prior == 0:
                    rp["status"] = "prior_not_found"
                    rp["new_disclosure"] = chars >= RPT_MIN_CHARS
                    rp["prior_chars"] = 0
                else:
                    g = round(chars / prior - 1.0, 9)
                    rp["yoy_change_pct"] = round(g * 100, 1)
                    rp["prior_chars"] = prior
                    rp["status"] = "ok"
                    if g > RPT_GROWTH_THRESHOLD and chars >= RPT_MIN_CHARS:
                        rp["detected"] = True
                        add_flag(y, FLAG_RPT, "related_party_chars_yoy_pct", rp["yoy_change_pct"],
                                 f"Related-party disclosure grew {rp['yoy_change_pct']:.0f}% in FY{y} "
                                 f"({prior:,} to {chars:,} characters" + (f", {src}" if src else "") + ")")
        related_party_flags[y] = rp

    # --- aggregate ---------------------------------------------------------------------------
    flags_fired = sum(len(v) for v in flags_by_year.values())
    focus_flags = set(flags_by_year.get(focus_year, []))
    # hard combination: auditor change + CFO change in the same year.  Changes that belong to a business combination / SPAC
    # merger are recorded (merger_context_changes) but never reach flags_by_year, so they cannot form the combination (B10).
    hard = bool(focus_flags & HARD_FLAGS) or (FLAG_AUDITOR in focus_flags and FLAG_CFO in focus_flags)
    n = len(focus_flags)
    severity = "High" if (hard or n >= 3) else "Medium" if n == 2 else "Low" if n == 1 else "None"
    key_finding = _key_finding(flags_by_year, evidence, focus_year, years_in, unavailable)

    return {
        "auditor_history": auditor_history,
        "executive_changes": executive_changes,
        "audit_fees": audit_fees,
        "restatements": restatements,
        "related_party_flags": related_party_flags,
        "going_concern": going_concern,
        "entity_context": {y: e for y, e in entity_context.items() if y in obs_years},
        "merger_context_changes": merger_changes,
        "flags_fired": flags_fired,
        "key_finding": key_finding,
        "severity": severity,
        "flags_by_year": flags_by_year,
        "focus_year": focus_year,
        "data_quality": {"unavailable": unavailable},
        "degraded": degraded,
        "evidence": evidence,
        "thresholds": {"audit_fee_growth": FEE_GROWTH_THRESHOLD, "revenue_coverage_ratio": REVENUE_COVERAGE_RATIO,
                       "related_party_growth": RPT_GROWTH_THRESHOLD, "related_party_min_chars": RPT_MIN_CHARS},
    }


def _key_finding(flags_by_year: dict[int, list[str]], evidence: list[dict], focus_year: int,
                 years: list[int], unavailable: dict[str, str]) -> str:
    def pick(year: int) -> Optional[dict]:
        fl = set(flags_by_year.get(year, []))
        if not fl:
            return None
        for key in _KEY_ORDER:
            if key == "auditor+cfo":
                if FLAG_AUDITOR in fl and FLAG_CFO in fl:
                    a = next(e for e in evidence if e["year"] == year and e["flag"] == FLAG_AUDITOR)
                    c = next(e for e in evidence if e["year"] == year and e["flag"] == FLAG_CFO)
                    return {"display": f"{a['display']} and {c['display']}"}
            elif key in fl:
                return next(e for e in evidence if e["year"] == year and e["flag"] == key)
        return None

    f = pick(focus_year)
    if f:
        extra = len(flags_by_year[focus_year]) - 1
        s = f["display"].rstrip(".")
        return s + (f" (plus {extra} other network flag{'s' if extra != 1 else ''})." if extra > 0 and "and CFO" not in s else ".")
    for y in sorted(years, reverse=True):
        f = pick(y)
        if f:
            return f"No network flags in FY{focus_year}; most recent earlier signal: {f['display'].rstrip('.')}."
    gaps = len(unavailable)
    base = f"No auditor, executive, restatement, fee, related-party or going-concern signals in FY{years[0]}-FY{years[-1]}"
    return base + (f" ({gaps} data gap(s) recorded)." if gaps else ".")


# ---- public entry point -------------------------------------------------------------------
def run_network(state: dict) -> dict:
    """LangGraph node for Agent 3. Never raises."""
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    try:
        result = _analyse(state or {})
        status = "unavailable" if result.get("unavailable") else "ok"
    except Exception as exc:  # pragma: no cover - last-resort guard
        log.warning("network agent failed: %r", exc)
        result = _empty_result(f"internal error: {exc!r}")
        status = "error"
    deg = list(result.get("degraded", []))
    trace = {
        "agent": AGENT,
        "status": status,
        "started": started,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "summary": result.get("key_finding", ""),
        "degraded": deg,
    }
    return {"network_result": result, "agent_trace": [trace], "degraded": deg}
