"""Text extraction and keyword forensics for SEC annual reports (10-K, 10-K405, 10-KSB, 20-F).

This module is pure Python (no network, no LLM).  It consumes the *plain text* of a filing
(HTML already converted to text with tables rendered one row per line using `` | `` separators,
or the raw ``.txt`` of a pre-2001 filing) and extracts the pieces the forensic agents need:

* ``extract_sections``      - MD&A, Risk Factors, Legal Proceedings, related-party disclosures,
                              Item 9 (changes in / disagreements with accountants), the
                              principal-accountant-fee item, the signature page and the
                              financial-statement related-party note.
* ``extract_auditor``       - normalised audit-firm name (``Arthur Andersen LLP`` ...).
* ``extract_signatories``   - CEO / CFO names and titles from the signature page.
* ``extract_audit_fees``    - audit / total fees from an Item 14 / 16C (or proxy) fee table.
* ``keyword_hits``          - regex hits with negation / boilerplate / hypothetical awareness.
* ``detect_restatement``, ``detect_material_weakness``, ``detect_going_concern`` - curated
  signal detectors built on ``keyword_hits``.
* ``build_filing_metadata`` - one dict per filing for ``state["filing_metadata"]``.
* ``normalize_firm_name`` / ``same_firm`` / ``normalize_person_name`` / ``same_person`` -
  name normalisation for auditor / CFO / CEO change detection.

Table-of-contents trap
----------------------
Every ``Item N`` header appears twice: once in the table of contents (TOC) and once in the body.
All candidate headers are collected (a header must begin a line, may be preceded by ``PART X``,
and must not continue in lower case - which would make it a cross-reference such as
"Item 7 of this report").  The span of a candidate runs to the next candidate with a *greater*
item key.  For each item the candidate that is (1) not TOC-like (no trailing page number),
then (2) has the longest content after its header line is selected.  A TOC entry's content is
empty, so the body always wins; if only TOC entries exist the section is reported as not found.

Honesty notes
-------------
* Nothing is invented: a section that cannot be located is ``""`` with ``found[section] = False``.
* ``found`` means "a real (non-TOC) header was located"; ``incorporated_by_reference`` flags
  sections whose body just points elsewhere (typical for Items 10-14 of a 10-K).
* Heuristics (signature parsing, auditor sign-off, fee tables) are validated on real filings in
  ``tests/test_text_parser.py``; they are not guaranteed for every filer.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "html_to_text",
    "extract_sections",
    "extract_auditor",
    "extract_auditor_details",
    "extract_signatories",
    "extract_audit_fees",
    "keyword_hits",
    "detect_restatement",
    "detect_material_weakness",
    "detect_going_concern",
    "detect_merger_context",
    "detect_shell_filing",
    "locate_sections",
    "build_filing_metadata",
    "related_party_measure",
    "normalize_firm_name",
    "firm_network",
    "auditor_changed",
    "same_firm",
    "normalize_person_name",
    "same_person",
    "SECTION_KEYS",
    "V2_SECTION_KEYS",
    "ALL_SECTION_KEYS",
    "RESTATEMENT_PATTERNS",
    "MATERIAL_WEAKNESS_PATTERNS",
    "GOING_CONCERN_PATTERNS",
]

SECTION_KEYS: tuple[str, ...] = (
    "mdna",
    "risk_factors",
    "legal_proceedings",
    "related_party",
    "item9_changes",
    "item14",
    "signatures",
    "notes_rpt",
)
# v2 additions (kept out of SECTION_KEYS so that existing consumers iterating it are unaffected)
V2_SECTION_KEYS: tuple[str, ...] = (
    "legal_note",   # B11: the Commitments & Contingencies / Legal Matters note a thin Item 3 points to
    "controls",     # B1/B12: Item 9A (10-K) / Item 15 (20-F) Controls and Procedures
)
ALL_SECTION_KEYS: tuple[str, ...] = SECTION_KEYS + V2_SECTION_KEYS

# --------------------------------------------------------------------------------------
# Text preparation
# --------------------------------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "section", "center", "pre", "blockquote", "hr",
}
_SGML_TAG_LINE = re.compile(
    r"^[ \t]*</?(?:PAGE|TABLE|CAPTION|S|C|FN|TEXT|DOCUMENT|TYPE|SEQUENCE|FILENAME|DESCRIPTION|PDF|IMS-DOCUMENT)\b[^>\n]*>[ \t]*$",
    re.I | re.M,
)
_SGML_INLINE = re.compile(r"</?[SC]>", re.I)
_HTMLISH = re.compile(r"<(?:html|body|div|table|p|span|font|ix:)\b", re.I)


def _decode_bytes(raw: bytes) -> str:
    """Strict UTF-8, else Windows-1252 (legacy EDGAR HTML/text is cp1252: 0x85 ellipsis, 0x95 bullet).

    v2 (mojibake fix): the previous ``utf-8, errors="replace"`` turned every cp1252 ellipsis / bullet / curly quote
    into U+FFFD.  cp1252 leaves 5 bytes undefined; those (and only those) are dropped.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="ignore")


def html_to_text(raw: str | bytes) -> str:
    """Convert filing HTML (incl. iXBRL) to text; one line per paragraph, one line per table row.

    Table cells are joined with `` | `` (empty cells dropped).  Hidden iXBRL header blocks,
    ``script`` and ``style`` elements are removed.  Used only as a convenience (tests,
    callers that hold raw HTML); the project's EDGAR client has its own converter and
    ``extract_*`` functions accept either.
    """
    if isinstance(raw, bytes):
        raw = _decode_bytes(raw)
    try:
        import lxml.html  # type: ignore

        body = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw, count=1)
        doc = lxml.html.fromstring(body)
        for bad in doc.xpath("//script|//style|//head"):
            bad.drop_tree()
        for bad in doc.xpath("//*[starts-with(name(),'ix:header')]"):
            bad.drop_tree()
        for el in doc.xpath("//*[contains(translate(@style,' ',''),'display:none')]"):
            el.drop_tree()
        for tr in reversed(doc.xpath("//tr")):
            cells = []
            for td in tr.xpath("./td|./th"):
                t = re.sub(r"\s+", " ", td.text_content()).strip()
                if t:
                    cells.append(t)
            tail = tr.tail
            for child in list(tr):
                tr.remove(child)
            tr.text = " | ".join(cells)
            tr.tail = tail
        for el in doc.iter():
            if isinstance(el.tag, str) and el.tag in _BLOCK_TAGS:
                el.text = "\n" + (el.text or "")
                el.tail = "\n" + (el.tail or "")
        text = doc.text_content()
    except Exception:  # pragma: no cover - lxml missing / malformed HTML
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        text = re.sub(r"(?i)</?(?:p|div|br|tr|li|h\d)[^>]*>", "\n", text)
        text = re.sub(r"(?i)</t[dh]>", " | ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as _html

        text = _html.unescape(text)
    # numeric references in the 0x80-0x9f range are Windows-1252 punctuation (curly quotes, dashes)
    text = text.translate({c: bytes([c]).decode("cp1252", errors="replace") for c in range(0x80, 0xA0) if c not in (0x81, 0x8D, 0x8F, 0x90, 0x9D)})
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"[ ]*\n[ ]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# C1 control characters (U+0080-U+009F) are never text: in EDGAR filings they are Windows-1252 bytes that were decoded as
# Latin-1 (0x85 ellipsis, 0x92 apostrophe, 0x93/0x94 quotes, 0x95 bullet, 0x96/0x97 dashes).  Rendered by a UTF-8 or cp1252 viewer
# they show as the replacement-glyph "mojibake" the evaluation report exhibited at excerpt truncation (ellipsis / bullet).
_C1_MAP = {c: (bytes([c]).decode("cp1252", errors="ignore")) for c in range(0x80, 0xA0)}


def _prepare(text: str | None) -> str:
    """Normalise newlines, strip SGML page/table tags, convert raw HTML if given."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    head = text[:4000]
    if _HTMLISH.search(head) and head.count("<") > 20:
        text = html_to_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace("\f", "\n")
    if "�" in text:   # undecodable byte upstream: never let a replacement char reach an excerpt
        text = text.replace("�", "")
    text = text.translate(_C1_MAP)
    text = _SGML_TAG_LINE.sub("", text)
    text = _SGML_INLINE.sub("", text)
    return text


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------------------
# Item header detection
# --------------------------------------------------------------------------------------

_ITEM_RE = re.compile(
    r"^[^\w\n]{0,8}(?:PART[ \t]+[IV]+[^\w\n]{0,8})?ITEM[ \t]*(\d{1,2})[ \t]*(?:[.\-–—][ \t]*)?([A-Ha-h])?(?![A-Za-z0-9])(?P<rest>[^\n]*)$",
    re.I | re.M,
)
_TOC_PAGE_END = re.compile(r"(?:\|\s*|\s{2,}|\.{3,}\s*|\s)(?:\d{1,3}|[A-Z]-\d{1,3})\s*$")
_LOWER_START = re.compile(r"^[a-z]")


class _Header:
    __slots__ = ("pos", "line_end", "num", "letter", "title", "toc_like", "key")

    def __init__(self, pos: int, line_end: int, num: int, letter: str, title: str, toc_like: bool):
        self.pos = pos
        self.line_end = line_end
        self.num = num
        self.letter = letter
        self.title = title
        self.toc_like = toc_like
        self.key = (num, letter)

    @property
    def item_id(self) -> str:
        return f"{self.num}{self.letter}"


def _find_headers(text: str) -> list[_Header]:
    """All plausible ``Item N`` header lines (TOC and body), in document order."""
    out: list[_Header] = []
    for m in _ITEM_RE.finditer(text):
        rest = m.group("rest")
        stripped = rest.lstrip(" \t|.:–—-")
        if rest[:1] in {",", ")", ";"}:  # "Item 1A, Risk Factors," style cross reference
            continue
        if stripped[:1].islower():  # "Item 7 of this report ..." cross reference
            continue
        num = int(m.group(1))
        if num == 0 or num > 25:
            continue
        letter = (m.group(2) or "").upper()
        line_end = m.end()
        title = _collapse(rest.strip(" \t|.:–—-"))
        nxt_start = line_end + 1
        nxt_end = text.find("\n", nxt_start)
        nxt = text[nxt_start: nxt_end if nxt_end != -1 else len(text)].strip()
        toc_like = bool(_TOC_PAGE_END.search(rest.rstrip()))
        if not toc_like and nxt and len(nxt) < 120 and not _ITEM_RE.match(nxt) and _TOC_PAGE_END.search(nxt):
            # wrapped TOC entry: "Item 9. Changes in and Disagreements with Accountants\n and Financial Disclosure ....48"
            if len(title) < 120 and re.search(r"\.{2,}\s*(?:\d{1,3}|[A-Z]-\d{1,3})\s*$|\s{3,}\d{1,3}\s*$", nxt):
                toc_like = True
        if len(title) < 60 and nxt and not _ITEM_RE.match(nxt) and len(nxt) < 90:
            title = _collapse(title + " " + nxt)
        out.append(_Header(m.start(), line_end, num, letter, title, toc_like))
        if len(out) > 1500:
            break
    return out


class _Span:
    __slots__ = ("start", "end", "header", "content_start")

    def __init__(self, start: int, end: int, header: Optional[_Header], content_start: int):
        self.start = start
        self.end = end
        self.header = header
        self.content_start = content_start

    def text(self, src: str) -> str:
        return src[self.content_start: self.end].strip()


def _strip_title_wrap(text: str, header: _Header) -> int:
    """Return content start after header line (+ wrapped upper-case title continuation)."""
    start = min(header.line_end + 1, len(text))
    nl = text.find("\n", start)
    nxt = text[start: nl if nl != -1 else len(text)].strip()
    if nxt and len(nxt) < 90 and nxt.upper() == nxt and re.search(r"[A-Z]{3}", nxt) and not nxt.endswith((".", ":")):
        if not header.title.rstrip().endswith((".",)) and len(header.title) < 140:
            if nl != -1:
                return nl + 1
    return start


def _spans_for(text: str, headers: list[_Header]) -> dict[str, list[_Span]]:
    """Map item id -> candidate spans; a span ends at the next header with a greater key."""
    spans: dict[str, list[_Span]] = {}
    n = len(headers)
    for i, h in enumerate(headers):
        end = len(text)
        for j in range(i + 1, n):
            if headers[j].key > h.key:
                end = headers[j].pos
                break
        spans.setdefault(h.item_id, []).append(_Span(h.pos, end, h, _strip_title_wrap(text, h)))
    return spans


def _choose(spans: list[_Span], text: str, title_must: Optional[re.Pattern] = None) -> Optional[_Span]:
    """Best body candidate: non-TOC first, then longest content, then latest."""
    best: Optional[_Span] = None
    best_key: tuple = ()
    for sp in spans:
        h = sp.header
        assert h is not None
        if title_must is not None and not title_must.search(h.title):
            continue
        content_len = len(text[sp.content_start: sp.end].strip())
        key = (0 if h.toc_like else 1, 1 if content_len > 0 else 0, content_len, sp.start)
        if best is None or key > best_key:
            best, best_key = sp, key
    if best is None:
        return None
    if best.header is not None and best.header.toc_like:
        return None  # only TOC entries exist: not a real section
    if len(text[best.content_start: best.end].strip()) == 0:
        return None
    return best


# --------------------------------------------------------------------------------------
# Heading based helpers (sub-sections / fallbacks)
# --------------------------------------------------------------------------------------

_END_MDNA = re.compile(
    r"^[^\w\n]*(?:item\s*7\s*a\b|item\s*8\b|quantitative\s+and\s+qualitative\s+disclosures?|"
    r"report\s+of\s+independent|independent\s+(?:registered\s+)?(?:public\s+)?(?:accountants|auditors)|"
    r"consolidated\s+(?:balance\s+sheets?|statements?\s+of)|notes\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial)",
    re.I | re.M,
)
_MDNA_HEADING = re.compile(
    r"^[^\w\n]*(?:item\s*7\.?[^\w\n]*)?management.{0,3}s\s+discussion\s+and\s+analysis(?:\s+of\s+(?:consolidated\s+)?(?:financial\s+condition|results)[^\n]{0,80})?[^\w\n]*$",
    re.I | re.M,
)
_RISK_HEADING = re.compile(
    r"^[^\w\n]*(?:item\s*1\s*a\.?[^\w\n]*)?(?:risk\s+factors|factors\s+(?:that\s+)?(?:may\s+)?affect(?:ing)?\s+(?:our\s+)?(?:future\s+)?(?:results|performance|operating\s+results)[^\n]{0,60})[^\w\n]*$",
    re.I | re.M,
)
_INCORP_REF = re.compile(
    r"incorporated\s+(?:herein\s+)?by\s+reference|incorporated\s+into\s+this|set\s+forth\s+(?:in|under)\s+(?:the\s+)?(?:company.s\s+)?(?:definitive\s+)?proxy|"
    r"will\s+be\s+(?:contained|included|set\s+forth|filed)|to\s+be\s+(?:included|filed|contained)|annual\s+report\s+to\s+(?:share|stock)holders|"
    r"is\s+(?:included|contained)\s+in\s+(?:the\s+)?(?:company.s\s+)?(?:definitive\s+)?proxy|"
    r"\bsee\b[^.]{0,80}\bnote\s+\d|\bsee\s+item\s+\d|refer\s+to\s+note|(?:included|described|discussed)\s+in\s+note\s+\d",
    re.I,
)


def _heading_lines(text: str, rx: re.Pattern, max_len: int = 160) -> list[re.Match]:
    out = []
    for m in rx.finditer(text):
        line = m.group(0).strip()
        if len(line) > max_len or _TOC_PAGE_END.search(line):
            continue
        out.append(m)
    return out


def _heading_fallback_mdna(text: str) -> Optional[tuple[int, int]]:
    best: Optional[tuple[int, int]] = None
    for m in _heading_lines(text, _MDNA_HEADING):
        start = m.end()
        end_m = None
        for em in _END_MDNA.finditer(text, start + 1500):
            end_m = em
            break
        end = end_m.start() if end_m else min(len(text), start + 120_000)
        if best is None or (end - start) > (best[1] - best[0]):
            best = (start, end)
    return best


def _heading_fallback_risk(text: str) -> Optional[tuple[int, int]]:
    best: Optional[tuple[int, int]] = None
    stop = re.compile(r"^[^\w\n]*(?:item\s*\d|unresolved\s+staff|properties$|legal\s+proceedings$)", re.I | re.M)
    for m in _heading_lines(text, _RISK_HEADING, 120):
        start = m.end()
        sm = stop.search(text, start + 800)
        end = sm.start() if sm else min(len(text), start + 40_000)
        end = min(end, start + 80_000)
        if end - start >= 1500 and (best is None or (end - start) > (best[1] - best[0])):
            best = (start, end)
    return best


# --------------------------------------------------------------------------------------
# Section extraction
# --------------------------------------------------------------------------------------

_NOTE_RPT_HEADING = re.compile(
    r"^[^\w\n]{0,4}(?:note\s*)?\(?(\d{1,2})\)?[\s.:)\-–—]*\s*related[\s-]*part(?:y|ies)(?:\s+(?:transactions?|matters|disclosures?|balances(?:\s+and\s+transactions)?))?[^\w\n]*$",
    re.I | re.M,
)
_NOTE_ANY_HEADING = re.compile(
    r"^[^\w\n]{0,4}(?:note\s*)?\(?(\d{1,2})\)?[\s.:)\-–—]+\s*[A-Z][A-Za-z ,&/'’()\-–]{3,90}[^\w\n]*$",
    re.I | re.M,
)
_RPT_BARE_HEADING = re.compile(
    r"^[^\w\n]*related[\s-]*part(?:y|ies)(?:\s+(?:transactions?|matters))?[^\w\n]*$", re.I | re.M
)


def _extract_notes_rpt(text: str) -> str:
    """Financial-statement note headed 'Related Party Transactions' (numbered note preferred)."""
    best = ""
    for m in _NOTE_RPT_HEADING.finditer(text):
        line = m.group(0).strip()
        if len(line) > 100 or _TOC_PAGE_END.search(line.replace(m.group(1), "", 1)) and "|" in line:
            continue
        num = int(m.group(1))
        start = m.end()
        end = min(len(text), start + 25_000)
        for nm in _NOTE_ANY_HEADING.finditer(text, start + 1, end):
            try:
                n2 = int(nm.group(1))
            except ValueError:
                continue
            if n2 != num and nm.group(0).strip() != line and not re.search(r"related[\s-]*part", nm.group(0), re.I):
                end = nm.start()
                break
        body = text[start:end].strip()
        if len(body) > len(best):
            best = body
    if best:
        return best
    for m in _RPT_BARE_HEADING.finditer(text):
        line = m.group(0).strip()
        if len(line) > 60:
            continue
        body = text[m.end(): m.end() + 15_000].strip()
        stop = re.search(r"\n(?:item\s*\d|note\s*\d|\d{1,2}\.\s+[A-Z])", body, re.I)
        if stop and stop.start() > 200:
            body = body[: stop.start()]
        if len(body) > len(best):
            best = body
    return best


# --------------------------------------------------------------------------------------
# Legal Proceedings note (v2, B11)
# --------------------------------------------------------------------------------------

_LEGAL_NOTE_HEADING = re.compile(
    r"^[^\w\n]{0,4}(?:note\s*)?\(?(\d{1,2}(?:[ ]\d)?)\)?[\s.:)|\-–—]*\s*(?P<title>[A-Za-z][A-Za-z ,&/'’()\-–—]{3,110}?)[^\w\n]*$",
    re.I | re.M,
)
_LEGAL_TITLE_RANK = [
    (re.compile(r"legal|litigation|lawsuit|proceedings", re.I), 3),
    (re.compile(r"conti\w*gen", re.I), 2),
    (re.compile(r"^\W*commitments\W*$", re.I), 1),
]
_NOTE_REF = re.compile(r"\bnotes?\s+(\d{1,2})\b", re.I)


def _legal_title_rank(title: str) -> int:
    for rx, rk in _LEGAL_TITLE_RANK:
        if rx.search(title):
            return rk
    return 0


def _extract_legal_note(text: str, pointer_text: str = "") -> Optional[dict[str, Any]]:
    """The financial-statement note that carries the real litigation disclosure (Commitments and Contingencies / Legal
    Matters / Litigation).  Preferred: the note number the Item 3 / 8.A.7 pointer names ("see Note 14"); else the
    best-titled note.  Returns ``{"text", "note", "title", "via_pointer"}`` or ``None``."""
    want = None
    m = _NOTE_REF.search(pointer_text or "")
    if m:
        want = int(m.group(1))
    best: Optional[dict[str, Any]] = None
    best_key: tuple = ()
    for hm in _LEGAL_NOTE_HEADING.finditer(text):
        line = hm.group(0).strip()
        if len(line) > 130:
            continue
        if re.search(r"item\s*$", text[max(0, hm.start() - 12): hm.start()], re.I):   # wrapped "ITEM\n3. LEGAL PROCEEDINGS" header
            continue
        num = int(hm.group(1).replace(" ", ""))
        title = hm.group("title").strip()
        rank = _legal_title_rank(title)
        via_ptr = want is not None and num == want and rank > 0
        if rank == 0 or (rank == 1 and not via_ptr):
            continue
        start = hm.end()
        end = min(len(text), start + 60_000)
        for nm in _NOTE_ANY_HEADING.finditer(text, start + 200, end):
            try:
                n2 = int(nm.group(1))
            except ValueError:
                continue
            if n2 == num + 1:
                end = nm.start()
                break
        body = text[start:end].strip()
        if len(body) < 150:
            continue
        key = (1 if via_ptr else 0, rank, len(body))
        if best is None or key > best_key:
            best, best_key = {"text": body, "note": num, "title": title, "via_pointer": via_ptr}, key
    return best


_SIG_HEADING = re.compile(r"^[^\w\n]*SIGNATURES?[^\w\n]*$", re.I | re.M)
_SIG_QUALIFIER = re.compile(r"pursuant\s+to\s+the\s+requirements|duly\s+caused|hereby\s+certifies", re.I)
_SIG_END = re.compile(
    r"^[^\w\n]*(?:index\s+to\s+(?:consolidated\s+)?financial\s+statements|exhibit\s+index|index\s+to\s+exhibits|report\s+of\s+independent|"
    r"consolidated\s+financial\s+statements\s*$)",
    re.I | re.M,
)


def _signature_section(text: str) -> str:
    cands = []
    for m in _SIG_HEADING.finditer(text):
        if _SIG_QUALIFIER.search(text[m.end(): m.end() + 3500]):
            cands.append(m)
    if not cands:
        return ""
    n = len(text)
    chosen = next((m for m in cands if m.start() > 0.3 * n), cands[-1])
    start = chosen.start()
    end = min(n, start + 16_000)
    em = _SIG_END.search(text, start + 400, end)
    if em:
        end = em.start()
    return text[start:end].strip()


def _form_family(form: Optional[str], text: str) -> str:
    f = (form or "").upper().strip()
    if f.startswith("20-F") or f.startswith("20F"):
        return "20-F"
    if f.startswith("40-F"):
        return "40-F"
    if f.startswith("10-KSB") or f.startswith("10KSB"):
        return "10-KSB"
    if f.startswith("10-K") or f.startswith("10K"):
        return "10-K"
    head = text[:6000].upper()
    if "FORM 20-F" in head:
        return "20-F"
    if "FORM 40-F" in head:
        return "40-F"
    return "10-K"


_ITEM14_TITLE = re.compile(r"account(?:ant|ing)|auditor", re.I)
_RPT_TITLE = re.compile(r"relationship|related", re.I)


def _empty_result() -> dict[str, Any]:
    return {
        **{k: "" for k in ALL_SECTION_KEYS},
        "found": {k: False for k in ALL_SECTION_KEYS},
        "method": "none",
        "method_by_section": {},
        "incorporated_by_reference": {k: False for k in ALL_SECTION_KEYS},
        "form": "",
        "warnings": [],
        "legal_note_info": None,
    }


_PART_LINE = re.compile(r"^[ \t]*PART[ \t]+[IV]+[ \t]*$", re.I | re.M)
_TAIL_JUNK = re.compile(
    r"(?:\n[ \t]*(?:table\s+of\s+contents|F-\d+|\d{1,3}|[^\n|]{0,60}\|\s*(?:\d{4}\s+)?(?:form\s+10-?k\s*\|\s*)?\d{1,3})[ \t]*)+\s*$",
    re.I,
)


def _trim_section(content: str) -> str:
    """Drop a trailing 'PART III' divider, page footers and 'Table of Contents' lines."""
    m = _PART_LINE.search(content, 1)
    if m:
        content = content[: m.start()]
    return _TAIL_JUNK.sub("", content.rstrip()).strip()


def _set(res: dict[str, Any], key: str, content: str, method: str) -> None:
    content = content.strip()
    if key not in {"signatures", "notes_rpt"}:
        content = _trim_section(content)
    if not content:
        return
    res[key] = content
    res["found"][key] = True
    res["method_by_section"][key] = method
    res["incorporated_by_reference"][key] = bool(_INCORP_REF.search(content[:700])) and len(content) < 2500


def _sub_span(text: str, outer_start: int, outer_end: int, start_rx: re.Pattern, end_rx: Optional[re.Pattern]) -> Optional[tuple[int, int]]:
    m = start_rx.search(text, outer_start, outer_end)
    if not m:
        return None
    s = m.end()
    e = outer_end
    if end_rx is not None:
        em = end_rx.search(text, s, outer_end)
        if em:
            e = em.start()
    return s, e


def extract_sections(text: str, form: Optional[str] = None) -> dict[str, Any]:
    """Extract the forensic sections of an annual report.

    Returns a dict with string values (``""`` when not found) for ``mdna``, ``risk_factors``,
    ``legal_proceedings``, ``related_party`` (Item 13 / 20-F Item 7.B), ``item9_changes``
    (Item 9 / 20-F Item 16F), ``item14`` (Principal Accountant Fees; 10-K Item 14 / 20-F 16C),
    ``signatures`` and ``notes_rpt`` (financial-statement related-party note), plus:

    * ``found``: ``{section: bool}``
    * ``method``: summary string, ``method_by_section``: ``{section: "item-headers" | ...}``
    * ``incorporated_by_reference``: ``{section: bool}`` (body merely points elsewhere)
    * ``form``: detected form family (10-K, 10-KSB, 20-F, 40-F), ``warnings``

    v2 additions (existing keys unchanged; ``SECTION_KEYS`` is unchanged, the new keys are in ``V2_SECTION_KEYS``):
    ``legal_note`` - the financial-statement note with the real litigation disclosure (Commitments and Contingencies / Legal
    Matters / Litigation), preferring the note number an Item 3 / 8.A.7 pointer names ("see Note 14"); ``legal_note_info``
    ``{"note", "title", "via_pointer", "legal_proceedings_is_pointer"}`` (or ``None``); ``controls`` - Item 9A (10-K) / Item 15
    (20-F) Controls and Procedures.

    Mapping - 10-K/10-K405: Item 7 / 1A / 3 / 13 / 9 / 14 (14 only if titled "Principal Accountant
    Fees"; before FY2003 Item 14 was Exhibits, so it is reported not found).  10-KSB: Items 6 / - / 3 /
    12 / 8.  20-F: Item 5 (Operating & Financial Review = MD&A), Item 3.D (risk factors), Item
    8.A.7 (legal proceedings), Item 7.B (related party), Item 16.F (change in certifying accountant),
    Item 16.C (accountant fees).
    """
    res = _empty_result()
    t = _prepare(text)
    fam = _form_family(form, t)
    res["form"] = fam
    if not t.strip():
        res["warnings"].append("empty text")
        return res

    headers = _find_headers(t)
    spans = _spans_for(t, headers)

    def item(item_id: str, title_must: Optional[re.Pattern] = None) -> Optional[_Span]:
        return _choose(spans.get(item_id, []), t, title_must)

    methods: set[str] = set()

    if fam == "20-F":
        sp = item("5")
        if sp:
            _set(res, "mdna", sp.text(t), "item-headers")
        sp3 = item("3")
        if sp3:
            rf_rx = re.compile(r"^[^\w\n]{0,3}(?:(?:item\s*)?3\s*\.?\s*)?D\s*[.):]\s*risk\s+factors[^\n]*$", re.I | re.M)
            sub = _sub_span(t, sp3.content_start, sp3.end, rf_rx, None)
            if sub:
                _set(res, "risk_factors", t[sub[0]: sub[1]], "item-headers+subitem(3.D)")
            else:
                bare = re.compile(r"^[^\w\n]*risk\s+factors[^\w\n]*$", re.I | re.M)
                sub = _sub_span(t, sp3.content_start, sp3.end, bare, None)
                if sub:
                    _set(res, "risk_factors", t[sub[0]: sub[1]], "item-headers+heading(Risk Factors)")
        sp8 = item("8")
        if sp8:
            lp_rx = re.compile(r"^[^\w\n]{0,3}(?:(?:item\s*)?8\s*\.?\s*A\s*\.?\s*7\s*\.?\s*)?legal\s+(?:and\s+administrative\s+)?proceedings[^\w\n]*$", re.I | re.M)
            end_rx = re.compile(
                r"^[^\w\n]{0,3}(?:8\s*\.\s*B\b|B\s*\.\s*significant\s+changes|dividend\s+(?:policy|distribution)|significant\s+changes)", re.I | re.M
            )
            sub = _sub_span(t, sp8.content_start, sp8.end, lp_rx, end_rx)
            if sub and t[sub[0]: sub[1]].strip():
                _set(res, "legal_proceedings", t[sub[0]: sub[1]], "item-headers+subitem(8.A.7)")
            else:
                sub = _sub_span(t, sp8.content_start, sp8.end, re.compile(r"^[^\w\n]{0,3}8\s*\.\s*A\b[^\n]*$", re.I | re.M), end_rx)
                if sub and t[sub[0]: sub[1]].strip():
                    _set(res, "legal_proceedings", t[sub[0]: sub[1]], "item-headers+subitem(8.A)")
        sp7 = item("7")
        if sp7:
            rp_rx = re.compile(r"^[^\w\n]{0,3}(?:(?:item\s*)?7\s*\.?\s*)?B\s*[.):]\s*related[\s-]*part(?:y|ies)[^\n]*$", re.I | re.M)
            end_rx7 = re.compile(r"^[^\w\n]{0,3}(?:(?:item\s*)?7\s*\.?\s*)?C\s*[.):]\s*interests\s+of\s+experts", re.I | re.M)
            sub = _sub_span(t, sp7.content_start, sp7.end, rp_rx, end_rx7)
            if sub:
                _set(res, "related_party", t[sub[0]: sub[1]], "item-headers+subitem(7.B)")
            else:
                _set(res, "related_party", sp7.text(t), "item-headers(7 whole)")
        sp = item("16F") or item("16.F")
        if sp:
            _set(res, "item9_changes", sp.text(t), "item-headers(16F)")
        sp = item("16C", _ITEM14_TITLE)
        if sp:
            _set(res, "item14", sp.text(t), "item-headers(16C)")
        if res["found"]["mdna"] or res["found"]["risk_factors"]:
            methods.add("item-headers")
    else:
        if fam == "10-KSB":
            plan = {"mdna": ("6", None), "legal_proceedings": ("3", None), "related_party": ("12", _RPT_TITLE), "item9_changes": ("8", None)}
        else:
            plan = {
                "mdna": ("7", None),
                "risk_factors": ("1A", None),
                "legal_proceedings": ("3", None),
                "related_party": ("13", _RPT_TITLE),
                "item9_changes": ("9", None),
                "item14": ("14", _ITEM14_TITLE),
            }
        for key, (iid, title_rx) in plan.items():
            sp = item(iid, title_rx)
            if sp:
                _set(res, key, sp.text(t), "item-headers")
                methods.add("item-headers")
        # MD&A fallback: missing, or merely incorporated by reference / suspiciously short
        need_fb = (not res["found"]["mdna"]) or (
            len(res["mdna"]) < 2500 and _INCORP_REF.search(res["mdna"][:900]) is not None
        )
        if need_fb:
            fb = _heading_fallback_mdna(t)
            if fb and (fb[1] - fb[0]) > max(2500, len(res["mdna"]) * 2):
                res["mdna"] = ""
                res["found"]["mdna"] = False
                _set(res, "mdna", t[fb[0]: fb[1]], "heading-fallback")
                methods.add("heading-fallback")
        if fam != "10-KSB" and not res["found"]["risk_factors"]:
            fb = _heading_fallback_risk(t)
            if fb:
                _set(res, "risk_factors", t[fb[0]: fb[1]], "heading-fallback")
                methods.add("heading-fallback")

    sig = _signature_section(t)
    if sig:
        _set(res, "signatures", sig, "signature-heading")
        res["incorporated_by_reference"]["signatures"] = False
    notes = _extract_notes_rpt(t)
    if notes:
        _set(res, "notes_rpt", notes, "note-heading")
        res["incorporated_by_reference"]["notes_rpt"] = False
    # v2 additions ----------------------------------------------------------------------------------------
    sp_ctl = item("15" if fam == "20-F" else "9A", re.compile(r"control", re.I))
    if sp_ctl:
        _set(res, "controls", sp_ctl.text(t), "item-headers")
        res["incorporated_by_reference"]["controls"] = False
    try:
        ln = _extract_legal_note(t, res["legal_proceedings"])
    except Exception as exc:  # pragma: no cover - defensive
        ln = None
        res["warnings"].append(f"legal_note failed: {exc!r}")
    if ln:
        _set(res, "legal_note", ln["text"], f"note-heading(note {ln['note']}{'; named by the Item 3 pointer' if ln['via_pointer'] else ''})")
        res["incorporated_by_reference"]["legal_note"] = False
        res["legal_note_info"] = {"note": ln["note"], "title": ln["title"], "via_pointer": ln["via_pointer"],
                                  "legal_proceedings_is_pointer": bool(res["incorporated_by_reference"].get("legal_proceedings"))}
    res["method"] = "+".join(sorted(methods)) if methods else "none"
    return res


# --------------------------------------------------------------------------------------
# Firm-name normalisation
# --------------------------------------------------------------------------------------

_SUFFIX_RE = r"(?:LLP|L\.L\.P\.|LLC|P\.?C\.?|Ltd\.?|Limited|PLLC|Inc\.?|S\.?C\.?|SC)"

# (canonical base, network family, regex on lower-case text, default suffix)
_FIRMS: list[tuple[str, str, str, str]] = [
    ("Arthur Andersen", "Arthur Andersen", r"arthur\s+andersen(?:\s*(?:&|and)\s*co\.?)?", "LLP"),
    ("PricewaterhouseCoopers", "PricewaterhouseCoopers", r"pricewaterhouse\s*coopers|price\s*waterhouse\s*coopers|\bpwc\b", "LLP"),
    ("Price Waterhouse", "PricewaterhouseCoopers", r"price\s+waterhouse(?!\s*coopers)", "LLP"),
    ("Coopers & Lybrand", "PricewaterhouseCoopers", r"coopers\s*(?:&|and)\s*lybrand", "LLP"),
    ("Ernst & Young", "Ernst & Young", r"ernst\s*(?:&|&amp;|and)\s*young|\be\s*&\s*y\b", "LLP"),
    ("KPMG", "KPMG", r"kpmg(?:\s+peat\s+marwick)?", "LLP"),
    ("Deloitte & Touche", "Deloitte", r"deloitte\s*(?:&|&amp;|and)\s*touche(?:\s+tohmatsu)?|deloitte\s+touche\s+tohmatsu|deloitte\s+(?:&|and)\s+touche|deloitte(?!\s*(?:&|and)\s*touche)", "LLP"),
    ("Grant Thornton", "Grant Thornton", r"grant\s+thornton", "LLP"),
    ("BDO USA", "BDO", r"bdo\s+usa|bdo\s+seidman|\bbdo\b", "LLP"),
    ("RSM US", "RSM", r"rsm\s+us|mcgladrey(?:\s*(?:&|and)\s*pullen)?|\brsm\b", "LLP"),
    ("Crowe", "Crowe", r"crowe(?:\s+horwath)?", "LLP"),
    ("Moss Adams", "Moss Adams", r"moss\s+adams", "LLP"),
    ("Marcum Bernstein & Pinchuk", "Marcum Bernstein & Pinchuk", r"marcum\s+bernstein\s*(?:&|and)\s*pinchuk", "LLP"),
    ("Marcum", "Marcum", r"marcum(?!\s+bernstein)", "LLP"),
    ("Baker Tilly", "Baker Tilly", r"baker\s+tilly(?:\s+us)?", "LLP"),
    ("MaloneBailey", "MaloneBailey", r"malone\s*bailey", "LLP"),
    ("Mazars", "Mazars", r"mazars(?:\s+usa)?", "LLP"),
    ("Friedman", "Friedman", r"friedman(?!\s+(?:billings|&))", "LLP"),
    ("WithumSmith+Brown", "Withum", r"withum\s*smith\s*\+?\s*brown|\bwithum\b", "PC"),
    ("Cherry Bekaert", "Cherry Bekaert", r"cherry\s+bekaert", "LLP"),
    ("Plante & Moran", "Plante Moran", r"plante\s*(?:&|and)\s*moran", "PLLC"),
    ("Eide Bailly", "Eide Bailly", r"eide\s+bailly", "LLP"),
    ("Haskell & White", "Haskell & White", r"haskell\s*(?:&|and)\s*white", "LLP"),
    ("CohnReznick", "CohnReznick", r"cohn\s*reznick", "LLP"),
    ("EisnerAmper", "EisnerAmper", r"eisner\s*amper", "LLP"),
    ("Centurion ZD CPA & Co.", "Centurion ZD", r"centurion\s+zd\s+cpa(?:\s*(?:&|and)\s*co\.?)?", ""),
    ("Dixon Hughes Goodman", "Dixon Hughes Goodman", r"dixon\s+hughes\s+goodman", "LLP"),
    ("Frazier & Deeter", "Frazier & Deeter", r"frazier\s*(?:&|and)\s*deeter", "LLC"),
    ("Squar Milner", "Squar Milner", r"squar\s+milner", "LLP"),
    ("Armanino", "Armanino", r"armanino", "LLP"),
]
_FIRM_COMPILED = [(c, fam, re.compile(rx, re.I), suf) for c, fam, rx, suf in _FIRMS]
_REGION_STOP = {
    "llp", "llc", "pc", "p.c.", "ltd", "ltd.", "limited", "pllc", "inc", "inc.", "and", "the", "of", "a", "an", "certified",
    "public", "accountants", "registered", "independent", "auditors", "chartered", "cpa", "cpas", "special", "general", "partnership",
    "us", "usa",
}
_REGION_ALIASES = {"hua ming": "Hua Ming", "huaming": "Hua Ming", "hua zhen": "Huazhen", "huazhen": "Huazhen", "zhong tian": "Zhong Tian",
                   "zhongtian": "Zhong Tian", "hong kong": "Hong Kong", "touche tohmatsu": ""}

# Known firm names appear as a whole line (sign-off) or after "/s/".
_ANY_FIRM_RX = re.compile("|".join(f"(?:{rx})" for _, _, rx, _ in _FIRMS), re.I)


def _clean_firm_raw(name: str) -> str:
    n = name.replace("&amp;", "&")
    n = re.sub(r"^[^\w]*/s/\s*", "", n.strip(), flags=re.I)
    n = re.sub(r"\(.*?\)", " ", n)  # "(Special General Partnership)"
    n = n.replace("|", " ")
    return _collapse(n)


def _suffix_from(raw_tail: str) -> str:
    m = re.match(r"\s*[,]?\s*(LLP|L\.L\.P\.|LLC|P\.?C\.?|PLLC|Ltd\.?|Limited)\b", raw_tail, re.I)
    if not m:
        return ""
    s = m.group(1).upper().replace(".", "")
    return {"LLP": "LLP", "LLC": "LLC", "PC": "P.C.", "PLLC": "PLLC", "LTD": "Ltd.", "LIMITED": "Limited"}.get(s, m.group(1))


def normalize_firm_name(name: Optional[str]) -> Optional[str]:
    """Normalise an audit-firm name (case, punctuation, city suffix, spelling variants).

    Examples: ``"ARTHUR ANDERSEN LLP"`` -> ``"Arthur Andersen LLP"``; ``"PricewaterhouseCoopers"`` ->
    ``"PricewaterhouseCoopers LLP"``; ``"Ernst & Young Hua Ming LLP"`` is preserved (regional member
    firm kept); ``"KPMG Hua Zhen LLP (Special General Partnership)"`` -> ``"KPMG Huazhen LLP"``.
    Unknown firms are returned tidied (``/s/`` removed, whitespace collapsed, trailing city dropped
    after the legal suffix).  Returns ``None`` for empty input.
    """
    if not name or not str(name).strip():
        return None
    raw = _clean_firm_raw(str(name))
    if not raw:
        return None
    for canon, _fam, rx, default_suffix in _FIRM_COMPILED:
        m = rx.search(raw)
        if not m:
            continue
        tail = raw[m.end():]
        # words between the base name and the legal suffix are regional qualifiers (Hua Ming, Zhong Tian ...)
        region_words: list[str] = []
        suffix = ""
        mm = re.match(r"\s*(?:[,\-]\s*)?((?:[A-Za-z][A-Za-z.]*\s*){0,3}?)\s*[,]?\s*(LLP|L\.L\.P\.|LLC|P\.?C\.?|PLLC|Ltd\.?|Limited)\b", tail, re.I)
        if mm:
            words = mm.group(1).split()
            region_words = [w for w in words if w.lower().strip(".,") not in _REGION_STOP]
            suffix = _suffix_from(tail[mm.start(2) - 0:]) if False else {"LLP": "LLP", "L.L.P.": "LLP", "LLC": "LLC", "PLLC": "PLLC", "LTD": "Ltd.", "LIMITED": "Limited"}.get(
                mm.group(2).upper().replace(" ", ""), "P.C." if mm.group(2).upper().replace(".", "") == "PC" else mm.group(2)
            )
        else:
            words = []
        region = _collapse(" ".join(region_words))
        region = _REGION_ALIASES.get(region.lower(), region)
        if canon == "Deloitte & Touche" and re.search(r"tohmatsu", raw[m.start(): m.end() + 20], re.I) and not region:
            region = ""
        base = canon
        if canon == "BDO USA" and re.search(r"seidman", raw, re.I):
            base = "BDO Seidman"
            if not suffix:
                suffix = "LLP"
        if not suffix:
            suffix = default_suffix
        if canon == "BDO USA" and suffix == "LLP" and re.search(r"p\.?c\.?\b", tail[:30], re.I):
            suffix = "P.C."
        parts = [base]
        if region:
            parts.append(region)
        out = " ".join(parts)
        if suffix:
            out += (", " if canon in {"BDO USA", "BDO Seidman"} else " ") + suffix
        return out
    # unknown firm: tidy
    m = re.search(rf"^(.*?\b{_SUFFIX_RE})(?=\W|$)", raw, re.I)
    tidy = m.group(1) if m else raw
    tidy = re.sub(r"\s+,", ",", tidy)
    if tidy.isupper() or tidy.islower():
        tidy = " ".join(w if w.upper() in {"LLP", "LLC", "PC", "P.C.", "CPA", "CPAS"} else w.capitalize() for w in tidy.split())
    return tidy.strip(" ,.") or None


def firm_network(name: Optional[str]) -> Optional[str]:
    """Network / family key for a firm (``"Ernst & Young Hua Ming LLP"`` -> ``"Ernst & Young"``).

    Legacy names map to their successors (Price Waterhouse, Coopers & Lybrand -> PricewaterhouseCoopers;
    BDO Seidman -> BDO).  Unknown firms return their lower-cased normalised name without legal suffix.
    """
    if not name:
        return None
    raw = _clean_firm_raw(str(name))
    for _canon, fam, rx, _s in _FIRM_COMPILED:
        if rx.search(raw):
            return fam
    return _firm_key(name)


_LEGAL_SUFFIX_END = re.compile(r"[\s,]+(?:llp|l\.l\.p\.|llc|p\.?c\.?|pllc|ltd\.?|limited|inc\.?)\s*$", re.I)


def _firm_key(name: Optional[str]) -> Optional[str]:
    """Comparison key: normalised name without legal-form suffix (LLP / P.C. changes are not auditor changes)."""
    n = normalize_firm_name(name)
    if not n:
        return None
    n = _LEGAL_SUFFIX_END.sub("", n).lower()
    n = n.replace("bdo seidman", "bdo usa")
    return re.sub(r"[^a-z0-9&+ ]", "", n).strip()


def same_firm(a: Optional[str], b: Optional[str], network_level: bool = False) -> bool:
    """True when two auditor names refer to the same firm.

    Default: same firm incl. regional member (``"Ernst & Young LLP"`` != ``"Ernst & Young Hua Ming LLP"``) but
    ignoring the legal-form suffix (``"BDO USA, LLP"`` == ``"BDO USA, P.C."``).  With ``network_level=True``
    member firms of one network match.  Missing names never match.
    """
    if not a or not b:
        return False
    if network_level:
        fa, fb = firm_network(a), firm_network(b)
        return bool(fa and fb and fa == fb)
    ka, kb = _firm_key(a), _firm_key(b)
    return bool(ka and kb and ka == kb)


def auditor_changed(prev: Optional[str], cur: Optional[str]) -> Optional[bool]:
    """True if the audit *network* changed between two filings; None when either name is unknown.

    A move between member firms of one network (E&Y LLP -> E&Y Hua Ming LLP) or a legal-form change
    (BDO USA LLP -> BDO USA P.C.) is NOT a change; Arthur Andersen -> KPMG is.
    """
    if not prev or not cur:
        return None
    return not same_firm(prev, cur, network_level=True)


# --------------------------------------------------------------------------------------
# Auditor extraction
# --------------------------------------------------------------------------------------

_AUDIT_REPORT_HEADING = re.compile(
    r"^[^\w\n]*(?:report\s+of\s+(?:the\s+)?independent\s+(?:registered\s+)?(?:public\s+)?(?:certified\s+public\s+)?(?:accounting\s+firm|accountants?|auditors?)|"
    r"independent\s+(?:registered\s+)?(?:public\s+)?(?:accountants?|auditors?)['’]?s?\s+report|"
    r"independent\s+auditors?['’]?\s+report)[^\n]{0,60}$",
    re.I | re.M,
)


def _firm_line(line: str) -> Optional[str]:
    """If *line* is (essentially only) an audit-firm name / sign-off, return the raw name."""
    s = line.strip().strip("|").strip()
    s = re.sub(r"^/s/\s*", "", s, flags=re.I).strip()
    s = re.sub(r"^\|?\s*", "", s)
    if not s or len(s) > 95:
        return None
    m = _ANY_FIRM_RX.match(s)
    if not m:
        return None
    # the rest of the line must be a legal suffix / region / city only (no sentence)
    rest = s[m.end():]
    if len(rest.split()) > 9 or re.search(r"\b(?:the|has|have|was|were|is|are|issued|audit(?:ed)?|report|served|dismiss)", rest, re.I):
        return None
    return s


_CONSENT_LINE = re.compile(r"consent|letter|filed\s+herewith", re.I)


def extract_auditor_details(text: str) -> dict[str, Any]:
    """Locate the audit firm; returns ``{"name", "raw", "source", "candidates"}`` (name None if not found).

    Priority: (1) sign-off line within 12k chars after an auditor's-report heading; (2) any
    ``/s/ <firm>`` line; (3) a stand-alone firm line; (4) 'audited by / accounting firm <firm>'
    narrative in Item 14 / 16C; (5) first known-firm mention in Item 9.
    """
    t = _prepare(text)
    out: dict[str, Any] = {"name": None, "raw": None, "source": None, "candidates": []}
    if not t:
        return out

    def finish(raw: str, source: str) -> dict[str, Any]:
        out["raw"] = raw
        out["name"] = normalize_firm_name(raw)
        out["source"] = source
        return out

    headings = []
    for hm in _AUDIT_REPORT_HEADING.finditer(t):
        line = hm.group(0).strip()
        if len(line) > 140 or _TOC_PAGE_END.search(line) or "...." in line:
            continue
        headings.append(hm)
    seen_norm: list[str] = []
    for i, hm in enumerate(headings):
        limit = headings[i + 1].start() if i + 1 < len(headings) else len(t)
        window = t[hm.end(): min(limit, hm.end() + 12_000)]
        for ln in window.split("\n"):
            raw = _firm_line(ln)
            if raw and not _CONSENT_LINE.search(ln):
                norm = normalize_firm_name(raw) or raw
                if norm not in seen_norm:
                    seen_norm.append(norm)
                    out["candidates"].append(raw)
                break
    if out["candidates"]:
        res = finish(out["candidates"][0], "auditor-report-signoff")
        res["all_signoffs"] = list(seen_norm)
        return res
    for m in re.finditer(r"^[^\w\n]*/s/\s*([^\n]{3,90})$", t, re.M | re.I):
        raw = _firm_line(m.group(0))
        if raw:
            return finish(raw, "/s/-line")
    for ln in t.split("\n"):
        if len(ln) < 70:
            raw = _firm_line(ln)
            if raw and not _CONSENT_LINE.search(ln) and re.search(r"\b(?:LLP|LLC|P\.C\.|Ltd|Limited)\b|^\s*(?:KPMG|Arthur\s+Andersen)", raw, re.I):
                return finish(raw, "standalone-line")
    secs = extract_sections(t)
    for key in ("item14", "item9_changes"):
        body = secs.get(key) or ""
        m = re.search(
            r"(?:audited\s+by|(?:auditor|accounting\s+firm|accountants)s?(?:,|\s+(?:is|are|was|were|namely))?\s+|engaged\s+|appointed\s+|billed\s+by\s+|fees?\s+(?:of|to|paid\s+to)\s+)\s*((?:"
            + "|".join(rx for _, _, rx, _ in _FIRMS)
            + r")[^,.;\n]{0,40})",
            body,
            re.I,
        )
        if m:
            return finish(m.group(1), f"narrative({key})")
        m2 = _ANY_FIRM_RX.search(body)
        if m2:
            return finish(body[m2.start(): m2.end() + 40].split("\n")[0], f"mention({key})")
    return out


def extract_auditor(text: str) -> Optional[str]:
    """Normalised audit-firm name from the auditor's report / Item 14 / Item 9, else None."""
    return extract_auditor_details(text)["name"]


# --------------------------------------------------------------------------------------
# Signatories
# --------------------------------------------------------------------------------------

_ROLE_WORDS = {
    "chief", "executive", "officer", "financial", "accounting", "president", "director", "chairman", "chairwoman", "chair", "vice", "senior",
    "treasurer", "secretary", "controller", "comptroller", "principal", "general", "counsel", "and", "of", "the", "board", "ceo", "cfo",
    "coo", "cto", "managing", "head", "global", "corporate", "operating", "strategy", "co-chief", "co", "finance", "evp", "svp", "vp",
    "inc", "corp", "llc", "llp", "company", "signature", "title", "date", "name", "capacity", "registrant", "by", "power", "attorney",
}
_TOKEN = r"(?:[A-Z][A-Za-z'’\-]*\.?|(?:van|von|de|der|la|di|da|del|bin|al|ibn)(?=\s+[A-Z]))"
_NAME_RX = rf"{_TOKEN}(?:[ ]{_TOKEN}){{1,4}}"
_SLASH_S = re.compile(rf"/s/[ \t]*(?P<name>{_NAME_RX})", re.I)
_BY_RX = re.compile(rf"\bBy:?[ \t|]*(?P<name>{_NAME_RX})(?![A-Za-z])")
_CAPS_ROW = re.compile(r"^[ \t]*(?:By:[ \t]*)?(?P<name>[A-Z][A-Z.'’\-]*(?:[ ]{1,2}[A-Z][A-Z.'’\-]*){1,4})\*?(?:,?\s*(?:JR|SR|II|III|IV)\.?)?[ \t]{3,}(?P<rest>\S.*)$")
_MIXED_ROW = re.compile(rf"^[ \t]*(?P<name>{_NAME_RX})\*?[ \t]*\|[ \t]*(?P<rest>\S.*)$")
_DATE_RX = re.compile(
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?[ \t]+\d{1,2},?[ \t]*\d{4}|"
    r"\d{1,2}(?:st|nd|rd|th)?[ \t]+day[ \t]+of[ \t]+\w+,?[ \t]*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
)
_JUNK_LINE = re.compile(r"^\s*(?:power\s+of\s+attorney|know\s+all|pursuant\s+to|the\s+registrant\s+hereby|table\s+of\s+contents|signature\b|name\s*\|?\s*title|\d{1,3}\s*$|<|[^\n]{0,40}form\s+10-?k\b[^\n]{0,20}\d+\s*$)", re.I)

_CEO_RX = re.compile(r"chief\s+executive\s+officer|principal\s+executive\s+officer|\bC\.?E\.?O\b", re.I)
_CFO_STRONG = re.compile(r"chief\s+financial\s+officer|\bC\.?F\.?O\b", re.I)
_CFO_WEAK = re.compile(r"principal\s+financial|financial\s+officer", re.I)


def _title_case_name(name: str) -> str:
    out = []
    for w in name.split():
        w2 = w.strip("*")
        if not w2:
            continue
        if re.fullmatch(r"[A-Z]\.?", w2):
            out.append(w2 if w2.endswith(".") else w2 + ".")
        elif w2.upper() in {"JR", "JR.", "SR", "SR."}:
            out.append(w2.capitalize().rstrip(".") + ".")
        elif w2.upper() in {"II", "III", "IV"}:
            out.append(w2.upper())
        elif w2.isupper() or w2.islower():
            c = "-".join(p.capitalize() for p in w2.split("-"))
            c = re.sub(r"^(Mc)([a-z])", lambda m: m.group(1) + m.group(2).upper(), c)
            c = re.sub(r"^(O')([a-z])", lambda m: m.group(1) + m.group(2).upper(), c)
            out.append(c)
        else:
            out.append(w2)
    return " ".join(out)


def _strip_trailing_roles(name: str) -> tuple[str, str]:
    """Split trailing title words glued to a name by single spaces ('/s/ David Weigand Chief ...')."""
    toks = name.split()
    spill: list[str] = []
    while len(toks) > 1 and toks[-1].lower().strip(".,") in _ROLE_WORDS:
        spill.insert(0, toks.pop())
    return " ".join(toks), " ".join(spill)


class _Anchor:
    __slots__ = ("line_idx", "name", "rest", "kind")

    def __init__(self, line_idx: int, name: str, rest: str, kind: str):
        self.line_idx = line_idx
        self.name = name
        self.rest = rest
        self.kind = kind


def _name_pattern(name: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"\s+", name.strip()) if p]
    return re.compile(r"[ \t]*".join(parts) if False else r"\s*".join(parts), re.I)


def _parse_signers(sig_text: str) -> list[dict[str, str]]:
    lines = sig_text.split("\n")
    anchors: list[_Anchor] = []
    for i, ln in enumerate(lines):
        if len(ln) > 220 or _JUNK_LINE.match(ln):
            continue
        m = _SLASH_S.search(ln)
        if m:
            name, spill = _strip_trailing_roles(m.group("name"))
            rest = (spill + " " + ln[m.start("name") + len(m.group("name")):]).strip()
            anchors.append(_Anchor(i, name, rest, "slash"))
            continue
        m = _CAPS_ROW.match(ln)
        if m:
            nm = m.group("name")
            toks = nm.split()
            if len(toks) >= 2 and not any(tk.lower().strip(".") in _ROLE_WORDS for tk in toks):
                anchors.append(_Anchor(i, nm, m.group("rest"), "caps"))
                continue
        m = _MIXED_ROW.match(ln)
        if m:
            nm, spill = _strip_trailing_roles(m.group("name"))
            if len(nm.split()) >= 2 and not any(tk.lower().strip(".") in _ROLE_WORDS for tk in nm.split()):
                anchors.append(_Anchor(i, nm, (spill + " " + m.group("rest")).strip(), "row"))
                continue
        m = _BY_RX.search(ln)
        if m:
            nm, spill = _strip_trailing_roles(m.group("name"))
            if len(nm.split()) >= 2 and not any(tk.lower().strip(".") in _ROLE_WORDS for tk in nm.split()):
                anchors.append(_Anchor(i, nm, (spill + " " + ln[m.end():]).strip(), "by"))
    signers: list[dict[str, str]] = []
    anchor_lines = {a.line_idx for a in anchors}
    for a in anchors:
        window = [a.rest]
        for j in range(a.line_idx + 1, min(len(lines), a.line_idx + 6)):
            if j in anchor_lines:
                break
            ln = lines[j]
            if len(ln) > 170 or _JUNK_LINE.match(ln):
                break
            window.append(ln)
        blob = " \n ".join(window)
        # canonical name: prefer mixed-case "(Name)" echo, else the anchor name
        name = a.name.strip().rstrip("*")
        canon = name
        if name.isupper():
            echo = re.search(r"\(\s*(" + _name_pattern(name).pattern + r")\s*\*?\s*\)", blob, re.I)
            canon = _collapse(echo.group(1)) if echo else _title_case_name(name)
            if echo and canon.isupper():
                canon = _title_case_name(canon)
        # remove name echoes and clutter from title text
        title = blob
        title = re.sub(r"\(\s*" + _name_pattern(name).pattern + r"\s*\*?\s*\)", " ", title, flags=re.I)
        title = _name_pattern(name).sub(" ", title)
        title = _name_pattern(canon).sub(" ", title)
        title = re.sub(r"/s/", " ", title, flags=re.I)
        title = _DATE_RX.sub(" ", title)
        title = re.sub(r"-{3,}|_{3,}|={3,}", " ", title)
        title = re.sub(r"\b(?:Name|Title|Date|By|Signature|Capacity)\s*:", " ", title, flags=re.I)
        title = title.replace("|", " ").replace("*", " ")
        title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title)  # "theBoard" -> "the Board" (title glue)
        title = re.sub(r"\)(?=[A-Za-z])", ") ", title)
        title = re.sub(r"(?<=[A-Za-z])\(", " (", title)
        title = re.sub(r"(?:(?<=\s)|^)[-–—](?=\s|$)", " ", title)  # stray column dashes
        title = _collapse(title)
        signers.append({"name": canon, "title": title, "kind": a.kind})
    return signers


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _signature_text_for(text: str) -> str:
    t = _prepare(text)
    sig = _signature_section(t)
    if sig:
        return sig
    tail = t[-30_000:]
    m = None
    for m in re.finditer(r"/s/", tail):
        break
    return tail[m.start() - 600 if m and m.start() > 600 else 0:] if m else ""


def _tidy_signer_name(name: Optional[str]) -> Optional[str]:
    """Undo two layout artefacts of signature blocks (v2): small-caps split initials ("S ATYA N ADELLA" -> "SATYA NADELLA")
    and a name echoed after itself ("Julio Rodriguez Julio Rodriguez", "SATYA NADELLA Satya").  Already clean names are
    returned unchanged."""
    if not name:
        return name
    toks = name.split()
    merged: list[str] = []
    i = 0
    while i < len(toks):
        if i + 1 < len(toks) and re.fullmatch(r"[A-Z]", toks[i]) and re.fullmatch(r"[A-Z]{2,}", toks[i + 1]):
            merged.append(toks[i] + toks[i + 1])
            i += 2
        else:
            merged.append(toks[i])
            i += 1
    toks = merged
    for k in range(1, len(toks) // 2 + 1):
        head = [t.lower().strip(".,") for t in toks[:k]]
        tail = [t.lower().strip(".,") for t in toks[-k:]]
        if head == tail and len(toks) - k >= 2:
            toks = toks[:-k]
            break
    out = " ".join(toks)
    if out.isupper():
        out = _title_case_name(out)
    return out


def extract_signatories(text: str) -> dict[str, Any]:
    """CEO / CFO from the signature page.

    Returns ``{"ceo": name|None, "cfo": name|None, "ceo_title": str|None, "cfo_title": str|None,
    "signers": [{"name","title"}, ...]}``.  Handles ``/s/ Name | Title | Date`` tables, stacked
    name/title lines, side-by-side caps columns (old .txt), ``By:`` blocks and 20-F ``Name:/Title:``
    layouts.  Role detection (on the cleaned title text): CEO = "Chief Executive Officer" /
    "Principal Executive Officer"; CFO = "Chief Financial Officer" (preferred) or "Principal
    Financial Officer".  A co-title such as "Chairman and CEO" or "Executive Vice President and
    Chief Financial Officer" matches.  "Chief Accounting Officer" alone is NOT a CFO.
    Names appearing in several places (registrant "By:" block and the director table) are
    de-duplicated; if the 20-F carries only one signer, the other role is None (never guessed).
    """
    out: dict[str, Any] = {"ceo": None, "cfo": None, "ceo_title": None, "cfo_title": None, "signers": []}
    sig = _signature_text_for(text)
    if not sig:
        return out
    signers = _parse_signers(sig)
    seen: dict[str, dict[str, str]] = {}
    for s in signers:
        key = normalize_person_name(s["name"]) or s["name"].lower()
        prev = seen.get(key)
        if prev is None:
            seen[key] = dict(s)
        elif s["title"]:
            # same person listed twice (registrant block + director table, or name echoed on a 2nd row)
            a_new, a_old = _alnum(s["title"]), _alnum(prev["title"])
            if a_new and a_new in a_old:
                continue
            if a_old and a_old in a_new:
                prev["title"] = s["title"]
            else:
                prev["title"] = _collapse(prev["title"] + " " + s["title"])
    out["signers"] = [{"name": s["name"], "title": s["title"]} for s in seen.values()]
    ceo = None
    for s in seen.values():
        if _CEO_RX.search(s["title"]):
            ceo = s
            break
    cfo = None
    for s in seen.values():
        if _CFO_STRONG.search(s["title"]):
            cfo = s
            break
    if cfo is None:
        for s in seen.values():
            if _CFO_WEAK.search(s["title"]):
                cfo = s
                break
    if ceo:
        out["ceo"], out["ceo_title"] = _tidy_signer_name(ceo["name"]), ceo["title"]
    if cfo:
        out["cfo"], out["cfo_title"] = _tidy_signer_name(cfo["name"]), cfo["title"]
    return out


# --------------------------------------------------------------------------------------
# Person-name normalisation
# --------------------------------------------------------------------------------------

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "cpa", "phd", "md", "esq", "mba"}
_HONORIFICS = {"mr", "mrs", "ms", "dr", "prof", "sir", "hon"}
_NICK_GROUPS = [
    {"william", "bill", "billy", "will", "willy", "liam"}, {"robert", "bob", "bobby", "rob", "robbie", "bert"}, {"richard", "rick", "ricky", "dick", "rich", "richie"},
    {"james", "jim", "jimmy", "jamie"}, {"michael", "mike", "mick", "mickey", "mikey"}, {"thomas", "tom", "tommy"}, {"david", "dave", "davey"},
    {"steven", "stephen", "steve"}, {"christopher", "chris", "kit"}, {"timothy", "tim", "timmy"}, {"andrew", "andy", "drew"},
    {"anthony", "tony"}, {"edward", "ed", "eddie", "ted", "teddy", "ned"}, {"gregory", "greg"}, {"jeffrey", "jeff", "geoffrey", "geoff"},
    {"joseph", "joe", "joey"}, {"john", "jack", "johnny", "jon"}, {"kenneth", "ken", "kenny"}, {"lawrence", "larry", "laurence"},
    {"matthew", "matt"}, {"nicholas", "nick", "nicky"}, {"patrick", "pat"}, {"peter", "pete"}, {"philip", "phillip", "phil"}, {"ronald", "ron", "ronnie"},
    {"samuel", "sam", "sammy"}, {"daniel", "dan", "danny"}, {"donald", "don", "donnie"}, {"douglas", "doug"}, {"frederick", "fred", "freddie", "fredrick"},
    {"gerald", "gerry", "jerry"}, {"harold", "harry", "hal"}, {"henry", "hank", "harry"}, {"albert", "al", "bert"}, {"alexander", "alex", "sandy"},
    {"benjamin", "ben", "benny"}, {"charles", "charlie", "chuck", "chas"}, {"walter", "walt"}, {"raymond", "ray"}, {"vincent", "vince", "vinnie"},
    {"zachary", "zach", "zack"}, {"margaret", "peggy", "maggie", "meg"}, {"elizabeth", "liz", "beth", "betsy", "lisa", "eliza"},
    {"katherine", "catherine", "kathryn", "kate", "katie", "kathy", "cathy"}, {"susan", "sue", "susie", "suzanne"}, {"jennifer", "jen", "jenny"},
    {"patricia", "pat", "patty", "trish"}, {"deborah", "debbie", "debra"}, {"barbara", "barb", "barbie"}, {"rebecca", "becky"}, {"victoria", "vicky", "vicki"},
    {"cynthia", "cindy"}, {"pamela", "pam"}, {"stanley", "stan"}, {"theodore", "ted", "theo"}, {"nathaniel", "nate", "nathan"}, {"leonard", "len", "lenny", "leo"},
    {"eugene", "gene"}, {"francis", "frank", "frankie"}, {"jonathan", "jon", "jonny"}, {"russell", "russ"}, {"bernard", "bernie", "barney"},
]
_NICK_INDEX: dict[str, set[int]] = {}
for _i, _g in enumerate(_NICK_GROUPS):
    for _n in _g:
        _NICK_INDEX.setdefault(_n, set()).add(_i)
_PARTICLES = {"van", "von", "de", "der", "den", "la", "le", "di", "da", "del", "della", "bin", "al", "ibn", "st", "mac"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _person_tokens(name: Optional[str]) -> tuple[list[str], str]:
    """(given-name tokens lower-cased, last name lower-cased)."""
    if not name:
        return [], ""
    s = _strip_accents(str(name)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("*", " ").replace("’", "'")
    if "," in s:
        a, _, b = s.partition(",")
        b_tokens = re.sub(r"[^\w\s'\-]", " ", b).split()
        if b_tokens and all(t in _NAME_SUFFIXES for t in b_tokens):
            s = a
        else:
            s = f"{b} {a}"  # "Fastow, Andrew S."
    s = re.sub(r"[^\w\s'\-]", " ", s)
    toks = [t.strip("'-") for t in s.split()]
    toks = [t for t in toks if t and t not in _NAME_SUFFIXES and t not in _HONORIFICS]
    if len(toks) < 2:
        return toks[:-1] if toks else [], toks[-1] if toks else ""
    last = toks[-1]
    given = toks[:-1]
    while given and given[-1] in _PARTICLES:
        last = given.pop() + " " + last
    last = last.replace("-", "").replace("'", "")
    given = [g.replace("'", "") for g in given]
    return given, last


def normalize_person_name(name: Optional[str]) -> Optional[str]:
    """Canonical comparison key ``"first last"`` (lower case, accents/punctuation/suffix/middle names removed)."""
    given, last = _person_tokens(name)
    if not last:
        return None
    first = given[0] if given else ""
    return f"{first} {last}".strip()


def _first_names_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    if a in _NICK_INDEX and b in _NICK_INDEX and _NICK_INDEX[a] & _NICK_INDEX[b]:
        return True
    return False


def same_person(a: Optional[str], b: Optional[str]) -> bool:
    """True if two executive names refer to the same person.

    ``same_person("Andrew S. Fastow", "Andrew Fastow")`` -> True; middle names/initials, case,
    punctuation, suffixes (Jr., III), "Last, First" order, accents and common nicknames (Bill /
    William, Andy / Andrew) are tolerated; a different first name or last name -> False.  A
    single-token name never matches (conservative: a change might be missed, never invented).
    """
    ga, la = _person_tokens(a)
    gb, lb = _person_tokens(b)
    if not la or not lb or not ga or not gb:
        return False
    if la != lb:
        return False
    if _first_names_match(ga[0], gb[0]):
        return True
    # first name differs: allow "J. Scott Smith" vs "Scott Smith" (initial first, real name second)
    if len(ga[0]) == 1 and len(ga) > 1 and _first_names_match(ga[1], gb[0]):
        return True
    if len(gb[0]) == 1 and len(gb) > 1 and _first_names_match(gb[1], ga[0]):
        return True
    return False


# --------------------------------------------------------------------------------------
# Audit fees
# --------------------------------------------------------------------------------------

_FEE_ROW = re.compile(
    r"^[^\w\n]{0,4}(?P<label>audit[\s-]+related\s+fees?|audit\s+fees?|principal\s+auditor\s+fees?|tax\s+fees?|all\s+other\s+fees?|other\s+fees?|total(?:\s+fees?)?(?:\s+billed)?)\b(?P<rest>[^\n]*)$",
    re.I | re.M,
)
_NUM_RX = re.compile(r"(?<![\w.])\(?\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\)?(?![\w])")
_YEAR_RX = re.compile(r"\b(?:19|20)\d{2}\b")


def _fee_numbers(rest: str) -> list[float]:
    rest = re.sub(r"\(\s*\d\s*\)|\(\s*[a-z]\s*\)", " ", rest)  # footnote markers
    vals = []
    for m in _NUM_RX.finditer(rest):
        s = m.group(1).replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        unit = re.match(r"\s*(million|thousand)\b", rest[m.end():], re.I)  # "$25 million"
        if unit:
            v *= 1_000_000.0 if unit.group(1).lower() == "million" else 1_000.0
        vals.append(v)
    return vals


def extract_audit_fees(text: str) -> Optional[dict[str, Any]]:
    """Parse the principal-accountant fee table (10-K Item 14, 20-F Item 16C, or a proxy statement).

    Returns ``{"audit_fees": float|None, "total_fees": float|None, "year": int|None,
    "source_excerpt": str, "unit_multiplier": float, "columns": {...}}`` in absolute currency units
    (reported "in thousands" tables are multiplied by 1,000; the currency is whatever the filing
    uses, e.g. RMB for Luckin).  The current-year column is chosen from the year header (largest
    year); with no header the first column is used.  ``total_fees`` is only returned when the table
    has a Total row (never summed).  Returns ``None`` when no fee table / narrative is found.
    """
    t = _prepare(text)
    if not t:
        return None
    rows = list(_FEE_ROW.finditer(t))
    # group consecutive rows (within 12 lines of each other)
    groups: list[list[re.Match]] = []
    for m in rows:
        if groups and m.start() - groups[-1][-1].end() < 700:
            groups[-1].append(m)
        else:
            groups.append([m])
    best: Optional[dict[str, Any]] = None
    for g in groups:
        audit = None
        nums: list[float] = []
        for m in g:
            if re.match(r"(?:principal\s+)?audit(?:or)?\s+fees?", m.group("label"), re.I):
                if len(m.group("rest")) > 160 and len(m.group("rest").split()) > 25 and "|" not in m.group("rest"):
                    continue          # a prose paragraph ("Audit Fees. Audit fees consist of ... Forms 10-Q ...") is not a table row
                nums = _fee_numbers(m.group("rest"))
                if len(nums) >= 2 and nums[0] < 10 and nums[0] == int(nums[0]) and any(v >= 1000 for v in nums[1:]):
                    nums = nums[1:]   # "Audit Fees 1 | $1,963,668 | $1,459,734": the leading 1 is a footnote marker, not a fee
                if nums:
                    audit = m
                    break
        if audit is None:
            continue
        before = t[max(0, g[0].start() - 900): g[0].start()]
        years = [int(y) for y in _YEAR_RX.findall(before[-450:])]
        years = [yy for i, yy in enumerate(years) if i == 0 or yy != years[i - 1]]   # "May 5, 2017 2017 (inception)" repeats a year
        # keep the last run of years that has as many entries as numeric columns
        col = 0
        year: Optional[int] = None
        if years:
            tail_years = years[-len(nums):] if len(years) >= len(nums) else years
            if len(tail_years) == len(nums) and len(set(tail_years)) == len(tail_years):
                year = max(tail_years)
                col = tail_years.index(year)
            else:
                year = max(years[-2:]) if len(years) >= 2 else years[-1]
        context = (before + " " + audit.group(0)).lower()
        scaled_in_row = bool(re.search(r"\d\s*(?:million|thousand)\b", audit.group("rest"), re.I))
        mult = 1.0 if scaled_in_row else 1_000.0 if re.search(r"in\s+thousands|\(000s?\)|\$000|\(in\s+000|in\s+'?000s?\b|'000s?\b|amounts\s+in\s+000", context) else (1_000_000.0 if re.search(r"in\s+millions", context) else 1.0)
        audit_val = nums[col] if col < len(nums) else nums[0]
        total_val = None
        for m in g:
            if m.group("label").lower().startswith("total"):
                tn = _fee_numbers(m.group("rest"))
                if tn:
                    total_val = tn[col] if col < len(tn) else tn[0]
                break
        excerpt = _collapse(t[g[0].start(): g[-1].end()])[:600]
        cand = {
            "audit_fees": audit_val * mult,
            "total_fees": total_val * mult if total_val is not None else None,
            "year": year,
            "source_excerpt": excerpt,
            "unit_multiplier": mult,
            "columns": {"n_numeric_columns": len(nums), "chosen_index": col},
        }
        score = (year or 0, 1 if total_val is not None else 0)
        if best is None or score > best["_score"]:
            cand["_score"] = score
            best = cand
    if best is not None:
        best.pop("_score", None)
        return best
    # narrative fallback: "audit fees ... were $1.2 million"
    m = re.search(
        r"(?:aggregate\s+)?audit\s+fees?(?:(?!audit[\s-]+related|tax\s+fees|all\s+other)[^$\n]){0,800}?\$\s*(\d[\d,]*(?:\.\d+)?)\s*(million|thousand)?",
        t,
        re.I,
    )
    if m:
        v = float(m.group(1).replace(",", ""))
        mult = 1_000_000.0 if (m.group(2) or "").lower() == "million" else (1_000.0 if (m.group(2) or "").lower() == "thousand" else 1.0)
        ctx = t[max(0, m.start() - 300): m.end() + 100]
        ys = [int(y) for y in _YEAR_RX.findall(ctx)]
        return {
            "audit_fees": v * mult,
            "total_fees": None,
            "year": max(ys) if ys else None,
            "source_excerpt": _collapse(t[m.start(): m.end() + 80])[:600],
            "unit_multiplier": mult,
            "columns": {"n_numeric_columns": 1, "chosen_index": 0},
        }
    return None


# --------------------------------------------------------------------------------------
# Keyword hits with negation / boilerplate awareness
# --------------------------------------------------------------------------------------

RESTATEMENT_PATTERNS: list[str] = [
    r"\brestat(?:e|es|ed|ing|ement|ements)\b",
    r"\bnon-?reliance\b",
    r"\bno\s+longer\s+be\s+relied\s+upon\b|\bshould\s+no\s+longer\s+be\s+relied\b",
    r"\bitem\s+4\.02\b",
]
MATERIAL_WEAKNESS_PATTERNS: list[str] = [
    r"\bmaterial\s+weakness(?:es)?\b",
    r"\bsignificant\s+deficienc(?:y|ies)\b",
]
GOING_CONCERN_PATTERNS: list[str] = [
    r"substantial\s+doubt[^.]{0,250}?(?:ability\s+to\s+continue|going\s+concern)",
    r"(?:ability\s+to\s+continue\s+as\s+a\s+going\s+concern|going\s+concern)[^.]{0,200}?substantial\s+doubt",
    r"raise[sd]?\s+substantial\s+doubt",
    r"going\s+concern\s+(?:qualification|explanatory)",
]

_NEG_CUE = re.compile(
    r"\b(?:no(?!\s+longer)|not|none|never|neither|nor|without|cannot|absence\s+of|free\s+(?:of|from)|nothing|unable\s+to\s+(?:identify|find)|"
    r"did\s+not|does\s+not|do\s+not|have\s+not|has\s+not|had\s+not|were\s+not|was\s+not|is\s+not|are\s+not|"
    r"alleviate[sd]?|alleviating|eliminate[sd]?|dispel(?:led|s)?|(?:isn|wasn|weren|didn|doesn|hasn|haven|hadn)['’]t)\b",
    re.I,
)
_CONTRAST = re.compile(r"\b(?:but|however|except|although|though|yet|other\s+than|aside\s+from|while)\b|;|,\s*(?:and|or)\b", re.I)
_NEG_RIGHT = re.compile(
    r"^[\s,]*(?:(?:was|were|has|have|had|is|are|been|being|be)\s+)*(?:not|never)\s+(?:been\s+)?(?:identified|found|detected|noted|reported|present|disclosed|raised)\b|"
    r"^[\s,]*(?:was|were|has|have|had|is|are)\s+(?:alleviated|eliminated|dispelled)\b|"
    r"^[\s,]*(?:have|has|had|was|were)\s+been\s+(?:alleviated|eliminated)\b",
    re.I,
)
_HYPO_CUE = re.compile(
    r"\b(?:if|could|may|might|would|should|in\s+the\s+event(?:\s+of)?|potential(?:ly)?|possib(?:le|ility)|possibility\s+of|risk\s+of|likelihood\s+of|"
    r"future|subject\s+us\s+to|result\s+in(?:\s+a|\s+an)?|lead\s+to|cause\s+(?:a|an)|unable\s+to\s+(?:timely|accurately))\b",
    re.I,
)
_ASSERT_VERB = re.compile(
    r"\b(?:we|company|management|board|committee)\s+(?:has\s+|have\s+|had\s+)?(?:identified|concluded|determined|restated|reported|announced)\b", re.I
)


def _is_hypothetical(left: str) -> bool:
    """Conditional / risk-factor wording shortly before the match, with no intervening contrast or assertion."""
    tail = left[-120:]
    last = None
    for m in _HYPO_CUE.finditer(tail):
        last = m
    if last is None:
        return False
    between = tail[last.end():]
    if len(between) > 95 or _CONTRAST.search(between) or re.search(r"[.;\n]", between):
        return False
    return not _ASSERT_VERB.search(tail)
_RESTATE_BOILERPLATE_SENT = [
    re.compile(r"hereby\s+restates?|restates,?\s+(?:ratifies|reaffirms)", re.I),
    re.compile(r"conform(?:ed|ing|s)?\s+to\s+(?:the\s+)?(?:current|present|prior|new|2\d{3}|this)", re.I),
    re.compile(r"reclassif", re.I),
    re.compile(r"to\s+reflect\s+(?:the\s+)?(?:effects?\s+of\s+|impact\s+of\s+)?(?:a\s+|the\s+)?(?:\w+[-\s]for[-\s]\w+\s+)?(?:stock\s+split|reverse|retrospective|adoption|change\s+in\s+(?:segment|accounting|presentation|reporting)|discontinued|recast)", re.I),
    re.compile(r"\b(?:adjusted|restated|recast)\s+(?:for|to\s+give\s+effect)\s+(?:the\s+)?(?:\w+[-\s]for[-\s]\w+\s+)?(?:stock\s+split|adoption|retrospective|reverse|discontinued|stock\s+dividend|change\s+in)", re.I),
    re.compile(r"restated\s+for\s+(?:comparability|consistency|presentation)", re.I),
    re.compile(r"retrospective(?:ly)?\s+(?:adopt|appl|basis)", re.I),
    re.compile(r"amended\s+and\s+restated|and\s+restated\s+(?:certificate|articles|bylaws|by-laws|charter|agreement|plan|credit|indenture)|restated\s+(?:certificate|articles|bylaws|by-laws|charter|credit|plan|stock|agreement|revolving|master|indenture|declaration|trust|note|loan|lease|equity|incentive|employment|securities)", re.I),
    re.compile(r"for\s+comparability|comparative\s+(?:amounts|figures|periods)\s+(?:have\s+been|were)\s+(?:restated|reclassified|conformed)", re.I),
]
_CLAWBACK = re.compile(
    r"recoup|claw\s*-?\s*back|incentive[-\s]based\s+compensation|erroneously\s+(?:awarded|paid)|excess\s+incentive|compensation\s+recovery",
    re.I,
)
_ERROR_WORDS = re.compile(r"\berrors?\b|misstate|irregularit|incorrect|\bcorrect(?:ion|ed|ing)?\b|improper|fraud|invalid|material\s+weakness", re.I)
_RESTATE_SOFT_BOILERPLATE = [
    re.compile(r"retroactively\s+restated|restated\s+retroactively", re.I),
    re.compile(r"restated\s+(?:in\s+all\s+(?:comparative|prior)\s+periods?\s+)?(?:up\s+to\s+\S+\s+\S+\s+)?(?:to|for)\s+(?:reflect|give\s+effect|include|combine|present|account)", re.I),
    re.compile(r"restated\s+(?:to\s+)?(?:reflect|include|give\s+effect)", re.I),
    re.compile(r"pooling[-\s]of[-\s]interests|recapitaliz|stock\s+split|stock\s+dividend|reverse\s+merger|business\s+combination", re.I),
]
_MW_DEFINITION = re.compile(
    r"is\s+a\s+deficiency,?\s+or\s+(?:a\s+)?combination\s+of\s+deficiencies|reasonable\s+possibility\s+that\s+a\s+material\s+misstatement|"
    r"risk\s+that\s+a\s+material\s+weakness\s+exists|deficiencies\s+that\s+(?:are|were)\s+less\s+severe\s+than\s+a\s+material\s+weakness",
    re.I,
)
_DOC_TITLE_RESTATED = re.compile(
    r"(?:amended\s+and\s*|as\s+amended\s+and\s*)$|^\s*(?:\d{4}\s+)?(?:[A-Za-z0-9&.'’-]+\s+){0,5}?(?:plan|agreement|deferral|certificate|articles|bylaws|by-laws|charter|indenture|facility|program|note|notes|declaration|trust|lease)\b",
    re.I,
)
_GC_BASIS = re.compile(r"going[-\s]concern\s+(?:basis|assumption|value|premium|accounting)|(?:prepared|presented)\s+(?:on\s+a\s+going|assuming\s+(?:that\s+)?(?:the\s+company|we)\s+(?:will\s+)?continue)", re.I)

NL = "\n"
_SENT_BREAK = re.compile(r"\.\s+(?=[A-Z\"“(])|;\s")


def _hard_line_end(line: str) -> bool:
    """True if a newline after *line* ends a sentence (vs. a soft wrap in fixed-width .txt)."""
    st = line.strip()
    if not st or len(st) < 45 or "|" in st:
        return True
    return st.endswith((".", "!", "?", ":", ";", '"', "”"))


def _sentence_bounds(text: str, s: int, e: int) -> tuple[int, int]:
    lo = max(0, s - 500)
    chunk = text[lo:s]
    cut = 0
    for m in _SENT_BREAK.finditer(text, lo, min(len(text), s + 1)):
        if m.end() <= s:
            cut = m.end() - lo
    pos = 0
    for line in chunk.split(NL)[:-1]:
        pos += len(line) + 1
        if _hard_line_end(line) and pos > cut:
            cut = pos
    start = lo + cut
    hi = min(len(text), e + 400)
    tail = text[e:hi]
    end = hi
    m2 = re.search(r"\.\s+(?=[A-Z\"“(])", tail)
    if m2:
        end = e + m2.start() + 1
    pos = 0
    for line in tail.split(NL)[:-1]:
        pos += len(line) + 1
        seg_start = pos - len(line) - 1
        if pos + e > end:
            break
        if _hard_line_end(line) and seg_start > 0:
            end = min(end, e + pos - 1)
            break
    return start, end


def _classify_hit(text: str, s: int, e: int) -> tuple[bool, Optional[str]]:
    """Return (negated, reason) for the match text[s:e]."""
    ss, se = _sentence_bounds(text, s, e)
    left = text[ss:s]
    right = text[e:se]
    matched = text[s:e].lower()
    sentence = text[ss:se]
    is_restate = "restat" in matched or "relied" in matched or "reliance" in matched or "4.02" in matched
    is_mw = "material weakness" in matched or "significant deficienc" in matched
    is_gc = "going concern" in matched or "substantial doubt" in matched or "continue as a going" in matched

    if is_restate:
        for rx in _RESTATE_BOILERPLATE_SENT:
            if rx.search(sentence):
                return True, "boilerplate"
        if _CLAWBACK.search(text[max(0, ss - 350): se + 150]):
            return True, "boilerplate"
        if not _ERROR_WORDS.search(sentence):
            for rx in _RESTATE_SOFT_BOILERPLATE:
                if rx.search(sentence):
                    return True, "boilerplate"
        if re.match(r"restated", matched) and (
            _DOC_TITLE_RESTATED.search(text[max(0, s - 24): s]) or _DOC_TITLE_RESTATED.search(text[e: e + 80])
        ):
            return True, "boilerplate"
    if is_mw and _MW_DEFINITION.search(sentence) and not re.search(r"\bidentified\b|\bconclude[sd]?\b", sentence, re.I):
        return True, "boilerplate"
    if is_gc and _GC_BASIS.search(sentence) and not re.search(r"substantial\s+doubt", matched, re.I):
        return True, "boilerplate"

    # negation: cue shortly before the match with no contrast in between
    tail = left[-110:]
    last_cue = None
    for cm in _NEG_CUE.finditer(tail):
        last_cue = cm
    if last_cue is not None:
        between = tail[last_cue.end():]
        if len(between) <= 85 and not _CONTRAST.search(between):
            return True, "negation"
    if _NEG_RIGHT.search(right[:90]):
        return True, "negation"
    if is_restate and not is_mw:
        # risk-factor noun phrase opening a sentence: "Restated financial statements ... may cause us ..."
        if len(left.strip()) < 6 and re.match(r"\s*(?:\w+\s+){0,10}?(?:may|could|might|would|can)\b", right[:140], re.I):
            return True, "hypothetical"
    if is_gc or is_mw or is_restate:
        # hypothetical / risk-factor language ("could result in a restatement", "any material weakness")
        if _is_hypothetical(left):
            if not (is_gc and re.search(r"\bthere\s+(?:is|was|exists|existed)\b", left[-60:], re.I)):
                return True, "hypothetical"
    return False, None


def keyword_hits(
    text: str,
    patterns: Iterable[str | re.Pattern],
    negations: bool = True,
    *,
    context: int = 160,
    max_hits_per_pattern: int = 25,
) -> list[dict[str, Any]]:
    """Find regex *patterns* (case-insensitive) in *text* and classify each hit.

    Each hit: ``{"pattern": str, "excerpt": str, "negated": bool, "reason": str|None, "start": int}``.
    With ``negations=True`` a hit is marked ``negated=True`` (a *non*-signal) when its sentence
    shows (reason ``"negation"``) a nearby negation cue ("no material weakness", "did not identify
    ...", "has not been identified", "alleviated substantial doubt"), (``"boilerplate"``) accounting
    boilerplate ("restated to conform to current presentation", "restated to reflect the stock split",
    "Amended and Restated Bylaws", the 'material weakness' definition sentence, "going concern basis"),
    or (``"hypothetical"``) conditional risk-factor language ("could result in a restatement").
    ``negations=False`` returns every raw match with ``negated=False``.
    """
    t = _prepare(text)
    hits: list[dict[str, Any]] = []
    if not t:
        return hits
    for pat in patterns:
        rx = pat if isinstance(pat, re.Pattern) else re.compile(pat, re.I)
        n = 0
        for m in rx.finditer(t):
            s, e = m.start(), m.end()
            negated, reason = (False, None)
            if negations:
                negated, reason = _classify_hit(t, s, e)
            ex_s = max(0, s - context)
            ex_e = min(len(t), e + context)
            hits.append(
                {
                    "pattern": rx.pattern,
                    "excerpt": _collapse(t[ex_s:ex_e]),
                    "negated": negated,
                    "reason": reason,
                    "start": s,
                }
            )
            n += 1
            if n >= max_hits_per_pattern:
                break
    return hits


def _detect(text: str, patterns: Sequence[str]) -> dict[str, Any]:
    hits = keyword_hits(text, patterns, negations=True)
    live = [h for h in hits if not h["negated"]]
    # de-duplicate overlapping excerpts of the same position
    seen: set[int] = set()
    uniq = []
    for h in live:
        if any(abs(h["start"] - p) < 40 for p in seen):
            continue
        seen.add(h["start"])
        uniq.append(h)
    return {"detected": bool(uniq), "hits": uniq, "negated_hits": [h for h in hits if h["negated"]], "n_raw": len(hits)}


# --------------------------------------------------------------------------------------
# Where in the document is a hit?  (v2, B1/B12)
# --------------------------------------------------------------------------------------

_SECTION_RANK = {"item9a": 0, "body": 1, "risk_factors": 2, "preface": 2}


def locate_sections(text: str, form: Optional[str] = None) -> dict[str, Any]:
    """Character spans of the sections needed to say WHERE a keyword hit sits.

    Returns ``{"item9a": (s, e)|None, "risk_factors": (s, e)|None, "preface_end": int, "length": int}``.
    ``preface_end`` is the start of the first non-TOC ``Item`` header: everything before it (cover page, forward-looking
    statements preamble, table of contents) is the *preface*.  Positions refer to ``_prepare(text)``.
    """
    t = _prepare(text)
    out: dict[str, Any] = {"item9a": None, "risk_factors": None, "preface_end": 0, "length": len(t)}
    if not t:
        return out
    headers = _find_headers(t)
    spans = _spans_for(t, headers)
    fam = _form_family(form, t)
    ctl = re.compile(r"control", re.I)
    sp9 = _choose(spans.get("15" if fam == "20-F" else "9A", []), t, ctl)
    if sp9:
        out["item9a"] = (sp9.start, sp9.end)
    sprf = _choose(spans.get("3" if fam == "20-F" else "1A", []), t, None)
    if sprf and fam != "20-F":
        out["risk_factors"] = (sprf.start, sprf.end)
    elif sprf:
        rf = re.compile(r"^[^\w\n]{0,3}(?:(?:item\s*)?3\s*\.?\s*)?D\s*[.):]\s*risk\s+factors[^\n]*$", re.I | re.M)
        m = rf.search(t, sprf.content_start, sprf.end)
        if m:
            out["risk_factors"] = (m.end(), sprf.end)
    body = [h.pos for h in headers if not h.toc_like]
    if body:
        out["preface_end"] = min(body)
    return out


def _section_of(pos: int, loc: dict[str, Any]) -> str:
    for name in ("item9a", "risk_factors"):
        sp = loc.get(name)
        if sp and sp[0] <= pos < sp[1]:
            return name
    if pos < loc.get("preface_end", 0):
        return "preface"
    return "body"


def _tag_hit(h: dict[str, Any], loc: dict[str, Any], **extra: Any) -> dict[str, Any]:
    n = max(1, loc.get("length", 1))
    h = dict(h)
    h["section"] = _section_of(h["start"], loc)
    h["pct_of_document"] = round(100.0 * h["start"] / n, 1)
    h.update(extra)
    return h


def _rank_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Item 9A / body evidence first, risk-factor and preface mentions last (B12)."""
    return sorted(hits, key=lambda h: (_SECTION_RANK.get(h.get("section", "body"), 1), h.get("kind_rank", 5), h["start"]))


# --------------------------------------------------------------------------------------
# Material weakness: a REPORTED weakness, not a mention (v2, B1)
# --------------------------------------------------------------------------------------

_MW_RX = re.compile(r"\bmaterial\s+weakness(?:es)?\b", re.I)
# forward-looking / conditional wording before the mention ("our ability to timely and effectively remediate material weaknesses")
_MW_FORWARD_LEFT = re.compile(
    r"\b(?:in)?ability\s+(?:of\s+\w+\s+)?to\b(?:[\s,\-]+[\w'’]+){0,7}[\s,]*$|"
    r"\bfail(?:ure|ed|s|ing)?\s+to\s+(?:[\w'’]+\s+){0,3}(?:remediate|maintain|identify|detect|prevent)\b[^.;]{0,50}$|"
    r"\b(?:no\s+assurance|cannot\s+assure|can(?:not|'t)\s+be\s+(?:sure|certain)|there\s+can\s+be\s+no)\b[^.]{0,120}$|"
    r"\bany\s+(?:such\s+|future\s+|other\s+|new\s+|further\s+)?$|\bfuture\s+$|"
    r"\b(?:risks?|possibility|likelihood|consequences?|effects?|impact)\s+(?:of|from|that|associated\s+with|relating\s+to|related\s+to)\s+(?:[\w'’]+\s+){0,4}$",
    re.I,
)
_MW_ASSERT = re.compile(
    r"\b(?:identified|determined|concluded|reported|disclosed|noted|discovered|communicated|detected|found|"
    r"reaffirm\w*|continue[sd]?\s+to\s+(?:have|report|identify|disclose))\b[^.]{0,220}?\bmaterial\s+weakness|"
    r"\bmaterial\s+weakness(?:es)?\b[^.]{0,100}?\b(?:was|were|has\s+been|have\s+been|had\s+been)\s+(?:identified|noted|reported|discovered|detected|communicated|found)|"
    r"\b(?:contain(?:s|ed)?|resulted?\s+in|result(?:ed|ing)\s+(?:from|in)|constitut(?:e|es|ed|ing)|represent(?:s|ed|ing)?|"
    r"amount(?:s|ed)?\s+to|collectively\s+(?:constitut|represent))\b[^.]{0,100}?\bmaterial\s+weakness|"
    r"\b(?:the|these|those|such|following|aforementioned|foregoing|above)\s+material\s+weakness|"
    r"\bmaterial\s+weakness(?:es)?\s+(?:relate[sd]?|exist(?:s|ed)?|remain(?:s|ed)?|related\s+to|involv\w+|include[sd]?|consist\w*|"
    r"in\s+(?:our|the\s+company.s)\s+internal\s+control)",
    re.I,
)
_MW_NOT_REMEDIATED = re.compile(
    r"\bnot\s+(?:yet\s+|been\s+|fully\s+|completely\s+)*(?:remediated|resolved|cured)\b|\bunremediated\b|"
    r"\bremediation\b[^.]{0,60}\b(?:is|are|was|were)\s+(?:not\s+(?:yet\s+)?(?:complete|completed)|ongoing|in\s+progress|continuing)|"
    r"\b(?:is|are)\s+(?:in\s+the\s+process\s+of|currently|still)\s+(?:being\s+)?(?:remediat|implement)|"
    r"\bremain(?:s|ed|ing)?\b[^.]{0,60}\bmaterial\s+weakness|\bmaterial\s+weakness(?:es)?\b[^.]{0,60}\bremain(?:s|ed|ing)?\b|"
    r"\bstill\s+(?:exist|remain)|\bcontinue[sd]?\s+to\s+exist",
    re.I,
)
_MW_REMEDIATED = re.compile(
    r"\b(?:has|have|had|was|were)\s+(?:been\s+)?(?:(?!part)(?:\w+ly|since|now|already)\s+)*(?:remediated|resolved|cured)\b|"
    r"\b(?:recently|previously|since|subsequently|already)\s+(?:(?!part)\w+ly\s+)?(?:remediated|resolved|cured)\b|"
    r"\bremediation\b[^.]{0,80}?\b(?:was|were|has\s+been|have\s+been)\s+(?:fully\s+|successfully\s+)?(?:completed|implemented|effective)|"
    r"\bcompleted\s+(?:the\s+|our\s+|its\s+|all\s+)?(?:\w+\s+)?(?:remediation|remedial)|"
    r"\bno\s+longer\s+(?:a\s+material|constitut|exist|consider)",
    re.I,
)
_MW_PRIOR_PERIOD = re.compile(r"\bpreviously\s+(?:\w+\s+){0,3}?(?:identified|reported|disclosed|existing)\b|\bprior[-\s]+(?:year|period|fiscal)\b", re.I)
# v3 (T2): SOX 302 / 906 certification boilerplate ("I have disclosed ... to the registrant's auditors and the audit committee ...
# all significant deficiencies and material weaknesses in the design or operation of internal control over financial reporting")
_MW_CERT = re.compile(
    r"(?:all\s+)?significant\s+deficienc(?:y|ies)\s+and\s+material\s+weakness(?:es)?\s+in\s+the\s+design\s+or\s+operation|"
    r"\b(?:disclosed|reported)\b[^.]{0,260}?\b(?:registrant.s|company.s|issuer.s)\s+(?:auditors?|independent\s+(?:registered\s+)?(?:public\s+)?accountants?)[^.]{0,200}?(?:significant\s+deficienc|material\s+weakness)|"
    r"\bcertif(?:y|ication|ying)\b[^.]{0,200}?\bsignificant\s+deficienc[^.]{0,80}?\bmaterial\s+weakness",
    re.I,
)
_CONCLUSION_REVERSED = re.compile(r"\bno\s+longer\b|\bnot\s+(?:an?\s+)?adverse\b|\bwithout\s+(?:an?\s+)?adverse\b|\bnot\s+receiv\w*\s+an?\s+adverse\b", re.I)
_ICFR_ADVERSE = re.compile(
    r"\bdid\s+not\s+maintain,?\s+in\s+all\s+material\s+respects,?\s+effective\s+internal\s+control|"
    r"\badverse\s+opinion\s+on\s+(?:the\s+)?(?:effectiveness\s+of\s+(?:the\s+)?)?(?:company.s\s+|our\s+)?internal\s+control",
    re.I,
)
_ICFR_NOT_EFFECTIVE = re.compile(
    r"\b(?:internal\s+control\s+over\s+financial\s+reporting|internal\s+controls?\s+over\s+financial\s+reporting|ICFR|"
    r"disclosure\s+controls?\s+and\s+procedures)\b[^.]{0,120}?\b(?:was|were|is|are)\s+(?:not\s+effective|ineffective)\b|"
    r"\bconcluded\s+that\b[^.]{0,120}\b(?:not\s+effective|ineffective)\b",
    re.I,
)
_ICFR_EFFECTIVE = re.compile(
    r"\b(?:internal\s+control\s+over\s+financial\s+reporting|internal\s+controls?\s+over\s+financial\s+reporting|ICFR)\b[^.]{0,120}?\b(?:was|were|is|are)\s+effective\b|"
    r"\bmaintained,?\s+in\s+all\s+material\s+respects,?\s+effective\s+internal\s+control\b|"
    r"\bconcluded\s+that\b[^.]{0,160}?\binternal\s+control\s+over\s+financial\s+reporting\b[^.]{0,80}?\beffective\b",
    re.I,
)
_ASOF_DATE = re.compile(r"\b[Aa]s\s+of\s+(?:[A-Z][a-z]+\s+\d{1,2},?\s+)(\d{4})\b")
_FY_END = re.compile(r"for\s+the\s+(?:fiscal\s+)?year\s+ended\s*:?\s*(?:[A-Za-z]+\s+\d{1,2},?\s+)(\d{4})", re.I)
_COND_WORD = re.compile(r"\b(?:if|whether|unless|could|may|might|would|should)\b", re.I)


def _fiscal_year_of(t: str) -> Optional[int]:
    m = _FY_END.search(t[:12000])
    return int(m.group(1)) if m else None


def _conclusion_sentences(t: str, scope: tuple[int, int], rx: re.Pattern) -> list[tuple[int, int]]:
    """Spans (start, end) of sentences inside *scope* matching *rx*, skipping conditional/hypothetical wording."""
    out: list[tuple[int, int]] = []
    s0, e0 = scope
    for m in rx.finditer(t, s0, e0):
        ss, se = _sentence_bounds(t, m.start(), m.end())
        left = t[ss: m.start()]
        if _is_hypothetical(left) or _COND_WORD.search(left[-90:]):
            continue
        out.append((ss, se))
        if len(out) >= 12:
            break
    return out


def detect_material_weakness(text: str, form: Optional[str] = None) -> dict[str, Any]:
    """A REPORTED material weakness (v2, B1/B12), not a mention of the phrase.

    A hit counts only when it is a reported weakness / adverse ICFR conclusion for the filing's own period:

    * management's or the auditor's conclusion language - "we identified a material weakness", "we concluded that our
      internal control over financial reporting was not effective", an adverse ICFR audit opinion ("did not maintain, in
      all material respects, effective internal control"), or a weakness described in the Item 9A section while Item 9A
      concludes "not effective";
    * NOT forward-looking boilerplate ("our ability to timely and effectively remediate material weaknesses", "any
      material weakness could ..."), NOT the auditor-report definition ("a deficiency, or a combination of
      deficiencies ..."), NOT negated ("no material weakness"), and NOT history: a weakness described as completed
      remediation / previously reported / as of an earlier balance-sheet date, or mentioned while Item 9A concludes ICFR
      WAS effective, is classified separately in ``remediated_hits`` (recorded, never flagged).

    Returns the usual ``{"detected", "hits", "negated_hits", "n_raw"}`` plus ``remediated_hits``, ``forward_looking_hits``,
    ``icfr_not_effective``, ``icfr_effective``, ``auditor_adverse_opinion``.  Every hit carries ``kind`` (``reported`` |
    ``icfr_not_effective`` | ``adverse_opinion``), ``section`` (``item9a`` | ``body`` | ``risk_factors`` | ``preface``)
    and ``pct_of_document``; ``hits`` is ordered Item 9A first and risk-factor / preface last, so ``hits[0]`` is the
    best excerpt to show.  A conclusion that ICFR/disclosure controls were not effective counts as a reported weakness
    even when the phrase "material weakness" is absent.
    """
    t = _prepare(text)
    res: dict[str, Any] = {"detected": False, "hits": [], "negated_hits": [], "n_raw": 0, "remediated_hits": [],
                           "forward_looking_hits": [], "icfr_not_effective": False, "icfr_effective": False,
                           "auditor_adverse_opinion": False}
    if not t:
        return res
    loc = locate_sections(t, form)
    n = len(t)
    scope = loc["item9a"] or (0, n)
    fy = _fiscal_year_of(t)

    # v3 (T2): "the audit report no longer expresses an adverse opinion" / "no longer ... not effective" is history, not a conclusion
    ineff = [sp for sp in _conclusion_sentences(t, scope, _ICFR_NOT_EFFECTIVE) if not _CONCLUSION_REVERSED.search(t[sp[0]:sp[1]])]
    adverse = [sp for sp in _conclusion_sentences(t, (0, n), _ICFR_ADVERSE) if not _CONCLUSION_REVERSED.search(t[sp[0]:sp[1]])]
    eff = [sp for sp in _conclusion_sentences(t, scope, _ICFR_EFFECTIVE) if not re.search(r"\bnot\s+effective\b", t[sp[0]:sp[1]], re.I)]
    res["icfr_not_effective"] = bool(ineff)
    res["auditor_adverse_opinion"] = bool(adverse)
    mgmt_effective = bool(eff) and not ineff and not adverse
    res["icfr_effective"] = mgmt_effective
    in_9a_span = loc["item9a"]

    def mk(pos: int, end: int, kind: str, reason: Optional[str], negated: bool, rank: int = 5) -> dict[str, Any]:
        ex_s, ex_e = max(0, pos - 160), min(n, end + 160)
        h = {"pattern": _MW_RX.pattern, "excerpt": _collapse(t[ex_s:ex_e]), "negated": negated, "reason": reason, "start": pos}
        return _tag_hit(h, loc, kind=kind, kind_rank=rank)

    reported: list[dict[str, Any]] = []
    raw_n = 0
    seen_pos: list[int] = []
    for m in _MW_RX.finditer(t):
        raw_n += 1
        s, e = m.start(), m.end()
        if len(seen_pos) > 400 or any(abs(s - p) < 40 for p in seen_pos[-6:]):
            continue
        seen_pos.append(s)
        ss, se = _sentence_bounds(t, s, e)
        left, sentence = t[ss:s], t[ss:se]
        continuing = bool(_MW_NOT_REMEDIATED.search(sentence)) or bool(_MW_NOT_REMEDIATED.search(t[se: se + 300]))
        if _MW_DEFINITION.search(sentence) and not re.search(r"\bidentified\b|\bconclude[sd]?\b", sentence, re.I):
            res["negated_hits"].append(mk(s, e, "definition", "boilerplate", True))
            continue
        if _MW_CERT.search(sentence):
            # v3 (T2): SOX 302/906 certification text names weaknesses generically; it reports none
            res["negated_hits"].append(mk(s, e, "certification", "boilerplate", True))
            continue
        if _MW_FORWARD_LEFT.search(left[-260:]) or _is_hypothetical(left):
            h = mk(s, e, "forward_looking", "forward_looking", True)
            res["forward_looking_hits"].append(h)
            res["negated_hits"].append(h)
            continue
        if mgmt_effective and in_9a_span is not None and not (in_9a_span[0] <= s < in_9a_span[1]):
            # v3 (T3): Item 9A concluded ICFR was effective and reported no weakness; a weakness mentioned elsewhere
            # (risk factors, preface, notes about third parties / acquirees) cannot set a current-year flag
            res["remediated_hits"].append(mk(s, e, "outside_9a_effective_icfr", "outside_9a_effective_icfr", False))
            continue
        if not continuing:
            neg, why = _classify_hit(t, s, e)
            if neg:
                res["negated_hits"].append(mk(s, e, "negated", why, True))
                continue
        asserted = bool(_MW_ASSERT.search(sentence))
        if not continuing:
            if (_MW_REMEDIATED.search(sentence) or _MW_REMEDIATED.search(t[se: se + 450])
                    or _MW_REMEDIATED.search(t[max(0, ss - 250): ss])):
                res["remediated_hits"].append(mk(s, e, "remediated", "remediated", False))
                continue
            years = [int(y) for y in (_ASOF_DATE.findall(t[e:se]) or _ASOF_DATE.findall(sentence))]   # v3: the date attached to the weakness
            if fy and years and max(years) < fy:
                res["remediated_hits"].append(mk(s, e, "prior_period", "prior_period", False))
                continue
            if _MW_PRIOR_PERIOD.search(sentence):
                res["remediated_hits"].append(mk(s, e, "prior_period", "prior_period", False))
                continue
            current_asof = bool(fy and re.search(rf"\b[Aa]s\s+of\s+[A-Z][a-z]+\s+\d{{1,2}},?\s+{fy}\b", sentence))
            if mgmt_effective and not current_asof:
                # management concluded ICFR WAS effective: any weakness described here is history, not a current one
                res["remediated_hits"].append(mk(s, e, "history_effective_icfr", "history_effective_icfr", False))
                continue
        in_9a = in_9a_span is not None and in_9a_span[0] <= s < in_9a_span[1]
        if asserted or continuing or ((ineff or adverse) and in_9a):
            reported.append(mk(s, e, "reported", None, False, rank=0))
        else:
            res["negated_hits"].append(mk(s, e, "mention", "no_assertion", True))
    res["n_raw"] = raw_n

    # conclusion-language hits (management 'not effective', auditor adverse opinion)
    for spans_, kind in ((ineff, "icfr_not_effective"), (adverse, "adverse_opinion")):
        for ss, se in spans_[:6]:
            h = {"pattern": kind, "excerpt": _collapse(t[max(0, ss): min(n, se + 120)])[:520], "negated": False, "reason": None, "start": ss}
            reported.append(_tag_hit(h, loc, kind=kind, kind_rank=1))
    res["hits"] = _rank_hits(reported)
    res["detected"] = bool(reported)
    res["remediated_hits"] = _rank_hits(res["remediated_hits"])
    return res


# --------------------------------------------------------------------------------------
# Restatement: non-reliance / restating PREVIOUSLY ISSUED financials (v2, B1)
# --------------------------------------------------------------------------------------

_NONRELIANCE_RX = re.compile(r"non-?reliance|no\s+longer\s+be\s+relied|should\s+not\s+be\s+relied\s+upon|\bitem\s+4\.02\b|\bnot\s+be\s+relied\s+upon\b", re.I)
_RESTATE_WORD = re.compile(r"\brestat(?:e|es|ed|ing|ement|ements)\b", re.I)
_PRIOR_FS = re.compile(
    r"previously\s+(?:issued|reported|filed|published|released|furnished)|"
    r"(?:prior|previous|earlier)\s+(?:period|year|quarter|fiscal)s?\b[^.]{0,40}?(?:financial|results)|"
    r"(?:annual|quarterly|interim|consolidated|audited|unaudited)\s+financial\s+statements|"
    r"\b(?:our|its|the\s+company.s|the)\s+(?:[\w'’\-]+\s+){0,3}?(?:financial\s+statements|financial\s+results|financials)\b|"
    r"financial\s+statements\s+(?:for|as\s+of)\b",
    re.I,
)
# a recast caused by adopting an accounting standard / changing principle / reorganising entities is not a restatement of ERRORS
_ACCT_CHANGE = re.compile(
    r"\badopt(?:ion|ed|ing|s)?\b|accounting\s+(?:standard|principle|change)|accounting\s+standards?\s+update|\bASU\b|\bstandard\b|"
    r"retrospective|retroactive|change\s+in\s+(?:accounting|reporting\s+entity|segment)|pooling|common\s+control|discontinued\s+operation|"
    r"stock\s+split|reclassif|conform|effect\s+of\s+the\s+change|(?:was|were)\s+discontinued|change\s+in\s+(?:method|estimate|policy)",
    re.I,
)
_RESTATE_ERROR = re.compile(
    r"\berrors?\b|misstat|irregularit|incorrect|non-?reliance|should\s+not\s+be\s+relied|no\s+longer\s+be\s+relied|\bfraud|"
    r"special\s+investigation|audit\s+committee\s+investigation|improper|material\s+weakness|\bitem\s+4\.02\b|invalid|inaccura",
    re.I,
)


# v3 (T2): a restatement is the REGISTRANT's own previously issued financial statements
_THIRD_PARTY_ROLE = re.compile(
    r"\b(?:investee|investees|equity[-\s]method|unconsolidated|affiliate|affiliates|joint\s+venture|customers?|suppliers?|vendors?|licensees?|franchisees?|"
    r"borrowers?|competitors?|third[-\s]part(?:y|ies)|former\s+parent|acquiree|target|counterpart(?:y|ies)|lessee|tenant)\b",
    re.I,
)
_RESTATE_DECLINED = re.compile(
    r"\brather\s+than\s+(?:to\s+)?restat|\b(?:chose|elected|decided|determined)\s+not\s+to\s+restat|"
    r"\b(?:not|never)\s+(?:be\s+)?(?:required|necessary|needed|appropriate|warranted)\s+to\s+restat|\bno\s+(?:need|requirement)\s+to\s+restat|\bnot\s+a\s+restatement\b",
    re.I,
)
_PROPER_SUBJ_RESTATED = re.compile(
    r"(?P<subj>(?:[A-Z][\w&.\-]*\s+){1,4})(?:(?:again|also|subsequently|then|recently)\s+)?(?:has\s+|have\s+|had\s+|will\s+)?(?:restated|restate)\s+(?:its|their)\b"
)
_OWN_NAMES = {"we", "our", "us", "the", "company", "registrant", "management", "board", "audit", "committee", "and", "that", "which", "however", "also", "then"}
_INVESTEE_CONTEXT = re.compile(r"equity[-\s]method|investee|unconsolidated|affiliate|joint\s+venture|summarized\s+financial\s+information|our\s+(?:investment|ownership|share\s+of)", re.I)
_IMMATERIAL = re.compile(r"\bimmaterial\b|\bnot\s+material\b|\bnot\s+(?:been\s+)?(?:deemed|considered|determined)\s+(?:to\s+be\s+)?material", re.I)
_REVISE = re.compile(r"\brevis(?:e|ed|es|ing|ion|ions)\b|out[-\s]of[-\s]period|\bcorrect(?:ed|ion|ions|ing)?\b", re.I)
_OWN_RESTATED = re.compile(
    r"\b(?:we|the\s+company|company|management|the\s+audit\s+committee)\s+(?:has\s+|have\s+|had\s+)?(?:\w+\s+)?restated\b|\brestated\s+(?:our|the\s+company.s)\b|"
    r"\bshould\s+be\s+restated\b|\bwill\s+(?:be\s+)?restate",
    re.I,
)
_OWN_FS_WORDS = re.compile(r"\b(?:our|the\s+company.s)\s+(?:previously|consolidated|financial|annual|quarterly|audited|unaudited)", re.I)


def _restatement_not_registrants(t: str, ss: int, se: int) -> Optional[str]:
    """v3 (T2): why a 'restated ...' sentence is not a restatement of the registrant's own issued financials (or None)."""
    sent = t[ss:se]
    if _RESTATE_DECLINED.search(sent):
        return "declined_or_not_a_restatement"
    if _THIRD_PARTY_ROLE.search(sent) and not _OWN_RESTATED.search(sent) and not _OWN_FS_WORDS.search(sent):
        return "third_party"
    m = _PROPER_SUBJ_RESTATED.search(sent)
    if m:
        words = [w.lower().strip(".,") for w in m.group("subj").split()]
        if words and not any(w in _OWN_NAMES for w in words) and _INVESTEE_CONTEXT.search(t[max(0, ss - 700): se + 700]):
            return "third_party"
    ctx = t[max(0, ss - 300): se + 300]
    if _IMMATERIAL.search(ctx) and _REVISE.search(ctx) and not _NONRELIANCE_RX.search(ctx) and not _OWN_RESTATED.search(sent):
        return "immaterial_revision"
    return None


def detect_restatement(text: str, form: Optional[str] = None) -> dict[str, Any]:
    """Non-negated restatement of PREVIOUSLY ISSUED financials, or non-reliance / Item 4.02 language (v2, B1).

    Hits in ``hits`` have ``kind`` ``non_reliance`` or ``restated_previously_issued`` (a "restate*" word in a sentence that
    says previously issued / prior-period / the company's financial statements-results, after the existing boilerplate
    filters: "Amended and Restated ...", reclassification, stock split, pooling, clawback policy, hypothetical risk-factor
    wording).  Bare mentions of "restatement" are kept in ``other_hits`` (``kind = mention``) and never make the result
    ``detected``.  Hits carry ``section`` / ``pct_of_document`` and are ordered body-first, risk factors / preface last.
    """
    base = _detect(text, RESTATEMENT_PATTERNS)
    if not base["hits"]:
        base["other_hits"] = []
        return base
    t = _prepare(text)
    loc = locate_sections(t, form)
    kept: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for h in base["hits"]:
        s = h["start"]
        ss, se = _sentence_bounds(t, s, s + 1)
        sent = t[ss:se]
        if _NONRELIANCE_RX.search(sent) or re.search(r"non-?reliance|relied|4\\.02", h["pattern"], re.I):
            kept.append(_tag_hit(h, loc, kind="non_reliance", kind_rank=0))
        elif _RESTATE_WORD.search(sent) and (why := _restatement_not_registrants(t, ss, se)):
            other.append(_tag_hit(h, loc, kind=why, kind_rank=9))
        elif _RESTATE_WORD.search(sent) and _PRIOR_FS.search(sent):
            ctx = t[max(0, ss - 400): se + 250]
            if _ACCT_CHANGE.search(ctx) and not _RESTATE_ERROR.search(ctx):
                other.append(_tag_hit(h, loc, kind="accounting_change_recast", kind_rank=9))
            else:
                kept.append(_tag_hit(h, loc, kind="restated_previously_issued", kind_rank=1))
        else:
            other.append(_tag_hit(h, loc, kind="mention", kind_rank=9))
    kept = _rank_hits(kept)
    return {"detected": bool(kept), "hits": kept, "other_hits": other,
            "negated_hits": base["negated_hits"], "n_raw": base["n_raw"]}


def detect_going_concern(text: str) -> dict[str, Any]:
    """Non-negated going-concern doubt: 'substantial doubt about ... ability to continue as a going concern'.

    A bare "going concern basis" / "assuming the Company continues as a going concern" is not a
    signal; "alleviated substantial doubt" and "no substantial doubt" are negated.
    """
    base = _detect(text, GOING_CONCERN_PATTERNS)
    if not base["hits"]:
        return base
    t = _prepare(text)
    kept: list[dict[str, Any]] = []
    dropped = list(base["negated_hits"])
    for h in base["hits"]:
        why = _gc_nongenuine_reason(t, h["start"])
        if why:
            dropped.append({**h, "negated": True, "reason": why})
        else:
            kept.append(h)
    return {"detected": bool(kept), "hits": kept, "negated_hits": dropped, "n_raw": base["n_raw"]}


# v3 (T1): text SEMANTICS that are not a going-concern doubt of THIS registrant
# (a) an accounting-pronouncement description (ASU 2014-15 / ASC 205-40: "requires management to evaluate whether ...")
_GC_PRONOUNCEMENT_REF = re.compile(
    r"\bASU\b|\bASC\s*205|\b205-40\b|Accounting\s+Standards\s+Update|\bFASB\b|\bSubtopic\b|"
    r"\b(?:amendments?|guidance|standard|update|pronouncement)\b[^.]{0,80}?\b(?:provides?|requires?|is\s+intended|aims?|effective)\b",
    re.I,
)
_GC_EVALUATE_WHETHER = re.compile(
    r"\b(?:(?:will\s+be\s+|is\s+|are\s+)?required\s+to|requires?\s+(?:that\s+)?(?:management\s+)?(?:to\s+)?|responsibility\s+to|must|shall)\s+"
    r"(?:evaluate|assess|determine|consider)\b|\b(?:evaluate|assess)\s+whether\s+there\s+(?:is|are)\b",
    re.I,
)
# an affirmative first-person / conditions-based conclusion of doubt survives even next to a pronouncement reference
_GC_AFFIRMED = re.compile(
    r"\b(?:these|such|those|the\s+(?:above|foregoing)|this|that)\s+(?:\w+\s+){0,3}?(?:conditions?|events?|factors?|matters?|circumstances|uncertainties)\b[^.]{0,60}?"
    r"\b(?:raise[sd]?|give[sn]?\s+rise\s+to|cast)\b|"
    r"\b(?:management|we|the\s+company|the\s+board)\s+(?:has\s+|have\s+)?(?:determined|concluded)\s+that\s+(?!there\s+(?:is|are|was|were)\s+no\b)[^.]{0,200}?\b(?:raises?|exists?|existed)\b|"
    r"\b(?:has|have)\s+expressed\s+substantial\s+doubt|\bexplanatory\s+paragraph\b|\bsuffered\s+recurring\s+losses|\bsubstantial\s+doubt\s+(?:exists|existed|remains)\b",
    re.I,
)
# (b) a conclusion that there is NO doubt
_GC_NO_DOUBT = re.compile(
    r"\bno\s+(?:substantial\s+doubt|conditions?|events?|factors?|circumstances)\b|"
    r"\b(?:did|does|do|has|have|had|was|were)\s+not\s+(?:\w+\s+){0,2}?(?:identif\w+|find|found|conclude|raise|give|have\s+substantial|aware|alleviat)|"
    r"\bnot\s+(?:aware|raise)\b|\bwithout\s+substantial\s+doubt\b|\bdoes\s+not\s+(?:raise|exist)\b",
    re.I,
)


def _gc_nongenuine_reason(t: str, pos: int) -> Optional[str]:
    """``"pronouncement"`` / ``"no_doubt"`` when the going-concern match at *pos* is not the registrant's own doubt, else None."""
    ss, se = _sentence_bounds(t, pos, pos + 1)
    sent = t[ss:se]
    prev = t[max(0, ss - 260):ss]
    contrast = _CONTRAST.search(sent) is not None
    if _GC_NO_DOUBT.search(sent) and not _GC_AFFIRMED.search(sent) and not re.search(r"\b(?:but|however|although|though|yet)\b", sent, re.I):
        return "no_doubt"
    if _GC_AFFIRMED.search(sent):
        return None
    if _GC_PRONOUNCEMENT_REF.search(sent) and (_GC_EVALUATE_WHETHER.search(sent) or re.search(r"\bASU\b|\b205-40\b|Accounting\s+Standards\s+Update|\bFASB\b", sent)):
        return "pronouncement"
    if _GC_EVALUATE_WHETHER.search(sent) and re.search(r"\bwhether\b[^.]{0,80}?\b(?:substantial\s+doubt|conditions?)", sent, re.I):
        return "pronouncement"
    if re.search(r"\bwhether\s+there\s+(?:is|are)\s+substantial\s+doubt", sent, re.I) and _GC_PRONOUNCEMENT_REF.search(prev + " " + sent):
        return "pronouncement"
    return None


# --------------------------------------------------------------------------------------
# Corporate-transaction context: SPAC shells and business combinations (v2, B10)
# --------------------------------------------------------------------------------------

_SHELL_CUES = [
    ("blank check self-description", re.compile(
        r"(?:\bwe\s+are|\bis|,)\s+(?:a\s+|an\s+)(?:newly\s+(?:organized|formed|incorporated)\s+)?(?:blank[-\s]check\s+(?:company|corporation)|"
        r"special\s+purpose\s+acquisition\s+(?:company|corporation))\b", re.I)),
    ("no operations / no revenue", re.compile(
        r"\bneither\s+engaged\s+in\s+any\s+operations\s+nor\s+generated\s+any\s+revenues?|"
        r"\b(?:we\s+)?have\s+not\s+(?:yet\s+)?(?:commenced|generated)\s+any\s+(?:operations?|revenues?)", re.I)),
    ("trust account for an initial business combination", re.compile(
        r"(?:\btrust\s+account\b[\s\S]{0,6000}?){5}", re.I)),
]
# past-tense completion of the combination (case-sensitive defined term; "consummate our initial business combination" in a
# SPAC's own risk factors is hypothetical and must not count)
_SHELL_PAST = re.compile(
    r"\bBusiness\s+Combination\s+(?:was|were|has\s+been|had\s+been)\s+(?:consummated|completed|closed)\b|"
    r"\b(?:consummated|completed|closed)\s+the\s+Business\s+Combination\b|"
    r"\b(?:was|were)\s+(?:formerly|previously)\s+(?:a\s+)?(?:blank[-\s]check|special\s+purpose)|"
    r"\bLegacy\s+[A-Z]\w+(?:[’']s)?\s+(?:Chief|CFO|CEO|financial\s+statements|stockholders|common|Class|Series|board|management)"
)
_LEGACY_CUE = re.compile(r"\bLegacy\s+[A-Z][A-Za-z0-9&.\-]+(?:[’']s)?\s+(?:Chief|CFO|CEO|auditor|independent|financial\s+statements|board|management|stockholders|common|Class|Series)")
_MERGER_STRONG = [
    ("pre-merger SPAC", re.compile(r"pre-?merger\s+(?:special\s+purpose|SPAC|blank[-\s]check)", re.I)),
    ("prior to the Business Combination", re.compile(r"\bprior\s+to\s+(?:the\s+)?(?:consummation\s+of\s+the\s+)?Business\s+Combination\b", re.I)),
    ("Legacy <Company>", _LEGACY_CUE),
    ("merger with a SPAC", re.compile(r"(?:merger|business\s+combination)\s+with\s+[^.]{0,80}(?:special\s+purpose\s+acquisition|blank[-\s]check|SPAC)", re.I)),
]
_MERGER_WEAK = [
    ("Business Combination consummated", re.compile(r"\b(?:consummat|complet|clos)\w*\s+(?:of\s+)?(?:the\s+)?Business\s+Combination\b", re.I)),
    ("reverse recapitalization", re.compile(r"reverse\s+recapitalization", re.I)),
]
_SPAC_WORD = re.compile(r"special\s+purpose\s+acquisition|blank[-\s]check|\bSPAC\b", re.I)


def detect_shell_filing(text: str) -> dict[str, Any]:
    """Is this filing a pre-merger SPAC / blank-check / shell company's own annual report?  (v2, B10)

    Requires at least two distinct PRESENT-tense self-description cues ("we are a blank check company", "we have neither
    engaged in any operations nor generated any revenues", initial business combination + trust account) in the first
    ~40% of the document and no "consummated the Business Combination" language.  Returns ``{"is_shell": bool, "cues": [...]}``.
    """
    t = _prepare(text)
    if not t:
        return {"is_shell": False, "cues": []}
    head = t[: max(60_000, int(len(t) * 0.4))]
    cues = [name for name, rx in _SHELL_CUES if rx.search(head)]
    past = bool(_SHELL_PAST.search(t))
    return {"is_shell": len(cues) >= 2 and not past, "cues": cues, "completed_combination_language": past}


_COMBO_SENT = re.compile(r"Business\s+Combination|merger", re.I)
_COMBO_DONE = re.compile(r"\b(?:consummat\w+|clos(?:ed|ing)|complet(?:ed|ion)|Closing\s+Date|effective\s+time)\b", re.I)
_DATE_YEAR = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(20\d\d|19\d\d)\b")


def _combination_year(t: str) -> Optional[int]:
    """Calendar year in which the document says the Business Combination / Merger CLOSED: the most frequent year among dates
    printed next to "consummated / closed / Closing Date" and "Business Combination" (needs >= 2 mentions, else ``None``)."""
    counts: dict[int, int] = {}
    n = 0
    for m in re.finditer(r"Business\s+Combination|\bMerger\b", t):
        win = t[max(0, m.start() - 150): m.end() + 150]
        if _COMBO_DONE.search(win):
            for dm in _DATE_YEAR.finditer(win):
                counts[int(dm.group(1))] = counts.get(int(dm.group(1)), 0) + 1
        n += 1
        if n > 400:
            break
    if not counts:
        return None
    yr, c = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return yr if c >= 2 else None


def detect_merger_context(text: str) -> dict[str, Any]:
    """Does the filing itself describe a business combination / SPAC merger / reverse merger?  (v2, B10)

    ``{"detected": bool, "cues": [str], "excerpt": str, "closing_year": int|None}`` (``closing_year``: the year printed most often next to
    "consummated / closed / Closing Date" and "Business Combination").  Strong cues: "prior to the Business Combination", "Legacy
    <Company> ... Chief/CFO/auditor", "pre-merger special purpose acquisition company", "merger with a special purpose
    acquisition company".  Weak cues (completed "Business Combination", reverse recapitalization) count only when two
    appear together with SPAC wording.  Used to mark auditor / CEO / CFO changes as merger mechanics, not governance signals.
    """
    t = _prepare(text)
    out: dict[str, Any] = {"detected": False, "cues": [], "excerpt": "", "closing_year": None}
    if not t:
        return out
    out["closing_year"] = _combination_year(t)
    strong, weak = [], []
    first: Optional[re.Match] = None
    for name, rx in _MERGER_STRONG:
        m = rx.search(t)
        if m:
            strong.append(name)
            first = first or m
    for name, rx in _MERGER_WEAK:
        m = rx.search(t)
        if m:
            weak.append(name)
            first = first or m
    if strong or (len(weak) >= 2 and _SPAC_WORD.search(t)):
        out["detected"] = True
        out["cues"] = strong + weak
        if first is not None:
            out["excerpt"] = _collapse(t[max(0, first.start() - 120): first.end() + 160])
    return out


# --------------------------------------------------------------------------------------
# Filing metadata
# --------------------------------------------------------------------------------------


def related_party_measure(secs: Mapping[str, Any]) -> tuple[int, Optional[str]]:
    """(chars, source) for the related-party disclosure of one filing (v2, B9).

    ``note``: the related-party note of the financial statements (the substantive disclosure, same kind of text every year);
    ``item13``: no note, but an inline Item 13 / 7.B body; ``pointer``: Item 13 only points elsewhere ("incorporated by
    reference", fewer than 400 characters) - its length is a formatting fact, not disclosure size; ``None``: nothing found.
    """
    note = secs.get("notes_rpt") or ""
    item13 = secs.get("related_party") or ""
    if note.strip():
        return len(note), "note"
    if item13.strip():
        ibr = bool((secs.get("incorporated_by_reference") or {}).get("related_party"))
        if ibr or len(item13.strip()) < 400:
            return len(item13), "pointer"
        return len(item13), "item13"
    return 0, None


def build_filing_metadata(filing: Mapping[str, Any] | None, text: str, proxy_text: Optional[str] = None) -> dict[str, Any]:
    """One metadata dict per filing for ``state["filing_metadata"][year]``.

    Keys: ``auditor``, ``ceo``, ``cfo``, ``filing_date``, ``form``, ``accession``, ``audit_fees``
    (float, absolute currency units of the filing - the *current-year audit fee*), ``audit_fee_source``
    (``"filing"`` | ``"proxy"`` | None), ``related_party_chars`` (v2, B9: ONE consistent
    measure - the length of the related-party NOTE when one was found (``related_party_source = "note"``), else the length of an
    inline Item 13 / 7.B body (``"item13"``), else the length of a mere pointer such as "incorporated by reference to the
    proxy" (``"pointer"``); ``None`` source = nothing found.  Only values with the same non-pointer source are comparable
    across years), ``related_party_note_chars`` / ``related_party_item13_chars`` (the two raw components),
    ``signatures_found``.  Extras: ``ceo_title``, ``cfo_title``, ``auditor_source``, ``audit_fee_detail``
    (full ``extract_audit_fees`` dict), ``sections_found``, ``incorporated_by_reference``, ``mdna_chars``,
    ``risk_factor_chars``, ``legal_chars``, ``item9_changes_text``, ``warnings``.
    Never raises; missing items are ``None``.
    """
    filing = filing or {}
    t = _prepare(text)
    form = filing.get("form") or None
    meta: dict[str, Any] = {
        "auditor": None,
        "ceo": None,
        "cfo": None,
        "filing_date": filing.get("filing_date"),
        "form": form,
        "accession": filing.get("accession"),
        "audit_fees": None,
        "audit_fee_source": None,
        "related_party_chars": 0,
        "related_party_source": None,
        "related_party_note_chars": 0,
        "related_party_item13_chars": 0,
        "signatures_found": False,
        "ceo_title": None,
        "cfo_title": None,
        "auditor_source": None,
        "audit_fee_detail": None,
        "sections_found": {},
        "incorporated_by_reference": {},
        "mdna_chars": 0,
        "risk_factor_chars": 0,
        "legal_chars": 0,
        "legal_note_chars": 0,
        "item9_changes_text": "",
        "warnings": [],
    }
    if not t:
        meta["warnings"].append("empty filing text")
        return meta
    try:
        secs = extract_sections(t, form)
        meta["sections_found"] = dict(secs["found"])
        meta["incorporated_by_reference"] = dict(secs["incorporated_by_reference"])
        rp_chars, rp_src = related_party_measure(secs)
        meta["related_party_chars"], meta["related_party_source"] = rp_chars, rp_src
        meta["related_party_note_chars"] = len(secs["notes_rpt"])
        meta["related_party_item13_chars"] = len(secs["related_party"])
        meta["signatures_found"] = bool(secs["found"]["signatures"])
        meta["mdna_chars"] = len(secs["mdna"])
        meta["risk_factor_chars"] = len(secs["risk_factors"])
        meta["legal_chars"] = len(secs["legal_proceedings"])
        meta["legal_note_chars"] = len(secs["legal_note"])
        meta["item9_changes_text"] = secs["item9_changes"][:3000]
    except Exception as exc:  # pragma: no cover - defensive
        secs = None
        meta["warnings"].append(f"sections failed: {exc!r}")
    try:
        det = extract_auditor_details(t)
        meta["auditor"], meta["auditor_source"] = det["name"], det["source"]
    except Exception as exc:  # pragma: no cover
        meta["warnings"].append(f"auditor failed: {exc!r}")
    try:
        sg = extract_signatories(t)
        meta["ceo"], meta["cfo"] = sg["ceo"], sg["cfo"]
        meta["ceo_title"], meta["cfo_title"] = sg["ceo_title"], sg["cfo_title"]
    except Exception as exc:  # pragma: no cover
        meta["warnings"].append(f"signatories failed: {exc!r}")
    try:
        fee = None
        if secs is not None and secs["item14"]:
            fee = extract_audit_fees(secs["item14"])
        if fee is not None:
            meta["audit_fee_source"] = "filing"
        elif proxy_text:
            fee = extract_audit_fees(proxy_text)
            if fee is not None:
                meta["audit_fee_source"] = "proxy"
        if fee is not None:
            meta["audit_fees"] = fee["audit_fees"]
            meta["audit_fee_detail"] = fee
    except Exception as exc:  # pragma: no cover
        meta["warnings"].append(f"audit fees failed: {exc!r}")
    return meta
