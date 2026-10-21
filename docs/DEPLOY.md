# Deploying a public demo (Streamlit Community Cloud)

The public demo is **read-only and key-free**: it shows the saved analyses in `sample_analysis/` and the saved backtest result sets in
`evaluation/results/`. It makes no SEC, Claude or Jev calls, creates no watchlist database, and never imports the pipeline, EDGAR client,
LLM clients, spaCy or the scheduler. Everything the visitor sees was produced earlier and is committed to the repo.

## Demo deployment (recommended)

1. Push this repository to GitHub (public, or private with Streamlit access). Make sure `.env` is NOT committed (it is gitignored).
   `sample_analysis/` and `evaluation/results/` must be in the repo.
2. Go to <https://share.streamlit.io>, sign in with GitHub, **Create app** -> "Deploy a public app from GitHub".
3. Repository: your fork/repo; Branch: `main`; **Main file path: `deploy/streamlit_demo.py`**.
4. **Advanced settings**: Python version **3.11**. Secrets: leave empty (none needed).
5. Dependencies: Streamlit Cloud installs from the requirements file found next to the main file first, so
   `deploy/requirements.txt` (streamlit, plotly, pandas, numpy) is used instead of the heavy root `requirements.txt`. If your Cloud
   build picks up the root file instead, move/copy `deploy/requirements.txt` to the repo root of a dedicated demo branch.
6. Deploy. `deploy/streamlit_demo.py` sets `FFA_DEMO_MODE=1` itself, so the demo cannot start in live mode by accident.

Locally the same thing is: `pip install -r deploy/requirements.txt && streamlit run deploy/streamlit_demo.py`.

## Demo mode rules (`FFA_DEMO_MODE`)

* `1` / `true` / `yes` => demo; `0` / `false` / `no` => live; unset => **auto**: demo unless a real `SEC_USER_AGENT` is configured
  (set, contains an `@`, and not a placeholder such as `your@email` or `example.com`; read from the environment, then `.env`).
* Demo: page 1 offers only "Load saved analysis" (samples only), page 2 is an explanatory read-only notice, page 3 browses the result sets
  with the live-evaluation expander hidden; the sidebar shows "DEMO MODE: read-only, saved results only".

## Optional: a live deployment (not recommended on a public URL)

Streamlit Cloud exposes top-level secrets as environment variables. In **Settings -> Secrets**:

```toml
ANTHROPIC_API_KEY = "..."
JEV_API_KEY = "..."
SEC_USER_AGENT = "YourApp your-real@email.com"
FFA_ACCESS_CODE = "a long random string"
FFA_DEMO_MODE = "0"
```

and use `app.py` as the main file with the root `requirements.txt` plus the spaCy model wheel line (take the exact
`en_core_web_sm` URL from `docs/requirements.lock.txt`; without it a rule-based fallback is used).

* **Cost and abuse warning.** Every analysis spends Anthropic and Jev credits and hits SEC EDGAR (rate-limited, identified by your
  `SEC_USER_AGENT`). Anyone with the URL can trigger runs unless `FFA_ACCESS_CODE` is set; with it, analysis runs, watchlist actions and
  evaluation runs are locked until the code is typed into the sidebar (checked with `hmac.compare_digest`; the code is never logged).
  The gate is a speed bump, not an authentication system: keep the app private (Cloud sharing settings) and set provider spend limits.
* The filesystem is ephemeral: the EDGAR cache, live evaluation outputs and any SQLite file are lost on restart and shared by all visitors.
* **The watchlist is not supported on Cloud** (no scheduler, ephemeral disk). Run it locally or on your own server.
* Memory and time: the free tier has roughly 1 GB RAM. A full analysis (spaCy, lxml parsing of several 10-Ks, LangGraph) takes minutes
  and may exceed that; the 12-case live evaluation (10-15 min) is not realistic there.

## What was verified, and what was not

Verified locally (Windows, Python 3.14 host): a fresh venv with only `deploy/requirements.txt` runs `deploy/streamlit_demo.py` under
Streamlit AppTest (sample load, watchlist notice, every result-set selector option, 0 exceptions), `streamlit run` serves `/` with HTTP 200 and
`/_stcore/health` = ok, no live-only module is imported, and no database file is created. Tests: `tests/test_app.py`.

**Not verified:** Streamlit Community Cloud itself (build, requirements-file precedence, Python 3.11 selection, memory limits, secrets
injection, sleep/wake behaviour) cannot be tested from here. The live deployment path was not run on Cloud at all.
