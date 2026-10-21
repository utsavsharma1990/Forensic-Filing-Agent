"""Forensic Filing Intelligence Agent - Streamlit UI (3 pages, docs/SPEC.md "STREAMLIT UI").

Design rules
* Heavy modules (graph.pipeline, evaluation.evaluator, watchlist.*) are imported lazily inside handlers, so the app launches
  even if one of them is broken; failures are shown as errors, never as empty/zero data.
* Long runs execute in worker threads (``Job``); worker threads never call Streamlit APIs, they only append progress events
  that the script thread renders on each poll-rerun.
* Nothing is cached with st.cache_*: every view shows the state it was given plus its analysis timestamp.
* DEMO MODE (FFA_DEMO_MODE, see app_components/demo.py) is a public read-only deployment: saved results only. It never imports
  tools.edgar_api, graph.pipeline, evaluation.evaluator, watchlist.* or any LLM client, and never creates a database file.
  Live actions (analysis, watchlist, evaluation run) can additionally be gated by FFA_ACCESS_CODE when demo mode is off.
* A run without ANTHROPIC_API_KEY / JEV_API_KEY is DEGRADED and labelled as such. Missing data is shown as "unavailable:
  reason", never as zero.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_components import charts as C  # noqa: E402
from app_components import demo as D  # noqa: E402
from app_components import eval_adapter as EA  # noqa: E402
from app_components import formatting as F  # noqa: E402

SAMPLE_DIR = ROOT / "sample_analysis"
DEMO_FIXTURE = ROOT / "tests" / "fixtures" / "ui_state.json"
PAGES = ["Forensic Analysis", "Watchlist", "Retrospective Validation"]
EVAL_DISCLAIMER = ("This evaluation uses publicly available SEC filings. Past detection performance does not guarantee future "
                   "accuracy. This tool is for research purposes and does not constitute investment advice.")
DEMO_BADGE = "DEMO MODE: read-only, saved results only"
DEMO_NOTE = ("Live analysis, the watchlist and live evaluation are switched off in this public demo (no API keys, no SEC calls, no stored data). "
             "Browse the saved analyses and the saved backtest result sets instead. To run it yourself see the README (Quick start).")
STATUS_SHORT = ("Detection quality is limited: on two sealed holdouts it genuinely caught only about 1-2 of every 12-15 fraud cases at the "
                "High/Critical cutoff. Not investment advice. See README.md and the Retrospective Validation page.")
STEPS = [
    ("fetch_data", "\U0001F50D Fetching SEC EDGAR data..."),
    ("quantitative", "\U0001F4CA Running quantitative forensics..."),
    ("language", "\U0001F4DD Analyzing filing language..."),
    ("network", "\U0001F517 Checking auditor and executive history..."),
    ("peer", "\U0001F465 Comparing against peer group..."),
    ("temporal", "\U0001F4C8 Building temporal intelligence..."),
    ("jev", "⚡ Running Jev confidence scoring..."),
    ("synthesis", "\U0001F9E0 Synthesizing final verdict..."),
]
AGENTS = ["quantitative", "language", "network", "peer", "temporal"]

st.set_page_config(page_title="Forensic Filing Intelligence Agent", page_icon="\U0001F575", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown(
    """
<style>
button[data-testid="stBaseButton-primary"] {background:#d03b3b;border-color:#d03b3b;color:#fff;font-weight:700;
  font-size:1.15rem;min-height:3rem;padding:.5rem 1.6rem;}
button[data-testid="stBaseButton-primary"]:hover {background:#b32f2f;border-color:#b32f2f;color:#fff;}
.gun {border-left:7px solid #d03b3b;background:rgba(208,59,59,.13);padding:.85rem 1rem;margin:.5rem 0;border-radius:6px;
  font-size:1.02rem;line-height:1.4;}
.gun b {font-weight:700;}
.banner-degraded {border:2px solid #d03b3b;border-radius:8px;padding:.7rem 1rem;margin:.5rem 0 1rem 0;
  background:rgba(250,178,25,.14);}
.gradewrap {display:flex;align-items:center;gap:1rem;flex-wrap:wrap;margin:.25rem 0 .5rem 0;}
.firstdet {border:2px solid #d03b3b;border-radius:8px;padding:.8rem 1rem;background:rgba(208,59,59,.10);font-size:1.05rem;}
.card {border:1px solid rgba(128,128,128,.35);border-radius:8px;padding:.7rem .9rem;}
.metriclbl {font-size:.85rem;opacity:.75;} .metricval {font-size:1.9rem;font-weight:800;line-height:1.1;}
.metricci {font-size:.8rem;opacity:.8;}
.small {font-size:.85rem;opacity:.85;}
</style>
""",
    unsafe_allow_html=True,
)


# =============================================================================================== infrastructure
class Job:
    """A background computation. Worker threads only call ``emit``; the UI thread reads ``events``."""

    def __init__(self, kind: str, label: str = ""):
        self.kind, self.label = kind, label
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self.result: Any = None
        self.error: Optional[str] = None
        self.finished = False
        self.started = time.time()
        self.ended: Optional[float] = None
        self.processed = False  # post-processing (e.g. DB write) done by the UI thread
        self.thread: Optional[threading.Thread] = None

    def emit(self, ev: Any) -> None:
        with self._lock:
            self.events.append(ev if isinstance(ev, dict) else {"message": str(ev)})

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def start(self, fn: Callable[["Job"], Any]) -> "Job":
        def runner():
            try:
                self.result = fn(self)
            except BaseException as exc:  # noqa: BLE001 - everything is surfaced in the UI
                self.error = f"{type(exc).__name__}: {exc}"
                self.traceback = traceback.format_exc()
            finally:
                self.ended = time.time()
                self.finished = True

        self.thread = threading.Thread(target=runner, name=f"job-{self.kind}", daemon=True)
        self.thread.start()
        return self


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - not available in some test/embedded contexts
        return "light"


def show_fig(fig, key: str) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, key=key, config={"displaylogo": False})


def table(rows: list[dict], key: Optional[str] = None, height: Optional[int] = None) -> None:
    if not rows:
        return
    kwargs = {"hide_index": True, "width": "stretch"}
    if height:
        kwargs["height"] = height
    st.dataframe(pd.DataFrame(rows), **kwargs)


def poll_rerun(job: Job, delay: float = 0.7) -> None:
    """Keep the page live while a job runs (no blocking in the script thread beyond a short sleep)."""
    if not job.finished:
        time.sleep(delay)
        st.rerun()


def step_states(events: list[dict]) -> dict:
    """node -> {"state": pending|running|done|error, "message": str, "elapsed_ms": int|None}

    The real pipeline emits ``{"node": fetch_data|quantitative|language|network|peer|temporal|synthesis, "status":
    start|done|error}`` plus a sub-event ``{"node": "jev"|"synthesis", "status": "jev"}`` when Jev scoring starts (it ends
    with synthesis). Legacy ``run_<agent>`` node names are accepted too. A ``pipeline`` error event marks every unfinished
    stage as errored (graph-level crash).
    """
    out = {k: {"state": "pending", "message": "", "elapsed_ms": None} for k, _ in STEPS}
    for ev in events:
        node = ev.get("node")
        if isinstance(node, str) and node.startswith("run_"):
            node = node[4:]
        s = str(ev.get("status", "")).lower()
        if node == "pipeline" and s in ("error", "failed", "fail"):
            for v in out.values():
                if v["state"] != "done":
                    v["state"], v["message"] = "error", str(ev.get("message") or ev.get("detail") or "pipeline error")
            continue
        if node not in out:
            continue
        if s in ("start", "started", "running", "begin", "jev"):
            if out[node]["state"] != "done":
                out[node]["state"] = "running"
        elif s in ("done", "ok", "complete", "completed", "success", "degraded"):
            out[node]["state"] = "done"
        elif s in ("error", "failed", "fail"):
            out[node]["state"] = "error"
        if (ev.get("detail") or ev.get("message")) and out[node]["state"] == "error":
            out[node]["message"] = str(ev.get("detail") or ev["message"])
        if ev.get("elapsed_ms") is not None:
            out[node]["elapsed_ms"] = ev["elapsed_ms"]
    if out["synthesis"]["state"] in ("done", "error") and out["jev"]["state"] == "running":
        out["jev"]["state"] = "done"       # Jev is a sub-step of synthesis (D8): finished when synthesis is
    return out


def render_progress(job: Job, title: str) -> None:
    states = step_states(job.snapshot())
    n_done = sum(1 for v in states.values() if v["state"] in ("done", "error"))
    status_state = "error" if job.error else ("complete" if job.finished else "running")
    with st.status(f"{title} ({time.time() - job.started:.0f}s elapsed)" if not job.finished else title,
                   state=status_state, expanded=True):
        for key, msg in STEPS:
            s = states[key]
            icon = {"pending": "▫️", "running": "⏳", "done": "✅", "error": "❌"}[s["state"]]
            extra = f" ({s['elapsed_ms'] / 1000:.1f}s)" if s["elapsed_ms"] else ""
            err = f" - {F.md_escape(s['message'])}" if s["state"] == "error" and s["message"] else ""
            line = f"{icon} {msg}{extra}{err}"
            st.markdown(f"**{line}**" if s["state"] == "running" else (line if s["state"] != "pending" else f"<span style='opacity:.5'>{line}</span>"),
                        unsafe_allow_html=True)
    st.progress(min(1.0, n_done / len(STEPS)), text=f"{n_done} of {len(STEPS)} stages finished")


# =============================================================================================== sidebar / navigation
def is_demo() -> bool:
    return D.demo_mode()


def live_allowed() -> bool:
    """True when live actions may run: demo mode off and (no access code configured, or the code was entered this session)."""
    if is_demo():
        return False
    return not D.access_code() or bool(st.session_state.get("ffa_unlocked"))


def sidebar_gate() -> None:
    """Optional access gate (live mode with FFA_ACCESS_CODE set). The code is never logged or stored beyond the unlocked flag."""
    code = D.access_code()
    if is_demo() or not code:
        return
    if st.session_state.get("ffa_unlocked"):
        st.sidebar.success("Live actions unlocked for this session.")
        return
    with st.sidebar.form("gate_form", clear_on_submit=True):
        entered = st.text_input("Access code (required for live actions)", type="password", key="gate_code")
        ok = st.form_submit_button("Unlock live actions")
    if ok:
        if D.check_code(entered, code):
            st.session_state["ffa_unlocked"] = True
            st.rerun()
        else:
            st.sidebar.error("Wrong access code.")
    st.sidebar.caption("Live actions are locked: analysis runs, watchlist changes and evaluation runs need the access code.")


def sidebar_nav() -> str:
    st.sidebar.title("Forensic Filing Agent")
    page = st.sidebar.radio("Navigation", PAGES, key="page", label_visibility="collapsed")
    st.sidebar.divider()
    if is_demo():
        st.sidebar.error("**" + DEMO_BADGE + "**")
    else:
        sidebar_gate()
    st.sidebar.markdown("**Status: research prototype.** " + STATUS_SHORT)
    return page


# =============================================================================================== PAGE 1
def list_saved() -> dict[str, Path]:
    out: dict[str, Path] = {}
    if SAMPLE_DIR.is_dir():
        for p in sorted(SAMPLE_DIR.glob("*.json")):
            out[f"sample_analysis/{p.name}"] = p
    if is_demo():
        return out  # public demo: the real saved samples and nothing else (no synthetic test fixture)
    if DEMO_FIXTURE.exists():
        out["SYNTHETIC demo state (tests/fixtures/ui_state.json, invented data)"] = DEMO_FIXTURE
    return out


def load_state_file(path: Path) -> dict:
    return F.normalize_state(json.loads(path.read_text(encoding="utf-8")))


def _analysis_worker(ticker: str, years: int, cik: Optional[str]) -> Callable[[Job], Any]:
    def run(job: Job):
        from graph.pipeline import analyze_company  # lazy: a broken pipeline must not stop the app launching
        kwargs: dict[str, Any] = {"progress_callback": job.emit}
        if cik:
            kwargs["cik"] = cik
        return asyncio.run(analyze_company(ticker, years, **kwargs))
    return run


def page_analysis() -> None:
    ss = st.session_state
    st.title("Forensic Filing Intelligence Agent")
    st.caption("Multi-agent SEC filing analysis powered by LangGraph + Claude + Jev")
    st.info("**Status: research prototype.** A grade here is a screening aid, not a verdict. " + STATUS_SHORT)

    job: Optional[Job] = ss.get("analysis_job")
    running = bool(job and not job.finished)

    demo = is_demo()
    locked = not demo and not live_allowed()
    ticker, years, cik, go_clicked = "", 5, "", False
    if demo:
        st.warning("**Live analysis is disabled in this public demo.** " + DEMO_NOTE)
        st.markdown("#### Load a saved analysis")
        st.caption("These are the saved analyses in `sample_analysis/` (produced earlier with live keys). Pick one and press the button.")
    else:
        c1, c2 = st.columns([3, 1])
        ticker = c1.text_input("Enter ticker symbol (e.g. AAPL, ENRNQ)", key="in_ticker", disabled=running or locked)
        years = c2.number_input("Years to analyze", min_value=1, max_value=10, value=5, step=1, key="in_years", disabled=running or locked)
        with st.expander("Advanced: CIK override (required for delisted tickers such as ENRNQ)"):
            cik = st.text_input("CIK (optional, 10 digits)", key="in_cik", disabled=running or locked)
        go_clicked = st.button("Run Forensic Analysis", type="primary", disabled=running or locked, key="btn_run")
        if locked:
            st.caption("Locked: enter the access code in the sidebar to run a live analysis.")

    saved = list_saved()
    with st.expander("Load saved analysis (works offline, no pipeline run)", expanded=demo):
        if not any(k.startswith("sample_analysis/") for k in saved):
            st.caption("sample_analysis/ contains no saved analyses yet; they are produced by scripts/generate_samples.py.")
        if saved:
            choice = st.selectbox("Saved analysis", list(saved), key="in_saved")
            if st.button("Load saved analysis", key="btn_load", type="primary" if demo else "secondary"):
                try:
                    st_ = load_state_file(saved[choice])
                    ss["analysis"] = {"state": st_, "source": f"saved file: {choice}", "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                    ss.pop("analysis_job", None)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not load {choice}: {type(exc).__name__}: {exc}")
        else:
            st.caption("Nothing to load.")

    if go_clicked:
        t = (ticker or "").strip().upper()
        if not live_allowed():
            st.error("Live analysis is not available (demo mode or access code not entered).")
        elif not t:
            st.error("Enter a ticker symbol first.")
        else:
            ss["analysis_job"] = Job("analysis", t).start(_analysis_worker(t, int(years), (cik or "").strip() or None))
            ss["analysis_req"] = {"ticker": t, "years": int(years)}
            ss.pop("analysis", None)
            st.rerun()

    job = ss.get("analysis_job")
    if job is not None:
        req = ss.get("analysis_req", {})
        if not job.finished:
            render_progress(job, f"Analyzing {req.get('ticker', '')}")
            poll_rerun(job)
        elif job.error:
            render_progress(job, f"Analysis of {req.get('ticker', '')} failed")
            st.error(f"The analysis could not be completed: {job.error}")
            with st.expander("Technical details"):
                st.code(getattr(job, "traceback", job.error))
        elif not job.processed:
            job.processed = True
            res = F.normalize_state(job.result if isinstance(job.result, dict) else {})
            ss["analysis"] = {"state": res, "source": f"live run for {req.get('ticker')} ({req.get('years')} years)",
                              "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            st.rerun()

    a = ss.get("analysis")
    if a:
        render_analysis(a["state"], a["source"], a["loaded_at"])
    elif job is None and demo:
        st.info("Pick a saved analysis above and press **Load saved analysis**.")
    elif job is None:
        st.info("Enter a ticker and press **Run Forensic Analysis**, or load a saved analysis to explore the interface offline.")


def render_analysis(state: dict, source: str, loaded_at: str) -> None:
    mode = theme_mode()
    if not state:
        st.error("The analysis returned no state.")
        return
    if state.get("_fixture_note"):
        st.warning(f"**SYNTHETIC DATA.** {state['_fixture_note']}")
    grade = state.get("risk_grade")
    deg = F.degraded_summary(state)
    name = state.get("company_name") or state.get("ticker") or ""
    st.markdown(f"### {F.md_escape(name)} ({F.md_escape(state.get('ticker', ''))}) - FY{state.get('focus_year', '?')}")
    st.caption(f"Source: {source}  |  analysis timestamp: {state.get('analysis_timestamp', 'n/a')}  |  displayed at {loaded_at}")

    # ---- degraded banner
    if deg["claude"] or deg["jev"] or state.get("error"):
        missing = [x for x, f in (("Claude (LLM explanations / specificity / narrative)", deg["claude"]), ("Jev (confidence scoring)", deg["jev"])) if f]
        st.markdown(
            '<div class="banner-degraded"><b>DEGRADED RUN.</b> ' + ("Deterministic fallback used in this run for: " + "; ".join(F.esc(m) for m in missing) + ". " if missing else "")
            + "Deterministic fallbacks were used where possible; metrics that need the missing component are shown as "
              "<i>unavailable</i>, not as zero. "
              + ("The <b>Critical</b> grade cannot be reached without Jev. " if deg["jev"] else "") + "See &ldquo;Degraded components&rdquo; below.</div>",
            unsafe_allow_html=True)

    # ---- risk badge
    known = F.is_known_grade(grade)
    st.markdown(f'<div class="gradewrap">{F.badge_html(grade, large=True)}'
                f'<span class="small">Overall risk grade (rule-based; see rationale)</span></div>', unsafe_allow_html=True)
    if not known:
        st.error(f"Risk grade is **{grade or 'missing'}**: the analysis did not produce a valid grade. This is an error state, "
                 f"not a Low-risk result. {F.md_escape(state.get('error') or '')}")
    if state.get("grade_rationale"):
        st.info(f"**Grade rationale.** {F.md_escape(state['grade_rationale'])}")
    if state.get("risk_changed") and state.get("previous_risk_grade"):
        st.caption(f"Risk grade changed vs previous grade ({state.get('previous_risk_grade')}).")

    # ---- smoking guns
    st.subheader("Smoking guns")
    guns = [g for g in (state.get("smoking_guns") or []) if str(g).strip()][:3]
    if guns:
        for g in guns:
            st.markdown(f'<div class="gun">\U0001F6A8 <b>{F.esc(g)}</b></div>', unsafe_allow_html=True)
        if len(guns) < 3:
            st.caption(f"Only {len(guns)} evidence-backed finding(s) available; the list is never padded.")
    else:
        st.info("No smoking-gun findings: no flagged evidence was available to report (the list is never padded).")

    # ---- timeline
    st.subheader("Forensic timeline")
    timeline = state.get("forensic_timeline") or (state.get("temporal_result") or {}).get("timeline") or []
    tl_ok = [r for r in timeline if isinstance(r.get("year"), int)]
    fdy = state.get("first_detection_year")
    show_fig(C.timeline_chart(tl_ok, fdy, mode), "fig_timeline")
    st.caption("Suspicion score = sum of fixed flag weights per fiscal year (capped at 100), not a probability. "
               "Diamonds mark years in which new flags first fired; hover for the flags.")

    if state.get("final_narrative"):
        st.subheader("Final narrative")
        st.markdown(F.md_escape(state["final_narrative"]))

    # ---- tabs
    st.subheader("Agent detail")
    tabs = st.tabs(["Quantitative", "Language", "Network", "Peer", "Temporal"])
    with tabs[0]:
        tab_quantitative(state.get("quantitative_result"), mode)
    with tabs[1]:
        tab_language(state.get("language_result"), mode)
    with tabs[2]:
        tab_network(state.get("network_result"), mode)
    with tabs[3]:
        tab_peer(state.get("peer_result"), mode)
    with tabs[4]:
        tab_temporal(state.get("temporal_result"), tl_ok, mode)

    # ---- degraded expander
    with st.expander(f"Degraded components ({len(deg['items'])})", expanded=bool(deg["items"])):
        if deg["items"]:
            for it in deg["items"]:
                st.markdown(f"- {F.md_escape(it)}")
        else:
            st.write("None: every component ran in full.")
        unavailable_agents = [k.replace("_result", "") for k in ("quantitative_result", "language_result", "network_result", "peer_result", "temporal_result")
                              if isinstance(state.get(k), dict) and state[k].get("unavailable")]
        if unavailable_agents:
            st.warning("Agents that returned no usable result: " + ", ".join(unavailable_agents))
        tr = [{"Agent": t.get("agent"), "Status": t.get("status"), "Duration (ms)": t.get("duration_ms"), "Summary": str(t.get("summary", ""))[:160]}
              for t in (state.get("agent_trace") or []) if isinstance(t, dict)]
        if tr:
            st.caption("Agent trace")
            table(tr)
    with st.expander("Download this analysis (JSON)"):
        try:
            if is_demo():
                raise RuntimeError("demo mode: no agents imports")
            from agents.state import to_jsonable
            payload = json.dumps(to_jsonable(state), indent=1, default=str)
        except Exception:  # noqa: BLE001
            payload = json.dumps(state, indent=1, default=str)
        st.download_button("Download JSON", payload, file_name=f"{state.get('ticker', 'analysis')}_analysis.json", mime="application/json")

    sidebar_jev(state)


# ---------------------------------------------------------------------------------------------- Jev sidebar
def sidebar_jev(state: dict) -> None:
    sb = st.sidebar
    sb.subheader("Jev confidence")
    js = state.get("jev_scores") or {}
    if not F.jev_overall_available(state):
        reasons = sorted({str(v.get("error")) for v in js.values() if isinstance(v, dict) and v.get("error")})
        sb.warning("**Jev unavailable** for this analysis" + (f" ({'; '.join(reasons)})" if reasons else "") +
                   ". No confidence scores are shown or estimated. Grades above High need Jev.")
        return
    for ag in AGENTS:
        v = js.get(ag)
        with sb.container(border=True):
            sb.markdown(f"**{F.AGENT_LABELS[ag]}**")
            if not isinstance(v, dict) or not v.get("available"):
                sb.caption(f"Jev unavailable for this agent{': ' + str(v.get('error')) if isinstance(v, dict) and v.get('error') else ''}")
                continue
            strength = str(v.get("evidence_strength"))
            sb.markdown(f"Evidence strength: **{F.esc(strength.upper())}**", unsafe_allow_html=True)
            conf = F.finite(v.get("confidence_score"))
            if conf is None:
                sb.caption("Confidence: unavailable")
            else:
                sb.progress(max(0.0, min(1.0, conf / 100.0)), text=f"Confidence {conf:.0f}%")
            mc = v.get("material_change")
            sb.caption("◆ Material change vs prior year: **YES**" if mc is True else
                       "◇ No material change vs prior year" if mc is False else "Material change: not assessed")


# ---------------------------------------------------------------------------------------------- agent tabs
def _unavailable_rows(result: dict, containers: dict[str, str]) -> list[dict]:
    rows = []
    for label, key in containers.items():
        d = result.get(key) or {}
        for y in F.years_sorted(d):
            e = F.yget(d, y)
            if isinstance(e, dict) and e.get("status") == "unavailable":
                rows.append({"Metric": label, "Year": f"FY{y}", "Reason": f"unavailable: {e.get('reason', 'no reason given')}"})
    for k, v in ((result.get("data_quality") or {}).get("unavailable") or {}).items():
        rows.append({"Metric": k, "Year": "", "Reason": f"unavailable: {v}"})
    return rows


def _agent_header(res: Any, name: str) -> bool:
    """Show the agent's key finding. Returns False when the agent produced nothing usable."""
    if not isinstance(res, dict) or not res:
        st.warning(f"{name}: no result was produced.")
        return False
    if res.get("unavailable"):
        st.warning(f"{name} unavailable: {F.md_escape(res.get('reason') or res.get('error') or 'no reason reported')}")
    sev = res.get("severity", "None")
    st.markdown(f"**Severity:** {F.esc(sev)}  |  **Flags fired (all years):** {res.get('flags_fired', 0)}")
    if res.get("key_finding"):
        st.markdown(f"**Key finding.** {F.md_escape(res['key_finding'])}")
    return not res.get("unavailable") or bool(res.get("beneish_scores") or res.get("hedging_trend"))


def tab_quantitative(q: Any, mode: str) -> None:
    if not _agent_header(q, "Quantitative agent"):
        return
    years = F.years_sorted(q.get("beneish_scores")) or [y for y in q.get("analysed_years", [])]

    # Beneish
    by = q.get("beneish_scores") or {}
    ys = F.years_sorted(by)
    if ys:
        vals = [F.finite((F.yget(by, y) or {}).get("score")) if (F.yget(by, y) or {}).get("status") == "ok" else None for y in ys]
        flags = [bool((F.yget(by, y) or {}).get("flag")) for y in ys]
        extra = [f"Zone: {(F.yget(by, y) or {}).get('zone', 'unavailable')}" + (" (imputed: " + ", ".join(F.yget(by, y)["imputed"]) + ")" if (F.yget(by, y) or {}).get("imputed") else "") for y in ys]
        bands = [(None, -2.22, "Unlikely (M < -2.22)", "#0ca30c"), (-2.22, -1.78, "Grey zone", "#fab219"), (-1.78, None, "Manipulator (M > -1.78)", "#d03b3b")]
        show_fig(C.banded_line("Beneish M-Score", ys, vals, bands, "M-Score", flags, mode, value_name="M-Score", hover_extra=extra), "fig_beneish")
        imputed = {y: (F.yget(by, y) or {}).get("imputed") for y in ys if (F.yget(by, y) or {}).get("imputed")}
        if imputed:
            st.caption("Imputed inputs (neutral 1.0): " + "; ".join(f"FY{y}: {', '.join(v)}" for y, v in imputed.items()))
    else:
        st.info("Beneish M-Score: unavailable for all analysed years.")

    # Altman
    al = q.get("altman_scores") or {}
    ys = F.years_sorted(al)
    if ys:
        ok = [F.yget(al, y) or {} for y in ys]
        variant = next((e.get("variant") for e in ok if e.get("status") == "ok"), None)
        zones = (1.23, 2.90) if variant == "Z-prime" else (1.81, 2.99)
        vals = [F.finite(e.get("score")) if e.get("status") == "ok" else None for e in ok]
        bands = [(None, zones[0], f"Distress (< {zones[0]})", "#d03b3b"), (zones[0], zones[1], "Grey zone", "#fab219"), (zones[1], None, f"Safe (> {zones[1]})", "#0ca30c")]
        show_fig(C.banded_line(f"Altman Z ({'Z-prime, book-equity variant' if variant == 'Z-prime' else 'original Z' if variant else 'unavailable'})",
                               ys, vals, bands, "Z-score", [bool(e.get("flag")) for e in ok], mode, value_name="Z"), "fig_altman")
        st.caption("Altman distress is a **business-distress** signal, not evidence of manipulation.")

    # ratio trends
    cols = st.columns(3)
    spec = [("Revenue quality (OCF / net income)", "revenue_quality", "ratio", 0.8, "flag < 0.8 two years running", ".2f", "OCF/NI"),
            ("Days sales outstanding", "dso_trend", "dso_days", None, "", ".1f", "DSO (days)"),
            ("Accruals ratio ((NI - OCF) / assets)", "accruals_ratio", "ratio", 0.05, "flag > 0.05", ".3f", "Accruals")]
    for col, (title, key, field, thr, thr_label, fmt, nm) in zip(cols, spec):
        d = q.get(key) or {}
        ys = F.years_sorted(d)
        with col:
            if ys:
                vals = [F.finite((F.yget(d, y) or {}).get(field)) if (F.yget(d, y) or {}).get("status") == "ok" else None for y in ys]
                if all(v is None for v in vals):
                    st.info(f"{title}: unavailable for all years.")
                else:
                    show_fig(C.small_trend(title, ys, vals, [bool((F.yget(d, y) or {}).get("flag")) for y in ys], nm, mode, thr, thr_label,
                                           value_name=nm, fmt=fmt), f"fig_{key}")
            else:
                st.info(f"{title}: unavailable.")

    # flags table
    st.markdown("**Flags fired**")
    ev = q.get("evidence") or []
    rows = []
    for y in F.years_sorted(q.get("flags_by_year")):
        for f in F.yget(q.get("flags_by_year"), y) or []:
            disp = next((e.get("display") for e in ev if e.get("flag") == f and e.get("year") == y), "")
            rows.append({"Year": f"FY{y}", "Flag": F.flag_label(f), "Evidence": disp})
    if rows:
        table(rows)
    else:
        st.write("No quantitative flags fired in any analysed year.")
    ua = _unavailable_rows(q, {"Beneish M-Score": "beneish_scores", "Altman Z": "altman_scores", "Revenue quality": "revenue_quality",
                               "DSO": "dso_trend", "Accruals ratio": "accruals_ratio"})
    if ua:
        st.markdown("**Unavailable metrics**")
        table(ua)


def tab_language(l: Any, mode: str) -> None:
    if not _agent_header(l, "Language agent"):
        return
    h = l.get("hedging_trend") or {}
    ys = F.years_sorted(h)
    if ys:
        vals = [None if F.finite((F.yget(h, y) or {}).get("ratio")) is None else F.finite(F.yget(h, y)["ratio"]) * 100 for y in ys]
        if all(v is None for v in vals):
            st.info("Hedging trend: unavailable for all years (MD&A not found).")
        else:
            show_fig(C.small_trend("Hedging-word ratio (% of MD&A words)", ys, vals, [bool((F.yget(h, y) or {}).get("flag")) for y in ys],
                                   "% of words", mode, value_name="Hedging ratio %", fmt=".2f", height=320), "fig_hedge")
    c1, c2 = st.columns(2)
    for col, key, field, title, thr, thr_l, scale in ((c1, "passive_voice", "pct", "Passive-voice sentences (%) - v2 flags a >25% relative YoY rise", None, "", 1),
                                                         (c2, "risk_factor_length", "chars", "Risk-factor section length (thousand chars)", None, "", 1e-3)):
        d = l.get(key) or {}
        yy = F.years_sorted(d)
        with col:
            vals = [None if F.finite((F.yget(d, y) or {}).get(field)) is None else F.finite(F.yget(d, y)[field]) * scale for y in yy]
            if yy and any(v is not None for v in vals):
                show_fig(C.small_trend(title, yy, vals, [bool((F.yget(d, y) or {}).get("flag")) for y in yy], title.split(" (")[0], mode, thr, thr_l,
                                       value_name=title.split(" (")[0], fmt=".1f"), f"fig_{key}")
            else:
                st.info(f"{title}: unavailable.")
    # specificity
    sp = l.get("specificity_scores") or {}
    ys = F.years_sorted(sp)
    scored = [(y, F.yget(sp, y)) for y in ys if F.finite((F.yget(sp, y) or {}).get("score")) is not None]
    st.markdown("**MD&A specificity (1-10, Claude Haiku)**")
    if scored:
        show_fig(C.small_trend("Specificity score", [y for y, _ in scored], [e["score"] for _, e in scored], [bool(e.get("flag")) for _, e in scored],
                               "Score (1-10)", mode, 5, "flag < 5", value_name="Specificity", fmt=".0f", height=300), "fig_spec")
        table([{"Year": f"FY{y}", "Score": e.get("score"), "Reason": e.get("reason")} for y, e in scored])
    else:
        st.info("Specificity scoring **requires ANTHROPIC_API_KEY** and is unavailable in this run. Scores are shown as unavailable (not zero) "
                "and no heuristic stand-in is computed.")
        reasons = sorted({str((F.yget(sp, y) or {}).get("reason")) for y in ys})
        if reasons:
            st.caption("Reason: " + "; ".join(reasons))
    # excerpts
    st.markdown("**Notable excerpts**")
    nl = l.get("new_legal_proceedings") or {}
    exc = [(y, F.yget(nl, y)) for y in F.years_sorted(nl) if (F.yget(nl, y) or {}).get("detected") and (F.yget(nl, y) or {}).get("text")]
    for y, e in exc:
        st.markdown(f"> **FY{y} - new legal proceeding:** {F.md_escape(str(e.get('text'))[:600])}")
    for e in (l.get("evidence") or []):
        if e.get("flag") != "language.new_legal":
            st.markdown(f"- FY{e.get('year')}: {F.md_escape(e.get('display', ''))}")
    if not exc and not (l.get("evidence") or []):
        st.write("No excerpts: no language flag fired.")
    ua = _unavailable_rows(l, {})
    if ua:
        with st.expander(f"Unavailable language metrics ({len(ua)})"):
            table(ua)


def tab_network(n: Any, mode: str) -> None:
    if not _agent_header(n, "Network agent"):
        return
    ah, ex = n.get("auditor_history") or {}, n.get("executive_changes") or {}
    ys = sorted(set(F.years_sorted(ah)) | set(F.years_sorted(ex)))
    st.markdown("**Auditor history**")
    rows = []
    for y in F.years_sorted(ah):
        e = F.yget(ah, y) or {}
        rows.append({"Year": f"FY{y}", "Auditor": e.get("name") or "unavailable: not found in filing",
                     "Changed": "YES" if e.get("changed") else ("no" if e.get("status") not in ("unknown",) else "unknown"), "Status": e.get("status", "")})
    table(rows) if rows else st.write("Auditor history unavailable.")
    st.markdown("**Executive changes**")
    rows = []
    for y in F.years_sorted(ex):
        e = F.yget(ex, y) or {}
        rows.append({"Year": f"FY{y}", "CFO": e.get("cfo") or "unavailable", "CFO changed": "YES" if e.get("cfo_changed") else "no",
                     "CEO": e.get("ceo") or "unavailable", "CEO changed": "YES" if e.get("ceo_changed") else "no"})
    table(rows) if rows else st.write("Executive data unavailable.")
    st.markdown("**Audit fee trend**")
    af = n.get("audit_fees") or {}
    ys = F.years_sorted(af)
    vals = [None if F.finite((F.yget(af, y) or {}).get("amount")) is None else F.finite(F.yget(af, y)["amount"]) / 1e6 for y in ys]
    if ys and any(v is not None for v in vals):
        show_fig(C.small_trend("Audit fees ($ millions)", ys, vals, [bool((F.yget(af, y) or {}).get("flag")) for y in ys], "$ millions", mode,
                               value_name="Audit fees $M", fmt=".2f", height=300), "fig_fees")
        table([{"Year": f"FY{y}", "Fees ($)": F.fmt_num((F.yget(af, y) or {}).get("amount"), 0), "YoY change": F.fmt_num((F.yget(af, y) or {}).get("yoy_change_pct"), 1, "%"),
                "Revenue growth": F.fmt_num((F.yget(af, y) or {}).get("revenue_growth_pct"), 1, "%"), "Flag": "YES" if (F.yget(af, y) or {}).get("flag") else "no"} for y in ys])
    else:
        st.info("Audit fees: unavailable (not disclosed in the analysed filings or their proxies).")
    st.markdown("**Other network signals**")
    rows = []
    for y in F.years_sorted(n.get("restatements")):
        r, rp, g = F.yget(n["restatements"], y) or {}, F.yget(n.get("related_party_flags"), y) or {}, F.yget(n.get("going_concern"), y) or {}
        rows.append({"Year": f"FY{y}", "Restatement / material weakness": "YES" if r.get("detected") else "no", "Related-party growth": "YES" if rp.get("detected") else "no",
                     "Going concern": "YES" if g.get("detected") else "no"})
    if rows:
        table(rows)
    for e in n.get("evidence") or []:
        st.markdown(f"- FY{e.get('year')}: {F.md_escape(e.get('display', ''))}")


def tab_peer(p: Any, mode: str) -> None:
    if not isinstance(p, dict) or not p:
        st.warning("Peer agent: no result was produced.")
        return
    if p.get("unavailable"):
        st.warning(f"Peer comparison unavailable: {F.md_escape(p.get('reason') or p.get('error') or 'no reason reported')}")
        return
    _agent_header(p, "Peer agent")
    zs = p.get("metric_zscores") or {}
    fig, notes = C.radar_chart(zs, mode)
    if fig.data:
        show_fig(fig, "fig_radar")
        st.caption("Radar of company z-scores against the SIC peer mean (dashed ring at z = 0); dotted rings mark the +/-2 standard-deviation flag lines. The centre of the chart is z = -4 and the outer edge z = +4.")
        for nline in notes:
            st.caption(nline)
    else:
        st.info("Radar needs at least 3 metrics with a defined z-score; see the table below.")
    rows = []
    for m, d in zs.items():
        rows.append({"Metric": F.PEER_METRIC_LABELS.get(m, m), "Company": F.fmt_num(d.get("company_value"), 3), "Peer mean": F.fmt_num(d.get("peer_mean"), 3),
                     "z-score": F.fmt_num(d.get("z_score"), 2), "Direction": d.get("direction") or "n/a", "Flag": "YES" if d.get("flag") else "no",
                     "Peers (n)": d.get("n_peers"), "Interpretation": d.get("interpretation")})
    table(rows)
    ua = ((p.get("data_quality") or {}).get("unavailable") or {})
    if ua:
        st.markdown("**Unavailable metrics**")
        table([{"Metric": F.PEER_METRIC_LABELS.get(k, k), "Reason": f"unavailable: {v}"} for k, v in ua.items()])
    st.markdown("**Peers used**")
    table([{"Ticker": x.get("ticker"), "Name": x.get("name"), "Fiscal year": x.get("fiscal_year"), "SIC tier": x.get("tier")} for x in p.get("peer_list") or []])
    if (p.get("data_quality") or {}).get("note"):
        st.caption(F.md_escape(p["data_quality"]["note"]))


def tab_temporal(t: Any, timeline: list[dict], mode: str) -> None:
    if not isinstance(t, dict) or not t:
        st.warning("Temporal agent: no result was produced.")
        return
    if t.get("unavailable"):
        st.warning(f"Temporal analysis unavailable: {F.md_escape(t.get('error') or t.get('key_finding') or '')}")
    fd = t.get("first_detection_year")
    if fd:
        fdate = t.get("first_detection_filing_date")
        proxy = " (date is a proxy estimate)" if t.get("filing_date_is_proxy") else ""
        st.markdown(f'<div class="firstdet"><b>First detection: FY{fd}</b>'
                    + (f" - filing date {F.esc(fdate)}{proxy}" if fdate else "") + "<br>First year the suspicion score reached 40 while new flags were appearing.</div>",
                    unsafe_allow_html=True)
    else:
        st.info("No first-detection year: the suspicion score never reached 40 together with escalating (new) flags in the analysed period.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Signal trajectory", t.get("signal_trajectory", "n/a"))
    c2.metric("Years of elevated risk", t.get("years_of_elevated_risk", "n/a"))
    c3.metric("Focus-year signal change", t.get("focus_signal_change", "n/a"))
    if t.get("key_finding"):
        st.markdown(f"**Key finding.** {F.md_escape(t['key_finding'])}")
    if timeline:
        show_fig(C.stacked_flags_chart(timeline, mode), "fig_flagstack")
        table([{"Year": f"FY{r['year']}", "Score": r.get("suspicion_score"), "Level": r.get("risk_level"), "Signal change": r.get("signal_change"),
                "Flags fired": r.get("flags_fired"), "New flags": "; ".join(F.flag_label(f) for f in (r.get("new_flags_this_year") or []))} for r in timeline])
    else:
        st.info("No timeline data.")
    for note in t.get("notes") or []:
        st.caption(F.md_escape(note))


# =============================================================================================== PAGE 2
def _wl_modules():
    from watchlist import manager, scheduler
    return manager, scheduler


def _watch_run_worker(c: dict) -> Callable[[Job], Any]:
    def run(job: Job):
        from graph.pipeline import analyze_company
        manager, scheduler = _wl_modules()
        prev = c.get("last_grade") or c.get("last_risk_grade") or None
        kwargs: dict[str, Any] = {"progress_callback": job.emit, "previous_risk_grade": prev, "watchlist_id": str(c.get("id"))}
        if c.get("cik"):
            kwargs["cik"] = c["cik"]
        state = asyncio.run(analyze_company(c["ticker"], 5, **kwargs))
        grade = state.get("risk_grade") if isinstance(state, dict) else None
        if not isinstance(state, dict) or state.get("error") or not F.is_known_grade(grade):
            raise RuntimeError(f"analysis failed or produced no valid grade (grade={grade!r}): {(state or {}).get('error') if isinstance(state, dict) else state}")
        alert_id = None
        if scheduler.should_alert(prev, grade, c.get("alert_threshold") or "Medium"):
            alert_id = manager.create_alert(c["ticker"], prev, grade,
                                            f"Risk grade rose from {prev} to {grade}. Top smoking gun: {(state.get('smoking_guns') or ['none'])[0]}")
        manager.record_analysis(c["ticker"], state)
        return {"ticker": c["ticker"], "grade": grade, "previous": prev, "alert_id": alert_id}
    return run


def _watch_check_worker(job: Job):
    _, scheduler = _wl_modules()
    return scheduler.run_watchlist_check(force=False)


def page_watchlist() -> None:
    ss = st.session_state
    st.title("Filing Watchlist — Real-Time Risk Monitor")
    if is_demo():
        st.info("**The watchlist is read-only in this public demo, so it is switched off.** The watchlist stores companies and alerts in a local "
                "SQLite file and checks for new filings on a schedule. A public host has an ephemeral filesystem (anything stored is lost on "
                "restart and would be shared between visitors) and no scheduler, and adding a company needs live SEC calls. " + DEMO_NOTE)
        st.caption("Nothing is stored and no database file is created in demo mode. Run the app locally to use the watchlist "
                   "(`python watchlist_monitor.py --help` for the headless monitor).")
        return
    if not live_allowed():
        st.warning("The watchlist (add, remove, run, acknowledge) is locked. Enter the access code in the sidebar to use it.")
        return
    try:
        manager, _ = _wl_modules()
        manager.init_db()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Watchlist storage is unavailable: {type(exc).__name__}: {exc}")
        return
    mode = theme_mode()
    job: Optional[Job] = ss.get("watch_job")
    running = bool(job and not job.finished)

    # ---- add
    with st.form("add_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 2])
        t = c1.text_input("Ticker", key="wl_ticker")
        thr = c2.selectbox("Alert threshold", ["Low", "Medium", "High", "Critical"], index=1, key="wl_thr")
        c3.write("")
        submitted = c3.form_submit_button("Add to Watchlist")
    if submitted:
        if not t.strip():
            st.error("Enter a ticker.")
        else:
            try:
                with st.spinner("Resolving ticker on SEC EDGAR..."):
                    comp = manager.add_company(t, thr)
                st.success(f"Added {comp['ticker']} ({comp.get('company_name') or 'name unavailable'}) with alert threshold {thr}.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not add {t!r}: {exc}")

    # ---- running job
    if job is not None:
        if not job.finished:
            title = "Checking all companies for new filings" if job.kind == "watch_check" else f"Analyzing {job.label}"
            render_progress(job, title) if job.kind == "watch_run" else st.status(f"{title}... ({time.time() - job.started:.0f}s)", state="running")
            poll_rerun(job)
        elif not job.processed:
            job.processed = True
            if job.error:
                ss["watch_msg"] = ("error", f"{job.kind.replace('_', ' ')} failed for {job.label or 'watchlist'}: {job.error}")
            elif job.kind == "watch_run":
                r = job.result or {}
                ss["watch_msg"] = ("success", f"{r.get('ticker')}: grade {r.get('grade')} (previously {r.get('previous') or 'none'})" + (" - ALERT created." if r.get("alert_id") else ""))
            else:
                res = job.result or []
                ss["watch_msg"] = ("info", "Check complete: " + "; ".join(f"{x.get('ticker')}: {x.get('status')}" + (f" ({x.get('error')})" if x.get("error") else "") for x in res) if res else "Check complete: no active companies.")
            st.rerun()
    if ss.get("watch_msg"):
        kind, msg = ss.pop("watch_msg")
        getattr(st, kind)(msg)

    # ---- alerts
    try:
        companies = manager.list_companies(active_only=False)
        alerts = manager.list_alerts(unacknowledged_only=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the watchlist database: {exc}")
        return
    names = {c["ticker"]: c.get("company_name") or c["ticker"] for c in companies}
    if alerts:
        st.subheader("Unacknowledged alerts")
        for a in alerts:
            c1, c2 = st.columns([6, 1])
            c1.warning(f"⚠️ {F.md_escape(names.get(a['ticker'], a['ticker']))} risk elevated from {a.get('previous_grade')} to "
                       f"{a.get('new_grade')} on {str(a.get('alert_date', ''))[:10]}")
            if a.get("trigger_reason"):
                c1.caption(F.md_escape(a["trigger_reason"]))
            if c2.button("Acknowledge", key=f"ack_{a['id']}"):
                manager.acknowledge_alert(a["id"])
                st.rerun()

    # ---- table
    active = [c for c in companies if c.get("active")]
    st.subheader("Watched companies")
    if not active:
        st.info("The watchlist is empty. Add a ticker above to start monitoring it.")
    else:
        hdr = st.columns([3, 1.5, 2, 1, 1.6, 3.2])
        for h, lbl in zip(hdr, ["Company", "Risk Grade", "Last Analyzed", "Flags Fired", "Trend", "Actions"]):
            h.markdown(f"**{lbl}**")
        for c in active:
            cols = st.columns([3, 1.5, 2, 1, 1.6, 3.2])
            cols[0].markdown(f"**{F.md_escape(c.get('company_name') or c['ticker'])}**  \n`{c['ticker']}`  \n<span class='small'>alert at {c.get('alert_threshold')}</span>", unsafe_allow_html=True)
            g = c.get("last_grade")
            cols[1].markdown(F.badge_html(g) if g else '<span class="small">not analyzed</span>', unsafe_allow_html=True)
            cols[2].write((c.get("last_analyzed") or "never")[:16].replace("T", " "))
            cols[3].write("n/a" if c.get("flags_fired") is None else c["flags_fired"])
            trend = c.get("trend")
            cols[4].write({"up": "↑ escalating", "flat": "→ stable", "down": "↓ improving"}.get(trend, "n/a (needs 2 analyses)"))
            a1, a2, a3 = cols[5].columns(3)
            if a1.button("Run Now", key=f"run_{c['ticker']}", disabled=running):
                ss["watch_job"] = Job("watch_run", c["ticker"]).start(_watch_run_worker(c))
                st.rerun()
            if a2.button("Remove", key=f"rm_{c['ticker']}", disabled=running):
                manager.remove_company(c["ticker"])
                st.rerun()
            if a3.button("View History", key=f"hist_{c['ticker']}"):
                ss["wl_hist"] = c["ticker"]
                st.rerun()
        if st.button("Check all for new filings now", disabled=running, key="btn_check_all"):
            ss["watch_job"] = Job("watch_check", "").start(_watch_check_worker)
            st.rerun()
        st.caption("Run Now analyzes the company immediately (5 years). Removing keeps its history (soft remove); re-adding reactivates it.")

    # ---- history chart
    st.subheader("Risk history")
    if not companies:
        st.info("No history yet.")
        return
    tickers = [c["ticker"] for c in companies]
    default = ss.get("wl_hist") if ss.get("wl_hist") in tickers else tickers[0]
    sel = st.selectbox("Company", tickers, index=tickers.index(default), key="wl_hist_sel", format_func=lambda x: f"{x} - {names.get(x, x)}")
    hist = manager.get_risk_history(sel)
    if not hist:
        st.info(f"No analyses recorded for {sel} yet. Press Run Now to create the first data point.")
    else:
        fig, skipped = C.risk_history_chart(hist, mode)
        show_fig(fig, "fig_riskhist")
        if skipped:
            st.caption(f"{skipped} analysis row(s) have no suspicion score and are not plotted.")
        table([{"Analysis date": h["analysis_date"][:16].replace("T", " "), "Grade": h.get("risk_grade") or "n/a", "Suspicion": h.get("suspicion_score"),
                "Flags fired": h.get("flags_fired"), "Top finding": h.get("smoking_gun_1")} for h in reversed(hist)])


# =============================================================================================== PAGE 3
RESULTS_ROOT = ROOT / "evaluation" / "results"
LIVE_RUNS_ROOT = ROOT / ".cache" / "ui_eval_runs"


def results_root() -> Path:
    """Where the saved result sets live (FFA_RESULTS_DIR overrides it; used by the tests)."""
    return Path(os.environ.get("FFA_RESULTS_DIR") or RESULTS_ROOT)


def live_runs_root() -> Path:
    return Path(os.environ.get("FFA_LIVE_RUNS_DIR") or LIVE_RUNS_ROOT)


def _eval_worker(mode: str, out_dir: Path) -> Callable[[Job], Any]:
    def run(job: Job):
        from evaluation.evaluator import run_evaluation
        return run_evaluation(mode, progress_callback=job.emit, results_dir=out_dir)
    return run


def metric_card(col, label: str, m: dict, extra: str = "") -> None:
    if m["value"] is None:
        val, ci = "undefined", "no cases in the denominator" if m.get("n") == 0 else "not reported"
    else:
        val = f"{m['value'] * 100:.1f}%"
        ci = f"95% Wilson CI {m['ci'][0] * 100:.0f}% - {m['ci'][1] * 100:.0f}%" if m["ci"] else "95% CI not reported"
        if m.get("ci_source") and m["ci_source"] != "evaluator":
            ci += f" ({m['ci_source']})"
    col.markdown(f'<div class="card"><div class="metriclbl">{F.esc(label)}</div><div class="metricval">{F.esc(val)}</div>'
                 f'<div class="metricci">{F.esc(ci)}{("<br>" + F.esc(extra)) if extra else ""}</div></div>', unsafe_allow_html=True)


def page_eval() -> None:
    ss = st.session_state
    mode = theme_mode()
    st.title("Backtesting Results — Known Fraud vs Clean Companies")
    st.write("The evaluation framework that separates a serious tool from a demo. Results on 12 SEC filings from known fraud cases and matched clean companies.")
    st.caption("Note: the clean companies are six large surviving US companies and are not size- or industry-matched to the fraud cases. "
               "The larger sealed holdouts (24 and 30 filings) use matched clean controls; pick a result set below.")

    job: Optional[Job] = ss.get("eval_job")
    running = bool(job and not job.finished)

    # ---- optional live run (never the default; writes to a NEW timestamped folder, overwrites nothing)
    if is_demo():
        st.caption("Demo mode: you are browsing the saved result sets; running a new live evaluation is disabled.")
    else:
        with st.expander("Advanced: run a NEW live evaluation (not needed to view the saved results below)"):
            c1, c2 = st.columns([2, 3])
            eval_locked = not live_allowed()
            ev_mode = c1.selectbox("Evaluation mode", ["spec", "strict", "both"], key="ev_mode", disabled=running or eval_locked,
                                   help="spec = the spec's analysis years (headline); strict = only filings made before the fraud was public")
            c2.write("")
            c2.write("")
            out_hint = live_runs_root() / "<timestamp>"
            c2.caption(f"Runs the CURRENT code on the 12 development cases only, with live SEC / Claude / Jev calls (needs API keys and network). "
                       f"It writes to {out_hint.as_posix()} and overwrites nothing under evaluation/results/. Development cases are not a performance estimate.")
            if st.button("Run live evaluation on the 12 development cases (~10-15 min)", type="primary", disabled=running or eval_locked, key="btn_eval") and live_allowed():
                out_dir = live_runs_root() / time.strftime("%Y%m%d_%H%M%S")
                ss["eval_job"] = Job("eval", ev_mode).start(_eval_worker(ev_mode, out_dir))
                ss["eval_out_dir"] = str(out_dir)
                st.rerun()

    if job is not None:
        if not job.finished:
            evs = job.snapshot()
            with st.status(f"Evaluation running ({time.time() - job.started:.0f}s elapsed) - {len(evs)} progress event(s)", state="running", expanded=True):
                for ev in evs[-14:]:
                    who = ev.get("ticker") or ev.get("case") or ev.get("node") or ""
                    st.write(f"{who} {ev.get('status', '')} {ev.get('message', '')}".strip())
            tot = next((ev.get("total") or ev.get("n_cases") for ev in reversed(evs) if ev.get("total") or ev.get("n_cases")), None)
            done = next((ev.get("done") or ev.get("index") or ev.get("completed") for ev in reversed(evs) if ev.get("done") or ev.get("index") or ev.get("completed")), None)
            if tot and done:
                st.progress(min(1.0, float(done) / float(tot)), text=f"{done} of {tot} cases")
            poll_rerun(job, 1.0)
        elif not job.processed:
            job.processed = True
            if job.error:
                ss["eval_msg"] = ("error", f"Evaluation failed: {job.error}")
            else:
                ss["eval_msg"] = ("success", f"Evaluation finished; written to {ss.get('eval_out_dir')}. It is available in the result-set selector as 'Live run'.")
                ss["eval_live"] = {"id": "live", "dir": "", "role": "development", "version": "current code", "n": 12, "root": ss.get("eval_out_dir"),
                                   "label": f"Live run from this session ({Path(str(ss.get('eval_out_dir'))).name}) - 12 development cases, current code"}
                ss["ev_set"] = "live"
            st.rerun()
    if ss.get("eval_msg"):
        kind, msg = ss.pop("eval_msg")
        getattr(st, kind)(msg)

    # ---- result-set selector (default: H2 v3, the most meaningful out-of-sample result)
    sets = list(EA.RESULT_SETS) + ([ss["eval_live"]] if ss.get("eval_live") else [])
    by_id = {x["id"]: x for x in sets}
    if ss.get("ev_set") not in by_id:
        ss["ev_set"] = sets[0]["id"]
    sid = st.selectbox("Result set (which evaluation to show)", [x["id"] for x in sets], key="ev_set",
                       format_func=lambda i: by_id[i]["label"],
                       help="Sealed holdouts are the only out-of-sample results. Development-case numbers are shown for completeness only.")
    spec = by_id[sid]
    results, note = EA.load_result_set(spec.get("root") or results_root(), spec)
    if results is None:
        st.info(f"**No saved result for this set.** {note or ''}")
        _eval_limitations(None, spec=spec)
        st.caption(EVAL_DISCLAIMER)
        return
    render_eval(results, mode, spec)


def _set_banner(spec: dict, results: dict) -> None:
    """Role / version / n header and the development-vs-holdout banner for the selected result set."""
    block, _ = EA.pick_mode(results, results.get("headline_key"))
    meta = results.get("metadata") or {}
    n_eval = block.get("n_evaluable") if isinstance(block, dict) else None
    role = "SEALED HOLDOUT (out-of-sample)" if spec["role"] == "sealed" else "DEVELOPMENT SET"
    st.markdown(f"**Role:** {role}  |  **Pipeline version:** {F.md_escape(spec['version'])}  |  **n:** {spec['n']} filings"
                + (f" ({n_eval} evaluable)" if n_eval is not None and n_eval != spec["n"] else "")
                + (f"  |  code hash `{str(meta.get('code_hash'))[:16]}`" if meta.get("code_hash") else ""))
    if spec["role"] == "development":
        st.error("**DEVELOPMENT-SET NUMBERS ARE NOT PERFORMANCE ESTIMATES.** The detection rules were designed and tuned while looking at "
                 "these cases, so any score on them is optimistic and contaminated. For an out-of-sample result select a sealed holdout "
                 "(H2 or Holdout 1) in the selector above.")
    else:
        st.info("**Sealed holdout.** Cases were chosen and frozen before the run, one run per version with live keys. Even so n is tiny, "
                "confidence intervals are wide, and each set is now spent (never tune on it). Treat every figure below as descriptive.")
    st.caption(EA.set_audit_note(spec))


def render_eval(results: dict, mode: str, spec: Optional[dict] = None) -> None:
    spec = spec or {"id": "dev_v2", "role": "development", "version": "?", "n": 12}
    _set_banner(spec, results)
    runs = EA.available_modes(results)
    hk = results.get("headline_key")
    if len(runs) > 1:
        view = st.radio("Run (headline and sensitivity analyses)", runs, key=f"ev_view_{spec['id']}", horizontal=False,
                        format_func=lambda k: EA.run_label(k, hk) if "/" in k else k,
                        help="The headline is the spec run with the frozen rules. Every other run is a labelled sensitivity analysis.")
    else:
        view = runs[0] if runs else None
    block, mname = EA.pick_mode(results, view)
    is_headline = (mname == hk) if hk else True
    meta = results.get("run_metadata") or results.get("metadata") or {}
    keys = meta.get("keys_available") or meta.get("keys") or {}
    if not keys and isinstance(meta, dict):
        keys = {n: meta[f] for n, f in (("ANTHROPIC_API_KEY", "anthropic_key_available"), ("JEV_API_KEY", "jev_key_available")) if f in meta}
    keys_missing = isinstance(keys, dict) and any(v is False for v in keys.values())
    degraded_run = keys_missing or bool(results.get("degraded") or (isinstance(block, dict) and block.get("degraded_run")))
    if keys_missing:
        missing = ", ".join(k for k, v in keys.items() if v is False)
        st.markdown('<div class="banner-degraded"><b>DEGRADED EVALUATION.</b> This backtest ran without ' + F.esc(missing) +
                    " (no Claude and/or no Jev): no LLM specificity score or narrative, no Jev confidence, and Critical grades are unreachable. "
                    "Results reflect the deterministic fallbacks only and understate what the full system may do.</div>", unsafe_allow_html=True)
    elif degraded_run:
        dc = (block.get("degraded_components") or {}) if isinstance(block, dict) else {}
        what = "; ".join(f"{k} ({len(v)} case(s))" for k, v in dc.items() if isinstance(v, list)) if isinstance(dc, dict) else ""
        st.caption("Live Claude and Jev keys were available for this run, but some components fell back to deterministic behaviour in some cases"
                   + (f": {what}" if what else "") + ". Details are in the case table and the evaluator's degraded-components list.")
    ts = meta.get("timestamp") or meta.get("timestamp_utc") or meta.get("run_timestamp") if isinstance(meta, dict) else None
    st.caption(f"Showing run: **{mname}**" + (" (headline)" if is_headline else " (SENSITIVITY analysis, not the headline)")
               + (f"  |  run at {ts}" if ts else "") + (f"  |  code hash {str(meta.get('code_hash'))[:12]}" if isinstance(meta, dict) and meta.get("code_hash") else ""))

    rows = EA.cases_of(block)
    h = EA.headline(block)
    st.subheader("Headline metrics" if is_headline else f"Metrics for sensitivity run {mname}")
    for ln in EA.result_lines(results, mname):
        st.markdown(ln.replace("$", "\\$"))
    if block.get("n_excluded") or block.get("n_error"):
        st.warning(f"{block.get('n_error', 0)} case(s) errored and {block.get('n_excluded', 0)} were excluded from this run's matrix: "
                   + "; ".join(f"{e.get('ticker')} ({e.get('reason')})" for e in (block.get("excluded") or []) if isinstance(e, dict)))
    conf = h["confusion"]
    cols = st.columns(4)
    metric_card(cols[0], "Precision", h["precision"], f"n = {h['precision']['n']} predicted positives" if h["precision"]["n"] is not None else "")
    metric_card(cols[1], "Recall", h["recall"], f"n = {h['recall']['n']} fraud cases" if h["recall"]["n"] is not None else "")
    metric_card(cols[2], "F1", h["f1"], h["f1"].get("note") or "")
    metric_card(cols[3], "False Positive Rate", h["fpr"], f"n = {h['fpr']['n']} clean cases" if h["fpr"]["n"] is not None else "")
    if any(v is not None for v in conf.values()):
        st.caption("Confusion matrix: " + ", ".join(f"{k} = {v}" for k, v in conf.items()) + ". A positive prediction is a High or Critical grade. Cases that errored are excluded and listed.")

    # paired (cutoff-free) metric: present in v3 result rows only
    paired = EA.paired_of(block)
    if paired:
        st.subheader("Paired score metric (fraud vs its matched control, cutoff-free)")
        pc = st.columns(4)
        pc[0].metric("Fraud scores higher", f"{paired['wins']} of {paired['n_pairs']} pairs")
        pc[0].caption(f"{paired['ties']} tie(s), {paired['losses']} loss(es)")
        pc[1].metric("Sign test (two-sided)", "n/a" if paired["p"] is None else f"p = {paired['p']:.3f}")
        pc[1].caption(f"{paired['n_non_tied']} non-tied pairs")
        pc[2].metric("Paired AUC", "n/a" if paired["auc"] is None else f"{paired['auc']:.2f}")
        if paired["auc_lo"] is not None and paired["auc_hi"] is not None:
            pc[2].caption(f"bootstrap 95% CI {paired['auc_lo']:.2f}-{paired['auc_hi']:.2f}")
        pc[3].write("")
        st.caption("Descriptive only, not a detection rate: it compares the focus-year temporal suspicion score of each fraud filing with its matched control, "
                   "with no grade cutoff. Per docs/H2_AUDIT.md only about 5 of the 11 wins are genuine and all 3 losses are artifact-driven. "
                   "Defined only for v3 result rows (v1 and v2 rows do not carry the instrumentation).")
        if paired["pairs"]:
            with st.expander(f"Per-pair scores ({len(paired['pairs'])} pairs)"):
                table([{"Fraud": x.get("fraud"), "Control": x.get("control"), "Fraud score": x.get("fraud_score"),
                        "Control score": x.get("control_score"), "Result": x.get("result")} for x in paired["pairs"]], key="tbl_paired")

    # baselines
    st.subheader("Baselines for comparison")
    brows = EA.baselines_of(block)
    if brows:
        table([{"Predictor": b["name"], "Precision": EA.fmt_metric(b["m"].get("precision")), "Recall": EA.fmt_metric(b["m"].get("recall")),
                "F1": EA.fmt_metric(b["m"].get("f1")), "FPR": EA.fmt_metric(b["m"].get("fpr")), "Accuracy": EA.fmt_metric(b["m"].get("accuracy"))}
               for b in brows], key="tbl_baselines")
        bn = (block.get("baselines") or {}).get("note")
        un = (block.get("baselines") or {}).get("beneish_unavailable_cases")
        st.caption((bn or "") + (f" Beneish unavailable for: {', '.join(un)}." if un else ""))
    elif isinstance(block.get("baselines"), dict) and block["baselines"]:
        with st.expander("Baselines for comparison"):
            st.json(block["baselines"])
    else:
        st.info("No baselines in the results file.")

    # timing
    st.subheader("Detection timing")
    tm = EA.timing_of(block, rows)
    if tm["detected"]:
        labels = [i["label"] + ("" if i["valid"] is not False else "  (not a valid early-warning test)") for i in tm["detected"]]
        ok_vals = [i["months"] if i["valid"] is not False else None for i in tm["detected"]]
        bad_vals = [i["months"] if i["valid"] is False else None for i in tm["detected"]]
        series = [("Valid early-warning test (filing pre-dates revelation)", ok_vals, None)]
        if tm["invalid"]:
            series.append(("NOT a valid early-warning test (analysed filing post-dates public revelation)", bad_vals, "#8a8a85"))
        fig = C.hbar("Months between first flag and public revelation", labels, series, "Months before public revelation (negative = flagged only after it)", mode,
                     height=max(260, 90 + 56 * len(labels)))
        show_fig(fig, "fig_timing")
        if tm["average"] is not None:
            st.markdown(f"### Average detection: **{tm['average']:.1f} months** before public revelation")
        else:
            st.markdown("### Average detection: not available")
        excl = [i["label"] for i in tm["detected"] if i not in tm["positive"]]
        st.caption(f"n = {len(tm['positive'])} fraud case(s) with a valid pre-revelation filing and a positive lead (of {tm['n_fraud']} fraud cases; {len(tm['detected'])} detected)."
                   + (f" Excluded from the average: {', '.join(excl)}"
                      + (f" ({', '.join(i['label'] for i in tm['invalid'])}: analysed filing post-dates public revelation, so not a valid early-warning test)" if tm["invalid"] else "") + "." if excl else "")
                   + (f" The evaluator's own average ({tm['evaluator_average']:.1f} months) also counts the post-revelation-filing cases." if tm["evaluator_average"] is not None and tm["invalid"] else "")
                   + " A very small n: do not generalise. " + (tm["caveat"] or "Detection is quantized to annual filing dates."))
    else:
        st.info("No fraud case has a recorded detection lead time (none detected, or timing not reported); no average is reported.")

    # agent contribution
    st.subheader("Agent contribution")
    contrib = EA.agent_contrib_of(block)
    if contrib and any(c["unique_pct"] is not None or c["flagged_pct"] is not None for c in contrib):
        labels = [F.AGENT_LABELS.get(c["agent"], c["agent"]) for c in contrib]
        series = []
        if any(c["flagged_pct"] is not None for c in contrib):
            series.append(("Fraud cases flagged (%)", [c["flagged_pct"] for c in contrib], None))
        if any(c["unique_pct"] is not None for c in contrib):
            series.append(("Caught only by this agent (%)", [c["unique_pct"] for c in contrib], None))
        if any(c.get("false_alarm_pct") is not None for c in contrib):
            series.append(("Clean companies flagged (%)", [c.get("false_alarm_pct") for c in contrib], None))
        show_fig(C.hbar("Share of cases flagged by agent", labels, series, "% of the fraud (or clean) cases", mode, height=max(300, 90 + 80 * len(labels)), xrange=(0, 115)), "fig_contrib")
        if any("flagged_cases" in c for c in contrib):
            table([{"Agent": F.AGENT_LABELS.get(c["agent"], c["agent"]), "Fraud cases flagged": ", ".join(c.get("flagged_cases", [])) or "none",
                    "Caught only by this agent": ", ".join(c.get("unique_cases", [])) or "none",
                    "Clean companies flagged": ", ".join(c.get("false_alarm_cases", [])) or "none",
                    "Unavailable for": ", ".join(c.get("unavailable_cases", [])) or "-"} for c in contrib], key="tbl_contrib")
    else:
        st.info("Agent-contribution data not present in the results file.")

    fn = block.get("fraud_nature")
    if isinstance(fn, dict) and fn:
        st.subheader("Recall by fraud type")
        table([{"Fraud type": k.replace("_", " "), "Cases": v.get("n_cases"), "Detected (TP)": v.get("tp"), "Missed (FN)": v.get("fn"),
                "Recall": EA.fmt_metric(v.get("recall")), "Tickers": ", ".join(c.get("ticker", "?") for c in v.get("cases", []))} for k, v in fn.items() if isinstance(v, dict)],
              key="tbl_nature")

    # case table
    st.subheader("Case-by-case results")
    if rows:
        table([EA.case_view(r) for r in rows], key="tbl_cases")
        errs = [r for r in rows if r.get("error") or str(r.get("status", "")).upper() == "ERROR"]
        if errs:
            st.warning(f"{len(errs)} case(s) errored and are excluded from the confusion matrix (not counted as negatives).")
        n_inv = sum(1 for r in rows if r.get("pre_revelation_valid") is False and r.get("ground_truth") in (1, True))
        if n_inv:
            st.caption(f"{n_inv} fraud case(s) in this run were analysed on a filing that post-dates public revelation: a detection there is not early warning.")
    else:
        st.info("No per-case rows in the results file.")
    _eval_limitations(block, results, spec)
    with st.expander("Raw results JSON"):
        st.json({k: v for k, v in results.items() if k != "report_markdown"}, expanded=False)
    st.caption(results.get("disclaimer") or EVAL_DISCLAIMER)
    if results.get("disclaimer") and results["disclaimer"] != EVAL_DISCLAIMER:
        st.caption(EVAL_DISCLAIMER)


def _eval_limitations(block: Optional[dict], results: Optional[dict] = None, spec: Optional[dict] = None) -> None:
    st.subheader("Contamination and limitations")
    dev = (spec or {}).get("role", "development") == "development"
    lim = EA.limitations_markdown(results) if isinstance(results, dict) and dev else None
    if not dev:
        st.warning("These are the best available out-of-sample numbers and are still weak evidence. Read the audit before quoting any number.")
        st.markdown(
            "- **Tiny sample.** 24 or 30 filings (half fraud): Wilson intervals are wide, and a few cases flip every conclusion; versions cannot be separated statistically.\n"
            "- **Genuine versus artifact.** The independent audits found that most High grades (and several misses) came from data-extraction artifacts or boilerplate, not real forensic signal. See "
            f"{EA.AUDIT_DOCS['h2']} and {EA.AUDIT_DOCS['holdout1']}.\n"
            "- **Controls are 'no known problem', not proven clean**, and the sets must not be pooled with each other or with the development cases.\n"
            "- **Spent sets.** Both holdouts have been inspected and used for fixes; they can no longer serve as untouched tests.\n"
            "- **Timing is quantized** to annual filing dates. The evaluator's built-in limitation text describes the 12 development cases and is shown only for them.")
    elif lim:
        st.warning("These results are NOT clean out-of-sample evidence. Read this section before quoting any number.")
        st.markdown(F.md_escape(lim.replace("## LIMITATIONS AND CONTAMINATION (READ BEFORE QUOTING ANY NUMBER)", "").strip()))
    else:
        st.markdown(
            "- **Tiny sample.** 12 filings (6 fraud, 6 clean): confidence intervals are wide; no result here supports a claim of general accuracy.\n"
            "- **Selection and survivorship bias.** The fraud cases are famous failures chosen with hindsight; the clean cases are surviving large companies, not size/industry matched.\n"
            "- **Look-ahead risk.** Some spec analysis years use a filing made after the fraud was public (flagged `pre_revelation_valid=False` in the case data); the *strict* mode re-runs on pre-revelation filings only.\n"
            "- **Model contamination.** Claude was trained on public text that discusses these cases; any LLM-written narrative for them may reflect that knowledge. The grade itself comes from deterministic rules fixed before the evaluation.\n"
            "- **Fraud types differ.** Only some cases are financial-statement frauds that Beneish/Altman-style analytics target; others are disclosure or claims cases.\n"
            "- **Timing is quantized** to annual filing dates.")
    extra = []
    for src in (block, results):
        if isinstance(src, dict):
            for k in ("limitations", "contamination", "caveats", "notes"):
                v = src.get(k)
                if isinstance(v, str):
                    extra.append(v)
                elif isinstance(v, list):
                    extra.extend(str(x) for x in v)
    if extra:
        st.markdown("**From the evaluator:**")
        for e in dict.fromkeys(extra):
            st.markdown(f"- {F.md_escape(e)}")
    if isinstance(results, dict) and isinstance(results.get("metadata"), dict):
        dc = (block or {}).get("degraded_components") if isinstance(block, dict) else None
        if isinstance(dc, dict) and dc:
            with st.expander("Degraded components in this run (cases affected)"):
                table([{"Component": k, "Cases": ", ".join(v)} for k, v in dc.items()], key="tbl_degraded")


# =============================================================================================== main
def main() -> None:
    page = sidebar_nav()
    if page == PAGES[0]:
        page_analysis()
    elif page == PAGES[1]:
        page_watchlist()
    else:
        page_eval()


main()
