"""Ingestion pipeline: CUR CSV -> validated line items -> daily cost per service (DuckDB)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb

REQUIRED_COLUMNS = {
    "line_item_usage_start_date",
    "product_servicecode",
    "line_item_unblended_cost",
}


class IngestError(ValueError):
    """Raised when an uploaded report does not match the expected CUR schema."""


def _columns(con: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    rel = con.sql("SELECT * FROM read_csv_auto(?, header=true) LIMIT 0", params=[path])
    return {c.lower() for c in rel.columns}


def aggregate_csv(path: str | Path) -> list[dict]:
    """Aggregate a CUR CSV into daily totals per service without persisting anything."""
    con = duckdb.connect()
    try:
        return _aggregate(con, str(path))
    finally:
        con.close()


def _aggregate(con: duckdb.DuckDBPyConnection, path: str) -> list[dict]:
    missing = REQUIRED_COLUMNS - _columns(con, path)
    if missing:
        raise IngestError(f"missing required columns: {', '.join(sorted(missing))}")
    result = con.execute(
        """
        SELECT CAST(CAST(line_item_usage_start_date AS TIMESTAMP) AS DATE) AS day,
               product_servicecode AS service,
               ROUND(SUM(CAST(line_item_unblended_cost AS DOUBLE)), 6) AS cost
        FROM read_csv_auto(?, header=true, all_varchar=true)
        WHERE product_servicecode IS NOT NULL AND product_servicecode <> ''
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [path],
    ).fetchall()
    return [{"day": d, "service": s, "cost": float(c)} for d, s, c in result]


class DuckDBStore:
    """Local storage of daily aggregates in a DuckDB file (or in memory)."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(db_path))
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_cost (
                day DATE NOT NULL,
                service VARCHAR NOT NULL,
                cost DOUBLE NOT NULL,
                PRIMARY KEY (day, service)
            )
            """
        )

    def upsert(self, rows: Iterable[dict]) -> int:
        data = [(r["day"], r["service"], r["cost"]) for r in rows]
        if not data:
            return 0
        self.con.executemany(
            "INSERT OR REPLACE INTO daily_cost VALUES (?, ?, ?)",
            data,
        )
        return len(data)

    def ingest_csv(self, path: str | Path) -> int:
        return self.upsert(_aggregate(self.con, str(path)))

    def rows(self) -> list[dict]:
        out = self.con.execute(
            "SELECT day, service, cost FROM daily_cost ORDER BY day, service"
        ).fetchall()
        return [{"day": d, "service": s, "cost": c} for d, s, c in out]

    def count(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM daily_cost").fetchone()[0])

    def close(self) -> None:
        self.con.close()


def as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
