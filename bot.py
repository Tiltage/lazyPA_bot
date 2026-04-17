import logging
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)
from config import TELEGRAM_TOKEN, LOG_LEVEL
from interface.handlers import get_command_registry, handle_callback, handle_message


class _CleanFormatter(logging.Formatter):
    """Strip level/name prefix — just emit the message."""
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def _setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.DEBUG)

    # Root: WARNING only — catches anything not explicitly configured below
    logging.basicConfig(level=logging.WARNING)

    # Silence noisy third-party libraries
    for _name in ("httpcore", "httpx", "telegram", "asyncio",
                  "google_genai", "urllib3"):
        logging.getLogger(_name).setLevel(logging.WARNING)

    # App loggers: clean [ACTION] format, no propagation to noisy root handler
    _handler = logging.StreamHandler()
    _handler.setFormatter(_CleanFormatter())
    for _name in ("agent", "interface.handlers", "tools", "tools.base"):
        _log = logging.getLogger(_name)
        _log.setLevel(level)
        _log.addHandler(_handler)
        _log.propagate = False


_setup_logging(LOG_LEVEL)


async def _set_commands(app: Application) -> None:
    commands = [BotCommand(name, desc) for name, desc, _ in get_command_registry()]
    await app.bot.set_my_commands(commands)


def main():
    """Build and run the Telegram bot."""
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_set_commands).build()

    for name, _, fn in get_command_registry():
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
