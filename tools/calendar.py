"""Google Calendar tool functions."""
import datetime
import logging
from config import CALENDAR_DEFAULT_DAYS_AHEAD, CALENDAR_MAX_EVENTS, TIMEZONE_NAME
from tools.utils import get_service

logger = logging.getLogger(__name__)


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


def list_events(days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> str:
    """List upcoming Google Calendar events for the specified number of days ahead.

    Args:
        days_ahead: Number of days ahead to search for events. Defaults to 180.
    """
    events = _fetch_events(days_ahead)
    if not events:
        result = f"No events in the next {days_ahead} days."
        logger.debug("[TOOL list_events] days_ahead=%d => %s", days_ahead, result)
        return result
    lines = [
        f"• {e['start_display']}: {e['summary']}{' (recurring)' if e['is_recurring'] else ''} [id: {e['id']}]"
        for e in events
    ]
    result = "\n".join(lines)
    logger.debug("[TOOL list_events] days_ahead=%d => %d events:\n%s",
                 days_ahead, len(events), result)
    return result


def get_events_raw(days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> list[dict]:
    """Return structured event dicts for UI rendering (not for the LLM)."""
    return _fetch_events(days_ahead)


def create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    recurrence: str = "",
) -> str:
    """Create a Google Calendar event — single or recurring.

    recurrence: an RRULE string for recurring events, e.g. 'RRULE:FREQ=WEEKLY;BYDAY=MO'.
    Leave empty (default) for a single one-off event.
    """
    service = get_service("calendar", "v3")
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_datetime, "timeZone": TIMEZONE_NAME},
        "end": {"dateTime": end_datetime, "timeZone": TIMEZONE_NAME},
    }
    if recurrence:
        event["recurrence"] = [recurrence]
    created = service.events().insert(calendarId="primary", body=event).execute()
    result = f"Event '{summary}' created{' (recurring)' if recurrence else ''}. Link: {created.get('htmlLink')}"
    logger.debug("[TOOL create_event] summary=%r start=%r end=%r recurrence=%r => %s",
                 summary, start_datetime, end_datetime, recurrence, result)
    return result


def delete_event(event_id: str, scope: str = "single") -> str:
    """Delete a Google Calendar event.

    scope="single"  — delete only this occurrence (for a recurring event instance ID).
    scope="series"  — delete the entire recurring series (strips the instance suffix).
    For non-recurring events, scope is ignored and the event is always fully deleted.
    """
    service = get_service("calendar", "v3")
    if scope == "series":
        # Strip the "_YYYYMMDDTHHmmssZ" instance suffix to target the base recurring event.
        target_id = event_id.split("_")[0] if "_" in event_id else event_id
    else:
        target_id = event_id
    service.events().delete(calendarId="primary", eventId=target_id).execute()
    result = f"Event '{target_id}' deleted successfully (scope={scope})."
    logger.debug("[TOOL delete_event] event_id=%r scope=%r target_id=%r => %s",
                 event_id, scope, target_id, result)
    return result


def update_event(
    event_id: str,
    summary: str = None,
    start_datetime: str = None,
    end_datetime: str = None,
    description: str = None,
) -> str:
    """Update fields of an existing Google Calendar event. Only provided fields are changed."""
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
    updated = service.events().patch(calendarId="primary", eventId=event_id, body=patch).execute()
    result = f"Event updated: '{updated.get('summary', event_id)}'. Link: {updated.get('htmlLink')}"
    logger.debug("[TOOL update_event] event_id=%r patch=%r => %s", event_id, patch, result)
    return result
