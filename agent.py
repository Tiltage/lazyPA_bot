import datetime
import logging
import anthropic
from google import genai
from google.genai import types

from config import (
    ANTHROPIC_KEY, GEMINI_KEY,
    CLAUDE_MODEL, GEMINI_MODEL, MAX_TOKENS,
    TIMEZONE_NAME, TIMEZONE_OFFSET_HOURS,
    GMAIL_DEFAULT_MAX_RESULTS,
    CALENDAR_DEFAULT_DAYS_AHEAD,
    LOG_LEVEL,
)
from tools import list_emails, get_email, send_email, list_events, create_event, delete_event, update_event


logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))

MAX_HISTORY_TURNS = 20  # Max user+assistant turn pairs to retain

# ── System Prompt ─────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=TIMEZONE_OFFSET_HOURS))
    ).strftime("%A, %d %B %Y %H:%M")
    tz_abbr = TIMEZONE_NAME.split("/")[-1].upper()
    
    system_prompt = f"""
    You are a personal assistant with access to the user's Gmail and Google Calendar. Today's date and time is {now} ({tz_abbr}). Follow these operating rules at all times:

    1. Grounding: When you retrieve emails or events, base your response STRICTLY on the retrieved context. Do not make assumptions about the user's intent (e.g., do not assume a 'job search' query means they want a 'resume' unless they explicitly ask for one).
    2. Comprehensiveness: Ensure you answer every part of the user's query.
    3. Formatting: Format all responses using Telegram HTML tags: <b>bold</b>, <i>italic</i>, <code>inline code</code>. Use plain bullet lines (• item) for lists. Never use markdown asterisks, underscores, or backtick syntax.
    4. Email Actions: Always confirm before sending emails — describe exactly what you will send and ask 'Should I send this?' unless the user explicitly said to go ahead.
    5. Calendar Actions: For creating, deleting, or editing calendar events, infer the timezone as {TIMEZONE_NAME} unless told otherwise. Always confirm destructive actions (delete/update) before proceeding — describe the event and the change, then ask 'Should I go ahead?' unless the user explicitly said to go ahead. To find an event's ID for deletion or editing, call list_events first — always pass days_ahead={CALENDAR_DEFAULT_DAYS_AHEAD} unless the user explicitly requests a different range. When creating an event, if the user's request implies recurrence (e.g. 'every Monday', 'weekly standup', 'daily reminder'), confirm the recurrence pattern with them before creating, then pass the appropriate RRULE string. For deleting recurring events (marked with '(recurring)'), you MUST ask the user: 'This is a recurring event — do you want to delete just this occurrence, or the entire series?' Then call delete_event with scope='single' or scope='series' based on their answer.
    6. Email Summaries: When asked to summarise email content, you MUST call get_email for each relevant email to retrieve the full body before summarising. Never summarise based on the snippet alone.
    7. Tool Boundaries: NEVER use Gmail tools (list_emails, get_email) to search for calendar events. Calendar events can only be found via list_events. If list_events does not return the expected event, try a larger days_ahead value before giving up.
    
    """
    
    return (system_prompt)

# ── Tool Schemas (Anthropic format) ───────────────────────────────────────────

TOOLS = [
    {
        "name": "list_emails",
        "description": "List recent emails from Gmail inbox. Use query for filtering (e.g. 'from:boss@example.com', 'is:unread', 'subject:invoice').",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Number of emails to return (default 5, max 20)", "default": GMAIL_DEFAULT_MAX_RESULTS},
                "query": {"type": "string", "description": "Gmail search query string", "default": ""}
            }
        }
    },
    {
        "name": "get_email",
        "description": "Get the full content of a specific email by its message ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The Gmail message ID"}
            },
            "required": ["message_id"]
        }
    },
    {
        "name": "send_email",
        "description": "Send an email via Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text)"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "list_events",
        "description": "List upcoming Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": f"How many days ahead to look (default {CALENDAR_DEFAULT_DAYS_AHEAD}). Always use {CALENDAR_DEFAULT_DAYS_AHEAD} unless the user explicitly requests a different range.", "default": CALENDAR_DEFAULT_DAYS_AHEAD}
            }
        }
    },
    {
        "name": "create_event",
        "description": (
            "Create a new Google Calendar event — either a single occurrence or a recurring series. "
            "For recurring events, ask the user for the recurrence pattern (e.g. every Monday, daily, monthly) "
            "and construct the appropriate RRULE string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start_datetime": {"type": "string", "description": "Start time in ISO 8601 format with timezone, e.g. 2026-03-20T14:00:00+08:00"},
                "end_datetime": {"type": "string", "description": "End time in ISO 8601 format with timezone"},
                "description": {"type": "string", "description": "Optional event description", "default": ""},
                "recurrence": {
                    "type": "string",
                    "description": (
                        "RRULE string for recurring events. Leave empty for a single event. "
                        "Examples: 'RRULE:FREQ=DAILY', 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR', "
                        "'RRULE:FREQ=MONTHLY;BYMONTHDAY=1', 'RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261231T000000Z'."
                    ),
                    "default": ""
                }
            },
            "required": ["summary", "start_datetime", "end_datetime"]
        }
    },
    {
        "name": "delete_event",
        "description": (
            "Delete a Google Calendar event by its event ID. Call list_events first to find the correct event ID. "
            "If the event is recurring (marked with '(recurring)' in list_events output), you MUST ask the user "
            "whether to delete just this single occurrence or the entire series before calling this tool, "
            "then pass scope='single' or scope='series' accordingly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The Google Calendar event ID to delete"},
                "scope": {
                    "type": "string",
                    "enum": ["single", "series"],
                    "description": "For recurring events: 'single' deletes only this occurrence, 'series' deletes all occurrences. For non-recurring events use 'single'.",
                    "default": "single"
                }
            },
            "required": ["event_id", "scope"]
        }
    },
    {
        "name": "update_event",
        "description": "Update one or more fields of an existing Google Calendar event. Call list_events first to find the correct event ID. Only provided fields are changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The Google Calendar event ID to update"},
                "summary": {"type": "string", "description": "New event title"},
                "start_datetime": {"type": "string", "description": "New start time in ISO 8601 format with timezone"},
                "end_datetime": {"type": "string", "description": "New end time in ISO 8601 format with timezone"},
                "description": {"type": "string", "description": "New event description"}
            },
            "required": ["event_id"]
        }
    },
]

# ── Tool Dispatcher ───────────────────────────────────────────────────────────

_TOOL_MAP = {
    "list_emails":  list_emails,
    "get_email":    get_email,
    "send_email":   send_email,
    "list_events":  list_events,
    "create_event": create_event,
    "delete_event": delete_event,
    "update_event": update_event,
}

def run_tool(tool_name: str, tool_input: dict) -> str:
    fn = _TOOL_MAP.get(tool_name)
    if fn is None:
        return f"Unknown tool: {tool_name}"
    try:
        return fn(**tool_input)
    except Exception as e:
        return f"Tool error ({tool_name}): {str(e)}"

# ── Claude Agent ──────────────────────────────────────────────────────────────

def ask_claude(user_message: str, history: list[dict] | None = None) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    # Build messages from history (simple text turns) + current user message
    messages = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in (history or [])
    ]
    messages.append({"role": "user", "content": user_message})

    logger.debug(
        "[CLAUDE INPUT] history turns: %d, total messages: %d\n%s",
        len(history or []),
        len(messages),
        "\n".join(
            f"  [{i}] {m['role']}: {repr(m['content'])[:200]}{'...' if len(repr(m['content'])) > 200 else ''}"
            for i, m in enumerate(messages)
        ),
    )

    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        logger.debug(
            "[CLAUDE RAW OUTPUT] stop_reason=%s, usage=%s\n%s",
            response.stop_reason,
            response.usage,
            "\n".join(f"  block: {repr(block)[:300]}" for block in response.content),
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "(No response)"

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    logger.debug("[CLAUDE TOOL] %s(%s) => %s", block.name, block.input, repr(result)[:300])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "(Unexpected stop reason)"

# ── History Summariser ────────────────────────────────────────────────────────

def summarise_history(history: list[dict]) -> str:
    """Summarise a conversation history into a compact paragraph using Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    lines = []
    for turn in history:
        role = turn["role"].upper()
        content = turn["content"]
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
        # Skip tool-use blocks that were stored as lists (shouldn't occur, but guard)
    transcript = "\n".join(lines)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Summarise the following conversation concisely, preserving all "
                "important context, decisions, pending items, and any data the "
                "user may refer back to (e.g. event names, email subjects):\n\n"
                + transcript
            ),
        }],
    )
    return response.content[0].text


# ── Gemini Agent ──────────────────────────────────────────────────────────────

def ask_gemini(user_message: str, history: list[dict] | None = None) -> str:
    gemini_tools = [list_emails, get_email, send_email, list_events, create_event, delete_event, update_event]
    client = genai.Client(api_key=GEMINI_KEY)
    # Gemini uses "model" for assistant role; convert our shared history format
    gemini_history = [
        types.Content(
            role="model" if turn["role"] == "assistant" else "user",
            parts=[types.Part(text=turn["content"])],
        )
        for turn in (history or [])
    ]

    logger.debug(
        "[GEMINI INPUT] history turns: %d, new message: %s\n%s",
        len(history or []),
        repr(user_message)[:200],
        "\n".join(
            f"  [{i}] {m.role}: {repr(m.parts)[:200]}{'...' if len(repr(m.parts)) > 200 else ''}"
            for i, m in enumerate(gemini_history)
        ),
    )

    chat = client.chats.create(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            tools=gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
        ),
        history=gemini_history,
    )
    try:
        response = chat.send_message(user_message)
        logger.debug(
            "[GEMINI RAW OUTPUT]\n  candidates: %s\n  usage_metadata: %s",
            repr(response.candidates)[:500],
            response.usage_metadata,
        )
        return response.text
    except Exception as e:
        logger.debug("[GEMINI ERROR] %s", e)
        return f"Gemini Error: {str(e)}"
