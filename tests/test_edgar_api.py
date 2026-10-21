"""Tests for tools.edgar_api.

Offline tests use httpx.MockTransport with SYNTHETIC payloads (structure only; no financial claims).
``@pytest.mark.network`` tests hit the real SEC and assert against what EDGAR returns.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tools import edgar_api as e


# --------------------------------------------------------------------------- offline
def test_pad_cik():
    assert e.pad_cik(320193) == "0000320193"
    assert e.pad_cik("CIK0000320193") == "0000320193"
    assert e.pad_cik("320193") == "0000320193"
    with pytest.raises(ValueError):
        e.pad_cik("abc")


def test_user_agent_header_and_placeholder(make_client, mock_sec, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    mock_sec.add("/x.json", {"ok": 1})
    c = make_client()
    c.get_json("https://data.sec.gov/x.json")
    assert mock_sec.requests[0].headers["user-agent"] == "forensic-filing-agent contact@example.com"


def test_user_agent_env_override(monkeypatch, tmp_path, mock_sec):
    monkeypatch.setenv("SEC_USER_AGENT", "TestApp test-contact@test.invalid")
    mock_sec.add("/x.json", {"ok": 1})
    c = e.EdgarClient(cache_dir=tmp_path, transport=httpx.MockTransport(mock_sec), sleep=lambda s: None)
    c.get_json("https://data.sec.gov/x.json")
    assert mock_sec.requests[0].headers["user-agent"] == "TestApp test-contact@test.invalid"


def test_cache_second_call_makes_no_http(make_client, mock_sec):
    mock_sec.add("/data.json", {"a": [1, 2]})
    c = make_client()
    assert c.get_json("https://data.sec.gov/data.json") == {"a": [1, 2]}
    assert c.get_json("https://data.sec.gov/data.json") == {"a": [1, 2]}
    assert c.http_calls == 1 and len(mock_sec.requests) == 1
    c.get_json("https://data.sec.gov/data.json", use_cache=False)
    assert c.http_calls == 2


def test_cache_ttl_expiry_and_immutable_archive(make_client, mock_sec):
    mock_sec.add("/submissions/CIK0000000001.json", {"v": 1})
    mock_sec.add("/Archives/edgar/data/1/doc.htm", "<html><body>hi</body></html>")
    c = make_client()
    sub_url = "https://data.sec.gov/submissions/CIK0000000001.json"
    doc_url = "https://www.sec.gov/Archives/edgar/data/1/doc.htm"
    c.get_json(sub_url)
    c.get_text(doc_url)
    assert c.http_calls == 2
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    for url in (sub_url, doc_url):
        _, meta = c._paths(url)
        m = json.loads(meta.read_text(encoding="utf-8"))
        m["fetched_at"] = old
        meta.write_text(json.dumps(m), encoding="utf-8")
    c.get_json(sub_url)      # 6h TTL -> refetched
    c.get_text(doc_url)      # immutable archive document -> still cached
    assert c.http_calls == 3


def test_404_raises_and_is_negative_cached(make_client, mock_sec):
    c = make_client()
    with pytest.raises(e.EdgarNotFound):
        c.get_json("https://data.sec.gov/nothing.json")
    with pytest.raises(e.EdgarNotFound):
        c.get_json("https://data.sec.gov/nothing.json")
    assert c.http_calls == 1


def test_get_companyfacts_404_returns_empty_dict(make_client):
    make_client()
    assert e.get_companyfacts("0001024401") == {}


def test_retry_429_503_then_success(make_client, mock_sec):
    seq = iter([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(503), httpx.Response(200, json={"ok": True})])
    mock_sec.add("/flaky.json", lambda req: next(seq))
    c = make_client()
    assert c.get_json("https://data.sec.gov/flaky.json") == {"ok": True}
    assert c.http_calls == 3
    sleeps = make_client.sleeps
    assert any(abs(s - 3.0) < 1e-6 for s in sleeps), sleeps  # Retry-After honoured
    assert max(sleeps) < 61


def test_retry_exhaustion_raises_after_six_tries(make_client, mock_sec):
    mock_sec.add("/down.json", lambda req: httpx.Response(503))
    c = make_client()
    with pytest.raises(e.EdgarError):
        c.get_json("https://data.sec.gov/down.json")
    assert c.http_calls == e.MAX_TRIES == 6


def test_403_is_not_retried(make_client, mock_sec):
    mock_sec.add("/forbidden", lambda req: httpx.Response(403))
    c = make_client()
    with pytest.raises(e.EdgarError, match="SEC_USER_AGENT"):
        c.get_json("https://data.sec.gov/forbidden")
    assert c.http_calls == 1


def test_transport_error_retried(make_client, mock_sec):
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": 1})

    mock_sec.add("/conn.json", handler)
    c = make_client()
    assert c.get_json("https://data.sec.gov/conn.json") == {"ok": 1}
    assert state["n"] == 3


def test_rate_limiter_caps_throughput_single_thread(make_client, mock_sec):
    mock_sec.add("/r/", {"ok": 1})
    c = make_client(max_rps=40.0, sleep=time.sleep)
    n = 21
    t0 = time.monotonic()
    for i in range(n):
        c.get_json(f"https://data.sec.gov/r/{i}.json")
    elapsed = time.monotonic() - t0
    assert elapsed >= (n - 1) / 40.0 * 0.95, elapsed


def test_rate_limiter_is_global_across_threads(make_client, mock_sec):
    mock_sec.add("/t/", {"ok": 1})
    c = make_client(max_rps=40.0, sleep=time.sleep)
    stamps: list[float] = []
    lock = threading.Lock()

    def work(k: int) -> None:
        for i in range(8):
            c.get_json(f"https://data.sec.gov/t/{k}-{i}.json")
            with lock:
                stamps.append(time.monotonic())

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    t0 = time.monotonic()
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.monotonic() - t0
    assert len(stamps) == 32
    assert elapsed >= 31 / 40.0 * 0.95, elapsed


def test_default_limit_is_at_most_8_rps():
    assert e.MAX_REQUESTS_PER_SECOND <= 8.0


def _submissions_payload() -> dict:
    cols = {
        "accessionNumber": ["0000000001-21-000003", "0000000001-20-000002", "0000000001-19-000001", "0000000001-21-000009"],
        "form": ["10-K", "10-K", "10-K/A", "DEF 14A"],
        "filingDate": ["2021-03-01", "2020-03-02", "2019-06-01", "2021-04-01"],
        "reportDate": ["2020-12-31", "2019-12-31", "2018-12-31", ""],
        "primaryDocument": ["a10k.htm", "b10k.htm", "c10ka.htm", "proxy.htm"],
    }
    older = {
        "accessionNumber": ["0000000001-18-000001", "0000000001-17-000001"],
        "form": ["10-K", "10-K405"],
        "filingDate": ["2018-03-01", "2017-02-20"],
        "reportDate": ["2018-02-03", "2016-12-31"],
        "primaryDocument": ["d.htm", ""],
    }
    return {"name": "Synthetic Corp", "sic": "1234", "sicDescription": "Synthetic", "tickers": ["SYN"], "exchanges": ["Nasdaq"],
            "fiscalYearEnd": "1231", "formerNames": [],
            "filings": {"recent": cols, "files": [{"name": "CIK0000000001-submissions-001.json"}]}}, older


def test_list_annual_filings_merge_pages_asof_and_fiscal_year(make_client, mock_sec):
    main, older = _submissions_payload()
    mock_sec.add("CIK0000000001-submissions-001.json", older)
    mock_sec.add("CIK0000000001.json", main)
    make_client()
    allf = e.list_annual_filings("1")
    assert [f["accession"] for f in allf] == ["0000000001-21-000003", "0000000001-20-000002",
                                              "0000000001-18-000001", "0000000001-17-000001"]  # /A excluded, newest first
    by_acc = {f["accession"]: f for f in allf}
    assert by_acc["0000000001-18-000001"]["fiscal_year"] == 2017          # period ending 2018-02-03 -> prior year (D12)
    assert by_acc["0000000001-21-000003"]["fiscal_year"] == 2020
    assert by_acc["0000000001-21-000003"]["document_url"].endswith("/000000000121000003/a10k.htm")
    assert by_acc["0000000001-17-000001"]["document_url"].endswith("/0000000001-17-000001.txt")  # no primary doc
    asof = e.list_annual_filings("1", as_of="2020-12-31")
    assert [f["fiscal_year"] for f in asof] == [2019, 2017, 2016]
    proxies = e.list_filings("1", ["DEF 14A"])
    assert len(proxies) == 1 and proxies[0]["fiscal_year"] is None


def test_resolve_company_ticker_and_delisted(make_client, mock_sec):
    main, older = _submissions_payload()
    mock_sec.add("company_tickers.json", {"0": {"cik_str": 1, "ticker": "SYN", "title": "Synthetic Corp"},
                                          "1": {"cik_str": 2, "ticker": "BRK-B", "title": "Other"}})
    mock_sec.add("CIK0000000001-submissions-001.json", older)
    mock_sec.add("CIK0000000001.json", main)
    make_client()
    r = e.resolve_company("syn")
    assert r["cik"] == "0000000001" and r["name"] == "Synthetic Corp" and r["sic"] == "1234" and r["ticker"] == "SYN"
    assert e.resolve_company("0000000001")["ticker"] == "SYN"
    assert e.resolve_company("ENRNQ", cik=1)["ticker"] == "ENRNQ"
    with pytest.raises(e.EdgarNotFound):
        e.resolve_company("ENRNQ")


def test_html_to_text_tables_and_hidden_header():
    html = """<html><head><title>x</title><style>p{}</style></head><body>
    <ix:header><ix:hidden>HIDDEN STUFF</ix:hidden></ix:header>
    <div>Item 7. <span>Management's</span> Discussion</div>
    <p>Net sales   increased&nbsp;5%.</p>
    <table><tr><td>Net income</td><td>$</td><td>1,234</td><td></td><td>$</td><td>(56</td><td>)</td></tr>
    <tr><td>Margin</td><td>12.5</td><td>%</td></tr></table><p>After table</p></body></html>"""
    t = e.html_to_text(html)
    assert "HIDDEN" not in t and "p{}" not in t
    assert "Item 7. Management's Discussion" in t
    assert "Net sales increased 5%." in t
    assert "Net income | $1,234 | $(56)" in t
    assert "Margin | 12.5%" in t
    assert t.index("Margin") < t.index("After table")


def test_fetch_filing_text_html_cached_and_legacy_txt(make_client, mock_sec):
    mock_sec.add("/Archives/edgar/data/1/000000000121000003/a10k.htm", "<html><body><p>Hello world</p></body></html>")
    mock_sec.add("/Archives/edgar/data/1/old.txt", "FORM 10-K\n<PAGE> 1\nBody text\n<PAGE>\nMore")
    c = make_client()
    f = {"accession": "0000000001-21-000003", "form": "10-K", "document_url":
         "https://www.sec.gov/Archives/edgar/data/1/000000000121000003/a10k.htm", "cik": "0000000001"}
    assert "Hello world" in e.fetch_filing_text(f)
    n = c.http_calls
    assert "Hello world" in e.fetch_filing_text(f)
    assert c.http_calls == n
    assert e.fetch_filing_text(f, max_chars=5) == "Hello"
    old = e.fetch_filing_text("https://www.sec.gov/Archives/edgar/data/1/old.txt")
    assert "<PAGE>" not in old and "Body text" in old and "More" in old


def test_fetch_filing_text_falls_back_to_submission_txt(make_client, mock_sec):
    sub = ("<SEC-DOCUMENT>x\n<DOCUMENT>\n<TYPE>EX-13\n<TEXT>\nexhibit\n</TEXT>\n</DOCUMENT>\n"
           "<DOCUMENT>\n<TYPE>10-K\n<TEXT>\nANNUAL REPORT BODY\n<PAGE>\nPage two\n</TEXT>\n</DOCUMENT>")
    mock_sec.add("/000000000199000007/0000000001-99-000007.txt", sub)
    make_client()
    f = {"accession": "0000000001-99-000007", "form": "10-K", "cik": "0000000001",
         "document_url": "https://www.sec.gov/Archives/edgar/data/1/000000000199000007/missing.htm"}
    txt = e.fetch_filing_text(f)
    assert "ANNUAL REPORT BODY" in txt and "Page two" in txt and "exhibit" not in txt


def test_find_company_by_sic_parses_atom(make_client, mock_sec):
    atom = """<feed><entry><content><cik>0000320193</cik><conformed-name>APPLE INC</conformed-name>
    <state-location>CA</state-location></content></entry>
    <entry><content><cik>0000789019</cik><conformed-name>MICROSOFT &amp; CO</conformed-name></content></entry></feed>"""
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, text=atom if calls["n"] == 1 else "<feed></feed>")

    mock_sec.add("browse-edgar", handler)
    make_client()
    out = e.find_company_by_sic(3571, limit=10)
    assert [o["cik"] for o in out] == ["0000320193", "0000789019"]
    assert out[1]["name"] == "MICROSOFT & CO"


# --------------------------------------------------------------------------- live SEC
@pytest.mark.network
def test_live_resolve_aapl_and_filings():
    r = e.resolve_company("AAPL")
    assert r["cik"] == "0000320193" and r["name"].lower().startswith("apple") and r["sic"] == "3571"
    fs = e.list_annual_filings(r["cik"])
    years = {f["fiscal_year"]: f for f in fs}
    for y in range(2016, 2023):
        assert y in years and years[y]["form"] == "10-K"
    assert years[2020]["report_date"] == "2020-09-26"
    assert e.list_annual_filings(r["cik"], as_of="2019-12-31")[0]["fiscal_year"] == 2019


@pytest.mark.network
def test_live_companyfacts_cached_second_call_no_http():
    c = e.get_client()
    cf = e.get_companyfacts("0000320193")
    assert cf["entityName"].lower().startswith("apple") and "us-gaap" in cf["facts"]
    before = c.http_calls
    cf2 = e.get_companyfacts("0000320193")
    assert c.http_calls == before and cf2["cik"] == cf["cik"]


@pytest.mark.network
def test_live_pre_xbrl_enron_empty_and_readable_text():
    assert e.get_companyfacts("0001024401") == {}
    fs = e.list_annual_filings("0001024401", as_of="2001-12-31")
    fy2000 = [f for f in fs if f["fiscal_year"] == 2000]
    assert fy2000, "Enron FY2000 10-K not found"
    txt = e.fetch_filing_text(fy2000[0])
    assert len(txt) > 100_000
    assert "ENRON CORP" in txt.upper() and "FISCAL YEAR ENDED DECEMBER 31, 2000" in txt.upper()
    assert "<PAGE>" not in txt


@pytest.mark.network
def test_live_aapl_html_text_has_financial_tables():
    fs = {f["fiscal_year"]: f for f in e.list_annual_filings("0000320193")}
    txt = e.fetch_filing_text(fs[2020])
    assert "Total net sales | $274,515" in txt
    assert "ix:" not in txt.lower()
