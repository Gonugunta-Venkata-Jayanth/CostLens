from datetime import date

import pytest

from costlens import synthetic
from costlens.pipeline import DuckDBStore, IngestError, aggregate_csv


def test_generator_is_deterministic():
    a, ta = synthetic.generate(days=30, n_anomalies=2, seed=3)
    b, tb = synthetic.generate(days=30, n_anomalies=2, seed=3)
    assert a == b and ta == tb
    assert set(a[0]) == set(synthetic.CUR_COLUMNS)


def test_aggregate_matches_line_item_sum(synthetic_data):
    path, items, _ = synthetic_data
    daily = aggregate_csv(path)
    services = len(synthetic.SERVICES)
    assert len(daily) == 90 * services
    expected = sum(float(r["line_item_unblended_cost"]) for r in items)
    assert sum(r["cost"] for r in daily) == pytest.approx(expected, rel=1e-6)
    assert daily[0]["day"] == date(2026, 6, 15)


def test_reingest_is_idempotent(synthetic_data):
    store = DuckDBStore()
    store.ingest_csv(synthetic_data[0])
    first = store.count()
    store.ingest_csv(synthetic_data[0])
    assert store.count() == first


def test_missing_columns_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("date,amount\n2026-01-01,3.5\n")
    with pytest.raises(IngestError, match="missing required columns"):
        aggregate_csv(bad)


def test_file_backed_store_persists(tmp_path, synthetic_data):
    db = tmp_path / "nested" / "cost.duckdb"
    s = DuckDBStore(db)
    s.ingest_csv(synthetic_data[0])
    n = s.count()
    s.close()
    assert DuckDBStore(db).count() == n
