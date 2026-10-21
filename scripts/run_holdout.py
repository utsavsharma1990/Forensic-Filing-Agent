"""Run ONE version of the system on the sealed holdout, once (docs/V2_PROTOCOL.md).

usage: python scripts/run_holdout.py --root <project root of the version> --out <results dir>
The version's own evaluator/agents are imported from --root; holdout cases come from this repo's evaluation/holdout_cases.py;
keys are loaded from this repo's .env; the EDGAR/LLM caches are shared (deterministic, content-addressed).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cases-module", default="holdout_cases")
    ap.add_argument("--cases-var", default="HOLDOUT_CASES")
    a = ap.parse_args()
    root, out = Path(a.root).resolve(), Path(a.out).resolve()
    from dotenv import load_dotenv
    load_dotenv(MAIN / ".env", override=False, encoding="utf-8")
    os.environ.setdefault("EDGAR_CACHE_DIR", str(MAIN / ".cache"))
    spec = importlib.util.spec_from_file_location(a.cases_module, MAIN / "evaluation" / f"{a.cases_module}.py")
    hc = importlib.util.module_from_spec(spec); spec.loader.exec_module(hc)
    cases = getattr(hc, a.cases_var)
    os.chdir(root); sys.path.insert(0, str(root))
    from evaluation import evaluator as ev
    out.mkdir(parents=True, exist_ok=True)
    res = ev.run_evaluation(mode="spec", cases=cases, variants=("spec",), results_dir=out, use_cache=not a.no_cache,
                            progress_callback=lambda m: print(str(m)[:160], flush=True))
    run = res["runs"]["spec/spec"]
    print("ROOT", root, "code_hash", res["metadata"]["code_hash"][:16])
    print("n", run["metrics"]["n"], "TP/FP/TN/FN", run["metrics"]["tp"], run["metrics"]["fp"], run["metrics"]["tn"], run["metrics"]["fn"],
          "errors", run["n_error"], "excluded", run["n_excluded"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
