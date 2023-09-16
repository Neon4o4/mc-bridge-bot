import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Defaults

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
    mc_config = CONFIG["mc-server"]

    app = (
        ApplicationBuilder()
        .token(tg_config["token"])
        .base_url(tg_config["base_url"])
        .base_file_url("base_file_url")
        .defaults(Defaults(block=False))
        .build()
    )

    logger.info("bot starting")

    app.add_handler(CommandHandler("start", start))
    MinecraftCommandHandler(
        app,
        mc_config["base_dir"],
        mc_config["logfile"],
        mc_config["world_dir"],
        mc_config["rcon_host"],
        mc_config["rcon_port"],
        mc_config["rcon_password"],
        mc_config["backup_chat_id"],
        mc_config["daily_backup"],
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)
