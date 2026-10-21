"""Evaluation case registry: 6 known-fraud filings and 6 "clean" filings.

Every metadata field below was verified in this build against primary sources
(SEC EDGAR ``data.sec.gov`` submissions + companyfacts JSON, fetched with the
project User-Agent) and press/regulator pages (URLs in each case's ``sources``).
Full evidence and every correction to the original spec are in
``docs/case_research.md``.

Selection rules and honest caveats
----------------------------------
* The 12 cases come from the project spec (SPEC.md) and were NOT swapped or
  dropped.  Where the spec was wrong (CIKs for Luckin, Lordstown, Virgin
  Galactic; the "collapsed" year for Virgin Galactic and Lordstown) the value
  is corrected and ``spec_*`` keeps the original (CONTRACTS D11).
* ``ground_truth`` = 1 means the company was later publicly accused (and, for
  five of six, officially sanctioned or bankrupt) of misleading investors.
  Only Enron, WorldCom and Luckin are *financial-statement* frauds, which is
  what Beneish/Altman-style analytics target.  Nikola, Lordstown and Virgin
  Galactic are *disclosure/claims* cases (``fraud_nature``); the financial
  statements themselves were not alleged to be manipulated, so a low score
  on them is not necessarily a detector failure.  Virgin Galactic's fraud
  label is WEAK: a securities class action (settled, no admission; no SEC
  accounting action was found) alleging misleading safety disclosures.
* Look-ahead: ``pre_revelation_valid`` is computed as
  ``analysis_filing_date < public_revelation_date``.  Luckin, Nikola,
  Lordstown and Virgin Galactic FAIL that test for the spec's analysis year.
  They are kept (never silently dropped) and ``strict_alt`` records the last
  annual filing filed before the revelation (or ``None`` when no annual
  report existed).  For Nikola and Lordstown the strict_alt filing is a SPAC
  shell 10-K (pre-merger blank-cheque company), not the operating business.
* ``as_of`` for a spec run = ``analysis_filing_date`` (information set up to
  and including that filing).  ``strict_as_of`` = the strict_alt filing date.
* Survivorship / selection bias: the fraud cases are famous, well-documented
  failures chosen with hindsight; the clean cases are six surviving US
  mega-caps (NOT size/industry matched, despite the UI wording "matched").
  Clean means "no known accounting fraud or restatement" only.  MMM and JNJ
  carried very large litigation disclosures; BRK-B is an insurer/conglomerate
  to which Beneish/Altman (built for industrial firms) apply poorly.
  Sample size n=12 gives wide confidence intervals.
* ``has_xbrl`` = the analysis filing itself carries XBRL facts in
  data.sec.gov companyfacts.  Enron FY2000 and WorldCom FY2001 are pre-XBRL.

Dates are ISO ``YYYY-MM-DD`` strings (CONTRACTS D13); CIKs are 10-digit strings.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "FRAUD_CASES",
    "CLEAN_CASES",
    "ALL_CASES",
    "get_case",
    "cases_as_dataframe",
]

_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _alt(fiscal_year: int, filing_date: str, form: str, accession: str, note: str = "") -> dict[str, Any]:
    """Build a ``strict_alt`` record (last annual filing before the revelation)."""
    return {
        "fiscal_year": fiscal_year,
        "filing_date": filing_date,
        "form": form,
        "accession": accession,
        "note": note,
    }


def _valid(filing_date: str, revelation_date: str | None) -> bool:
    """pre_revelation_valid = analysis_filing_date < public_revelation_date (ISO strings)."""
    if revelation_date is None:
        return True
    return filing_date < revelation_date


def _fraud(**kw: Any) -> dict[str, Any]:
    """Assemble a fraud case, deriving ``pre_revelation_valid`` and ``as_of``."""
    kw["ground_truth"] = 1
    kw["label"] = "Fraud"
    kw["pre_revelation_valid"] = _valid(kw["analysis_filing_date"], kw["public_revelation_date"])
    kw["as_of"] = kw["analysis_filing_date"]
    alt = kw.get("strict_alt")
    kw["strict_as_of"] = alt["filing_date"] if alt else None
    kw["corrected"] = bool(kw.get("correction_reason"))
    kw["correction_reason"] = kw.get("correction_reason") or ""
    kw.setdefault("early_warning", "")
    kw["sources"] = [
        _SUBMISSIONS.format(cik=kw["cik"]),
        *( [_COMPANYFACTS.format(cik=kw["cik"])] if kw["has_xbrl"] else [] ),
        *kw["sources"],
    ]
    return kw


def _clean(**kw: Any) -> dict[str, Any]:
    """Assemble a clean case (no revelation/collapse; label 'Clean')."""
    kw.update(
        ground_truth=0,
        label="Clean",
        collapsed_year=None,
        collapse_date=None,
        public_revelation_date=None,
        pre_revelation_valid=True,
        fraud_type="",
        fraud_nature="none",
        label_confidence="no known fraud/restatement (not a proof of cleanliness)",
        strict_alt=None,
        strict_as_of=None,
        corrected=bool(kw.get("correction_reason")),
        spec_cik=kw["cik"],
        spec_analysis_year=2020,
        early_warning="",
    )
    kw["correction_reason"] = kw.get("correction_reason") or ""
    kw["as_of"] = kw["analysis_filing_date"]
    kw["sources"] = [
        _SUBMISSIONS.format(cik=kw["cik"]),
        _COMPANYFACTS.format(cik=kw["cik"]),
        *kw["sources"],
    ]
    return kw


FRAUD_CASES: list[dict[str, Any]] = [
    _fraud(
        ticker="ENRNQ",
        company_name="Enron Corp",
        edgar_name="ENRON CORP/OR/",
        former_names=["ENRON OREGON CORP"],
        sic="6200",
        cik="0001024401",
        spec_cik="0001024401",
        correction_reason="",
        spec_analysis_year=2000,
        analysis_year=2000,
        spec_collapsed_year=2001,
        collapsed_year=2001,
        collapse_date="2001-12-02",
        collapse_event="Chapter 11 bankruptcy filing",
        public_revelation_date="2001-10-16",
        revelation_event=(
            "Q3-2001 earnings release with ~$1B of charges and a $618M quarterly loss; followed by "
            "the SEC inquiry (Oct 2001) and the 2001-11-08 restatement of 1997-2000 results "
            "(income overstated by $586M)."
        ),
        early_warning=(
            "2001-03-05 Fortune 'Is Enron Overpriced?' questioned how Enron made money (before the "
            "FY2000 10-K, but raised no allegation of fraud); 2001-08-14 Skilling resigned."
        ),
        fraud_type="Revenue inflation, SPE concealment",
        fraud_nature="financial_statement",
        label_confidence="established (restatement, bankruptcy, criminal convictions)",
        form_type="10-K",
        accession="0001024401-01-500010",
        analysis_filing_date="2001-04-02",
        report_date="2000-12-31",
        has_xbrl=False,
        xbrl_note="Pre-XBRL: companyfacts 404. Needs tools/statement_parser.py (D4).",
        strict_alt=_alt(2000, "2001-04-02", "10-K", "0001024401-01-500010", "same as analysis filing"),
        validity_note=(
            "Valid: FY2000 10-K filed 2001-04-02, 6.5 months before the 2001-10-16 revelation. "
            "NOTE: the commonly assumed CIK 72859 is the predecessor registrant (Enron Corp, "
            "annual reports only through FY1996 on EDGAR); FY1997-FY2000 10-Ks are filed under "
            "CIK 1024401 (ENRON CORP/OR/), so the spec CIK is correct."
        ),
        sources=[
            "https://fortune.com/article/is-enron-overpriced-fortune-2001/",
            "https://kvia.com/news/us-world/2021/04/25/enron-fast-facts/",
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1024401&type=10-K",
        ],
    ),
    _fraud(
        ticker="WCOM",
        company_name="WorldCom Inc",
        edgar_name="MCI INC",
        former_names=["WORLDCOM INC", "WORLDCOM INC/GA//", "MCI WORLDCOM INC", "WORLDCOM INC /GA/",
                      "WORLDCOM INC /MS/", "LDDS COMMUNICATIONS INC /GA/"],
        sic="4813",
        cik="0000723527",
        spec_cik="0000723527",
        correction_reason="",
        spec_analysis_year=2001,
        analysis_year=2001,
        spec_collapsed_year=2002,
        collapsed_year=2002,
        collapse_date="2002-07-21",
        collapse_event="Chapter 11 bankruptcy filing (largest US bankruptcy to that date)",
        public_revelation_date="2002-06-25",
        revelation_event=(
            "WorldCom announced it would restate 2001 and Q1-2002: $3.055B (2001) and $797M (Q1 2002) "
            "of line costs improperly transferred to capital accounts; later restatements raised the "
            "total (Aug 2002: a further $3.8B)."
        ),
        early_warning=(
            "2002-03-11 WorldCom disclosed a confidential SEC request for documents (accounting "
            "policies, loans to executives) - two days BEFORE the FY2001 10-K405 was filed "
            "(2002-03-13). It was an inquiry, not a fraud disclosure."
        ),
        fraud_type="Capitalized expenses as assets",
        fraud_nature="financial_statement",
        label_confidence="established (restatement, bankruptcy, convictions)",
        form_type="10-K405",
        accession="0001005477-02-001226",
        analysis_filing_date="2002-03-13",
        report_date="2001-12-31",
        has_xbrl=False,
        xbrl_note="Pre-XBRL: companyfacts 404. Needs tools/statement_parser.py (D4).",
        strict_alt=_alt(2001, "2002-03-13", "10-K405", "0001005477-02-001226", "same as analysis filing"),
        validity_note=(
            "Valid against the fraud revelation (filed 3 months before 2002-06-25). Caveat: a public "
            "SEC document request (2002-03-11) preceded the filing by two days; a stricter "
            "'first public red flag' cut-off would instead use the FY2000 10-K405 "
            "(0000912057-01-505916, filed 2001-03-30). The 10-K405/A filed 2001-04-26 amends FY2000. "
            "Spec CIK 723527 verified (EDGAR name now 'MCI INC'). Form type is 10-K405."
        ),
        sources=[
            "https://www.verizon.com/about/node/867723",
            "https://www.verizon.com/about/node/867811",
            "https://money.cnn.com/2002/07/19/news/worldcom_bankruptcy/",
            "https://www.sec.gov/Archives/edgar/data/0000723527/000091205702025338/a2083227zex-99_1.txt",
        ],
    ),
    _fraud(
        ticker="LK",
        company_name="Luckin Coffee Inc.",
        edgar_name="Luckin Coffee Inc.",
        former_names=[],
        sic="5810",
        cik="0001767582",
        spec_cik="0001767380",
        correction_reason=(
            "Spec CIK 0001767380 does not exist in EDGAR (data.sec.gov submissions returns 404). "
            "Luckin Coffee Inc. is CIK 1767582 (name, ticker LK/LKNCY and 20-F filings confirmed)."
        ),
        spec_analysis_year=2019,
        analysis_year=2019,
        spec_collapsed_year=2020,
        collapsed_year=2020,
        collapse_date="2020-07-13",
        collapse_event=(
            "Nasdaq delisting effective 2020-07-13 (company withdrew its hearing request 2020-06-25); "
            "SEC charged the company 2020-12-16 ($180M penalty)."
        ),
        public_revelation_date="2020-01-31",
        revelation_event=(
            "Muddy Waters published an anonymous 89-page short report alleging inflated store sales; "
            "on 2020-04-02 Luckin itself disclosed ~RMB2.2B of fabricated 2019 sales (shares -80%)."
        ),
        early_warning="",
        fraud_type="Fabricated sales transactions",
        fraud_nature="financial_statement",
        label_confidence="established (company admission, SEC complaint)",
        form_type="20-F",
        accession="0001104659-21-087180",
        analysis_filing_date="2021-06-30",
        report_date="2019-12-31",
        has_xbrl=True,
        xbrl_note=(
            "Companyfacts exist; FY2019 20-F (accession above) carries ~430 us-gaap facts. Foreign "
            "private issuer: no 10-K/10-Q, so only annual 20-F data."
        ),
        strict_alt=None,
        validity_note=(
            "INVALID (look-ahead): the FY2019 20-F was filed 2021-06-30, 17 months AFTER the "
            "2020-01-31 short report and 15 months after the fraud admission. Luckin IPO'd May 2019 "
            "and filed no annual report before the revelation, so strict_alt is None (only F-1 "
            "registration statements and 6-Ks exist). The 20-F was prepared after the internal "
            "investigation, so whether it still shows the fabricated sales is NOT verified here. "
            "Kept in the spec run, flagged invalid."
        ),
        sources=[
            "https://www.qsrmagazine.com/food/beverage/luckin-coffee-faces-fraud-allegations-anonymous-report/",
            "https://www.cnbc.com/2020/04/02/luckin-coffee-stock-plummets-after-investigation-finds-coo-fabricated-sales.html",
            "https://www.sec.gov/Archives/edgar/data/1767582/000135445720000301/lkdelistreason.txt",
            "https://www.sec.gov/litigation/litreleases/2020/lr24987.htm",
        ],
    ),
    _fraud(
        ticker="NKLA",
        company_name="Nikola Corp",
        edgar_name="Nikola Corp",
        former_names=["VectoIQ Acquisition Corp."],
        sic="3711",
        cik="0001731289",
        spec_cik="0001731289",
        correction_reason="",
        spec_analysis_year=2020,
        analysis_year=2020,
        spec_collapsed_year=2021,
        collapsed_year=2021,
        collapse_date="2021-12-21",
        collapse_event=(
            "SEC settled order: Nikola paid a $125M civil penalty (2021-12-21). Company filed "
            "Chapter 11 on 2025-02-19 (final outcome)."
        ),
        public_revelation_date="2020-09-10",
        revelation_event=(
            "Hindenburg Research short report 'How to Parlay An Ocean of Lies...'; founder "
            "Trevor Milton resigned 2020-09-21."
        ),
        early_warning="",
        fraud_type="False product capability claims",
        fraud_nature="disclosure_claims",
        label_confidence="established (SEC order against the company); misstatements concern product claims, not the financial statements",
        form_type="10-K",
        accession="0001731289-21-000006",
        analysis_filing_date="2021-02-25",
        report_date="2020-12-31",
        has_xbrl=True,
        xbrl_note="FY2020 10-K carries ~640 XBRL facts. A 10-K/A for FY2020 was filed 2021-05-06 (0001731289-21-000058).",
        strict_alt=_alt(
            2019, "2020-03-06", "10-K", "0001104659-20-030103",
            "SPAC SHELL: filed by VectoIQ Acquisition Corp. before the 2020-06-03 merger; trust-account "
            "financials only, no Nikola operating history.",
        ),
        validity_note=(
            "INVALID (look-ahead): FY2020 10-K filed 2021-02-25, five months AFTER Hindenburg "
            "(2020-09-10). The only annual filing before the revelation (FY2019 10-K, 2020-03-06) "
            "belongs to the SPAC VectoIQ and contains no operating-company financials, so the strict "
            "run has little meaning for this case."
        ),
        sources=[
            "https://fortune.com/2020/09/10/nikola-motor-stock-hindenburg-research-allegations",
            "https://www.electrive.com/2020/09/21/trevor-milton-resigns-as-nikola-executive-chair/",
            "https://www.newsfilecorp.com/release/108208/Nikola-Corporation-to-Pay-125-Million-to-Resolve-Fraud-Charges",
            "https://www.sec.gov/Archives/edgar/data/1731289/000173128925000004/pressreleaseofnikolacorpor.htm",
        ],
    ),
    _fraud(
        ticker="RIDE",
        company_name="Lordstown Motors Corp",
        edgar_name="Stark Novus Financial Inc. (formerly Lordstown Motors Corp., NU RIDE INC.)",
        former_names=["Lordstown Motors Corp.", "DiamondPeak Holdings Corp.", "NU RIDE INC."],
        sic="3711",
        cik="0001759546",
        spec_cik="0001759774",
        correction_reason=(
            "Spec CIK 0001759774 is Postal Realty Trust, Inc. (PSTL, a REIT). Lordstown Motors Corp. "
            "(ex-DiamondPeak Holdings, ticker RIDE) is CIK 1759546. EDGAR's current entity name for "
            "this CIK is 'Stark Novus Financial Inc.' (ticker SNFI) after post-bankruptcy renames, so "
            "ticker lookup for RIDE will not resolve: callers must pass cik=."
        ),
        spec_analysis_year=2020,
        analysis_year=2020,
        spec_collapsed_year=2021,
        collapsed_year=2021,
        collapse_date="2021-06-14",
        collapse_event=(
            "CEO Steve Burns and CFO Julio Rodriguez resignations announced 2021-06-14 (8-K). "
            "Chapter 11 followed on 2023-06-27; SEC settled order (disgorgement $25.5M) in 2024."
        ),
        public_revelation_date="2021-03-12",
        revelation_event=(
            "Hindenburg Research report 'The Lordstown Motors Mirage' alleging fictitious pre-orders "
            "(the original brief's 2021-03-15 was not supported; sources give 2021-03-12)."
        ),
        early_warning="",
        fraud_type="Inflated order book",
        fraud_nature="disclosure_claims",
        label_confidence="established (SEC settled order on misleading pre-order claims); not a financial-statement fraud",
        form_type="10-K",
        accession="0001558370-21-003449",
        analysis_filing_date="2021-03-25",
        report_date="2020-12-31",
        has_xbrl=True,
        xbrl_note=(
            "FY2020 10-K carries XBRL (~150 facts; pre-revenue development-stage company, so revenue-"
            "based metrics such as DSRI/SGI/DSO are not meaningful). A 10-K/A for FY2020 was filed 2021-06-08."
        ),
        strict_alt=_alt(
            2019, "2020-03-25", "10-K", "0001213900-20-007365",
            "SPAC SHELL: filed by DiamondPeak Holdings Corp. before the 2020-10-23 merger; no "
            "Lordstown operating financials.",
        ),
        validity_note=(
            "INVALID (look-ahead): FY2020 10-K filed 2021-03-25, thirteen days AFTER the Hindenburg "
            "report (2021-03-12). The only earlier annual filing is the DiamondPeak SPAC shell 10-K "
            "(2020-03-25)."
        ),
        sources=[
            "https://www.ktmc.com/new-cases/lordstown-motors-corp",
            "https://www.sec.gov/Archives/edgar/data/1759546/000110465921080500/tm2119596d1_8k.htm",
            "https://www.bnnbloomberg.ca/us-truck-startup-lordstown-files-for-bankruptcy-after-foxconn-deal-falls-through-1.1938347",
            "https://constructionequipment.com/trucking/news/33038138/lordstown-settles-sec-case-for-25-million",
        ],
    ),
    _fraud(
        ticker="SPCE",
        company_name="Virgin Galactic Holdings, Inc",
        edgar_name="Virgin Galactic Holdings, Inc",
        former_names=["Social Capital Hedosophia Holdings Corp."],
        sic="4700",
        cik="0001706946",
        spec_cik="0001679273",
        correction_reason=(
            "Spec CIK 0001679273 is Lamb Weston Holdings, Inc. (LW). Virgin Galactic Holdings is CIK 1706946. "
            "Also: the spec's 2023 'collapse' is unverified (company still files 10-Ks); collapsed_year/"
            "collapse_date use the 2021-10-14 stock-drop/class-period end instead."
        ),
        spec_analysis_year=2021,
        analysis_year=2021,
        spec_collapsed_year=2023,
        collapsed_year=2021,
        collapse_date="2021-10-14",
        collapse_event=(
            "NOT a collapse. 2021-10-14 is the last day of the securities class-action class period "
            "(commercial service delayed to Q4 2022, stock -14%). No bankruptcy/delisting/SEC accounting "
            "action was found for 2023; the company still files 10-Ks (latest FY2025). The spec's 2023 "
            "'collapse' could not be verified."
        ),
        public_revelation_date="2021-09-01",
        revelation_event=(
            "The New Yorker (2021-09-01) first reported that the 2021-07-11 Unity 22 flight with Richard "
            "Branson had strayed from its assigned airspace; the FAA grounded SpaceShipTwo pending "
            "investigation on 2021-09-02. Cleared to resume late Sept 2021."
        ),
        early_warning=(
            "2021-05-28 Lavin v. Virgin Galactic class action filed (class period then reported as "
            "2019-10-26 to 2021-04-30); amended complaint covers 2019-07-10 to 2021-10-14 and alleges "
            "misleading safety/commercial-flight statements. Settled (reported $8.5M, announced June 2025)."
        ),
        fraud_type="Misleading safety disclosures",
        fraud_nature="disclosure_claims",
        label_confidence=(
            "WEAK: civil securities class action settled without admission; no SEC/DOJ finding, no "
            "restatement, no financial-statement manipulation alleged"
        ),
        form_type="10-K",
        accession="0001706946-22-000035",
        analysis_filing_date="2022-02-28",
        report_date="2021-12-31",
        has_xbrl=True,
        xbrl_note="FY2021 10-K carries ~520 XBRL facts. FY2020 10-K/As were filed 2021-03-11 and 2021-05-10.",
        strict_alt=_alt(2020, "2021-03-01", "10-K", "0001706946-21-000022",
                        "original FY2020 10-K (10-K/As on 2021-03-11 and 2021-05-10 were later)"),
        validity_note=(
            "INVALID (look-ahead): FY2021 10-K filed 2022-02-28, six months AFTER the 2021-09-01 "
            "revelation and after the 2021-10-14 stock drop. Strict alternative is the FY2020 10-K "
            "(2021-03-01). The 'fraud' label is the weakest of the 12: treat Virgin Galactic as a "
            "contested/disclosure-risk case, not proven accounting fraud."
        ),
        sources=[
            "https://en.wikipedia.org/wiki/Virgin_Galactic_Unity_22",
            "https://www.sec.gov/Archives/edgar/data/1706946/000170694623000016/spce-20221231.htm",
            "https://www.businesswire.com/news/home/20210601006019/en/Notice-of-Lead-Plaintiff-Deadline-for-Shareholders-in-the-Virgin-Galactic-Holdings-Inc.-Class-Action-Lawsuit",
            "https://virgingalacticsecuritiessettlement.com/wp-content/uploads/sites/17/2026/03/1_21-cv-03070-NRM-TAM_198_Exhibit-1-Stipulation-of-Settlement.pdf",
        ],
    ),
]


CLEAN_CASES: list[dict[str, Any]] = [
    _clean(
        ticker="AAPL",
        company_name="Apple Inc.",
        edgar_name="Apple Inc.",
        former_names=["APPLE COMPUTER INC"],
        sic="3571",
        cik="0000320193",
        analysis_year=2020,
        form_type="10-K",
        accession="0000320193-20-000096",
        analysis_filing_date="2020-10-30",
        report_date="2020-09-26",
        has_xbrl=True,
        xbrl_note="FY2020 (Sept 26, 2020) 10-K carries ~530 facts.",
        validity_note="Clean control; fiscal year ends late September (FY2020 = Oct 2019-Sep 2020).",
        caveats="No SEC accounting action found against the company (only a 2016-era insider-trading case against a former employee).",
        sources=["https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/"],
    ),
    _clean(
        ticker="MSFT",
        company_name="Microsoft Corp",
        edgar_name="MICROSOFT CORP",
        former_names=[],
        sic="7372",
        cik="0000789019",
        analysis_year=2020,
        form_type="10-K",
        accession="0001564590-20-034944",
        analysis_filing_date="2020-07-30",
        report_date="2020-06-30",
        has_xbrl=True,
        xbrl_note="FY2020 (June 30, 2020) 10-K carries ~630 facts.",
        validity_note="Clean control; fiscal year ends June 30.",
        caveats=(
            "Historic: SEC settled accounting charges in 2002 (reserve accounts, 1994-1998 financials). "
            "Nothing found for 2019-2021."
        ),
        sources=["https://www.sec.gov/news/press/2002-80.htm"],
    ),
    _clean(
        ticker="JNJ",
        company_name="Johnson & Johnson",
        edgar_name="JOHNSON & JOHNSON",
        former_names=["JOHNSON & JOHNSON ET AL"],
        sic="2834",
        cik="0000200406",
        analysis_year=2020,
        form_type="10-K",
        accession="0000200406-21-000008",
        analysis_filing_date="2021-02-22",
        report_date="2021-01-03",
        has_xbrl=True,
        xbrl_note=(
            "Fiscal 2020 ended 2021-01-03 (52/53-week year); the SEC fy tag is 2020. Under CONTRACTS D12 "
            "a period ending in January maps to the prior year, so FY2020 is correct. ~630 facts."
        ),
        validity_note="Clean control; 53-week fiscal 2020 ending 2021-01-03.",
        caveats=(
            "Very large talc/opioid litigation disclosures; DOJ and SEC subpoenas about talc were disclosed "
            "in Feb 2019. No restatement or accounting-fraud action found, so the label stays Clean "
            "(= no known accounting fraud/restatement). Expect litigation language to trip text agents. "
            "SEC FCPA action 2011 (historic, not accounting fraud)."
        ),
        sources=[
            "https://nbcnews.com/business/business-news/doj-sec-subpoena-johnson-johnson-talc-powder-asbestos-probe-n973901",
        ],
    ),
    _clean(
        ticker="PG",
        company_name="Procter & Gamble Co",
        edgar_name="PROCTER & GAMBLE Co",
        former_names=[],
        sic="2840",
        cik="0000080424",
        analysis_year=2020,
        form_type="10-K",
        accession="0000080424-20-000053",
        analysis_filing_date="2020-08-06",
        report_date="2020-06-30",
        has_xbrl=True,
        xbrl_note="FY2020 (June 30, 2020) 10-K carries ~610 facts. A 10-K/A (0000080424-20-000059) was filed 2020-08-07; the original is used.",
        validity_note="Clean control; fiscal year ends June 30. Use the original 10-K, not the next-day 10-K/A (reason for the amendment not examined).",
        caveats="No SEC accounting enforcement action found against P&G for the period.",
        sources=[],
    ),
    _clean(
        ticker="BRK-B",
        company_name="Berkshire Hathaway Inc",
        edgar_name="BERKSHIRE HATHAWAY INC",
        former_names=["NBH INC"],
        sic="6331",
        cik="0001067983",
        analysis_year=2020,
        form_type="10-K",
        accession="0001564590-21-009611",
        analysis_filing_date="2021-03-01",
        report_date="2020-12-31",
        has_xbrl=True,
        xbrl_note=(
            "FY2020 10-K carries ~430 facts. One registrant (CIK 1067983) with two share classes: BRK-A and "
            "BRK-B (EDGAR tickers list ['BRK-B','BRK-A']; Yahoo style BRK-B, others BRK.B). Pass cik= to be safe."
        ),
        validity_note="Clean control; Dec FYE.",
        caveats=(
            "Insurance/investment conglomerate with an unclassified balance sheet: current assets/COGS/"
            "receivables concepts are partly absent, so Beneish/Altman may be unavailable or "
            "misleading. SEC action in 2005 concerned General Re individuals, not Berkshire's statements."
        ),
        sources=[],
    ),
    _clean(
        ticker="MMM",
        company_name="3M Co",
        edgar_name="3M CO",
        former_names=["MINNESOTA MINING & MANUFACTURING CO"],
        sic="3841",
        cik="0000066740",
        analysis_year=2020,
        form_type="10-K",
        accession="0001558370-21-000737",
        analysis_filing_date="2021-02-04",
        report_date="2020-12-31",
        has_xbrl=True,
        xbrl_note="FY2020 10-K carries ~710 facts.",
        validity_note="Clean control; Dec FYE.",
        caveats=(
            "Very large litigation disclosures (Combat Arms earplugs, PFAS) and a 2019 securities class "
            "action over PFAS exposure statements; a 2020 grand-jury subpoena (Alabama discharges). SEC "
            "FCPA books-and-records settlement (2023) concerns 2016-2018 China travel payments, not "
            "accounting fraud/restatement. Label stays Clean (= no known accounting fraud/restatement)."
        ),
        sources=[
            "https://www.sec.gov/newsroom/press-releases/2023-160",
            "https://www.mprnews.org/story/2020/01/30/federal-grand-jury-subpoenas-3m-over-chemical-discharges",
        ],
    ),
]

ALL_CASES: list[dict[str, Any]] = FRAUD_CASES + CLEAN_CASES

_ALIASES = {
    "ENRON": "ENRNQ",
    "ENE": "ENRNQ",
    "WORLDCOM": "WCOM",
    "MCIP": "WCOM",
    "LKNCY": "LK",
    "NIKOLA": "NKLA",
    "LORDSTOWN": "RIDE",
    "LMC": "RIDE",
    "VIRGINGALACTIC": "SPCE",
    "BRK.B": "BRK-B",
    "BRKB": "BRK-B",
    "BRK_B": "BRK-B",
    "BRK-A": "BRK-B",
    "BRK.A": "BRK-B",
    "3M": "MMM",
}


def get_case(ticker: str) -> dict[str, Any] | None:
    """Return a deep copy of the case for ``ticker`` (case-insensitive, aliases allowed).

    Returns ``None`` when the ticker is unknown (never raises).  A CIK string
    (with or without zero padding) also matches.
    """
    if not ticker:
        return None
    key = str(ticker).strip().upper()
    key = _ALIASES.get(key, key)
    digits = key.lstrip("0")
    for case in ALL_CASES:
        if case["ticker"] == key or (digits.isdigit() and case["cik"].lstrip("0") == digits):
            return copy.deepcopy(case)
    return None


def cases_as_dataframe():
    """Return all 12 cases as a flat ``pandas.DataFrame`` (one row per case).

    ``strict_alt`` is flattened to ``strict_alt_fiscal_year``, ``strict_alt_filing_date``,
    ``strict_alt_form``, ``strict_alt_accession`` (None when absent); list-valued fields
    (``sources``, ``former_names``) are joined with `` | ``.
    """
    import pandas as pd

    rows = []
    for case in ALL_CASES:
        row = {k: v for k, v in case.items() if k != "strict_alt"}
        alt = case.get("strict_alt") or {}
        for field in ("fiscal_year", "filing_date", "form", "accession"):
            row[f"strict_alt_{field}"] = alt.get(field)
        for k in ("sources", "former_names"):
            row[k] = " | ".join(case.get(k) or [])
        rows.append(row)
    return pd.DataFrame(rows)
