import json
from datetime import datetime, timedelta, timezone

import pytest

from collector.models import Meter, Rejected
from collector.registry import MeterRegistry
from collector.validator import Accepted, Reason, Validator, parse_topic

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
TOPIC = "meters/obolonskyi/M-000001/readings"


def make_validator() -> Validator:
    reg = MeterRegistry(meters=[
        Meter("M-000001", "obolonskyi", 1, "household"),
        Meter("M-000002", "pecherskyi", 3, "industrial"),
    ])
    return Validator(reg)


def msg(**over) -> str:
    base = {
        "meter_id": "M-000001",
        "ts": "2026-11-23T11:59:00Z",
        "energy_kwh": 1234.5,
        "power_w": 2100.0,
        "voltage_v": 229.8,
        "current_a": 9.9,
        "power_factor": 0.93,
        "frequency_hz": 50.01,
    }
    base.update(over)
    return json.dumps({k: v for k, v in base.items() if v is not ...})


def check(v, payload, topic=TOPIC):
    return v.validate(topic, payload.encode(), now=NOW)


def test_valid_message_is_accepted():
    res = check(make_validator(), msg())
    assert isinstance(res, Accepted)
    assert res.meter.district == "obolonskyi"
    assert res.reading.ts == datetime(2026, 11, 23, 11, 59, tzinfo=timezone.utc)


def test_unix_timestamp_is_accepted():
    res = check(make_validator(), msg(ts=int((NOW - timedelta(seconds=30)).timestamp())))
    assert isinstance(res, Accepted)


def test_shared_subscription_topic_is_parsed():
    assert parse_topic("meters/obolonskyi/M-1/readings") == ("obolonskyi", "M-1")
    assert parse_topic("$share/g/meters/obolonskyi/M-1/readings") == ("obolonskyi", "M-1")
    assert parse_topic("meters/obolonskyi/M-1") is None


@pytest.mark.parametrize(
    "payload, reason",
    [
        ("{not json", Reason.INVALID_JSON),
        ("[1, 2, 3]", Reason.INVALID_JSON),
        (msg(voltage_v=...), Reason.SCHEMA_ERROR),
        (msg(voltage_v="high"), Reason.SCHEMA_ERROR),
        (msg(ts="2026-11-23T11:59:00"), Reason.SCHEMA_ERROR),
        (msg(meter_id="M-000002"), Reason.TOPIC_MISMATCH),
        (msg(voltage_v=512.0), Reason.OUT_OF_RANGE),
        (msg(frequency_hz=0.0), Reason.OUT_OF_RANGE),
        (msg(power_factor=1.4), Reason.OUT_OF_RANGE),
        (msg(power_w=-5.0), Reason.OUT_OF_RANGE),
        (msg(power_w=5000.0), Reason.INCONSISTENT_POWER),
        (msg(ts="2026-11-23T14:00:00Z"), Reason.FUTURE_TIMESTAMP),
        (msg(ts="2026-10-01T00:00:00Z"), Reason.STALE_TIMESTAMP),
    ],
)
def test_rejections(payload, reason):
    res = check(make_validator(), payload)
    assert isinstance(res, Rejected)
    assert res.reason == reason, res.detail
    assert res.raw_payload == payload


def test_nan_is_rejected():
    payload = msg().replace("229.8", "NaN")
    res = check(make_validator(), payload)
    assert isinstance(res, Rejected) and res.reason == Reason.OUT_OF_RANGE


def test_unknown_meter():
    payload = msg(meter_id="M-777777")
    res = check(make_validator(), payload, topic="meters/obolonskyi/M-777777/readings")
    assert res.reason == Reason.UNKNOWN_METER


def test_district_mismatch():
    res = check(make_validator(), msg(), topic="meters/podilskyi/M-000001/readings")
    assert res.reason == Reason.DISTRICT_MISMATCH


def test_three_phase_meter_allows_higher_power():
    payload = msg(meter_id="M-000002", power_w=6000.0)
    res = check(make_validator(), payload, topic="meters/pecherskyi/M-000002/readings")
    assert isinstance(res, Accepted)


def test_energy_must_not_decrease():
    v = make_validator()
    assert isinstance(check(v, msg(ts="2026-11-23T11:58:00Z", energy_kwh=100.0)), Accepted)
    assert isinstance(check(v, msg(ts="2026-11-23T11:58:30Z", energy_kwh=100.0)), Accepted)
    res = check(v, msg(ts="2026-11-23T11:59:00Z", energy_kwh=99.0))
    assert res.reason == Reason.ENERGY_DECREASED


def test_rounding_noise_in_energy_is_tolerated():
    v = make_validator()
    check(v, msg(ts="2026-11-23T11:58:00Z", energy_kwh=100.0))
    assert isinstance(check(v, msg(ts="2026-11-23T11:59:00Z", energy_kwh=99.9995)), Accepted)


def test_duplicate_and_out_of_order_are_rejected():
    v = make_validator()
    assert isinstance(check(v, msg()), Accepted)
    assert check(v, msg()).reason == Reason.OUT_OF_ORDER
    assert check(v, msg(ts="2026-11-23T11:50:00Z")).reason == Reason.OUT_OF_ORDER


def test_rejected_message_does_not_change_state():
    v = make_validator()
    check(v, msg(ts="2026-11-23T11:58:00Z", energy_kwh=100.0))
    check(v, msg(ts="2026-11-23T11:58:30Z", energy_kwh=50.0))  # відкинуто
    assert isinstance(check(v, msg(ts="2026-11-23T11:59:00Z", energy_kwh=100.5)), Accepted)


def test_seeded_state_is_used_after_restart():
    v = make_validator()
    v.seed_state("M-000001", datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc), 2000.0)
    assert check(v, msg(energy_kwh=1999.0)).reason == Reason.ENERGY_DECREASED
