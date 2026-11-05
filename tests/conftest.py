import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from costlens import synthetic  # noqa: E402
from costlens.pipeline import DuckDBStore  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_data(tmp_path_factory):
    items, truth = synthetic.generate(days=90, n_anomalies=6, seed=11)
    path = synthetic.write_csv(items, tmp_path_factory.mktemp("cur") / "cur.csv")
    return path, items, truth


@pytest.fixture()
def store(synthetic_data):
    s = DuckDBStore()
    s.ingest_csv(synthetic_data[0])
    yield s
    s.close()
