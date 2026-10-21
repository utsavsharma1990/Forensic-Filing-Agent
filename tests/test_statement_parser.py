"""Tests for tools/statement_parser.py (CONTRACTS D4).

Three groups:

* mechanics tests on small SYNTHETIC tables (the numbers are invented on purpose and only exercise parsing rules:
  parentheses, dashes, column order, wrapped labels, scale, identity refusal);
* real-filing tests (``@pytest.mark.network``): Enron FY2000 10-K and WorldCom FY2001 10-K405 (no XBRL exists) and modern
  iXBRL filings compared with SEC ``companyfacts``.  The filings are downloaded once from sec.gov Archives into
  ``.cache/legacy`` (User-Agent from SEC_USER_AGENT or the spec placeholder, <= 8 req/s, backoff on 429/503) and the tests
  run offline from that cache afterwards; when neither cache nor network is available they are skipped, not failed;
* expected numbers in the real-filing tests were read from the printed statements of the downloaded filings, never typed
  from memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import statement_parser as sp  # noqa: E402
from tools.statement_parser import CANONICAL_ITEMS, extract_statements, flatten_values, parse_number  # noqa: E402

LEGACY_CACHE = ROOT / ".cache" / "legacy"
_PLACEHOLDER_UA = "forensic-filing-agent contact@example.com"
_last_request = [0.0]


# --------------------------------------------------------------------------------------
# local cached downloader (does NOT use tools.edgar_api)
# --------------------------------------------------------------------------------------

def _cache_path(url: str) -> Path:
    return LEGACY_CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + "_" + url.rstrip("/").split("/")[-1][:60])


def fetch(url: str) -> str:
    """Download ``url`` from sec.gov once, cache on disk, return decoded text (utf-8, cp1252 fallback).

    Skips the calling test when the document is neither cached nor downloadable.
    """
    LEGACY_CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    if not path.exists():
        try:
            import requests  # local import: only needed when the cache is cold
        except Exception:  # pragma: no cover
            pytest.skip("requests not installed and document not cached")
        try:  # corporate proxies: use the OS trust store when truststore is available
            import truststore  # type: ignore

            truststore.inject_into_ssl()
        except Exception:
            pass
        headers = {"User-Agent": os.environ.get("SEC_USER_AGENT") or _PLACEHOLDER_UA, "Accept-Encoding": "gzip, deflate"}
        data = None
        for attempt in range(6):
            wait = 0.15 - (time.time() - _last_request[0])  # <= ~6.7 req/s
            if wait > 0:
                time.sleep(wait)
            _last_request[0] = time.time()
            try:
                r = requests.get(url, headers=headers, timeout=60)
            except Exception as exc:
                if attempt == 5:
                    pytest.skip(f"network unavailable and {url} not cached: {exc}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                pytest.skip(f"{url} -> HTTP {r.status_code}")
            data = r.content
            break
        if data is None:
            pytest.skip(f"could not download {url}")
        path.write_bytes(data)
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


ENRON_URL = "https://www.sec.gov/Archives/edgar/data/1024401/000102440101500010/ene10-k.txt"
WCOM_URL = "https://www.sec.gov/Archives/edgar/data/723527/000100547702001226/d02-36461.txt"
AAPL_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/aapl-20200926.htm"
PG_URL = "https://www.sec.gov/Archives/edgar/data/80424/000008042420000053/pg-20200630.htm"
JNJ_URL = "https://www.sec.gov/Archives/edgar/data/200406/000020040621000008/jnj-20210103.htm"
KO08_URL = "https://www.sec.gov/Archives/edgar/data/21344/000104746909001875/a2190274z10-k.htm"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def val(res: dict, item: str, key: str = "values") -> float:
    return res[key][item]["value"]


# --------------------------------------------------------------------------------------
# 1. mechanics (synthetic numbers)
# --------------------------------------------------------------------------------------

def test_parse_number_variants() -> None:
    assert parse_number("1,234") == ("num", 1234.0)
    assert parse_number("$ 1,234") == ("num", 1234.0)
    assert parse_number("(1,234)") == ("num", -1234.0)
    assert parse_number("(1,234") == ("num", -1234.0)        # closing parenthesis lives in the next HTML cell
    assert parse_number("-56") == ("num", -56.0)
    assert parse_number("− 56") == ("num", -56.0)
    assert parse_number("12.5") == ("num", 12.5)
    assert parse_number("—") == ("dash", 0.0)
    assert parse_number("--") == ("dash", 0.0)
    assert parse_number("$")[0] == "skip"
    assert parse_number(")")[0] == "skip"
    assert parse_number("")[0] == "skip"
    assert parse_number("5%")[0] == "pct"
    assert parse_number("Total assets")[0] == "text"
    assert parse_number("31,")[0] == "text"                   # 'December 31,' must never become the number 31


def test_year_headers_and_january_rule() -> None:
    assert sp._year_of("2020") == 2020
    assert sp._year_of("Fiscal 2019") == 2019
    assert sp._year_of("September 26, 2020") == 2020
    assert sp._year_of("Dec. 31, 2000") == 2000
    assert sp._year_of("January 3, 2021") == 2020            # CONTRACTS D12: January period end -> prior fiscal year
    assert sp._year_of("Total assets") is None
    assert sp._year_of("1,234") is None
    assert sp._date_of("September 26, 2020") == "2020-09-26"


def test_detect_scale() -> None:
    assert sp.detect_scale("(In millions, except per share amounts)")[0] == 1e6
    assert sp.detect_scale("(Dollars in thousands)")[0] == 1e3
    assert sp.detect_scale("($ in billions)")[0] == 1e9
    assert sp.detect_scale("(Millions, except per-share amounts)")[0] == 1e6
    assert sp.detect_scale("(000's omitted)")[0] == 1e3
    assert sp.detect_scale("no caption here") is None
    # share counts printed in thousands must not override the amount scale
    cap = "BALANCE SHEETS (In millions, except number of shares which are reflected in thousands and par value)"
    assert sp.detect_scale(cap, last=True)[0] == 1e6
    assert sp.detect_scale(cap)[0] == 1e6


def test_split_numeric_tail() -> None:
    label, toks = sp._split_numeric_tail("  Total revenues                    $ 1,000    $   900   $(8)")
    assert label == "Total revenues"
    assert [parse_number(t)[1] for t in toks] == [1000.0, 900.0, -8.0]
    label, toks = sp._split_numeric_tail("Year ended December 31,")
    assert toks == [] and label == "Year ended December 31,"
    label, toks = sp._split_numeric_tail("  Impairment                          -        441        --")
    assert [parse_number(t)[1] for t in toks] == [0.0, 441.0, 0.0]
    label, toks = sp._split_numeric_tail("Series B preferred 29")                  # bare integer glued to a label is not a value
    assert toks == []


def _text_stmt(order_desc: bool) -> str:
    """Synthetic 3-statement text filing; order_desc=True prints the newest year first (Enron style)."""
    ys = ["2005", "2004"] if order_desc else ["2004", "2005"]
    pick = (lambda cur, prev: (cur, prev)) if order_desc else (lambda cur, prev: (prev, cur))

    def row(label: str, cur: str, prev: str) -> str:
        a, b = pick(cur, prev)
        return f"  {label:<46}{a:>12}{b:>12}"

    return "\n".join([
        "SYNTHETIC CO. CONSOLIDATED INCOME STATEMENT",
        "<TABLE>",
        "<CAPTION>",
        f"(In thousands, except per share amounts)         {ys[0]}        {ys[1]}",
        "<S>                                              <C>         <C>",
        row("Net sales", "$ 1,000", "$ 800"),
        row("Cost of goods sold", "600", "500"),
        row("Gross profit", "400", "300"),
        row("Selling, general and administrative", "150", "120"),
        row("Operating income", "250", "180"),
        row("Interest expense", "(20)", "(15)"),
        row("Provision for income taxes", "70", "50"),
        row("Net income", "160", "115"),
        "</TABLE>",
        "",
        "<TABLE>",
        f"CONSOLIDATED BALANCE SHEET (In thousands)    December 31,",
        f"                                                 {ys[0]}        {ys[1]}",
        row("Cash and cash equivalents", "$ 100", "$ 90"),
        row("Accounts receivable, net of allowance", "200", "150"),
        row("Total current assets", "400", "330"),
        row("Property, plant and equipment, net", "500", "450"),
        row("Total assets", "$ 900", "$ 780"),
        row("Total current liabilities", "250", "200"),
        row("Long-term debt", "150", "140"),
        row("Total liabilities", "400", "340"),
        row("Retained earnings", "300", "250"),
        row("Total stockholders' equity", "500", "440"),
        row("Total liabilities and stockholders' equity", "$ 900", "$ 780"),
        "</TABLE>",
        "",
        "<TABLE>",
        f"CONSOLIDATED STATEMENT OF CASH FLOWS (In thousands)",
        f"                                                 {ys[0]}        {ys[1]}",
        row("Cash flows from operating activities", "", ""),
        row("Net income", "160", "115"),
        row("Depreciation and amortization", "55", "50"),
        row("Net cash provided by operating activities", "230", "190"),
        row("Net cash used in investing activities", "(90)", "(80)"),
        row("Net cash provided by financing activities", "(40)", "(30)"),
        "</TABLE>",
    ])


@pytest.mark.parametrize("newest_first", [True, False])
def test_synthetic_text_filing_column_order(newest_first: bool) -> None:
    res = extract_statements(_text_stmt(newest_first), 2005, "10-K")
    v, p = res["values"], res["prior_values"]
    assert v["Revenue"]["value"] == 1_000_000.0 and p["Revenue"]["value"] == 800_000.0     # thousands applied
    assert v["COGS"]["value"] == 600_000.0
    assert v["InterestExpense"]["value"] == 20_000.0                                       # magnitude of a parenthesised cost
    assert v["TotalAssets"]["value"] == 900_000.0 and p["TotalAssets"]["value"] == 780_000.0
    assert v["TotalLiabilities"]["value"] == 400_000.0 and not v["TotalLiabilities"]["derived"]
    assert v["StockholdersEquity"]["value"] == 500_000.0
    assert v["OperatingCashFlow"]["value"] == 230_000.0
    assert v["Depreciation"]["value"] == 55_000.0
    assert v["NetIncome"]["tag"].lower() == "net income"
    assert v["Revenue"]["source"] == "statement-table" and v["Revenue"]["unit"] == "USD"
    assert p["Revenue"]["comparative"] is True and v["Revenue"]["comparative"] is False
    assert res["checks"]["balance_identity"] is True
    assert res["checks"]["gross_profit_identity"] is True
    assert res["checks"]["net_income_cross_statement"] is True
    assert "CurrentDebt" in res["missing"]


def test_synthetic_wrapped_labels_and_unlabeled_totals() -> None:
    doc = "\n".join([
        "<TABLE>",
        "BALANCE SHEET (In millions)",
        "                                                  2002        2001",
        "ASSETS",
        "Current assets:",
        "  Cash and cash equivalents                      $ 10        $ 20",
        "  Accounts receivable, net of allowance for",
        "   doubtful accounts of $1 and $2,                     30          40",
        "     Total current assets                           40          60",
        "  Property and equipment:",
        "    Equipment                                       100         90",
        "    Accumulated depreciation                        (30)       (20)",
        "                                                     70          70",
        "                                                    ----        ----",
        "                                                  $ 110       $ 130",
        "LIABILITIES AND SHAREHOLDERS' EQUITY",
        "Current liabilities:",
        "  Short-term debt                                   5           6",
        "  Total current liabilities                        25          30",
        "Long-term debt                                     35          45",
        "Minority interests                                  5           5",
        "Shareholders' equity:",
        "  Retained earnings                                30          40",
        "  Total shareholders' equity                       45          50",
        "                                                $ 110       $ 130",
        "</TABLE>",
    ])
    res = extract_statements(doc, 2002, "10-K")
    v = res["values"]
    assert v["NetReceivables"]["value"] == 30e6                                # wrapped label re-joined
    assert "doubtful accounts" in v["NetReceivables"]["tag"]
    assert v["TotalAssets"]["value"] == 110e6 and "unlabeled" in v["TotalAssets"]["tag"]
    assert v["PPE"]["value"] == 70e6 and "unlabeled" in v["PPE"]["tag"]
    assert v["CurrentDebt"]["value"] == 5e6
    assert v["LongTermDebt"]["value"] == 35e6
    tl = v["TotalLiabilities"]
    assert tl["derived"] and tl["tag"].startswith("derived:") and tl["value"] == (110 - 45 - 5) * 1e6
    assert res["checks"]["balance_identity"] is True


def test_synthetic_html_cells_and_dates() -> None:
    html = """
    <html><body><p>CONSOLIDATED STATEMENTS OF OPERATIONS (In millions, except per share amounts)</p>
    <table>
      <tr><td></td><td colspan="2">Years ended</td></tr>
      <tr><td></td><td>September 26, 2020</td><td></td><td>September 28, 2019</td></tr>
      <tr><td>Total net sales</td><td>$</td><td>1,000</td><td></td><td>$</td><td>900</td></tr>
      <tr><td>Total cost of sales</td><td></td><td>(600</td><td>)</td><td></td><td>500</td></tr>
      <tr><td>Gross margin</td><td></td><td>400</td><td></td><td></td><td>400</td></tr>
      <tr><td>Operating income</td><td></td><td>250</td><td></td><td></td><td>&#8212;</td></tr>
      <tr><td>Net income</td><td>$</td><td>160</td><td></td><td>$</td><td>115</td></tr>
      <tr><td>Gross margin %</td><td></td><td>40</td><td>%</td><td></td><td>44</td><td>%</td></tr>
    </table></body></html>"""
    res = extract_statements(html, 2020, "10-K", period_end="2020-09-26", filed="2020-10-30", accn="0000000000-20-000001")
    v, p = res["values"], res["prior_values"]
    assert v["Revenue"]["value"] == 1000e6 and p["Revenue"]["value"] == 900e6
    assert v["COGS"]["value"] == 600e6                                         # cost printed as (600 -> expense magnitude
    assert p["OperatingIncome"]["value"] == 0.0                                # em-dash is zero
    assert v["Revenue"]["end"] == "2020-09-26" and v["Revenue"]["filed"] == "2020-10-30" and v["Revenue"]["accn"].endswith("001")
    assert res["tables"]["income_statement"]["years"] == [2020, 2019]
    # percentage row 'Gross margin %' must not be taken as GrossProfit: the real row wins
    assert v["GrossProfit"]["value"] == 400e6 and v["GrossProfit"]["tag"] == "Gross margin"


def test_identity_failure_withholds_balance_sheet() -> None:
    bad = re.sub(r"(  Total assets\s+\$ )900", r"\g<1>905", _text_stmt(True), count=1)
    assert "$ 905" in bad
    res = extract_statements(bad, 2005, "10-K")
    assert res["checks"]["balance_identity"] is False
    for item in ("TotalAssets", "StockholdersEquity", "CurrentAssets", "RetainedEarnings"):
        assert item not in res["values"]
        assert res["missing"][item].startswith("withheld: balance-sheet identity")
    # the income statement is still returned
    assert res["values"]["Revenue"]["value"] == 1_000_000.0
    assert any("identity check failed" in w for w in res["warnings"])


def test_cogs_is_never_guessed_from_total_costs() -> None:
    doc = "\n".join([
        "<TABLE>", "INCOME STATEMENT (In millions)", "                         2002      2001",
        "Revenues                 1,000       900",
        "Costs and Expenses",
        "  Operating expenses       300       250",
        "  Other expenses           200       150",
        "    Total costs and expenses  500     400",
        "Operating income           500       500",
        "Net income                 300       280", "</TABLE>"])
    res = extract_statements(doc, 2002, "10-K")
    assert "COGS" not in res["values"] and "COGS" in res["missing"]
    assert "GrossProfit" not in res["values"]
    assert res["values"]["Revenue"]["value"] == 1000e6


def test_multiple_cost_lines_without_total_are_ambiguous() -> None:
    doc = "\n".join([
        "<TABLE>", "INCOME STATEMENT (In millions)", "                         2002      2001",
        "Revenues                 1,000       900",
        "  Cost of products sold    300       250",
        "  Cost of services         200       150",
        "Operating income           500       500",
        "Net income                 300       280", "</TABLE>"])
    res = extract_statements(doc, 2002, "10-K")
    assert "COGS" not in res["values"]
    assert "component cost-of lines" in res["missing"]["COGS"]


def test_unlabeled_year_column_and_missing_fiscal_year() -> None:
    res = extract_statements(_text_stmt(True), 1990, "10-K")
    assert res["values"] == {}
    assert all(isinstance(v, str) and v for v in res["missing"].values())
    assert set(res["missing"]) >= set(CANONICAL_ITEMS)


@pytest.mark.parametrize("junk", ["", "   ", "plain prose with no tables at all. " * 50, "<html><body><table></table></body></html>",
                                  "<TABLE>\n</TABLE>", "\x00\x01\x02", "<tr><td>x</td></tr>"])
def test_garbage_input_never_raises(junk: str) -> None:
    res = extract_statements(junk, 2000, "10-K")
    assert res["values"] == {}
    assert set(res["missing"]) >= set(CANONICAL_ITEMS)
    assert "warnings" in res and "checks" in res


def test_flatten_values_roundtrip() -> None:
    res = extract_statements(_text_stmt(True), 2005, "10-K")
    flat = flatten_values(res["values"])
    assert set(flat) == set(CANONICAL_ITEMS)
    assert flat["Revenue"] == 1_000_000.0 and flat["CurrentDebt"] is None


# --------------------------------------------------------------------------------------
# 2. real legacy filings (no XBRL exists)
# --------------------------------------------------------------------------------------

def _printed_number_in_text(res_item: dict, text: str) -> bool:
    """Provenance: the source row label and the printed number both occur in the filing text."""
    if res_item["derived"] or res_item["tag"].startswith("("):
        return True
    scale = res_item["table"].get("scale") or 1.0
    shown = abs(res_item["value"]) / scale
    num = f"{shown:,.0f}"
    first_words = re.escape(" ".join(res_item["tag"].split()[:2]))
    return re.search(first_words, text, re.I) is not None and num in text


@pytest.mark.network
def test_enron_fy2000_matches_printed_statements() -> None:
    text = fetch(ENRON_URL)
    res = extract_statements(text, 2000, "10-K")
    v, p = res["values"], res["prior_values"]
    M = 1e6
    # FY2000 / FY1999 figures as printed in the Consolidated Income Statement, Balance Sheet and Cash Flow statement
    expect_fy = {"Revenue": 100_789, "COGS": 94_517, "NetIncome": 979, "OperatingIncome": 1_953, "IncomeTaxExpense": 434,
                 "InterestExpense": 838, "Depreciation": 855, "OperatingCashFlow": 4_779, "TotalAssets": 65_503,
                 "CurrentAssets": 30_381, "CurrentLiabilities": 28_406, "NetReceivables": 10_396, "PPE": 11_743,
                 "LongTermDebt": 8_550, "CurrentDebt": 1_679, "RetainedEarnings": 3_226, "StockholdersEquity": 11_470,
                 "CashAndEquivalents": 1_374}
    expect_prior = {"Revenue": 40_112, "COGS": 34_761, "NetIncome": 893, "OperatingIncome": 802, "OperatingCashFlow": 1_228,
                    "TotalAssets": 33_381, "CurrentAssets": 7_255, "StockholdersEquity": 9_570, "RetainedEarnings": 2_698,
                    "LongTermDebt": 7_151, "CashAndEquivalents": 288}
    for k, e in expect_fy.items():
        assert v[k]["value"] == e * M, k
    for k, e in expect_prior.items():
        assert p[k]["value"] == e * M, k
    # Enron prints no SG&A line and no total-liabilities line: SGA stays missing, TL is derived from the balance sheet
    assert "SGA" not in v and "SGA" in res["missing"]
    assert v["TotalLiabilities"]["derived"]
    assert v["TotalLiabilities"]["value"] == (28_406 + 8_550 + 13_759) * M          # CL + LTD + deferred credits as printed
    assert p["TotalLiabilities"]["value"] == (6_759 + 7_151 + 6_471) * M
    assert v["COGS"]["tag"].startswith("Cost of gas, electricity, metals and other products")   # wrapped label re-joined
    assert v["Revenue"]["table"]["scale_source"].lower().startswith("table caption")
    assert res["checks"] == {"balance_identity": True, "current_assets_le_total": True, "current_liabilities_le_total": True,
                             "gross_profit_identity": None, "net_income_cross_statement": True}
    for k, fv in v.items():
        assert _printed_number_in_text(fv, text), k


@pytest.mark.network
def test_worldcom_fy2001_matches_printed_statements() -> None:
    text = fetch(WCOM_URL)
    res = extract_statements(text, 2001, "10-K405")
    v, p = res["values"], res["prior_values"]
    M = 1e6
    expect_fy = {"Revenue": 35_179, "COGS": 14_739, "SGA": 11_046, "OperatingIncome": 3_514, "InterestExpense": 1_533,
                 "IncomeTaxExpense": 927, "NetIncome": 1_501, "Depreciation": 5_880, "OperatingCashFlow": 7_994,
                 "TotalAssets": 103_914, "CurrentAssets": 9_205, "CurrentLiabilities": 9_210, "NetReceivables": 5_308,
                 "PPE": 38_809, "LongTermDebt": 30_038, "CurrentDebt": 172, "RetainedEarnings": 4_400,
                 "StockholdersEquity": 57_930, "CashAndEquivalents": 1_416}
    expect_prior = {"Revenue": 39_090, "COGS": 15_462, "SGA": 10_597, "NetIncome": 4_153, "OperatingCashFlow": 7_666,
                    "Depreciation": 4_878, "TotalAssets": 98_903, "CurrentLiabilities": 17_673, "PPE": 37_423,
                    "LongTermDebt": 17_696, "CurrentDebt": 7_200, "StockholdersEquity": 55_409}
    for k, e in expect_fy.items():
        assert v[k]["value"] == e * M, k
    for k, e in expect_prior.items():
        assert p[k]["value"] == e * M, k
    # WorldCom prints its grand totals without a label: they must be taken by position and say so
    assert "unlabeled" in v["TotalAssets"]["tag"] and "unlabeled" in v["PPE"]["tag"]
    # tracking-stock (WorldCom group / MCI group) copies of the statements must not be picked
    assert v["OperatingCashFlow"]["value"] != 6_605 * M
    # total liabilities derived = current + long-term liabilities as printed (9,210 + 34,680)
    assert v["TotalLiabilities"]["value"] == (9_210 + 34_680) * M
    assert res["checks"]["balance_identity"] is True and res["checks"]["net_income_cross_statement"] is True
    assert res["values"]["InterestExpense"]["value"] > 0                           # printed (1,533) in parentheses -> magnitude
    for k, fv in v.items():
        assert _printed_number_in_text(fv, text), k


@pytest.mark.network
def test_real_filing_with_perturbed_total_is_withheld() -> None:
    text = fetch(ENRON_URL)
    needle = "Total Assets                              $65,503     $33,381"
    assert needle in text
    bad = text.replace(needle, "Total Assets                              $65,999     $33,381", 1)
    res = extract_statements(bad, 2000, "10-K")
    assert res["checks"]["balance_identity"] is False
    assert "TotalAssets" not in res["values"] and "StockholdersEquity" not in res["values"]
    assert res["missing"]["TotalAssets"].startswith("withheld")
    assert res["values"]["Revenue"]["value"] == 100_789 * 1e6                      # other statements unaffected
    # prior-year column is untouched and still validated
    assert res["prior_values"]["TotalAssets"]["value"] == 33_381 * 1e6


# --------------------------------------------------------------------------------------
# 3. modern iXBRL filings validated against SEC companyfacts
# --------------------------------------------------------------------------------------

_XBRL_TAGS = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "COGS": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "GrossProfit": ["GrossProfit"], "SGA": ["SellingGeneralAndAdministrativeExpense"],
    "NetIncome": ["NetIncomeLoss", "ProfitLoss"], "OperatingIncome": ["OperatingIncomeLoss"],
    "InterestExpense": ["InterestExpense", "InterestExpenseDebt"], "IncomeTaxExpense": ["IncomeTaxExpenseBenefit"],
    "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    "TotalAssets": ["Assets"], "CurrentAssets": ["AssetsCurrent"], "CurrentLiabilities": ["LiabilitiesCurrent"],
    "TotalLiabilities": ["Liabilities"], "NetReceivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "PPE": ["PropertyPlantAndEquipmentNet"], "LongTermDebt": ["LongTermDebtNoncurrent"],
    "CurrentDebt": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"],
    "RetainedEarnings": ["RetainedEarningsAccumulatedDeficit"],
    "StockholdersEquity": ["StockholdersEquity"], "CashAndEquivalents": ["CashAndCashEquivalentsAtCarryingValue"],
}
_FLOW = {"Revenue", "COGS", "GrossProfit", "SGA", "NetIncome", "OperatingIncome", "InterestExpense", "IncomeTaxExpense",
         "OperatingCashFlow", "Depreciation"}


def _xbrl_candidates(facts: dict, item: str, end: str) -> list[float]:
    import datetime as dt

    out: list[float] = []
    for tag in _XBRL_TAGS[item]:
        node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
        if not node:
            continue
        for a in node.get("units", {}).get("USD", []):
            if a["end"] != end or not str(a.get("form", "")).startswith("10-K"):
                continue
            if item in _FLOW:
                try:
                    days = (dt.date.fromisoformat(a["end"]) - dt.date.fromisoformat(a["start"])).days
                except Exception:
                    continue
                if not 350 <= days <= 380:
                    continue
            out.append(float(a["val"]))
    return out


def _agreement(res: dict, facts: dict, end: str) -> tuple[int, int, list[str]]:
    tested = agreed = 0
    bad: list[str] = []
    for item, fv in res["values"].items():
        cands = _xbrl_candidates(facts, item, end)
        if not cands:
            continue
        tested += 1
        if any(abs(fv["value"] - c) <= 0.005 * max(abs(c), 1.0) for c in cands):
            agreed += 1
        else:
            bad.append(f"{item}: parsed {fv['value']:,.0f} vs xbrl {cands}")
    return tested, agreed, bad


@pytest.mark.network
@pytest.mark.parametrize("name,url,cik,fy,end,min_items", [
    ("AAPL FY2020", AAPL_URL, 320193, 2020, "2020-09-26", 17),
    ("PG FY2020", PG_URL, 80424, 2020, "2020-06-30", 17),
    ("JNJ FY2020 (52/53-week, ends 2021-01-03)", JNJ_URL, 200406, 2020, "2021-01-03", 17),
])
def test_modern_filings_agree_with_xbrl(name: str, url: str, cik: int, fy: int, end: str, min_items: int) -> None:
    html = fetch(url)
    facts = json.loads(fetch(FACTS_URL.format(cik=cik)))
    res = extract_statements(html, fy, "10-K", period_end=end)
    assert len(res["values"]) >= min_items, (name, sorted(res["missing"].items()))
    assert res["checks"]["balance_identity"] is True
    tested, agreed, bad = _agreement(res, facts, end)
    assert tested >= 15
    # only definitional differences are tolerated (e.g. commercial paper + current term debt vs the LongTermDebtCurrent tag)
    assert agreed / tested >= 0.9, (name, bad)
    # prior-year comparatives come from the same table
    assert len(res["prior_values"]) >= min_items - 2
    assert all(fv["comparative"] for fv in res["prior_values"].values())


@pytest.mark.network
def test_pre_xbrl_2008_html_filing_generalises() -> None:
    """Coca-Cola FY2008 10-K (filed 2009, plain HTML, no XBRL): identities hold and income/cash-flow items agree with XBRL."""
    html = fetch(KO08_URL)
    facts = json.loads(fetch(FACTS_URL.format(cik=21344)))
    res = extract_statements(html, 2008, "10-K", period_end="2008-12-31")
    assert res["checks"]["balance_identity"] is True and res["checks"]["net_income_cross_statement"] is True
    for item in ("Revenue", "COGS", "NetIncome", "OperatingIncome", "OperatingCashFlow", "TotalAssets", "StockholdersEquity"):
        assert item in res["values"], item
    flow_only = {"values": {k: v for k, v in res["values"].items() if k in _FLOW or k in ("TotalAssets", "StockholdersEquity", "CurrentAssets")}}
    tested, agreed, bad = _agreement(flow_only, facts, "2008-12-31")
    assert tested >= 8 and agreed == tested, bad


@pytest.mark.network
def test_statements_in_exhibit_13_are_reported_missing_not_invented() -> None:
    """A 10-K whose financial statements live in another exhibit has no statement tables: everything is 'missing'."""
    jnj08 = "https://www.sec.gov/Archives/edgar/data/200406/000095012309003187/y74152e10vk.htm"
    res = extract_statements(fetch(jnj08), 2008, "10-K")
    assert res["values"] == {}
    assert all(isinstance(r, str) and r for r in res["missing"].values())
    assert any("no qualifying table" in w for w in res["warnings"])


# --------------------------------------------------------------------------------------
# v3: balance-sheet evidence for "no long-term debt" and the non-current-line label qualifier
# --------------------------------------------------------------------------------------

def _bs_html(noncurrent_rows: list[tuple[str, int, int]], total_liabilities: tuple[int, int] | None, cur_liab=(40, 35),
             equity=(None, None)) -> str:
    """Synthetic balance sheet (in thousands). Assets 200/170; equity is whatever makes the identity hold."""
    nc = "".join(f"<tr><td>{lab}</td><td>{a}</td><td>{b}</td></tr>" for lab, a, b in noncurrent_rows)
    ncs = (sum(r[1] for r in noncurrent_rows), sum(r[2] for r in noncurrent_rows))
    tl = total_liabilities
    eq = (200 - cur_liab[0] - ncs[0], 170 - cur_liab[1] - ncs[1])
    tl_row = f"<tr><td>Total liabilities</td><td>{tl[0]}</td><td>{tl[1]}</td></tr>" if tl else ""
    return f"""<html><body><p>CONSOLIDATED BALANCE SHEETS (in thousands)</p><table>
      <tr><td></td><td>December 31, 2019</td><td>December 31, 2018</td></tr>
      <tr><td>Cash and cash equivalents</td><td>50</td><td>40</td></tr>
      <tr><td>Accounts receivable, net</td><td>60</td><td>50</td></tr>
      <tr><td>Total current assets</td><td>110</td><td>90</td></tr>
      <tr><td>Property and equipment, net</td><td>90</td><td>80</td></tr>
      <tr><td>Total assets</td><td>200</td><td>170</td></tr>
      <tr><td>Accounts payable</td><td>25</td><td>20</td></tr>
      <tr><td>Accrued liabilities</td><td>15</td><td>15</td></tr>
      <tr><td>Total current liabilities</td><td>{cur_liab[0]}</td><td>{cur_liab[1]}</td></tr>
      {nc}
      {tl_row}
      <tr><td>Stockholders' equity</td><td></td><td></td></tr>
      <tr><td>Retained earnings</td><td>{eq[0] - 10}</td><td>{eq[1] - 10}</td></tr>
      <tr><td>Common stock</td><td>10</td><td>10</td></tr>
      <tr><td>Total stockholders' equity</td><td>{eq[0]}</td><td>{eq[1]}</td></tr>
      <tr><td>Total liabilities and stockholders' equity</td><td>200</td><td>170</td></tr>
    </table></body></html>"""


def test_no_debt_evidence_when_only_deferred_and_other_rows_follow_current_liabilities() -> None:
    res = extract_statements(_bs_html([("Deferred income taxes", 6, 5), ("Other long-term liabilities", 4, 3)], (50, 43)), 2019)
    ev = res["no_debt_evidence"][2019]
    assert ev["ok"] is True and ev["rows"] == ["Deferred income taxes", "Other long-term liabilities"] and not ev["tl_derived"]
    assert res["no_debt_evidence"][2018]["ok"] is True
    assert "LongTermDebt" not in res["values"]                       # evidence is evidence, not a value


def test_no_debt_evidence_when_total_liabilities_is_not_printed_uses_assets_less_equity() -> None:
    res = extract_statements(_bs_html([("Other long-term liabilities", 10, 8)], None), 2019)
    ev = res["no_debt_evidence"][2019]
    assert ev["ok"] is True and ev["tl_derived"] is True and ev["total_liabilities"] == 50_000.0


def test_no_debt_evidence_refused_for_debt_like_row_or_unreconciled_rows() -> None:
    res = extract_statements(_bs_html([("Convertible notes payable", 30, 30), ("Other long-term liabilities", 4, 3)], (74, 68)), 2019)
    assert res["no_debt_evidence"][2019]["ok"] is False and "debt-like" in res["no_debt_evidence"][2019]["reason"]
    # a finance-lease line counts as borrowed money
    res = extract_statements(_bs_html([("Finance lease obligations, long-term", 5, 5)], (45, 40)), 2019)
    assert res["no_debt_evidence"][2019]["ok"] is False
    # rows do not add up to total liabilities - current liabilities (a hidden non-current item): refuse
    res = extract_statements(_bs_html([("Other long-term liabilities", 4, 3)], (50, 43)), 2019)
    assert res["no_debt_evidence"][2019]["ok"] is False and "do not add up" in res["no_debt_evidence"][2019]["reason"]
    # operating-lease liabilities are not borrowed money
    res = extract_statements(_bs_html([("Operating lease liabilities, non-current", 6, 5)], (46, 40)), 2019)
    assert res["no_debt_evidence"][2019]["ok"] is True


def test_unrecognised_noncurrent_row_blocks_the_evidence() -> None:
    res = extract_statements(_bs_html([("Widgets owed to partners", 6, 5)], (46, 40)), 2019)
    assert res["no_debt_evidence"][2019]["ok"] is False and "not recognisable" in res["no_debt_evidence"][2019]["reason"]


def test_long_term_debt_label_with_current_maturities_qualifier_is_the_noncurrent_line() -> None:
    for label in ("Long-term debt, excluding current maturities", "Long-term debt, net of current portion",
                  "Long-term debt, less current portion"):
        res = extract_statements(_bs_html([(label, 30, 30), ("Other long-term liabilities", 4, 3)], (74, 68)), 2019)
        assert res["values"]["LongTermDebt"]["value"] == 30_000.0, label
        assert res["values"]["LongTermDebt"]["tag"] == label
    # the current portion row itself is still never the non-current line
    res = extract_statements(_bs_html([("Current portion of long-term debt", 30, 30)], (70, 65)), 2019)
    assert "LongTermDebt" not in res["values"]
