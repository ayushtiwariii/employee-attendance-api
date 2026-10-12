from datetime import datetime, timezone

import pytest

from app.main import (
    EmployeeCreate,
    RegularizeRequest,
    build_department_trend_pipeline,
    calc_fields,
    dt_ms,
    epoch_ms,
    parse_range,
    qround,
    serialize_record,
    working_days,
)


def test_epoch_milliseconds_are_strict():
    assert epoch_ms(1_800_000_000_000) == 1_800_000_000_000
    for invalid in (True, 1_800_000_000, 1.5, "1800000000000", 99_999_999_999):
        with pytest.raises(ValueError):
            epoch_ms(invalid)


def test_rounding_is_half_up():
    assert qround(1.23445, 4) == 1.2345
    assert qround(1.23444, 4) == 1.2344
    assert qround(None, 4) is None


def test_working_days_respects_mid_month_joining():
    # July 2026 starts on Wednesday; joined on Wednesday 15 July.
    assert working_days("2026-07-15", "2026-07-01", "2026-07-31") == 13
    assert working_days("2026-08-01", "2026-07-01", "2026-07-31") == 0


def test_employee_input_rejects_extra_and_invalid_join_date():
    with pytest.raises(Exception):
        EmployeeCreate(
            emp_code="EMP1",
            name="Asha",
            email="asha@example.com",
            department="Engineering",
            joined_on="2026-07-01",
        )
    with pytest.raises(Exception):
        EmployeeCreate(
            emp_code="EMP0001",
            name="Asha",
            email="asha@example.com",
            department="Engineering",
            joined_on="2026-02-30",
            unexpected="no",
        )


def test_legacy_attendance_serialization_defaults_missing_fields():
    record = {
        "emp_code": "EMP0001",
        "date": "2026-07-06",
        "status": "PRESENT",
        "punch_in": datetime(2026, 7, 6, 4, tzinfo=timezone.utc),
        "punch_out": None,
        "history": [],
    }
    out = serialize_record(record)
    assert out["punch_in"] == dt_ms(record["punch_in"])
    assert out["punch_out"] is None
    assert out["history"] == []
    assert out["half_day"] is False


def test_non_presence_status_clears_derived_attendance_metrics():
    fields = calc_fields({"shift_start": "09:30", "shift_end": "18:30"}, {
        "status": "LEAVE", "punch_in": None, "punch_out": None,
    })
    assert fields == {
        "late_minutes": 0,
        "work_hours": None,
        "overtime_minutes": 0,
        "half_day": False,
    }


def test_trend_pipeline_generates_date_range_in_database():
    pipeline = build_department_trend_pipeline(
        "Engineering", "2026-07-01", "2026-07-03",
        __import__("datetime").date(2026, 7, 1),
        __import__("datetime").date(2026, 7, 3),
    )
    assert pipeline[0] == {"$match": {"department": "Engineering"}}
    assert any("$range" in stage.get("$addFields", {}).get("_day_offsets", {}) for stage in pipeline)
    assert any("$lookup" in stage and stage["$lookup"].get("from") == "attendance_logs" for stage in pipeline)
    assert any("$setWindowFields" in stage for stage in pipeline)
