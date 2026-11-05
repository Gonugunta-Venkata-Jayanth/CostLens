"""AWS Lambda handlers.

* ``ingest_handler``: triggered by S3 ``ObjectCreated`` for ``*.csv`` under ``cur/``.
  Downloads the report, aggregates it with DuckDB and writes daily totals to DynamoDB.
* ``api_handler``: API Gateway HTTP API (payload v2) routes that read DynamoDB and
  return the same JSON as the FastAPI service.

boto3 is provided by the Lambda runtime; clients are injectable for tests.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
from decimal import Decimal

from costlens import analytics
from costlens.pipeline import aggregate_csv

TABLE_NAME = os.getenv("COSTLENS_TABLE", "costlens-daily-cost")


class DynamoStore:
    """Daily aggregates in DynamoDB: pk = service, sk = ISO day, attribute cost."""

    def __init__(self, client, table: str = TABLE_NAME) -> None:
        self.client = client
        self.table = table

    def upsert(self, rows: list[dict]) -> int:
        items = [
            {
                "PutRequest": {
                    "Item": {
                        "service": {"S": r["service"]},
                        "day": {"S": str(r["day"])[:10]},
                        "cost": {"N": str(Decimal(str(round(r["cost"], 6))))},
                    }
                }
            }
            for r in rows
        ]
        for i in range(0, len(items), 25):  # BatchWriteItem limit
            request = {self.table: items[i : i + 25]}
            for _ in range(5):
                resp = self.client.batch_write_item(RequestItems=request)
                request = resp.get("UnprocessedItems") or {}
                if not request:
                    break
            else:
                raise RuntimeError("DynamoDB left items unprocessed after retries")
        return len(items)

    def rows(self) -> list[dict]:
        out: list[dict] = []
        kwargs: dict = {"TableName": self.table}
        while True:
            page = self.client.scan(**kwargs)
            for item in page.get("Items", []):
                out.append(
                    {
                        "service": item["service"]["S"],
                        "day": item["day"]["S"],
                        "cost": float(item["cost"]["N"]),
                    }
                )
            if "LastEvaluatedKey" not in page:
                return out
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _clients():  # pragma: no cover - exercised only on AWS
    import boto3

    return boto3.client("s3"), boto3.client("dynamodb")


def ingest_handler(event, context, s3=None, dynamodb=None):
    if s3 is None or dynamodb is None:
        s3, dynamodb = _clients()
    store = DynamoStore(dynamodb)
    processed = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
            s3.download_fileobj(bucket, key, tmp)
            tmp.flush()
            rows = aggregate_csv(tmp.name)
        processed.append({"key": key, "service_days": store.upsert(rows)})
    return {"processed": processed}


def _response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "access-control-allow-origin": "*"},
        "body": json.dumps(body),
    }


def api_handler(event, context, dynamodb=None):
    if dynamodb is None:
        _, dynamodb = _clients()
    path = event.get("rawPath", "/")
    params = event.get("queryStringParameters") or {}
    if path == "/health":
        return _response(200, {"status": "ok"})

    rows = DynamoStore(dynamodb).rows()
    if not rows:
        return _response(404, {"detail": "no cost data ingested yet"})
    try:
        if path == "/api/summary":
            return _response(200, analytics.summary(rows, period=int(params.get("period", 30))))
        if path == "/api/daily":
            return _response(200, analytics.daily_series(rows, service=params.get("service")))
        if path == "/api/anomalies":
            threshold = float(params.get("threshold", 4.0))
            found = analytics.detect_anomalies(rows, threshold=threshold)
            return _response(200, {"threshold": threshold, "count": len(found), "anomalies": found})
        if path == "/api/forecast":
            return _response(200, analytics.forecast_month(rows))
    except ValueError as exc:
        return _response(400, {"detail": str(exc)})
    return _response(404, {"detail": f"no route for {path}"})
