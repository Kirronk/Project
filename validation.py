from __future__ import annotations

from datetime import date, datetime


DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y")
TIME_FORMATS = ("%H:%M", "%H.%M", "%H-%M", "%H%M")


def normalize_date(value: str | date, field_name: str = "Дата", required: bool = True) -> str:
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{field_name}: укажите дату.")
        return ""

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass

    raise ValueError(
        f"{field_name}: неверная дата '{text}'. Используйте формат YYYY-MM-DD или DD.MM.YYYY."
    )


def is_valid_optional_date(value: str) -> bool:
    try:
        normalize_date(value, required=False)
    except ValueError:
        return False
    return True


def normalize_time(value: str, field_name: str = "Время", required: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{field_name}: укажите время.")
        return ""

    if text.isdigit() and len(text) in {1, 2}:
        text = f"{int(text):02d}:00"

    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            pass

    raise ValueError(
        f"{field_name}: неверное время '{text}'. Используйте формат HH:MM, например 09:30."
    )


def is_valid_optional_time(value: str) -> bool:
    try:
        normalize_time(value, required=False)
    except ValueError:
        return False
    return True
