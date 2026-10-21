"""Tests for tools/text_parser.py.

Two layers:

* Synthetic unit tests (always run, no network): TOC trap, negation / boilerplate, signature
  layouts, fee tables, name normalisation, robustness.
* Real-filing tests: filings are downloaded from SEC EDGAR (User-Agent from ``SEC_USER_AGENT``
  or the spec placeholder; <= 8 req/s; retries on 429/503; cached under ``.cache/text``).
  If a filing is neither cached nor downloadable (offline) its tests are SKIPPED, never faked.
  Ground truth (auditor, CEO, CFO, fee amounts ...) was established by reading the real filing
  text, not from memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import text_parser as tp  # noqa: E402

CACHE = ROOT / ".cache" / "text"
SEC_UA = os.environ.get("SEC_USER_AGENT") or "forensic-filing-agent contact@example.com"
_last_request = [0.0]


# --------------------------------------------------------------------------------------
# Local cached downloader (edgar_api is built concurrently and deliberately not imported)
# --------------------------------------------------------------------------------------


def _http_get(url: str) -> bytes:
    """GET with <=8 req/s, 429/503 backoff and on-disk cache. Raises on failure."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".bin")
    if path.exists():
        return path.read_bytes()
    import requests  # local import: only needed when the cache is cold

    try:  # corporate TLS inspection: use the OS trust store when available
        import truststore  # type: ignore

        truststore.inject_into_ssl()
    except Exception:
        pass
    last_exc: Optional[Exception] = None
    for attempt in range(6):
        wait = 0.13 - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.time()
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=60)
        except Exception as exc:  # network error
            last_exc = exc
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        path.write_bytes(r.content)
        return r.content
    raise RuntimeError(f"download failed for {url}: {last_exc}")


def _archive_url(cik: int, accession: str, doc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}"


# name -> (cik, accession, primary doc, form)
FILINGS = {
    "aapl19": (320193, "0000320193-19-000119", "a10-k20199282019.htm", "10-K"),
    "aapl20": (320193, "0000320193-20-000096", "aapl-20200926.htm", "10-K"),
    "enron00": (1024401, "0001024401-01-500010", "ene10-k.txt", "10-K"),
    "wcom01": (723527, "0001005477-02-001226", "d02-36461.txt", "10-K405"),
    "lk19": (1767582, "0001104659-21-087180", "a20-36633_120f.htm", "20-F"),
    "nkla20": (1731289, "0001731289-21-000006", "nkla-20201231.htm", "10-K"),
    "nkla20a": (1731289, "0001731289-21-000058", "nkla-20201231.htm", "10-K/A"),
    "bbby22": (886158, "0000886158-23-000059", "bbby-20230225.htm", "10-K"),
    "khc18": (1637459, "0001637459-19-000049", "form10-k2018.htm", "10-K"),
    "smci24": (1375365, "0001375365-25-000004", "smci-20240630.htm", "10-K"),
}
PROXIES = {
    "aapl_proxy21": (320193, "0001193125-21-001987", "d767770ddef14a.htm"),
    "enron_proxy01": (1024401, "0000950129-01-001669", "h84664ddef14a.txt"),
}
_TEXT_MEMO: dict[str, str] = {}


def _load(name: str) -> str:
    """Text of a real filing/proxy (html -> text via tp.html_to_text); skip if unavailable."""
    if name in _TEXT_MEMO:
        return _TEXT_MEMO[name]
    if name in FILINGS:
        cik, acc, doc, _form = FILINGS[name]
    else:
        cik, acc, doc = PROXIES[name]
    url = _archive_url(cik, acc, doc)
    try:
        raw = _http_get(url)
    except Exception as exc:  # offline and not cached
        pytest.skip(f"filing {name} unavailable (offline, not cached): {exc}")
    if doc.lower().endswith((".htm", ".html")):
        text = tp.html_to_text(raw)
    else:
        text = raw.decode("utf-8", errors="replace")
    _TEXT_MEMO[name] = text
    return text


def _sections(name: str) -> dict:
    return tp.extract_sections(_load(name), FILINGS[name][3])


# --------------------------------------------------------------------------------------
# Synthetic: TOC trap and section boundaries
# --------------------------------------------------------------------------------------

SYNTH_10K = """\
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K
TABLE OF CONTENTS
PART I
Item 1. | Business | 1
Item 1A. | Risk Factors | 5
Item 3. | Legal Proceedings | 9
PART II
Item 7. | Management's Discussion and Analysis of Financial Condition and Results of Operations | 12
Item 7A. | Quantitative and Qualitative Disclosures About Market Risk | 20
Item 8. | Financial Statements and Supplementary Data | 21
Item 9. | Changes in and Disagreements with Accountants on Accounting and Financial Disclosure | 40
PART III
Item 13. | Certain Relationships and Related Transactions | 41
Item 14. | Principal Accountant Fees and Services | 41
PART I
Item 1. Business
We make widgets. """ + "Widgets are sold worldwide. " * 40 + """
Item 1A. Risk Factors
Our results may vary. """ + "Competition could harm us. " * 60 + """
Item 1B. Unresolved Staff Comments
None.
Item 3. Legal Proceedings
We are party to a lawsuit styled Acme v. Widgetco filed in 2019 alleging breach of contract.
See Item 7 of this report for further discussion of contingencies.
Item 4. Mine Safety Disclosures
Not applicable.
PART II
Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Revenue increased 12% to $120.0 million. """ + "Gross margin was stable at 40%. " * 80 + """
Item 7A. Quantitative and Qualitative Disclosures About Market Risk
We are exposed to interest rate risk.
Item 8. Financial Statements and Supplementary Data
Report of Independent Registered Public Accounting Firm
We have audited the accompanying balance sheets.
/s/ Ernst & Young LLP
San Jose, California
Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure
None.
PART III
Item 13. Certain Relationships and Related Transactions
Incorporated by reference to the proxy statement.
Item 14. Principal Accountant Fees and Services
Fees billed by the auditor:
2020 | 2019
Audit Fees | $ | 1,250,000 | $ | 1,100,000
Total | $ | 1,300,000 | $ | 1,150,000
PART IV
Item 15. Exhibits
SIGNATURES
Pursuant to the requirements of Section 13 or 15(d) of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed.
/s/ Jane Roe | Chairman and Chief Executive Officer | March 1, 2021
/s/ John Doe | Executive Vice President and Chief Financial Officer | March 1, 2021
/s/ Pat Poe | Vice President and Principal Accounting Officer | March 1, 2021
"""


def test_toc_trap_picks_body_not_toc():
    s = tp.extract_sections(SYNTH_10K, "10-K")
    assert s["mdna"].startswith("Revenue increased 12%")
    assert "Quantitative and Qualitative" not in s["mdna"]
    assert s["risk_factors"].startswith("Our results may vary")
    assert "Unresolved Staff" not in s["risk_factors"]
    assert "Acme v. Widgetco" in s["legal_proceedings"]
    assert s["legal_proceedings"].rstrip().endswith("for further discussion of contingencies.")  # cross-ref line did not truncate
    assert s["item9_changes"] == "None."
    assert s["found"]["item14"] and "Audit Fees" in s["item14"]
    assert s["incorporated_by_reference"]["related_party"] is True
    assert s["found"]["signatures"]
    assert s["found"]["notes_rpt"] is False and s["notes_rpt"] == ""


def test_toc_only_item_is_not_found():
    text = "TABLE OF CONTENTS\nItem 1A. | Risk Factors | 5\nItem 3. | Legal Proceedings | 9\nItem 7. | MD&A | 12\nSome other text without any items."
    s = tp.extract_sections(text, "10-K")
    assert not any(s["found"][k] for k in ("mdna", "risk_factors", "legal_proceedings"))
    assert s["mdna"] == ""


def test_item14_requires_accountant_title_for_old_filings():
    old = "Item 14. Exhibits, Financial Statement Schedules, and Reports on Form 8-K\n" + "(a) The following documents are filed. " * 20
    s = tp.extract_sections(old + "\nSIGNATURES\n", "10-K405")
    assert s["found"]["item14"] is False


def test_20f_subitems():
    text = (
        "TABLE OF CONTENTS\nITEM 3. | KEY INFORMATION | 1\nITEM 4. | INFORMATION ON THE COMPANY | 42\nITEM 5. | OPERATING AND FINANCIAL REVIEW AND PROSPECTS | 66\n"
        "ITEM 7. | MAJOR SHAREHOLDERS AND RELATED PARTY TRANSACTIONS | 92\nITEM 8. | FINANCIAL INFORMATION | 93\nITEM 9. | THE OFFER AND LISTING | 96\n"
        "ITEM 16.C. | PRINCIPAL ACCOUNTANT FEES AND SERVICES | 111\nITEM 16.D. | EXEMPTIONS | 112\n"
        "ITEM 3. KEY INFORMATION\n3.A. Selected Financial Data\nNone.\n3.D. Risk Factors\nRisks relating to our business. " + "We may lose money. " * 50 + "\n"
        "ITEM 4. INFORMATION ON THE COMPANY\nWe operate cafes.\n"
        "ITEM 5. OPERATING AND FINANCIAL REVIEW AND PROSPECTS\n5.A. Operating Results\n" + "Net revenues grew. " * 30 + "\n"
        "ITEM 7. MAJOR SHAREHOLDERS AND RELATED PARTY TRANSACTIONS\n7.A. Major Shareholders\nSee table.\n7.B. Related Party Transactions\nWe lent RMB10 million to an affiliate.\n7.C. Interests of Experts and Counsel\nNot applicable.\n"
        "ITEM 8. FINANCIAL INFORMATION\n8.A. Consolidated Statements and Other Financial Information\nSee F-pages.\nLegal Proceedings\nA class action was filed against us in 2020.\n8.B. Significant Changes\nNone.\n"
        "ITEM 9. THE OFFER AND LISTING\nADSs trade on Nasdaq.\n"
        "ITEM 16.C. Principal Accountant Fees and Services\nAudit Fees | 100 | 200\nITEM 16.D. Exemptions\nNone.\n"
    )
    s = tp.extract_sections(text, "20-F")
    assert s["form"] == "20-F"
    assert s["mdna"].startswith("5.A. Operating Results")
    assert s["risk_factors"].startswith("Risks relating to our business")
    assert "Investment" not in s["risk_factors"] and "We operate cafes" not in s["risk_factors"]
    assert "class action" in s["legal_proceedings"] and "Significant Changes" not in s["legal_proceedings"]
    assert "RMB10 million" in s["related_party"] and "Major Shareholders" not in s["related_party"]
    assert s["found"]["item14"]


def test_html_input_is_converted():
    html = "<html><body>" + "<p>filler</p>" * 30 + "<p>Item 3. Legal Proceedings</p><p>We are sued.</p><p>Item 4. Mine Safety</p><p>NA</p></body></html>"
    s = tp.extract_sections(html, "10-K")
    assert s["legal_proceedings"] == "We are sued."


@pytest.mark.parametrize("bad", [None, "", "   \n  ", "x" * 5000, "Item 7. " * 200, "\x00\x01\x02" * 100, "<html>" * 50])
def test_never_crashes_on_garbage(bad):
    s = tp.extract_sections(bad, "10-K")
    assert set(tp.SECTION_KEYS) <= set(s)
    assert tp.extract_auditor(bad) is None or isinstance(tp.extract_auditor(bad), str)
    assert set(tp.extract_signatories(bad)) >= {"ceo", "cfo"}
    assert tp.extract_audit_fees(bad) is None
    assert tp.keyword_hits(bad, ["restate"]) is not None
    meta = tp.build_filing_metadata({"form": "10-K"}, bad)
    assert meta["auditor"] is None or isinstance(meta["auditor"], str)


# --------------------------------------------------------------------------------------
# Synthetic: signatories
# --------------------------------------------------------------------------------------


def _sig(body: str) -> dict:
    return tp.extract_signatories("filler\n" * 5 + "SIGNATURES\nPursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed.\n" + body)


def test_signatories_table_with_co_titles():
    r = _sig(
        "/s/ Jane Roe | Chairman and CEO | March 1, 2021\n"
        "/s/ John Doe | Executive VP and Chief Financial Officer | March 1, 2021\n"
        "/s/ Pat Poe | Senior Vice President and Principal Accounting Officer | March 1, 2021\n"
        "/s/ Ann Dir | Director | March 1, 2021\n"
    )
    assert r["ceo"] == "Jane Roe"
    assert r["cfo"] == "John Doe"
    assert "Chief Financial Officer" in r["cfo_title"]
    names = [s["name"] for s in r["signers"]]
    assert "Pat Poe" in names  # principal accounting officer parsed but is not the CFO


def test_signatories_principal_accounting_officer_is_not_cfo():
    r = _sig("/s/ Jane Roe | President and Chief Executive Officer\n/s/ Pat Poe | Principal Accounting Officer\n")
    assert r["ceo"] == "Jane Roe" and r["cfo"] is None


def test_signatories_principal_financial_officer_is_cfo_when_no_cfo_title():
    r = _sig("/s/ Jane Roe | Chief Executive Officer\n/s/ Laura Crossen | Senior Vice President of Finance & Chief Accounting Officer\nLaura Crossen | (Principal Financial Officer)\n")
    assert r["cfo"] == "Laura Crossen"


def test_signatories_stacked_and_caps_column_layouts():
    stacked = _sig("By: /s/ Luca Maestri\nLuca Maestri\nSenior Vice President,Chief Financial Officer\n")
    assert stacked["cfo"] == "Luca Maestri"
    caps = _sig(
        "     JEFFREY  K. SKILLING     Chief Executive Officer and\n"
        "     (Jeffrey K. Skilling)    Director\n"
        "                              (Principal Executive Officer)\n\n"
        "      ANDREW S. FASTOW        Executive Vice President and\n"
        "     (Andrew S. Fastow)       Chief Financial Officer\n"
        "                              (Principal Financial Officer)\n\n"
        "     ROBERT A. BELFER*        Director\n    (Robert A. Belfer)\n"
    )
    assert caps["ceo"] == "Jeffrey K. Skilling"
    assert caps["cfo"] == "Andrew S. Fastow"


def test_signatories_20f_name_title_labels():
    r = _sig("Luckin Coffee Inc.\nBy: | /s/ Reinout Hendrik Schakel\nName: | Reinout Hendrik Schakel\nTitle: | Chief Financial Officer and Chief Strategy Officer\nDate: June 30, 2021\n")
    assert r["cfo"] == "Reinout Hendrik Schakel" and r["ceo"] is None


# --------------------------------------------------------------------------------------
# Synthetic: keyword_hits negation / boilerplate / going concern
# --------------------------------------------------------------------------------------

NOT_SIGNALS = [
    "Management concluded there was no material weakness in our internal control over financial reporting.",
    "We did not identify any material weaknesses during the audit.",
    "Our auditors did not identify any significant deficiencies or material weaknesses.",
    "No material weaknesses were identified.",
    "Material weaknesses were not identified in the current year.",
]
NOT_RESTATEMENT = [
    "Prior period amounts have been restated to conform to current presentation.",
    "Certain prior year amounts were restated to conform to the current year presentation.",
    "Share data has been restated to reflect the 2-for-1 stock split.",
    "Amended and Restated Certificate of Incorporation of the Registrant.",
    "If we are required to restate our financial statements, our stock price could decline.",
    "The Company has not had any restatement of its financial statements.",
    "Our clawback policy applies in the event of a restatement of our financial results.",
    "The SkyTel merger was accounted for as a pooling-of-interests and prior periods have been restated to include SkyTel.",
]


@pytest.mark.parametrize("sentence", NOT_SIGNALS)
def test_material_weakness_negations(sentence):
    hits = tp.keyword_hits(sentence, tp.MATERIAL_WEAKNESS_PATTERNS)
    assert hits and all(h["negated"] for h in hits)
    assert tp.detect_material_weakness(sentence)["detected"] is False
    raw = tp.keyword_hits(sentence, tp.MATERIAL_WEAKNESS_PATTERNS, negations=False)
    assert raw and not any(h["negated"] for h in raw)


@pytest.mark.parametrize("sentence", NOT_RESTATEMENT)
def test_restatement_boilerplate_is_not_a_signal(sentence):
    assert tp.detect_restatement(sentence)["detected"] is False
    assert all(h["negated"] for h in tp.keyword_hits(sentence, tp.RESTATEMENT_PATTERNS))


@pytest.mark.parametrize(
    "sentence",
    [
        "We restated our consolidated financial statements for fiscal 2017 and 2018 to correct errors in the accounting for leases.",
        "The Audit Committee concluded that the previously issued financial statements should no longer be relied upon.",
        "The Company will restate previously issued consolidated financial statements as of and for the year ended December 31, 2020.",
        "We have not identified any material weakness, however, we restated our financial statements due to an error.",
    ],
)
def test_real_restatement_phrases_are_signals(sentence):
    assert tp.detect_restatement(sentence)["detected"] is True


def test_material_weakness_positive():
    s = "We identified a material weakness in our internal control over financial reporting related to revenue recognition."
    assert tp.detect_material_weakness(s)["detected"] is True
    assert tp.keyword_hits(s, ["material weakness"])[0]["negated"] is False


@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("There is substantial doubt about the Company's ability to continue as a going concern.", True),
        ("These conditions raise substantial doubt about our ability to continue as a going concern.", True),
        ("Our recurring losses raise substantial doubt regarding our ability to continue as a going concern for one year.", True),
        ("Management has alleviated the substantial doubt about the Company's ability to continue as a going concern.", False),
        ("We have concluded that there is no substantial doubt about our ability to continue as a going concern.", False),
        ("The financial statements have been prepared on a going concern basis.", False),
        ("The accompanying financial statements have been prepared assuming that the Company will continue as a going concern.", False),
    ],
)
def test_going_concern(sentence, expected):
    assert tp.detect_going_concern(sentence)["detected"] is expected


def test_keyword_hits_shape_and_excerpt():
    text = "A" * 400 + " the company restated its results because of an error. " + "B" * 400
    hits = tp.keyword_hits(text, ["restated"])
    assert len(hits) == 1
    h = hits[0]
    assert set(h) >= {"pattern", "excerpt", "negated"} and "restated its results" in h["excerpt"]
    assert len(h["excerpt"]) < 500
    assert tp.keyword_hits("", ["x"]) == []


# --------------------------------------------------------------------------------------
# Synthetic: fees, firm and person names
# --------------------------------------------------------------------------------------


def test_audit_fees_year_column_and_units():
    t = "Year Ended December 31,\n2019 | 2020\n(in thousands)\nAudit Fees | $ | 900 | $ | 1,000\nTax Fees | 10 | 20\nTotal | $ | 910 | $ | 1,020\n"
    r = tp.extract_audit_fees(t)
    assert r["year"] == 2020 and r["audit_fees"] == 1_000_000 and r["total_fees"] == 1_020_000
    r2 = tp.extract_audit_fees("2020 | 2019\nAudit Fees(1) | $ | 5,000,000 | $ | 4,000,000\nAudit-Related Fees | 1 | 2\n")
    assert r2["year"] == 2020 and r2["audit_fees"] == 5_000_000 and r2["total_fees"] is None
    r3 = tp.extract_audit_fees("During 2000 we retained the auditor.\nPrincipal Auditor Fees:      $25 million\nAll Other Fees:   $27 million\n")
    assert r3["audit_fees"] == 25_000_000 and r3["year"] == 2000
    assert tp.extract_audit_fees("There are no fees here.") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ARTHUR ANDERSEN LLP", "Arthur Andersen LLP"),
        ("Arthur Andersen LLP Houston, Texas", "Arthur Andersen LLP"),
        ("/s/ Ernst & Young LLP", "Ernst & Young LLP"),
        ("Ernst &amp; Young Hua Ming LLP", "Ernst & Young Hua Ming LLP"),
        ("PricewaterhouseCoopers", "PricewaterhouseCoopers LLP"),
        ("PricewaterhouseCoopers Zhong Tian LLP", "PricewaterhouseCoopers Zhong Tian LLP"),
        ("KPMG", "KPMG LLP"),
        ("KPMG Hua Zhen LLP (Special General Partnership)", "KPMG Huazhen LLP"),
        ("DELOITTE & TOUCHE LLP", "Deloitte & Touche LLP"),
        ("Centurion ZD CPA& Co.", "Centurion ZD CPA & Co."),
        ("Marcum Bernstein & Pinchuk LLP", "Marcum Bernstein & Pinchuk LLP"),
        ("BDO USA, P.C.", "BDO USA, P.C."),
    ],
)
def test_normalize_firm_name(raw, expected):
    assert tp.normalize_firm_name(raw) == expected


def test_firm_comparison_helpers():
    assert tp.normalize_firm_name("") is None and tp.normalize_firm_name(None) is None
    assert tp.same_firm("BDO USA, LLP", "BDO USA, P.C.")
    assert tp.same_firm("BDO Seidman, LLP", "BDO USA, LLP")
    assert not tp.same_firm("Ernst & Young LLP", "Ernst & Young Hua Ming LLP")
    assert tp.same_firm("Ernst & Young LLP", "Ernst & Young Hua Ming LLP", network_level=True)
    assert tp.auditor_changed("Arthur Andersen LLP", "KPMG LLP") is True
    assert tp.auditor_changed("Ernst & Young LLP", "Ernst & Young Hua Ming LLP") is False
    assert tp.auditor_changed(None, "KPMG LLP") is None
    assert tp.firm_network("Coopers & Lybrand L.L.P.") == "PricewaterhouseCoopers"


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("Andrew S. Fastow", "Andrew Fastow", True),
        ("Fastow, Andrew S.", "Andrew S. Fastow", True),
        ("ANDREW S. FASTOW", "andrew fastow", True),
        ("Jeff Skilling", "Jeffrey K. Skilling", True),
        ("Scott D. Sullivan", "Scott Sullivan", True),
        ("Timothy D. Cook", "Tim Cook", True),
        ("Bill Gates", "William H. Gates III", True),
        ("A. Fastow", "Andrew Fastow", True),
        ("José García", "Jose Garcia", True),
        ("Robert Smith Jr.", "Robert Smith", True),
        ("Mary-Anne O'Neil", "Mary-Anne ONeil", True),
        ("John Smith", "Jane Smith", False),
        ("John Smith", "John Smyth", False),
        ("Luca Maestri", "Kevan Parekh", False),
        ("Maestri", "Luca Maestri", False),
        ("", "", False),
        (None, "Andrew Fastow", False),
    ],
)
def test_same_person(a, b, expected):
    assert tp.same_person(a, b) is expected


def test_normalize_person_name():
    assert tp.normalize_person_name("Andrew S. Fastow") == tp.normalize_person_name("FASTOW, ANDREW")
    assert tp.normalize_person_name("") is None


# --------------------------------------------------------------------------------------
# Real filings: ground truth established by reading the filing text
# --------------------------------------------------------------------------------------

#                         mdna  risk  legal rpt   item9 item14 sigs  notes_rpt
EXPECTED_FOUND = {
    "aapl19": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=0),
    "aapl20": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=0),
    "enron00": dict(mdna=1, risk_factors=0, legal_proceedings=1, related_party=1, item9_changes=1, item14=0, signatures=1, notes_rpt=1),
    "wcom01": dict(mdna=1, risk_factors=0, legal_proceedings=1, related_party=1, item9_changes=1, item14=0, signatures=1, notes_rpt=1),
    "lk19": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=1),
    "nkla20": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=1),
    "nkla20a": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=1),
    "bbby22": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=0),
    "khc18": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=0),
    "smci24": dict(mdna=1, risk_factors=1, legal_proceedings=1, related_party=1, item9_changes=1, item14=1, signatures=1, notes_rpt=1),
}
# pre-2003 filings have no Risk Factors item and Item 14 = Exhibits; "0" above is the correct, honest answer.


@pytest.mark.parametrize("name", sorted(EXPECTED_FOUND))
def test_section_found_matrix(name):
    s = _sections(name)
    got = {k: int(s["found"][k]) for k in tp.SECTION_KEYS}
    assert got == EXPECTED_FOUND[name], f"{name}: {got}"
    for k, v in EXPECTED_FOUND[name].items():
        assert bool(s[k]) is bool(v)


def test_extraction_success_rate_report(capsys):
    """Prints the per-filing / per-section success table (run with -s) and asserts the overall rate."""
    ok = tot = 0
    lines = []
    for name in sorted(EXPECTED_FOUND):
        s = _sections(name)
        row = []
        for k in tp.SECTION_KEYS:
            expected = bool(EXPECTED_FOUND[name][k])
            actual = bool(s["found"][k])
            tot += 1
            ok += int(expected == actual)
            row.append(f"{k}={'Y' if actual else '-'}({len(s[k])})")
        lines.append(f"{name:8s} " + " ".join(row))
    with capsys.disabled():
        print("\nSECTION EXTRACTION (found/(chars)) - matches ground truth in %d/%d cells" % (ok, tot))
        print("\n".join(lines))
    assert ok == tot


def test_apple_fy2019_and_fy2020():
    for name, fy in (("aapl19", 2019), ("aapl20", 2020)):
        t = _load(name)
        s = _sections(name)
        first = "This section and other parts of this Annual Report" if fy == 2019 else "The following discussion should be read in conjunction"
        assert s["mdna"].startswith(first)  # the body, not the table-of-contents entry
        assert len(s["mdna"]) > 20_000 and "Quantitative and Qualitative Disclosures About Market Risk" not in s["mdna"][:200]
        assert len(s["risk_factors"]) > 40_000 and s["risk_factors"].startswith("The following discussion of risk factors")
        assert "legal proceedings and claims" in s["legal_proceedings"]
        assert s["item9_changes"] == "None."
        assert s["incorporated_by_reference"]["item14"] is True
        assert tp.extract_auditor(t) == "Ernst & Young LLP"
        sg = tp.extract_signatories(t)
        assert (sg["ceo"], sg["cfo"]) == ("Timothy D. Cook", "Luca Maestri")
        assert "Chief Financial Officer" in sg["cfo_title"]
        assert tp.extract_audit_fees(s["item14"]) is None  # fees are incorporated from the proxy
        assert tp.detect_restatement(t)["detected"] is False
        assert tp.detect_material_weakness(t)["detected"] is False
        assert tp.detect_going_concern(t)["detected"] is False


def test_apple_metadata_with_proxy_fees():
    filing = {"form": "10-K", "filing_date": "2020-10-30", "accession": "0000320193-20-000096"}
    meta = tp.build_filing_metadata(filing, _load("aapl20"), proxy_text=_load("aapl_proxy21"))
    assert meta["auditor"] == "Ernst & Young LLP"
    assert (meta["ceo"], meta["cfo"]) == ("Timothy D. Cook", "Luca Maestri")
    assert meta["filing_date"] == "2020-10-30" and meta["form"] == "10-K" and meta["accession"] == "0000320193-20-000096"
    assert meta["audit_fee_source"] == "proxy"
    assert meta["audit_fees"] == 17_568_300.0
    assert meta["audit_fee_detail"]["total_fees"] == 22_183_900.0 and meta["audit_fee_detail"]["year"] == 2020
    assert meta["signatures_found"] is True and meta["related_party_chars"] > 0


def test_enron_fy2000_10k():
    t = _load("enron00")
    s = _sections("enron00")
    assert s["mdna"].startswith("The following review of the results of operations")
    assert len(s["mdna"]) > 40_000
    assert "claims and litigation" in s["legal_proceedings"]
    assert s["item9_changes"] == "None."
    assert s["risk_factors"] == "" and s["item14"] == ""  # no Item 1A / Item 14 was Exhibits in FY2000
    flat = " ".join(s["notes_rpt"].split())  # fixed-width .txt wraps lines
    assert "limited partnerships" in flat and "(the Related Party)" in flat
    assert tp.extract_auditor(t) == "Arthur Andersen LLP"
    sg = tp.extract_signatories(t)
    assert sg["ceo"] == "Jeffrey K. Skilling"
    assert sg["cfo"] == "Andrew S. Fastow" and "Chief Financial Officer" in sg["cfo_title"]
    assert tp.same_person(sg["cfo"], "Andrew Fastow")
    # the Chief Accounting Officer signed too but is not the CFO
    assert any(x["name"] == "Richard A. Causey" for x in sg["signers"])
    assert tp.detect_restatement(t)["detected"] is False  # restatement came in Nov 2001, after this filing
    assert tp.detect_going_concern(t)["detected"] is False


def test_enron_proxy_audit_fees():
    r = tp.extract_audit_fees(_load("enron_proxy01"))
    assert r["audit_fees"] == 25_000_000 and r["year"] == 2000
    assert "$27 million" in r["source_excerpt"]  # 'All Other Fees' (consulting) of $27M, visible in the excerpt


def test_worldcom_fy2001_10k405():
    t = _load("wcom01")
    s = _sections("wcom01")
    assert len(s["mdna"]) > 100_000 and "recapitalization" in s["mdna"][:600]
    assert s["item9_changes"].strip() == "None"
    assert "Ebbers" in s["notes_rpt"]  # loans to the CEO are disclosed in the related-party note
    assert tp.extract_auditor(t) == "Arthur Andersen LLP"
    sg = tp.extract_signatories(t)
    assert sg["ceo"] == "Bernard J. Ebbers"
    assert sg["cfo"] == "Scott D. Sullivan"
    assert "Chief Financial Officer" in sg["cfo_title"]
    assert tp.detect_restatement(t)["detected"] is False  # pooling-of-interests / split 'restated' are boilerplate


def test_luckin_fy2019_20f():
    t = _load("lk19")
    s = _sections("lk19")
    assert s["form"] == "20-F"
    assert s["mdna"].startswith("You should read the following discussion")
    assert s["risk_factors"].startswith("Risks Relating to Our Internal Investigation") and len(s["risk_factors"]) > 150_000
    assert "legal and administrative proceedings" in s["legal_proceedings"]
    assert "Haode" in s["related_party"]
    assert "Marcum Bernstein & Pinchuk" in s["item9_changes"]
    assert "Audit Fees" in s["item14"]
    det = tp.extract_auditor_details(t)
    assert det["name"] == "Centurion ZD CPA & Co."  # signs the FY2019 report; EY Hua Ming signs the FY2018 comparative report
    assert det["all_signoffs"] == ["Centurion ZD CPA & Co.", "Ernst & Young Hua Ming LLP"]
    sg = tp.extract_signatories(t)
    assert sg["cfo"] == "Reinout Hendrik Schakel" and "Chief Strategy Officer" in sg["cfo_title"]
    assert sg["ceo"] is None  # only the CFO signed the 20-F
    fees = tp.extract_audit_fees(s["item14"])
    assert fees["audit_fees"] == 45_012_000 and fees["total_fees"] == 45_506_000 and fees["year"] == 2019  # RMB, "(in thousands)"
    assert tp.detect_restatement(t)["detected"] is True
    assert tp.detect_material_weakness(t)["detected"] is True


def test_nikola_fy2020_original_vs_restated_amendment():
    orig, amend = _load("nkla20"), _load("nkla20a")
    assert tp.detect_restatement(orig)["detected"] is False
    assert tp.detect_material_weakness(orig)["detected"] is False
    ra = tp.detect_restatement(amend)
    assert ra["detected"] is True
    assert any("restate previously issued" in h["excerpt"] for h in ra["hits"])
    assert tp.detect_material_weakness(amend)["detected"] is True
    sg = tp.extract_signatories(orig)
    assert (sg["ceo"], sg["cfo"]) == ("Mark A. Russell", "Kim J. Brady")
    assert tp.extract_auditor(orig) == "Ernst & Young LLP"
    assert "Aircraft Charter" in _sections("nkla20")["notes_rpt"]
    sga = tp.extract_signatories(amend)
    assert sga["ceo"] == "Mark A. Russell" and sga["cfo"] is None  # the 10-K/A is signed by the CEO only
    fees = tp.extract_audit_fees(_sections("nkla20a")["item14"])
    assert fees["audit_fees"] == 933_895 and fees["year"] == 2020


def test_bbby_going_concern():
    t = _load("bbby22")
    gc = tp.detect_going_concern(t)
    assert gc["detected"] is True and len(gc["hits"]) >= 3
    assert any("substantial doubt" in h["excerpt"] and "Chapter 11" in t for h in gc["hits"])
    assert tp.extract_auditor(t) == "KPMG LLP"
    sg = tp.extract_signatories(t)
    assert sg["ceo"] == "Sue E. Gove" and sg["cfo"] == "Laura Crossen"  # CFO via "(Principal Financial Officer)"
    assert tp.detect_restatement(t)["detected"] is False  # only clawback-policy language


def test_kraft_heinz_restatement_and_material_weakness():
    t = _load("khc18")
    s = _sections("khc18")
    assert tp.detect_restatement(t)["detected"] is True
    assert tp.detect_material_weakness(t)["detected"] is True
    assert tp.detect_going_concern(t)["detected"] is False
    assert tp.extract_auditor(t) == "PricewaterhouseCoopers LLP"
    sg = tp.extract_signatories(t)
    assert (sg["ceo"], sg["cfo"]) == ("Bernardo Hees", "David H. Knopf")
    fees = tp.extract_audit_fees(s["item14"])
    assert fees["audit_fees"] == 19_234_000 and fees["total_fees"] == 20_893_000 and fees["year"] == 2018


def test_supermicro_fy2024_auditor_change_and_material_weakness():
    t = _load("smci24")
    s = _sections("smci24")
    assert tp.extract_auditor(t) == "BDO USA, P.C."
    assert "letter of resignation" in s["item9_changes"] and "EY resigned" in s["item9_changes"]
    assert "Ernst & Young" in s["item14"] and "BDO" in s["item14"] and "Deloitte" in s["item14"]
    assert tp.detect_material_weakness(t)["detected"] is True
    assert tp.detect_restatement(t)["detected"] is False  # no restatement; hits are risk-factor / clawback language
    sg = tp.extract_signatories(t)
    assert sg["ceo"] == "Charles Liang" and sg["cfo"] == "David Weigand"
    fees = tp.extract_audit_fees(s["item14"])
    assert fees["audit_fees"] == 8_000_000 and fees["year"] == 2024
    assert tp.same_firm(tp.extract_auditor(t), "BDO USA, LLP")


# --------------------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["khc18", "lk19", "wcom01", "smci24"])
def test_sections_under_two_seconds(name):
    t = _load(name)
    assert len(t) > 500_000
    start = time.perf_counter()
    tp.extract_sections(t, FILINGS[name][3])
    assert time.perf_counter() - start < 2.0


def test_full_metadata_under_two_seconds_on_3mb_text():
    t = _load("khc18") + "\n" + _load("lk19") + "\n" + _load("wcom01")
    assert len(t) > 2_000_000
    start = time.perf_counter()
    tp.extract_sections(t, "10-K")
    assert time.perf_counter() - start < 2.0


# ======================================================================================
# v2 (docs/V2_CHANGELOG_text_network.md): B1 / B12 material weakness + restatement
# ======================================================================================

def _k10(preface="", rf="", item9a="", body="", extra=""):
    """Synthetic 10-K skeleton (artificial text) with a TOC, preface, Item 1A, Item 8 and Item 9A."""
    return (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\nFor the fiscal year ended December 31, 2020\n"
        + preface + "\nTABLE OF CONTENTS\nItem 1A. | Risk Factors | 12\nItem 8. | Financial Statements | 40\nItem 9A. | Controls and Procedures | 60\n"
        "PART I\nItem 1. Business\nWe sell widgets. " + "Our business is steady. " * 20 + "\nItem 1A. Risk Factors\n" + rf + "\n"
        "Item 1B. Unresolved Staff Comments\nNone.\nPART II\nItem 8. Financial Statements and Supplementary Data\n" + body + "\n"
        "Item 9. Changes in and Disagreements with Accountants\nNone.\nItem 9A. Controls and Procedures\n" + item9a + "\n"
        "Item 9B. Other Information\nNone.\n" + extra
    )


VG_STYLE_PREFACE = ("Forward-looking statements. These include: extensive and evolving government regulation that impact the way we operate; "
                    "risks associated with international expansion; our ability to timely and effectively remediate material weaknesses and "
                    "maintain effective internal control over financial reporting and disclosure and procedures; and our ability to continue to "
                    "use, maintain, enforce, protect and defend our owned and licensed intellectual property.")
AUDITOR_DEFINITION = ("A material weakness is a deficiency, or a combination of deficiencies, in internal control over financial reporting, such that "
                      "there is a reasonable possibility that a material misstatement of the company's annual or interim financial statements will not "
                      "be prevented or detected on a timely basis. Because of its inherent limitations, we assess the risk that a material weakness exists.")


def test_mw_forward_looking_preface_and_auditor_definition_are_not_reported():
    t = _k10(preface=VG_STYLE_PREFACE, body=AUDITOR_DEFINITION,
             item9a="Management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is False and mw["hits"] == []
    assert len(mw["forward_looking_hits"]) >= 1          # recorded, not flagged
    assert mw["icfr_effective"] is True


@pytest.mark.parametrize("sentence", [
    "Our ability to timely remediate any material weakness could affect investor confidence.",
    "If we identify a material weakness in the future, investors could lose confidence.",
    "We may in the future identify material weaknesses, and there can be no assurance that we will remediate them.",
    "The failure to maintain effective internal control, including any material weakness, would harm us.",
])
def test_mw_forward_looking_risk_factor_wording_is_not_reported(sentence):
    r = tp.detect_material_weakness(_k10(rf=sentence), "10-K")
    assert r["detected"] is False


def test_mw_reported_in_item_9a_with_not_effective_conclusion():
    t = _k10(rf="We may identify material weaknesses in the future that could harm us.",
             item9a="Management concluded that, as of December 31, 2020, our internal control over financial reporting was not effective. "
                    "We identified a material weakness related to revenue recognition controls.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is True and mw["icfr_not_effective"] is True
    assert mw["hits"][0]["section"] == "item9a"          # B12: the Item 9A hit is first, not the risk-factor sentence
    assert all(h["section"] == "item9a" for h in mw["hits"])
    assert 0 < mw["hits"][0]["pct_of_document"] < 100


def test_mw_item_9a_hit_is_preferred_over_preface_hit():
    t = _k10(preface="Explanatory note. We identified a material weakness in our internal control over financial reporting, as described below.",
             item9a="We identified a material weakness in our internal control over financial reporting as of December 31, 2020, "
                    "and our internal control over financial reporting was not effective.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is True
    secs = [h["section"] for h in mw["hits"]]
    assert secs[0] == "item9a" and "preface" in secs and secs.index("item9a") < secs.index("preface")


def test_mw_not_effective_conclusion_without_the_phrase_counts():
    t = _k10(item9a="Our management concluded that our internal control over financial reporting was not effective as of December 31, 2020.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is True and mw["hits"][0]["kind"] == "icfr_not_effective"
    t2 = _k10(item9a="Our management concluded that our disclosure controls and procedures were ineffective as of December 31, 2020.")
    assert tp.detect_material_weakness(t2, "10-K")["detected"] is True


def test_mw_auditor_adverse_icfr_opinion_counts():
    t = _k10(body="In our opinion, the Company did not maintain, in all material respects, effective internal control over financial reporting "
                  "as of December 31, 2020, based on the COSO criteria.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is True and mw["auditor_adverse_opinion"] is True and mw["hits"][0]["kind"] == "adverse_opinion"


def test_mw_remediated_history_is_recorded_not_flagged():
    t = _k10(item9a="In connection with the audit of our 2019 financial statements we identified two material weaknesses. During 2020 we "
                    "completed the remediation of these material weaknesses. Management concluded that our internal control over financial "
                    "reporting was effective as of December 31, 2020.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is False
    assert len(mw["remediated_hits"]) >= 1 and mw["icfr_effective"] is True


def test_mw_prior_period_and_previously_reported_are_history():
    t = _k10(body="As of December 31, 2018, we identified a material weakness related to inventory counts.")
    assert tp.detect_material_weakness(t, "10-K")["detected"] is False       # earlier balance-sheet date than FY2020
    t2 = _k10(body="We previously identified a material weakness related to inventory counts.")
    r2 = tp.detect_material_weakness(t2, "10-K")
    assert r2["detected"] is False and r2["remediated_hits"]


def test_mw_not_yet_remediated_is_still_reported():
    t = _k10(item9a="We previously identified a material weakness in our controls over revenue. The material weakness has not been remediated "
                    "as of December 31, 2020, and management concluded that our internal control over financial reporting was not effective.")
    assert tp.detect_material_weakness(t, "10-K")["detected"] is True


def test_mw_hit_shape_and_backward_compat():
    r = tp.detect_material_weakness("We identified a material weakness in our internal control over financial reporting.")
    assert {"detected", "hits", "negated_hits", "n_raw"} <= set(r)
    h = r["hits"][0]
    assert {"pattern", "excerpt", "negated", "reason", "start", "section", "pct_of_document", "kind"} <= set(h)
    assert tp.detect_material_weakness("")["detected"] is False and tp.detect_material_weakness(None)["detected"] is False


def test_restatement_amended_and_restated_agreement_is_not_a_signal():
    t = _k10(body="Exhibit 10.4 Amended and Restated Registration Rights Agreement. Amended and Restated Trademark License Agreement. "
                  "Amended and Restated Bylaws of the Company.")
    r = tp.detect_restatement(t, "10-K")
    assert r["detected"] is False


@pytest.mark.parametrize("sentence,kind", [
    ("The Audit Committee concluded that the previously issued financial statements should no longer be relied upon (Item 4.02 non-reliance).", "non_reliance"),
    ("We restated previously issued financial statements for the years ended December 31, 2018 and 2019 to correct errors.", "restated_previously_issued"),
    ("The Company restated its quarterly financial statements for 2019 because of accounting irregularities.", "restated_previously_issued"),
])
def test_restatement_reported_kinds(sentence, kind):
    r = tp.detect_restatement(_k10(body=sentence), "10-K")
    assert r["detected"] is True and r["hits"][0]["kind"] == kind and r["hits"][0]["section"] in ("body", "preface")


@pytest.mark.parametrize("sentence", [
    "Adoption of the standard required us to restate certain previously reported results using the full retrospective method.",
    "The effect of the change was immaterial and prior amounts were not restated; equity for 2014-2016 has been restated from the amounts previously reported.",
    "A restatement could occur if we find errors, which could harm our stock price.",
])
def test_restatement_accounting_change_recast_and_hypothetical_are_not_signals(sentence):
    r = tp.detect_restatement(_k10(body=sentence), "10-K")
    assert r["detected"] is False


def test_locate_sections_positions():
    t = _k10(preface="PREFACE-MARK", rf="Competition may hurt us.", item9a="nine-a-body text")
    loc = tp.locate_sections(t, "10-K")
    s, e = loc["item9a"]
    assert "nine-a-body text" in t[s:e] and "Item 9B" not in t[s:e]
    assert t.index("PREFACE-MARK") < loc["preface_end"] <= t.index("Item 1. Business")
    assert loc["risk_factors"] is not None


# ---- B9: one consistent related-party measure -------------------------------------------------

def test_related_party_measure_prefers_note_then_item13_then_pointer():
    note = "x" * 500
    inline = "y" * 900
    assert tp.related_party_measure({"notes_rpt": note, "related_party": inline}) == (500, "note")
    assert tp.related_party_measure({"notes_rpt": "", "related_party": inline, "incorporated_by_reference": {"related_party": False}}) == (900, "item13")
    ptr = "The information required is incorporated by reference to the proxy statement."
    assert tp.related_party_measure({"notes_rpt": "", "related_party": ptr, "incorporated_by_reference": {"related_party": True}}) == (len(ptr), "pointer")
    assert tp.related_party_measure({"notes_rpt": "", "related_party": ""}) == (0, None)


def test_build_filing_metadata_related_party_fields_synthetic():
    meta = tp.build_filing_metadata({"form": "10-K"}, SYNTH_10K)
    assert meta["related_party_source"] == "pointer"           # Item 13 only says "Incorporated by reference to the proxy statement."
    assert meta["related_party_chars"] == meta["related_party_item13_chars"] > 0 and meta["related_party_note_chars"] == 0


# ---- B11: Legal Proceedings pointer -> note ----------------------------------------------------

LEGAL_POINTER_10K = (
    "FORM 10-K\nTABLE OF CONTENTS\nItem 3. | Legal Proceedings | 20\nPART I\nItem 1. Business\nWe sell widgets. " + "Filler text. " * 40 + "\n"
    "Item 3. Legal Proceedings\nFor a description of our legal proceedings, see Note 7, Commitments and Contingencies, to the financial statements.\n"
    "Item 4. Mine Safety Disclosures\nNot applicable.\nPART II\nItem 8. Financial Statements\n"
    "NOTE 6 - LEASE COMMITMENTS\nWe lease office space under operating leases. " + "Rent is paid monthly. " * 20 + "\n"
    "NOTE 7 - COMMITMENTS AND CONTINGENCIES\nLegal Proceedings\nOn March 3, 2021 a putative class action was filed against the Company alleging "
    "securities fraud. The SEC issued a subpoena. " + "The Company intends to defend vigorously. " * 10 + "\n"
    "NOTE 8 - RELATED PARTY TRANSACTIONS\nWe paid the CEO consulting fees. " + "Details follow. " * 15 + "\n"
    "Item 9. Changes in and Disagreements with Accountants\nNone.\n"
)


def test_legal_note_is_exposed_when_item3_is_a_pointer():
    s = tp.extract_sections(LEGAL_POINTER_10K, "10-K")
    assert s["incorporated_by_reference"]["legal_proceedings"] is True and len(s["legal_proceedings"]) < 300
    assert s["found"]["legal_note"] is True
    assert "putative class action" in s["legal_note"] and "SEC issued a subpoena" in s["legal_note"]
    assert "RELATED PARTY" not in s["legal_note"] and "LEASE COMMITMENTS" not in s["legal_note"]
    info = s["legal_note_info"]
    assert info["note"] == 7 and info["via_pointer"] is True and info["legal_proceedings_is_pointer"] is True


def test_legal_note_ignores_wrapped_item3_header_and_balance_sheet_caption():
    text = ("ITEM\n3. LEGAL PROCEEDINGS\nNone.\nItem 4. Mine Safety\nN/A\nCommitments and contingencies (Note 5) | | \nTotal liabilities | 1,000 |\n" + "z " * 100)
    s = tp.extract_sections(text, "10-K")
    assert s["legal_note"] == "" and s["found"]["legal_note"] is False


def test_section_keys_backward_compatible():
    s = tp.extract_sections(SYNTH_10K, "10-K")
    assert set(tp.SECTION_KEYS) == {"mdna", "risk_factors", "legal_proceedings", "related_party", "item9_changes", "item14", "signatures", "notes_rpt"}
    assert set(tp.V2_SECTION_KEYS) == {"legal_note", "controls"} and set(tp.ALL_SECTION_KEYS) <= set(s)
    assert set(s["found"]) == set(tp.ALL_SECTION_KEYS)


# ---- mojibake ----------------------------------------------------------------------------------

def test_cp1252_bytes_and_c1_control_characters_never_become_replacement_glyphs():
    raw = b"<html><body><p>Item 3. Legal Proceedings</p><p>Pending\x85 see list: \x95 first \x95 second \x93quoted\x94 \x92s</p></body></html>"
    txt = tp.html_to_text(raw)
    assert "�" not in txt and "…" in txt and "•" in txt and "“quoted”" in txt
    prepared = tp._prepare("Chapter 11\x85 and the \x95 bullet \x97 dash")
    assert "�" not in prepared and not any("\x80" <= c <= "\x9f" for c in prepared)
    hits = tp.keyword_hits("We identified a material weakness\x85 and \x95 more � text.", tp.MATERIAL_WEAKNESS_PATTERNS)
    assert hits and all("�" not in h["excerpt"] and not any("\x80" <= c <= "\x9f" for c in h["excerpt"]) for h in hits)


# ---- B10 helpers --------------------------------------------------------------------------------

SPAC_10K = ("FORM 10-K\nWe are a blank check company incorporated as a Cayman Islands exempted company. We have neither engaged in any operations "
            "nor generated any revenue to date. " + "Funds in the trust account are held in treasury. " * 8 +
            "If we do not consummate our initial business combination within 24 months, we will liquidate the trust account.")


def test_detect_shell_filing_synthetic():
    assert tp.detect_shell_filing(SPAC_10K)["is_shell"] is True
    merged = SPAC_10K + " On June 3, 2020 we consummated the Business Combination, and Legacy Foo's Chief Financial Officer became our CFO."
    assert tp.detect_shell_filing(merged)["is_shell"] is False
    ordinary = ("The registrant is a large accelerated filer. Indicate by check mark whether the registrant is a shell company. No. "
                "Our preferred stock is blank check preferred stock. We make widgets. " * 3)
    assert tp.detect_shell_filing(ordinary)["is_shell"] is False


def test_detect_merger_context_synthetic():
    t = ("Withum, our independent registered public accounting firm prior to the Business Combination, was replaced by KPMG, which audited "
         "only the pre-merger special purpose acquisition company. Mr. Rodriguez served as Legacy Lordstown's Chief Financial Officer. "
         "The Business Combination was consummated on October 23, 2020. On October 23, 2020 (the Closing Date) the Business Combination closed.")
    d = tp.detect_merger_context(t)
    assert d["detected"] is True and "prior to the Business Combination" in d["cues"] and d["closing_year"] == 2020
    assert tp.detect_merger_context("We changed auditors after a competitive tender. The CFO retired in 2020.")["detected"] is False
    assert tp.detect_merger_context("Our legacy products and legacy systems remain in service.")["detected"] is False


# ======================================================================================
# v2 on REAL cached dev filings (Luckin FY2019 20-F, Nikola FY2020 10-K and 10-K/A, WorldCom, Enron, Apple)
# ======================================================================================

def test_real_luckin_20f_material_weakness_comes_from_item_15_not_the_preface():
    t, form = _load("lk19"), "20-F"
    mw = tp.detect_material_weakness(t, form)
    assert mw["detected"] is True and mw["icfr_not_effective"] is True
    assert mw["hits"][0]["section"] == "item9a"                     # Item 15 'Controls and Procedures' of the 20-F
    assert "disclosure controls and procedures were ineffective" in mw["hits"][0]["excerpt"]
    rs = tp.detect_restatement(t, form)
    assert rs["detected"] is True and rs["hits"][0]["kind"] == "non_reliance"
    assert any("should not be relied upon" in h["excerpt"] for h in rs["hits"])
    assert _sections("lk19")["found"]["controls"] is True


def test_real_nikola_original_10k_is_clean_and_amendment_reports_a_weakness():
    orig, amend = _load("nkla20"), _load("nkla20a")
    assert tp.detect_material_weakness(orig, "10-K")["detected"] is False
    ma = tp.detect_material_weakness(amend, "10-K/A")
    assert ma["detected"] is True and ma["hits"][0]["section"] in ("item9a", "body")
    assert tp.detect_restatement(amend, "10-K/A")["detected"] is True


def test_real_nikola_item3_pointer_resolves_to_the_commitments_and_contingencies_note():
    s = _sections("nkla20")
    assert s["incorporated_by_reference"]["legal_proceedings"] is True and len(s["legal_proceedings"]) < 400
    assert s["found"]["legal_note"] and s["legal_note_info"]["note"] == 14 and s["legal_note_info"]["via_pointer"] is True
    low = s["legal_note"].lower()
    assert len(s["legal_note"]) > 10_000 and "subpoena" in low and "hindenburg" in low and "securities and exchange commission" in low


def test_real_related_party_measure_source_flags():
    for name, src in (("enron00", "note"), ("wcom01", "note"), ("nkla20", "note")):
        meta = tp.build_filing_metadata({"form": FILINGS[name][3]}, _load(name))
        assert meta["related_party_source"] == src, name
        assert meta["related_party_chars"] == meta["related_party_note_chars"] > 0, name
        assert meta["related_party_item13_chars"] > 0, name           # raw component kept for transparency
    meta = tp.build_filing_metadata({"form": "10-K"}, _load("aapl20"))
    assert meta["related_party_source"] == "pointer" and meta["related_party_chars"] == meta["related_party_item13_chars"] < 600


@pytest.mark.parametrize("name", ["aapl19", "aapl20", "enron00", "wcom01", "bbby22"])
def test_real_clean_filings_stay_clean_under_v2_detectors(name):
    t, form = _load(name), FILINGS[name][3]
    assert tp.detect_material_weakness(t, form)["detected"] is False
    assert tp.detect_restatement(t, form)["detected"] is False


@pytest.mark.parametrize("name", ["khc18", "smci24"])
def test_real_reported_weakness_filings_detected_from_item_9a(name):
    t, form = _load(name), FILINGS[name][3]
    mw = tp.detect_material_weakness(t, form)
    assert mw["detected"] is True and mw["hits"][0]["section"] == "item9a" and mw["icfr_not_effective"] is True


@pytest.mark.parametrize("name", ["aapl20", "nkla20", "lk19", "khc18", "wcom01"])
def test_real_excerpts_have_no_replacement_glyphs(name):
    t = _load(name)
    for fn in (tp.detect_material_weakness, tp.detect_restatement, tp.detect_going_concern):
        for h in fn(t)["hits"][:20]:
            assert "�" not in h["excerpt"] and not any("\x80" <= c <= "\x9f" for c in h["excerpt"])


# ---- other text_parser defects found while verifying on the dev cases -----------------------------

def test_fee_table_footnote_marker_is_not_the_fee():
    t = "The table below sets forth the aggregate fees billed by the auditor in 2019 and 2020.\n\n2020 | 2019 (3,4)\nAudit Fees 1 | $1,963,668 | $1,459,734\nAudit Related Fees | — | —\nTotal | $1,963,668 | $1,774,848\n"
    f = tp.extract_audit_fees(t)
    assert f["audit_fees"] == 1_963_668 and f["year"] == 2020 and f["total_fees"] == 1_963_668


def test_fee_prose_paragraph_is_not_a_table_row_and_narrative_amount_is_used():
    t = ("Audit Fees. Audit fees consist of fees for professional services rendered for the audit of our year-end financial statements and "
         "services that are normally provided by the firm in connection with regulatory filings. The aggregate fees for professional services "
         "rendered for the audit of our annual financial statements, review of the financial information included in our Forms 10-Q for the "
         "respective periods totaled approximately $54,600 for the period ended December 31, 2018. Audit-related fees totaled approximately $69,250.")
    f = tp.extract_audit_fees(t)
    assert f["audit_fees"] == 54_600


def test_fee_year_header_with_repeated_year_token():
    t = ("Fees\nYear ended December 31, 2018 | For the Period from May 5, 2017 2017 (inception) through December 31, 2017\n"
         "Audit Fees (1) | $54,848 | $54,270\nTotal | $54,848 | $101,220\n")
    f = tp.extract_audit_fees(t)
    assert f["audit_fees"] == 54_848 and f["year"] == 2018


@pytest.mark.parametrize("raw,expected", [
    ("S ATYA N ADELLA Satya", "Satya Nadella"),
    ("Julio Rodriguez Julio Rodriguez", "Julio Rodriguez"),
    ("Timothy D. Cook TIMOTHY D.", "Timothy D. Cook"),
    ("Kim J. Brady", "Kim J. Brady"),
])
def test_tidy_signer_name(raw, expected):
    assert tp._tidy_signer_name(raw) == expected


# ======================================================================================
# v3 (docs/V3_CHANGELOG_text_network.md): pronouncement / certification / investee / immaterial-revision / history guards
# ======================================================================================

def _v3_tenk(rf="", item9a="", body=""):
    return ("FORM 10-K\nFor the fiscal year ended December 31, 2020\nPART I\nItem 1. Business\nWe sell widgets. " + "Steady business. " * 20
            + "\nItem 1A. Risk Factors\n" + rf + "\nItem 1B. Unresolved Staff Comments\nNone.\nPART II\n" + body
            + "\nItem 9. Changes in and Disagreements\nNone.\nItem 9A. Controls and Procedures\n" + item9a + "\nItem 9B. Other Information\nNone.\n")


@pytest.mark.parametrize("sentence", [
    "In August 2014, the FASB issued ASU 2014-15, which is intended to define management's responsibility to evaluate whether there is substantial doubt about an organization's ability to continue as a going concern.",
    "Management of public and private companies will be required to evaluate whether there are conditions and events that raise substantial doubt about the entity's ability to continue as a going concern within one year after the financial statements are issued.",
    "The amendments in this update provide guidance about management's responsibility to evaluate whether there is substantial doubt about an entity's ability to continue as a going concern and to provide related footnote disclosures.",
    "ASC 205-40 requires management to assess, each reporting period, whether conditions raise substantial doubt about the Company's ability to continue as a going concern.",
    "During the year, management assessed the Company's ability to continue as a going concern as required and concluded there were no conditions that gave rise to substantial doubt about the ability to continue as a going concern; therefore, additional disclosures were not required.",
    "Management did not identify conditions or events that raise substantial doubt about the Company's ability to continue as a going concern within one year.",
])
def test_v3_going_concern_pronouncement_and_no_doubt_text_is_not_a_signal(sentence):
    r = tp.detect_going_concern(sentence)
    assert r["detected"] is False, r["hits"]


@pytest.mark.parametrize("sentence", [
    "These conditions raise substantial doubt about the Company's ability to continue as a going concern.",
    "The Company has suffered recurring losses from operations, which raise substantial doubt about its ability to continue as a going concern. Management's plans are described in Note 2.",
    "As discussed in Note 2, the Company's recurring losses and negative working capital raise substantial doubt about its ability to continue as a going concern.",
    "In accordance with ASU 2014-15, management evaluated the Company's liquidity and concluded that conditions raise substantial doubt about the Company's ability to continue as a going concern.",
    "Our independent registered public accounting firm has included an explanatory paragraph expressing substantial doubt about our ability to continue as a going concern.",
])
def test_v3_genuine_going_concern_statements_still_detected(sentence):
    assert tp.detect_going_concern(sentence)["detected"] is True


_CERT = ("5. The registrant's other certifying officer and I have disclosed, based on our most recent evaluation of internal control over financial reporting, "
         "to the registrant's auditors and the audit committee of the registrant's board of directors: (a) all significant deficiencies and material weaknesses "
         "in the design or operation of internal control over financial reporting which are reasonably likely to adversely affect the registrant's ability to record, "
         "process, summarize and report financial information; and (b) any fraud, whether or not material, that involves management.")


def test_v3_sox_302_certification_is_not_a_reported_weakness():
    t = _v3_tenk(item9a="Management concluded that internal control over financial reporting was effective.", body="Exhibit 31.1 Certification\n" + _CERT)
    assert tp.detect_material_weakness(t, "10-K")["detected"] is False
    assert tp.detect_material_weakness(_CERT, "10-K")["detected"] is False
    assert tp.detect_restatement(_CERT, "10-K")["detected"] is False


def test_v3_investee_or_third_party_restatement_is_not_the_registrants():
    for s in ("The Company accounts for its investment in Vail under the equity method. In November 2003, Vail again restated its financial statements. The Company chose to reflect the full impact in fiscal 2003 rather than restate its previously reported financial statements.",
              "Our equity method investee restated its previously issued financial statements for 2018 and 2019.",
              "One of our largest customers announced that it would restate its previously issued financial statements."):
        assert tp.detect_restatement(s, "10-K")["detected"] is False, s
    own = "On March 1 the Audit Committee concluded that the Company's previously issued financial statements should be restated because of errors in revenue recognition."
    assert tp.detect_restatement(own, "10-K")["detected"] is True
    assert tp.detect_restatement("We restated our previously issued consolidated financial statements to correct errors in the accounting for leases.", "10-K")["detected"] is True


def test_v3_immaterial_correction_without_restatement_is_not_a_restatement():
    imm = ("The Company identified errors in prior period financial statements that were not material to any prior period. The Company has revised "
           "previously issued financial statements to correct these immaterial errors and did not restate its prior filings.")
    assert tp.detect_restatement(imm, "10-K")["detected"] is False
    imm2 = ("Management concluded the errors were immaterial to previously issued financial statements; accordingly the previously issued financial statements "
            "have been revised and the revision is not a restatement.")
    assert tp.detect_restatement(imm2, "10-K")["detected"] is False
    nonrel = imm + " The Audit Committee also concluded that the previously issued financial statements should no longer be relied upon."
    assert tp.detect_restatement(nonrel, "10-K")["detected"] is True


@pytest.mark.parametrize("sentence", [
    "Although we have recently remediated a material weakness in our internal control over financial reporting, if we are unable to maintain effective controls our stock price could decline.",
    "We recently remediated the material weakness in our internal control over financial reporting that was identified last year.",
    "The material weakness identified in the prior year has since been remediated.",
])
def test_v3_recently_remediated_weakness_is_history_not_a_current_flag(sentence):
    t = _v3_tenk(rf=sentence, item9a="Management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    assert tp.detect_material_weakness(t, "10-K")["detected"] is False
    t2 = _v3_tenk(body=sentence, item9a="")
    assert tp.detect_material_weakness(t2, "10-K")["detected"] is False


def test_v3_auditor_report_that_no_longer_expresses_an_adverse_opinion_is_history():
    s = ("As a result, our assessment of the effectiveness of our internal control over financial reporting as of December 31, 2020 no longer reports this material "
         "weakness, and the audit report of our independent registered public accounting firm no longer expresses an adverse opinion on the effectiveness of our "
         "internal control over financial reporting as of December 31, 2020.")
    t = _v3_tenk(rf=s, item9a="Management concluded that our internal control over financial reporting was effective as of December 31, 2020.")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is False and mw["auditor_adverse_opinion"] is False


def test_v3_weakness_dated_before_the_fiscal_year_is_history_even_if_the_sentence_also_dates_the_current_year():
    s = ("Although our internal controls over financial reporting were effective as of December 31, 2020, we identified a material weakness in our "
         "internal controls over financial reporting as of December 31, 2019 and December 31, 2018.")
    t = _v3_tenk(body=s, item9a="")
    mw = tp.detect_material_weakness(t, "10-K")
    assert mw["detected"] is False and mw["remediated_hits"]


def test_v3_item_9a_first_effective_icfr_outside_weakness_mentions_cannot_flag():
    effective = "Management concluded that our internal control over financial reporting was effective as of December 31, 2020. No material weakness was reported."
    for where, txt in (("rf", "We identified a material weakness in the internal controls of an acquired company that has not been remediated."),
                       ("body", "Our supplier disclosed that it has identified a material weakness in its internal controls which remains unremediated.")):
        t = _v3_tenk(**{where: txt}, item9a=effective)
        mw = tp.detect_material_weakness(t, "10-K")
        assert mw["detected"] is False, (where, mw["hits"])
        assert mw["icfr_effective"] is True and mw["remediated_hits"]
    # the same sentence in Item 9A while 9A says NOT effective still flags
    bad = ("Management concluded that our internal control over financial reporting was not effective as of December 31, 2020 because we identified "
           "a material weakness in controls over revenue that has not been remediated.")
    assert tp.detect_material_weakness(_v3_tenk(item9a=bad), "10-K")["detected"] is True
    # no Item 9A located: a body assertion is not suppressed
    assert tp.detect_material_weakness("We identified a material weakness in our internal control over financial reporting as of December 31, 2020 that has not been remediated.", "10-K")["detected"] is True
