"""AGENT 2 - Language forensics (docs/SPEC.md "AGENT 2", docs/CONTRACTS.md section 4).

``run_language(state) -> dict`` is synchronous and never raises. It reads ONLY the raw state fields
``filing_texts`` ({year: full annual-report text}), ``analysis_years`` (and optionally ``focus_year`` /
``filings``) and returns a partial state update::

    {"language_result": {...}, "agent_trace": [{...}], "degraded": [...]}

Signals computed per fiscal year (spec thresholds are FROZEN and must not be tuned):

1. HEDGING   - hedge-word ratio over MD&A prose; flag if it rises > +25% (relative) year on year.
2. PASSIVE   - % of MD&A sentences in the passive voice (spaCy ``nsubjpass``/``auxpass``; documented
               rule-based fallback when the model is missing -> ``degraded``); v2: flag if the share rises
               > +25% (relative) year on year, the same form as hedging. The spec's fixed 15% cut-off fired on
               25/25 healthy large-cap filings (TUNING_LEDGER P2), i.e. carried no information; the measured
               percentage is still reported (docs/V2_CHANGELOG_agents.md B7).
3. RISK_LEN  - character length of the Risk Factors section; flag if it grows > +40% YoY.
4. SPECIFICITY - Claude Haiku rating 1-10 of the MD&A (needs ANTHROPIC_API_KEY; with no key the
               score is None and a ``degraded`` entry is written - NO heuristic stand-in);
               flag if score < 5 or it drops > 2 points YoY.
5. NEW_LEGAL - Legal Proceedings text compared with the prior year by IDENTIFIERS (v3, docs/V3_CHANGELOG_lang_eval.md L1):
               case captions, docket numbers, courts, agency + matter type (SEC subpoena, DOJ investigation, ...), unseen
               named parties; dates and amounts are stripped and reworded boilerplate is not a new proceeding. A paragraph
               with no identifier falls back to a strict content-word similarity test (LEGAL_FALLBACK_*). v2 (B11): when
               Item 3 only points to a note, the contingencies note text (``extract_sections()["legal_note"]``, when
               the parser supplies it) is compared instead; both years must use the same source.

v2 (B8/B2) SHELL / SPAC PREDECESSOR YEARS. ``state["filing_entity_flags"] = {year: {"is_shell", "spac_predecessor",
"reason"}}`` (from the pipeline; tolerated when absent) marks filings of a different entity (a blank-check company
before its business combination). Such a year is NOT a valid baseline: hedging, passive-voice, risk-factor growth,
specificity-drop and new-legal comparisons that would use it as year t-1 are not computed (the next year behaves like a
first year), and flags are never raised for the shell year itself. Absolute (level) tests still apply to the operating year.

Honesty rules: a metric that cannot be computed (section not found - e.g. Risk Factors in pre-2005
filings, MD&A incorporated by reference to an exhibit, no prior year, no LLM key) is reported as
unavailable with a reason in ``data_quality["unavailable"]``; it is never reported as zero and never
fires a flag.

Methodology choices that the spec leaves open (all documented in the result):
* Hedging terms are matched literally (word-boundary, case-insensitive; "subject to" is a phrase), so
  inflections ("expects", "believed", "plans") are NOT counted; the capitalised month "May" is not a
  hedge. The denominator is the number of alphabetic words in MD&A *prose* paragraphs (table rows and
  space-aligned tables are excluded), and the numerator is counted over the same paragraphs.
* Passive voice is measured on the same prose paragraphs, MD&A only (Risk Factors / Legal are heavy in
  boilerplate, so they are excluded as the task brief requires).
* A section extract shorter than ``MIN_MDNA_WORDS`` words (MD&A) / ``MIN_RISK_CHARS`` chars (Risk
  Factors) is treated as "incorporated by reference or truncated extraction" -> unavailable. A
  supplementary heading-based extractor (``_supplement_section``) is tried first because
  ``tools.text_parser`` can truncate sections at repeated running page headers (seen on MSFT).
"""
from __future__ import annotations

import difflib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from tools import llm
from tools.common import get_logger
from tools.text_parser import extract_sections

log = get_logger("agents.language")

AGENT_NAME = "language"

# --------------------------------------------------------------------------------------------------
# Frozen spec thresholds
# --------------------------------------------------------------------------------------------------
HEDGING_YOY_THRESHOLD = 0.25      # relative increase of the hedging ratio
PASSIVE_YOY_THRESHOLD = 0.25      # v2 (B7): relative increase of the passive share (same form as hedging); replaces the fixed 15% cut-off
RISK_YOY_THRESHOLD = 0.40         # relative increase of Risk Factors characters
SPECIFICITY_MIN_SCORE = 5         # flag if score < 5
SPECIFICITY_MAX_DROP = 2          # flag if score drops by more than 2 points YoY

# Data-sufficiency guards (structural, not tuned on any evaluation outcome)
MIN_MDNA_WORDS = 1000
MIN_RISK_CHARS = 3000
MIN_PASSIVE_SENTENCES = 20
MDNA_LLM_MAX_CHARS = 12_000
NEW_LEGAL_SIM_THRESHOLD = 0.5     # v2 only (superseded in v3 by the identifier rule; kept for reference / old tests)
NEW_LEGAL_CAPTION_SIM = 0.8       # v2 only (unused since v3)
LEGAL_MIN_UNIT_CHARS = 80
EXCERPT_MAX_CHARS = 400

HEDGING_TERMS = ("may", "might", "could", "subject to", "uncertain", "contingent", "approximately",
                 "estimated", "believe", "expect", "intend", "plan")

FLAG_HEDGING = "language.hedging"
FLAG_PASSIVE = "language.passive_voice"
FLAG_RISK = "language.risk_factor_growth"
FLAG_SPECIFICITY = "language.specificity"
FLAG_LEGAL = "language.new_legal"

# Prompt owned by this module (prompts/templates.py is owned by another engineer). The task text is the
# spec's sentence verbatim; the extra lines only constrain the output format.
SPECIFICITY_SYSTEM_PROMPT = (
    "You are a forensic accounting analyst reviewing the Management's Discussion and Analysis (MD&A) "
    "section of an SEC annual report.\n"
    "Rate the specificity of this MD&A section from 1-10. High specificity means concrete numbers, "
    "named products, specific markets. Low specificity means vague language about 'macroeconomic "
    "conditions' and 'industry trends'.\n"
    "Judge only the text provided. Do not use outside knowledge about the company and do not "
    "mention any figure that is not in the text. Keep the reason under 40 words.\n"
    'Return JSON only: {"score": int, "reason": str}'
)

_HEDGE_RE = re.compile(
    r"\b(?:" + "|".join(r"subject\s+to" if t == "subject to" else re.escape(t) for t in HEDGING_TERMS) + r")\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

# --------------------------------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------------------------------


def _fmt_pct(x: float, nd: int = 0) -> str:
    return f"{x:.{nd}f}%"


def _to_int_year(k: Any) -> Optional[int]:
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _entity_exclusions(raw: Any) -> dict[int, str]:
    """{year: reason} for years flagged is_shell / spac_predecessor in ``filing_entity_flags`` (malformed input ignored)."""
    out: dict[int, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, rec in raw.items():
        y = _to_int_year(k)
        if y is not None and isinstance(rec, dict) and (rec.get("is_shell") is True or rec.get("spac_predecessor") is True):
            out[y] = str(rec.get("reason") or "shell / SPAC predecessor filing")
    return out


def _effective_legal(info: dict) -> tuple[str, str]:
    """(text, source). Item 3 when it has substantive content; the referenced contingencies note (``legal_note``) when
    Item 3 is empty or only points to a note; else Item 3."""
    item3 = info.get("legal") or ""
    note = info.get("legal_note") or ""
    if note.strip():
        if not item3.strip():
            return note, "legal_note"
        cls = _classify_legal_units(item3)
        if not cls["units"] and cls["pointer"]:
            return note, "legal_note"
    return item3, "item3"


def _reason(msg: str) -> str:
    return msg if msg.startswith("unavailable") else f"unavailable: {msg}"


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs with internal line wraps joined."""
    out = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if lines:
            out.append(lines)
    return out  # type: ignore[return-value]


def _is_prose(lines: list[str]) -> bool:
    """True when a paragraph (list of lines) is running prose rather than a table / page furniture."""
    joined = " ".join(lines)
    words = _WORD_RE.findall(joined)
    if len(words) < 12:
        return False
    pipe_lines = sum(1 for ln in lines if " | " in ln or ln.count("|") >= 2)
    if pipe_lines / len(lines) >= 0.3:
        return False
    aligned = sum(1 for ln in lines if re.search(r"\S\s{3,}\S.*\s{3,}\S", ln))
    if len(lines) >= 3 and aligned / len(lines) >= 0.3:
        return False
    digits = sum(c.isdigit() for c in joined)
    if digits / max(1, len(joined)) > 0.2:
        return False
    return True


def prose_paragraphs(text: str) -> list[str]:
    """Prose paragraphs of ``text`` (tables and short fragments dropped), each as one string."""
    return [" ".join(lines) for lines in _paragraphs(text) if _is_prose(lines)]  # type: ignore[arg-type]


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


# --------------------------------------------------------------------------------------------------
# Supplementary section extraction (guards against text_parser truncation / stubs)
# --------------------------------------------------------------------------------------------------
_SUPP_PATTERNS = {
    "mdna": (
        re.compile(r"(?im)^[ \t|]*item\s*7\s*[.:\-–—]?\s*\|?\s*management\S{0,3}s?\s+discussion"),
        re.compile(r"(?im)^[ \t|]*item\s*(?:7a|8)\b"),
    ),
    "risk_factors": (
        re.compile(r"(?im)^[ \t|]*item\s*1a\s*[.:\-–—]?\s*\|?\s*risk\s+factors"),
        re.compile(r"(?im)^[ \t|]*item\s*(?:1b|2)\b"),
    ),
}


def _supplement_section(text: str, key: str) -> str:
    """Heading-based extraction; adopted only when it is > 1.5x longer than the parser's section.

    Picks the longest span that starts at an ``Item 7. Management's Discussion`` /
    ``Item 1A. Risk Factors`` heading line and ends at the next ``Item 7A/8`` / ``Item 1B/2`` heading
    line (this skips the table of contents, whose span is tiny)."""
    pats = _SUPP_PATTERNS.get(key)
    if not pats or not text:
        return ""
    start_rx, end_rx = pats
    best = ""
    for m in start_rx.finditer(text):
        e = end_rx.search(text, m.end())
        if not e:
            continue  # no closing heading: refuse rather than run to the end of the filing
        seg = text[m.start(): e.start()]
        if len(seg) > len(best):
            best = seg
    return best.strip()


def _section_text(secs: dict, text: str, key: str, min_chars: int) -> tuple[str, str]:
    """(section text, method). Prefers the parser's section; supplements it when it is too short."""
    base = (secs.get(key) or "") if isinstance(secs, dict) else ""
    method = (secs.get("method_by_section") or {}).get(key, secs.get("method", "")) if isinstance(secs, dict) else ""
    alt = _supplement_section(text, key)
    if len(alt) >= min_chars and len(alt) > 1.5 * len(base):
        return alt, "language_agent-heading-supplement"
    return base, str(method or "")


# --------------------------------------------------------------------------------------------------
# 1. Hedging
# --------------------------------------------------------------------------------------------------


def hedging_counts(text: str) -> dict:
    """Hedge-word count and ratio over the prose paragraphs of ``text`` (see module docstring)."""
    paras = prose_paragraphs(text)
    total_words = 0
    hedges = 0
    by_term: dict[str, int] = {}
    for p in paras:
        total_words += len(_WORD_RE.findall(p))
        for m in _HEDGE_RE.finditer(p):
            tok = m.group(0)
            low = re.sub(r"\s+", " ", tok.lower())
            if tok == "May":  # capitalised "May": a month unless it opens a sentence and is not followed by a day/year
                before = p[: m.start()].rstrip()
                after = p[m.end():].lstrip()
                sentence_start = (not before) or before[-1] in ".?!:;"
                if not sentence_start or re.match(r"\d", after):
                    continue
            elif low == "may" and re.match(r"\s*\d", p[m.end(): m.end() + 4]):
                continue  # "MAY 2019"
            hedges += 1
            by_term[low] = by_term.get(low, 0) + 1
    return {
        "count": hedges,
        "words": total_words,
        "ratio": (hedges / total_words) if total_words else None,
        "by_term": by_term,
    }


# --------------------------------------------------------------------------------------------------
# 2. Passive voice
# --------------------------------------------------------------------------------------------------
_NLP = None
_NLP_LOCK = threading.Lock()
_NLP_STATE: dict[str, Any] = {"tried": False, "error": None}
SPACY_MODEL = "en_core_web_sm"
_PASSIVE_DEPS = {"nsubjpass", "auxpass", "nsubj:pass", "aux:pass"}


def get_nlp():
    """Lazily load the spaCy pipeline (parser only). Returns None when spaCy or the model is missing."""
    global _NLP
    if _NLP is not None:
        return _NLP
    with _NLP_LOCK:
        if _NLP is not None:
            return _NLP
        if _NLP_STATE["tried"]:
            return None
        _NLP_STATE["tried"] = True
        try:
            import spacy

            nlp = spacy.load(SPACY_MODEL, disable=["ner", "lemmatizer", "tagger", "attribute_ruler"])
            nlp.max_length = 2_000_000
            _NLP = nlp
        except Exception as exc:  # noqa: BLE001 - model missing / spaCy not installed / python incompat
            _NLP_STATE["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            log.warning("spaCy model %s unavailable (%s); passive-voice uses the rule-based detector",
                        SPACY_MODEL, _NLP_STATE["error"])
            _NLP = None
    return _NLP


_BE = r"(?:is|are|was|were|be|been|being|am)"
_IRREGULAR_PART = {
    "made", "paid", "sold", "held", "built", "known", "given", "taken", "shown", "seen", "done", "set", "put",
    "cut", "led", "lost", "kept", "sent", "found", "bought", "brought", "begun", "chosen", "driven", "written",
    "grown", "drawn", "spent", "met", "read", "left", "won", "run", "hit", "paid", "understood", "withdrawn",
    "borne", "caught", "taught", "thrown", "worn", "broken", "spoken", "stolen", "forgotten", "gotten",
}
_NOT_PARTICIPLE = {
    "need", "indeed", "speed", "feed", "seed", "bed", "red", "shed", "hundred", "need", "embed", "proceed",
    "exceed", "succeed", "bleed", "breed", "agreed_", "often", "even", "seven", "eleven", "open", "then",
    "when", "token", "kitchen", "children", "women", "garden", "golden", "sudden", "ten", "listen", "wooden",
    "ever", "never", "when", "hidden_", "given_", "then",
}
_PASSIVE_RULE_RE = re.compile(
    r"\b" + _BE + r"(?:\s+(?:\w+ly|not|also|then|now|currently|generally|typically|primarily|n't))*\s+(\w+)\b",
    re.IGNORECASE,
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“(])")


def _is_participle(w: str) -> bool:
    lw = w.lower()
    if lw in _NOT_PARTICIPLE:
        return False
    if lw in _IRREGULAR_PART:
        return True
    if len(lw) >= 5 and (lw.endswith("ed") or lw.endswith("en")):
        return True
    return False


def passive_rule_based(sentence: str) -> bool:
    """Rule-based passive detector: a form of 'to be' (+ optional adverbs / 'not') + a past participle
    (regular -ed/-en or an irregular-participle list). Approximate: it can count adjectival participles
    ("is limited") and miss "get"-passives. Used only when spaCy / the model is unavailable."""
    for m in _PASSIVE_RULE_RE.finditer(sentence):
        if _is_participle(m.group(1)):
            return True
    return False


def _chunk_long(p: str, limit: int = 8000) -> list[str]:
    if len(p) <= limit:
        return [p]
    out, cur = [], ""
    for s in _SENT_SPLIT_RE.split(p):
        if len(cur) + len(s) + 1 > limit and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def passive_stats(text: str, nlp=None) -> dict:
    """Passive-voice share of MD&A prose sentences. ``nlp`` None -> rule-based detector."""
    paras = [c for p in prose_paragraphs(text) for c in _chunk_long(p)]
    sentences = 0
    passive = 0
    if nlp is not None:
        for doc in nlp.pipe(paras, batch_size=64):
            for sent in doc.sents:
                if sum(1 for t in sent if t.is_alpha) < 5:
                    continue
                sentences += 1
                if any(t.dep_ in _PASSIVE_DEPS for t in sent):
                    passive += 1
        method = f"spacy:{SPACY_MODEL}"
    else:
        for p in paras:
            for s in _SENT_SPLIT_RE.split(p):
                if len(_WORD_RE.findall(s)) < 5:
                    continue
                sentences += 1
                if passive_rule_based(s):
                    passive += 1
        method = "rule-based"
    return {
        "sentences": sentences,
        "passive_sentences": passive,
        "pct": (100.0 * passive / sentences) if sentences else None,
        "method": method,
    }


# --------------------------------------------------------------------------------------------------
# 5. New legal proceedings
# --------------------------------------------------------------------------------------------------
_MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_AMOUNT_RE = re.compile(r"(?:us\$|\$|rmb|cny|eur|€|£)\s?[\d,.]+(?:\s?(?:million|billion|thousand|m|bn|k))?", re.I)
_DATE_RE = re.compile(r"\b" + _MONTHS + r"\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?:19|20)\d\d\b|\b" + _MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?\b", re.I)
_STOP = set("""a an the and or of to in on at by for with from as is are was were be been being that this these those it its
their his her which who whom whose would could should may might will shall has have had not no any such also than then
into over under about against between during after before upon within without other others company we our us they
said""".split())
_NONE_RE = re.compile(
    r"(?:\bnone\b\.?$|not\s+(?:currently\s+|presently\s+)?(?:a\s+)?(?:party|subject)\s+to\s+any\b.{0,80}\b(?:legal|litigation|proceedings)"
    r"|no\s+(?:material\s+)?(?:pending\s+)?(?:legal\s+)?(?:proceedings|litigation)"
    r"|not\s+(?:currently\s+|presently\s+)?involved\s+in\s+any\b.{0,60}\b(?:legal|proceedings|litigation))", re.I)
_POINTER_RE = re.compile(
    r"incorporated\s+(?:herein\s+)?by\s+reference|\b(?:see|refer\s+to|described\s+in|discussed\s+in|set\s+forth\s+(?:in|under)|included\s+in)\b"
    r".{0,120}\bnotes?\b|\bnote\s+\d+\b", re.I)
_GENERIC_RE = re.compile(r"ordinary\s+course\s+of|inherently\s+uncertain|from\s+time\s+to\s+time", re.I)
_CAPTION_RE = re.compile(
    r"((?:[A-Z][\w.&'\-]*,?\s+){1,5}?)v[s]?\.\s+((?:[A-Z][\w.&'\-]*,?\s*){1,5})|\bIn\s+re\s+((?:[A-Z][\w.&'\-]*\s*){1,6})")


def _normalise_legal(s: str) -> str:
    s = s.lower()
    s = _AMOUNT_RE.sub(" ", s)
    s = _DATE_RE.sub(" ", s)
    s = re.sub(r"\b(?:19|20)\d\d\b", " ", s)
    s = re.sub(r"[^a-z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(norm: str) -> set[str]:
    return {w for w in norm.split() if w not in _STOP and len(w) > 2}


def _captions(s: str) -> set[str]:
    out = set()
    for m in _CAPTION_RE.finditer(s):
        raw = " ".join(g for g in m.groups() if g)
        n = re.sub(r"[^a-z\s]", " ", raw.lower())
        n = re.sub(r"\s+", " ", n).strip()
        if len(n) >= 6:
            out.add(n)
    return out


_GENERIC_PROPER = set("""the company court district states united state act securities exchange commission inc corp corporation
llc ltd plc new york california texas delaware county federal law laws code rule rules section sections note notes
item part form january february march april may june july august september october november december
alabama alaska arizona arkansas colorado connecticut florida georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana
maine maryland massachusetts michigan minnesota mississippi missouri montana nebraska nevada hampshire jersey mexico carolina dakota
ohio oklahoma oregon pennsylvania rhode island tennessee utah vermont virginia washington wisconsin wyoming columbia d.c
canada china europe european germany belgium france italy spain japan korea india brazil israel australia kingdom ireland
netherlands switzerland sweden russia asia pacific latin america americas african middle east eastern western northern southern
central national international american u.s u.s. nos no inc. l.p l.p. llp holdings group partners
authority department agency division bureau office board administration commission council committee regulation regulations
directive directives requirement requirements standards standard law laws program programs plan plans agreement agreements
consultants incorporated telephone water building products services systems technologies technology solutions industries
collection payment labor enforcement organic pollutants evaluation authorization""".split())


def _proper_nouns(unit: str) -> set[str]:
    """Distinct capitalised words that are not sentence-initial (names of parties, courts, places, statutes)."""
    out: set[str] = set()
    prev_end = True
    for tok in unit.split():
        core = re.sub(r"(?:['’�]s)$", "", tok)
        core = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", core)
        if core and core[0].isupper() and not prev_end and len(core) >= 3 and core.lower() not in _GENERIC_PROPER                 and core.lower() not in _STOP:
            out.add(core.lower())
        prev_end = tok[-1:] in ".?!:;" or not core
    return out


def _is_continuation(unit: str, prev_text: str) -> bool:
    """A paragraph whose named entities (>= 2, >= 60%) already occur in last year's section is a development in
    an EXISTING matter (new status / ruling / settlement wording), not a new proceeding."""
    pn = _proper_nouns(unit)
    if len(pn) < 2:
        return False
    low = prev_text.lower()
    shared = sum(1 for w in pn if re.search(r"\b" + re.escape(w) + r"\b", low))
    return shared >= 2 and shared / len(pn) >= 0.6


_PAGE_FURNITURE_RE = re.compile(
    r"^[ \t]*(?:table\s+of\s+contents|index)[ \t]*$|^[ \t]*-?[ \t]*\d{1,3}[ \t]*-?[ \t]*$", re.IGNORECASE | re.MULTILINE)


def _legal_units(text: str) -> list[str]:
    units: list[str] = []
    text = _PAGE_FURNITURE_RE.sub("", text or "")
    for lines in _paragraphs(text):
        para = re.sub(r"\s+", " ", " ".join(lines)).strip()  # type: ignore[arg-type]
        if len(para) > 1200:
            cur = ""
            for s in _SENT_SPLIT_RE.split(para):
                if cur and len(cur) + len(s) > 800:
                    units.append(cur)
                    cur = s
                else:
                    cur = f"{cur} {s}".strip()
            if cur:
                units.append(cur)
        else:
            units.append(para)
    merged: list[str] = []
    for u in units:  # a paragraph that starts lower-case continues the previous one (page-break artefact)
        if merged and u[:1].islower():
            merged[-1] = f"{merged[-1]} {u}"
        else:
            merged.append(u)
    return merged


def _classify_legal_units(text: str) -> dict:
    """Split a Legal Proceedings section into substantive units and note boilerplate / pointers."""
    substantive, pointer, none_stmt = [], False, False
    for u in _legal_units(text):
        if len(u) < LEGAL_MIN_UNIT_CHARS and not _captions(u):
            if _POINTER_RE.search(u):
                pointer = True
            elif _NONE_RE.search(u):
                none_stmt = True
            continue  # headings / fragments
        has_caption = bool(_captions(u))
        if len(u) < 900 and not has_caption:
            if _NONE_RE.search(u):
                none_stmt = True
                continue
            if _POINTER_RE.search(u):
                pointer = True
                continue
            if _GENERIC_RE.search(u):
                continue
        substantive.append(u)
    return {"units": substantive, "pointer": pointer, "none": none_stmt}


def _trim_legal_excerpt(ex: str, max_chars: Optional[int] = None) -> str:
    """Whole-paragraph excerpt, cut back to the last whole word (plus "...") when over the length cap."""
    max_chars = EXCERPT_MAX_CHARS if max_chars is None else max_chars
    ex = " ".join((ex or "").split())
    if len(ex) <= max_chars:
        return ex
    cut = ex[: max_chars - 3]
    if not ex[max_chars - 3].isspace() and " " in cut:  # cut landed inside a word: drop the fragment
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "..."


# ---- v3 (docs/V3_CHANGELOG_lang_eval.md L1): identifier-based "is this a NEW proceeding" ---------------------------------
# A paragraph is new only if it introduces an IDENTIFIER (case caption, docket number, agency + matter type, unseen named
# parties / courts) that is absent from last year's section. Wording, dates and amounts are irrelevant for such paragraphs.
# A paragraph with no extractable identifier falls back to a strict text-similarity test. The constants are fixed a priori
# (chosen before the dev cases were re-scored; NOT tuned) and are deliberately conservative = they make "new" harder.
LEGAL_FALLBACK_JACCARD = 0.30      # content-word Jaccard with some prior paragraph at or above this => same text, not new
LEGAL_FALLBACK_CONTAIN = 0.70      # >= 70% of the paragraph's content words already occur in last year's section => not new
LEGAL_NEW_PARTY_MIN = 2            # at least this many unseen named parties/courts ...
LEGAL_ANCHOR_MAX = 1               # ... and at most this many already-known ones (>= 2 known names = a development of an old matter)
_INITIATION_RE = re.compile(
    r"\b(?:filed|commenced|brought|initiated|instituted)\s+(?:a\s+|an\s+|the\s+|its\s+)?(?:\w+[\s,-]+){0,4}?"
    r"(?:complaint|suit|lawsuit|action|petition|claim|proceeding|arbitration)s?\b"
    r"|\bnamed\s+(?:as\s+)?(?:a\s+)?(?:co-)?defendants?\b|\bwere\s+served\b|\bwe\s+(?:received|were\s+served\s+with)\b"
    r"|\b(?:was|were|been)\s+filed\b|\bsued\b|\bdemanded\b"
    r"|\breceived\s+(?:an?\s+|the\s+|several\s+)?(?:\w+\s+){0,2}(?:subpoenas?|wells\s+notice|notices?|letters?|requests?|demands?)\b", re.I)

_AGENCIES = (
    ("sec", r"\bSEC\b|Securities\s+and\s+Exchange\s+Commission"),
    ("doj", r"\bDOJ\b|Department\s+of\s+Justice|U\.?S\.?\s+Attorney|United\s+States\s+Attorney"),
    ("ftc", r"\bFTC\b|Federal\s+Trade\s+Commission"),
    ("fda", r"\bFDA\b|Food\s+and\s+Drug\s+Administration"),
    ("epa", r"\bEPA\b|Environmental\s+Protection\s+Agency"),
    ("osha", r"\bOSHA\b|Occupational\s+Safety"),
    ("cftc", r"\bCFTC\b|Commodity\s+Futures"),
    ("finra", r"\bFINRA\b"),
    ("pcaob", r"\bPCAOB\b"),
    ("irs", r"\bIRS\b|Internal\s+Revenue\s+Service"),
    ("ag", r"Attorneys?\s+General"),
    ("dol", r"Department\s+of\s+Labor|\bDOL\b"),
    ("eeoc", r"\bEEOC\b|Equal\s+Employment"),
    ("nlrb", r"\bNLRB\b|National\s+Labor\s+Relations"),
    ("fcc", r"\bFCC\b|Federal\s+Communications"),
    ("cfpb", r"\bCFPB\b|Consumer\s+Financial\s+Protection"),
    ("ofac", r"\bOFAC\b|Office\s+of\s+Foreign\s+Assets"),
    ("ec", r"European\s+Commission"),
    ("nhtsa", r"\bNHTSA\b|National\s+Highway\s+Traffic"),
    ("dot", r"Department\s+of\s+Transportation"),
    ("dod", r"Department\s+of\s+Defense|\bDCAA\b|Defense\s+Contract"),
    ("hhs", r"\bHHS\b|\bOIG\b|Health\s+and\s+Human\s+Services|Office\s+of\s+Inspector\s+General"),
    ("cms", r"\bCMS\b|Centers\s+for\s+Medicare"),
    ("fed", r"Federal\s+Reserve|\bFDIC\b|Comptroller\s+of\s+the\s+Currency"),
)
_AGENCY_RES = [(k, re.compile(v)) for k, v in _AGENCIES]
_MATTERS = (
    ("subpoena", r"subpoena"),
    ("wells", r"wells\s+notice"),
    ("cid", r"civil\s+investigative\s+demand"),
    ("investigation", r"investigat|inquir|\bprobe\b|informal\s+request|document\s+request"),
    ("enforcement", r"enforcement\s+action|cease[-\s]and[-\s]desist|consent\s+(?:decree|order|judgment)|indict|criminal\s+(?:complaint|charge)"),
    ("class_action", r"class\s+action|putative\s+class|purported\s+class"),
    ("derivative", r"derivative\s+(?:action|suit|complaint|lawsuit)|shareholder\s+derivative"),
    ("qui_tam", r"qui\s+tam|false\s+claims\s+act"),
    ("patent", r"patent\s+infring|infring\w*\s+(?:of\s+)?(?:its|their|certain)?\s*patents?"),
    ("antitrust", r"antitrust|anti-trust|price[-\s]fixing"),
    ("product_liability", r"product\s+liability|personal\s+injury|wrongful\s+death|asbestos"),
    ("environmental", r"superfund|environmental\s+(?:remediation|claim|matter)|\bCERCLA\b"),
    ("employment", r"wage[-\s]and[-\s]hour|employment\s+(?:discrimination|practices)"),
    ("arbitration", r"arbitration\s+(?:demand|proceeding)|demand\s+for\s+arbitration"),
)
_MATTER_RES = [(k, re.compile(v, re.I)) for k, v in _MATTERS]
_COURT_RE = re.compile(
    r"((?:United\s+States|U\.S\.)?\s*(?:District|Bankruptcy|Circuit)?\s*Court\s+(?:of\s+Appeals\s+)?(?:for|of)\s+the\s+"
    r"(?:[A-Z][a-z]+\s+){0,3}(?:District|Circuit)(?:\s+of\s+(?:[A-Z][a-z]+\s*){1,3})?"
    r"|(?:Superior|Supreme|Circuit|Chancery|District|Appellate)\s+Court\s+(?:of|for)\s+(?:the\s+)?(?:State\s+of\s+|County\s+of\s+)?(?:[A-Z][a-z]+\s*){1,3}"
    r"|Court\s+of\s+Chancery(?:\s+of\s+the\s+State\s+of\s+Delaware)?)")
_DOCKET_RE = re.compile(
    r"(?:\b(?:Case|Civil\s+Action|Civ\.?\s+Action|Docket|Index)\s+(?:No\.?|Number|#)\s*:?\s*|\bNo\.\s+)([A-Za-z0-9:\-./]*\d[A-Za-z0-9:\-./]*)"
    r"|\b(\d{1,2}[-:]\s?(?:cv|CV|cr|CR|md|MD|civ)[-:]\s?\d{3,6}(?:[-:][A-Za-z]{2,5})?)\b")


def _court_norm(s: str) -> str:
    s = re.sub(r"[^a-z\s]", " ", (s or "").lower())
    s = re.sub(r"\b(?:the|united|states|u|s)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _legal_ids(text: str) -> dict:
    """Identifiers of a Legal Proceedings text: captions, docket numbers, courts, agency:matter keys, bare matter keys, parties."""
    text = " ".join((text or "").split())
    ids: dict[str, set] = {"captions": _captions(text), "dockets": set(), "courts": set(), "agency_matters": set(),
                           "matters": set(), "parties": set()}
    for m in _DOCKET_RE.finditer(text):
        d = re.sub(r"[^a-z0-9]", "", (m.group(1) or m.group(2) or "").lower())
        if len(d) >= 4 and re.search(r"\d{3}", d):
            ids["dockets"].add(d)
    for m in _COURT_RE.finditer(text):
        c = _court_norm(m.group(1))
        if len(c) >= 12:
            ids["courts"].add(c)
    ids["court_text"] = _court_norm(text)  # type: ignore[assignment]  (whole text, to recognise a court spelled differently)
    ids["agencies_any"] = {k for k, rx in _AGENCY_RES if rx.search(text)}
    ids["matters_any"] = {k for k, rx in _MATTER_RES if rx.search(text)}
    for sent in _SENT_SPLIT_RE.split(text):  # an agency pairs with a matter type only inside one sentence
        agencies = [k for k, rx in _AGENCY_RES if rx.search(sent)]
        for mt in (k for k, rx in _MATTER_RES if rx.search(sent)):
            if agencies:
                ids["agency_matters"].update(f"{ag}:{mt}" for ag in agencies)
            else:
                ids["matters"].add(mt)
    ids["parties"] = _proper_nouns(text)
    return ids


def _id_known(cap: str, prior_norm: str, prior_toks: set) -> bool:
    """A caption is known when its normalised string occurs in last year's text or all its distinctive words do."""
    if cap in prior_norm:
        return True
    words = [w for w in cap.split() if w not in _STOP and w not in _GENERIC_PROPER and len(w) > 2]
    return len(words) >= 2 and all(w in prior_toks for w in words)


def _new_identifiers(ids: dict, prior_ids: dict, prior_norm: str, prior_toks: set, initiation: bool = False) -> list[str]:
    """Identifiers of a paragraph that last year's section does not contain (empty list => nothing new by identifier)."""
    new: list[str] = []
    for c in sorted(ids["captions"]):
        if c not in prior_ids["captions"] and not _id_known(c, prior_norm, prior_toks):
            new.append(f"caption:{c}")
    squashed = prior_norm.replace(" ", "")
    for d in sorted(ids["dockets"] - prior_ids["dockets"]):
        if d not in squashed:
            new.append(f"docket:{d}")
    for k in sorted(ids["agency_matters"] - prior_ids["agency_matters"]):
        ag, mt = k.split(":")  # known when last year names this agency and this matter type anywhere, even in other sentences
        if not (ag in prior_ids["agencies_any"] and mt in prior_ids["matters_any"]):
            new.append(f"agency:{k}")
    if initiation:  # a suit initiated in a court last year's section never mentions is a new matter, whatever the party names
        for c in sorted(c for c in ids["courts"] - prior_ids["courts"] if c not in prior_ids["court_text"]):
            new.append(f"court:{c}")
    if initiation:  # a bare matter type (class action, patent suit, ...) is only a NEW matter when the paragraph initiates one
        for k in sorted(ids["matters"] - prior_ids["matters_any"]):
            new.append(f"matter:{k}")
    # named parties / courts: >= 2 unseen and at most 1 known anchor => a different matter (an old matter keeps its names)
    named = [f"party:{p}" for p in sorted(ids["parties"])] + [f"court:{c}" for c in sorted(ids["courts"])]
    unseen = [n for n in named if (n[6:] not in prior_ids["courts"] and n[6:] not in prior_ids["court_text"]
                                   if n.startswith("court:")
                                   else not re.search(r"\b" + re.escape(n[6:]) + r"\b", prior_norm))]
    if initiation and len(unseen) >= LEGAL_NEW_PARTY_MIN and len(named) - len(unseen) <= LEGAL_ANCHOR_MAX:
        new += unseen  # capitalised words alone (table headings, accounting terms) never make a paragraph a new matter
    return new


def _has_identifiers(ids: dict) -> bool:
    return bool(ids["captions"] or ids["dockets"] or ids["agency_matters"] or ids["matters"] or ids["courts"]
                or len(ids["parties"]) >= LEGAL_NEW_PARTY_MIN)


def compare_legal(prev_text: str, cur_text: str) -> dict:
    """Year-on-year comparison of two Legal Proceedings sections (v3, identifier based). See module docstring.

    A paragraph is NEW iff it introduces an identifier (case caption, docket number, agency + matter type, bare matter
    type, >= 2 unseen named parties/courts) absent from the prior-year text; if it has no extractable identifier at all
    it is NEW only when its content-word Jaccard against every prior paragraph is < LEGAL_FALLBACK_JACCARD, fewer than
    LEGAL_FALLBACK_CONTAIN of its content words occur in the prior section AND it describes the initiation of a matter
    (filed a complaint / named a defendant / received a subpoena): a procedural update of a pending matter ("oral
    argument was held") is a development, not a new proceeding. Dates and amounts are stripped first.
    """
    prev = _classify_legal_units(prev_text)
    cur = _classify_legal_units(cur_text)
    base = {"detected": False, "text": "", "new_units": 0, "n_units": len(cur["units"]),
            "confidence": "high", "status": "ok"}
    if not cur["units"]:
        if cur["pointer"]:
            base.update(confidence="low", status="incorporated_by_reference",
                        note="Legal Proceedings only refers to a note; the note text is not parsed, so new "
                             "proceedings cannot be assessed.")
        else:
            base.update(status="none_disclosed")
        return base
    if not prev["units"] and prev["pointer"] and not prev["none"]:
        base.update(confidence="low", status="prior_year_by_reference",
                    note="Prior-year Legal Proceedings only referred to a note, so a comparison is not possible.")
        return base
    prior_ids = _legal_ids(prev_text)
    prior_norm = _normalise_legal(prev_text)
    prior_toks = _tokens(prior_norm)
    prev_unit_toks = [_tokens(_normalise_legal(u)) for u in prev["units"]]
    new_units: list[tuple[float, str, list[str]]] = []
    for u in cur["units"]:
        toks = _tokens(_normalise_legal(u))
        best = 0.0
        for pt in prev_unit_toks:
            if toks and pt:
                best = max(best, len(toks & pt) / len(toks | pt))
        ids = _legal_ids(u)
        if _GENERIC_RE.search(u) and len(u) < 1500:  # ordinary-course boilerplate: only a caption / docket / agency matter can make it new
            ids["matters"], ids["parties"], ids["courts"] = set(), set(), set()
        if _has_identifiers(ids):
            new_ids = _new_identifiers(ids, prior_ids, prior_norm, prior_toks, bool(_INITIATION_RE.search(u)))
            if new_ids:
                new_units.append((best, u, new_ids[:6]))
            continue
        contain = len(toks & prior_toks) / len(toks) if toks else 1.0
        if best < LEGAL_FALLBACK_JACCARD and contain < LEGAL_FALLBACK_CONTAIN and _INITIATION_RE.search(u):
            new_units.append((best, u, ["text:no-identifier-fallback"]))
    base["new_units"] = len(new_units)
    if new_units:
        best_u = min(new_units, key=lambda bu: (bu[0], -len(bu[1])))  # least similar to anything in last year
        base["detected"] = True
        base["text"] = _trim_legal_excerpt(best_u[1])
        base["new_identifiers"] = best_u[2]
    return base


def _legal_by_year(secinfo: dict, all_years: list, excluded: dict) -> dict:
    """Per-year ``new_legal`` comparison (status handling + :func:`compare_legal`); never raises."""
    def shell_note(y: int) -> str:
        return f"FY{y - 1} is a shell/SPAC predecessor filing ({excluded[y - 1]}): not a valid YoY baseline"

    legal: dict[int, dict] = {}
    eff: dict[int, tuple[str, str]] = {y: _effective_legal(secinfo[y]) for y in all_years if not secinfo[y].get("error")}
    for y in all_years:
        info = secinfo[y]
        cur_t, cur_src = eff.get(y, ("", "item3"))
        if info.get("error") or not cur_t.strip():
            legal[y] = {"detected": False, "text": "", "confidence": None, "status": "unavailable", "source": cur_src,
                        "reason": _reason(info.get("error") or "Legal Proceedings section not found")}
            continue
        if y in excluded:
            legal[y] = {"detected": False, "text": "", "confidence": None, "status": "excluded_entity", "source": cur_src,
                        "reason": _reason(f"FY{y} is a shell/SPAC predecessor filing ({excluded[y]}): not compared")}
            continue
        prev_info = secinfo.get(y - 1)
        if (y - 1) in excluded:
            legal[y] = {"detected": False, "text": "", "confidence": None, "status": "no_prior_year", "source": cur_src,
                        "reason": _reason(shell_note(y))}
            continue
        prev_t, prev_src = eff.get(y - 1, ("", "item3"))
        if prev_info is None or prev_info.get("error") or not prev_t.strip():
            legal[y] = {"detected": False, "text": "", "confidence": None, "status": "no_prior_year", "source": cur_src,
                        "reason": _reason("no prior-year Legal Proceedings section to compare with")}
            continue
        if prev_src != cur_src:
            legal[y] = {"detected": False, "text": "", "confidence": "low", "status": "source_changed", "source": cur_src,
                        "note": f"FY{y} legal text comes from {cur_src} but FY{y - 1} from {prev_src}: formats are not "
                                "comparable, so new proceedings cannot be assessed."}
            continue
        try:
            legal[y] = compare_legal(prev_t, cur_t)
            legal[y]["source"] = cur_src
        except Exception as exc:  # noqa: BLE001
            legal[y] = {"detected": False, "text": "", "confidence": None, "status": "unavailable", "source": cur_src,
                        "reason": _reason(f"legal comparison failed ({type(exc).__name__})")}
    return legal


# --------------------------------------------------------------------------------------------------
# 4. Specificity (LLM)
# --------------------------------------------------------------------------------------------------


def _truncate_for_llm(mdna: str, limit: int = MDNA_LLM_MAX_CHARS) -> str:
    if len(mdna) <= limit:
        return mdna
    cut = mdna[:limit]
    nl = cut.rfind("\n")
    return cut[:nl] if nl > limit * 0.7 else cut


def _score_specificity(year: int, mdna: str) -> dict:
    """One Haiku call; never raises. Returns {"score","reason","flag"} (score None when unusable)."""
    user = f"Fiscal year {year} MD&A section (possibly truncated):\n\n{_truncate_for_llm(mdna)}"
    try:
        out = llm.llm_json("haiku", SPECIFICITY_SYSTEM_PROMPT, user, max_tokens=300)
    except Exception as exc:  # noqa: BLE001 - llm_json should not raise, but a mock/misuse might
        return {"score": None, "reason": f"unavailable: LLM call failed ({type(exc).__name__})", "flag": False}
    if not isinstance(out, dict):
        return {"score": None, "reason": "unavailable: LLM returned no valid JSON", "flag": False}
    raw = out.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return {"score": None, "reason": "unavailable: LLM JSON had no usable 'score'", "flag": False}
    try:
        score = int(round(float(raw)))
    except (TypeError, ValueError):
        return {"score": None, "reason": "unavailable: LLM JSON had a non-numeric 'score'", "flag": False}
    if not 1 <= score <= 10:
        return {"score": None, "reason": f"unavailable: LLM score {score} outside 1-10", "flag": False}
    reason = out.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    return {"score": score, "reason": reason[:400], "flag": False}


# --------------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_year_metrics(reason: str) -> dict:
    return {"flag": False, "reason": _reason(reason)}


def _analyse(state: dict) -> tuple[dict, list[str]]:
    degraded: list[str] = []
    raw_texts = state.get("filing_texts") or {}
    texts: dict[int, str] = {}
    for k, v in (raw_texts.items() if isinstance(raw_texts, dict) else []):
        y = _to_int_year(k)
        if y is not None:
            texts[y] = v if isinstance(v, str) else ""
    ay_raw = state.get("analysis_years") or []
    analysis_years = sorted({y for y in (_to_int_year(k) for k in ay_raw) if y is not None}) or sorted(texts)
    all_years = sorted(set(texts) | set(analysis_years))
    focus_year = _to_int_year(state.get("focus_year")) or (max(analysis_years) if analysis_years else None)
    forms: dict[int, str] = {}
    for f in state.get("filings") or []:
        try:
            fy = _to_int_year(f.get("fiscal_year"))
            if fy is not None and f.get("form"):
                forms[fy] = str(f["form"])
        except AttributeError:
            continue

    excluded = _entity_exclusions(state.get("filing_entity_flags"))

    def shell_note(y: int) -> str:
        return f"FY{y - 1} is a shell/SPAC predecessor filing ({excluded[y - 1]}): not a valid YoY baseline"

    unavailable: dict[str, str] = {}
    sections: dict[int, dict] = {}
    secinfo: dict[int, dict] = {}

    # ---- section extraction -------------------------------------------------------------------
    for y in all_years:
        t = texts.get(y, "")
        if not t.strip():
            secinfo[y] = {"mdna": "", "risk": "", "legal": "", "legal_ibr": False, "error": "no filing text"}
            continue
        try:
            secs = extract_sections(t, forms.get(y))
        except Exception as exc:  # noqa: BLE001
            secs = {}
            secinfo[y] = {"mdna": "", "risk": "", "legal": "", "legal_ibr": False,
                          "error": f"section extraction failed: {type(exc).__name__}"}
            continue
        mdna, m_method = _section_text(secs, t, "mdna", 8000)
        risk, r_method = _section_text(secs, t, "risk_factors", MIN_RISK_CHARS)
        legal = secs.get("legal_proceedings") or ""
        legal_note = secs.get("legal_note") if isinstance(secs.get("legal_note"), str) else ""
        ibr = bool((secs.get("incorporated_by_reference") or {}).get("legal_proceedings"))
        secinfo[y] = {"mdna": mdna, "risk": risk, "legal": legal, "legal_note": legal_note, "legal_ibr": ibr, "error": None,
                      "mdna_method": m_method, "risk_method": r_method,
                      "risk_ibr": bool((secs.get("incorporated_by_reference") or {}).get("risk_factors")),
                      "found": dict(secs.get("found") or {})}
        sections[y] = {"mdna_chars": len(mdna), "risk_factor_chars": len(risk), "legal_chars": len(legal),
                       "legal_note_chars": len(legal_note or ""),
                       "mdna_method": m_method, "risk_method": r_method}

    # ---- 1. hedging ---------------------------------------------------------------------------
    hedging: dict[int, dict] = {}
    mdna_ok: dict[int, bool] = {}
    for y in all_years:
        info = secinfo[y]
        if info.get("error"):
            hedging[y] = {"ratio": None, **_empty_year_metrics(info["error"])}
            mdna_ok[y] = False
            continue
        mdna = info["mdna"]
        if not mdna:
            hedging[y] = {"ratio": None, **_empty_year_metrics("MD&A section not found in this filing")}
            mdna_ok[y] = False
            continue
        try:
            h = hedging_counts(mdna)
        except Exception as exc:  # noqa: BLE001
            hedging[y] = {"ratio": None, **_empty_year_metrics(f"hedging computation failed ({type(exc).__name__})")}
            mdna_ok[y] = False
            continue
        if h["words"] < MIN_MDNA_WORDS:
            hedging[y] = {"ratio": None, "count": h["count"], "words": h["words"],
                          **_empty_year_metrics(f"MD&A extract has only {h['words']} prose words (< {MIN_MDNA_WORDS}); "
                                                f"likely incorporated by reference to an exhibit or a truncated extraction")}
            mdna_ok[y] = False
            continue
        mdna_ok[y] = True
        hedging[y] = {"ratio": h["ratio"], "count": h["count"], "words": h["words"], "by_term": h["by_term"],
                      "yoy_change": None, "yoy_change_pct": None, "flag": False}
    for y in all_years:
        h = hedging[y]
        p = None if (y - 1) in excluded else hedging.get(y - 1)
        if h.get("ratio") is not None and p and p.get("ratio"):
            ch = (h["ratio"] - p["ratio"]) / p["ratio"]
            h["yoy_change"] = ch
            h["yoy_change_pct"] = 100.0 * ch
            h["prior_ratio"] = p["ratio"]
            h["flag"] = bool(y in analysis_years and y not in excluded and round(ch, 9) > HEDGING_YOY_THRESHOLD)
        elif h.get("ratio") is not None:
            h["yoy_note"] = shell_note(y) if (y - 1) in excluded else "no usable prior-year MD&A: YoY change not computed"
    for y in analysis_years:
        h = hedging[y]
        if h.get("ratio") is None:
            unavailable[f"hedging_trend.{y}"] = h["reason"]
        elif h.get("yoy_change") is None:
            unavailable[f"hedging_trend.{y}.yoy"] = (h.get("yoy_note") or "no usable prior-year MD&A: YoY change not computed") + " (ratio still reported)"

    # ---- 2. passive voice ---------------------------------------------------------------------
    nlp = get_nlp()
    if nlp is None:
        degraded.append(f"language_passive_voice: spaCy model {SPACY_MODEL} unavailable "
                        f"({_NLP_STATE.get('error') or 'not installed'}); rule-based passive-voice detector used "
                        f"(run: python -m spacy download {SPACY_MODEL})")
    passive: dict[int, dict] = {}
    # the year before each analysed year is measured too (YoY baseline), but never reported as unavailable on its own
    pass_years = sorted((set(analysis_years) | {y - 1 for y in analysis_years}) & set(all_years))
    for y in pass_years:
        def _pun(key: str, msg: str) -> None:
            if y in analysis_years:
                unavailable[key] = msg
        if not mdna_ok.get(y):
            passive[y] = {"pct": None, **_empty_year_metrics(hedging[y].get("reason", "MD&A unavailable"))}
            _pun(f"passive_voice.{y}", passive[y]["reason"])
            continue
        try:
            ps = passive_stats(secinfo[y]["mdna"], nlp)
        except Exception as exc:  # noqa: BLE001
            if nlp is not None:  # spaCy failure on this text: fall back for this year, say so
                try:
                    ps = passive_stats(secinfo[y]["mdna"], None)
                    degraded.append(f"language_passive_voice: spaCy failed for FY{y} ({type(exc).__name__}); rule-based used")
                except Exception as exc2:  # noqa: BLE001
                    ps = None
                    err = type(exc2).__name__
            else:
                ps, err = None, type(exc).__name__
            if ps is None:
                passive[y] = {"pct": None, **_empty_year_metrics(f"passive-voice computation failed ({err})")}
                _pun(f"passive_voice.{y}", passive[y]["reason"])
                continue
        if ps["sentences"] < MIN_PASSIVE_SENTENCES or ps["pct"] is None:
            passive[y] = {"pct": None, "sentences": ps["sentences"], **_empty_year_metrics(
                f"only {ps['sentences']} prose sentences in MD&A (< {MIN_PASSIVE_SENTENCES})")}
            _pun(f"passive_voice.{y}", passive[y]["reason"])
            continue
        passive[y] = {"pct": ps["pct"], "passive_sentences": ps["passive_sentences"], "sentences": ps["sentences"],
                      "method": ps["method"], "yoy_change": None, "yoy_change_pct": None, "flag": False}
    for y in pass_years:
        pv = passive[y]
        if pv.get("pct") is None:
            continue
        prev_p = None if (y - 1) in excluded else passive.get(y - 1)
        if prev_p and prev_p.get("pct"):
            ch = (pv["pct"] - prev_p["pct"]) / prev_p["pct"]
            pv["yoy_change"], pv["yoy_change_pct"], pv["prior_pct"] = ch, 100.0 * ch, prev_p["pct"]
            pv["flag"] = bool(y in analysis_years and y not in excluded and round(ch, 9) > PASSIVE_YOY_THRESHOLD)
        else:
            pv["yoy_note"] = shell_note(y) if (y - 1) in excluded else "no usable prior-year MD&A: YoY change not computed"
            if y in analysis_years:
                unavailable[f"passive_voice.{y}.yoy"] = pv["yoy_note"] + " (share still reported)"
    for y in analysis_years:
        passive.setdefault(y, {"pct": None, **_empty_year_metrics(hedging[y].get("reason", "MD&A unavailable"))})

    # ---- 3. risk factor length ----------------------------------------------------------------
    risk: dict[int, dict] = {}
    risk_ok: dict[int, bool] = {}
    for y in all_years:
        info = secinfo[y]
        n = len(info.get("risk") or "")
        if info.get("error"):
            risk[y] = {"chars": None, "yoy_change": None, **_empty_year_metrics(info["error"])}
            risk_ok[y] = False
        elif n == 0:
            why = "Risk Factors section not found"
            if y < 2005:
                why += " (Item 1A Risk Factors did not exist in annual reports before FY2005)"
            risk[y] = {"chars": None, "yoy_change": None, **_empty_year_metrics(why)}
            risk_ok[y] = False
        elif n < MIN_RISK_CHARS:
            risk[y] = {"chars": None, "raw_chars": n, "yoy_change": None, **_empty_year_metrics(
                f"Risk Factors extract is only {n} chars (< {MIN_RISK_CHARS}): a cross-reference/stub or incorporated "
                f"by reference, not the disclosure itself")}
            risk_ok[y] = False
        else:
            risk[y] = {"chars": n, "yoy_change": None, "flag": False}
            risk_ok[y] = True
    for y in all_years:
        r = risk[y]
        p = None if (y - 1) in excluded else risk.get(y - 1)
        if r.get("chars") and p and p.get("chars"):
            ch = (r["chars"] - p["chars"]) / p["chars"]
            r["yoy_change"] = ch
            r["yoy_change_pct"] = 100.0 * ch
            r["prior_chars"] = p["chars"]
            r["flag"] = bool(y in analysis_years and y not in excluded and round(ch, 9) > RISK_YOY_THRESHOLD)
    for y in analysis_years:
        r = risk[y]
        if r.get("chars") is None:
            unavailable[f"risk_factor_length.{y}"] = r["reason"]
        elif r.get("yoy_change") is None:
            unavailable[f"risk_factor_length.{y}.yoy"] = (shell_note(y) if (y - 1) in excluded
                                                          else "prior-year Risk Factors unavailable: YoY change not computed")

    # ---- 4. specificity -----------------------------------------------------------------------
    spec: dict[int, dict] = {}
    have_llm = False
    try:
        have_llm = bool(llm.llm_available())
    except Exception:  # noqa: BLE001
        have_llm = False
    spec_years = [y for y in all_years if mdna_ok.get(y)]
    if not have_llm:
        reason = "unavailable: no ANTHROPIC_API_KEY"
        for y in analysis_years:
            spec[y] = {"score": None, "reason": reason, "flag": False}
            unavailable[f"specificity_scores.{y}"] = reason
        degraded.append("language_specificity: ANTHROPIC_API_KEY not set; specificity scores unavailable "
                        "(no heuristic stand-in is computed)")
    else:
        for y in all_years:  # prior year needed for the YoY-drop rule, so score the baseline year too
            if y not in spec_years:
                spec[y] = {"score": None, "reason": hedging[y].get("reason", "unavailable: MD&A unavailable"), "flag": False}
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {y: ex.submit(_score_specificity, y, secinfo[y]["mdna"]) for y in spec_years}
            for y, fu in futs.items():
                try:
                    spec[y] = fu.result()
                except Exception as exc:  # noqa: BLE001
                    spec[y] = {"score": None, "reason": f"unavailable: LLM call failed ({type(exc).__name__})", "flag": False}
        for y in all_years:
            s = spec[y]
            if s.get("score") is None:
                continue
            p = None if (y - 1) in excluded else spec.get(y - 1)
            drop = None
            if p and p.get("score") is not None:
                drop = p["score"] - s["score"]
                s["prior_score"] = p["score"]
                s["drop"] = drop
            s["flag"] = bool(y in analysis_years and y not in excluded and (s["score"] < SPECIFICITY_MIN_SCORE or
                                                      (drop is not None and drop > SPECIFICITY_MAX_DROP)))
        bad = [y for y in analysis_years if spec[y].get("score") is None]
        for y in bad:
            unavailable[f"specificity_scores.{y}"] = spec[y]["reason"]
        if bad:
            degraded.append("language_specificity: no valid LLM score for FY" + ", FY".join(str(y) for y in bad))

    # ---- 5. new legal proceedings -------------------------------------------------------------
    legal = _legal_by_year(secinfo, all_years, excluded)
    for y in analysis_years:
        L = legal[y]
        if L["status"] in ("unavailable", "no_prior_year", "excluded_entity"):
            unavailable[f"new_legal_proceedings.{y}"] = L["reason"]
        elif L.get("confidence") == "low":
            unavailable[f"new_legal_proceedings.{y}"] = f"low confidence ({L['status']}): {L.get('note', '')}"

    # ---- assemble flags / evidence ------------------------------------------------------------
    flags_by_year: dict[int, list[str]] = {y: [] for y in analysis_years}
    evidence: list[dict] = []
    for y in analysis_years:
        if y in excluded:
            continue  # a shell / SPAC predecessor filing is not evidence about the operating company
        h = hedging[y]
        if h.get("flag"):
            flags_by_year[y].append(FLAG_HEDGING)
            up = round(h["yoy_change_pct"])
            pct = round(100 * h["ratio"], 1)
            evidence.append({"flag": FLAG_HEDGING, "year": y, "metric": "hedging_ratio", "value": h["ratio"],
                             "display": f"Hedging-word ratio rose {up}% to {pct}% of MD&A words in FY{y}",
                             "numbers": [up, pct, y]})
        p = passive[y]
        if p.get("flag"):
            flags_by_year[y].append(FLAG_PASSIVE)
            pc = round(p["pct"], 1)
            up = round(p["yoy_change_pct"])
            evidence.append({"flag": FLAG_PASSIVE, "year": y, "metric": "passive_voice_pct", "value": p["pct"],
                             "display": f"Passive-voice share of MD&A sentences rose {up}% to {pc}% in FY{y}",
                             "numbers": [up, pc, y], "informational_weight": "low"})
        r = risk[y]
        if r.get("flag"):
            flags_by_year[y].append(FLAG_RISK)
            up = round(r["yoy_change_pct"])
            evidence.append({"flag": FLAG_RISK, "year": y, "metric": "risk_factor_chars", "value": r["chars"],
                             "display": f"Risk Factors section grew {up}% to {r['chars']:,} characters in FY{y}",
                             "numbers": [up, r["chars"], y]})
        s = spec[y]
        if s.get("flag"):
            flags_by_year[y].append(FLAG_SPECIFICITY)
            parts = []
            nums: list = [s["score"]]
            if s["score"] < SPECIFICITY_MIN_SCORE:
                parts.append(f"MD&A specificity scored {s['score']}/10 in FY{y} (below {SPECIFICITY_MIN_SCORE})")
                nums.append(SPECIFICITY_MIN_SCORE)
            if s.get("drop") is not None and s["drop"] > SPECIFICITY_MAX_DROP:
                parts.append(f"MD&A specificity fell {s['drop']} points to {s['score']}/10 in FY{y}"
                             if not parts else f"down {s['drop']} points from {s['prior_score']}")
                nums += [s["drop"], s["prior_score"]]
            nums.append(y)
            evidence.append({"flag": FLAG_SPECIFICITY, "year": y, "metric": "specificity_score", "value": s["score"],
                             "display": "; ".join(parts) + " (LLM-rated)", "numbers": nums, "source": "llm"})
        L = legal[y]
        if L.get("detected"):
            flags_by_year[y].append(FLAG_LEGAL)
            evidence.append({"flag": FLAG_LEGAL, "year": y, "metric": "new_legal_paragraphs", "value": L["new_units"],
                             "display": f"{L['new_units']} materially new paragraph(s) in the FY{y} Legal Proceedings section "
                                        f"vs FY{y - 1}",
                             "numbers": [L["new_units"], y, y - 1], "text": L["text"],
                             "confidence": L.get("confidence")})

    flags_fired = sum(len(v) for v in flags_by_year.values())
    focus_flags = flags_by_year.get(focus_year, []) if focus_year is not None else []
    n = len(focus_flags)
    severity = "High" if n >= 3 else "Medium" if n == 2 else "Low" if n == 1 else "None"

    # JSON-friendly per-year outputs: spec structure for analysed years + the baseline year
    def spec_view(d: dict[int, dict]) -> dict[int, dict]:
        return {y: d[y] for y in all_years if y in d}

    key_finding = _key_finding(focus_year, focus_flags, hedging, passive, risk, spec, legal, unavailable, evidence)

    result = {
        "hedging_trend": spec_view(hedging),
        "passive_voice": spec_view(passive),
        "risk_factor_length": spec_view(risk),
        "specificity_scores": spec_view(spec),
        "new_legal_proceedings": spec_view({y: {"detected": legal[y]["detected"], "text": legal[y]["text"],
                                                **{k: v for k, v in legal[y].items() if k not in ("detected", "text")}}
                                            for y in legal}),
        "flags_fired": flags_fired,
        "key_finding": key_finding,
        "severity": severity,
        "flags_by_year": flags_by_year,
        "focus_year": focus_year,
        "analysis_years": analysis_years,
        "evidence": evidence,
        "sections": sections,
        "excluded_entity_years": dict(excluded),
        "data_quality": {"unavailable": unavailable},
        "degraded": list(degraded),
        "thresholds": {"hedging_yoy": HEDGING_YOY_THRESHOLD, "passive_yoy": PASSIVE_YOY_THRESHOLD,
                       "risk_factor_yoy": RISK_YOY_THRESHOLD, "specificity_min": SPECIFICITY_MIN_SCORE,
                       "specificity_drop": SPECIFICITY_MAX_DROP},
        "methodology": {"hedging_terms": list(HEDGING_TERMS), "hedging_matching": "literal, word-boundary, case-insensitive",
                        "passive_scope": "MD&A prose sentences only; flag = YoY relative increase > 25% (v2)",
                        "passive_method": f"spacy:{SPACY_MODEL}" if nlp is not None else "rule-based",
                        "specificity_prompt": "agents.language_agent.SPECIFICITY_SYSTEM_PROMPT"},
    }
    return result, degraded


def _key_finding(focus, focus_flags, hedging, passive, risk, spec, legal, unavailable, evidence) -> str:
    if focus is None:
        return "Language analysis unavailable: no filing text for any analysed year."
    ev = {e["flag"]: e for e in evidence if e["year"] == focus}
    for flag in (FLAG_LEGAL, FLAG_SPECIFICITY, FLAG_HEDGING, FLAG_RISK, FLAG_PASSIVE):
        if flag in ev:
            more = len(focus_flags) - 1
            base = ev[flag]["display"]
            if flag == FLAG_LEGAL:
                base = f"A materially new legal proceeding appeared in the FY{focus} Legal Proceedings section"
            tail = f" (plus {more} other language flag{'s' if more > 1 else ''})" if more > 0 else ""
            return base + tail + "."
    n_unavail = sum(1 for k in unavailable if k.endswith(f".{focus}"))
    if n_unavail >= 4:
        return (f"Language forensics largely unavailable for FY{focus} ({n_unavail} of 5 metrics could not be "
                f"computed); no language flags fired on the data that was available.")
    suffix = f"; {n_unavail} metric(s) unavailable" if n_unavail else ""
    return f"No language-forensics flags fired for FY{focus}{suffix}."


def _error_result(msg: str) -> dict:
    return {"error": msg, "unavailable": True, "severity": "None", "flags_fired": 0, "flags_by_year": {},
            "focus_year": None, "evidence": [], "data_quality": {"unavailable": {"language_agent": msg}},
            "degraded": [], "key_finding": f"language unavailable: {msg}"}


def run_language(state: dict) -> dict:
    """AGENT 2 entry point. Sync, never raises. See module docstring."""
    t0 = time.perf_counter()
    started = _now()
    try:
        result, degraded = _analyse(state if isinstance(state, dict) else {})
        status = "degraded" if degraded else "ok"
        summary = result["key_finding"]
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        log.exception("language agent failed")
        msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        result, degraded, status = _error_result(msg), [], "error"
        summary = result["key_finding"]
    trace = {"agent": AGENT_NAME, "status": status, "started": started,
             "duration_ms": int((time.perf_counter() - t0) * 1000), "summary": summary, "degraded": list(degraded)}
    return {"language_result": result, "agent_trace": [trace], "degraded": list(degraded)}
