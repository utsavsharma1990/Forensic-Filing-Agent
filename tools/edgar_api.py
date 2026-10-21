"""SEC EDGAR API wrappers: rate-limited, cached, retrying HTTP client plus filing helpers.

Etiquette implemented here
* ``User-Agent`` comes from ``SEC_USER_AGENT`` (falls back to the spec placeholder and warns once).
* A single process-wide limiter keeps traffic at <= 8 requests/second across all threads.
* HTTP 429/5xx and connection errors are retried with exponential backoff (``Retry-After`` honoured), max 6 tries.
* Everything is cached on disk under ``.cache/edgar/``: submissions/indexes 6h, companyfacts 24h,
  immutable archive documents forever, 404s negative-cached for 24h so repeated lookups make no HTTP.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import ssl
import threading
import time
from datetime import timedelta, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict, Union

import httpx

from tools import common
from tools.common import fiscal_year_of, get_logger

log = get_logger("edgar_api")

PLACEHOLDER_UA = "forensic-filing-agent contact@example.com"
ANNUAL_FORMS: tuple[str, ...] = ("10-K", "10-K405", "10-KSB", "20-F", "40-F")
MAX_REQUESTS_PER_SECOND = 8.0
MAX_TRIES = 6

TTL_SUBMISSIONS = timedelta(hours=6)
TTL_COMPANYFACTS = timedelta(hours=24)
TTL_NEGATIVE = timedelta(hours=24)
_FOREVER = None


class EdgarError(RuntimeError):
    """Any non-recoverable EDGAR failure (HTTP error after retries, bad payload)."""


class EdgarNotFound(EdgarError):
    """HTTP 404 (or a lookup that matches nothing)."""


class Filing(TypedDict, total=False):
    """One SEC filing as returned by :func:`list_annual_filings` / :func:`list_filings`."""

    accession: str          # dashed, e.g. 0000320193-20-000096
    form: str
    filing_date: str        # ISO
    report_date: str        # ISO period of report ("" if unknown)
    fiscal_year: Optional[int]
    primary_document: str
    index_url: str
    document_url: str
    cik: str


def pad_cik(cik: Union[str, int]) -> str:
    """Zero-pad a CIK to 10 digits (accepts ints, digit strings, or ``CIK0000320193``)."""
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError(f"not a CIK: {cik!r}")
    return digits.zfill(10)


def _ssl_context() -> Union[ssl.SSLContext, bool]:
    """TLS context using the OS trust store (needed behind corporate TLS-inspecting proxies on Windows).

    Falls back to httpx defaults (certifi) if ``truststore`` is unavailable. ``SSL_CERT_FILE`` /
    ``REQUESTS_CA_BUNDLE`` are honoured when set. Verification is never disabled.
    """
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and Path(bundle).exists():
        return ssl.create_default_context(cafile=bundle)
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True


def _user_agent() -> str:
    common.load_env()
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    return ua or PLACEHOLDER_UA


class EdgarClient:
    """Thread-safe SEC HTTP client with global rate limiting, retries and an on-disk cache.

    Parameters are mainly for tests: ``transport`` (an ``httpx`` transport, e.g. ``MockTransport``),
    ``cache_dir`` and ``sleep``.
    """

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        max_rps: float = MAX_REQUESTS_PER_SECOND,
        user_agent: Optional[str] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else common.CACHE_DIR / "edgar"
        self.user_agent = user_agent or _user_agent()
        if "example.com" in self.user_agent or "your@email.com" in self.user_agent:
            log.warning("SEC_USER_AGENT is unset or a placeholder (%r); set it to 'AppName your-real@email' per SEC policy.",
                        self.user_agent)
        self._sleep = sleep
        self._min_interval = 1.0 / max_rps
        self._rl_lock = threading.Lock()
        self._next_slot = 0.0
        self._fs_lock = threading.Lock()
        self.http_calls = 0  # real network round trips (retries included); used by tests
        kwargs: dict[str, Any] = {}
        if transport is not None:
            kwargs["transport"] = transport
        else:
            kwargs["verify"] = _ssl_context()
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
            **kwargs,
        )

    # ------------------------------------------------------------------ rate limiting
    def _throttle(self) -> None:
        """Block until the next global request slot (spacing >= 1/max_rps seconds)."""
        with self._rl_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._min_interval
        wait = slot - now
        if wait > 0:
            self._sleep(wait)

    # ------------------------------------------------------------------ caching
    @staticmethod
    def _ttl_for(url: str) -> Optional[timedelta]:
        u = url.lower()
        if "/api/xbrl/companyfacts/" in u or "company_tickers" in u:
            return TTL_COMPANYFACTS
        if "data.sec.gov/submissions/" in u or "cgi-bin" in u or "efts.sec.gov" in u:
            return TTL_SUBMISSIONS
        if "/archives/edgar/" in u:
            if u.endswith("/") or u.endswith("index.json") or u.endswith("-index.htm") or u.endswith("-index.html"):
                return TTL_SUBMISSIONS
            return _FOREVER
        return TTL_SUBMISSIONS

    def _paths(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.dat", self.cache_dir / f"{h}.meta.json"

    def _cache_get(self, url: str, ttl: Optional[timedelta], use_ttl: bool = True) -> Optional[Union[bytes, EdgarNotFound]]:
        dat, meta = self._paths(url)
        try:
            with self._fs_lock:
                if not meta.exists():
                    return None
                m = json.loads(meta.read_text(encoding="utf-8"))
                fetched = datetime.fromisoformat(m["fetched_at"])
                age = datetime.now(timezone.utc) - fetched
                if m.get("status") == 404:
                    return EdgarNotFound(f"404 (cached): {url}") if age <= TTL_NEGATIVE else None
                if use_ttl and ttl is not None and age > ttl:
                    return None
                return dat.read_bytes() if dat.exists() else None
        except Exception:
            return None

    def _cache_put(self, url: str, content: Optional[bytes], status: int) -> None:
        dat, meta = self._paths(url)
        try:
            with self._fs_lock:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                if content is not None:
                    tmp = dat.with_suffix(".tmp")
                    tmp.write_bytes(content)
                    tmp.replace(dat)
                elif dat.exists():
                    dat.unlink()
                meta.write_text(json.dumps({"url": url, "status": status,
                                            "fetched_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - cache failure must not break fetching
            log.debug("cache write failed for %s: %s", url, exc)

    # ------------------------------------------------------------------ HTTP
    def get_bytes(self, url: str, *, ttl: Optional[timedelta] = None, use_cache: bool = True) -> bytes:
        """GET ``url`` with cache, rate limit and retry. Raises :class:`EdgarNotFound` on 404."""
        eff_ttl = ttl if ttl is not None else self._ttl_for(url)
        if use_cache:
            cached = self._cache_get(url, eff_ttl)
            if isinstance(cached, EdgarNotFound):
                raise cached
            if cached is not None:
                return cached
        backoff = 1.0
        last_err = "no attempt"
        for attempt in range(1, MAX_TRIES + 1):
            self._throttle()
            self.http_calls += 1
            try:
                resp = self._client.get(url)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                    raise EdgarError(f"TLS certificate verification failed for {url}: {exc}. "
                                     "Install 'truststore' or set SSL_CERT_FILE to your CA bundle.") from exc
                last_err = f"{type(exc).__name__}: {exc}"
                log.warning("EDGAR transport error (try %d/%d) %s", attempt, MAX_TRIES, last_err)
                self._sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            code = resp.status_code
            if code == 200:
                if use_cache:
                    self._cache_put(url, resp.content, 200)
                return resp.content
            if code == 404:
                if use_cache:
                    self._cache_put(url, None, 404)
                raise EdgarNotFound(f"404 Not Found: {url}")
            if code == 429 or code >= 500:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else backoff
                except ValueError:
                    delay = backoff
                last_err = f"HTTP {code}"
                log.warning("EDGAR HTTP %d (try %d/%d); sleeping %.1fs", code, attempt, MAX_TRIES, delay)
                self._sleep(min(max(delay, backoff), 60.0))
                backoff = min(backoff * 2, 30.0)
                continue
            hint = " (check SEC_USER_AGENT)" if code == 403 else ""
            raise EdgarError(f"HTTP {code} for {url}{hint}")
        raise EdgarError(f"giving up after {MAX_TRIES} tries ({last_err}): {url}")

    def get_text(self, url: str, **kw: Any) -> str:
        """GET as text (UTF-8, falling back to latin-1 for legacy filings)."""
        return _decode(self.get_bytes(url, **kw))

    def get_json(self, url: str, **kw: Any) -> Any:
        """GET and parse JSON."""
        raw = self.get_bytes(url, **kw)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise EdgarError(f"invalid JSON from {url}: {exc}") from exc

    def close(self) -> None:
        self._client.close()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


_client_lock = threading.Lock()
_client: Optional[EdgarClient] = None


def get_client() -> EdgarClient:
    """Process-wide singleton :class:`EdgarClient`."""
    global _client
    with _client_lock:
        if _client is None:
            _client = EdgarClient()
        return _client


def set_client(client: Optional[EdgarClient]) -> None:
    """Replace the singleton (tests). ``None`` resets so the next ``get_client`` builds a fresh one."""
    global _client
    with _client_lock:
        _client = client


# ---------------------------------------------------------------------- company resolution
def _tickers_table() -> dict[str, dict]:
    data = get_client().get_json("https://www.sec.gov/files/company_tickers.json")
    out: dict[str, dict] = {}
    rows = data.values() if isinstance(data, dict) else data
    for row in rows:
        t = str(row.get("ticker", "")).upper()
        if t and t not in out:
            out[t] = row
    return out


def _norm_ticker(t: str) -> str:
    return t.strip().upper().replace(".", "-").replace("/", "-")


def resolve_company(ticker_or_cik: Union[str, int], cik: Optional[Union[str, int]] = None) -> dict:
    """Resolve a ticker (or CIK) to company identity.

    Returns ``{"ticker","cik","name","sic","sic_description","fiscal_year_end","exchanges","former_names"}``.
    Delisted tickers (e.g. ENRNQ) are absent from ``company_tickers.json``; pass ``cik=`` explicitly.
    Raises :class:`EdgarNotFound` if nothing matches.
    """
    ident = str(ticker_or_cik).strip()
    resolved_cik: Optional[str] = None
    ticker = ""
    if cik is not None and str(cik).strip():
        resolved_cik = pad_cik(cik)
        ticker = _norm_ticker(ident) if not ident.isdigit() else ""
    elif ident.isdigit() or ident.upper().startswith("CIK"):
        resolved_cik = pad_cik(ident)
    else:
        ticker = _norm_ticker(ident)
        row = _tickers_table().get(ticker)
        if row is None:
            raise EdgarNotFound(
                f"ticker {ident!r} not found in SEC company_tickers.json (delisted/renamed?). Pass cik= explicitly.")
        resolved_cik = pad_cik(row["cik_str"])
    sub = get_submissions(resolved_cik)
    tickers = [str(t).upper() for t in sub.get("tickers") or []]
    if not ticker:
        ticker = tickers[0] if tickers else ""
    return {
        "ticker": ticker,
        "cik": resolved_cik,
        "name": sub.get("name") or "",
        "sic": str(sub.get("sic") or ""),
        "sic_description": sub.get("sicDescription") or "",
        "fiscal_year_end": sub.get("fiscalYearEnd") or "",
        "exchanges": list(sub.get("exchanges") or []),
        "former_names": list(sub.get("formerNames") or []),
    }


def get_submissions(cik: Union[str, int]) -> dict:
    """Company submissions JSON with the older paginated ``filings.files`` pages merged into ``filings.recent``."""
    c = get_client()
    padded = pad_cik(cik)
    sub = c.get_json(f"https://data.sec.gov/submissions/CIK{padded}.json")
    recent = sub.setdefault("filings", {}).setdefault("recent", {})
    for page in sub["filings"].get("files") or []:
        name = page.get("name")
        if not name:
            continue
        try:
            extra = c.get_json(f"https://data.sec.gov/submissions/{name}")
        except EdgarError as exc:
            log.warning("could not fetch submissions page %s: %s", name, exc)
            continue
        for key, vals in extra.items():
            if isinstance(vals, list):
                recent.setdefault(key, [])
                recent[key] = list(recent[key]) + vals
    return sub


def _filing_rows(cik: str, as_of: Optional[str]) -> list[Filing]:
    sub = get_submissions(cik)
    recent = sub.get("filings", {}).get("recent", {})
    n = len(recent.get("accessionNumber", []))
    rows: list[Filing] = []
    cik_int = str(int(cik))

    def col(name: str, i: int) -> str:
        arr = recent.get(name) or []
        return str(arr[i]) if i < len(arr) and arr[i] is not None else ""

    for i in range(n):
        acc = col("accessionNumber", i)
        nodash = acc.replace("-", "")
        prim = col("primaryDocument", i)
        base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}"
        fdate = col("filingDate", i)
        if as_of and fdate and fdate > as_of:
            continue
        rows.append({
            "accession": acc,
            "form": col("form", i),
            "filing_date": fdate,
            "report_date": col("reportDate", i),
            "fiscal_year": None,
            "primary_document": prim,
            "index_url": f"{base}/{acc}-index.htm",
            "document_url": f"{base}/{prim}" if prim else f"{base}/{acc}.txt",
            "cik": cik,
        })
    rows.sort(key=lambda r: (r["filing_date"], r["accession"]), reverse=True)
    return rows


def list_filings(cik: Union[str, int], forms: Union[tuple, list, set, str], as_of: Optional[str] = None) -> list[Filing]:
    """Filings of the given form types filed on or before ``as_of`` (ISO), newest first.

    ``fiscal_year`` is only populated for annual forms (see :func:`tools.common.fiscal_year_of`).
    """
    wanted = {forms} if isinstance(forms, str) else set(forms)
    out = []
    for f in _filing_rows(pad_cik(cik), as_of):
        if f["form"] in wanted:
            if f["form"] in ANNUAL_FORMS:
                f["fiscal_year"] = fiscal_year_of(f["report_date"]) if f["report_date"] else None
            out.append(f)
    return out


def list_annual_filings(cik: Union[str, int], as_of: Optional[str] = None,
                        forms: Union[tuple, list, set] = ANNUAL_FORMS) -> list[Filing]:
    """Annual reports (10-K, 10-K405, 10-KSB, 20-F, 40-F; amendments excluded) filed <= ``as_of``, newest first."""
    return list_filings(cik, forms, as_of)


def get_companyfacts(cik: Union[str, int]) -> dict:
    """Raw XBRL companyfacts JSON, or ``{}`` for 404 (pre-XBRL / non-filer). Never raises for 404.

    Other failures (network exhausted) raise :class:`EdgarError`.
    """
    try:
        return get_client().get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{pad_cik(cik)}.json")
    except EdgarNotFound:
        return {}


# ---------------------------------------------------------------------- filing text
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
               "article", "table", "hr", "pre", "blockquote", "center", "dd", "dt", "dl", "body", "title"}
_CACHE_TEXT_VERSION = "v1"


def _clean_cells(cells: list[str]) -> list[str]:
    """Merge currency/percent/paren fragments produced by EDGAR table markup (``$ | 1,234 | )`` -> ``$1,234 )``)."""
    out: list[str] = []
    pending_prefix = ""
    for c in cells:
        c = c.strip()
        if not c:
            continue
        if c in {"$", "US$", "RMB", "¥", "€", "£", "(", "$("}:
            pending_prefix += c
            continue
        if c in {")", "%", "%)", ")%", "pts"} and out:
            out[-1] += c
            continue
        out.append(pending_prefix + c)
        pending_prefix = ""
    return out


def html_to_text(html: str) -> str:
    """Convert a filing's HTML / inline-XBRL to clean text.

    Tables are rendered one row per line with `` | `` between non-empty cells; hidden iXBRL header
    blocks, scripts and styles are dropped; blank lines are collapsed.
    """
    import warnings

    from bs4 import BeautifulSoup, NavigableString, XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for tag in soup.find_all(re.compile(r"^ix:header$", re.I)):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        tag.decompose()
    for table in soup.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True).replace("\xa0", " ")) for td in tr.find_all(["td", "th"])]
            cells = _clean_cells(cells)
            if cells:
                lines.append(" | ".join(cells))
        table.replace_with(NavigableString("\n" + "\n".join(lines) + "\n"))
    for tag in soup.find_all(list(_BLOCK_TAGS)):
        tag.insert_before(NavigableString("\n"))
        tag.insert_after(NavigableString("\n"))
    text = soup.get_text("")
    text = text.replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln:
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank == 1 and out:
                out.append("")
    return "\n".join(out).strip() + "\n"


def _looks_html(s: str) -> bool:
    head = s[:3000].lower()
    return "<html" in head or "<!doctype html" in head or "<body" in head or "<?xml" in head or "<ix:" in head or "<div" in head


def _text_from_submission_txt(raw: str, form: str = "") -> str:
    """Extract the primary annual-report document from a complete-submission ``.txt`` and render it as text."""
    docs = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, flags=re.S | re.I)
    chosen = None
    prefix = (form or "10-K")[:4].upper()
    for d in docs:
        m = re.search(r"<TYPE>\s*([^\s<]+)", d, re.I)
        if m and m.group(1).upper().startswith(prefix[:3]) and not m.group(1).upper().startswith("EX"):
            chosen = d
            break
    if chosen is None:
        chosen = docs[0] if docs else raw
    m = re.search(r"<TEXT>(.*)", chosen, re.S | re.I)
    body = m.group(1) if m else chosen
    body = re.sub(r"</TEXT>\s*$", "", body, flags=re.I)
    if _looks_html(body):
        return html_to_text(body)
    return _plain_text(body)


def _plain_text(raw: str) -> str:
    """Normalise a legacy plain-text filing: ``<PAGE>`` markers become blank-line page breaks, tags removed."""
    s = raw.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"^\s*<PAGE>.*$", "\n", s, flags=re.M | re.I)
    s = re.sub(r"</?(?:PRE|TEXT|CAPTION|TABLE|S|C|FN)>", "", s, flags=re.I)
    s = re.sub(r"</?(?:PRE|TEXT|CAPTION|TABLE|S|C|FN)\b[^>]*>", "", s, flags=re.I)
    return _html.unescape(s)


def fetch_filing_html(filing: Union[Filing, dict, str]) -> str:
    """Raw HTML (or raw text for legacy filings) of the filing's primary document."""
    url = filing if isinstance(filing, str) else filing["document_url"]
    c = get_client()
    try:
        return c.get_text(url)
    except EdgarNotFound:
        if isinstance(filing, str):
            raise
        return c.get_text(_submission_txt_url(filing))


def _submission_txt_url(filing: dict) -> str:
    acc = filing["accession"]
    cik = str(int(filing.get("cik") or re.search(r"/data/(\d+)/", filing["document_url"]).group(1)))
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}.txt"


def fetch_filing_text(filing_or_url: Union[Filing, dict, str], max_chars: Optional[int] = None) -> str:
    """Readable text of an annual report.

    HTML / inline XBRL -> clean text (tables one row per line, cells joined by `` | ``). Legacy ``.txt``
    filings are returned as-is (``<PAGE>`` markers handled). If the primary document 404s (very old
    submissions) falls back to the complete submission ``{accession}.txt``. Processed text is cached.
    """
    is_url = isinstance(filing_or_url, str)
    url = filing_or_url if is_url else filing_or_url["document_url"]
    form = "" if is_url else str(filing_or_url.get("form", ""))
    client = get_client()
    tpath = client.cache_dir / "text" / (hashlib.sha256(f"{_CACHE_TEXT_VERSION}|{url}".encode()).hexdigest() + ".txt")
    text: Optional[str] = None
    try:
        if tpath.exists():
            text = tpath.read_text(encoding="utf-8")
    except OSError:
        text = None
    if text is None:
        used_submission_txt = False
        try:
            raw = client.get_text(url)
        except EdgarNotFound:
            if is_url:
                raise
            raw = client.get_text(_submission_txt_url(filing_or_url))  # type: ignore[arg-type]
            used_submission_txt = True
        if used_submission_txt or "<DOCUMENT>" in raw[:5000].upper():
            text = _text_from_submission_txt(raw, form)
        elif url.lower().endswith((".htm", ".html", ".xhtml")) or _looks_html(raw):
            text = html_to_text(raw)
        else:
            text = _plain_text(raw)
        try:
            tpath.parent.mkdir(parents=True, exist_ok=True)
            tpath.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return text[:max_chars] if max_chars else text


# ---------------------------------------------------------------------- peer discovery
def find_company_by_sic(sic: Union[str, int], limit: int = 100) -> list[dict]:
    """Companies listed under an SIC code via the browse-edgar atom feed: ``[{"cik","name","state"}]``.

    Best effort: the feed is paginated by 100 and may return fewer rows; returns ``[]`` on failure.
    """
    out: list[dict] = []
    seen: set[str] = set()
    start = 0
    c = get_client()
    while len(out) < limit and start < 1000:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&SIC={str(sic).strip()}&type=10-K&owner=include&count=100&start={start}&output=atom")
        try:
            body = c.get_text(url)
        except EdgarError as exc:
            log.warning("find_company_by_sic(%s) failed: %s", sic, exc)
            break
        found = 0
        for m in re.finditer(r"<(?:content|entry)[^>]*>.*?</(?:content|entry)>", body, flags=re.S):
            blk = m.group(0)
            cik_m = re.search(r"<cik>\s*0*(\d+)\s*</cik>", blk, re.I) or re.search(r"CIK=0*(\d+)", blk, re.I)
            name_m = re.search(r"<conformed-name>(.*?)</conformed-name>", blk, re.I | re.S) or re.search(r"<title>(.*?)</title>", blk, re.S)
            if not cik_m:
                continue
            cik = pad_cik(cik_m.group(1))
            if cik in seen:
                continue
            seen.add(cik)
            st = re.search(r"<state-location>(.*?)</state-location>", blk, re.I | re.S)
            out.append({"cik": cik, "name": _html.unescape(name_m.group(1)).strip() if name_m else "",
                        "state": st.group(1).strip() if st else ""})
            found += 1
        if not found:
            # HTML fallback format: rows with CIK links
            for m in re.finditer(r'CIK=0*(\d+)[^>]*>[^<]*</a></td>\s*<td[^>]*>([^<]*)</td>', body, flags=re.S):
                cik = pad_cik(m.group(1))
                if cik not in seen:
                    seen.add(cik)
                    out.append({"cik": cik, "name": _html.unescape(m.group(2)).strip(), "state": ""})
                    found += 1
        if not found:
            break
        start += 100
    return out[:limit]
