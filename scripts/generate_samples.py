"""Generate the three sample analyses in sample_analysis/ by running the REAL pipeline (CONTRACTS D10).

    python scripts/generate_samples.py [--only enron_2000,luckin_2019,apple_2022]

Each JSON is ``agents.state.to_jsonable(final_state)`` plus a top-level ``_meta`` block. Keys missing => ``degraded: true``
(the pipeline's own deterministic fallbacks were used; nothing is fabricated). The Apple sample uses the actual filing date
of its FY2022 10-K (looked up from EDGAR) as ``as_of`` so the analysis is point-in-time.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "sample_analysis"
APPLE_CIK = "0000320193"


def _apple_fy2022_filing_date() -> str:
    from tools.edgar_api import list_annual_filings
    fil = [f for f in list_annual_filings(APPLE_CIK) if str(f.get("fiscal_year")) == "2022" and f.get("form") == "10-K"]
    if not fil:  # fall back to period-end year (Apple FY ends late September)
        fil = [f for f in list_annual_filings(APPLE_CIK) if str(f.get("report_date", ""))[:4] == "2022" and f.get("form") == "10-K"]
    if not fil:
        raise RuntimeError("no FY2022 10-K found for Apple on EDGAR")
    return sorted(fil, key=lambda f: f["filing_date"])[0]["filing_date"]


def _jobs() -> dict[str, dict]:
    return {
        "enron_2000": dict(ticker="ENRNQ", cik="0001024401", as_of="2001-04-02", end_year=2000),
        "luckin_2019": dict(ticker="LK", cik="0001767582", as_of="2021-06-30", end_year=2019),
        "apple_2022": dict(ticker="AAPL", cik=APPLE_CIK, as_of=None, end_year=2022),  # as_of resolved at run time
    }


def generate(name: str, params: dict) -> dict:
    from agents.state import to_jsonable
    from graph.pipeline import analyze_company_sync
    from tools.common import load_env

    load_env()
    params = dict(params)
    if name == "apple_2022":
        params["as_of"] = _apple_fy2022_filing_date()
    t0 = time.time()
    events: list[dict] = []
    state = analyze_company_sync(params["ticker"], 5, cik=params["cik"], end_year=params["end_year"], as_of=params["as_of"],
                                 progress_callback=events.append)
    runtime = round(time.time() - t0, 1)
    data = to_jsonable(dict(state))
    import os
    has_llm, has_jev = bool(os.getenv("ANTHROPIC_API_KEY")), bool(os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY"))
    degraded = not (has_llm and has_jev)
    # Keys present is not the same as every component working: list the components that fell back (state["degraded"]).
    fallbacks = sorted({str(x).split(":", 1)[0] for x in (data.get("degraded") or [])})
    narrative_fallback = any(str(x).startswith("narrative:") for x in (data.get("degraded") or []))
    data["_meta"] = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "degraded": degraded,
        "components_with_fallback": fallbacks,
        "narrative_source": "deterministic fallback (Sonnet text rejected by validation)" if narrative_fallback else "Claude Sonnet (validated)",
        "note": ("degraded run: no ANTHROPIC/JEV keys" if degraded else
                 "keys present; components that fell back are listed in components_with_fallback"),
        "anthropic_key_available": has_llm, "jev_key_available": has_jev,
        "params": params, "runtime_seconds": runtime, "n_progress_events": len(events),
        "generator": "scripts/generate_samples.py (graph.pipeline.analyze_company_sync)",
    }
    text = json.dumps(data, indent=1, allow_nan=False, ensure_ascii=False, default=str)   # raises on NaN/Infinity
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(text, encoding="utf-8")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    jobs = _jobs()
    names = [n for n in args.only.split(",") if n] or list(jobs)
    for n in names:
        d = generate(n, jobs[n])
        print(f"{n}: grade={d.get('risk_grade')} suspicion={d.get('suspicion_score')} runtime={d['_meta']['runtime_seconds']}s "
              f"degraded_items={len(d.get('degraded') or [])}")


if __name__ == "__main__":
    main()
