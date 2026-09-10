"""Check-cadence definitions, kept free of any Qt import so the privileged
``set-interval`` helper can share them with the GUI.
"""

from __future__ import annotations

# Ordered: label -> systemd OnCalendar expression. "manual" is special-cased
# (the timer is disabled entirely).
INTERVALS: dict[str, str] = {
    "manual": "",
    "hourly": "hourly",
    "every 3 hours": "*-*-* 00/3:00:00",
    "daily": "daily",
    "weekly": "weekly",
}
DEFAULT_INTERVAL = "every 3 hours"


def is_valid(label: str) -> bool:
    return label in INTERVALS


def oncalendar_for(label: str) -> str:
    return INTERVALS.get(label, INTERVALS[DEFAULT_INTERVAL])
