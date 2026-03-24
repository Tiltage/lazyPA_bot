"""
Telegram UI helpers — message formatting, menus, and inline keyboard builders.
All presentation logic lives here to keep handlers clean.

Telegram rendering notes:
  - parse_mode="HTML" is used throughout; always html.escape() user-supplied data.
  - Telegram does NOT render <table> tags — <pre> ASCII tables are used instead.
  - InlineKeyboardButton callback_data has a hard 64-byte limit.
  - Event/email objects are stored in user_data so callback handlers can look
    them up by index without cramming details into callback_data.
"""
import html
from html.parser import HTMLParser

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── LLM output sanitiser ──────────────────────────────────────────────────────

_TELEGRAM_ALLOWED_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 'ins',
    's', 'strike', 'del', 'code', 'pre', 'tg-spoiler',
}


class _TelegramHTMLSanitizer(HTMLParser):
    """Keep only Telegram-safe HTML tags; escape everything else as visible text."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._out: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in _TELEGRAM_ALLOWED_TAGS:
            self._out.append(f'<{tag}>')
        elif tag == 'a':
            href = html.escape(dict(attrs).get('href', ''))
            self._out.append(f'<a href="{href}">')
        else:
            self._out.append(html.escape(f'<{tag}>'))

    def handle_endtag(self, tag: str):
        if tag in _TELEGRAM_ALLOWED_TAGS or tag == 'a':
            self._out.append(f'</{tag}>')
        else:
            self._out.append(html.escape(f'</{tag}>'))

    def handle_data(self, data: str):
        self._out.append(html.escape(data))

    def handle_entityref(self, name: str):
        self._out.append(f'&{name};')

    def handle_charref(self, name: str):
        self._out.append(f'&#{name};')

    def output(self) -> str:
        return ''.join(self._out)


def sanitize_telegram_html(text: str) -> str:
    """Sanitize LLM output for Telegram HTML mode.

    Keeps allowed formatting tags (<b>, <i>, <code>, etc.) and escapes
    anything else (e.g. email subjects containing '<ADV>') as visible text.
    """
    sanitizer = _TelegramHTMLSanitizer()
    sanitizer.feed(text)
    return sanitizer.output()

_SEP = "─"
_MAX_SUMMARY_LEN = 26   # chars for event title column
_MAX_SENDER_LEN  = 22   # chars for email sender column
_MAX_SUBJECT_LEN = 24   # chars for email subject column


# ── Generic feedback ──────────────────────────────────────────────────────────

def format_error(message: str) -> str:
    return f"❌ <b>Error:</b> {html.escape(message)}"


def format_model_switch(model_label: str) -> str:
    return f"✅ Switched to <b>{html.escape(model_label)}</b>"


def format_clear_confirm(turns: int) -> str:
    if turns == 0:
        return "ℹ️ Chat history is already empty."
    noun = "message" if turns == 1 else "messages"
    return f"🗑 History cleared ({turns} {noun} removed)."


def format_compact_thinking() -> str:
    return "⏳ Summarising conversation history…"


def format_compact_done(original_turns: int) -> str:
    return (
        f"✅ History compacted ({original_turns} messages → 1 summary). "
        "Context has been reset."
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _trunc(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _ascii_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a fixed-width ASCII table string (not HTML-escaped — caller escapes)."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep_line    = "  ".join(_SEP * widths[i] for i in range(len(headers)))
    data_lines  = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, sep_line] + data_lines)


# ── Calendar display ──────────────────────────────────────────────────────────

def format_events_table(events: list[dict]) -> str:
    """Return an HTML <pre> ASCII table of calendar events."""
    if not events:
        return "📅 No upcoming events."
    rows = [
        [str(i), e["start_display"], _trunc(e["summary"], _MAX_SUMMARY_LEN)]
        for i, e in enumerate(events, 1)
    ]
    table = _ascii_table(["#", "When", "Event"], rows)
    return f"📅 <b>Upcoming events</b>\n<pre>{html.escape(table)}</pre>"


def build_events_keyboard(events: list[dict]) -> InlineKeyboardMarkup:
    """Numbered event-select buttons (up to 10) plus Add Event."""
    number_buttons = [
        InlineKeyboardButton(str(i), callback_data=f"evt_sel:{i - 1}")
        for i in range(1, min(len(events), 10) + 1)
    ]
    # Group into rows of 5
    rows = [number_buttons[i:i + 5] for i in range(0, len(number_buttons), 5)]
    rows.append([InlineKeyboardButton("➕ Add Event", callback_data="evt_add")])
    return InlineKeyboardMarkup(rows)


def build_event_action_keyboard(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit",        callback_data=f"evt_edit:{idx}"),
            InlineKeyboardButton("🕐 Reschedule",  callback_data=f"evt_rsched:{idx}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel Event", callback_data=f"evt_cancel:{idx}"),
        ],
        [
            InlineKeyboardButton("◀ Back",          callback_data="evt_back"),
        ],
    ])


def build_event_cancel_confirm_keyboard(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, cancel it", callback_data=f"evt_cancel_ok:{idx}"),
        InlineKeyboardButton("Keep it",        callback_data=f"evt_sel:{idx}"),
    ]])


def format_event_detail(event: dict) -> str:
    summary = html.escape(event.get("summary", "(no title)"))
    when    = html.escape(event.get("start_display", ""))
    desc    = event.get("description", "").strip()
    text    = f"📅 <b>{summary}</b>\n🕐 {when}"
    if desc:
        text += f"\n📝 {html.escape(_trunc(desc, 120))}"
    text += "\n\nWhat would you like to do?"
    return text


def format_event_cancel_confirm(event: dict) -> str:
    summary = html.escape(event.get("summary", "(no title)"))
    when    = html.escape(event.get("start_display", ""))
    return f"⚠️ Cancel <b>{summary}</b> on {when}?"


# ── Calendar month-view keyboards ────────────────────────────────────────────

_MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def build_calendar_keyboard(
    year: int, month: int, days_with_events: set[int],
) -> InlineKeyboardMarkup:
    """Build the keyboard shown below the calendar image.

    Layout:
      [◀] [Month Year] [▶]
      day buttons (only days with events, rows of 7)
      [➕ Add Event]
    """
    # Navigation row
    nav_row = [
        InlineKeyboardButton("◀", callback_data="cal_prev"),
        InlineKeyboardButton(
            f"{_MONTH_NAMES[month]} {year}", callback_data="cal_noop"
        ),
        InlineKeyboardButton("▶", callback_data="cal_next"),
    ]

    # Day buttons — only for days that have events, grouped in rows of 7
    sorted_days = sorted(days_with_events)
    day_buttons = [
        InlineKeyboardButton(str(d), callback_data=f"cal_day:{d}")
        for d in sorted_days
    ]
    day_rows = [day_buttons[i : i + 7] for i in range(0, len(day_buttons), 7)]

    # Add event row
    add_row = [InlineKeyboardButton("➕ Add Event", callback_data="evt_add")]

    return InlineKeyboardMarkup([nav_row] + day_rows + [add_row])


def build_day_detail_keyboard(
    day_events: list[dict],
) -> InlineKeyboardMarkup:
    """Numbered event buttons for a specific day + Back to calendar."""
    number_buttons = [
        InlineKeyboardButton(str(i), callback_data=f"evt_sel:{i - 1}")
        for i in range(1, min(len(day_events), 10) + 1)
    ]
    rows = [number_buttons[i : i + 5] for i in range(0, len(number_buttons), 5)]
    rows.append([InlineKeyboardButton("◀ Back to calendar", callback_data="cal_back")])
    return InlineKeyboardMarkup(rows)


def format_day_events_text(
    events: list[dict], year: int, month: int, day: int,
) -> str:
    """Format a day's events as an HTML message."""
    import datetime

    d = datetime.date(year, month, day)
    header = f"📅 <b>{d.strftime('%A, %b %d %Y')}</b>\n"

    if not events:
        return header + "\nNo events on this day."

    lines: list[str] = []
    for i, ev in enumerate(events, 1):
        summary = html.escape(ev.get("summary", "(no title)"))
        when = html.escape(ev.get("start_display", ""))
        tag = " 🔵" if ev.get("is_recurring") else " 🟠"
        lines.append(f"<b>{i}.</b> {summary}{tag}\n     🕐 {when}")
        desc = ev.get("description", "").strip()
        if desc:
            lines.append(f"     📝 {html.escape(_trunc(desc, 80))}")

    return header + "\n" + "\n".join(lines) + "\n\nTap a number to manage that event."


# ── Email display ─────────────────────────────────────────────────────────────

def format_emails_table(emails: list[dict]) -> str:
    """Return an HTML <pre> ASCII table of emails."""
    if not emails:
        return "📧 No emails found."
    rows = [
        [
            str(i),
            _trunc(e["from_short"], _MAX_SENDER_LEN),
            _trunc(e["subject"],    _MAX_SUBJECT_LEN),
            e["date_short"],
        ]
        for i, e in enumerate(emails, 1)
    ]
    table = _ascii_table(["#", "From", "Subject", "Date"], rows)
    return f"📧 <b>Recent emails</b>\n<pre>{html.escape(table)}</pre>"


def build_emails_keyboard(emails: list[dict]) -> InlineKeyboardMarkup:
    """Numbered email-select buttons (up to 10)."""
    number_buttons = [
        InlineKeyboardButton(str(i), callback_data=f"mail_sel:{i - 1}")
        for i in range(1, min(len(emails), 10) + 1)
    ]
    rows = [number_buttons[i:i + 5] for i in range(0, len(number_buttons), 5)]
    return InlineKeyboardMarkup(rows)


def build_email_action_keyboard(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Read Full",      callback_data=f"mail_read:{idx}"),
            InlineKeyboardButton("↩️ Reply",          callback_data=f"mail_reply:{idx}"),
        ],
        [
            InlineKeyboardButton("◀ Back",            callback_data="mail_back"),
        ],
    ])


def format_email_detail(email: dict) -> str:
    sender  = html.escape(email.get("from", ""))
    subject = html.escape(email.get("subject", "(no subject)"))
    date    = html.escape(email.get("date_short", ""))
    snippet = html.escape(email.get("snippet", ""))
    return (
        f"📧 <b>{subject}</b>\n"
        f"From: {sender}\n"
        f"Date: {date}\n\n"
        f"{snippet}\n\n"
        "What would you like to do?"
    )
