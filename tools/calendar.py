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
        })
    return events


def list_events(days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> str:
    """List upcoming Google Calendar events for the specified number of days ahead."""
    events = _fetch_events(days_ahead)
    if not events:
        result = f"No events in the next {days_ahead} days."
        logger.debug("[TOOL list_events] days_ahead=%d => %s", days_ahead, result)
        return result
    lines = [f"• {e['start_display']}: {e['summary']}" for e in events]
    result = "\n".join(lines)
    logger.debug("[TOOL list_events] days_ahead=%d => %d events:\n%s",
                 days_ahead, len(events), result)
    return result


def get_events_raw(days_ahead: int = CALENDAR_DEFAULT_DAYS_AHEAD) -> list[dict]:
    """Return structured event dicts for UI rendering (not for the LLM)."""
    return _fetch_events(days_ahead)


def create_event(summary: str, start_datetime: str, end_datetime: str, description: str = "") -> str:
    """Create a new Google Calendar event. start_datetime and end_datetime must be ISO 8601 (e.g. 2026-03-20T14:00:00+08:00)."""
    service = get_service("calendar", "v3")
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_datetime, "timeZone": TIMEZONE_NAME},
        "end": {"dateTime": end_datetime, "timeZone": TIMEZONE_NAME},
    }
    created = service.events().insert(calendarId="primary", body=event).execute()
    result = f"Event '{summary}' created. Link: {created.get('htmlLink')}"
    logger.debug("[TOOL create_event] summary=%r start=%r end=%r => %s",
                 summary, start_datetime, end_datetime, result)
    return result
