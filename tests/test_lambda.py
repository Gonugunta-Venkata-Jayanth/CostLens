"""Lambda handlers exercised with in-memory fakes of the S3 and DynamoDB clients."""

import json
import shutil

from aws.handlers import DynamoStore, api_handler, ingest_handler


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def download_fileobj(self, bucket, key, fh):
        with open(self.objects[(bucket, key)], "rb") as src:
            shutil.copyfileobj(src, fh)


class FakeDynamo:
    def __init__(self, page_size=100):
        self.items = {}
        self.page_size = page_size
        self.fail_once = True

    def batch_write_item(self, RequestItems):
        (table, reqs), = RequestItems.items()
        if self.fail_once:  # simulate throttling: leave the last item unprocessed once
            self.fail_once = False
            for r in reqs[:-1]:
                self._put(r)
            return {"UnprocessedItems": {table: reqs[-1:]}}
        for r in reqs:
            self._put(r)
        return {"UnprocessedItems": {}}

    def _put(self, req):
        item = req["PutRequest"]["Item"]
        self.items[(item["service"]["S"], item["day"]["S"])] = item

    def scan(self, TableName, ExclusiveStartKey=None):
        keys = sorted(self.items)
        start = ExclusiveStartKey["i"] if ExclusiveStartKey else 0
        page = {"Items": [self.items[k] for k in keys[start:start + self.page_size]]}
        if start + self.page_size < len(keys):
            page["LastEvaluatedKey"] = {"i": start + self.page_size}
        return page


def s3_event(bucket, key):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def test_ingest_then_query(synthetic_data):
    s3 = FakeS3({("reports", "cur/2026 06.csv"): synthetic_data[0]})
    ddb = FakeDynamo()
    out = ingest_handler(s3_event("reports", "cur/2026+06.csv"), None, s3=s3, dynamodb=ddb)
    assert out["processed"][0]["service_days"] == 90 * 7
    assert len(DynamoStore(ddb).rows()) == 90 * 7  # paginated scan, retried batch

    resp = api_handler({"rawPath": "/api/summary"}, None, dynamodb=ddb)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["days"] == 90

    resp = api_handler({"rawPath": "/api/anomalies", "queryStringParameters": {"threshold": "4"}},
                       None, dynamodb=ddb)
    assert json.loads(resp["body"])["count"] >= 1

    for path in ("/api/daily", "/api/forecast", "/health"):
        assert api_handler({"rawPath": path}, None, dynamodb=ddb)["statusCode"] == 200
    assert api_handler({"rawPath": "/api/nope"}, None, dynamodb=ddb)["statusCode"] == 404


def test_api_empty_table():
    resp = api_handler({"rawPath": "/api/summary"}, None, dynamodb=FakeDynamo())
    assert resp["statusCode"] == 404
