from datetime import datetime, timezone
from app.main import compute_work_hours, compute_late_minutes, compute_overtime, shift_bounds, trunc_ms


def emp(start="09:30", end="18:30"):
    return {"shift_start": start, "shift_end": end}


def ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_work_hours_half_up():
    assert compute_work_hours(0, 4 * 3600 * 1000 + 30 * 60 * 1000) == 4.5
    assert compute_work_hours(None, None) is None


def test_late_grace_boundary():
    # Shift starts 09:30 IST = 04:00 UTC.
    e = emp()
    assert compute_late_minutes(e, ms("2026-01-01T04:10:00")) == 0
    assert compute_late_minutes(e, ms("2026-01-01T04:10:01")) == 10
    assert compute_late_minutes(e, ms("2026-01-01T04:45:59")) == 45


def test_overnight_shift_date_and_overtime():
    e = emp("22:00", "06:00")
    punch = ms("2026-01-02T00:29:00")  # 06:00 IST, shift began previous date
    assert shift_bounds(e, punch)[2] == "2026-01-01"
    pi = ms("2026-01-01T16:30:00")  # 22:00 IST
    po = ms("2026-01-02T01:00:00")  # 06:15 IST
    assert compute_overtime(e, po, pi) == 30


def test_truncate_to_seconds():
    assert trunc_ms(1_800_000_123_999) == 1_800_000_123_000
