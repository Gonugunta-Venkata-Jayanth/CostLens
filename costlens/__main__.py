"""Command line entry point: ``python -m costlens <command>``."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from . import analytics, synthetic
from .pipeline import DuckDBStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costlens")
    sub = parser.add_subparsers(dest="cmd", required=True)

    seed = sub.add_parser("seed", help="load synthetic CUR data into the local store")
    seed.add_argument("--db", default=os.getenv("COSTLENS_DB", "data/costlens.duckdb"))
    seed.add_argument("--days", type=int, default=120)
    seed.add_argument("--if-empty", action="store_true")

    gen = sub.add_parser("generate", help="write a synthetic CUR CSV")
    gen.add_argument("output")
    gen.add_argument("--days", type=int, default=120)

    ing = sub.add_parser("ingest", help="ingest a CUR CSV into the local store")
    ing.add_argument("csv")
    ing.add_argument("--db", default=os.getenv("COSTLENS_DB", "data/costlens.duckdb"))

    rep = sub.add_parser("report", help="print summary, forecast and anomalies as JSON")
    rep.add_argument("--db", default=os.getenv("COSTLENS_DB", "data/costlens.duckdb"))

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        rows, _ = synthetic.generate(days=args.days)
        synthetic.write_csv(rows, args.output)
        print(f"wrote {len(rows)} line items to {args.output}")
        return 0

    store = DuckDBStore(args.db)
    try:
        if args.cmd == "seed":
            if args.if_empty and store.count():
                print("store already populated; skipping seed")
                return 0
            rows, _ = synthetic.generate(days=args.days)
            with tempfile.TemporaryDirectory() as tmp:
                path = synthetic.write_csv(rows, Path(tmp) / "cur.csv")
                n = store.ingest_csv(path)
            print(f"seeded {n} service-days from {len(rows)} synthetic line items")
        elif args.cmd == "ingest":
            print(f"ingested {store.ingest_csv(args.csv)} service-days")
        elif args.cmd == "report":
            rows = store.rows()
            out = {
                "summary": analytics.summary(rows),
                "forecast": analytics.forecast_month(rows),
                "anomalies": analytics.detect_anomalies(rows),
            }
            print(json.dumps(out, indent=2))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
