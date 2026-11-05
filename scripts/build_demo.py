"""Build the static dashboard into dist/ with a precomputed snapshot of synthetic data.

The snapshot is produced by the same pipeline and analytics code the API uses, so the
static demo shows exactly what the API would return for the synthetic dataset.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from costlens import analytics, synthetic  # noqa: E402
from costlens.pipeline import DuckDBStore  # noqa: E402


def main(out_dir: str = "dist") -> Path:
    out = ROOT / out_dir
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "frontend", out)

    line_items, _ = synthetic.generate()
    store = DuckDBStore()
    with tempfile.TemporaryDirectory() as tmp:
        store.ingest_csv(synthetic.write_csv(line_items, Path(tmp) / "cur.csv"))
    rows = store.rows()

    snapshot = {
        "source": "synthetic",
        "line_items": len(line_items),
        "summary": analytics.summary(rows),
        "daily": analytics.daily_series(rows),
        "forecast": analytics.forecast_month(rows),
        # Lowest threshold the UI slider allows; the UI filters by z-score client-side.
        "anomalies": analytics.detect_anomalies(rows, threshold=2.5),
    }
    (out / "snapshot.json").write_text(json.dumps(snapshot, separators=(",", ":")))
    (out / "config.js").write_text('window.COSTLENS_CONFIG = { mode: "snapshot" };\n')
    print(f"demo built in {out} ({len(rows)} service-days)")
    return out


if __name__ == "__main__":
    main(*sys.argv[1:])
