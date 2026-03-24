"""LLM agent classes (Claude, Gemini) and system prompt."""

import datetime
import logging
from abc import ABC, abstractmethod

import anthropic
from google import genai
from google.genai import types

from config import (
    ANTHROPIC_KEY, GEMINI_KEY,
    CLAUDE_MODEL, GEMINI_MODEL, MAX_TOKENS,
    TIMEZONE_NAME, TIMEZONE_OFFSET_HOURS,
    CALENDAR_DEFAULT_DAYS_AHEAD,
    LOG_LEVEL,
)
from tools import registry

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))

MAX_HISTORY_TURNS = 20  # Max user+assistant turn pairs to retain


# ── System Prompt ────────────────────────────────────────────────────────────


def build_system_prompt() -> str:
    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=TIMEZONE_OFFSET_HOURS))
    ).strftime("%A, %d %B %Y %H:%M")

    return f"""\
You are a personal assistant with access to the user's Gmail and Google Calendar.
Current date/time: {now} ({TIMEZONE_NAME})

RULES:

1. GROUNDING
   Base responses strictly on retrieved data.
   Do not assume intent beyond what the user stated — e.g. do not assume
   a "job search" query means they want a "resume" unless explicitly asked.

2. COMPLETENESS
   Address every part of the user's query.

3. FORMATTING
   Use Telegram HTML: <b>bold</b>, <i>italic</i>, <code>code</code>.
   Use bullet lines (• item) for lists. Never use markdown syntax.

4. EMAIL ACTIONS
   Always confirm before sending — describe the recipient, subject, and body,
   then ask "Should I send this?" unless the user explicitly told you to go ahead.

5. CALENDAR — FINDING EVENTS
   To find an event, call list_events with days_ahead={CALENDAR_DEFAULT_DAYS_AHEAD}
   unless the user specifies a different range.
   If the user refers to an event vaguely ("my meeting", "the standup", "that thing tomorrow"):
   • Call list_events first.
   • If exactly one event matches the description, confirm it with the user.
   • If multiple events could match, list the candidates and ask which one.
   • If none match, try a wider days_ahead range before giving up.
   Never use Gmail tools (list_emails, get_email) to search for calendar events.

6. CALENDAR — CREATING EVENTS
   Timezone: assume {TIMEZONE_NAME} unless told otherwise.
   When the user gives a vague time reference:
   • "next week" or "sometime next week" without a specific day → ask which day and time.
   • A specific day without a time ("next Monday") → ask what time.
   • "morning" = 09:00, "afternoon" = 14:00, "evening" = 18:00.
   Default duration: if the user does not specify an end time or duration, assume 1 hour.
   For meal-related events ("lunch", "dinner"), assume 1.5 hours.
   If the request implies recurrence ("every Monday", "weekly standup", "daily reminder"),
   confirm the recurrence pattern before creating, then pass the appropriate RRULE string.
   Always confirm the full details before creating:
   "I'll create <b>title</b> on <b>day</b> at <b>start–end</b> ({TIMEZONE_NAME}). Shall I go ahead?"

7. CALENDAR — MODIFYING / DELETING EVENTS
   Always confirm destructive actions before proceeding.
   For recurring events marked "(recurring)", ask:
   "This is a recurring event — delete just this occurrence, or the entire series?"
   Then pass scope='single' or scope='series' accordingly.

8. EMAIL SUMMARIES
   When asked to summarise email content, always call get_email for each relevant
   email to retrieve the full body. Never summarise from the snippet alone."""


# ── Agent Base Class ─────────────────────────────────────────────────────────


class Agent(ABC):
    """Base class for LLM agents."""

    @abstractmethod
    def ask(self, user_message: str, history: list[dict] | None = None) -> str:
        """Send a message (with optional conversation history) and return the reply."""
        ...


# ── Claude Agent ─────────────────────────────────────────────────────────────


class ClaudeAgent(Agent):
    """Claude agent with tool-use loop."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def ask(self, user_message: str, history: list[dict] | None = None) -> str:
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
                f"  [{i}] {m['role']}: {repr(m['content'])[:200]}"
                for i, m in enumerate(messages)
            ),
        )

        while True:
            response = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=build_system_prompt(),
                tools=registry.anthropic_schemas(),
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            logger.debug(
                "[CLAUDE RAW OUTPUT] stop_reason=%s, usage=%s\n%s",
                response.stop_reason,
                response.usage,
                "\n".join(
                    f"  block: {repr(block)[:300]}" for block in response.content
                ),
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
                        result = registry.run(block.name, block.input)
                        logger.debug(
                            "[CLAUDE TOOL] %s(%s) => %s",
                            block.name, block.input, repr(result)[:300],
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return "(Unexpected stop reason)"


# ── Gemini Agent ─────────────────────────────────────────────────────────────


class GeminiAgent(Agent):
    """Gemini agent with automatic function calling."""

    def __init__(self):
        self._client = genai.Client(api_key=GEMINI_KEY)

    def ask(self, user_message: str, history: list[dict] | None = None) -> str:
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
                f"  [{i}] {m.role}: {repr(m.parts)[:200]}"
                for i, m in enumerate(gemini_history)
            ),
        )

        chat = self._client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=build_system_prompt(),
                tools=registry.gemini_callables(),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False
                ),
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


# ── Module-level singletons ─────────────────────────────────────────────────

claude_agent = ClaudeAgent()
gemini_agent = GeminiAgent()


# ── History Summariser (always uses Claude) ──────────────────────────────────


def summarise_history(history: list[dict]) -> str:
    """Summarise a conversation history into a compact paragraph using Claude."""
    lines = []
    for turn in history:
        role = turn["role"].upper()
        content = turn["content"]
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
    transcript = "\n".join(lines)
    response = claude_agent._client.messages.create(
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
