"""Streamlit Community Cloud entrypoint for the PUBLIC read-only demo.

Main file path on Streamlit Cloud: deploy/streamlit_demo.py
Forces demo mode (saved results only: no SEC / Claude / Jev calls, no watchlist database), puts the repo root on sys.path and
as the working directory, then runs ../app.py as __main__.
"""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["FFA_DEMO_MODE"] = "1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
