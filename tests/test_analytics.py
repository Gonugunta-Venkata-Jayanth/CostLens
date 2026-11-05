from datetime import date, timedelta

import pytest

from costlens import analytics


def flat(days=40, cost=10.0, service="AmazonEC2", start=date(2026, 3, 1)):
    return [{"day": start + timedelta(days=i), "service": service, "cost": cost + (i % 3) * 0.1}
            for i in range(days)]


def test_flat_series_has_no_anomalies():
    assert analytics.detect_anomalies(flat()) == []


def test_single_spike_is_detected_and_excluded_from_baseline():
    rows = flat()
    rows[30]["cost"] = 40.0
    rows[31]["cost"] = 38.0
    found = analytics.detect_anomalies(rows)
    assert [a["day"] for a in found] == ["2026-03-31", "2026-04-01"]
    assert found[0]["expected"] == pytest.approx(10.1, abs=0.11)
    assert found[0]["severity"] == "high"


def test_small_absolute_change_is_ignored():
    rows = flat(cost=0.05)
    rows[30]["cost"] = 0.5  # 10x, but under the 1 USD minimum excess
    assert analytics.detect_anomalies(rows) == []


def test_needs_minimum_history():
    rows = flat(days=10)
    rows[9]["cost"] = 100.0
    assert analytics.detect_anomalies(rows) == []


def test_synthetic_recall(store, synthetic_data):
    truth = {(t.day.isoformat(), t.service) for t in synthetic_data[2]}
    found = {(a["day"], a["service"]) for a in analytics.detect_anomalies(store.rows())}
    assert len(found & truth) >= len(truth) - 1


def test_forecast_linear_trend_is_exact():
    start = date(2026, 4, 1)
    rows = [{"day": start + timedelta(days=i), "service": "S", "cost": 10.0 + i} for i in range(20)]
    f = analytics.forecast_month(rows)
    assert f["month"] == "2026-04"
    assert f["month_to_date"] == pytest.approx(sum(10.0 + i for i in range(20)))
    assert f["days_remaining"] == 10
    assert f["projected_total"] == pytest.approx(sum(10.0 + i for i in range(30)), rel=1e-6)
    assert f["daily_trend"] == pytest.approx(1.0)
    assert f["lower"] == pytest.approx(f["upper"], abs=1e-6)


def test_summary_period_change():
    start = date(2026, 1, 1)
    rows = [{"day": start + timedelta(days=i), "service": "A" if i % 2 else "B",
             "cost": 1.0 if i < 30 else 2.0} for i in range(60)]
    s = analytics.summary(rows)
    assert s["period_spend"] == 60.0
    assert s["previous_period_spend"] == 30.0
    assert s["change_pct"] == 100.0
    assert sum(x["share_pct"] for x in s["services"]) == pytest.approx(100.0)


def test_empty_input_raises():
    with pytest.raises(ValueError):
        analytics.summary([])
    with pytest.raises(ValueError):
        analytics.forecast_month([])


def test_daily_series_filter(store):
    d = analytics.daily_series(store.rows(), service="AmazonS3")
    assert list(d["series"]) == ["AmazonS3"]
    assert len(d["series"]["AmazonS3"]) == len(d["days"]) == 90
