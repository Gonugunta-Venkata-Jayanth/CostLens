"""Deterministic generator for synthetic AWS Cost and Usage Report (CUR) line items.

The generator produces CUR 2.0 style columns with a configurable number of
injected cost spikes. The injected spikes are returned as ground truth so the
anomaly detector can be evaluated against known labels.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

CUR_COLUMNS = [
    "line_item_usage_start_date",
    "line_item_usage_account_id",
    "product_servicecode",
    "product_region_code",
    "line_item_usage_type",
    "line_item_unblended_cost",
]

# service code -> (baseline daily USD, daily growth rate, usage types)
SERVICES: dict[str, tuple[float, float, list[str]]] = {
    "AmazonEC2": (42.0, 0.0020, ["BoxUsage:t3.medium", "EBS:VolumeUsage.gp3", "DataTransfer-Out-Bytes"]),
    "AmazonRDS": (18.0, 0.0010, ["InstanceUsage:db.t4g.medium", "RDS:GP3-Storage"]),
    "AmazonS3": (6.5, 0.0030, ["TimedStorage-ByteHrs", "Requests-Tier1", "DataTransfer-Out-Bytes"]),
    "AWSLambda": (3.2, 0.0040, ["Request", "Lambda-GB-Second"]),
    "AmazonDynamoDB": (2.4, 0.0025, ["ReadRequestUnits", "WriteRequestUnits", "TimedStorage-ByteHrs"]),
    "AmazonCloudWatch": (4.1, 0.0015, ["CW:MetricMonitorUsage", "DataProcessing-Bytes"]),
    "AmazonApiGateway": (1.6, 0.0035, ["ApiGatewayHttpRequest"]),
}

ACCOUNTS = ["111122223333", "444455556666"]
REGIONS = ["ap-south-1", "us-east-1"]


@dataclass(frozen=True)
class InjectedAnomaly:
    day: date
    service: str
    multiplier: float


def generate(
    start: date = date(2026, 6, 15),
    days: int = 120,
    n_anomalies: int = 10,
    seed: int = 7,
) -> tuple[list[dict[str, str]], list[InjectedAnomaly]]:
    """Return (line_items, injected_anomalies)."""
    rng = np.random.default_rng(seed)
    services = list(SERVICES)

    # Spikes are placed after a 21 day warm-up so a baseline exists.
    candidates = [(d, s) for d in range(21, days) for s in services]
    picks = rng.choice(len(candidates), size=n_anomalies, replace=False)
    injected = {
        candidates[i]: float(rng.uniform(1.3, 3.0)) for i in sorted(int(p) for p in picks)
    }

    rows: list[dict[str, str]] = []
    for d in range(days):
        day = start + timedelta(days=d)
        weekday_factor = 0.92 if day.weekday() >= 5 else 1.03
        for service in services:
            base, growth, usage_types = SERVICES[service]
            cost = base * (1 + growth) ** d * weekday_factor * rng.normal(1.0, 0.05)
            cost *= injected.get((d, service), 1.0)
            # Split the service-day total into several line items.
            shares = rng.dirichlet(np.ones(len(usage_types) * len(REGIONS)))
            k = 0
            for region in REGIONS:
                for usage in usage_types:
                    rows.append(
                        {
                            "line_item_usage_start_date": f"{day.isoformat()}T00:00:00Z",
                            "line_item_usage_account_id": ACCOUNTS[k % len(ACCOUNTS)],
                            "product_servicecode": service,
                            "product_region_code": region,
                            "line_item_usage_type": usage,
                            "line_item_unblended_cost": f"{max(cost, 0.0) * shares[k]:.6f}",
                        }
                    )
                    k += 1

    truth = [
        InjectedAnomaly(start + timedelta(days=d), s, m) for (d, s), m in sorted(injected.items())
    ]
    return rows, truth


def write_csv(rows: list[dict[str, str]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CUR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
