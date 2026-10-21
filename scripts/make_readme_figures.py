"""Regenerate the README charts from the stored evaluation results (evaluation/results/**/evaluation_results.json).

Everything is read from the result files except the audit-verified 'genuine' counts, which come from the written audits
(docs/EVAL_AUDIT.md, docs/HOLDOUT_AUDIT.md, docs/H2_AUDIT.md) and are marked as such below.
Usage: python scripts/make_readme_figures.py   (needs matplotlib; see requirements-dev.txt)
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evaluation" / "results"
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
COL = {"v1": "#8c8c8c", "v2": "#e6a23c", "v3": "#c0392b"}


def wilson(k: int, n: int, z: float = 1.959964):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def run(path: str) -> dict:
    return json.loads((RES / path / "evaluation_results.json").read_text(encoding="utf-8"))["runs"]["spec/spec"]


def counts(r: dict):
    m = r["metrics"]
    return m["tp"], m["fn"], m["fp"], m["tn"]


SETS = [  # (title, {version: results folder}, audit-verified genuine detections among v1's High grades)
    ("Development\n(12 filings, 6 fraud)", {"v1": "v1_dev_live_keys", "v2": ".", "v3": "v3_dev"}, 1),
    ("Sealed holdout 1\n(24 filings, 12 fraud)", {"v1": "holdout_v1", "v2": "holdout_v2"}, 1),
    ("Sealed holdout H2\n(30 filings, 15 fraud)", {"v1": "h2_v1", "v2": "h2_v2", "v3": "h2_v3"}, 1),
]
GENUINE_NOTE = "audit-verified genuine hits among v1's High grades (EVAL_AUDIT, HOLDOUT_AUDIT, H2_AUDIT)"

# ---- Figure 1: recall by version and set
fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.4), sharey=True)
for ax, (title, vers, genuine) in zip(axes, SETS):
    xs = range(len(vers))
    for i, (v, folder) in enumerate(vers.items()):
        tp, fn, fp, tn = counts(run(folder))
        p, lo, hi = wilson(tp, tp + fn)
        ax.bar(i, p * 100, color=COL[v], width=0.62, edgecolor="black", linewidth=0.6)
        ax.errorbar(i, p * 100, yerr=[[p * 100 - lo * 100], [hi * 100 - p * 100]], color="black", capsize=4, linewidth=1.2)
        ax.text(i, min(hi * 100 + 2.5, 96), f"{tp}/{tp + fn}", ha="center", fontsize=10, fontweight="bold")
        if v == "v1":
            gp = genuine / (tp + fn) * 100
            ax.bar(i, gp, color="none", width=0.62, hatch="///", edgecolor="#1b4f72", linewidth=1.4)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(list(vers.keys()))
    ax.set_title(title, fontsize=11)
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.25)
axes[0].set_ylabel("Recall at the High/Critical cutoff (%)\n(bars: headline; whiskers: Wilson 95% CI)")
fig.suptitle("Fraud cases graded High/Critical, by version (hatched = audit-verified genuine hits in v1)", fontsize=12.5, y=1.02)
fig.text(0.5, -0.04, "False alarms at the High cutoff: dev 0/6 clean (all versions); holdout 1: 0/12; H2: 1/15 (all versions). "
         "Development numbers are NOT performance estimates.", ha="center", fontsize=9, color="#444")
fig.tight_layout()
fig.savefig(OUT / "fig_recall_by_version.png", dpi=170, bbox_inches="tight")
plt.close(fig)

# ---- Figure 2: grade distribution on H2
fig, axes = plt.subplots(1, 2, figsize=(11, 4.0), sharey=True)
order, cols = ["Low", "Medium", "High", "Critical"], {"Low": "#7fb77e", "Medium": "#f2c14e", "High": "#e67e22", "Critical": "#c0392b"}
for ax, (label, truth) in zip(axes, (("Fraud filings (15)", 1), ("Matched clean filings (15)", 0))):
    for i, v in enumerate(("v1", "v2", "v3")):
        r = run({"v1": "h2_v1", "v2": "h2_v2", "v3": "h2_v3"}[v])
        c = Counter(x["risk_grade"] for x in r["cases"] if x["ground_truth"] == truth)
        bottom = 0
        for g in order:
            n = c.get(g, 0)
            if n:
                ax.bar(i, n, bottom=bottom, color=cols[g], edgecolor="white", linewidth=0.8, width=0.6, label=g if i == 0 else None)
                ax.text(i, bottom + n / 2, str(n), ha="center", va="center", fontsize=9.5, fontweight="bold")
                bottom += n
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(["v1", "v2", "v3"])
    ax.set_title(label, fontsize=11)
axes[0].set_ylabel("Number of filings")
h, l = axes[0].get_legend_handles_labels()
h2, l2 = axes[1].get_legend_handles_labels()
seen = dict(zip(l + l2, h + h2))
fig.legend([seen[k] for k in order if k in seen], [k for k in order if k in seen], loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.06))
fig.suptitle("H2 sealed holdout: grade distribution (most filings, fraud and clean alike, land at Medium)", fontsize=12, y=1.02)
fig.tight_layout()
fig.savefig(OUT / "fig_grade_distribution_h2.png", dpi=170, bbox_inches="tight")
plt.close(fig)

# ---- Figure 3: cutoff-free paired comparison (fraud vs its matched control)
h2_paired = run("h2_v3").get("paired") or {}
pairs = [("Holdout 1 (v2)\ndescriptive, audit", 8, 3, 1), ("H2 (v3)\nreported by evaluator", h2_paired.get("wins", 11), h2_paired.get("ties", 1), h2_paired.get("losses", 3))]
fig, ax = plt.subplots(figsize=(7.2, 3.6))
for i, (label, w, t, l) in enumerate(pairs):
    left = 0
    for n, color, name in ((w, "#2e7d32", "fraud scores higher"), (t, "#bdbdbd", "tie"), (l, "#c62828", "control scores higher")):
        ax.barh(i, n, left=left, color=color, edgecolor="white", label=name if i == 0 else None)
        if n:
            ax.text(left + n / 2, i, str(n), ha="center", va="center", color="white" if color != "#bdbdbd" else "black", fontweight="bold")
        left += n
ax.set_yticks([0, 1])
ax.set_yticklabels([p[0] for p in pairs])
ax.invert_yaxis()
ax.set_xlabel("Matched pairs (suspicion score of the fraud filing vs its clean control)")
ax.legend(ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.2), loc="upper center", fontsize=9)
ax.set_title(f"A weak ranking signal below the grade cutoff (H2: paired AUC {h2_paired.get('paired_auc', 0.77):.2f}, sign test p = {h2_paired.get('sign_test_p_two_sided', 0.057):.3f})", fontsize=10.5, pad=34)
fig.tight_layout()
fig.savefig(OUT / "fig_paired_scores.png", dpi=170, bbox_inches="tight")
plt.close(fig)
print("wrote", sorted(p.name for p in OUT.glob("fig_*.png")))
