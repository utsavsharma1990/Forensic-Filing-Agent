#!/bin/bash
# Run v3, v2, v1 on the sealed H2 holdout, exactly once each (docs/V3_PROTOCOL.md).
set -u
cd "C:/Users/Utsav.Sharma/source/forensic-filing-agent"
export PYTHONIOENCODING=utf-8
for spec in "v3|C:/Users/Utsav.Sharma/source/forensic-filing-agent" "v2|C:/Users/Utsav.Sharma/source/forensic-filing-agent-v2-snapshot" "v1|C:/Users/Utsav.Sharma/source/forensic-filing-agent-v1-snapshot"; do
  v="${spec%%|*}"; root="${spec#*|}"
  echo "=== H2 $v ($root) $(date +%H:%M:%S) ==="
  python scripts/run_holdout.py --root "$root" --out "evaluation/results/h2_$v" --no-cache --cases-module holdout2_cases --cases-var HOLDOUT2_CASES > ".cache/h2_$v.log" 2>&1
  echo "exit=$? $(tail -2 .cache/h2_$v.log | tr '\n' ' ' | cut -c1-260)"
done
