"""Per-conversation file logging.

Attaches a FileHandler to key loggers so every debug event (tool calls,
LLM inputs/outputs) for a single conversation is written to one file.

New file per conversation — triggered by the first message after startup
or after /clear. Conversation ID is stored in context.user_data so the
same file is reused across turns within the same conversation.
"""

import logging
import os
from datetime import datetime

LOGS_DIR = "logs"

# Loggers whose output is captured in the conversation file
_CAPTURE_LOGGERS = ["agent", "tools.base", "interface.handlers"]

_handler: logging.FileHandler | None = None


def _detach() -> None:
    global _handler
    if _handler is not None:
        for name in _CAPTURE_LOGGERS:
            logging.getLogger(name).removeHandler(_handler)
        _handler.close()
        _handler = None


def _attach(path: str) -> None:
    global _handler
    _detach()
    os.makedirs(LOGS_DIR, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setLevel(logging.DEBUG)
    h.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    for name in _CAPTURE_LOGGERS:
        logging.getLogger(name).addHandler(h)
    _handler = h


def start_conversation(user_data: dict) -> str:
    """Create a new conversation log file and store its ID in user_data."""
    conv_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    user_data["conversation_id"] = conv_id
    path = os.path.join(LOGS_DIR, f"conv_{conv_id}.log")
    _attach(path)
    logging.getLogger("interface.handlers").info(
        "=== NEW CONVERSATION %s ===", conv_id
    )
    return conv_id


def ensure_conversation(user_data: dict) -> str:
    """Return existing conv_id, or start a new one if none exists."""
    if "conversation_id" not in user_data:
        return start_conversation(user_data)
    return user_data["conversation_id"]
