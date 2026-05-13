from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from calendar import monthrange

from validation import normalize_date


OBSERVATION_CONSULTS = "Наблюдение и консультации"
WEEKLY_INDIVIDUAL = "Еженедельная индивидуальная ПТ"
BIWEEKLY_INDIVIDUAL = "Индивидуальная ПТ раз в 2 недели"
MONTHLY_INDIVIDUAL = "Индивидуальная поддерживающая ПТ"
OBSERVATION = "Наблюдение"
HYPNOTHERAPY = "Гипнотерапия"
GROUP_THERAPY = "Групповая ПТ"


@dataclass(frozen=True)
class PlannedSession:
    session_date: date
    slots: int
    title: str


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(normalize_date(value), "%Y-%m-%d").date()


def format_date(value: date) -> str:
    return value.isoformat()


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def next_weekday_on_or_after(value: date, weekdays: set[int]) -> date:
    current = value
    while current.weekday() not in weekdays:
        current += timedelta(days=1)
    return current


def generate_sessions(mode: str, start: str | date, count: int) -> list[PlannedSession]:
    if count <= 0:
        return []
    start_date = parse_date(start)

    if mode == OBSERVATION_CONSULTS:
        offsets = [0, 7, 14, 28]
        dates = [start_date + timedelta(days=days) for days in offsets]
        while len(dates) < count:
            dates.append(add_months(dates[-1], 1))
        return [PlannedSession(d, 1, mode) for d in dates[:count]]

    if mode == WEEKLY_INDIVIDUAL:
        return [
            PlannedSession(start_date + timedelta(weeks=i), 2, mode)
            for i in range(count)
        ]

    if mode == BIWEEKLY_INDIVIDUAL:
        return [
            PlannedSession(start_date + timedelta(weeks=2 * i), 2, mode)
            for i in range(count)
        ]

    if mode in {MONTHLY_INDIVIDUAL, OBSERVATION}:
        slots = 2 if mode == MONTHLY_INDIVIDUAL else 1
        return [PlannedSession(add_months(start_date, i), slots, mode) for i in range(count)]

    if mode == HYPNOTHERAPY:
        dates: list[date] = []
        current = next_weekday_on_or_after(start_date, {0, 2, 4})
        while len(dates) < count:
            if current.weekday() in {0, 2, 4}:
                dates.append(current)
            current += timedelta(days=1)
        return [PlannedSession(d, 1, mode) for d in dates]

    if mode == GROUP_THERAPY:
        return [
            PlannedSession(start_date + timedelta(weeks=i), 1, mode)
            for i in range(count)
        ]

    return [PlannedSession(start_date + timedelta(weeks=i), 1, mode) for i in range(count)]
