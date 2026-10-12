from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as api_module
from app.main import app


def epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


@pytest.fixture
def api():
    with TestClient(app) as test_client:
        database = api_module.db
        database.employees.delete_many({})
        database.attendance_logs.delete_many({})
        yield test_client
        database.attendance_logs.delete_many({})
        database.employees.delete_many({})


def create_employee(client, **overrides):
    body = {
        "emp_code": "EMP0001",
        "name": "Asha Rao",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-01",
    }
    body.update(overrides)
    response = client.post("/employees", json=body)
    assert response.status_code == 201, response.text
    return body


def test_employee_duplicate_code_is_conflict(api):
    create_employee(api)
    duplicate = api.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Another Person",
        "email": "another@example.com",
        "department": "Engineering",
        "joined_on": "2026-07-01",
    })
    assert duplicate.status_code == 409


def test_concurrent_punch_out_has_exactly_one_winner(api):
    create_employee(api)
    punch_in = api.post("/attendance/punch-in", json={
        "emp_code": "EMP0001",
        "punched_at": epoch_ms("2026-07-06T04:00:00Z"),
    })
    assert punch_in.status_code == 201, punch_in.text

    payload = {"emp_code": "EMP0001", "punched_at": epoch_ms("2026-07-06T13:00:00Z")}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: api.post("/attendance/punch-out", json=payload), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 409]
    record = api_module.db.attendance_logs.find_one({"emp_code": "EMP0001", "date": "2026-07-06"})
    assert record["punch_out"] is not None
    assert record["work_hours"] == 9.0


def test_regularize_legacy_record_without_history(api):
    create_employee(api)
    api_module.db.attendance_logs.insert_one({
        "emp_code": "EMP0001",
        "date": "2026-07-06",
        "status": "PRESENT",
        "punch_in": datetime(2026, 7, 6, 4, 35, tzinfo=timezone.utc),
        "punch_out": datetime(2026, 7, 6, 13, 0, tzinfo=timezone.utc),
        "work_hours": 8.42,
        "late_minutes": 35,
        "overtime_minutes": 0,
    })
    response = api.patch("/attendance/EMP0001/2026-07-06", json={
        "punch_in": epoch_ms("2026-07-06T03:58:00Z"),
        "reason": "Corrected biometric time",
        "regularized_by": "hr.admin",
    })
    assert response.status_code == 200, response.text
    assert response.json()["late_minutes"] == 0
    assert len(response.json()["history"]) == 1
    assert response.json()["history"][0]["changes"]["punch_in"]["from"] == epoch_ms("2026-07-06T04:35:00Z")


def test_trend_returns_every_date_when_department_has_no_logs(api):
    create_employee(api)
    response = api.get("/analytics/departments/Engineering/trend", params={
        "from": "2026-07-04",
        "to": "2026-07-06",
    })
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert [row["date"] for row in rows] == ["2026-07-04", "2026-07-05", "2026-07-06"]
    assert [row["present_count"] for row in rows] == [0, 0, 0]
    assert rows[0]["attendance_rate"] is None
    assert rows[1]["attendance_rate"] is None
    assert rows[2]["attendance_rate"] == 0.0
    assert rows[2]["moving_avg_7d"] == 0.0


def test_department_summary_counts_employee_with_no_logs(api):
    create_employee(api)
    response = api.get("/analytics/departments/summary", params={"month": "2026-07"})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [{
        "department": "Engineering",
        "headcount": 1,
        "present_days": 0,
        "avg_work_hours": None,
        "late_count": 0,
        "total_late_minutes": 0,
        "leave_count": 0,
        "on_duty_count": 0,
    }]
