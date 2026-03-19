import os
import configparser
from dotenv import load_dotenv

load_dotenv()

# ── Sensitive (from .env) ─────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY")
GEMINI_KEY       = os.getenv("GEMINI_API_KEY")
ALLOWED_CHAT_ID  = int(os.getenv("YOUR_CHAT_ID"))

# ── App config (from .config) ─────────────────────────────────────────────────

_cfg = configparser.ConfigParser()
_cfg.read(".config")

CLAUDE_MODEL    = _cfg.get("models", "claude")
GEMINI_MODEL    = _cfg.get("models", "gemini")
DEFAULT_MODEL   = _cfg.get("models", "gemini")
MAX_TOKENS      = _cfg.getint("models", "max_tokens", fallback=2048)

TIMEZONE_NAME         = _cfg.get("timezone", "name", fallback="Asia/Singapore")
TIMEZONE_OFFSET_HOURS = _cfg.getint("timezone", "offset_hours", fallback=8)

GMAIL_DEFAULT_MAX_RESULTS = _cfg.getint("gmail", "default_max_results", fallback=5)
GMAIL_MAX_BODY_LENGTH     = _cfg.getint("gmail", "max_body_length", fallback=3000)
GMAIL_SNIPPET_LENGTH      = _cfg.getint("gmail", "snippet_length", fallback=120)

CALENDAR_DEFAULT_DAYS_AHEAD = _cfg.getint("calendar", "default_days_ahead", fallback=7)
CALENDAR_MAX_EVENTS         = _cfg.getint("calendar", "max_events", fallback=15)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = "DEBUG"  # Set to INFO/WARNING/ERROR to silence agent debug output

# ── Google OAuth scopes ───────────────────────────────────────────────────────

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar",
]
