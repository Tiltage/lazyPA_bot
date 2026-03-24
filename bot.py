import logging
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)
from config import TELEGRAM_TOKEN, LOG_LEVEL
from interface.handlers import get_command_registry, handle_callback, handle_message

logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)


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
