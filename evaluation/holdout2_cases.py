"""SEALED HOLDOUT H2: 15 known-fraud filings and 15 matched "clean" filings (v3 protocol, docs/V3_PROTOCOL.md).

DO NOT OPEN, GREP OR RUN THIS FILE (or any ticker in it) while building v3.  It may be opened only after the v3 code freeze
(docs/V3_FREEZE.md).  The selection agent never ran the forensic system on any case.

Schema
------
Identical to ``evaluation/holdout_cases.py`` (which mirrors ``evaluation/fraud_cases.py`` key for key) so the evaluator can run
these dicts unchanged.  Added keys (as in holdout 1): ``match_partner``, ``holdout`` (always True), ``caveats`` (also on fraud cases),
informational ``total_assets`` (USD; XBRL ``Assets`` of the analysed filing, or read from the filing's balance sheet / comparative
facts of later filings for pre-XBRL cases), ``fiscal_year_end`` and ``revelation_sources``.  Deviations from the dev schema (same
as holdout 1): ``strict_alt`` and ``strict_as_of`` are ``None`` for every case (the analysed filing is already the last annual
report filed before the revelation, so a strict run equals the spec run); ``collapse_date`` / ``collapsed_year`` are ``None``
(terminal events not researched; the pre-registered timing metric uses ``public_revelation_date``); ``corrected`` is always False.

Selection protocol (docs/V2_PROTOCOL.md criteria, tightened in docs/V3_PROTOCOL.md)
-----------------------------------------------------------------------------------
FRAUD: US-listed operating companies with revenue and an SEC accounting / financial-statement enforcement action (AAER, civil
complaint or administrative order) or a restatement that led to one, whose first PUBLIC revelation (8-K item 4.02, NT 10-K/10-Q
reporting an accounting review, audit-committee review notice or earnings release; dated from the EDGAR filing) is later than the
filing date of the LAST annual report on EDGAR, and that report contains the full financial statements.  The analysed filing is
that report, so ``pre_revelation_valid`` is True for every fraud case.  Fiscal years 2006-2019 (10 of 15 fraud cases carry XBRL facts).  Selection used documentation quality, those criteria and industry/year stratification only; detectability by
any detector was never examined.  Candidate pool and every drop reason: docs/holdout2_research.md.
CLEAN: one control per fraud case, same fiscal-year label (D12), same 3-digit SIC where possible (see per-case notes), total assets
0.3x-3x of the fraud company's, revenue > 0, a 10-K for the year, no NT 10-K/10-Q or 8-K item 4.01/4.02/2.06 in FY-30d .. FY+3y+150d,
at least four 10-Ks in that window, and a text scan of the four 10-Ks FY..FY+3 for restatement,
non-boilerplate material weakness, going-concern doubt and SEC subpoena/inquiry.

Caveats
-------
* Labels come from SEC enforcement releases and company filings.  "Clean" = no known restatement/AAER/going-concern/material
  weakness/auditor resignation found in FY..FY+3; it is NOT proof of cleanliness.
* Label strength varies (see ``label_confidence``): settled orders with fraud findings, controls/reporting-only orders (Stein Mart,
  Plug Power), and one case where only individuals were sanctioned (UniTek).
* The SEC findings for Swisher Hygiene concern the 2011 quarters, not the analysed FY2010 annual report (the last one before the
  revelation); Volt's finding concerns FY2007 (carried in the analysed FY2008 report).
* Revelation dates are the first public filing/press date found; earlier press or short-seller commentary may exist (not
  exhaustively searched).
* n = 15 + 15 gives wide confidence intervals.  XBRL era: 10 of 15 fraud and 10 of 15 clean filings carry XBRL facts for the
  analysed accession; 5 pairs (FY2006, FY2008, FY2010 x2, FY2011 May) are pre-XBRL.
* Matching is on size, SIC and fiscal year only; it does not control for growth, leverage or distress.

Dates are ISO ``YYYY-MM-DD`` strings (CONTRACTS D13); CIKs are 10-digit strings.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "HOLDOUT2_FRAUD",
    "HOLDOUT2_CLEAN",
    "HOLDOUT2_CASES",
    "get_holdout2_case",
]

_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _filing_url(cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def _fraud(**kw: Any) -> dict[str, Any]:
    """Assemble a holdout fraud case (same derivations as fraud_cases._fraud; strict_alt always None)."""
    kw["ground_truth"] = 1
    kw["label"] = "Fraud"
    kw["pre_revelation_valid"] = kw["analysis_filing_date"] < kw["public_revelation_date"]
    kw["as_of"] = kw["analysis_filing_date"]
    kw["strict_alt"] = None
    kw["strict_as_of"] = None
    kw["corrected"] = False
    kw["correction_reason"] = ""
    kw["spec_cik"] = kw["cik"]
    kw["spec_analysis_year"] = kw["analysis_year"]
    kw["spec_collapsed_year"] = None
    kw["collapsed_year"] = None
    kw["collapse_date"] = None
    kw.setdefault("collapse_event", "not researched (terminal events outside the pre-registered metric)")
    kw.setdefault("early_warning", "")
    kw["holdout"] = True
    kw["sources"] = [
        _SUBMISSIONS.format(cik=kw["cik"]),
        *([_COMPANYFACTS.format(cik=kw["cik"])] if kw["has_xbrl"] else []),
        _filing_url(kw["cik"], kw["accession"]),
        *kw["revelation_sources"],
        *kw["sources"],
    ]
    return kw


def _clean(**kw: Any) -> dict[str, Any]:
    """Assemble a holdout clean control (same derivations as fraud_cases._clean)."""
    kw.update(
        ground_truth=0,
        label="Clean",
        collapsed_year=None,
        collapse_date=None,
        public_revelation_date=None,
        pre_revelation_valid=True,
        fraud_type="",
        fraud_nature="none",
        label_confidence="no known fraud/restatement in FY..FY+3 (not a proof of cleanliness)",
        strict_alt=None,
        strict_as_of=None,
        corrected=False,
        correction_reason="",
        spec_cik=kw["cik"],
        spec_analysis_year=kw["analysis_year"],
        early_warning="",
        holdout=True,
    )
    kw["as_of"] = kw["analysis_filing_date"]
    kw["sources"] = [
        _SUBMISSIONS.format(cik=kw["cik"]),
        *([_COMPANYFACTS.format(cik=kw["cik"])] if kw["has_xbrl"] else []),
        _filing_url(kw["cik"], kw["accession"]),
        *kw["sources"],
    ]
    return kw


HOLDOUT2_FRAUD: list[dict[str, Any]] = [
    _fraud(**{'ticker': 'MNTX',
     'company_name': 'Manitex International, Inc.',
     'edgar_name': 'Manitex International, Inc.',
     'former_names': ['Veri-Tek International, Corp.'],
     'sic': '3559',
     'cik': '0001302028',
     'analysis_year': 2016,
     'public_revelation_date': '2017-11-06',
     'revelation_event': '8-K (items 2.02/4.02) filed 2017-11-06: pending restatement of previously issued financial '
                         'statements (2016 sales of 39 cranes, ~$15M, to a single broker customer); NT 10-Q 2017-11-13; '
                         '10-K/A for FY2016 filed 2018-04-03.',
     'fraud_type': 'Improper revenue/inventory accounting through related-party entities (two schemes by senior '
                   'officers: Lift Ventures JV inventory contribution and 2016 crane sales to a broker customer)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2020-09-29 (AAER-4177): financial and accounting fraud by '
                         'senior officers; misstated filings Q4 2014-Q2 2017',
     'form_type': '10-K',
     'accession': '0001564590-17-003903',
     'analysis_filing_date': '2017-03-10',
     'report_date': '2016-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2016 10-K (FYE 2016-12-31) filed 2017-03-10, 7.9 months before the first public disclosure '
                      '(2017-11-06); no other annual report filed in between.',
     'match_partner': 'ACLS',
     'total_assets': 317985000,
     'fiscal_year_end': '2016-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1302028/000119312517334251/',
                            'https://www.sec.gov/Archives/edgar/data/1302028/000119312517339817/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2020/33-10860.pdf'],
     'caveats': 'The FY2016 10-K was later amended (10-K/A 2018-04-03, restated). The SEC misstatement window (Q4 '
                "2014-Q2 2017) contains the analysed year. 'Restated' mentions in the analysed 10-K concern "
                'discontinued-operations presentation and purchase-price allocation, not an error correction.'}),
    _fraud(**{'ticker': 'SAEX',
     'company_name': 'SAExploration Holdings, Inc.',
     'edgar_name': 'SAExploration Holdings, Inc.',
     'former_names': ['Trio Merger Corp.'],
     'sic': '1382',
     'cik': '0001514732',
     'analysis_year': 2018,
     'public_revelation_date': '2019-08-15',
     'revelation_event': 'NT 10-Q filed 2019-08-15 disclosed an SEC investigation of revenue recognition, receivables '
                         'and tax credits and an Audit Committee assessment of historical financial statements; 8-K item '
                         '4.02 filed 2019-08-16 (non-reliance on previously issued statements).',
     'fraud_type': 'Revenue (~$100M) recognised on seismic contracts with a purportedly unrelated customer controlled by '
                   'the CEO; concealed misappropriation (~$12M); related receivables/tax-credit issues',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC civil complaint 2020-10-08 (SDNY 20-cv-08423) against the company and four former '
                         'executives; final judgments 2023-2024 (AAER-4402/4474/4513)',
     'form_type': '10-K',
     'accession': '0001564590-19-009158',
     'analysis_filing_date': '2019-03-25',
     'report_date': '2018-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2018 10-K (FYE 2018-12-31) filed 2019-03-25, 4.7 months before the first public disclosure '
                      '(2019-08-15); no other annual report filed in between.',
     'match_partner': 'DWSN',
     'total_assets': 137473000,
     'fiscal_year_end': '2018-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1514732/000119312519222607/',
                            'https://www.sec.gov/Archives/edgar/data/1514732/000119312519222908/'],
     'sources': ['https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25700',
                 'https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25902',
                 'https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26078'],
     'caveats': 'The restatement of FY2018 was filed as a 10-K/A on 2020-02-07; the analysed filing is the original. The '
                'FY2018 10-K contains no SEC-investigation, subpoena or going-concern language (scanned). Small company '
                '(assets $137M) in an oilfield downcycle.'}),
    _fraud(**{'ticker': 'RVLT',
     'company_name': 'Revolution Lighting Technologies, Inc.',
     'edgar_name': 'Revolution Lighting Technologies, Inc.',
     'former_names': ['Nexxus Lighting, Inc.', 'SUPER VISION INTERNATIONAL INC'],
     'sic': '3640',
     'cik': '0000917523',
     'analysis_year': 2017,
     'public_revelation_date': '2018-10-19',
     'revelation_event': 'Press release 2018-10-19 (furnished on 8-K filed 2018-10-22): ongoing SEC investigation of '
                         'revenue recognition practices; Audit Committee review of bill-and-hold sales; 8-K item 4.02 '
                         'filed 2018-12-11; FY2018 10-K never filed on time (NT 10-K 2019-03-27).',
     'early_warning': '2018-08-10 NT 10-Q cited only the assessment of internal-control changes; the 2018-10-17 press '
                      'release (guidance cut, transaction committee for a chairman/CEO offer) contained no accounting '
                      'allegation.',
     'fraud_type': 'Premature revenue recognition on bill-and-hold sales supported by backdated documents (late 2014 to '
                   'mid-2018)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC complaint 2020-09-24 (LR-24915, AAER-4170): company, CEO, former CFO and two division CFOs '
                         'settled; accounting fraud',
     'form_type': '10-K',
     'accession': '0001193125-18-074202',
     'analysis_filing_date': '2018-03-08',
     'report_date': '2017-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2017 10-K (FYE 2017-12-31) filed 2018-03-08, 7.4 months before the first public disclosure '
                      '(2018-10-19); no other annual report filed in between.',
     'match_partner': 'LYTS',
     'total_assets': 170234000,
     'fiscal_year_end': '2017-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/917523/000119312518303652/',
                            'https://www.sec.gov/Archives/edgar/data/917523/000119312518346645/'],
     'sources': ['https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24915'],
     'caveats': 'The revelation date is the press-release date; the 8-K carrying it was filed three days later. The '
                'company was in a transaction process in late 2018.'}),
    _fraud(**{'ticker': 'HIL',
     'company_name': 'Hill International, Inc.',
     'edgar_name': 'Hill International, Inc.',
     'former_names': ['ARPEGGIO ACQUISITION CORP'],
     'sic': '8711',
     'cik': '0001287808',
     'analysis_year': 2016,
     'public_revelation_date': '2017-09-21',
     'revelation_event': '8-K item 4.02(a) filed 2017-09-21 (board determination 2017-09-20): FY2014, FY2015, FY2016 and '
                         'quarters of 2015-2016 and Q1 2017 can no longer be relied upon.',
     'early_warning': '2017-03-17 NT 10-K and 2017-08-10 NT 10-Q cited the tax treatment of the sale of the Construction '
                      'Claims Group, not an accounting allegation.',
     'fraud_type': 'Uncorrected foreign-currency exchange loss errors (~$5M, spread over time) and related errors that '
                   'overstated net earnings (May 2014-Mar 2017)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC complaint 2020-01-16 (LR-24720; AAER-4185 for the accountant): company settled with '
                         'permanent injunction and civil penalty; former chief accounting officer and a senior '
                         'accountant charged',
     'form_type': '10-K',
     'accession': '0001047469-17-002267',
     'analysis_filing_date': '2017-03-31',
     'report_date': '2016-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2016 10-K (FYE 2016-12-31) filed 2017-03-31, 5.7 months before the first public disclosure '
                      '(2017-09-21); no other annual report filed in between.',
     'match_partner': 'EXPO',
     'total_assets': 401208000,
     'fiscal_year_end': '2016-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1287808/000110465917058182/'],
     'sources': ['https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24720',
                 'https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24939'],
     'caveats': 'The analysed FY2016 10-K already reports material weaknesses and going-concern language (financial '
                'distress is visible), so it is not a clean-looking filing. 10-K/As for FY2016 were filed 2017-05-01 '
                '(Part III) and 2018-05-08 (restated).'}),
    _fraud(**{'ticker': 'SMRT',
     'company_name': 'Stein Mart, Inc.',
     'edgar_name': 'STEIN MART INC',
     'former_names': [],
     'sic': '5651',
     'cik': '0000884940',
     'analysis_year': 2011,
     'public_revelation_date': '2012-09-07',
     'revelation_event': "NT 10-Q filed 2012-09-07 for Q2: new inventory-system reconciliations and 'control "
                         "implications related to an error correction'; 8-K item 4.02 filed 2012-11-09 (restate "
                         'FY2009-FY2011 and quarters); restatement filed May 2013.',
     'fraud_type': "Inventory valued incorrectly for 'Perm POS' markdowns (written down at sale instead of at markdown) "
                   'plus errors in software assets, credit-card liabilities and other inventory items; quarterly pre-tax '
                   'income misstated 2010-Nov 2012',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2015-09-22 (AAER-3704) against the company only; reporting, '
                         'books-and-records and controls violations, no fraud finding',
     'form_type': '10-K',
     'accession': '0001193125-12-160849',
     'analysis_filing_date': '2012-04-12',
     'report_date': '2012-01-28',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2011 10-K (FYE 2012-01-28) filed 2012-04-12, 4.9 months before the first public disclosure '
                      '(2012-09-07); no other annual report filed in between.',
     'match_partner': 'BKE',
     'total_assets': 473216000,
     'fiscal_year_end': '2012-01-28',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/884940/000119312512385007/',
                            'https://www.sec.gov/Archives/edgar/data/884940/000119312512461903/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2015/34-75958.pdf'],
     'caveats': 'Weaker label tier (controls/reporting order, quarterly misstatements). The analysed FY2011 10-K (FYE '
                '2012-01-28) already reports two material weaknesses (system-incident communication, credit-card '
                'receivables). 52/53-week retail year; fiscal-year label 2011 per D12.'}),
    _fraud(**{'ticker': 'PLUG',
     'company_name': 'Plug Power Inc.',
     'edgar_name': 'PLUG POWER INC',
     'former_names': [],
     'sic': '3620',
     'cik': '0001093691',
     'analysis_year': 2019,
     'public_revelation_date': '2021-03-02',
     'revelation_event': 'NT 10-K filed 2021-03-02 (review of cost classification and ICFR assessment delayed the FY2020 '
                         '10-K); 8-K items 2.06/4.02 filed 2021-03-16: FY2018 and FY2019 10-Ks and 2019-2020 10-Qs '
                         'should no longer be relied upon; restated in the FY2020 10-K filed 2021-05-14.',
     'fraud_type': 'Errors in right-of-use assets/lease liabilities for sale-leasebacks, classification of R&D costs as '
                   'cost of revenue, and loss accruals on service contracts (restated 2018-2020)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2023-08-30 (AAER-4452): financial reporting, accounting and '
                         'controls failures leading to a multi-year restatement; no fraud finding',
     'form_type': '10-K',
     'accession': '0001558370-20-002267',
     'analysis_filing_date': '2020-03-10',
     'report_date': '2019-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2019 10-K (FYE 2019-12-31) filed 2020-03-10, 11.7 months before the first public disclosure '
                      '(2021-03-02); no other annual report filed in between.',
     'match_partner': 'EAF',
     'total_assets': 771184000,
     'fiscal_year_end': '2019-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1093691/000110465921030324/',
                            'https://www.sec.gov/Archives/edgar/data/1093691/000110465921037184/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2023/34-98243.pdf'],
     'caveats': 'Weakest label tier (reporting/controls order with restatement). Fast asset growth in the analysed year '
                '(assets $771M vs $390M).'}),
    _fraud(**{'ticker': 'PSIX',
     'company_name': 'Power Solutions International, Inc.',
     'edgar_name': 'POWER SOLUTIONS INTERNATIONAL, INC.',
     'former_names': ['FORMAT INC', 'FORMAT INC /FA/'],
     'sic': '3510',
     'cik': '0001137091',
     'analysis_year': 2015,
     'public_revelation_date': '2016-08-10',
     'revelation_event': 'NT 10-Q and 8-K item 7.01 filed 2016-08-10: Q2 10-Q delayed because the company had not '
                         'concluded its review of transactions needed to close the books; 8-K item 4.02 filed 2017-01-05 '
                         'after an Audit Committee independent review (preliminary findings 2016-12-28); FY2016 10-K not '
                         'timely filed (NT 10-K 2017-03-17).',
     'fraud_type': 'Bill-and-hold and side-agreement sales recognised as revenue before acceptance; ~$25M of revenue '
                   'overstated Q4 2014-Q4 2015',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order against the company 2020-09-24 (AAER-4169); the order '
                         'describes accounting fraud by the former CEO and two executives',
     'form_type': '10-K',
     'accession': '0001193125-16-482422',
     'analysis_filing_date': '2016-02-26',
     'report_date': '2015-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2015 10-K (FYE 2015-12-31) filed 2016-02-26, 5.5 months before the first public disclosure '
                      '(2016-08-10); no other annual report filed in between.',
     'match_partner': 'KAI',
     'total_assets': 359936000,
     'fiscal_year_end': '2015-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1137091/000119312516678104/',
                            'https://www.sec.gov/Archives/edgar/data/1137091/000119312517002121/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2020/34-89984.pdf'],
     'caveats': 'The first public signal (2016-08-10) is a delay notice without an accounting allegation; the '
                'independent Audit Committee review was announced at an unpinned date between 2016-08 and 2017-01. The '
                'analysed FY2015 10-K lies inside the SEC misstatement window.'}),
    _fraud(**{'ticker': 'RTIX',
     'company_name': 'RTI Surgical, Inc. (now Surgalign Holdings, Inc.)',
     'edgar_name': 'RTI SURGICAL, INC.',
     'former_names': ['RTI Biologics, Inc.', 'REGENERATION TECHNOLOGIES INC'],
     'sic': '3842',
     'cik': '0001100441',
     'analysis_year': 2018,
     'public_revelation_date': '2020-03-17',
     'revelation_event': 'NT 10-K filed 2020-03-17: Audit Committee internal investigation of revenue recognition '
                         'practices, precipitated by an SEC investigation; 8-K item 4.02 filed 2020-04-09: FY2014-FY2018 '
                         'and 2016-2019 quarters to be restated; restated FY2018 10-K/A filed 2020-06-08.',
     'fraud_type': 'Revenue pulled forward from future quarters by shipping orders early (with or without customer '
                   'approval) to meet guidance, 2015-2019; pull-forwards undisclosed',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled order 2022-08-03 (AAER-4318) against Surgalign Holdings (successor of RTI) and its '
                         'former CFO; restatement of 2014-2018',
     'form_type': '10-K',
     'accession': '0001193125-19-063391',
     'analysis_filing_date': '2019-03-05',
     'report_date': '2018-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2018 10-K (FYE 2018-12-31) filed 2019-03-05, 12.4 months before the first public disclosure '
                      '(2020-03-17); no other annual report filed in between.',
     'match_partner': 'INGN',
     'total_assets': 361186000,
     'fiscal_year_end': '2018-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1760173/000119312520075447/',
                            'https://www.sec.gov/Archives/edgar/data/1760173/000119312520101786/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2022/33-11088.pdf'],
     'caveats': 'The company was later renamed Surgalign (successor CIK 0001760173); the analysed filing is under the '
                'original RTI CIK. The FY2019 10-K was filed 2020-06-08 with the restatement.'}),
    _fraud(**{'ticker': 'SCOR',
     'company_name': 'comScore, Inc.',
     'edgar_name': 'COMSCORE, INC.',
     'former_names': ['COMSCORE NETWORKS INC'],
     'sic': '7389',
     'cik': '0001158172',
     'analysis_year': 2014,
     'public_revelation_date': '2016-02-29',
     'revelation_event': "NT 10-K filed 2016-02-29 (amended 2016-03-07): Audit Committee review of 'potential accounting "
                         "matters' delayed the FY2015 10-K; 8-K item 4.02 filed 2016-09-15; FY2015 and FY2016 were "
                         'reported in a combined 10-K filed 2018-03-23.',
     'fraud_type': 'Revenue overstated ~$50M (Feb 2014-Feb 2016) via manipulated non-monetary and monetary contracts, '
                   'plus false statements on key performance metrics',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled order 2019-09-24 (AAER-4091): financial accounting and disclosure fraud committed '
                         'principally through the former CEO',
     'form_type': '10-K',
     'accession': '0001158172-15-000020',
     'analysis_filing_date': '2015-02-20',
     'report_date': '2014-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2014 10-K (FYE 2014-12-31) filed 2015-02-20, 12.3 months before the first public disclosure '
                      '(2016-02-29); no other annual report filed in between.',
     'match_partner': 'DHX',
     'total_assets': 353952000,
     'fiscal_year_end': '2014-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1158172/000119312516485483/',
                            'https://www.sec.gov/Archives/edgar/data/1158172/000119312516494215/',
                            'https://www.sec.gov/Archives/edgar/data/1158172/000115817216000170/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2019/33-10692.pdf'],
     'caveats': 'The SEC misstatement window starts Feb 2014, so the analysed FY2014 10-K lies inside it. A 10-K/A '
                '(2015-04-24; content not examined) followed the original 10-K. The FY2015 annual report was never filed '
                'on its own.'}),
    _fraud(**{'ticker': 'HEV',
     'company_name': 'Ener1, Inc.',
     'edgar_name': 'ENER1 INC',
     'former_names': ['ENER 1 INC', 'INPRIMIS INC', 'BOCA RESEARCH INC'],
     'sic': '3690',
     'cik': '0000895642',
     'analysis_year': 2010,
     'public_revelation_date': '2011-08-10',
     'revelation_event': '8-K items 2.06/4.02 (event 2011-08-10, filed 2011-08-16): Audit Committee concluded FY2010 and '
                         'Q1 2011 financial statements should be restated (Think Holdings loans/receivables, impairment '
                         'timing); NT 10-Q 2011-08-09 and 2011-11-10.',
     'early_warning': '2011-06-22 8-K item 2.06 (impairment; content not examined).',
     'fraud_type': 'Failure to impair a 48%-owned related-party investment, loan and receivables at year-end 2010 and Q1 '
                   '2011, and improper Q4 2010 revenue on sales to that entity',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2016-04-19 (AAER-3766) against the company and three former '
                         'executives (CEO Gassenheimer, Seidel, Kamischke)',
     'form_type': '10-K',
     'accession': '0001144204-11-014018',
     'analysis_filing_date': '2011-03-10',
     'report_date': '2010-12-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'FY2010 10-K (FYE 2010-12-31) filed 2011-03-10, 5.0 months before the first public disclosure '
                      '(2011-08-10); no other annual report filed in between.',
     'match_partner': 'RSTI',
     'total_assets': 396544000,
     'fiscal_year_end': '2010-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/895642/000114420411047587/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2016/33-10068.pdf'],
     'caveats': 'No XBRL facts for the analysed 10-K in companyfacts (treated as pre-XBRL; statement tables parsed from '
                'text). The revelation is five months after the filing.'}),
    _fraud(**{'ticker': 'SABA',
     'company_name': 'Saba Software, Inc.',
     'edgar_name': 'SABA SOFTWARE INC',
     'former_names': [],
     'sic': '7372',
     'cik': '0001070380',
     'analysis_year': 2011,
     'public_revelation_date': '2012-04-09',
     'revelation_event': '8-K filed 2012-04-09: Audit Committee engaged counsel for an independent accounting review; '
                         'earnings release and 10-Q for the quarter ended 2012-02-29 delayed; 8-K item 4.02 filed '
                         '2012-06-29.',
     'fraud_type': 'Falsified consultant time records to recognise professional-services revenue early (fiscal 2008 '
                   'through Q2 fiscal 2012)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2014-09-24 (AAER-3583) against the company and two former '
                         'vice presidents; false results in at least 40 filings',
     'form_type': '10-K',
     'accession': '0001193125-11-212166',
     'analysis_filing_date': '2011-08-05',
     'report_date': '2011-05-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'FY2011 10-K (FYE 2011-05-31) filed 2011-08-05, 8.1 months before the first public disclosure '
                      '(2012-04-09); no other annual report filed in between.',
     'match_partner': 'LGTY',
     'total_assets': 113575000,
     'fiscal_year_end': '2011-05-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1070380/000119312512154429/',
                            'https://www.sec.gov/Archives/edgar/data/1070380/000119312512162881/',
                            'https://www.sec.gov/Archives/edgar/data/1070380/000119312512289589/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2014/33-9654.pdf'],
     'caveats': 'No XBRL facts for the analysed 10-K (FYE 2011-05-31, filed 2011-08-05) in companyfacts: treated as '
                'pre-XBRL. Delisted in 2013 for delinquent filings.'}),
    _fraud(**{'ticker': 'SWSH',
     'company_name': 'Swisher Hygiene Inc.',
     'edgar_name': 'Swisher Hygiene Inc.',
     'former_names': [],
     'sic': '2840',
     'cik': '0001504747',
     'analysis_year': 2010,
     'public_revelation_date': '2012-03-28',
     'revelation_event': '8-K item 4.02 and NT 10-K filed 2012-03-28: an internal review delayed the FY2011 10-K; '
                         'amended 10-Qs for Q1-Q3 2011 filed Feb 2013.',
     'fraud_type': 'Business-combination accounting not in conformity with GAAP, improper use of reserves, and '
                   'earnings-management entries to hit Adjusted EBITDA targets (misstated Q1-Q3 2011)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled cease-and-desist order 2016-05-24 (AAER-3775) against the company',
     'form_type': '10-K',
     'accession': '0000950123-11-031573',
     'analysis_filing_date': '2011-03-31',
     'report_date': '2010-12-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'FY2010 10-K (FYE 2010-12-31) filed 2011-03-31, 11.9 months before the first public disclosure '
                      '(2012-03-28); no other annual report filed in between.',
     'match_partner': 'SYNL',
     'total_assets': 106234262,
     'fiscal_year_end': '2010-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1504747/000119312512136037/',
                            'https://www.sec.gov/Archives/edgar/data/1504747/000119312512136054/'],
     'sources': ['https://www.sec.gov/files/litigation/admin/2016/33-10081.pdf'],
     'caveats': 'The SEC findings concern the 2011 quarters, not FY2010: the analysed FY2010 10-K is simply the last '
                'annual report before the revelation (and the first after the Nov 2010 merger); whether FY2010 itself '
                'was restated was not verified. Pre-XBRL. The control match is only on 2-digit SIC and size (no 3-digit '
                'peer passed).'}),
    _fraud(**{'ticker': 'VOL',
     'company_name': 'Volt Information Sciences, Inc.',
     'edgar_name': 'VOLT INFORMATION SCIENCES, INC.',
     'former_names': ['VOLT INFORMATION SCIENCES INC'],
     'sic': '7363',
     'cik': '0000103872',
     'analysis_year': 2008,
     'public_revelation_date': '2009-09-14',
     'revelation_event': 'NT 10-Q filed 2009-09-14: Q3 10-Q delayed while the company assessed whether previously '
                         'recognised revenues and related costs on certain customer contracts belonged in later periods; '
                         '8-K item 4.02 filed 2009-12-23 (FY2007, FY2008 and 2009 quarters to be restated).',
     'early_warning': '2009-09-09 8-K item 8.01 announced a delay of the Q3 earnings release (no reason). NT 10-K '
                      '2009-01-16 and 8-K 2009-01-21 (items 2.02/2.06) preceded the analysed 10-K (content not '
                      'examined).',
     'fraud_type': 'Improper revenue recognition at a subsidiary (SEC: $7.55M overstated in FY2007) and related '
                   'restatements',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled civil action against the company 2013-01-11 (LR-22589, AAER-3439; company '
                         'enjoined); former CFO final judgment 2014-07-18 (LR-23051, AAER-3569)',
     'form_type': '10-K',
     'accession': '0001157523-09-000729',
     'analysis_filing_date': '2009-02-02',
     'report_date': '2008-11-02',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'FY2008 10-K (FYE 2008-11-02) filed 2009-02-02, 7.4 months before the first public disclosure '
                      '(2009-09-14); no other annual report filed in between.',
     'match_partner': 'AMN',
     'total_assets': 925779000,
     'fiscal_year_end': '2008-11-02',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/103872/000091068009000434/',
                            'https://www.sec.gov/Archives/edgar/data/103872/000091068009000432/',
                            'https://www.sec.gov/Archives/edgar/data/103872/000091068009000571/'],
     'sources': ['https://www.sec.gov/enforcement-litigation/litigation-releases/lr-22589',
                 'https://www.sec.gov/enforcement-litigation/litigation-releases/lr-23051'],
     'caveats': "Pre-XBRL (assets from the filing's balance sheet, $925.8M). The SEC finding concerns FY2007; the "
                'analysed FY2008 10-K carried the FY2007 overstatement as a comparative. Material-weakness language is '
                'already present in the analysed filing (text count 15).'}),
    _fraud(**{'ticker': 'ISLN',
     'company_name': 'Isilon Systems, Inc.',
     'edgar_name': 'Isilon Systems, Inc.',
     'former_names': [],
     'sic': '3572',
     'cik': '0001373671',
     'analysis_year': 2006,
     'public_revelation_date': '2007-11-08',
     'revelation_event': '8-K item 8.01 filed 2007-11-08: Audit Committee independent review of sales to resellers and '
                         'other customers (revenue timing and internal controls); Q3 results and 10-Q delayed (NT 10-Q '
                         '2007-11-15); 8-K item 4.02 filed 2008-03-03 (restate FY2006, Q1-Q2 2007).',
     'fraud_type': 'Secret side deals with customers (undisclosed contingencies) allowing $4.8M of improper revenue in '
                   '2006-2007',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC fraud charges against the former CFO and settled proceeding against the company 2009-09-14 '
                         '(LR-21210, AAER-3050)',
     'form_type': '10-K',
     'accession': '0000950134-07-005674',
     'analysis_filing_date': '2007-03-15',
     'report_date': '2006-12-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'FY2006 10-K (FYE 2006-12-31) filed 2007-03-15, 7.8 months before the first public disclosure '
                      '(2007-11-08); no other annual report filed in between.',
     'match_partner': 'APKT',
     'total_assets': 136971000,
     'fiscal_year_end': '2006-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/1373671/000129993307006535/',
                            'https://www.sec.gov/Archives/edgar/data/1373671/000114036107022135/',
                            'https://www.sec.gov/Archives/edgar/data/1373671/000129993308001135/'],
     'sources': ['https://www.sec.gov/enforcement-litigation/litigation-releases/lr-21210'],
     'caveats': 'Pre-XBRL (FY2006). First annual report after the Dec 2006 IPO. A 10-K/A (2007-08-09; content not '
                "examined) was filed between the analysed 10-K and the revelation. Assets read from the filing's balance "
                'sheet ($137.0M).'}),
    _fraud(**{'ticker': 'UNTK',
     'company_name': 'UniTek Global Services, Inc.',
     'edgar_name': 'UniTek Global Services, Inc.',
     'former_names': ['BERLINER COMMUNICATIONS INC', 'NOVO NETWORKS INC', 'EVENTURES GROUP INC', 'ADINA INC'],
     'sic': '4812',
     'cik': '0000826773',
     'analysis_year': 2011,
     'public_revelation_date': '2013-03-27',
     'revelation_event': 'NT 10-K filed 2013-03-27: Audit Committee review of revenue recognition at the Pinnacle '
                         'Wireless division delayed the FY2012 10-K; 8-K item 4.02 filed 2013-04-12 (event 2013-04-10): '
                         'FY2011 and 2012 quarters no longer to be relied upon; FY2012 10-K with restatement filed '
                         '2013-08-12.',
     'fraud_type': 'Premature revenue recognition at the acquired Pinnacle Wireless division (invoice-based recognition '
                   'tied to earn-out incentives)',
     'fraud_nature': 'financial_statement',
     'label_confidence': 'SEC settled administrative orders 2017-06-09 (File 3-18020) against three former '
                         'executives/employees (Pinnacle president, UniTek chief accounting officer, Pinnacle '
                         'controller; joint $35,000 penalty); no SEC order against the issuer was found (details from '
                         'secondary summaries; order text not retrieved)',
     'form_type': '10-K',
     'accession': '0001144204-12-013579',
     'analysis_filing_date': '2012-03-07',
     'report_date': '2011-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'FY2011 10-K (FYE 2011-12-31) filed 2012-03-07, 12.6 months before the first public disclosure '
                      '(2013-03-27); no other annual report filed in between.',
     'match_partner': 'SHEN',
     'total_assets': 348880000,
     'fiscal_year_end': '2011-12-31',
     'revelation_sources': ['https://www.sec.gov/Archives/edgar/data/826773/000110465913024894/',
                            'https://www.sec.gov/Archives/edgar/data/826773/000110465913029058/'],
     'sources': ['https://www.secactions.com/sec-resolves-financial-fraud-action/'],
     'caveats': "Weakest label source (enforcement only against individuals, corroborated by the company's own "
                'restatement and an Audit Committee finding of fraudulent activity). The analysed FY2011 10-K is inside '
                'the restated period.'}),
]

HOLDOUT2_CLEAN: list[dict[str, Any]] = [
    _clean(**{'ticker': 'ACLS',
     'company_name': 'Axcelis Technologies, Inc.',
     'edgar_name': 'AXCELIS TECHNOLOGIES INC',
     'former_names': [],
     'sic': '3559',
     'cik': '0001113232',
     'analysis_year': 2016,
     'form_type': '10-K',
     'accession': '0001558370-17-001778',
     'analysis_filing_date': '2017-03-14',
     'report_date': '2016-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for MNTX (FY2016, SIC 3559 vs 3559: same 4-digit SIC, assets ratio 0.95).',
     'match_partner': 'MNTX',
     'total_assets': 302231000,
     'fiscal_year_end': '2016-12-31',
     'caveats': 'Text scan of FY2016-FY2019 10-Ks: only audit-report/risk boilerplate (no restatement, material '
                'weakness, going concern or SEC inquiry).',
     'sources': []}),
    _clean(**{'ticker': 'DWSN',
     'company_name': 'Dawson Geophysical Company',
     'edgar_name': 'DAWSON GEOPHYSICAL CO',
     'former_names': ['TGC INDUSTRIES INC'],
     'sic': '1382',
     'cik': '0000799165',
     'analysis_year': 2018,
     'form_type': '10-K',
     'accession': '0001558370-19-001602',
     'analysis_filing_date': '2019-03-06',
     'report_date': '2018-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for SAEX (FY2018, SIC 1382 vs 1382: same 4-digit SIC, assets ratio 1.10).',
     'match_partner': 'SAEX',
     'total_assets': 150685000,
     'fiscal_year_end': '2018-12-31',
     'caveats': 'Text scan FY2018-FY2021 clean. The EDGAR screen window also contains a 2022-03-25 8-K item 3.01 (Nasdaq '
                'audit-committee composition after director resignations) and a Part III 10-K/A (2022-05-02) around the '
                '2022 merger; both outside FY..FY+3 and benign.',
     'sources': []}),
    _clean(**{'ticker': 'LYTS',
     'company_name': 'LSI Industries Inc.',
     'edgar_name': 'LSI INDUSTRIES INC',
     'former_names': [],
     'sic': '3640',
     'cik': '0000763532',
     'analysis_year': 2017,
     'form_type': '10-K',
     'accession': '0001437749-17-015804',
     'analysis_filing_date': '2017-09-08',
     'report_date': '2017-06-30',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for RVLT (FY2017, SIC 3640 vs 3640: same 4-digit SIC, assets ratio 1.51).',
     'match_partner': 'RVLT',
     'total_assets': 256680000,
     'fiscal_year_end': '2017-06-30',
     'caveats': "Fiscal year ends 2017-06-30, six months before Revolution's; same fiscal-year label. Text scan "
                'FY2017-FY2020 clean.',
     'sources': []}),
    _clean(**{'ticker': 'EXPO',
     'company_name': 'Exponent, Inc.',
     'edgar_name': 'EXPONENT INC',
     'former_names': ['FAILURE GROUP INC'],
     'sic': '8742',
     'cik': '0000851520',
     'analysis_year': 2016,
     'form_type': '10-K',
     'accession': '0001144204-17-010991',
     'analysis_filing_date': '2017-02-24',
     'report_date': '2016-12-30',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for HIL (FY2016, SIC 8742 vs 8711: same 2-digit major group only, assets ratio '
                      '1.01).',
     'match_partner': 'HIL',
     'total_assets': 403744000,
     'fiscal_year_end': '2016-12-30',
     'caveats': 'SIC 8742 vs 8711: same 2-digit major group 87 only (no 3-digit peer passed the screen). Text scan '
                "FY2016-FY2019: 'restatement' appears only in risk-factor and exhibit boilerplate.",
     'sources': []}),
    _clean(**{'ticker': 'BKE',
     'company_name': 'The Buckle, Inc.',
     'edgar_name': 'BUCKLE INC',
     'former_names': [],
     'sic': '5651',
     'cik': '0000885245',
     'analysis_year': 2011,
     'form_type': '10-K',
     'accession': '0001157523-12-001574',
     'analysis_filing_date': '2012-03-28',
     'report_date': '2012-01-28',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for SMRT (FY2011, SIC 5651 vs 5651: same 4-digit SIC, assets ratio 1.12).',
     'match_partner': 'SMRT',
     'total_assets': 531539000,
     'fiscal_year_end': '2012-01-28',
     'caveats': 'Same fiscal year end (2012-01-28). Text scan FY2011-FY2014 clean.',
     'sources': []}),
    _clean(**{'ticker': 'EAF',
     'company_name': 'GrafTech International Ltd.',
     'edgar_name': 'GRAFTECH INTERNATIONAL LTD',
     'former_names': ['UCAR INTERNATIONAL INC'],
     'sic': '3620',
     'cik': '0000931148',
     'analysis_year': 2019,
     'form_type': '10-K',
     'accession': '0000931148-20-000024',
     'analysis_filing_date': '2020-02-21',
     'report_date': '2019-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for PLUG (FY2019, SIC 3620 vs 3620: same 4-digit SIC, assets ratio 1.98).',
     'match_partner': 'PLUG',
     'total_assets': 1526164000,
     'fiscal_year_end': '2019-12-31',
     'caveats': "SIC 3620 match; assets ratio 1.98 (upper part of the range). Text scan FY2019-FY2022: only ASC 842 'not "
                "restated' wording and cover-page error-correction check boxes.",
     'sources': []}),
    _clean(**{'ticker': 'KAI',
     'company_name': 'Kadant Inc.',
     'edgar_name': 'KADANT INC',
     'former_names': ['THERMO FIBERTEK INC'],
     'sic': '3550',
     'cik': '0000886346',
     'analysis_year': 2015,
     'form_type': '10-K',
     'accession': '0000886346-16-000221',
     'analysis_filing_date': '2016-03-16',
     'report_date': '2016-01-02',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for PSIX (FY2015, SIC 3550 vs 3510: same 2-digit major group only, assets ratio '
                      '1.15).',
     'match_partner': 'PSIX',
     'total_assets': 415498000,
     'fiscal_year_end': '2016-01-02',
     'caveats': 'SIC 3550 vs 3510: same 2-digit group 35 only (no 3-digit peer passed). 52/53-week year ending '
                "2016-01-02 (fiscal-year label 2015 per D12). Text scan: 'restated' only for ASU adoption and "
                'presentation changes.',
     'sources': []}),
    _clean(**{'ticker': 'INGN',
     'company_name': 'Inogen, Inc.',
     'edgar_name': 'Inogen Inc',
     'former_names': [],
     'sic': '3842',
     'cik': '0001294133',
     'analysis_year': 2018,
     'form_type': '10-K',
     'accession': '0001564590-19-004462',
     'analysis_filing_date': '2019-02-26',
     'report_date': '2018-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for RTIX (FY2018, SIC 3842 vs 3842: same 4-digit SIC, assets ratio 1.04).',
     'match_partner': 'RTIX',
     'total_assets': 375898000,
     'fiscal_year_end': '2018-12-31',
     'caveats': 'Text scan FY2018-FY2021: prior (2014-15) material weaknesses are described as remediated; none '
                'afterwards.',
     'sources': []}),
    _clean(**{'ticker': 'DHX',
     'company_name': 'DHI Group, Inc. (formerly Dice Holdings, Inc.)',
     'edgar_name': 'DHI GROUP, INC.',
     'former_names': ['DICE HOLDINGS, INC.'],
     'sic': '7389',
     'cik': '0001393883',
     'analysis_year': 2014,
     'form_type': '10-K',
     'accession': '0001393883-15-000008',
     'analysis_filing_date': '2015-02-10',
     'report_date': '2014-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for SCOR (FY2014, SIC 7389 vs 7389: same 4-digit SIC, assets ratio 1.21).',
     'match_partner': 'SCOR',
     'total_assets': 427247000,
     'fiscal_year_end': '2014-12-31',
     'caveats': 'Text scan FY2014-FY2017 clean.',
     'sources': []}),
    _clean(**{'ticker': 'RSTI',
     'company_name': 'Rofin-Sinar Technologies Inc.',
     'edgar_name': 'ROFIN SINAR TECHNOLOGIES INC',
     'former_names': [],
     'sic': '3690',
     'cik': '0001019361',
     'analysis_year': 2010,
     'form_type': '10-K',
     'accession': '0000930413-10-005871',
     'analysis_filing_date': '2010-11-30',
     'report_date': '2010-09-30',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'Clean control for HEV (FY2010, SIC 3690 vs 3690: same 4-digit SIC, assets ratio 1.41).',
     'match_partner': 'HEV',
     'total_assets': 558192000,
     'fiscal_year_end': '2010-09-30',
     'caveats': "Fiscal year ends 2010-09-30 vs Ener1's 2010-12-31. A 10-K/A (2010-12-23) only corrected a cover-page "
                'filer-status box. Text scan FY2010-FY2013 clean. No XBRL facts for the analysed 10-K.',
     'sources': []}),
    _clean(**{'ticker': 'LGTY',
     'company_name': 'Logility, Inc. (Logility Supply Chain Solutions)',
     'edgar_name': 'LOGILITY SUPPLY CHAIN SOLUTIONS, INC',
     'former_names': ['AMERICAN SOFTWARE INC'],
     'sic': '7372',
     'cik': '0000713425',
     'analysis_year': 2011,
     'form_type': '10-K',
     'accession': '0001193125-11-188351',
     'analysis_filing_date': '2011-07-14',
     'report_date': '2011-04-30',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'Clean control for SABA (FY2011, SIC 7372 vs 7372: same 4-digit SIC, assets ratio 0.92).',
     'match_partner': 'SABA',
     'total_assets': 104832000,
     'fiscal_year_end': '2011-04-30',
     'caveats': "Fiscal year ends 2011-04-30 (one month before Saba's). Majority-owned subsidiary of American Software. "
                "Text scan FY2011-FY2014: only risk-factor 'restatement' language. No XBRL facts for the analysed 10-K.",
     'sources': []}),
    _clean(**{'ticker': 'SYNL',
     'company_name': 'Synalloy Corporation (now Ascent Industries Co.)',
     'edgar_name': 'ASCENT INDUSTRIES CO.',
     'former_names': ['SYNALLOY CORP'],
     'sic': '2800',
     'cik': '0000095953',
     'analysis_year': 2010,
     'form_type': '10-K',
     'accession': '0000095953-11-000012',
     'analysis_filing_date': '2011-03-25',
     'report_date': '2011-01-01',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'Clean control for SWSH (FY2010, SIC 2800 vs 2840: same 2-digit major group only, assets ratio '
                      '0.77).',
     'match_partner': 'SWSH',
     'total_assets': 81375359,
     'fiscal_year_end': '2011-01-01',
     'caveats': 'SIC 2800 vs 2840: same 2-digit group 28 only; the 2-digit pool is almost all pharma/biotech, so this is '
                'the weakest industry match in the set. Fiscal year ends 2011-01-01 (label 2010). Text scan '
                'FY2010-FY2013 clean. No XBRL facts for the analysed 10-K.',
     'sources': []}),
    _clean(**{'ticker': 'AMN',
     'company_name': 'AMN Healthcare Services, Inc.',
     'edgar_name': 'AMN HEALTHCARE SERVICES INC',
     'former_names': [],
     'sic': '7363',
     'cik': '0001142750',
     'analysis_year': 2008,
     'form_type': '10-K',
     'accession': '0001193125-09-042607',
     'analysis_filing_date': '2009-03-02',
     'report_date': '2008-12-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'Clean control for VOL (FY2008, SIC 7363 vs 7363: same 4-digit SIC, assets ratio 0.69).',
     'match_partner': 'VOL',
     'total_assets': 642817000,
     'fiscal_year_end': '2008-12-31',
     'caveats': "Fiscal year ends 2008-12-31 vs Volt's 2008-11-02. Pre-XBRL; assets read from the filing's balance sheet "
                'text ($642.8M). Text scan FY2008-FY2011: one segment-restatement mention (presentation).',
     'sources': []}),
    _clean(**{'ticker': 'APKT',
     'company_name': 'Acme Packet, Inc.',
     'edgar_name': 'ACME PACKET INC',
     'former_names': [],
     'sic': '3576',
     'cik': '0001130258',
     'analysis_year': 2006,
     'form_type': '10-K',
     'accession': '0001104659-07-019671',
     'analysis_filing_date': '2007-03-16',
     'report_date': '2006-12-31',
     'has_xbrl': False,
     'xbrl_note': 'No XBRL facts for the analysed accession in companyfacts: treated as pre-XBRL (needs '
                  'tools/statement_parser.py, D4).',
     'validity_note': 'Clean control for ISLN (FY2006, SIC 3576 vs 3572: same 3-digit SIC group, assets ratio 1.12).',
     'match_partner': 'ISLN',
     'total_assets': 153923000,
     'fiscal_year_end': '2006-12-31',
     'caveats': 'SIC 3576 vs 3572 (same 3-digit group 357). Pre-XBRL. IPO year 2006; text scan FY2006-FY2009 clean.',
     'sources': []}),
    _clean(**{'ticker': 'SHEN',
     'company_name': 'Shenandoah Telecommunications Company',
     'edgar_name': 'SHENANDOAH TELECOMMUNICATIONS CO/VA/',
     'former_names': [],
     'sic': '4813',
     'cik': '0000354963',
     'analysis_year': 2011,
     'form_type': '10-K',
     'accession': '0001140361-12-013424',
     'analysis_filing_date': '2012-03-06',
     'report_date': '2011-12-31',
     'has_xbrl': True,
     'xbrl_note': 'Analysed 10-K carries XBRL facts in companyfacts (accn match).',
     'validity_note': 'Clean control for UNTK (FY2011, SIC 4813 vs 4812: same 3-digit SIC group, assets ratio 1.38).',
     'match_partner': 'UNTK',
     'total_assets': 479979000,
     'fiscal_year_end': '2011-12-31',
     'caveats': "SIC 4813 vs 4812 (same 3-digit group 481). Text scan FY2011-FY2014: 'restatement' only in risk-factor "
                'boilerplate.',
     'sources': []}),
]

HOLDOUT2_CASES: list[dict[str, Any]] = HOLDOUT2_FRAUD + HOLDOUT2_CLEAN

_ALIASES = {"RTI": "RTIX", "SRGA": "RTIX", "ASCENT": "SYNL", "ACNT": "SYNL", "DICE": "DHX", "LOGILITY": "LGTY"}


def get_holdout2_case(ticker: str) -> dict[str, Any] | None:
    """Return a deep copy of the holdout-2 case for ``ticker`` (case-insensitive; a CIK string also matches).

    Returns ``None`` when unknown (never raises)."""
    if not ticker:
        return None
    key = str(ticker).strip().upper()
    key = _ALIASES.get(key, key)
    digits = key.lstrip("0")
    for case in HOLDOUT2_CASES:
        if case["ticker"] == key or (digits.isdigit() and case["cik"].lstrip("0") == digits):
            return copy.deepcopy(case)
    return None
