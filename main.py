import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config import CONFIG

from minecraft import MinecraftCommandHandler

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
    )


if __name__ == "__main__":
    tg_config = CONFIG["telegram"]
    rcon_config = CONFIG["rcon"]

    app = (
        ApplicationBuilder()
        .token(tg_config["token"])
        .base_url(tg_config["base_url"])
        .base_file_url("base_file_url")
        .build()
    )

    logger.info("bot starting")

    app.add_handler(CommandHandler("start", start))
    MinecraftCommandHandler(app, rcon_config["host"], rcon_config["port"], rcon_config["password"])

    app.run_polling(allowed_updates=Update.ALL_TYPES)
