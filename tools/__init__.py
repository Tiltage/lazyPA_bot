"""Tool package — import modules to trigger registration, then export the registry."""

import tools.calendar  # noqa: F401 — registers calendar tools
import tools.gmail  # noqa: F401 — registers gmail tools

from tools.base import registry
from tools.calendar import get_events_raw, get_events_for_month, process_month_events
from tools.gmail import get_emails_raw

__all__ = [
    "registry",
    "get_events_raw",
    "get_events_for_month",
    "process_month_events",
    "get_emails_raw",
]
