"""Financial-statement table parser for filings without usable XBRL (CONTRACTS D4).

Purpose
-------
Extract the canonical line items of CONTRACTS section 2 for a fiscal year (and the
prior-year comparatives printed in the same filing) from the consolidated balance sheet,
statement of operations and statement of cash flows *inside the annual report itself*.
It is used for pre-2009 filings (Enron FY2000 10-K, WorldCom FY2001 10-K405) and as a
fallback elsewhere.

Input is a string: modern HTML (BeautifulSoup rows) or plain text / SGML ``<TABLE>`` text
(column-aligned lines).  No network access happens here.

Method (deterministic, no LLM)
------------------------------
1. Split the document into tables (HTML ``<table>`` elements, ``<TABLE>`` blocks of
   old text filings, or page-sized text blocks when the filing has no table tags).
2. Turn each table into rows ``label | numbers``.  Numbers: ``(1,234)`` and ``-1,234`` are
   negative, ``--``/em-dash are 0, ``$`` and ``%`` are dropped (percent cells are ignored).
   Labels wrapped over several lines are re-joined.
3. Read the column years from the header rows (dates such as ``Sep. 26, 2020`` or plain
   ``2000``); column order is taken from the header (Enron prints newest first, WorldCom
   oldest first).  A January period end counts as the prior fiscal year (CONTRACTS D12).
4. Classify tables as balance sheet / income statement / cash flow by how many statement
   key rows they contain; the best table(s) win (a balance sheet split over two tables,
   as in Enron, is merged).
5. Match row labels to canonical items with a synonym dictionary (``_RULES``).  Aggregates that
   are not a cost of goods line (``Total costs and expenses``) are never used as COGS: when
   COGS cannot be separated it is reported missing, never guessed.
6. Scale (units / thousands / millions / billions) comes from the table caption, the text
   just above the table, or - flagged - from another statement of the same filing.  All
   values are returned in whole currency units (as XBRL would report them).
7. Identity validation per year column; a failing table is withheld, not returned:

   * balance: ``TotalAssets == Total liabilities and equity`` (or ``TL + equity + minority /
     redeemable interests`` when the combined total is not printed), tolerance 0.5 %
   * ``CurrentAssets <= TotalAssets``; ``CurrentLiabilities <= TotalLiabilities``
   * income: ``Revenue - COGS == GrossProfit`` when all three are printed
   * cross-statement: the first ``Net income`` row of the cash-flow statement equals one
     of the net-income rows of the income statement.

Derived items (always flagged ``derived`` with a ``derived:`` tag): ``TotalLiabilities =
TotalAssets - StockholdersEquity - minority/redeemable-preferred rows`` when no
``Total liabilities`` row is printed; ``COGS = Revenue - GrossProfit`` when only gross profit
is printed; ``CurrentDebt`` = sum of the short-term borrowing rows of the current-liability
section; ``GrossProfit = Revenue - COGS``.

Every returned FactValue (CONTRACTS section 2) keeps the source row label in ``tag``, the
table context in ``table`` and ``source = "statement-table"``; prior-year comparatives are
additionally marked ``comparative = True``.  Nothing is ever invented: unmatched items are
listed in ``missing`` with a reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:  # BeautifulSoup is only needed for HTML input.
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - import guard
    BeautifulSoup = None  # type: ignore

log = logging.getLogger("statement_parser")

__all__ = [
    "CANONICAL_ITEMS",
    "extract_statements",
    "extract_statements_from_file",
    "flatten_values",
    "parse_number",
    "detect_scale",
]

CANONICAL_ITEMS: tuple[str, ...] = (
    "Revenue", "COGS", "GrossProfit", "SGA", "NetIncome", "OperatingIncome",
    "InterestExpense", "IncomeTaxExpense", "OperatingCashFlow", "Depreciation",
    "TotalAssets", "CurrentAssets", "CurrentLiabilities", "TotalLiabilities",
    "NetReceivables", "PPE", "LongTermDebt", "CurrentDebt", "RetainedEarnings",
    "StockholdersEquity", "CashAndEquivalents",
)

# --------------------------------------------------------------------------------------
# Number / date / scale helpers
# --------------------------------------------------------------------------------------

_DASHES = {"-", "--", "---", "—", "–", "−", "‒", "―", "——"}
_NUM_FULL = re.compile(
    r"^\$?\s*(?P<open>\()?\s*(?P<sign>[-−–])?\s*\$?\s*(?P<num>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)\s*(?P<close>\))?\s*(?P<pct>%)?$"
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(
    r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(?P<day>\d{1,2})?\s*,?\s*(?P<year>(?:19|20)\d\d)",
    re.I,
)
_YEAR_ONLY = re.compile(r"^(?:fiscal\s*(?:year\s*)?|fy\s*|year\s*)?(?P<year>(?:19|20)\d\d)\s*(?:\([a-z0-9 ]{1,12}\))?$", re.I)


def parse_number(token: str) -> tuple[str, float | None]:
    """Parse one table cell.

    Returns ``(kind, value)`` where kind is ``"num"`` (value set), ``"dash"`` (value 0.0),
    ``"pct"`` (percentage, ignored by callers), ``"skip"`` (``$``, ``)``, empty) or
    ``"text"``.  ``(1,234)`` and ``(1,234`` are negative; ``-`` / em-dash alone is zero.
    """
    t = (token or "").replace("\xa0", " ").replace("​", "").strip()
    if t == "" or t in {"$", ")", "(", "$)", "%", ")%", "*", "†", "‡"}:
        return "skip", None
    if t in _DASHES or re.fullmatch(r"\$?\s*(?:-{1,3}|—|–|−)", t):
        return "dash", 0.0
    m = _NUM_FULL.match(t)
    if not m:
        return "text", None
    raw = m.group("num").replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return "text", None
    if m.group("pct"):
        return "pct", val
    neg = bool(m.group("open")) or bool(m.group("sign"))
    return "num", -val if neg else val


def _year_of(cell: str) -> int | None:
    """Year a header cell stands for (``Sep. 26, 2020`` -> 2020; January period ends -> year-1)."""
    t = (cell or "").replace("\xa0", " ").strip()
    if not t:
        return None
    m = _YEAR_ONLY.match(t)
    if m:
        return int(m.group("year"))
    m = _DATE_RE.search(t)
    if m and len(re.sub(r"[^0-9]", "", t)) <= 8:
        year = int(m.group("year"))
        if m.group("mon").lower() == "jan" and m.group("day"):
            return year - 1  # CONTRACTS D12: period ending in January -> prior fiscal year
        return year
    return None


def _date_of(cell: str) -> str | None:
    m = _DATE_RE.search(cell or "")
    if not m or not m.group("day"):
        return None
    try:
        return f"{int(m.group('year')):04d}-{_MONTHS[m.group('mon').lower()[:3]]:02d}-{int(m.group('day')):02d}"
    except Exception:
        return None


_SCALE_WORDS = {"thousand": 1e3, "thousands": 1e3, "million": 1e6, "millions": 1e6, "billion": 1e9, "billions": 1e9}
_SCALE_RES = [
    re.compile(r"\bin\s+(?:\w+\s+)?(thousands?|millions?|billions?)\b", re.I),
    re.compile(r"\(\s*\$?\s*(thousands?|millions?|billions?)\s*[,)]", re.I),
    re.compile(r"\b(thousands?|millions?|billions?)\s+of\s+(?:u\.?s\.?\s+)?(?:dollars|rmb|renminbi|euros?|pounds|yen|\w+\s+dollars)", re.I),
    re.compile(r"\$\s*(?:in\s+)?(thousands?|millions?|billions?)\b", re.I),
    re.compile(r"\bexpressed\s+in\s+(thousands?|millions?|billions?)\b", re.I),
    re.compile(r"\(\s*(?:in\s+)?(000)'?s\s*(?:omitted)?\s*\)|\bin\s+(000)'?s\b|\b(000)'?s\s+omitted", re.I),
]


def detect_scale(text: str, *, last: bool = False) -> tuple[float, str] | None:
    """Return ``(multiplier, matched text)`` for ``in millions / thousands / billions`` captions.

    ``last=True`` picks the match closest to the end of ``text`` (used for text printed above a table).
    """
    found: list[tuple[int, float, str]] = []
    for rx in _SCALE_RES:
        for m in rx.finditer(text or ""):
            grp = next((g for g in m.groups() if g), "")
            g = grp.lower()
            if g == "000":
                mult = 1e3
            else:
                mult = _SCALE_WORDS.get(g if g in _SCALE_WORDS else g.rstrip("s") + ("s" if g + "s" in _SCALE_WORDS else ""), None)
                if mult is None:
                    mult = _SCALE_WORDS.get(g.rstrip("s"))
            if mult:
                before = (text or "")[max(0, m.start() - 40): m.start()]
                if re.search(r"(?:reflected|shares?|share data|per[- ]share)\b[^()]{0,30}$", before, re.I):
                    continue  # 'number of shares, which are reflected in thousands' describes share counts, not amounts
                found.append((m.start(), mult, m.group(0)))
    if not found:
        return None
    found.sort()
    pos, mult, snippet = found[-1] if last else found[0]
    return mult, snippet.strip()


_CURRENCY_RES = [
    (re.compile(r"\b(?:rmb|renminbi|cny)\b|¥\s*in", re.I), "CNY"),
    (re.compile(r"\beuros?\b|€|\beur\b", re.I), "EUR"),
    (re.compile(r"\bpounds? sterling\b|£|\bgbp\b", re.I), "GBP"),
    (re.compile(r"\byen\b|\bjpy\b", re.I), "JPY"),
    (re.compile(r"\bcanadian dollars?\b|\bcad\b", re.I), "CAD"),
]


def _detect_currency(text: str) -> str:
    for rx, code in _CURRENCY_RES:
        if rx.search(text or ""):
            return code
    return "USD"


# --------------------------------------------------------------------------------------
# Row / table model
# --------------------------------------------------------------------------------------

@dataclass
class Row:
    label: str                      # source label (wrapped lines joined)
    norm: str                       # normalised label for matching
    values: list[float]             # numeric values in column order (after dropping pct/skip cells)
    tokens: list[str] = field(default_factory=list)  # raw cell tokens (header detection)
    idx: int = 0
    table_idx: int = 0
    yearvals: dict[int, float] = field(default_factory=dict)
    section: str = ""               # balance-sheet section tag (see _tag_sections)
    unlabeled: bool = False


@dataclass
class Table:
    index: int
    rows: list[Row]
    years: list[int]                # column years in column order
    year_dates: dict[int, str]      # year -> ISO date if header carried a full date
    context_fn: Any                 # callable returning text printed above the table
    caption: str = ""               # header-row text found inside the table
    kind_scores: dict[str, int] = field(default_factory=dict)
    scale: float | None = None
    scale_src: str = ""
    currency: str = "USD"
    _context: str | None = None

    def context(self) -> str:
        if self._context is None:
            try:
                self._context = self.context_fn() if self.context_fn else ""
            except Exception:  # pragma: no cover - defensive
                self._context = ""
        return self._context


def _norm_label(label: str) -> str:
    t = (label or "").replace("\xa0", " ").replace("’", "'").replace("‘", "'").replace("`", "'")
    # C1 control characters are cp1252 punctuation that was mis-decoded as latin-1 in some old filings
    t = t.translate({0x91: "'", 0x92: "'", 0x93: '"', 0x94: '"', 0x95: "-", 0x96: "-", 0x97: "-", 0xFFFD: "'"})
    t = t.replace("–", "-").replace("—", "-").replace("−", "-")
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?:\s*\((?:\d|[a-z])\))+\s*$", "", t)        # trailing footnote refs
    t = re.sub(r"^[\s\-•*]+", "", t)
    t = re.sub(r"[\s:.\-]+$", "", t)
    return t


_C1_FIX = {0x91: "'", 0x92: "'", 0x93: '"', 0x94: '"', 0x95: "-", 0x96: "-", 0x97: "-", 0xFFFD: "'"}


def _clean_cell(t: str) -> str:
    t = (t or "").replace("\xa0", " ").replace("​", " ").translate(_C1_FIX)
    return re.sub(r"\s+", " ", t).strip()


def _aligned_fraction(t: "Table") -> float:
    """Share of numeric rows whose values could be mapped onto the header years (low for multi-column / selected-data tables)."""
    data = [r for r in t.rows if r.values]
    return (sum(1 for r in data if r.yearvals) / len(data)) if data else 0.0


# ---- HTML -----------------------------------------------------------------------------

def _html_cells(tr: Any) -> list[str]:
    return [_clean_cell(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]


def _cells_to_label_tokens(cells: list[str]) -> tuple[str, list[str]]:
    """Split HTML cells of one row into (label, remaining cell tokens)."""
    label = ""
    rest: list[str] = []
    seen_label = False
    for c in cells:
        if not seen_label:
            if c == "":
                continue
            kind, _ = parse_number(c)
            if kind in ("text",) and re.search(r"[A-Za-z]", c) and _year_of(c) is None:
                label = c
                seen_label = True
                continue
            # A leading numeric / year cell means the row has no label.
            seen_label = True
        rest.append(c)
    return label, rest


def _html_preceding_context(table_tag: Any, limit_chars: int = 900) -> str:
    parts: list[str] = []
    total = 0
    for s in table_tag.find_all_previous(string=True, limit=80):
        if any(getattr(p, "name", None) == "table" for p in s.parents):
            break
        t = _clean_cell(str(s))
        if not t:
            continue
        parts.append(t)
        total += len(t)
        if total >= limit_chars:
            break
    return " ".join(reversed(parts))[-limit_chars:]


# ---- Text -----------------------------------------------------------------------------

_TAG_RE = re.compile(r"</?(?:s|c|caption|fn|table|page|r|tr|td|th|thead|tbody|pre)\b[^>]*>", re.I)
_RULE_LINE = re.compile(r"^[\s=\-_─═\.\*]+$")
_CONNECTOR_END = re.compile(
    r"(?:,|\band|\bor|\bof|\bnet|\bfor|\bto|\bin|\bon|\bfrom|\bbefore|\bwith|\bless|\bby|\bat|\bthe|\bother|\(net|\(|-)$", re.I
)


def _numeric_word(w: str) -> bool:
    return parse_number(w)[0] in ("num", "dash", "pct")


def _split_numeric_tail(line: str) -> tuple[str, list[str]]:
    """Split a text-table line into ``(label, [numeric tokens in column order])``.

    Columns are separated by 2+ spaces; ``$ 1,374`` (a currency sign separated from its number) stays one
    token.  A bare integer glued to a label by a single space (``Series B 29``) is not taken as a value.
    """
    s = line.rstrip()
    chunks = [(m.start(), m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", s)]
    toks: list[str] = []
    cut = len(s)
    for pos, ch in reversed(chunks):
        words = ch.split(" ")
        words = [w for w in words if w != ""]
        # merge a bare '$' with the following number
        merged: list[str] = []
        for w in words:
            if merged and merged[-1] in ("$", "($") and w:
                merged[-1] = merged[-1] + w
            else:
                merged.append(w)
        if all(_numeric_word(w) or w == "$" for w in merged):
            toks[:0] = [w for w in merged if w != "$"]
            cut = pos
            continue
        # trailing numeric words inside a mixed chunk: accept only unambiguous ones
        k = len(merged)
        taken: list[str] = []
        while k > 0 and _numeric_word(merged[k - 1]):
            w = merged[k - 1]
            if w.startswith(("$", "(")) or "," in w or "." in w or w in _DASHES or taken:
                taken.insert(0, w)
                k -= 1
            else:
                break
        if taken:
            toks[:0] = taken
            # position of the first taken word inside the chunk
            idx = len(" ".join(merged[:k])) + (1 if k else 0)
            cut = pos + idx
        break
    label = s[:cut].rstrip(" .	").strip()
    return label, toks


def _is_yearish_token(tok: str) -> bool:
    return _year_of(tok) is not None and not re.search(r"[,]\d", tok)


def _header_years_from_line(line: str) -> list[int]:
    """Years in a pure header line such as ``December 31, 2000   December 31, 1999``."""
    stripped = line.strip()
    if not stripped or len(stripped) > 170:
        return []
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters) > 80:
        return []
    out: list[int] = []
    for m in re.finditer(
        r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}\s*,?\s*)?(?<![\d,.$])((?:19|20)\d\d)(?![\d,])",
        stripped, re.I,
    ):
        seg = m.group(0)
        y = _year_of(seg)
        out.append(y if y is not None else int(m.group(1)))
    return out


def _text_rows(lines: list[str]) -> list[tuple[str, list[str], bool]]:
    """Convert raw text-table lines to ``(label, tokens, is_header_only)`` with wrapped labels re-joined."""
    out: list[tuple[str, list[str], bool]] = []
    pending: list[str] = []

    def flush() -> None:
        for p in pending:
            out.append((p, [], True))
        pending.clear()

    for raw in lines:
        line = _TAG_RE.sub(" ", raw.replace("\t", "    ").replace("\xa0", " "))
        if not line.strip():
            flush()
            continue
        if _RULE_LINE.match(line):
            continue
        label, toks = _split_numeric_tail(line)
        if toks:
            # label wrapped over previous label-only lines?
            if label:
                cur = label
                while pending:
                    prev = pending[-1]
                    if (cur[:1].islower() or cur[:1] in "$)0123456789") or _CONNECTOR_END.search(prev.rstrip()):
                        cur = prev.strip() + " " + cur
                        pending.pop()
                    else:
                        break
                label = cur
            flush()
            out.append((label, toks, False))
        else:
            hy = _header_years_from_line(line)
            if hy and len(re.sub(r"[^A-Za-z]", "", line)) < 60 and not pending:
                out.append(("", [str(y) for y in hy], False))
                continue
            pending.append(line.strip())
    flush()
    return out


# ---- table assembly -----------------------------------------------------------------

def _assemble(raw_rows: list[tuple[str, list[str], bool]], index: int, context_fn: Any) -> Table | None:
    """Build a Table from ``(label, tokens, header_only)`` triples; detect header years."""
    rows: list[Row] = []
    header_year_lists: list[list[tuple[int, str | None]]] = []
    caption_bits: list[str] = []
    seen_data = False
    for label, tokens, header_only in raw_rows:
        vals: list[float] = []
        kinds: list[str] = []
        pending_neg = False
        for tok in tokens:
            if tok.strip() == "(":
                pending_neg = True
                continue
            kind, v = parse_number(tok)
            if kind in ("num", "dash") and pending_neg and v is not None:
                v = -abs(v)
            pending_neg = False
            kinds.append(kind)
            if kind in ("num", "dash") and v is not None:
                vals.append(v)
        nonblank = [t for t in tokens if parse_number(t)[0] != "skip"]
        year_row = bool(nonblank) and all(_year_of(t) is not None for t in nonblank) and not any(
            re.fullmatch(r"\d{1,3}(?:,\d{3})+", t) for t in nonblank
        )
        if year_row and not seen_data:
            header_year_lists.append([(int(_year_of(t)), _date_of(t)) for t in nonblank])  # type: ignore[arg-type]
            if label:
                caption_bits.append(label)
            continue
        if year_row and seen_data:
            continue  # secondary header (e.g. pro-forma block): not data
        if vals and label and re.fullmatch(r"(?:note|notes)s?\s*[\d, and]*", _norm_label(label)):
            continue
        if not vals:
            if not seen_data:
                caption_bits.append(label)
                # date-only header text without numeric tokens (e.g. 'December 31, 2000')
                ys = []
                for t in tokens:
                    y = _year_of(t)
                    if y is not None:
                        ys.append((y, _date_of(t)))
                if ys:
                    header_year_lists.append(ys)
            if label.strip():
                rows.append(Row(label=label.strip(), norm=_norm_label(label), values=[], tokens=tokens, idx=len(rows), table_idx=index))
            continue
        seen_data = True
        rows.append(Row(label=label.strip(), norm=_norm_label(label), values=vals, tokens=tokens, idx=len(rows), table_idx=index,
                        unlabeled=not label.strip()))
    if not any(r.values for r in rows):
        return None
    years: list[int] = []
    year_dates: dict[int, str] = {}
    if header_year_lists:
        best = max(header_year_lists, key=lambda l: len(l))
        htxt = " ".join(caption_bits)
        months = set(m.group(0).lower()[:3] for m in re.finditer(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            htxt, re.I))
        if best and all(d is None for _, d in best) and months == {"jan"}:
            # plain year headers under 'Fiscal years ended January 31,' -> fiscal year is the prior calendar year (D12)
            best = [(y - 1, d) for y, d in best]
        for y, d in best:
            years.append(y)
            if d and y not in year_dates:
                year_dates[y] = d
    tbl = Table(index=index, rows=rows, years=years, year_dates=year_dates, context_fn=context_fn,
                caption=" | ".join(c for c in caption_bits if c)[:400])
    has_note_col = bool(re.search(r"\bnotes?\b", tbl.caption, re.I))
    # per-row year mapping (first occurrence of a year wins for duplicated years)
    for r in rows:
        if not r.values or not years:
            continue
        n = len(years)
        vals = r.values
        if len(vals) == n + 1 and has_note_col and float(vals[0]).is_integer() and 0 < vals[0] <= 60:
            vals = vals[1:]  # 'Note reference number' column printed before the amounts
        if len(vals) != n:
            continue  # cannot align safely (missing cells or extra columns such as segment / elimination columns)
        for col, y in enumerate(years):
            if y not in r.yearvals:
                r.yearvals[y] = vals[col]
    return tbl


def _tables_from_html(doc: str) -> list[Table]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required to parse HTML filings (pip install beautifulsoup4 lxml)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # iXBRL is XHTML: bs4 warns that an HTML parser reads XML
        try:
            soup = BeautifulSoup(doc, "lxml")
        except Exception:
            soup = BeautifulSoup(doc, "html.parser")
    tables: list[Table] = []
    for i, tb in enumerate(soup.find_all("table")):
        if tb.find("table") is not None:
            continue  # layout wrapper
        raw: list[tuple[str, list[str], bool]] = []
        for tr in tb.find_all("tr"):
            cells = _html_cells(tr)
            if not any(cells):
                continue
            label, rest = _cells_to_label_tokens(cells)
            raw.append((label, rest, False))
        if len(raw) < 3:
            continue
        t = _assemble(raw, i, (lambda tag=tb: _html_preceding_context(tag)))
        if t is not None:
            tables.append(t)
    return tables


_TABLE_BLOCK = re.compile(r"<table\b[^>]*>(.*?)</table\s*>", re.I | re.S)
_PAGE_SPLIT = re.compile(r"\f|<page>[^\n]*", re.I)


def _tables_from_text(doc: str) -> list[Table]:
    tables: list[Table] = []
    blocks: list[tuple[int, str]] = []
    for m in _TABLE_BLOCK.finditer(doc):
        blocks.append((m.start(), m.group(1)))
    if not blocks:
        pos = 0
        for part in _PAGE_SPLIT.split(doc):
            # sub-split on 3+ blank lines
            off = 0
            for sub in re.split(r"\n\s*\n\s*\n\s*\n", part):
                blocks.append((pos + off, sub))
                off += len(sub) + 4
            pos += len(part) + 1
    for i, (start, body) in enumerate(blocks):
        lines = body.split("\n")
        if len(lines) < 4:
            continue
        raw = _text_rows(lines)
        if len(raw) < 3:
            continue

        def ctx(start=start, doc=doc) -> str:
            seg = doc[max(0, start - 1200): start]
            k = seg.lower().rfind("</table")
            if k >= 0:
                seg = seg[k + 8:]  # only text between the previous table and this one
            seg = _TAG_RE.sub(" ", seg)
            return re.sub(r"[ \t]+", " ", seg)[-900:]

        t = _assemble(raw, i, ctx)
        if t is not None:
            tables.append(t)
    return tables


def _looks_like_html(doc: str) -> bool:
    return bool(re.search(r"<tr[\s>]", doc[:20_000_000], re.I)) and bool(re.search(r"<t[dh][\s>]", doc, re.I))


# --------------------------------------------------------------------------------------
# Label rules
# --------------------------------------------------------------------------------------

def _rx(*pats: str) -> list[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in pats]


# Each rule: statement(s) searched in order, ordered synonym regexes (first pattern that has a match wins;
# the first matching row wins inside a pattern), exclusion regex, optional section restriction.
_RULES: dict[str, dict[str, Any]] = {
    "Revenue": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^total (?:net )?(?:operating )?(?:revenues?|sales)(?:, net)?(?: and other (?:income|revenues?))?$",
            r"^total net (?:revenues?|sales)\b",
            r"^(?:net )?(?:operating )?(?:revenues?|sales)(?:,? net)?$",
            r"^revenues?,? net\b",
            r"^net (?:sales|revenues?)(?: and other revenues?)?$",
            r"^sales to customers\b",
            r"^(?:total )?operating revenues?$",
            r"^revenues?\b(?!.*(?:cost|expense))",
            r"^net sales\b",
        ),
        "exclude": re.compile(r"per share|percent|\bcost\b|expense|%", re.I),
    },
    "COGS": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^total costs? of (?:sales|revenues?|goods sold|products? sold|services?)",
            r"^cost of (?:goods sold|sales|revenues?|products? sold|merchandise sold|gas|merchandise)\b",
            r"^costs? of (?:sales|revenues?|goods sold)\b",
            r"^cost of [a-z, ]*(?:products|goods|revenues?|sales|services)\b",
            r"^line costs\b",
            r"^cost of (?:operations|services)\b",
        ),
        "exclude": re.compile(r"\bincome\b|\btax|\bdebt\b|\bcapital|\binterest|\bexcess", re.I),
        "ambiguous_if_multiple_from": 1,  # patterns idx >= 1 are component lines: >1 distinct rows -> ambiguous
        "abs": True,  # cost lines printed in parentheses (as negatives) are expense magnitudes, like XBRL CostOf*
    },
    "GrossProfit": {
        "stmts": ("IS",),
        "pats": _rx(r"^gross (?:profit|margin)\b", r"^gross income\b"),
        "exclude": re.compile(r"%|percent|\bratio\b", re.I),
    },
    "SGA": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^(?:total )?selling,? general,? (?:and|&) administrative",
            r"^selling,? (?:general|marketing)[a-z, ]*administrative",
            r"^selling,? general\b",
            r"^marketing,? general (?:and|&) administrative",
            r"^general,? (?:selling )?(?:and|&) administrative expenses?$",
        ),
        "exclude": re.compile(r"%|percent", re.I),
        "abs": True,
    },
    "OperatingIncome": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^(?:total )?operating (?:income|profit|earnings)(?: \(loss\))?$",
            r"^operating (?:income|profit|earnings|loss)\b(?!.*(?:per|margin))",
            r"^(?:income|earnings|profit) \(?(?:loss)?\)? ?from (?:continuing )?operations(?! before)(?!.*per)$",
            r"^income from operations\b",
            r"^operating \(loss\) income",
        ),
        "exclude": re.compile(r"%|percent|margin|per share|discontinued|before income tax|after tax", re.I),
    },
    "InterestExpense": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^interest expense\b(?!.*income)",
            r"^interest and related charges",
            r"^interest and debt expense",
            r"^interest expense\b",
            r"^interest(?: and other)? charges",
            r"^interest and other financial charges",
        ),
        "exclude": re.compile(r"%|percent|capitalized interest", re.I),
        "abs": True,
    },
    "IncomeTaxExpense": {
        "stmts": ("IS",),
        "pats": _rx(
            r"^provision for (?:\(?benefit from\)? ?)?income taxes",
            r"^(?:provision|benefit|\(?provision\)?|income tax)[a-z \(\)]*income tax(?:es)?$",
            r"^income tax(?:es)? (?:expense|provision)",
            r"^provision for taxes on income",
            r"^provision for taxes\b",
            r"^(?:provision for )?income taxes?$",
            r"^taxes on income",
            r"^income tax \(?(?:benefit|expense)\)?",
            r"^provision \(benefit\) for income taxes",
            r"^(?:benefit|provision) .*income taxes",
        ),
        "exclude": re.compile(r"before|deferred|after|payable|%|net of|excluding", re.I),
    },
    "NetIncome": {
        "stmts": ("IS", "CF"),
        "pats": _rx(
            r"^net (?:income|earnings|loss|\(loss\) income|income \(loss\)|earnings \(loss\)) attributable to (?!non-?controlling|redeemable|minority|preferred)",
            r"^net (?:income|earnings|loss|\(loss\) income|income \(loss\)|earnings \(loss\))$",
            r"^net (?:income|earnings) \(loss\)",
            r"^net (?:income|earnings|loss)(?: \(loss\))?,? (?:including|before) (?:non-?controlling|minority)",
            r"^net (?:income|earnings)\b(?!.*(?:per|before|applicable|available|common|group|per share))",
            r"^profit \(loss\)$|^profit for the (?:year|period)$",
        ),
        "exclude": re.compile(r"per (?:common )?share|%|percent|before cumulative|applicable to|available to", re.I),
    },
    "OperatingCashFlow": {
        "stmts": ("CF",),
        "pats": _rx(
            r"^net cash (?:provided by|from|generated by|provided from|flows? from|\(used in\) provided by|provided by \(used in\)|\(used in\)/provided by|provided \(used\) by)[a-z ,()/]*operating activities",
            r"^net cash (?:provided by|from|generated by|used in|provided from)[a-z ,()/]*operations",
            r"^cash (?:generated by|provided by|from|flows? from)[a-z ,()/]*operating activities",
            r"^net cash[a-z ,()/]*operating activities",
            r"^net cash[a-z ,()/]*operations",
            r"^total cash[a-z ,()/]*operating activities",
            r"^total operating activities$",
            r"^(?:net )?cash (?:flows? )?(?:provided|generated|from)[a-z ,()/]*\boperating\b",        ),
        "exclude": re.compile(r"investing|financing|discontinued", re.I),
    },
    "Depreciation": {
        "stmts": ("CF", "IS"),
        "pats": _rx(
            r"^depreciation(?:,? depletion)?(?:,?| and| &) ?(?:depletion,? )?(?:and )?amortization\b",
            r"^depreciation\b",
            r"^amortization and depreciation",
            r"^depreciation and amortization",
            r"^(?:total )?depreciation, depletion and amortization",
        ),
        "exclude": re.compile(r"accumulated|deferred income|%|percent|of (?:debt|intangible)|stock", re.I),
    },
    "TotalAssets": {
        "stmts": ("BS",),
        "pats": _rx(r"^total assets$", r"^total assets\b"),
        "exclude": re.compile(r"less|liabilities", re.I),
    },
    "CurrentAssets": {
        "stmts": ("BS",),
        "pats": _rx(r"^total current assets\b"),
        "exclude": None,
    },
    "CurrentLiabilities": {
        "stmts": ("BS",),
        "pats": _rx(r"^total current liabilities\b"),
        "exclude": None,
    },
    "TotalLiabilities": {
        "stmts": ("BS",),
        "pats": _rx(r"^total liabilities$", r"^total liabilities\b(?! and)"),
        "exclude": re.compile(r"\band (?:share|stock|equity|member|partners|owners|capital)|equity|deficit", re.I),
    },
    "NetReceivables": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^(?:trade )?accounts receivable\b",
            r"^trade (?:accounts )?receivables?\b",
            r"^receivables?,? (?:net|less)\b",
            r"^(?:accounts|notes) and (?:accounts|notes) receivable",
            r"^accounts? and notes? receivable",
            r"^(?:net )?receivables?\b",
            r"^trade and other receivables",
            r"^notes? and accounts? receivable",
        ),
        "exclude": re.compile(r"\bother\b(?! than)|non-?trade|long-?term|noncurrent|related part|affiliate|finance|financing|unbilled|tax", re.I),
        "section_not": ("NCA",),
    },
    "PPE": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^property,? plant,? (?:and|&) equipment,? ?-? ?net\b",
            r"^(?:net )?property,? plant,? (?:and|&) equipment\b(?!.*(?:at cost|gross))",
            r"^property (?:and|&) equipment,? ?-? ?net\b",
            r"^net property(?:,? plant)?(?: and equipment)?",
            r"^property,? plant,? (?:and|&) equipment,? (?:at cost,? )?(?:less|net of)",
            r"^property (?:and|&) equipment,? (?:at cost,? )?(?:less|net of)",
            r"^(?:land,? )?(?:buildings?,? )?(?:and )?equipment,? net\b",
            r"^plant,? property (?:and|&) equipment,? net",
        ),
        "exclude": re.compile(r"at cost(?!,? less)|gross|held for sale|discontinued|right-of-use|operating lease", re.I),
    },
    "LongTermDebt": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^long-?term (?:debt|borrowings|notes? payable|obligations?)\b",
            r"^(?:non-?current|long-?term) (?:portion of )?(?:debt|borrowings)\b",
            r"^term debt\b",
            r"^senior (?:notes|debt)\b",
            r"^notes payable,? (?:long|non)",
            r"^debt,? (?:less|net of) current\b",
            r"^debt$",
            r"^borrowings\b",
            r"^long-?term (?:debt|liabilities?),? (?:less|excluding)",
        ),
        "exclude": re.compile(r"current (?:portion|maturit|installment)|due (?:within|in) (?:one|1)|short-?term|current liabilities|within one year|lease|%|issuance|repayment|\bnet of current\b.*\bcurrent portion\b", re.I),
        # v3: "Long-term debt, excluding current maturities" / "..., net of current portion" IS the non-current line
        "strip_qualifier": re.compile(
            r"[,(]?\s*\(?(?:excluding|exclusive of|net of|less|less the|after)\s+(?:the\s+)?(?:current|short-?term)\s+"
            r"(?:portion|maturit\w*|installments?)(?:\s+of\s+(?:long-?term\s+)?(?:debt|borrowings|notes?))?\)?", re.I),
        "section_not": ("CL", "CA", "NCA", "EQ"),
    },
    "RetainedEarnings": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^retained earnings\b",
            r"^reinvested earnings\b",
            r"^accumulated deficit\b",
            r"^retained (?:income|deficit)\b",
            r"^earnings (?:retained|reinvested)\b",
            r"^(?:accumulated )?earnings\b(?!.*(?:comprehensive|loss))",
            r"^(?:deficit|accumulated deficit|retained earnings \(deficit\))",
        ),
        "exclude": re.compile(r"appropriated|restricted|unappropriated(?!.*retained)|comprehensive", re.I),
    },
    "StockholdersEquity": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^total (?:[a-z0-9&.,'\- ]+ )?(?:share|stock)holders'? ?(?:equity|investment|deficit)",
            r"^total (?:[a-z0-9&.,'\- ]+ )?share ?owners'? ?(?:equity|investment)",
            r"^total (?:[a-z0-9&.,'\- ]+ )?(?:stockholders|shareholders|shareowners)['’]? \(?(?:equity|deficit)",
            r"^(?:total )?(?:stockholders|shareholders|shareowners)['’]? ?(?:equity|investment|deficit)\b",
            r"^total (?:[a-z0-9&.,'\- ]+ )?equity\b",
            r"^total equity\b",
            r"^total (?:members|partners)['’]? ?(?:capital|equity)",
        ),
        "exclude": re.compile(r"liabilities|non-?controlling|temporary|mezzanine|redeemable", re.I),
    },
    "CashAndEquivalents": {
        "stmts": ("BS",),
        "pats": _rx(
            r"^cash and cash equivalents\b",
            r"^cash,? cash equivalents\b",
            r"^cash and equivalents\b",
            r"^cash and (?:short-?term|temporary) (?:investments|deposits)",
            r"^cash and due from banks",
            r"^cash$",
            r"^cash\b(?! flow)",
        ),
        "exclude": re.compile(r"restricted|flows?\b|held for sale|segregated|deposits? with", re.I),
        "section_not": ("CL", "NCL", "EQ"),
    },
}

_CURRENT_DEBT_PATS = _rx(
    r"^(?:short-?term|current) (?:debt|borrowings|notes? payable|obligations|loans)\b",
    r"^notes and loans payable\b",
    r"^short-?term debt and current (?:maturities|portion)",
    r"^current (?:portion|maturities|installments?) of (?:long-?term )?(?:debt|borrowings|notes|obligations)",
    r"^(?:long-?term )?debt (?:due|payable) (?:within|in) (?:one|1) year",
    r"^current (?:maturities|portion) of long-?term",
    r"^long-?term debt,? (?:current|due within)",
    r"^(?:current )?(?:portion of )?long-?term debt",
    r"^commercial paper\b",
    r"^notes payable\b",
    r"^loans? (?:and notes )?payable\b",
    r"^(?:bank )?(?:loans|borrowings|overdrafts?)\b",
    r"^term debt\b",
    r"^short-?term (?:and current|debt and)",
    r"^debt (?:maturing|due) (?:within|in)",
    r"^current debt\b",
)
_CURRENT_DEBT_EXCL = re.compile(r"lease|payable to|receivable|accounts payable|trade|tax|interest payable|accrued", re.I)
_MINORITY_RE = re.compile(
    r"^(?:non-?controlling|minority) interests?|preferred securities|mandatorily redeemable|redeemable (?:non-?controlling|preferred|convertible)|"
    r"temporary equity|mezzanine|trust preferred|company-?obligated",
    re.I,
)
_TLE_RE = re.compile(r"^total liabilities,? (?:and|&|plus) |^total liabilities, (?:minority|mezzanine|redeemable)|^total liabilities and", re.I)

# --------------------------------------------------------------------------------------
# Statement classification
# --------------------------------------------------------------------------------------

_BS_KEYS = _rx(r"^total assets", r"^total current assets", r"^total current liabilities", r"^total liabilities\b",
               r"^total liabilities and ", r"^total (?:[a-z0-9&.,'\- ]+ )?(?:share|stock)holders'? ?(?:equity|investment|deficit)",
               r"^retained earnings|^reinvested earnings|^accumulated deficit", r"^cash and cash equivalents|^cash and equivalents",
               r"^total equity", r"^total (?:non-?current|long-?term) liabilities|^total liabilities and")
_IS_KEYS = _rx(r"^(?:total )?(?:net )?(?:revenues?|sales)\b|^net sales|^sales to customers|^operating revenues?",
               r"^(?:total )?costs? of |^cost of|^total costs and expenses|^line costs",
               r"^operating (?:income|profit|earnings)|^income from operations",
               r"^(?:provision for |benefit from )?income tax|^provision for taxes|^income taxes",
               r"^net (?:income|earnings|loss)",
               r"per (?:common )?share|earnings per|^basic|^diluted",
               r"^gross (?:profit|margin)",
               r"^selling,? ")
_CF_KEYS = _rx(r"operating activities|^cash flows? from operat", r"investing activities", r"financing activities",
               r"^net cash[a-z ,()/]*operating activities|^net cash[a-z ,()/]*operations",
               r"^depreciation", r"^net (?:increase|decrease|\(decrease\)|change)[a-z ,()/]*cash",
               r"cash and cash equivalents,? (?:at )?(?:the )?(?:end|beginning)|cash at (?:end|beginning)|cash and cash equivalents at")


_PENALTY_RE = re.compile(
    r"\bgroup\b|pro ?forma|condensed|parent company|parent only|registrant only|quarter|unaudited|consolidating|guarantor|"
    r"segment|\bselected\b|supplemental|restated|schedule\s+i\b", re.I)


def _title_penalty(t: Table) -> int:
    """1 when the table's own caption or the text printed just above it marks a non-primary presentation."""
    head = (t.caption[:300] + " " + t.context()[-300:])
    return 1 if _PENALTY_RE.search(head) else 0


def _score_table(t: Table) -> dict[str, int]:
    def score(keys: list[re.Pattern[str]]) -> int:
        hit = 0
        for k in keys:
            if any(k.search(r.norm) for r in t.rows):
                hit += 1
        return hit

    bs = score(_BS_KEYS)
    is_ = score(_IS_KEYS)
    cf = score(_CF_KEYS)
    has_ni_cf = any(p.search(r.norm) for r in t.rows if r.values for p in _RULES["OperatingCashFlow"]["pats"])
    if not has_ni_cf:
        cf = min(cf, 2)
    has_total_assets = any(r.norm.startswith("total assets") and r.values for r in t.rows) or any(
        re.match(r"total current liabilities|total liabilities and", r.norm) and r.values for r in t.rows)
    if bs and not has_total_assets and not any(r.unlabeled for r in t.rows):
        bs = min(bs, 1)
    if cf >= 3 and is_ > cf + 1:  # a CF-like table that has more IS keys is not CF
        cf -= 1
    return {"BS": bs, "IS": is_, "CF": cf}


# --------------------------------------------------------------------------------------
# Balance-sheet section tagging
# --------------------------------------------------------------------------------------

def _tag_sections(rows: list[Row]) -> None:
    """Tag rows CA/NCA/CL/NCL/EQ using headers and totals (best effort)."""
    state = ""
    after_ca_total = False
    for r in rows:
        n = r.norm
        if re.match(r"^current assets\b", n) and not r.values:
            state = "CA"
        elif re.match(r"^total current assets\b", n):
            r.section = "CA"
            state = "NCA"
            after_ca_total = True
            continue
        elif re.match(r"^(?:liabilities and|liabilities,? )", n) and not r.values:
            state = "CL"
        elif re.match(r"^current liabilities\b", n) and not r.values:
            state = "CL"
        elif re.match(r"^total current liabilities\b", n):
            r.section = "CL"
            state = "NCL"
            continue
        elif re.match(r"^(?:long-?term|non-?current|deferred credits)[a-z ,\-]*liabilities", n) and not r.values:
            state = "NCL"
        elif re.match(r"^(?:(?:share|stock)holders'?|share ?owners'?|members'|partners'|common)\s?(?:equity|investment|deficit|capital)|^equity$", n) and not r.values:
            state = "EQ"
        elif re.match(r"^total liabilities$", n):
            state = "EQ"
        r.section = state


# --------------------------------------------------------------------------------------
# Core extraction
# --------------------------------------------------------------------------------------

def _close(a: float | None, b: float | None, scale: float, rel: float = 0.005) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), 2.0 * scale)


def _match_rows(rows: Iterable[Row], pats: list[re.Pattern[str]], exclude: re.Pattern[str] | None,
                section_not: tuple[str, ...] = (), strip: re.Pattern[str] | None = None) -> list[list[Row]]:
    """For each pattern, the list of matching rows (rows with values)."""
    result: list[list[Row]] = []
    for p in pats:
        found: list[Row] = []
        for r in rows:
            if not r.values or not r.norm:
                continue
            if section_not and r.section in section_not:
                continue
            if not p.search(r.norm):
                continue
            if exclude is not None and exclude.search(strip.sub("", r.norm) if strip is not None else r.norm):
                continue
            found.append(r)
        result.append(found)
    return result


@dataclass
class _Pick:
    rows: list[Row]
    derived: bool = False
    tag: str | None = None
    stmt: str = ""
    note: str = ""


def _pick_rows(item: str, stmt_rows: dict[str, list[Row]]) -> tuple[_Pick | None, str]:
    """Choose the source row(s) for one canonical item.  Returns (pick, reason_if_none)."""
    rule = _RULES[item]
    reasons: list[str] = []
    for stmt in rule["stmts"]:
        rows = stmt_rows.get(stmt, [])
        if not rows:
            reasons.append(f"{stmt} table not found")
            continue
        groups = _match_rows(rows, rule["pats"], rule.get("exclude"), rule.get("section_not", ()), rule.get("strip_qualifier"))
        amb_from = rule.get("ambiguous_if_multiple_from")
        if amb_from is not None:
            for grp in groups[:amb_from]:        # explicit totals ('Total cost of sales') win outright
                if grp:
                    return _Pick(rows=[grp[0]], stmt=stmt), ""
            comps: dict[str, Row] = {}
            for grp in groups[amb_from:]:
                for r in grp:
                    comps.setdefault(r.norm, r)
            if len(comps) > 1:
                reason = "multiple component cost-of lines without a total: " + "; ".join(sorted(comps))[:160]
                return None, reason
            if comps:
                return _Pick(rows=[next(iter(comps.values()))], stmt=stmt), ""
        else:
            for grp in groups:
                if grp:
                    return _Pick(rows=[grp[0]], stmt=stmt), ""
        reasons.append(f"no {stmt} row matches {item} synonyms")
    return None, "; ".join(reasons) or f"no row matches {item} synonyms"


def _unlabeled_totals(bs_rows: list[Row]) -> tuple[Row | None, Row | None]:
    """Unlabelled grand-total rows of a balance sheet (WorldCom prints both totals without a label).

    Returns ``(total_assets_row, total_liabilities_and_equity_row)``: the last unlabelled numeric row before the
    ``LIABILITIES AND ...`` heading and the last one after it.
    """
    liab_idx = next((r.idx for r in bs_rows if not r.values and re.match(r"^liabilities(?: and|,)", r.norm)), None)
    if liab_idx is None:
        return None, None
    before = [r for r in bs_rows if r.unlabeled and r.values and r.yearvals and r.idx < liab_idx]
    after = [r for r in bs_rows if r.unlabeled and r.values and r.yearvals and r.idx > liab_idx]
    return (before[-1] if before else None), (after[-1] if after else None)


def _ppe_from_unlabeled(bs_rows: list[Row], year: int, scale: float) -> tuple[Row | None, float | None]:
    """Unlabelled net PP&E line printed after an 'accumulated depreciation' row (gross + accumulated = net)."""
    for i, r in enumerate(bs_rows):
        if re.match(r"^(?:less:? )?accumulated depreciation|^less accumulated", r.norm) and r.values and i + 1 < len(bs_rows):
            nxt = bs_rows[i + 1]
            prev = bs_rows[i - 1] if i > 0 else None
            if nxt.unlabeled and year in nxt.yearvals and year in r.yearvals and prev is not None and year in prev.yearvals:
                gross, acc, net = prev.yearvals[year], r.yearvals[year], nxt.yearvals[year]
                if abs(gross - abs(acc) - net) <= max(0.005 * abs(net), 2.0) or abs(gross + acc - net) <= max(0.005 * abs(net), 2.0):
                    return nxt, net
    return None, None



# --------------------------------------------------------------------------------------
# v3: balance-sheet rows and "no long-term debt line" evidence
# --------------------------------------------------------------------------------------

#: A balance-sheet label that may carry borrowed money (any of these blocks the "no debt line" conclusion).
_DEBT_LIKE = re.compile(
    r"debt|\bnotes?\b|borrowing|\bloans?\b|\bbonds?\b|debenture|credit (?:facilit|agreement|line)|line of credit|mortgage|"
    r"\bsenior\b|subordinated|term loan|convertible|financing|capital lease|finance lease|lease obligation|"
    r"obligations? under|revolv|\bfunding\b|\bpayable to\b|due to (?:bank|lender|related)", re.I)
#: Non-current liability rows that are NOT debt (deferred / other / provisions); the only rows allowed in a "no debt" balance sheet.
_NONDEBT_NCL = re.compile(
    r"deferred|\bother\b|operating lease|asset retirement|pension|post-?retirement|retirement|employee|compensation|"
    r"income tax|\btaxes?\b|warrant|derivative|contingent|accrued|unearned|customer|rent|reserve|provision|"
    r"insurance|environmental|litigation|royalt|commitments|contingenc", re.I)


def _balance_rows_export(bs_rows: list[Row], years: Iterable[int], scale: float) -> list[dict[str, Any]]:
    """Plain-dict export of the chosen balance-sheet rows (label, section, values in whole currency units)."""
    out = []
    for r in bs_rows:
        if not r.values:
            continue
        out.append({"label": r.label, "section": r.section,
                    "values": {int(y): float(v) * scale for y, v in r.yearvals.items() if y in set(years)}})
    return out


def no_long_term_debt_evidence(bs_rows: list[Row], year: int, scale: float,
                               tl_value: float | None = None, tl_derived: bool = False) -> dict[str, Any]:
    """Does the balance sheet SHOW that the company has no long-term debt in ``year``?

    Beneish's LVGI uses *total long-term debt*; a company that has none reports no such line (and no XBRL concept), which is
    a zero, not a missing value.  The conclusion is drawn only when ALL of these hold (otherwise ``ok`` is False and the
    reason says which condition failed; nothing is guessed):

    * a printed ``Total current liabilities`` row has a value for ``year``, and total liabilities are known (printed
      ``Total liabilities`` row, or - when none is printed, as in most balance sheets - ``tl_value`` = TotalAssets -
      equity from the caller, then ``derived`` is reported);
    * every row after Total current liabilities and before the equity section / Total liabilities that has a value for
      ``year`` is a deferred / other / provision style liability (:data:`_NONDEBT_NCL`) and none looks like borrowed money
      (:data:`_DEBT_LIKE`, e.g. notes, borrowings, convertible, capital/finance lease);
    * those rows add up to ``Total liabilities - Total current liabilities`` within 0.5 % (so no non-current liability was
      overlooked); with no such rows the two totals must be equal.
    """
    cl = next((r for r in bs_rows if r.values and re.match(r"^total current liabilities\b", r.norm) and year in r.yearvals), None)
    if cl is None:
        return {"ok": False, "reason": "no printed 'Total current liabilities' row for this year"}
    tl_row = next((r for r in bs_rows if r.values and re.match(r"^total liabilities$", r.norm) and year in r.yearvals
                   and r.idx > cl.idx), None)
    derived = False
    if tl_row is not None:
        tl, tl_label = tl_row.yearvals[year], tl_row.label
    elif tl_value is not None:
        tl, tl_label, derived = tl_value, "derived: TotalAssets - equity", True
    else:
        return {"ok": False, "reason": "no printed 'Total liabilities' row and no TotalAssets - equity derivation"}
    end_idx = tl_row.idx if tl_row is not None else next(
        (r.idx for r in bs_rows if r.idx > cl.idx and r.section == "EQ"), None)
    if end_idx is None:
        return {"ok": False, "reason": "end of the liabilities section not found"}
    between = [r for r in bs_rows if cl.idx < r.idx < end_idx and r.values and year in r.yearvals
               and not re.match(r"^total\b", r.norm)]
    labels = [r.label for r in between]
    bad = [r.label for r in between if _DEBT_LIKE.search(r.norm) and not re.search(r"operating lease", r.norm)]
    if bad:
        return {"ok": False, "reason": f"debt-like non-current liability row(s): {bad}", "rows": labels}
    other = [r.label for r in between if not _NONDEBT_NCL.search(r.norm)]
    if other:
        return {"ok": False, "reason": f"non-current liability row(s) not recognisable as deferred/other: {other}", "rows": labels}
    gap = tl - cl.yearvals[year]
    ssum = sum(r.yearvals[year] for r in between)
    tol = max(0.005 * abs(tl), 2.0)
    if abs(gap - ssum) > tol:
        return {"ok": False, "reason": (f"non-current rows ({ssum * scale:,.0f}) do not add up to Total liabilities - Total "
                                        f"current liabilities ({gap * scale:,.0f})"), "rows": labels}
    return {"ok": True, "reason": "no debt-like row between Total current liabilities and "
            + ("the equity section (total liabilities derived as total assets - equity)" if derived else "Total liabilities")
            + "; the rows reconcile to the gap", "rows": labels, "total_liabilities": tl * scale,
            "current_liabilities": cl.yearvals[year] * scale, "total_liabilities_label": tl_label, "tl_derived": derived}


def _fv(value: float, tag: str, unit: str, form: str, filed: str | None, accn: str | None, end: str | None,
        derived: bool, table: dict[str, Any], year: int, comparative: bool, fiscal_year: int) -> dict[str, Any]:
    return {
        "value": float(value), "tag": tag, "unit": unit, "form": form, "filed": filed, "accn": accn,
        "start": None, "end": end, "derived": derived, "source": "statement-table",
        "table": table, "column_year": year, "comparative": comparative, "from_filing_fy": fiscal_year,
    }


def extract_statements(
    text_or_html: str,
    fiscal_year: int,
    form: str = "10-K",
    *,
    period_end: str | None = None,
    filed: str | None = None,
    accn: str | None = None,
) -> dict[str, Any]:
    """Extract canonical line items for ``fiscal_year`` (+ prior-year comparatives) from a filing's own tables.

    Parameters
    ----------
    text_or_html : full text (plain/SGML) or HTML of the annual report.
    fiscal_year  : fiscal year of the filing (CONTRACTS D12); selects the current column.
    form         : form type (metadata only).
    period_end, filed, accn : optional metadata copied into every FactValue.

    Returns
    -------
    ``{"values": {canonical: FactValue}, "missing": {canonical: reason},
    "prior_values", "prior_missing", "by_year": {year: {canonical: FactValue}}, "missing_by_year",
    "checks": {"balance_identity": bool|None, ...}, "checks_detail", "warnings", "scale", "unit",
    "tables": {statement: context}, "fiscal_year", "form"}``.  Never raises on missing data.
    """
    warnings: list[str] = []
    result: dict[str, Any] = {
        "values": {}, "missing": {}, "prior_values": {}, "prior_missing": {}, "by_year": {}, "missing_by_year": {},
        "checks": {}, "checks_detail": {}, "balance_rows": [], "no_debt_evidence": {}, "warnings": warnings, "scale": None, "unit": "USD", "tables": {},
        "fiscal_year": fiscal_year, "form": form,
    }
    doc = text_or_html or ""
    if not doc.strip():
        warnings.append("empty document")
        _fill_all_missing(result, fiscal_year, "empty document")
        return result
    try:
        tables = _tables_from_html(doc) if _looks_like_html(doc) else _tables_from_text(doc)
    except Exception as exc:  # defensive: never crash on malformed input
        warnings.append(f"table extraction failed: {type(exc).__name__}: {exc}")
        _fill_all_missing(result, fiscal_year, "table extraction failed")
        return result

    for t in tables:
        t.kind_scores = _score_table(t)

    chosen: dict[str, list[Table]] = {}
    for stmt, min_score in (("BS", 3), ("IS", 3), ("CF", 3)):
        cands = [t for t in tables if t.kind_scores[stmt] >= min_score and t.years and _aligned_fraction(t) >= 0.5]
        if not cands:
            weaker = [t for t in tables if t.kind_scores[stmt] >= min_score]
            if weaker:
                warnings.append(f"{stmt}: best candidate table has no year header; skipped")
            continue
        # Prefer tables that are not group / pro-forma / condensed / quarterly presentations, then the best key-row
        # score, then the earliest table (the audited consolidated statements precede supplementary copies).
        top = sorted(cands, key=lambda t: (t.kind_scores[stmt], sum(1 for r in t.rows if r.values)), reverse=True)[:10]
        top.sort(key=lambda t: (_title_penalty(t), -t.kind_scores[stmt], t.index))
        cands = top
        best = cands[0]
        group = [best]
        if stmt == "BS":
            for t in tables:
                if t is best or t.kind_scores["BS"] < 1 or not t.years:
                    continue
                if abs(t.index - best.index) <= 2 and set(t.years) & set(best.years):
                    if t.kind_scores["IS"] > t.kind_scores["BS"] or t.kind_scores["CF"] > t.kind_scores["BS"]:
                        continue
                    group.append(t)
        chosen[stmt] = sorted(group, key=lambda t: t.index)
    names = {"BS": "balance_sheet", "IS": "income_statement", "CF": "cash_flow"}
    for stmt in ("BS", "IS", "CF"):
        if stmt not in chosen:
            warnings.append(f"{names[stmt]}: no qualifying table found")

    # ---- scale / unit
    stmt_scale: dict[str, tuple[float, str]] = {}
    unit_hits: list[str] = []
    for stmt, group in chosen.items():
        for t in group:
            sc = detect_scale(" ".join([t.caption, " ".join(r.label for r in t.rows[:8] if not r.values)]))
            src = "table caption"
            if sc is None:
                ctx = t.context()
                sc = detect_scale(ctx, last=True)
                src = "text above table"
            if sc is not None:
                t.scale, t.scale_src = sc[0], f"{src}: {sc[1]}"
            t.currency = _detect_currency(t.caption + " " + t.context())
            unit_hits.append(t.currency)
        scs = [(t.scale, t.scale_src) for t in group if t.scale]
        if scs:
            stmt_scale[stmt] = scs[0]
    fallback = next(iter(stmt_scale.values()), None)
    for stmt, group in chosen.items():
        for t in group:
            if t.scale is None:
                if fallback is not None:
                    t.scale, t.scale_src = fallback[0], f"ASSUMED from another statement of this filing ({fallback[1]})"
                    warnings.append(f"{names[stmt]}: scale not found in caption; assumed {fallback[0]:g} from another statement")
                else:
                    t.scale, t.scale_src = 1.0, "ASSUMED units (no 'in thousands/millions' caption found)"
                    warnings.append(f"{names[stmt]}: no scale caption found anywhere; values taken as printed (scale 1)")
    scales = {t.scale for g in chosen.values() for t in g}
    if len(scales) > 1:
        warnings.append(f"statements use different scales: {sorted(s for s in scales if s)}")
    result["scale"] = next(iter(scales)) if len(scales) == 1 else (sorted(scales)[0] if scales else None)
    currency = next((u for u in unit_hits if u != "USD"), "USD")
    result["unit"] = currency
    if currency != "USD":
        warnings.append(f"non-USD reporting currency detected: {currency}")

    # ---- rows per statement
    stmt_rows: dict[str, list[Row]] = {}
    stmt_tables: dict[str, list[Table]] = chosen
    for stmt, group in chosen.items():
        rows: list[Row] = []
        for t in group:
            rows.extend(t.rows)
        for i, r in enumerate(rows):
            r.idx = i
        if stmt == "BS":
            _tag_sections(rows)
        stmt_rows[stmt] = rows
    for stmt, group in chosen.items():
        result["tables"][names[stmt]] = {
            "table_index": [t.index for t in group], "years": group[0].years,
            "scale": group[0].scale, "scale_source": group[0].scale_src, "caption": group[0].caption[:200],
            "context": group[0].context()[-240:], "rows": sum(len(t.rows) for t in group),
        }

    years_avail: set[int] = set()
    for g in chosen.values():
        for t in g:
            years_avail |= set(t.years)
    if fiscal_year not in years_avail and years_avail:
        warnings.append(f"fiscal_year {fiscal_year} not among table column years {sorted(years_avail)}")
    target_years = [y for y in (fiscal_year, fiscal_year - 1) if y in years_avail]
    # also expose other printed years (e.g. 3-year income statement)
    all_years = sorted(years_avail, reverse=True)

    # ---- pick rows once, apply to every year column
    picks: dict[str, _Pick | None] = {}
    why_missing: dict[str, str] = {}
    for item in CANONICAL_ITEMS:
        if item == "CurrentDebt":
            continue
        pk, reason = _pick_rows(item, stmt_rows)
        picks[item] = pk
        if pk is None:
            why_missing[item] = reason

    unit = result["unit"]
    scale_of_stmt = {s: (g[0].scale or 1.0) for s, g in chosen.items()}

    def table_ctx(stmt: str) -> dict[str, Any]:
        return result["tables"].get(names.get(stmt, ""), {})

    for y in all_years:
        comparative = y != fiscal_year
        vals: dict[str, dict[str, Any]] = {}
        miss: dict[str, str] = {}
        end = None
        for g in chosen.values():
            for t in g:
                if y in t.year_dates:
                    end = t.year_dates[y]
                    break
            if end:
                break
        if end is None and y == fiscal_year:
            end = period_end

        def put(item: str, value: float, tag: str, stmt: str, derived: bool = False) -> None:
            sc = scale_of_stmt.get(stmt, result["scale"] or 1.0)
            vals[item] = _fv(value * sc, tag, unit, form, filed, accn, end, derived, table_ctx(stmt), y, comparative, fiscal_year)

        for item, pk in picks.items():
            if pk is None:
                miss[item] = why_missing.get(item, "no matching row")
                continue
            row = pk.rows[0]
            if y not in row.yearvals:
                miss[item] = f"row '{row.label}' has no value for column year {y}"
                continue
            v = row.yearvals[y]
            if _RULES[item].get("abs"):
                v = abs(v)
            put(item, v, row.label, pk.stmt)

        # --- BS special cases
        bs_rows = stmt_rows.get("BS", [])
        bs_scale = scale_of_stmt.get("BS", 1.0)
        if bs_rows:
            ta_unl, tle_unl = _unlabeled_totals(bs_rows)
            if "TotalAssets" not in vals and ta_unl is not None and y in ta_unl.yearvals:
                put("TotalAssets", ta_unl.yearvals[y], "(unlabeled total row after 'Other assets'; before liabilities)", "BS")
                miss.pop("TotalAssets", None)
            if "PPE" not in vals:
                prow, pval = _ppe_from_unlabeled(bs_rows, y, bs_scale)
                if prow is not None and pval is not None:
                    put("PPE", pval, "(unlabeled net subtotal after 'Accumulated depreciation')", "BS")
                    miss.pop("PPE", None)
            # current debt: sum of current-liability debt rows
            cd_rows: list[Row] = []
            seen: set[str] = set()
            for r in bs_rows:
                if not r.values or y not in r.yearvals or r.norm in seen:
                    continue
                in_cl = r.section == "CL"
                txt_current = bool(re.search(r"current (?:portion|maturit)|due within|short-?term|within one year", r.norm))
                if not (in_cl or txt_current):
                    continue
                if r.section in ("NCL", "EQ", "CA", "NCA"):
                    continue
                if _CURRENT_DEBT_EXCL.search(r.norm):
                    continue
                if any(p.search(r.norm) for p in _CURRENT_DEBT_PATS):
                    cd_rows.append(r)
                    seen.add(r.norm)
            if cd_rows:
                total = sum(r.yearvals[y] for r in cd_rows)
                if len(cd_rows) == 1:
                    put("CurrentDebt", total, cd_rows[0].label, "BS")
                else:
                    put("CurrentDebt", total, "derived:sum(" + " + ".join(r.label[:48] for r in cd_rows) + ")", "BS", derived=True)
            else:
                miss["CurrentDebt"] = "no short-term debt / current-maturities row in the current-liabilities section"
            # total liabilities derivation
            if "TotalLiabilities" not in vals and "TotalAssets" in vals and "StockholdersEquity" in vals:
                minority = [r for r in bs_rows if r.values and y in r.yearvals and _MINORITY_RE.search(r.norm)
                            and not re.match(r"^total", r.norm)]
                dedup: dict[str, Row] = {}
                for r in minority:
                    dedup.setdefault(r.norm, r)
                msum = sum(r.yearvals[y] for r in dedup.values())
                tl = vals["TotalAssets"]["value"] / bs_scale - vals["StockholdersEquity"]["value"] / bs_scale - msum
                tag = "derived:TotalAssets-StockholdersEquity" + "".join(f"-[{r.label[:40]}]" for r in dedup.values())
                put("TotalLiabilities", tl, tag, "BS", derived=True)
                miss.pop("TotalLiabilities", None)
            elif "TotalLiabilities" not in vals:
                miss.setdefault("TotalLiabilities", "no 'Total liabilities' row and TotalAssets/StockholdersEquity unavailable for derivation")
        else:
            miss.setdefault("CurrentDebt", "balance sheet not found")

        # --- IS derived: COGS from gross profit, GP from revenue-COGS
        if "Revenue" in vals and "COGS" not in vals and "GrossProfit" in vals:
            put("COGS", (vals["Revenue"]["value"] - vals["GrossProfit"]["value"]) / scale_of_stmt.get("IS", 1.0),
                "derived:Revenue-GrossProfit", "IS", derived=True)
            miss.pop("COGS", None)
        if "Revenue" in vals and "COGS" in vals and "GrossProfit" not in vals:
            put("GrossProfit", (vals["Revenue"]["value"] - vals["COGS"]["value"]) / scale_of_stmt.get("IS", 1.0),
                "derived:Revenue-COGS", "IS", derived=True)
            miss.pop("GrossProfit", None)

        result["by_year"][y] = vals
        result["missing_by_year"][y] = miss

    _validate(result, stmt_rows, chosen, fiscal_year, all_years)

    # v3: balance-sheet face rows and per-year "no long-term debt line" evidence (see no_long_term_debt_evidence)
    if stmt_rows.get("BS"):
        try:
            bs_sc = scale_of_stmt.get("BS", 1.0)
            result["balance_rows"] = _balance_rows_export(stmt_rows["BS"], all_years, bs_sc)
            def _tlv(y: int) -> float | None:
                fv = (result["by_year"].get(y) or {}).get("TotalLiabilities")
                return fv["value"] / bs_sc if fv else None
            result["no_debt_evidence"] = {y: no_long_term_debt_evidence(stmt_rows["BS"], y, bs_sc, tl_value=_tlv(y))
                                          for y in all_years}
        except Exception as exc:  # pragma: no cover - defensive, evidence is optional
            warnings.append(f"balance-sheet evidence failed: {type(exc).__name__}: {exc}")

    result["values"] = result["by_year"].get(fiscal_year, {})
    result["missing"] = result["missing_by_year"].get(fiscal_year, {})
    result["prior_values"] = result["by_year"].get(fiscal_year - 1, {})
    result["prior_missing"] = result["missing_by_year"].get(fiscal_year - 1, {})
    if fiscal_year not in result["by_year"]:
        _fill_year_missing(result, fiscal_year, "no table column for this fiscal year")
    if (fiscal_year - 1) not in result["by_year"]:
        _fill_year_missing(result, fiscal_year - 1, "no prior-year comparative column found")
    for key in ("missing", "prior_missing"):
        for item in CANONICAL_ITEMS:
            vv = result["values" if key == "missing" else "prior_values"]
            if item not in vv:
                result[key].setdefault(item, "not extracted")
    return result


def _fill_year_missing(result: dict[str, Any], year: int, reason: str) -> None:
    miss = {i: reason for i in CANONICAL_ITEMS}
    result["missing_by_year"].setdefault(year, miss)
    if year == result["fiscal_year"]:
        result["missing"] = dict(miss)
    elif year == result["fiscal_year"] - 1:
        result["prior_missing"] = dict(miss)


def _fill_all_missing(result: dict[str, Any], fiscal_year: int, reason: str) -> None:
    _fill_year_missing(result, fiscal_year, reason)
    _fill_year_missing(result, fiscal_year - 1, reason)
    result["checks"] = {"balance_identity": None}


# --------------------------------------------------------------------------------------
# Identity validation
# --------------------------------------------------------------------------------------

_BS_ITEMS = ("TotalAssets", "CurrentAssets", "CurrentLiabilities", "TotalLiabilities", "NetReceivables", "PPE", "LongTermDebt",
             "CurrentDebt", "RetainedEarnings", "StockholdersEquity", "CashAndEquivalents")
_IS_GP_ITEMS = ("Revenue", "COGS", "GrossProfit")


def _validate(result: dict[str, Any], stmt_rows: dict[str, list[Row]], chosen: dict[str, list[Table]],
              fiscal_year: int, years: list[int]) -> None:
    checks: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    bs_rows = stmt_rows.get("BS", [])
    is_rows = stmt_rows.get("IS", [])
    cf_rows = stmt_rows.get("CF", [])
    bs_scale = (chosen["BS"][0].scale or 1.0) if "BS" in chosen else 1.0
    for y in years:
        vals = result["by_year"].get(y, {})
        miss = result["missing_by_year"].setdefault(y, {})
        d: dict[str, Any] = {}

        def v(item: str) -> float | None:
            return vals[item]["value"] if item in vals else None

        # --- balance identity
        ta = v("TotalAssets")
        tle_val: float | None = None
        tle_label = ""
        if bs_rows:
            for r in bs_rows:
                if r.values and y in r.yearvals and _TLE_RE.search(r.norm):
                    tle_val, tle_label = r.yearvals[y] * bs_scale, r.label
                    break
            if tle_val is None:
                _, tle_unl = _unlabeled_totals(bs_rows)
                if tle_unl is not None and y in tle_unl.yearvals:
                    tle_val, tle_label = tle_unl.yearvals[y] * bs_scale, "(unlabeled total after liabilities heading)"
        bal: bool | None = None
        if ta is not None and tle_val is not None:
            bal = _close(ta, tle_val, bs_scale)
            d["balance_identity"] = {"TotalAssets": ta, "TotalLiabilitiesAndEquity": tle_val, "row": tle_label, "ok": bal}
        elif ta is not None and v("TotalLiabilities") is not None and v("StockholdersEquity") is not None \
                and not vals["TotalLiabilities"]["derived"]:
            minor = 0.0
            seen: set[str] = set()
            for r in bs_rows:
                if r.values and y in r.yearvals and _MINORITY_RE.search(r.norm) and not r.norm.startswith("total") and r.norm not in seen:
                    seen.add(r.norm)
                    minor += r.yearvals[y] * bs_scale
            ok_variants = [v("TotalLiabilities") + v("StockholdersEquity"), v("TotalLiabilities") + v("StockholdersEquity") + minor]
            teq = next((r.yearvals[y] * bs_scale for r in bs_rows if r.values and y in r.yearvals and re.match(r"^total equity\b", r.norm)), None)
            if teq is not None:
                ok_variants.append(v("TotalLiabilities") + teq)
            bal = any(_close(ta, x, bs_scale) for x in ok_variants)
            d["balance_identity"] = {"TotalAssets": ta, "variants": ok_variants, "ok": bal}
        if bal is None and ta is not None:
            d["balance_identity"] = {"ok": None, "note": "combined total not printed and TL/equity unavailable; not testable"}
        ca = v("CurrentAssets")
        if ca is not None and ta is not None:
            d["current_assets_le_total"] = {"ok": ca <= ta * 1.0005}
        cl, tl = v("CurrentLiabilities"), v("TotalLiabilities")
        if cl is not None and tl is not None:
            d["current_liabilities_le_total"] = {"ok": cl <= tl * 1.0005}
        # --- income identity
        rev, cg, gp = v("Revenue"), v("COGS"), v("GrossProfit")
        gp_ok: bool | None = None
        if rev is not None and cg is not None and gp is not None and not vals["GrossProfit"]["derived"] and not vals["COGS"]["derived"]:
            gp_ok = _close(rev - cg, gp, (chosen["IS"][0].scale or 1.0))
            d["gross_profit_identity"] = {"ok": gp_ok, "Revenue-COGS": rev - cg, "GrossProfit": gp}
        # --- net income cross-statement
        ni = v("NetIncome")
        ni_ok: bool | None = None
        if ni is not None and is_rows and cf_rows:
            cf_ni = next((r for r in cf_rows if r.values and y in r.yearvals and re.match(
                r"^net (?:income|earnings|loss|\(loss\) income|income \(loss\)|earnings \(loss\))\b(?!.*per)", r.norm)), None)
            if cf_ni is not None:
                cf_sc = chosen["CF"][0].scale or 1.0
                cf_val = cf_ni.yearvals[y] * cf_sc
                is_sc = chosen["IS"][0].scale or 1.0
                family = [r.yearvals[y] * is_sc for r in is_rows if r.values and y in r.yearvals and re.match(
                    r"^(?:less:? )?net (?:income|earnings|loss|\(loss\) income|income \(loss\))\b", r.norm) and not re.search(
                    r"per (?:common )?share|applicable to|available to|before cumulative", r.norm)]
                family.append(ni)
                ni_ok = any(_close(cf_val, f, max(is_sc, cf_sc)) or _close(cf_val, abs(f), max(is_sc, cf_sc)) for f in family)
                # attributable + noncontrolling interest also reconciles to the cash-flow net income
                if not ni_ok and len(family) >= 3:
                    ni_ok = any(_close(cf_val, a + b, max(is_sc, cf_sc)) for a in family for b in family if a != b)
                d["net_income_cross_statement"] = {"ok": ni_ok, "cash_flow_row": cf_ni.label, "cash_flow_value": cf_val, "income_statement_candidates": family}

        # --- apply refusals
        failed: list[str] = []
        if bal is False:
            failed.append("balance_identity")
        if d.get("current_assets_le_total", {}).get("ok") is False:
            failed.append("current_assets_le_total")
        if d.get("current_liabilities_le_total", {}).get("ok") is False:
            failed.append("current_liabilities_le_total")
        if failed:
            for item in _BS_ITEMS:
                if item in vals:
                    vals.pop(item)
                miss[item] = "withheld: balance-sheet identity check failed (" + ", ".join(failed) + ")"
        if gp_ok is False:
            for item in _IS_GP_ITEMS:
                if item in vals:
                    vals.pop(item)
                miss[item] = "withheld: Revenue - COGS != GrossProfit identity failed"
        if ni_ok is False:
            if "NetIncome" in vals:
                vals.pop("NetIncome")
            miss["NetIncome"] = "withheld: income-statement net income does not match cash-flow statement net income"
        for item in list(vals):
            if item in miss:
                miss.pop(item)
        detail[str(y)] = d
        if y == fiscal_year:
            checks = {
                "balance_identity": (d.get("balance_identity", {}).get("ok") if "balance_identity" in d else None),
                "current_assets_le_total": d.get("current_assets_le_total", {}).get("ok"),
                "current_liabilities_le_total": d.get("current_liabilities_le_total", {}).get("ok"),
                "gross_profit_identity": d.get("gross_profit_identity", {}).get("ok"),
                "net_income_cross_statement": d.get("net_income_cross_statement", {}).get("ok"),
            }
        if y == fiscal_year - 1:
            result.setdefault("checks_prior", {
                "balance_identity": (d.get("balance_identity", {}).get("ok") if "balance_identity" in d else None),
                "current_assets_le_total": d.get("current_assets_le_total", {}).get("ok"),
                "net_income_cross_statement": d.get("net_income_cross_statement", {}).get("ok"),
            })
    if not checks:
        checks = {"balance_identity": None}
    result["checks"] = checks
    result["checks_detail"] = detail
    for yk, dd in detail.items():
        for name, c in dd.items():
            if c.get("ok") is False:
                result["warnings"].append(f"identity check failed for column year {yk}: {name}")
            elif name == "balance_identity" and c.get("ok") is None:
                result["warnings"].append(f"balance identity not testable for column year {yk}: {c.get('note')}")


# --------------------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------------------

def flatten_values(values: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    """``{canonical: FactValue}`` -> ``{canonical: float|None}`` for every canonical item (financial_metrics input)."""
    return {item: (values[item]["value"] if item in values else None) for item in CANONICAL_ITEMS}


def extract_statements_from_file(path: str | Path, fiscal_year: int, form: str = "10-K", **kw: Any) -> dict[str, Any]:
    """Read ``path`` (UTF-8, errors replaced) and call :func:`extract_statements`."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return extract_statements(text, fiscal_year, form, **kw)


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description="Extract canonical line items from a filing's own financial statements")
    ap.add_argument("path")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--form", default="10-K")
    ns = ap.parse_args(argv)
    res = extract_statements_from_file(ns.path, ns.year, ns.form)
    for label, key in (("FY", "values"), ("PRIOR", "prior_values")):
        print(f"== {label}")
        for item in CANONICAL_ITEMS:
            fv = res[key].get(item)
            print(f"  {item:20s} {fv['value']:>22,.0f}  <- {fv['tag'][:70]}" if fv else f"  {item:20s} MISSING ({res['missing' if key == 'values' else 'prior_missing'].get(item)})")
    print("checks:", json.dumps(res["checks"]))
    for w in res["warnings"]:
        print("warning:", w)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
