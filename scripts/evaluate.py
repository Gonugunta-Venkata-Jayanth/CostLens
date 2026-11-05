"""Measure anomaly-detection precision and recall against injected synthetic spikes.

Runs several seeds of the synthetic generator and reports micro-averaged precision,
recall and F1 per threshold. Results are written to reports/evaluation.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from costlens import analytics, synthetic  # noqa: E402
from costlens.pipeline import DuckDBStore  # noqa: E402

SEEDS = range(1, 21)
THRESHOLDS = [2.5, 3.0, 3.5, 4.0, 5.0]


def main() -> dict:
    datasets = []
    ingest_seconds = 0.0
    n_items = 0
    for seed in SEEDS:
        items, truth = synthetic.generate(seed=seed)
        n_items += len(items)
        store = DuckDBStore()
        with tempfile.TemporaryDirectory() as tmp:
            path = synthetic.write_csv(items, Path(tmp) / "cur.csv")
            t0 = time.perf_counter()
            store.ingest_csv(path)
            ingest_seconds += time.perf_counter() - t0
        datasets.append((store.rows(), {(t.day.isoformat(), t.service) for t in truth}))
        store.close()

    results = []
    for th in THRESHOLDS:
        tp = fp = fn = 0
        for rows, truth in datasets:
            flagged = {(a["day"], a["service"]) for a in analytics.detect_anomalies(rows, threshold=th)}
            tp += len(flagged & truth)
            fp += len(flagged - truth)
            fn += len(truth - flagged)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        results.append(
            {"threshold": th, "tp": tp, "fp": fp, "fn": fn,
             "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}
        )

    report = {
        "data": "synthetic",
        "seeds": len(SEEDS),
        "days_per_seed": 120,
        "services": len(synthetic.SERVICES),
        "injected_per_seed": 10,
        "line_items_total": n_items,
        "mean_ingest_ms_per_report": round(ingest_seconds / len(SEEDS) * 1000, 1),
        "results": results,
    }
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
