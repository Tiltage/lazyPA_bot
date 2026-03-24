"""Google Calendar tool classes."""

import datetime
import logging

from config import CALENDAR_DEFAULT_DAYS_AHEAD, CALENDAR_MAX_EVENTS, TIMEZONE_NAME
from tools.base import Tool, registry
from tools.utils import get_service

logger = logging.getLogger(__name__)


# ── Private helpers (shared by tool classes) ─────────────────────────────────


def _format_start(start_dict: dict) -> tuple[str, str]:
    """Return (display_string, iso_string) from a Calendar start/end dict."""
    raw = start_dict.get("dateTime") or start_dict.get("date", "")
    if not raw:
        return "Unknown", ""
    try:
        if "T" in raw:
            dt = datetime.datetime.fromisoformat(raw)
            return dt.strftime("%a %b %d %H:%M"), raw
        else:
            d = datetime.date.fromisoformat(raw)
            return d.strftime("%a %b %d (all day)"), raw
    except ValueError:
        return raw, raw


def _fetch_events(days_ahead: int) -> list[dict]:
    """Fetch raw events from Google Calendar; returns list of structured dicts."""
    service = get_service("calendar", "v3")
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    end = now + datetime.timedelta(days=days_ahead)
    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=CALENDAR_MAX_EVENTS,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    items = result.get("items", [])
    events = []
    for e in items:
        start_display, start_iso = _format_start(e.get("start", {}))
        _, end_iso = _format_start(e.get("end", {}))
        events.append({
            "id": e.get("id", ""),
            "summary": e.get("summary", "(no title)"),
            "start_display": start_display,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "description": e.get("description", ""),
            "is_recurring": "recurringEventId" in e,
        })
    return events


def get_events_raw(days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> list[dict]:
    """Return structured event dicts for UI rendering (not for the LLM)."""
    return _fetch_events(days_ahead)


# ── Tool classes ─────────────────────────────────────────────────────────────


class ListEvents(Tool):
    name = "list_events"
    description = "List upcoming Google Calendar events for a given number of days ahead. Returns event summaries, times, IDs, and whether each is recurring."
    parameters = {
        "days_ahead": {
            "type": "integer",
            "description": f"Number of days ahead to search (default {CALENDAR_DEFAULT_DAYS_AHEAD}).",
        },
    }

    def execute(self, days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> str:
        events = _fetch_events(days_ahead)
        if not events:
            return f"No events in the next {days_ahead} days."
        lines = [
            f"• {e['start_display']}: {e['summary']}"
            f"{' (recurring)' if e['is_recurring'] else ''}"
            f" [id: {e['id']}]"
            for e in events
        ]
        return "\n".join(lines)


class CreateEvent(Tool):
    name = "create_event"
    description = (
        "Create a Google Calendar event. For recurring events, provide an RRULE string "
        "(e.g. 'RRULE:FREQ=WEEKLY;BYDAY=MO'). Omit recurrence for single events."
    )
    parameters = {
        "summary": {
            "type": "string",
            "description": "Event title.",
        },
        "start_datetime": {
            "type": "string",
            "description": "Start time in ISO 8601 format (e.g. '2025-03-25T14:00:00').",
        },
        "end_datetime": {
            "type": "string",
            "description": "End time in ISO 8601 format (e.g. '2025-03-25T15:00:00').",
        },
        "description": {
            "type": "string",
            "description": "Optional event description.",
        },
        "recurrence": {
            "type": "string",
            "description": "RRULE string for recurring events (e.g. 'RRULE:FREQ=WEEKLY;BYDAY=MO'). Leave empty for single events.",
        },
    }
    required = ["summary", "start_datetime", "end_datetime"]

    def execute(
        self,
        summary: str,
        start_datetime: str,
        end_datetime: str,
        description: str = "",
        recurrence: str = "",
    ) -> str:
        service = get_service("calendar", "v3")
        if recurrence and not recurrence.upper().startswith("RRULE:"):
            recurrence = f"RRULE:{recurrence}"
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_datetime, "timeZone": TIMEZONE_NAME},
            "end": {"dateTime": end_datetime, "timeZone": TIMEZONE_NAME},
        }
        if recurrence:
            event["recurrence"] = [recurrence]
        try:
            created = service.events().insert(calendarId="primary", body=event).execute()
        except Exception as e:
            return f"Failed to create event: {e}"
        return (
            f"Event '{summary}' created"
            f"{' (recurring)' if recurrence else ''}. "
            f"Link: {created.get('htmlLink')}"
        )


class DeleteEvent(Tool):
    name = "delete_event"
    description = (
        "Delete a Google Calendar event. "
        "Use scope='single' for one occurrence, scope='series' for the entire recurring series."
    )
    parameters = {
        "event_id": {
            "type": "string",
            "description": "The event ID from list_events.",
        },
        "scope": {
            "type": "string",
            "description": "'single' to delete one occurrence, 'series' to delete the entire recurring series.",
            "default": "single",
        },
    }
    required = ["event_id"]

    def execute(self, event_id: str, scope: str = "single") -> str:
        service = get_service("calendar", "v3")
        if scope == "series":
            target_id = event_id.split("_")[0] if "_" in event_id else event_id
        else:
            target_id = event_id
        try:
            service.events().delete(calendarId="primary", eventId=target_id).execute()
        except Exception as e:
            return f"Failed to delete event: {e}"
        return f"Event '{target_id}' deleted successfully (scope={scope})."


class UpdateEvent(Tool):
    name = "update_event"
    description = "Update fields of an existing Google Calendar event. Only provided fields are changed."
    parameters = {
        "event_id": {
            "type": "string",
            "description": "The event ID from list_events.",
        },
        "summary": {
            "type": "string",
            "description": "New event title.",
        },
        "start_datetime": {
            "type": "string",
            "description": "New start time in ISO 8601 format.",
        },
        "end_datetime": {
            "type": "string",
            "description": "New end time in ISO 8601 format.",
        },
        "description": {
            "type": "string",
            "description": "New event description.",
        },
    }
    required = ["event_id"]

    def execute(
        self,
        event_id: str,
        summary: str = None,
        start_datetime: str = None,
        end_datetime: str = None,
        description: str = None,
    ) -> str:
        service = get_service("calendar", "v3")
        patch = {}
        if summary is not None:
            patch["summary"] = summary
        if description is not None:
            patch["description"] = description
        if start_datetime is not None:
            patch["start"] = {"dateTime": start_datetime, "timeZone": TIMEZONE_NAME}
        if end_datetime is not None:
            patch["end"] = {"dateTime": end_datetime, "timeZone": TIMEZONE_NAME}
        if not patch:
            return "No fields provided to update."
        try:
            updated = service.events().patch(
                calendarId="primary", eventId=event_id, body=patch
            ).execute()
        except Exception as e:
            return f"Failed to update event: {e}"
        return (
            f"Event updated: '{updated.get('summary', event_id)}'. "
            f"Link: {updated.get('htmlLink')}"
        )


# ── Register all calendar tools ──────────────────────────────────────────────

registry.register(ListEvents())
registry.register(CreateEvent())
registry.register(DeleteEvent())
registry.register(UpdateEvent())
