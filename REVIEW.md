# Starter Code Review

The starter application contained the health endpoint but did not implement the complete contract. The following issues were verified in the supplied starter and addressed in the replacement implementation.

| Location | Defect / reproducible impact | Fix | Test / verification |
|---|---|---|---|
| `GET /health` | Always reported success without verifying MongoDB availability. | Ping MongoDB and return 503 on missing/unavailable DB. | Health behavior is explicit; integration test requires MongoDB. |
| `POST /employees` | Duplicate check/insert without database-enforced uniqueness is unsafe under concurrent requests. | Unique `emp_code` index and duplicate-key -> 409. | Add concurrent integration test when MongoDB is available. |
| Employee serialization | Mongo `_id` could leak or server timestamps were not consistently converted to epoch milliseconds. | Strip `_id`; serialize `created_at` to integer epoch ms. | API schema inspection. |
| Employee listing | Pagination offset and filtered total were incorrect. | `skip((page-1)*page_size)` and count the same filter. | Filter/pagination integration test recommended. |
| Attendance listing | Loading all records before slicing does not scale; sorting did not enforce required tie-breaker. | Mongo cursor sort/skip/limit and `date DESC, emp_code ASC`. | Query plan via explain endpoint. |
| Punch-in | Check-then-insert is not safe under concurrent requests; unknown employees were not handled cleanly. | Unique compound index; catch duplicate key as 409; unknown employee -> 404. | Concurrency integration test requires MongoDB. |
| Timestamp handling | Epoch seconds, floats, strings, and sub-second instants can be mishandled. | Strict epoch-ms validation and whole-second truncation. | `test_truncate_to_seconds`. |
| Late calculation | Grace boundary and whole-minute calculation can be off by one. | Strictly more than 600 seconds; floor whole minutes from shift start. | `test_late_grace_boundary`. |
| Overnight shifts | Calendar date of the punch alone cannot identify the shift-start date. | Resolve shift start/end in Asia/Kolkata and associate early-morning punches with previous shift date. | `test_overnight_shift_date_and_overtime`. |
| Work hours | Python `round()` uses ties-to-even rather than required half-up rounding. | Decimal `ROUND_HALF_UP`. | `test_work_hours_half_up`. |
| Punch-out | A read followed by unconditional update permits duplicate simultaneous punch-outs. | Conditional update requires `punch_out: null`; only one update wins. | Requires concurrent MongoDB integration test. |
| Regularization | Replacing audit history or blind updates can lose concurrent edits. | Append history with `$push` and optimistic compare-and-update; conflicting edit gets 409. | Requires concurrent MongoDB integration test. |

The supplied starter was intentionally minimal; analytics endpoints and the explain endpoint were absent and have been implemented in `app/main.py`. MongoDB-dependent behavior still needs integration testing against the assignment's MongoDB version and hidden-scale data.
