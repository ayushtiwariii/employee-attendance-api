# HROne Employee Attendance & Analytics API

Backend-only FastAPI + PyMongo implementation of the HROne assignment.
Application logic lives in `app/main.py`.

## Requirements

-   Python 3.11+
-   MongoDB 6.0+
-   PowerShell on Windows

## Setup

Run from the repository root:

``` powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure `.env` if required:

``` dotenv
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

Never commit `.env` or credentials.

Start the API:

``` powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

-   Swagger: <http://127.0.0.1:8000/docs>
-   ReDoc: <http://127.0.0.1:8000/redoc>
-   Base URL: `http://127.0.0.1:8000`

`GET /health` returns `{"status":"ok"}` only when MongoDB answers a
ping; otherwise it returns `503`. Indexes are created at startup when
MongoDB is reachable. Restart the API if MongoDB was offline at startup.

## Sample data

The database is `attendance_db`, with `employees` and `attendance_logs`
collections. Review `sample_seed.py` and point `.env` to a disposable
development database before running:

``` powershell
python sample_seed.py
```

Do not seed/reset a database containing data you need to preserve.

Sample employees:

  Code        Name          Department    Shift
  ----------- ------------- ------------- --------------
  `EMP0001`   Asha Rao      Engineering   09:30--18:30
  `EMP0002`   Vikram Shah   Engineering   09:30--18:30
  `EMP0003`   Neha Iyer     Sales         09:30--18:30
  `EMP0004`   Rohit Das     Sales         09:30--18:30
  `EMP0005`   Meera Nair    Support       22:00--06:00
  `EMP0006`   Karan Bedi    Support       09:30--18:30

The sample attendance records are from July 2026; use `month=2026-07`
for monthly analytics.

## Common rules

-   Send JSON bodies with `Content-Type: application/json`.
-   `punched_at`, `punch_in`, and `punch_out` are integer Unix epoch
    **milliseconds**, not seconds or ISO date strings.
-   If `punched_at` is omitted for punch-in/out, the server uses the
    current time.
-   Shift calculations use `Asia/Kolkata` (IST); timestamps are
    stored/serialized consistently.
-   Valid statuses: `PRESENT`, `WFH`, `ON_DUTY`, `ABSENT`, `LEAVE`.
-   List endpoints support `page` (default `1`) and `page_size` (default
    `20`, maximum `100`).

Convert a timestamp in PowerShell:

``` powershell
[DateTimeOffset]::Parse("2026-07-07T09:35:00+05:30").ToUnixTimeMilliseconds()
```

## Endpoints

All examples use `http://127.0.0.1:8000`.

### 1. `GET /health` --- Health check

No body or parameters.

``` powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
```

Success (`200`):

``` json
{"status":"ok"}
```

Returns `503` if MongoDB is unavailable.

### 2. `POST /employees` --- Create employee

Request body:

``` json
{
  "emp_code": "EMP0007",
  "name": "Rahul Verma",
  "email": "rahul@example.com",
  "department": "Engineering",
  "shift_start": "09:30",
  "shift_end": "18:30",
  "joined_on": "2026-07-15"
}
```

Rules: `emp_code` must match `EMP` plus 4--6 digits; `name` is 1--100
characters; `email` must be valid-looking and at most 120 characters;
`department` is 1--50 characters; shift times use `HH:MM` and cannot be
identical; `joined_on` must be `YYYY-MM-DD`. `shift_start` and
`shift_end` default to `09:30` and `18:30`. `created_at` is
server-generated.

Success: `201 Created`, returning employee fields and `created_at` as
epoch milliseconds.

Errors: `409` if employee code already exists; `422` for validation;
`503` for database operation failure.

### 3. `GET /employees` --- List employees

Query parameters: `department` (optional exact match), `page` (default
`1`), `page_size` (default `20`, range 1--100).

Examples:

``` text
GET /employees
GET /employees?department=Engineering
GET /employees?page=1&page_size=3
```

Response shape:

``` json
{
  "items": [],
  "total": 6,
  "page": 1,
  "page_size": 20
}
```

`items` contains employees sorted by `emp_code`; `total` is the total
matching the filter.

### 4. `POST /attendance/punch-in` --- Punch in

Request body:

``` json
{
  "emp_code": "EMP0006",
  "punched_at": 1783397100000,
  "status": "PRESENT"
}
```

`emp_code` is required. `punched_at` is optional epoch milliseconds;
`status` defaults to `PRESENT` and can be `PRESENT`, `WFH`, or
`ON_DUTY`.

For real-time punch-in:

``` json
{"emp_code":"EMP0006","status":"PRESENT"}
```

Success: `201 Created`, returning the new attendance record. Initially
`punch_out` and `work_hours` are `null`.

Errors: `404` unknown employee; `409` already punched in for that shift
date; `422` invalid timestamp or before joining date; `503` database
failure. Overnight shifts are associated with their shift-start date.

### 5. `GET /attendance` --- List attendance

Optional query parameters:

-   `emp_code`
-   `date_from` and `date_to` (inclusive, `YYYY-MM-DD`)
-   `status` (`PRESENT`, `WFH`, `ON_DUTY`, `ABSENT`, `LEAVE`)
-   `page` (default `1`)
-   `page_size` (default `20`, maximum `100`)

Examples:

``` text
GET /attendance
GET /attendance?emp_code=EMP0001
GET /attendance?date_from=2026-07-06&date_to=2026-07-14
GET /attendance?emp_code=EMP0001&date_from=2026-07-06&date_to=2026-07-07
```

Response shape:

``` json
{
  "items": [],
  "total": 8,
  "page": 1,
  "page_size": 20
}
```

Attendance items include `emp_code`, `date`, `status`, epoch-ms
`punch_in`/`punch_out`, `work_hours`, `late_minutes`,
`overtime_minutes`, `half_day`, and `history`.

### 6. `POST /attendance/punch-out` --- Punch out

Request body:

``` json
{
  "emp_code": "EMP0006",
  "punched_at": 1783429200000
}
```

`punched_at` is optional; if omitted, current time is used. The API
closes the most recent open record for the employee and calculates work
hours, overtime, and half-day fields.

Success: `200 OK`, returning the updated attendance record.

Errors: `404` unknown employee/no punch-in; `409` already punched out or
concurrent conflict; `422` if punch-out is not after punch-in or is more
than 24 hours later; `503` database failure.

### 7. `PATCH /attendance/{emp_code}/{date}` --- Regularize attendance

Example URL:

``` text
PATCH /attendance/EMP0001/2026-07-07
```

Request body example:

``` json
{
  "punch_in": 1783396680000,
  "reason": "Corrected due to biometric glitch",
  "regularized_by": "hr.admin"
}
```

Optional attendance fields: `status`, `punch_in`, `punch_out`. Required
audit fields: `reason` (5--200 characters) and `regularized_by` (1--50
characters). Timestamp fields are epoch milliseconds or `null`.

To mark leave:

``` json
{
  "status": "LEAVE",
  "reason": "Approved leave entered by HR",
  "regularized_by": "hr.admin"
}
```

`ABSENT` and `LEAVE` cannot have non-null punch times. Presence statuses
require `punch_in`. `punch_in` must be on the requested date in IST;
punch-out must be after punch-in and within 24 hours. At least one
attendance field must actually change.

Success: `200 OK`; response includes updated record and a `history`
entry with operator, reason, and changed values.

Errors: `404` employee/record not found; `409` concurrent modification;
`422` invalid data or `Request does not change the record`.

### 8. `GET /analytics/employees/{emp_code}/monthly` --- Employee monthly analytics

Required query parameter: `month` in `YYYY-MM`.

``` text
GET /analytics/employees/EMP0001/monthly?month=2026-07
```

Response shape:

``` json
{
  "emp_code": "EMP0001",
  "month": "2026-07",
  "working_days": 22,
  "present_days": 2,
  "leave_days": 0,
  "late_count": 0,
  "total_late_minutes": 0,
  "total_overtime_minutes": 0,
  "attendance_pct": 9.09
}
```

Numbers are illustrative; actual results depend on database records.
Metrics include working days, present days (half-day counts as `0.5`),
leave days, late count/minutes, overtime minutes, and attendance
percentage.

Errors: `404` unknown employee; `422` missing/invalid month.

### 9. `GET /analytics/departments/summary` --- Department summary

Required: `month=YYYY-MM`. Optional: `department`.

``` text
GET /analytics/departments/summary?month=2026-07
GET /analytics/departments/summary?month=2026-07&department=Engineering
```

Response shape:

``` json
{
  "month": "2026-07",
  "items": [
    {
      "department": "Engineering",
      "headcount": 2,
      "present_days": 4,
      "avg_work_hours": 9.1,
      "late_count": 1,
      "total_late_minutes": 35,
      "leave_count": 0,
      "on_duty_count": 0
    }
  ]
}
```

Numbers are illustrative. `headcount` counts employees who joined by the
end of the selected month; other metrics derive from attendance records.

### 10. `GET /analytics/leaderboard/late` --- Late-arrival leaderboard

Required: `month=YYYY-MM`. Optional: `limit` (default `10`, range 1--50)
and `department`.

``` text
GET /analytics/leaderboard/late?month=2026-07
GET /analytics/leaderboard/late?month=2026-07&limit=5
GET /analytics/leaderboard/late?month=2026-07&limit=10&department=Sales
```

Response shape:

``` json
{
  "month": "2026-07",
  "items": [
    {
      "rank": 1,
      "emp_code": "EMP0003",
      "name": "Neha Iyer",
      "department": "Sales",
      "total_late_minutes": 35,
      "late_count": 1
    }
  ]
}
```

Example values are illustrative of response shape; actual ranking uses
the selected month's stored records.

### 11. `GET /analytics/departments/{department}/trend` --- Department trend

Required query parameters: `from=YYYY-MM-DD` and `to=YYYY-MM-DD`.
Inclusive range; maximum 92 days.

``` text
GET /analytics/departments/Engineering/trend?from=2026-07-01&to=2026-07-14
GET /analytics/departments/Sales/trend?from=2026-07-01&to=2026-07-14
```

Response shape:

``` json
{
  "department": "Engineering",
  "items": [
    {
      "date": "2026-07-06",
      "is_working_day": true,
      "headcount": 2,
      "present_count": 2,
      "late_count": 1,
      "attendance_rate": 1.0,
      "moving_avg_7d": 1.0
    }
  ]
}
```

The actual response contains date rows for the requested range,
including dates without attendance. `attendance_rate` is a ratio (`1.0`
means 100%). Half-day presence contributes `0.5`.

Errors: `404` unknown department; `422` invalid range or more than 92
days; `503` database/aggregation feature unavailable.

### 12. `GET /admin/explain/{endpoint}` --- Explain MongoDB query plan

Allowed `{endpoint}` values:

-   `attendance_list`
-   `employee_monthly`
-   `department_summary`
-   `late_leaderboard`
-   `department_trend`

The endpoint returns MongoDB explain details for a query pattern; it
does not call the business endpoint itself.

**Attendance list**

``` text
GET /admin/explain/attendance_list?emp_code=EMP0001&date_from=2026-07-06&date_to=2026-07-14&page=1&page_size=20
```

Supports `emp_code`, `date_from`, `date_to`, `status`, `page`, and
`page_size`.

**Employee monthly**

``` text
GET /admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07
```

Requires `emp_code` and `month`.

**Department summary**

``` text
GET /admin/explain/department_summary?month=2026-07&department=Engineering
```

Requires `month`; `department` is optional.

**Late leaderboard**

``` text
GET /admin/explain/late_leaderboard?month=2026-07&limit=10&department=Sales
```

Requires `month`; `department` is optional.

**Department trend**

``` text
GET /admin/explain/department_trend?department=Engineering&from=2026-07-01&to=2026-07-14
```

Requires `department`, `from`, and `to`; maximum 92 days.

Response shape:

``` json
{
  "endpoint": "employee_monthly",
  "collection": "attendance_logs",
  "explain": {
    "queryPlanner": {},
    "executionStats": {}
  }
}
```

The `explain` object is MongoDB-generated and varies by query/version.
Unknown endpoint values return `422`. MongoDB must be reachable.

## Suggested smoke-test order

Use the existing July 2026 records for read-only testing:

1.  `GET /health`
2.  `GET /employees`
3.  `GET /employees?department=Engineering`
4.  `GET /attendance?date_from=2026-07-06&date_to=2026-07-14`
5.  `GET /analytics/employees/EMP0001/monthly?month=2026-07`
6.  `GET /analytics/departments/summary?month=2026-07`
7.  `GET /analytics/leaderboard/late?month=2026-07`
8.  `GET /analytics/departments/Engineering/trend?from=2026-07-01&to=2026-07-14`
9.  `GET /admin/explain/attendance_list?date_from=2026-07-06&date_to=2026-07-14`

For write tests, use a disposable development database and a new
employee code. Punch-in, punch-out, and regularization modify data;
repeated operations can return conflicts.

## Error responses

  -----------------------------------------------------------------------
  Status                              Meaning
  ----------------------------------- -----------------------------------
  `200`                               Successful read, punch-out, or
                                      regularization

  `201`                               Employee or attendance punch-in
                                      created

  `404`                               Employee, attendance record, or
                                      department not found

  `409`                               Duplicate employee/punch-in,
                                      already punched out, or concurrent
                                      update

  `422`                               Invalid field, timestamp, date,
                                      status, or business-rule violation

  `503`                               MongoDB unavailable or database
                                      operation/feature unavailable
  -----------------------------------------------------------------------

Common `422` causes include epoch seconds instead of milliseconds,
invalid `YYYY-MM` month, unsupported status, extra request fields, or a
regularization request that changes no attendance field.

## Tests

Full suite (requires MongoDB 6+):

``` powershell
python -m pytest -q
```

Helper-only tests without MongoDB:

``` powershell
python -m pytest tests/test_helpers.py tests/test_contract_helpers.py -q
```

The full suite covers deterministic calculations, strict timestamp
validation, legacy-record regularization, concurrent punch-out, no-log
department trends, department headcount, leaderboard ties, and an
explain-plan check with 100,200 attendance documents. GitHub Actions
runs the full suite with MongoDB 6.0 on pushes to `main` and pull
requests.


