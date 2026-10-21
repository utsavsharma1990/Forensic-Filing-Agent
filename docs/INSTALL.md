# Installation

Verified 2026-10-19 in clean virtual environments on Windows 11: Python 3.14.4 and Python 3.11.9 (both: 904 offline tests passed,
`app.py` loads under Streamlit AppTest with no exception). Not tested: Linux/macOS (commands below are the standard equivalents),
Python 3.10, 3.12 and 3.13 (not installed on the test machine). The project was built on 3.14; "3.10+" is the spec's claim and is unverified below 3.11.

Exact resolved versions that passed are in `docs/requirements.lock.txt` (`pip install -r docs/requirements.lock.txt` for a reproducible install;
it already contains the spaCy model wheel URL). `requirements.txt` uses `>=` pins (runtime), `requirements-dev.txt` adds test tools.

## Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt            # add requirements-dev.txt instead if you will run tests
python -m spacy download en_core_web_sm
copy .env.example .env                      # then edit .env (see below)
streamlit run app.py
```

## Linux / macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # or requirements-dev.txt for tests
python -m spacy download en_core_web_sm
cp .env.example .env                        # then edit .env
streamlit run app.py
```

## .env

```
ANTHROPIC_API_KEY=your-anthropic-key
JEV_API_KEY=your-jev-key
SEC_USER_AGENT="YourAppName your-real@email.com"
```

`SEC_USER_AGENT` must be `AppName contact-email` with a real contact; the SEC rejects anonymous or fake agents. Never commit `.env`.

## Other commands (venv active)

```
python watchlist_monitor.py --add AAPL:Medium --once     # watchlist: add a company and run one check (--list, --daemon, --remove T)
python -m pytest -q -m "not network"                      # offline tests (needs requirements-dev.txt); 904 pass, 87 network tests deselected
python -m pytest -q                                       # also runs live-SEC tests (needs internet + SEC_USER_AGENT)
python -m evaluation.evaluator --mode both --variants spec,no_passive   # reproduce the backtest (~20 min with warm EDGAR cache; hits SEC and APIs)
python scripts/generate_samples.py                        # regenerate sample_analysis/
```

## Common errors

| Symptom | Cause / fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` / SSL errors on SEC or API calls | TLS-inspecting corporate proxy. `truststore` (in requirements) makes Python use the OS certificate store; confirm it is installed (`pip show truststore`). Otherwise set `SSL_CERT_FILE` to your corporate CA bundle. |
| "spaCy model en_core_web_sm unavailable" in a degraded notice | Model not downloaded. Run `python -m spacy download en_core_web_sm`. Without it passive voice uses a rule-based detector (works, less accurate, and the output says so). |
| Output labelled degraded / no LLM or Jev scores | `ANTHROPIC_API_KEY` or `JEV_API_KEY` missing or empty. Everything still runs; the LLM-based and Jev signals are skipped and labelled. |
| HTTP 403 from sec.gov | Missing or invalid `SEC_USER_AGENT`. Use `AppName your-real@email`. Also avoid bursts; SEC limits to about 10 requests/s. |
| `ModuleNotFoundError: httpx2` when running tests | Installed only via `requirements-dev.txt` / `typesafe-sdk`; use `pip install -r requirements-dev.txt`. |
| spaCy or other wheel fails to build on a new Python | Wheels lag new Python releases; use 3.11 to 3.14 (tested) or the lock file. |
