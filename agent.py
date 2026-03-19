import datetime
import logging
import anthropic
import google.generativeai as genai

from config import (
    ANTHROPIC_KEY, GEMINI_KEY,
    CLAUDE_MODEL, GEMINI_MODEL, MAX_TOKENS,
    TIMEZONE_NAME, TIMEZONE_OFFSET_HOURS,
    GMAIL_DEFAULT_MAX_RESULTS,
    CALENDAR_DEFAULT_DAYS_AHEAD,
    LOG_LEVEL,
)
from tools import list_emails, get_email, send_email, list_events, create_event

genai.configure(api_key=GEMINI_KEY)

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
    5. Calendar Actions: For creating calendar events, infer the timezone as {TIMEZONE_NAME} unless told otherwise.
    6. Email Summaries: When asked to summarise email content, you MUST call get_email for each relevant email to retrieve the full body before summarising. Never summarise based on the snippet alone.
    
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
                "days_ahead": {"type": "integer", "description": "How many days ahead to look (default 7)", "default": CALENDAR_DEFAULT_DAYS_AHEAD}
            }
        }
    },
    {
        "name": "create_event",
        "description": "Create a new Google Calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start_datetime": {"type": "string", "description": "Start time in ISO 8601 format with timezone, e.g. 2026-03-20T14:00:00+08:00"},
                "end_datetime": {"type": "string", "description": "End time in ISO 8601 format with timezone"},
                "description": {"type": "string", "description": "Optional event description", "default": ""}
            },
            "required": ["summary", "start_datetime", "end_datetime"]
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
    gemini_tools = [list_emails, get_email, send_email, list_events, create_event]
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        tools=gemini_tools,
        system_instruction=build_system_prompt(),
    )
    # Gemini uses "model" for assistant role; convert our shared history format
    gemini_history = [
        {
            "role": "model" if turn["role"] == "assistant" else "user",
            "parts": [turn["content"]],
        }
        for turn in (history or [])
    ]

    logger.debug(
        "[GEMINI INPUT] history turns: %d, new message: %s\n%s",
        len(history or []),
        repr(user_message)[:200],
        "\n".join(
            f"  [{i}] {m['role']}: {repr(m['parts'])[:200]}{'...' if len(repr(m['parts'])) > 200 else ''}"
            for i, m in enumerate(gemini_history)
        ),
    )

    chat = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
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
