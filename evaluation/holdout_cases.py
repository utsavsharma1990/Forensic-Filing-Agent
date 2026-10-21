"""SEALED HOLDOUT: 12 known-fraud filings and 12 matched "clean" filings (v2 protocol, docs/V2_PROTOCOL.md).

DO NOT OPEN, GREP OR RUN THIS FILE (or any ticker in it) while building v2.  It may be opened only after
the v2 code freeze (docs/V2_FREEZE.md).  The selection agent never ran the forensic system on any case.

Schema
------
Mirrors ``evaluation/fraud_cases.py`` key for key (ticker, company_name, edgar_name, sic, cik (10-digit str),
analysis_year, collapsed_year / collapse_date / public_revelation_date, ground_truth, label, fraud_type,
fraud_nature, label_confidence, form_type, accession, analysis_filing_date, report_date, as_of,
strict_as_of, strict_alt, pre_revelation_valid, validity_note, has_xbrl, xbrl_note, corrected,
correction_reason, sources, caveats, spec_*, former_names, early_warning) so the evaluator can run these dicts
unchanged.  Added keys: ``match_partner`` (ticker of the matched case), ``holdout`` (always True), and
``caveats`` on fraud cases (the dev registry has it only on clean cases) and informational ``total_assets`` (USD, from XBRL ``Assets`` of the analysed filing; AIPC/RAH read from the
filing's own balance sheet), ``fiscal_year_end`` and ``revelation_sources``.  Deviations from the dev schema:
``strict_alt`` is ``None`` for every case and ``strict_as_of`` is ``None`` (the analysed filing is already the last
annual report filed before the revelation, so a strict run equals the spec run); ``collapse_date`` and
``collapsed_year`` are ``None`` for every fraud case (terminal events were not researched; the pre-registered
timing metric uses ``public_revelation_date``); ``corrected`` is always False.

Selection protocol (fixed in V2_PROTOCOL.md before any v2 change)
-----------------------------------------------------------------
FRAUD: US-listed operating companies with revenue and an SEC accounting / financial-statement fraud or
restatement-driven enforcement (administrative order, civil complaint or AAER) between 2005 and 2022, whose
first PUBLIC revelation (8-K item 4.02, audit-committee investigation notice, or earnings-release disclosure;
dated from the EDGAR filing) is later than the filing date of the LAST annual report (10-K) on EDGAR, and
that report contains the full financial statements.  The analysed filing is that report, so
``pre_revelation_valid`` is True for every fraud case.  Ambiguous candidates (short-seller allegations or
filing delays before the analysed 10-K, or no restatement / fraud finding) were dropped.  Selection used
documentation quality, those criteria and industry/year stratification only; detectability by any
detector was never examined.  The full candidate pool and reasons for every drop are in
docs/holdout_research.md.
CLEAN: one control per fraud case, same fiscal year label (D12), same 3-digit SIC where possible (10 of 12 pairs;
the other two are same 2-digit major group), total assets 0.3x-3x of the fraud company's (XBRL frames /
companyfacts), revenue > 0, a 10-K filed for the year, and no 8-K item 4.01/4.02/2.06, NT 10-K/NT 10-Q or
non-benign 10-K/A in the window FY .. FY+3 plus a text scan of the four 10-Ks FY..FY+3 for restatement,
non-boilerplate material weakness, going-concern doubt and SEC subpoena/investigation, plus web checks.
Candidates were taken in order of closeness of asset ratio; ones that failed (e.g. a material weakness in the
analysed year, an SEC order in the analysed year) were skipped and are listed in docs/holdout_research.md.

Caveats
-------
* Labels come from SEC enforcement releases and company 8-Ks.  "Clean" = no known restatement/AAER/going-concern/
  material weakness/auditor resignation found in FY..FY+3; it is NOT proof of cleanliness.
* Label strength varies: most cases have SEC fraud charges against the issuer and/or executives; Quantum is a
  controls-only settled order (restatement is the ground-truth event); Osiris's 2014 correction was small.
  ``label_confidence`` records the strength of each label.
* Revelation dates are the first public filing/press date found; earlier press or short-seller commentary
  may exist (not exhaustively searched; flagged per case where relevant).
* n = 12 + 12 gives wide confidence intervals.  XBRL era: 11 of 12 fraud and 11 of 12 clean cases; the other pair
  (AIPC FY2004, Ralcorp FY2004) is pre-XBRL and needs the statement-table parser (CONTRACTS D4).
* All 12 fraud cases are ``financial_statement`` in nature (no disclosure/claims cases were included, so the
  target of >= 80% financial_statement is met at 100%).
* Matching is on size, SIC and fiscal year only; it does not control for growth, leverage or distress.

Dates are ISO ``YYYY-MM-DD`` strings (CONTRACTS D13); CIKs are 10-digit strings.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "HOLDOUT_FRAUD",
    "HOLDOUT_CLEAN",
    "HOLDOUT_CASES",
    "get_holdout_case",
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


_XB = "Analysed 10-K carries XBRL facts in companyfacts (accn match)."
_PRE = "Pre-XBRL (FY2004): no companyfacts; needs tools/statement_parser.py (D4)."

HOLDOUT_FRAUD: list[dict[str, Any]] = [
    _fraud(
        ticker="OSIR", company_name="Osiris Therapeutics, Inc.", edgar_name="OSIRIS THERAPEUTICS, INC.",
        former_names=[], sic="2836", cik="0001360886", analysis_year=2014,
        public_revelation_date="2015-11-06",
        revelation_event=("Q3-2015 earnings release (8-K item 2.02) disclosed a review of revenue recognition on a "
                          "distributor contract; NT 10-Q 2015-11-10; 8-K item 4.02 on 2015-11-20 restated Q1-Q3 2015 "
                          "and 2014 product revenue."),
        fraud_type="Premature / improper revenue recognition (consignment, backdated documents, inflated prices)",
        fraud_nature="financial_statement",
        label_confidence="SEC civil complaint 2017-11-03 (fraud charges vs company settled $1.5M and four executives)",
        form_type="10-K", accession="0001047469-15-002532", analysis_filing_date="2015-03-20",
        report_date="2014-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note=("FY2014 10-K filed 2015-03-20, 7.5 months before the first public disclosure (2015-11-06). "
                       "An NT 10-K (2015-03-17) delayed it by 3 days for audit completion only, with no accounting "
                       "allegation."),
        match_partner="NSTG", total_assets=98118000, fiscal_year_end="2014-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1360886/000110465915076444/",
                            "https://www.sec.gov/Archives/edgar/data/1360886/000110465915080467/"],
        sources=["https://www.sec.gov/litigation/litreleases/2017/lr23978.htm",
                 "https://www.sec.gov/news/press-release/2017-207"],
        caveats=("The 2014 correction was ~$1.1M on $59.9M of 2014 product revenue (small); the FY2013 10-K disclosed a "
                 "remediated tax-accounting material weakness (so MW language is present in the analysed filing)."),
    ),
    _fraud(
        ticker="TNGO", company_name="Tangoe, Inc.", edgar_name="TANGOE INC", former_names=[],
        sic="7372", cik="0001182325", analysis_year=2014, public_revelation_date="2016-03-07",
        revelation_event=("8-K item 4.02 (event 2016-03-04, filed 2016-03-07): restatement of 2013, 2014 and Q1-Q3 2015; "
                          "FY2015 10-K never filed on time (NT 10-K 2016-03-15)."),
        fraud_type="Revenue overstated via improper recognition and artificial transactions (~$40M over 2013-2015)",
        fraud_nature="financial_statement",
        label_confidence="SEC complaint 2018-09-04 (company and three executives settled; fraud charges)",
        form_type="10-K", accession="0001047469-15-002289", analysis_filing_date="2015-03-16",
        report_date="2014-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2014 10-K filed 2015-03-16, ~12 months before the 2016-03-07 restatement notice.",
        match_partner="LPSN", total_assets=215012000, fiscal_year_end="2014-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1182325/000110465916102988/"],
        sources=["https://www.sec.gov/litigation/litreleases/2018/lr24255.htm",
                 "https://www.sec.gov/newsroom/press-releases/2018-175"],
        caveats="Misstated revenue was ~7% of reported revenue; analysed filing is the original (pre-restatement) 10-K.",
    ),
    _fraud(
        ticker="CGI", company_name="Celadon Group, Inc.", edgar_name="CELADON GROUP INC", former_names=[],
        sic="4213", cik="0000865941", analysis_year=2016, public_revelation_date="2017-05-01",
        revelation_event=("8-K items 1.01/4.02 filed 2017-05-01 (event 2017-04-25): FY2016 and Q1-Q2 FY2017 statements "
                          "no longer to be relied upon; Audit Committee investigation. NT 10-Q 2017-02-09 earlier "
                          "concerned a litigation judgement accrual, not accounting."),
        fraud_type="Concealed impairments/losses by selling and buying back trucks at inflated prices",
        fraud_nature="financial_statement",
        label_confidence="SEC civil complaint 2019-04-25 (company admitted fraud; restitution $42.2M; DOJ resolution)",
        form_type="10-K", accession="0001008886-16-000363", analysis_filing_date="2016-09-13",
        report_date="2016-06-30", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2016 (June FYE) 10-K filed 2016-09-13, 7.5 months before the 2017-05-01 non-reliance notice.",
        match_partner="LSTR", total_assets=1103290000, fiscal_year_end="2016-06-30",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/865941/000100888617000064/"],
        sources=["https://www.sec.gov/enforcement-litigation/litigation-releases/lr-24459",
                 "https://www.sec.gov/newsroom/press-releases/2019-60"],
        caveats="Misstatement ~$20M of impairments vs ~$30M pre-tax income (large relative to earnings).",
    ),
    _fraud(
        ticker="SNCR", company_name="Synchronoss Technologies, Inc.", edgar_name="SYNCHRONOSS TECHNOLOGIES INC",
        former_names=[], sic="7371", cik="0001131554", analysis_year=2016, public_revelation_date="2017-05-15",
        revelation_event=("Press release / 8-K item 7.01 (2017-05-15): Q1-2017 results delayed after a review of "
                          "accounting for prior-period transactions by new CEO/CFO and the audit committee; 8-K 4.02 "
                          "2017-06-13 (FY2016, FY2015 restated)."),
        early_warning="2017-04-27 new CEO/CFO announced (no accounting allegation); 2017-05-12 NT 10-Q.",
        fraud_type="Improper revenue recognition (no persuasive evidence, upfront license revenue); restated ~$190M cumulative revenue",
        fraud_nature="financial_statement",
        label_confidence="SEC order/complaint 2022-06-07 (company settled $12.5M; CFO and controller charged)",
        form_type="10-K", accession="0001131554-17-000037", analysis_filing_date="2017-02-27",
        report_date="2016-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2016 10-K filed 2017-02-27, ~2.5 months before the 2017-05-15 disclosure.",
        match_partner="EPAM", total_assets=1164729000, fiscal_year_end="2016-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1131554/000113155417000073/",
                            "https://www.sec.gov/Archives/edgar/data/1131554/000110465917038974/"],
        sources=["https://www.sec.gov/newsroom/press-releases/2022-101"],
        caveats="Short horizon between filing and revelation; the FY2017 10-K was only filed 2018-07-02.",
    ),
    _fraud(
        ticker="RRTS", company_name="Roadrunner Transportation Systems, Inc.",
        edgar_name="Roadrunner Transportation Systems, Inc.",
        former_names=["Roadrunner Transportation Services Holdings, Inc."], sic="4731", cik="0001440024",
        analysis_year=2015, public_revelation_date="2017-01-30",
        revelation_event=("8-K items 2.06/4.02 (2017-01-30): accounting discrepancies at two subsidiaries; prior-period "
                          "adjustments of $20-25M expected; Board investigation (opened Nov 2016)."),
        early_warning="2016-11-10 NT 10-Q cited a covenant-ratio calculation mistake (no accounting allegation).",
        fraud_type="Improperly deferred/unrecorded expenses and unreconciled balances to hit earnings targets (2013-2017)",
        fraud_nature="financial_statement",
        label_confidence="SEC settled order vs company (disgorgement ~$7.1M + $2.5M interest); 2019 SEC fraud charges vs former CFO and two employees",
        form_type="10-K", accession="0001440024-16-000049", analysis_filing_date="2016-03-01",
        report_date="2015-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2015 10-K filed 2016-03-01, 8 months before the first hint (2016-11-10) and 11 months before 2017-01-30.",
        match_partner="HUBG", total_assets=1326125000, fiscal_year_end="2015-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1440024/000144002417000002/",
                            "https://www.sec.gov/Archives/edgar/data/1440024/000144002416000074/"],
        sources=["https://www.sec.gov/newsroom/press-releases/2019-51"],
        caveats="An NT 10-K was filed the same day (2016-03-01) as the 10-K; its text contains no reason.",
    ),
    _fraud(
        ticker="GVA", company_name="Granite Construction Incorporated", edgar_name="GRANITE CONSTRUCTION INC",
        former_names=[], sic="1600", cik="0000861459", analysis_year=2018, public_revelation_date="2020-03-02",
        revelation_event=("2020-03-02 press release (8-K 2.02): Audit/Compliance Committee investigation of prior-period "
                          "reporting at the Heavy Civil Operating Group; 10-K delayed (NT 10-K 2020-03-03); 2017-2019 "
                          "later restated."),
        fraud_type="Improper deferral of expected costs in project forecasts (percentage-of-completion revenue)",
        fraud_nature="financial_statement",
        label_confidence="SEC order/complaint 2022 (company $12M penalty; fraud charges, injunction)",
        form_type="10-K", accession="0001564590-19-003791", analysis_filing_date="2019-02-22",
        report_date="2018-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2018 10-K filed 2019-02-22, ~12 months before the 2020-03-02 disclosure.",
        match_partner="MTZ", total_assets=2476601000, fiscal_year_end="2018-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/861459/000143774920004057/",
                            "https://www.sec.gov/Archives/edgar/data/861459/000143774920004188/"],
        sources=["https://www.sec.gov/newsroom/press-releases/2022-150",
                 "https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25507"],
        caveats="Largest fraud company in the set (assets $2.5B); the only other SIC-160 peer in range (KBR) had an SEC order in the analysed year (see matching table).",
    ),
    _fraud(
        ticker="USAT", company_name="USA Technologies, Inc. (now Cantaloupe, Inc.)", edgar_name="CANTALOUPE, INC.",
        former_names=["USA TECHNOLOGIES INC"], sic="3578", cik="0000896429", analysis_year=2017,
        public_revelation_date="2018-09-11",
        revelation_event=("2018-09-11 press release (8-K 8.01): FY2018 10-K delayed; Audit Committee internal "
                          "investigation of contractual arrangements and their accounting; NT 10-K 2018-09-13; 8-K 4.02 "
                          "2019-02-06 (FY2017 and FY2018 quarters restated)."),
        fraud_type="Bill-and-hold sales and shipments of unordered devices to inflate quarterly revenue",
        fraud_nature="financial_statement",
        label_confidence="SEC settled order 2023 (company $1.5M penalty; two former officers charged)",
        form_type="10-K", accession="0001558370-17-006780", analysis_filing_date="2017-08-23",
        report_date="2017-06-30", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2017 (June FYE) 10-K filed 2017-08-23, ~12.5 months before the 2018-09-11 disclosure.",
        match_partner="ALOT", total_assets=97691000, fiscal_year_end="2017-06-30",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/896429/000114036118038228/"],
        sources=["https://www.sec.gov/enforcement-litigation/administrative-proceedings/33-11202-s"],
        caveats=("The analysed 10-K already discloses an earlier, different problem (material weakness at 2015/2016 FYEs "
                 "and an associated class action); the FY2017 restatement was ~$2.56M (SEC: $4.61M total, 3.5% overstatement)."),
    ),
    _fraud(
        ticker="QTM", company_name="Quantum Corporation", edgar_name="QUANTUM CORP /DE/", former_names=[],
        sic="3572", cik="0000709283", analysis_year=2017, public_revelation_date="2018-02-08",
        revelation_event=("2018-02-08 press release/8-K: Q3 FY2018 results postponed; NT 10-Q 2018-02-12 discloses an SEC "
                          "subpoena (2018-01-11) on revenue-recognition accounting and controls; 8-K 4.02 2018-09-14 "
                          "restated FY2015-FY2017 and quarters."),
        fraud_type="Revenue recognised on channel-partner deals with undisclosed side terms (repeated recognition errors)",
        fraud_nature="financial_statement",
        label_confidence=("restatement + SEC settled order 34-87812 (internal accounting controls violations, $1M penalty); "
                          "no fraud finding against the issuer"),
        form_type="10-K", accession="0001628280-17-006127", analysis_filing_date="2017-06-01",
        report_date="2017-03-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="FY2017 (March FYE) 10-K filed 2017-06-01, 8 months before the 2018-02-08 disclosure.",
        match_partner="MITK", total_assets=225027000, fiscal_year_end="2017-03-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/709283/000162828018001297/",
                            "https://www.sec.gov/Archives/edgar/data/709283/000162828018001442/",
                            "https://www.sec.gov/Archives/edgar/data/709283/000119312518274209/"],
        sources=["https://www.sec.gov/enforcement-litigation/administrative-proceedings/34-87812-s"],
        caveats="Weakest label in the set: controls-only SEC order; restatement is the ground-truth event.",
    ),
    _fraud(
        ticker="OFIX", company_name="Orthofix International N.V. (now Orthofix Medical Inc.)",
        edgar_name="Orthofix Medical Inc.", former_names=["ORTHOFIX INTERNATIONAL N V"], sic="3841",
        cik="0000884624", analysis_year=2012, public_revelation_date="2013-07-29",
        revelation_event=("2013-07-29 press release (8-K 8.01 filed 2013-07-30): Audit Committee independent review of "
                          "revenue recognition; 8-K 4.02 filed 2013-08-07; FY2012 10-K/A filed 2014-03-24."),
        fraud_type="Premature revenue recognition (shipment before contingencies resolved) incl. Spine segment and Brazil subsidiary",
        fraud_nature="financial_statement",
        label_confidence="SEC settled order 2017-01 (company admitted wrongdoing; $14M incl. FCPA; misstatements 2011-Q1 2013)",
        form_type="10-K", accession="0001193125-13-087561", analysis_filing_date="2013-03-01",
        report_date="2012-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Original FY2012 10-K filed 2013-03-01, 5 months before the 2013-07-29 disclosure.",
        match_partner="ICUI", total_assets=504281000, fiscal_year_end="2012-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/884624/000119312513308166/",
                            "https://www.sec.gov/Archives/edgar/data/884624/000119312513322803/"],
        sources=["https://www.sec.gov/newsroom/press-releases/2017-18",
                 "https://www.sec.gov/files/litigation/admin/2017/33-10281.pdf"],
        caveats="Order combines accounting and FCPA (Brazil) findings; legacy HHS-OIG subpoena (Blackstone) disclosed in the 10-K.",
    ),
    _fraud(
        ticker="LIME", company_name="Lime Energy Co.", edgar_name="LIME ENERGY CO.",
        former_names=["ELECTRIC CITY CORP"], sic="1700", cik="0001065860", analysis_year=2011,
        public_revelation_date="2012-07-17",
        revelation_event=("8-K item 4.02 (event 2012-07-15, filed 2012-07-17): FY2010, FY2011 and Q1-2012 statements "
                          "should not be relied upon; some revenue improperly recorded."),
        fraud_type="Revenue booked early or on non-existent jobs (~$20M over 2010-2012)",
        fraud_nature="financial_statement",
        label_confidence="SEC complaint 2016 (company $1M settlement; four former executives charged)",
        form_type="10-K", accession="0001104659-12-018932", analysis_filing_date="2012-03-16",
        report_date="2011-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Original FY2011 10-K filed 2012-03-16, 4 months before the 2012-07-17 notice.",
        match_partner="AGX", total_assets=99554000, fiscal_year_end="2011-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1065860/000110465912049223/"],
        sources=["https://www.sec.gov/news/pressrelease/2016-218.html",
                 "https://www.sec.gov/files/litigation/complaints/2016/comp-pr2016-218.pdf"],
        caveats="Smallest fraud company (assets ~$100M); net losses in the analysed year already.",
    ),
    _fraud(
        ticker="TEUM", company_name="Pareteum Corporation", edgar_name="PARETEUM Corp",
        former_names=["ELEPHANT TALK COMMUNICATIONS CORP", "ELEPHANT TALK COMMUNICATIONS INC", "STARUNI CORP"],
        sic="7373", cik="0001084384", analysis_year=2018, public_revelation_date="2019-10-21",
        revelation_event=("8-K item 4.02 (2019-10-21): FY2018 and Q1-Q2 2019 financial statements should no longer be "
                          "relied upon; FY2018 restated 2020-12-14."),
        fraud_type="Revenue recorded from non-binding purchase orders; auditor confirmation process manipulated",
        fraud_nature="financial_statement",
        label_confidence="SEC settled order 2021 (company) and complaint 2023 (three former executives; fraud charges)",
        form_type="10-K", accession="0001144204-19-014694", analysis_filing_date="2019-03-18",
        report_date="2018-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Original FY2018 10-K filed 2019-03-18, 7 months before the 2019-10-21 notice.",
        match_partner="BAND", total_assets=161041166, fiscal_year_end="2018-12-31",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/1084384/000110465919055290/"],
        sources=["https://www.sec.gov/enforce/33-10975-s",
                 "https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25860"],
        caveats=("Earlier press/short-seller commentary in 2019 was NOT exhaustively searched (8-Ks between filing and "
                 "revelation show none). The analysed 10-K itself reports material weaknesses at 2018-12-31. Assets "
                 "jumped 6x in 2018 (acquisitions)."),
    ),
    _fraud(
        ticker="PTRY", company_name="American Italian Pasta Company", edgar_name="AMERICAN ITALIAN PASTA CO",
        former_names=[], sic="2090", cik="0000849667", analysis_year=2004, public_revelation_date="2005-08-09",
        revelation_event=("2005-08-09 press release (8-K 2.02/2.06 filed 2005-08-11): third-quarter results and 10-Q "
                          "delayed, Audit Committee investigation of accounting practices; 8-K 4.02 2005-10-25 "
                          "(FY2002-FY2004 and quarters not to be relied upon)."),
        fraud_type="Overstated pre-tax income FY2002-Q2 FY2004 (~$59M, 66%) via improper accounting adjustments",
        fraud_nature="financial_statement",
        label_confidence="SEC complaint + AAER 2008-09-15 (company and former CEO/CFO/others; fraud charges)",
        form_type="10-K", accession="0000922907-04-000547", analysis_filing_date="2004-12-15",
        report_date="2004-10-01", has_xbrl=False, xbrl_note=_PRE,
        validity_note="FY2004 (FYE 2004-10-01) 10-K filed 2004-12-15, 8 months before the 2005-08-09 disclosure.",
        match_partner="RAH", total_assets=748410000, fiscal_year_end="2004-10-01",
        revelation_sources=["https://www.sec.gov/Archives/edgar/data/849667/000092290705000482/",
                            "https://www.sec.gov/Archives/edgar/data/849667/000092290705000683/"],
        sources=["https://www.sec.gov/enforcement-litigation/litigation-releases/lr-20715",
                 "https://www.sec.gov/news/press/2008/2008-200.htm"],
        caveats=("Only pre-XBRL case; the SEC-alleged scheme ran FY2002-Q2 FY2004, so only the first half of FY2004 was "
                 "affected, but the 4.02 notice covers FY2004 as well. Assets read from the filing's own balance sheet "
                 "(total assets $748,410K)."),
    ),
]

HOLDOUT_CLEAN: list[dict[str, Any]] = [
    _clean(
        ticker="NSTG", company_name="NanoString Technologies, Inc. (EDGAR: NS Wind Down Co., Inc.)",
        edgar_name="NS Wind Down Co., Inc.", former_names=["NanoString Technologies Inc"], sic="2836",
        cik="0001401708", analysis_year=2014, form_type="10-K", accession="0001193125-15-091371",
        analysis_filing_date="2015-03-13", report_date="2014-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for OSIR (FY2014, SIC 2836, assets ratio 1.05).",
        match_partner="OSIR", total_assets=102748000, fiscal_year_end="2014-12-31",
        caveats=("Text scan of the FY2014-FY2017 10-Ks: no restatement, material weakness, going-concern doubt or SEC "
                 "subpoena. The EDGAR name reflects later wind-down events outside the FY..FY+3 window (not researched)."),
        sources=[],
    ),
    _clean(
        ticker="LPSN", company_name="LivePerson, Inc.", edgar_name="LIVEPERSON INC", former_names=[],
        sic="7372", cik="0001102993", analysis_year=2014, form_type="10-K", accession="0001628280-15-001726",
        analysis_filing_date="2015-03-12", report_date="2014-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for TNGO (FY2014, SIC 7372, assets ratio 1.12). Skipped Imperva (material weakness at 2014-09-30).",
        match_partner="TNGO", total_assets=239817000, fiscal_year_end="2014-12-31",
        caveats=("Only amendment in window is a 10-K/A (2016-01-22) revising the auditor consent date. Text scan FY2014-FY2017 "
                 "found only audit-report boilerplate."),
        sources=[],
    ),
    _clean(
        ticker="LSTR", company_name="Landstar System, Inc.", edgar_name="LANDSTAR SYSTEM INC", former_names=[],
        sic="4213", cik="0000853816", analysis_year=2016, form_type="10-K", accession="0001193125-17-056249",
        analysis_filing_date="2017-02-24", report_date="2016-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note=("Clean control for CGI (FY2016, SIC 4213, assets ratio 0.99). Calendar-year FYE vs Celadon's June FYE: "
                       "same fiscal-year label, ~6 months later as_of."),
        match_partner="CGI", total_assets=1096591000, fiscal_year_end="2016-12-31",
        caveats="Asset-light truckload/brokerage model differs from Celadon's asset-heavy fleet. Text scan found only an ASC 606 'not restated' note.",
        sources=[],
    ),
    _clean(
        ticker="EPAM", company_name="EPAM Systems, Inc.", edgar_name="EPAM Systems, Inc.",
        former_names=["EPAM SYSTEMS INC"], sic="7371", cik="0001352010", analysis_year=2016, form_type="10-K",
        accession="0001352010-17-000006", analysis_filing_date="2017-03-01", report_date="2016-12-31",
        has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for SNCR (FY2016, SIC 7371, assets ratio 0.80).",
        match_partner="SNCR", total_assets=925811000, fiscal_year_end="2016-12-31",
        caveats="FY2018 10-K 'restated' prior cash-flow presentation for ASU 2016-18 adoption (presentation change, not an error).",
        sources=[],
    ),
    _clean(
        ticker="HUBG", company_name="Hub Group, Inc.", edgar_name="Hub Group, Inc.",
        former_names=["Hub Group", "HUB GROUP INC"], sic="4731", cik="0000940942", analysis_year=2015,
        form_type="10-K", accession="0001564590-16-013549", analysis_filing_date="2016-02-26",
        report_date="2015-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for RRTS (FY2015, SIC 4731, assets ratio 0.98).",
        match_partner="RRTS", total_assets=1301146000, fiscal_year_end="2015-12-31",
        caveats=("A 10-K/A (2018-01-05) for FY2016 only added a date to the Section 906 certification. Hub restated in 2002 "
                 "and again for 2025 quarters (both far outside the window)."),
        sources=[],
    ),
    _clean(
        ticker="MTZ", company_name="MasTec, Inc.", edgar_name="MASTEC INC", former_names=["BURNUP & SIMS INC"],
        sic="1623", cik="0000015615", analysis_year=2018, form_type="10-K", accession="0000015615-19-000011",
        analysis_filing_date="2019-02-28", report_date="2018-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note=("Clean control for GVA (FY2018, SIC 1623 vs 1600: same 2-digit major group 16 only, because SIC 160 has no "
                       "passing peer; assets ratio 1.79). Skipped KBR (SEC order in analysed year) and Primoris (SEC ICFR order 2018-09)."),
        match_partner="GVA", total_assets=4439953000, fiscal_year_end="2018-12-31",
        caveats=("MasTec had a 2014-15 Audit Committee investigation of percentage-of-completion estimates and an SEC formal "
                 "investigation closed with no enforcement action (notice 2016-11-16), i.e. before the analysed year. "
                 "Text scan FY2018-FY2021 clean."),
        sources=["https://www.sec.gov/Archives/edgar/data/0000015615/000001561516000093/mtz12311510-k.htm"],
    ),
    _clean(
        ticker="ALOT", company_name="AstroNova, Inc.", edgar_name="AstroNova, Inc.", former_names=["ASTRO MED INC /NEW/"],
        sic="3577", cik="0000008146", analysis_year=2017, form_type="10-K", accession="0001193125-18-113108",
        analysis_filing_date="2018-04-10", report_date="2018-01-31", has_xbrl=True, xbrl_note=_XB,
        validity_note=("Clean control for USAT (SEC fy=2017 for FYE 2018-01-31 per D12; SIC 3577 vs 3578, assets ratio 1.25). "
                       "Fiscal-year end is 7 months after USAT's."),
        match_partner="USAT", total_assets=122313000, fiscal_year_end="2018-01-31",
        caveats="A web-search excerpt of its FY2018 10-K mentions an accounting error judged immaterial to prior periods (no restatement, no 8-K 4.02).",
        sources=[],
    ),
    _clean(
        ticker="MITK", company_name="Mitek Systems, Inc.", edgar_name="MITEK SYSTEMS INC", former_names=[],
        sic="3577", cik="0000807863", analysis_year=2017, form_type="10-K", accession="0000807863-17-000080",
        analysis_filing_date="2017-11-30", report_date="2017-09-30", has_xbrl=True, xbrl_note=_XB,
        validity_note=("Clean control for QTM (FY2017, SIC 3577 vs 3572, assets ratio 0.32 - near the lower bound). Skipped Digi "
                       "International (material weakness remediated in FY2017)."),
        match_partner="QTM", total_assets=71719000, fiscal_year_end="2017-09-30",
        caveats=("Mitek later restated interim periods (2022-10 and 2023-05) and faces an SEC investigation; these fall outside the "
                 "FY2017..FY2020 window."),
        sources=[],
    ),
    _clean(
        ticker="ICUI", company_name="ICU Medical, Inc.", edgar_name="ICU MEDICAL INC/DE", former_names=[],
        sic="3841", cik="0000883984", analysis_year=2012, form_type="10-K", accession="0000883984-13-000016",
        analysis_filing_date="2013-02-26", report_date="2012-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for OFIX (FY2012, SIC 3841, assets ratio 0.85).",
        match_partner="OFIX", total_assets=428512000, fiscal_year_end="2012-12-31",
        caveats="10-K/A of 2015-04-30 (FY2014) only added Part III. Text scan FY2012-FY2015 clean.",
        sources=[],
    ),
    _clean(
        ticker="AGX", company_name="Argan, Inc.", edgar_name="ARGAN INC", former_names=["PUROFLOW INC"],
        sic="1700", cik="0000100591", analysis_year=2011, form_type="10-K", accession="0001193125-12-161077",
        analysis_filing_date="2012-04-13", report_date="2012-01-31", has_xbrl=True, xbrl_note=_XB,
        validity_note=("Clean control for LIME (SEC fy=2011 for FYE 2012-01-31, SIC 1700, assets ratio 2.06 - the only passing peer "
                       "in SIC 170). Fiscal-year end is one month after Lime's."),
        match_partner="LIME", total_assets=205252000, fiscal_year_end="2012-01-31",
        caveats=("10-K/A filings in 2014 re-filed Item 8 for FY Jan-2014 without restatement; Argan restated FY2005 (long before the "
                 "window). Moved Nasdaq to NYSE in 2013."),
        sources=[],
    ),
    _clean(
        ticker="BAND", company_name="Bandwidth Inc.", edgar_name="Bandwidth Inc.", former_names=["Bandwidth.com, Inc."],
        sic="7372", cik="0001514416", analysis_year=2018, form_type="10-K", accession="0001514416-19-000011",
        analysis_filing_date="2019-02-15", report_date="2018-12-31", has_xbrl=True, xbrl_note=_XB,
        validity_note="Clean control for TEUM (FY2018, SIC 7372 vs 7373, assets ratio 0.93).",
        match_partner="TEUM", total_assets=150420000, fiscal_year_end="2018-12-31",
        caveats="Text scan FY2018-FY2021 shows only risk-factor boilerplate on restatements/subpoenas.",
        sources=[],
    ),
    _clean(
        ticker="RAH", company_name="Ralcorp Holdings, Inc.", edgar_name="RALCORP HOLDINGS INC /MO",
        former_names=["NEW RALCORP HOLDINGS INC"], sic="2040", cik="0001029506", analysis_year=2004, form_type="10-K",
        accession="0001068800-04-000720", analysis_filing_date="2004-12-14", report_date="2004-09-30", has_xbrl=False,
        xbrl_note=_PRE,
        validity_note=("Clean control for PTRY (FY2004, SIC 2040 vs 2090: same 2-digit group 20 only, since the only SIC-209 "
                       "peers in range (Reddy Ice restated in its FY2004 10-K; McCormick >3x) fail; assets ratio 1.63 from the "
                       "filing's balance sheet ($1,221.6M)."),
        match_partner="PTRY", total_assets=1221600000, fiscal_year_end="2004-09-30",
        caveats=("'Restatement' mentions in its 10-Ks concern an equity investee (Vail Resorts); the 2007 8-K 4.01 concerned its "
                 "savings plan's auditor only. Pre-XBRL."),
        sources=[],
    ),
]

HOLDOUT_CASES: list[dict[str, Any]] = HOLDOUT_FRAUD + HOLDOUT_CLEAN

_ALIASES = {"QMCO": "QTM", "PRTM": "TEUM", "CTLP": "USAT", "NS WIND DOWN": "NSTG", "NNOCQ": "NSTG"}


def get_holdout_case(ticker: str) -> dict[str, Any] | None:
    """Return a deep copy of the holdout case for ``ticker`` (case-insensitive; a CIK string also matches).

    Returns ``None`` when unknown (never raises)."""
    if not ticker:
        return None
    key = str(ticker).strip().upper()
    key = _ALIASES.get(key, key)
    digits = key.lstrip("0")
    for case in HOLDOUT_CASES:
        if case["ticker"] == key or (digits.isdigit() and case["cik"].lstrip("0") == digits):
            return copy.deepcopy(case)
    return None
