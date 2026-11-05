import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from costlens.pipeline import DuckDBStore


@pytest.fixture()
def client(store):
    return TestClient(create_app(store))


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["service_days"] > 0


def test_summary_and_forecast(client):
    s = client.get("/api/summary").json()
    assert s["days"] == 90 and s["services"]
    f = client.get("/api/forecast").json()
    assert f["projected_total"] >= f["month_to_date"]


def test_anomalies_threshold_monotonic(client):
    loose = client.get("/api/anomalies", params={"threshold": 3}).json()["count"]
    strict = client.get("/api/anomalies", params={"threshold": 8}).json()["count"]
    assert loose >= strict


def test_invalid_query_rejected(client):
    assert client.get("/api/anomalies", params={"threshold": 0}).status_code == 422


def test_empty_store_returns_404():
    c = TestClient(create_app(DuckDBStore()))
    assert c.get("/api/summary").status_code == 404


def test_upload_flow(synthetic_data):
    c = TestClient(create_app(DuckDBStore()))
    with open(synthetic_data[0], "rb") as fh:
        r = c.post("/api/ingest", files={"file": ("cur.csv", fh, "text/csv")})
    assert r.status_code == 201
    assert r.json()["total_service_days"] == 90 * 7


def test_upload_rejects_bad_schema(tmp_path):
    c = TestClient(create_app(DuckDBStore()))
    r = c.post("/api/ingest", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 422
    r = c.post("/api/ingest", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "CostLens" in r.text
