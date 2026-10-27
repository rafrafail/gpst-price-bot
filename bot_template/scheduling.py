"""Scheduling utilities for broadcast campaigns."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_relative_schedule(text: str, tz: str, now: datetime) -> str:
    """
    Parse relative schedule input.
    
    Supported formats:
    - "now" -> immediate
    - "today HH:MM" -> today at given time
    - "tomorrow HH:MM" -> tomorrow at given time
    - "DD.MM.YYYY HH:MM" -> exact datetime
    
    Returns UTC ISO format string.
    """
    text = text.strip().lower()
    zone = ZoneInfo(tz)
    
    if text == "now":
        return now.astimezone(timezone.utc).isoformat()
    
    if text.startswith("today "):
        time_part = text[6:].strip()
        return _parse_time_today(time_part, zone, now)
    
    if text.startswith("tomorrow "):
        time_part = text[9:].strip()
        return _parse_time_tomorrow(time_part, zone, now)
    
    # Try exact format
    return parse_exact_schedule(text, tz, now)


def _resolve_local_time(day, time_str: str, zone: ZoneInfo, now: datetime, allow_past: bool) -> str:
    """Resolve 'HH:MM' on a given local date to UTC ISO, rejecting DST gaps/ambiguity."""
    try:
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ValueError("Нужно время в формате ЧЧ:ММ (например, 14:30)") from None

    first = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
    second = first.replace(fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("Время попало на перевод часов. Выберите другое время.")
    utc = first.astimezone(timezone.utc)
    if utc.astimezone(zone).replace(tzinfo=None) != datetime(day.year, day.month, day.day, hour, minute):
        raise ValueError("Такого местного времени нет. Выберите другое время.")
    if not allow_past and utc <= now:
        raise ValueError("Это время уже прошло. Выберите будущее время или «Сейчас».")
    return utc.isoformat()


def _parse_time_today(time_str: str, zone: ZoneInfo, now: datetime) -> str:
    """Parse 'today HH:MM' format."""
    today = now.astimezone(zone).date()
    return _resolve_local_time(today, time_str, zone, now, allow_past=False)


def _parse_time_tomorrow(time_str: str, zone: ZoneInfo, now: datetime) -> str:
    """Parse 'tomorrow HH:MM' format."""
    tomorrow = now.astimezone(zone).date() + timedelta(days=1)
    return _resolve_local_time(tomorrow, time_str, zone, now, allow_past=True)


def parse_exact_schedule(text: str, tz: str, now: datetime) -> str:
    """Parse exact schedule in DD.MM.YYYY HH:MM format."""
    try:
        local = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        raise ValueError("Нужна дата в формате ДД.ММ.ГГГГ ЧЧ:ММ.") from None
    
    zone = ZoneInfo(tz)
    # Check for DST ambiguity
    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("Время попало на перевод часов. Выберите другое время.")
    utc = first.astimezone(timezone.utc)
    if utc.astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError("Такого местного времени нет. Выберите другое время.")
    if utc <= now:
        raise ValueError("Дата уже прошла. Укажите будущее время или выберите «Сейчас».")
    return utc.isoformat()


def format_schedule_utc(utc_iso: str, tz: str) -> str:
    """Format UTC ISO string for display in given timezone."""
    dt = datetime.fromisoformat(utc_iso).astimezone(ZoneInfo(tz))
    return dt.strftime("%d.%m.%Y %H:%M")


def get_schedule_options(tz: str, now: datetime) -> list[dict]:
    """
    Get quick schedule options for UI.
    
    Returns list of dicts with 'label', 'value', 'description'.
    """
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    
    options = [
        {
            "label": "Сейчас",
            "value": "now",
            "description": "Отправить немедленно"
        },
        {
            "label": f"Сегодня {local_now.strftime('%H:%M')}",
            "value": f"today {local_now.strftime('%H:%M')}",
            "description": "Сегодня в текущее время"
        },
    ]
    
    # Add specific time options for today
    for hour in [9, 12, 15, 18, 21]:
        if hour > local_now.hour or (hour == local_now.hour and local_now.minute < 30):
            options.append({
                "label": f"Сегодня {hour:02d}:00",
                "value": f"today {hour:02d}:00",
                "description": f"Сегодня в {hour:02d}:00"
            })
    
    # Tomorrow options
    for hour in [9, 12, 15, 18, 21]:
        options.append({
            "label": f"Завтра {hour:02d}:00",
            "value": f"tomorrow {hour:02d}:00",
            "description": f"Завтра в {hour:02d}:00"
        })
    
    # Custom option
    options.append({
        "label": "Другая дата и время",
        "value": "custom",
        "description": "Ввести дату вручную (ДД.ММ.ГГГГ ЧЧ:ММ)"
    })
    
    return options