"""Telegram command and callback handlers."""
import logging
from telegram import Update
from telegram.ext import ContextTypes

# ── Command registry ──────────────────────────────────────────────────────────

_registry: list[tuple[str, str, object]] = []  # (command_name, description, fn)


def command(name: str, description: str):
    """Decorator that registers a handler function as a bot command."""
    def decorator(fn):
        _registry.append((name, description, fn))
        return fn
    return decorator


def get_command_registry() -> list[tuple[str, str, object]]:
    return list(_registry)
from config import ALLOWED_CHAT_ID
from agent import claude_agent, gemini_agent, summarise_history, MAX_HISTORY_TURNS
from tools import get_events_raw, get_emails_raw
from interface.ui import (
    format_model_switch, format_error,
    format_clear_confirm, format_compact_thinking, format_compact_done,
    format_events_table, build_events_keyboard,
    build_event_action_keyboard, build_event_cancel_confirm_keyboard,
    format_event_detail, format_event_cancel_confirm,
    format_emails_table, build_emails_keyboard,
    build_email_action_keyboard, format_email_detail,
    sanitize_telegram_html,
)

logger = logging.getLogger(__name__)


# ── Shared agent helper ───────────────────────────────────────────────────────

async def _call_agent(user_text: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Run user_text through the active model, update history, return reply."""
    active_model = context.user_data.get("active_model", "gemini")
    history = context.user_data.get("conversation_history", [])
    agent = claude_agent if active_model == "claude" else gemini_agent
    try:
        reply = agent.ask(user_text, history)
    except Exception as e:
        return format_error(str(e))
    reply = sanitize_telegram_html(reply)
    history.append({"role": "user",      "content": user_text})
    history.append({"role": "assistant", "content": reply})
    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[-(MAX_HISTORY_TURNS * 2):]
    context.user_data["conversation_history"] = history
    return reply


def _guard(update: Update) -> bool:
    """Return True if the message is from the allowed chat."""
    return update.effective_chat.id == ALLOWED_CHAT_ID


# ── Model switch commands ─────────────────────────────────────────────────────

@command("claude", "Switch to Claude model")
async def set_claude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch active model to Claude."""
    if not _guard(update):
        return
    context.user_data["active_model"] = "claude"
    await update.message.reply_text(
        format_model_switch("Claude 3.5 Sonnet"), parse_mode="HTML"
    )


@command("gemini", "Switch to Gemini model")
async def set_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch active model to Gemini."""
    if not _guard(update):
        return
    context.user_data["active_model"] = "gemini"
    await update.message.reply_text(
        format_model_switch("Gemini 2.5 Pro"), parse_mode="HTML"
    )


# ── History management commands ───────────────────────────────────────────────

@command("clear", "Clear conversation history")
async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wipe conversation history. Usage: /clear"""
    if not _guard(update):
        return
    history = context.user_data.get("conversation_history", [])
    turns = len(history)
    context.user_data["conversation_history"] = []
    await update.message.reply_text(format_clear_confirm(turns))


@command("compact", "Summarise and compress history")
async def compact_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Summarise and compress conversation history. Usage: /compact"""
    if not _guard(update):
        return
    history = context.user_data.get("conversation_history", [])
    if not history:
        await update.message.reply_text("ℹ️ No history to compact.")
        return
    status = await update.message.reply_text(format_compact_thinking())
    try:
        summary = summarise_history(history)
        original_turns = len(history)
        # Replace history with a single summary turn the model can reference
        context.user_data["conversation_history"] = [
            {
                "role": "user",
                "content": "[System: Summary of our earlier conversation follows.]",
            },
            {"role": "assistant", "content": summary},
        ]
        await status.edit_text(format_compact_done(original_turns))
    except Exception as e:
        await status.edit_text(format_error(f"Compact failed: {e}"))


# ── Structured data display commands ─────────────────────────────────────────

@command("events", "Show upcoming calendar events")
async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and display calendar events with inline action keyboard. Usage: /events"""
    if not _guard(update):
        return
    try:
        events = get_events_raw()
    except Exception as e:
        await update.message.reply_text(format_error(str(e)), parse_mode="HTML")
        return
    context.user_data["last_events"] = events
    await update.message.reply_text(
        format_events_table(events),
        parse_mode="HTML",
        reply_markup=build_events_keyboard(events) if events else None,
    )


@command("emails", "Show recent emails")
async def show_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and display recent emails with inline action keyboard. Usage: /emails"""
    if not _guard(update):
        return
    try:
        emails = get_emails_raw()
    except Exception as e:
        await update.message.reply_text(format_error(str(e)), parse_mode="HTML")
        return
    context.user_data["last_emails"] = emails
    await update.message.reply_text(
        format_emails_table(emails),
        parse_mode="HTML",
        reply_markup=build_emails_keyboard(emails) if emails else None,
    )


# ── Inline keyboard callback handler ─────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatch inline keyboard button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # ── Calendar callbacks ────────────────────────────────────────────────────
    if data.startswith("evt_sel:"):
        idx = int(data.split(":")[1])
        events = context.user_data.get("last_events", [])
        if idx >= len(events):
            await query.answer("Event no longer available.", show_alert=True)
            return
        event = events[idx]
        await query.edit_message_text(
            format_event_detail(event),
            parse_mode="HTML",
            reply_markup=build_event_action_keyboard(idx),
        )

    elif data == "evt_back":
        events = context.user_data.get("last_events", [])
        await query.edit_message_text(
            format_events_table(events),
            parse_mode="HTML",
            reply_markup=build_events_keyboard(events),
        )

    elif data.startswith("evt_edit:"):
        idx = int(data.split(":")[1])
        events = context.user_data.get("last_events", [])
        event = events[idx] if idx < len(events) else {}
        prompt = (
            f"I want to edit the calendar event '{event.get('summary', 'unknown')}' "
            f"on {event.get('start_display', 'unknown')}. "
            "What details can I change, and can you guide me through updating it?"
        )
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(prompt, context)
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")

    elif data.startswith("evt_rsched:"):
        idx = int(data.split(":")[1])
        events = context.user_data.get("last_events", [])
        event = events[idx] if idx < len(events) else {}
        prompt = (
            f"I want to reschedule '{event.get('summary', 'unknown')}' "
            f"(currently {event.get('start_display', 'unknown')}). "
            "Please ask me for the new date and time."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(prompt, context)
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")

    elif data.startswith("evt_cancel:"):
        idx = int(data.split(":")[1])
        events = context.user_data.get("last_events", [])
        event = events[idx] if idx < len(events) else {}
        await query.edit_message_text(
            format_event_cancel_confirm(event),
            parse_mode="HTML",
            reply_markup=build_event_cancel_confirm_keyboard(idx),
        )

    elif data.startswith("evt_cancel_ok:"):
        idx = int(data.split(":")[1])
        events = context.user_data.get("last_events", [])
        event = events[idx] if idx < len(events) else {}
        prompt = (
            f"Please cancel (delete) the calendar event "
            f"'{event.get('summary', 'unknown')}' on "
            f"{event.get('start_display', 'unknown')}. "
            f"The event ID is {event.get('id', 'unknown')}."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(prompt, context)
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")

    elif data == "evt_add":
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(
            "I want to add a new calendar event. Please ask me for the details.",
            context,
        )
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")

    # ── Email callbacks ───────────────────────────────────────────────────────
    elif data.startswith("mail_sel:"):
        idx = int(data.split(":")[1])
        emails = context.user_data.get("last_emails", [])
        if idx >= len(emails):
            await query.answer("Email no longer available.", show_alert=True)
            return
        email = emails[idx]
        await query.edit_message_text(
            format_email_detail(email),
            parse_mode="HTML",
            reply_markup=build_email_action_keyboard(idx),
        )

    elif data == "mail_back":
        emails = context.user_data.get("last_emails", [])
        await query.edit_message_text(
            format_emails_table(emails),
            parse_mode="HTML",
            reply_markup=build_emails_keyboard(emails),
        )

    elif data.startswith("mail_read:"):
        idx = int(data.split(":")[1])
        emails = context.user_data.get("last_emails", [])
        email = emails[idx] if idx < len(emails) else {}
        prompt = (
            f"Please fetch and show me the full content of the email with "
            f"ID {email.get('id', 'unknown')} "
            f"(from {email.get('from', 'unknown')}, "
            f"subject: {email.get('subject', 'unknown')})."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(prompt, context)
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")

    elif data.startswith("mail_reply:"):
        idx = int(data.split(":")[1])
        emails = context.user_data.get("last_emails", [])
        email = emails[idx] if idx < len(emails) else {}
        prompt = (
            f"Draft a reply to the email from {email.get('from', 'unknown')} "
            f"with subject '{email.get('subject', 'unknown')}'. "
            "Ask me what I'd like to say if you need more context."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        reply = await _call_agent(prompt, context)
        await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="HTML")


# ── Free-text message handler ─────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route free-text messages through the active agent."""
    chat_id = update.effective_chat.id
    logger.debug("Message from %s (allowed: %s)", chat_id, ALLOWED_CHAT_ID)
    if chat_id != ALLOWED_CHAT_ID:
        logger.debug("Blocked: ID mismatch")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = await _call_agent(update.message.text, context)
    await update.message.reply_text(reply, parse_mode="HTML")
