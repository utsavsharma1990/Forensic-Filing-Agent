"""Point-in-time SIC peer discovery.

Pipeline (all SEC traffic goes through :mod:`tools.edgar_api`: rate limited and disk cached)

1. Company identity / SIC from submissions; own TotalAssets for ``focus_year`` as originally reported by ``as_of``.
2. SIC universe: the browse-edgar SIC listing (``edgar_api.find_company_by_sic``; verified live) compacted into a
   local index ``.cache/peers/sic_<code>.json`` with an explicit TTL (:func:`build_sic_index`). If the listing is
   empty/blocked we fall back to a bounded submissions-based SIC check of size-matched candidates.
3. Size universe: XBRL frames ``us-gaap/Assets/USD/CY<y>Q<q>I`` (one call per quarter-end, compacted and cached).
   Used only to pre-rank candidates by log-assets distance (frames hold the latest filed value, so it is NOT
   point-in-time and never used for the final numbers).
4. Verification of the closest candidates (bounded): an annual filing for ``focus_year`` filed <= ``as_of`` must
   exist and XBRL facts for that year as originally reported by ``as_of`` must contain TotalAssets and Revenue in USD
   within ``size_band``. Peers never use the company's data; the company is excluded; later filings are ignored.

Ordering is deterministic: tier (same 4-digit SIC first, then 3-digit, then 2-digit major group when needed) then |ln(assets/own assets)|, then CIK.

Caveats: SIC codes in the listing are the CURRENT SIC of each registrant (EDGAR keeps no SIC history), so a company
that changed SIC after ``as_of`` may be mis-grouped; the 10-K type filter of the listing excludes pure 20-F filers.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Optional

from tools import common, edgar_api, xbrl_parser

log = common.get_logger("peer_finder")

VERSION = "pf1"
SIC_INDEX_TTL_S = 7 * 86400
FRAMES_TTL_S = 7 * 86400
RESULT_TTL_S = 24 * 3600
MIN_XBRL_YEAR = 2009
ANNUAL_10K = ("10-K", "10-K405", "10-KSB")
MIN_PEERS_BEFORE_WIDENING = 3   # fewer than this inside the requested band -> widen once (flagged per peer)
WIDEN_FACTOR = 5.0


class PeerList(list):
    """A plain ``list`` of peer dicts that also carries ``.reason`` (why it is empty / short) and ``.diagnostics``."""

    reason: Optional[str] = None
    diagnostics: dict

    def __init__(self, items=(), reason: Optional[str] = None, diagnostics: Optional[dict] = None):
        super().__init__(items)
        self.reason = reason
        self.diagnostics = diagnostics or {}


# ------------------------------------------------------------------ small cache helpers
def _dir() -> Path:
    d = Path(common.CACHE_DIR) / "peers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(path: Path, ttl_s: float) -> Optional[Any]:
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl_s:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # corrupt cache -> rebuild
        return None
    return None


def _write(path: Path, obj: Any) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # cache is best effort
        log.warning("peer cache write failed %s: %s", path, exc)


# ------------------------------------------------------------------ SIC index
def _list_sic(sic: str, limit: int) -> set[str]:
    """Page through the browse-edgar SIC atom feed (verified live). edgar_api.find_company_by_sic stops after 1000 rows,
    which truncates big SICs (7372 has several thousand registrants), so we page here with the same rate-limited client."""
    out: set[str] = set()
    client = edgar_api.get_client()
    start = 0
    while start < limit:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&SIC={sic}&type=10-K&owner=include&count=100&start={start}&output=atom")
        try:
            body = client.get_text(url)
        except edgar_api.EdgarError as exc:
            log.warning("SIC listing %s start=%s failed: %s", sic, start, exc)
            break
        found = {edgar_api.pad_cik(m) for m in re.findall(r"<cik>\s*0*(\d+)\s*</cik>", body, flags=re.I)}
        if not found or found <= out:
            break
        out |= found
        start += 100
    return out


def build_sic_index(sic: str, *, force: bool = False, ttl_s: float = SIC_INDEX_TTL_S, limit: int = 3000) -> list[str]:
    """CIKs (10-digit) listed under a 4-digit SIC. Cached in ``.cache/peers/sic_<sic>.json`` for ``ttl_s``."""
    sic = str(sic).strip()
    path = _dir() / f"sic_{sic}.json"
    if not force:
        hit = _read(path, ttl_s)
        if hit is not None:
            return list(hit.get("ciks") or [])
    ciks = sorted(_list_sic(sic, limit))
    if ciks:  # never cache an empty (possibly throttled) answer
        _write(path, {"sic": sic, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "ciks": ciks})
    return ciks


# ------------------------------------------------------------------ frames
def _quarter_ends(year: int, month: int) -> list[tuple[int, int]]:
    """The 4 quarter periods (calendar year, quarter) ending at the quarter that contains (year, month), newest first."""
    q = (month - 1) // 3 + 1
    out = []
    y = year
    for _ in range(4):
        out.append((y, q))
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


def _frame_assets(year: int, q: int) -> dict[int, tuple[float, str]]:
    """{cik_int: (assets, end_date)} from the XBRL frame; cached compactly. Empty dict if no frame exists."""
    path = _dir() / f"frames_assets_CY{year}Q{q}I.json"
    hit = _read(path, FRAMES_TTL_S)
    if hit is None:
        url = f"https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY{year}Q{q}I.json"
        try:
            raw = edgar_api.get_client().get_json(url)
        except edgar_api.EdgarNotFound:
            raw = {}
        rows = raw.get("data") or []
        hit = {str(r["cik"]): [r["val"], r.get("end", "")] for r in rows if r.get("val") is not None and r.get("cik") is not None}
        if hit:
            _write(path, hit)
    return {int(k): (float(v[0]), v[1]) for k, v in hit.items()}


# ------------------------------------------------------------------ helpers
def _own_assets(cik: str, focus_year: int, as_of: Optional[str]) -> tuple[Optional[float], Optional[str], Optional[str], dict]:
    cf = edgar_api.get_companyfacts(cik)
    af = xbrl_parser.extract_annual_facts(cf, [focus_year], as_of=as_of)
    by = af["by_year"].get(focus_year) or {}
    ta = by.get("TotalAssets")
    return (ta["value"] if ta else None), af.get("unit"), (af.get("period_end") or {}).get(focus_year), af


def _verify(c_int: int, focus_year: int, as_of: Optional[str], own_assets: float, band: tuple[float, float],
            sic_expected: Optional[str], why: dict, allow_prior_year: bool = True) -> Optional[dict]:
    """Point-in-time verification of one candidate; ``why`` collects skip reasons. Returns the peer dict or None.

    The peer's data year is ``focus_year`` if its annual report for that year was filed by ``as_of``; otherwise (a
    June-FYE company analysed at its filing date cannot see December peers' same-year 10-K) the preceding year's
    report, recorded as ``fiscal_year`` / ``year_offset`` (never later data)."""
    cik = edgar_api.pad_cik(c_int)
    try:
        allf = edgar_api.list_annual_filings(cik, as_of=as_of, forms=ANNUAL_10K)
    except Exception as exc:
        why[cik] = f"submissions error: {type(exc).__name__}"
        return None
    years = [focus_year] + ([focus_year - 1] if allow_prior_year else [])
    peer_year, filings = None, []
    for y in years:
        filings = [f for f in allf if f.get("fiscal_year") == y]
        if filings:
            peer_year = y
            break
    if peer_year is None:
        why[cik] = f"no FY{focus_year} (or prior) annual filing filed by {as_of or 'today'}"
        return None
    try:
        sub = edgar_api.get_submissions(cik)
        cf = edgar_api.get_companyfacts(cik)
    except Exception as exc:
        why[cik] = f"fetch error: {type(exc).__name__}"
        return None
    sic = str(sub.get("sic") or "")
    if sic_expected and not sic.startswith(sic_expected):
        why[cik] = f"SIC {sic} outside prefix {sic_expected}"
        return None
    af = xbrl_parser.extract_annual_facts(cf, [peer_year], as_of=as_of)
    by = af["by_year"].get(peer_year) or {}
    if not by:
        why[cik] = f"no XBRL facts for FY{peer_year} as of as_of"
        return None
    if af.get("unit") != "USD":
        why[cik] = f"unit {af.get('unit')} != USD"
        return None
    ta, rev = by.get("TotalAssets"), by.get("Revenue")
    if not ta or ta["value"] is None or ta["value"] <= 0:
        why[cik] = "TotalAssets missing"
        return None
    if not rev:
        why[cik] = "Revenue missing"
        return None
    ratio = ta["value"] / own_assets
    if not (band[0] <= ratio <= band[1]):
        why[cik] = f"assets ratio {ratio:.3g} outside band"
        return None
    tickers = sub.get("tickers") or []
    return {"ticker": (tickers[0] if tickers else ""), "name": sub.get("name") or "", "cik": cik, "sic": sic,
            "assets": float(ta["value"]), "assets_ratio": round(ratio, 6), "fiscal_year": peer_year,
            "year_offset": focus_year - peer_year, "filing_date": filings[0]["filing_date"],
            "period_end": (af.get("period_end") or {}).get(peer_year)}


def _empty(reason: str, diag: Optional[dict] = None) -> PeerList:
    log.info("find_peers -> [] (%s)", reason)
    return PeerList([], reason, diag or {})


# ------------------------------------------------------------------ public API
def find_peers(cik: Any, sic: Optional[str] = None, as_of: Optional[str] = None, focus_year: Optional[int] = None,
               n: int = 8, size_band: tuple[float, float] = (0.1, 10), *, use_cache: bool = True,
               max_checks: Optional[int] = None) -> PeerList:
    """Up to ``n`` point-in-time SIC peers: ``[{"ticker","name","cik","sic","assets", ...extras}]`` (a ``list`` subclass
    with ``.reason`` / ``.diagnostics``). Returns an empty list with ``.reason`` (never raises) for pre-XBRL focus years,
    non-USD reporters, missing own facts or discovery failures."""
    try:
        cik = edgar_api.pad_cik(cik)
        key = f"{VERSION}_{cik}_{sic or ''}_{as_of or 'latest'}_{focus_year or 'auto'}_{n}_{size_band[0]}_{size_band[1]}"
        path = _dir() / f"result_{key}.json"
        if use_cache:
            hit = _read(path, RESULT_TTL_S)
            if hit is not None:
                return PeerList(hit["peers"], hit.get("reason"), hit.get("diagnostics"))
        res = _find(cik, sic, as_of, focus_year, n, tuple(size_band), max_checks)
        if res.reason is None or not res.reason.startswith("error"):
            _write(path, {"peers": list(res), "reason": res.reason, "diagnostics": res.diagnostics})
        return res
    except Exception as exc:  # never raise
        log.warning("find_peers failed: %s", exc)
        return _empty(f"error: {type(exc).__name__}: {exc}")


def _find(cik: str, sic: Optional[str], as_of: Optional[str], focus_year: Optional[int], n: int,
          band: tuple[float, float], max_checks: Optional[int]) -> PeerList:
    diag: dict = {"as_of": as_of}
    if not focus_year:
        fil = [f for f in edgar_api.list_annual_filings(cik, as_of=as_of) if f.get("fiscal_year")]
        if not fil:
            return _empty("no annual filings found as of as_of", diag)
        focus_year = max(f["fiscal_year"] for f in fil)
    diag["focus_year"] = focus_year
    if focus_year < MIN_XBRL_YEAR:
        return _empty(f"pre-XBRL focus year {focus_year} (< {MIN_XBRL_YEAR}): no companyfacts/frames for peers", diag)
    if not sic:
        try:
            sic = str(edgar_api.get_submissions(cik).get("sic") or "")
        except Exception as exc:
            return _empty(f"error: cannot resolve SIC ({type(exc).__name__})", diag)
    if not sic or not sic.isdigit():
        return _empty("SIC unavailable for company", diag)
    sic = sic.zfill(4)
    diag["sic"] = sic

    own, unit, period_end, af = _own_assets(cik, focus_year, as_of)
    if own is None or own <= 0:
        return _empty(f"no XBRL TotalAssets for FY{focus_year} as of {as_of or 'now'} (pre-XBRL or not yet filed)", diag)
    if unit != "USD":
        return _empty(f"reporting currency {unit} != USD: asset-size matching against USD peers is not meaningful "
                      f"(compare ratios only; no peers selected)", {**diag, "unit": unit})
    diag["own_assets"] = own
    pe = period_end or f"{focus_year}-12-31"
    py, pm = int(pe[:4]), int(pe[5:7])

    # --- size universe (frames, closest quarter first; first frame that has a cik wins)
    assets_by_cik: dict[int, float] = {}
    for (fy_, q) in _quarter_ends(py, pm):
        for k, (v, _end) in _frame_assets(fy_, q).items():
            if k not in assets_by_cik and v > 0:
                assets_by_cik[k] = v
    diag["frames_ciks"] = len(assets_by_cik)
    if not assets_by_cik:
        return _empty("XBRL frames unavailable for the focus period", diag)

    own_int = int(cik)
    checks_cap = max_checks or max(30, 6 * n)
    checks = 0
    why: dict[str, str] = {}
    peers: list[dict] = []
    seen_stage: set[int] = set()
    sic_sets: dict[int, set[int]] = {}

    def listing(code: str) -> set[int]:
        return {int(x) for x in build_sic_index(code)}

    sic_sets[4] = listing(sic)
    diag["sic4_listing_size"] = len(sic_sets[4])
    fallback = not sic_sets[4]
    if fallback:
        diag["sic_listing"] = "empty: falling back to bounded submissions-based SIC check"

    def tier_members(tier: int) -> Optional[set[int]]:
        if fallback:
            return None
        if tier not in sic_sets:
            prefix = sic[:3] if tier == 3 else sic[:2]
            codes = [prefix + str(d) for d in range(10)] if tier == 3 else [f"{prefix}{a}{b}" for a in range(10) for b in range(10)]
            acc: set[int] = set()
            for code in codes:
                if code != sic:
                    acc |= listing(code)
            sic_sets[tier] = acc | sic_sets[4]
            diag[f"sic{tier}_listing_size"] = len(sic_sets[tier])
        return sic_sets[tier]

    def run_stage(stage_band: tuple[float, float], widened: bool) -> None:
        nonlocal checks
        lo, hi = stage_band[0] / 2.0, stage_band[1] * 2.0  # frames are approximate (not point-in-time): prefilter wider
        ranked = sorted(((abs(math.log(v / own_assets)), k) for k, v in assets_by_cik.items()
                         if k != own_int and lo <= v / own_assets <= hi), key=lambda t: (t[0], t[1]))
        for tier, expected in ((4, sic), (3, sic[:3]), (2, sic[:2])):
            if len(peers) >= n:
                return
            members = tier_members(tier)
            for _d, k in ranked:
                if len(peers) >= n or checks >= checks_cap:
                    return
                if k in seen_stage or (members is not None and k not in members):
                    continue
                seen_stage.add(k)
                checks += 1
                p = _verify(k, focus_year, as_of, own_assets, stage_band, expected, why)
                if p:
                    p["tier"] = 4 if p["sic"] == sic else (3 if p["sic"][:3] == sic[:3] else 2)
                    p["band_widened"] = widened
                    peers.append(p)
            if fallback:
                return

    own_assets = own
    run_stage(band, False)
    if len(peers) < MIN_PEERS_BEFORE_WIDENING:
        wide = (band[0] / WIDEN_FACTOR, band[1] * WIDEN_FACTOR)
        diag["band_widened_to"] = wide
        seen_stage.clear()
        for k in {int(p["cik"]) for p in peers}:
            seen_stage.add(k)
        checks = 0
        run_stage(wide, True)
    diag["checks"] = checks
    diag["skipped"] = dict(sorted(why.items()))
    peers.sort(key=lambda p: (-p["tier"], abs(math.log(p["assets_ratio"])), p["cik"]))
    peers = peers[:n]
    reason = None
    if not peers:
        reason = f"no SIC-{sic[:2]}xx peers with annual XBRL facts filed by {as_of or 'now'} within size band"
    elif len(peers) < n:
        reason = f"only {len(peers)} of {n} requested peers found"
    return PeerList(peers, reason, diag)
