"""Cost analytics: robust anomaly detection, month-end forecast and spend summary.

All functions take daily rows of the form {"day": date | str, "service": str, "cost": float}
so they work identically on DuckDB (local) and DynamoDB (AWS) storage.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

import numpy as np

from .pipeline import as_date

MAD_SCALE = 1.4826  # makes MAD a consistent estimator of the standard deviation


def _by_service(rows: list[dict]) -> dict[str, dict[date, float]]:
    series: dict[str, dict[date, float]] = defaultdict(dict)
    for r in rows:
        day = as_date(r["day"])
        series[r["service"]][day] = series[r["service"]].get(day, 0.0) + float(r["cost"])
    return series


def total_by_day(rows: list[dict]) -> dict[date, float]:
    totals: dict[date, float] = defaultdict(float)
    for r in rows:
        totals[as_date(r["day"])] += float(r["cost"])
    return dict(sorted(totals.items()))


def detect_anomalies(
    rows: list[dict],
    threshold: float = 4.0,
    window: int = 28,
    min_history: int = 14,
    min_delta: float = 1.0,
) -> list[dict]:
    """Flag service-days whose cost is far above a rolling robust baseline.

    For each service and day, the baseline is the median of the previous ``window``
    days and the spread is the scaled median absolute deviation (MAD). A day is
    anomalous when its robust z-score is at least ``threshold`` and the excess over
    the baseline is at least ``min_delta`` USD. Earlier anomalies are excluded from
    later baselines so that one spike does not mask the next.
    """
    found: list[dict] = []
    for service, points in _by_service(rows).items():
        days = sorted(points)
        clean: list[float] = []
        for day in days:
            cost = points[day]
            history = clean[-window:]
            if len(history) >= min_history:
                base = median(history)
                mad = median(abs(x - base) for x in history) * MAD_SCALE
                spread = max(mad, 0.01 * base, 0.01)
                z = (cost - base) / spread
                if z >= threshold and cost - base >= min_delta:
                    found.append(
                        {
                            "day": day.isoformat(),
                            "service": service,
                            "cost": round(cost, 2),
                            "expected": round(base, 2),
                            "excess": round(cost - base, 2),
                            "z_score": round(z, 2),
                            "severity": "high" if z >= 2 * threshold else "medium",
                        }
                    )
                    continue  # keep the spike out of future baselines
            clean.append(cost)
    found.sort(key=lambda a: (a["day"], -a["excess"]))
    return found


def forecast_month(rows: list[dict], lookback: int = 30) -> dict:
    """Project the total for the latest calendar month with a linear trend.

    The trend is an ordinary least-squares fit on the last ``lookback`` days of
    total daily spend. The interval is +/- 1.96 * residual std * sqrt(days left).
    """
    totals = total_by_day(rows)
    if not totals:
        raise ValueError("no cost data")
    days = list(totals)
    last = days[-1]
    month_start = last.replace(day=1)
    days_in_month = calendar.monthrange(last.year, last.month)[1]
    month_end = last.replace(day=days_in_month)

    mtd = sum(v for d, v in totals.items() if d >= month_start)
    recent = [d for d in days if d > last - timedelta(days=lookback)]
    x = np.array([(d - recent[0]).days for d in recent], dtype=float)
    y = np.array([totals[d] for d in recent], dtype=float)
    if len(recent) >= 2:
        slope, intercept = np.polyfit(x, y, 1)
        resid_std = float(np.std(y - (slope * x + intercept), ddof=1)) if len(recent) > 2 else 0.0
    else:
        slope, intercept, resid_std = 0.0, float(y[0]), 0.0

    projection = []
    remaining = 0.0
    d = last + timedelta(days=1)
    while d <= month_end:
        xi = (d - recent[0]).days
        value = max(float(slope * xi + intercept), 0.0)
        projection.append({"day": d.isoformat(), "cost": round(value, 2)})
        remaining += value
        d += timedelta(days=1)

    left = len(projection)
    margin = 1.96 * resid_std * (left ** 0.5) if left else 0.0
    projected = mtd + remaining
    return {
        "month": month_start.strftime("%Y-%m"),
        "as_of": last.isoformat(),
        "month_to_date": round(mtd, 2),
        "projected_total": round(projected, 2),
        "lower": round(max(projected - margin, mtd), 2),
        "upper": round(projected + margin, 2),
        "daily_trend": round(float(slope), 4),
        "days_remaining": left,
        "projection": projection,
    }


def summary(rows: list[dict], period: int = 30) -> dict:
    """Headline numbers: totals, period-over-period change and top services."""
    totals = total_by_day(rows)
    if not totals:
        raise ValueError("no cost data")
    last = max(totals)
    cur_start = last - timedelta(days=period - 1)
    prev_start = cur_start - timedelta(days=period)
    current = sum(v for d, v in totals.items() if d >= cur_start)
    previous = sum(v for d, v in totals.items() if prev_start <= d < cur_start)

    per_service: dict[str, float] = defaultdict(float)
    for r in rows:
        if as_date(r["day"]) >= cur_start:
            per_service[r["service"]] += float(r["cost"])
    top = sorted(per_service.items(), key=lambda kv: kv[1], reverse=True)

    return {
        "first_day": min(totals).isoformat(),
        "last_day": last.isoformat(),
        "days": len(totals),
        "total_spend": round(sum(totals.values()), 2),
        "period_days": period,
        "period_spend": round(current, 2),
        "previous_period_spend": round(previous, 2),
        "change_pct": round((current - previous) / previous * 100, 2) if previous else None,
        "services": [
            {"service": s, "cost": round(c, 2), "share_pct": round(c / current * 100, 2)}
            for s, c in top
        ],
    }


def daily_series(rows: list[dict], service: str | None = None) -> dict:
    """Daily cost per service (optionally a single service) for charting."""
    series = _by_service(rows)
    if service:
        series = {k: v for k, v in series.items() if k == service}
    all_days = sorted({d for pts in series.values() for d in pts})
    return {
        "days": [d.isoformat() for d in all_days],
        "series": {
            s: [round(pts.get(d, 0.0), 2) for d in all_days] for s, pts in sorted(series.items())
        },
    }
