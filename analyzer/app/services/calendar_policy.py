from datetime import UTC, date, datetime, timedelta

UTC_CUTOFF_HOUR = 18


def resolve_work_date(received_at: datetime) -> date | None:
    value = received_at.astimezone(UTC)
    weekday = value.weekday()
    after_cutoff = value.hour >= UTC_CUTOFF_HOUR
    if weekday <= 3:
        return value.date() + timedelta(days=1 if after_cutoff else 0)
    if weekday == 4:
        return None if after_cutoff else value.date()
    if weekday == 5:
        return None
    return value.date() + timedelta(days=1) if after_cutoff else None
