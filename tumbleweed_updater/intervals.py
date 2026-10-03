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

# What Settings shows for each of them. The keys above are also the stored
# preference and the argument helper/set-interval checks, so the wording lives
# here instead of replacing them.
LABELS: dict[str, str] = {
    "manual": "Only when I press Check now",
    "hourly": "Every hour",
    "every 3 hours": "Every 3 hours",
    "daily": "Once a day",
    "weekly": "Once a week",
}

# What helper/set-interval says when systemd will not take a change. Shared so
# the window can tell these sentences, which are written for the user, from
# anything else a failed helper prints.
NOT_ACCEPTED = "The system did not accept the new schedule."
NOT_SWITCHED_OFF = "The system did not switch off the scheduled check."
NOT_STARTED = "The system did not start the scheduled check on the new schedule."
FAILURES = (NOT_ACCEPTED, NOT_SWITCHED_OFF, NOT_STARTED)


def is_valid(label: str) -> bool:
    return label in INTERVALS


def oncalendar_for(label: str) -> str:
    return INTERVALS.get(label, INTERVALS[DEFAULT_INTERVAL])
