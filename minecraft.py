import logging
from functools import wraps
from typing import List, Dict, Tuple
from urllib import response

import aiomcrcon
from telegram import Update
from telegram.ext import ContextTypes, ExtBot, CallbackContext, Application, CommandHandler


logger = logging.getLogger(__name__)


class MinecraftCommands:
    COMMANDS: Dict[str, Tuple[str, str]] = {}

    @staticmethod
    def register(cmd: str, desc: str):
        def wrapper(func):
            @wraps(func)
            async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                try:
                    cmd_chat_id = update.effective_chat.id
                    cmd_msg_id = update.message.message_id
                    await func(update, context)
                except Exception as e:
                    logger.exception("[%s] command failed in chat [%s] message [%s]:", cmd, cmd_chat_id, cmd_msg_id)
                    try:
                        await context.bot.send_message(
                            chat_id=cmd_chat_id,
                            reply_to_message_id=cmd_msg_id,
                            text=f"Error: {e}",
                        )
                    except Exception as e:
                        logger.error(
                            "[%s] failed to send error message; chat [%s] message [%s]", cmd, cmd_chat_id, cmd_msg_id
                        )

            MinecraftCommands.COMMANDS[cmd] = (desc, wrapped)
            logger.info("[%s][%s] registered", cmd, desc)
            return wrapped

        return wrapper


class MinecraftCommandHandler:
    RCON_CLIENT: "RCONClient" = None

    def __init__(self, app: Application, rcon_host: str, rcon_port: int, rcon_password: str) -> None:
        MinecraftCommandHandler.RCON_CLIENT = RCONClient(rcon_host, rcon_port, rcon_password, 5, 5)

        self.app = app
        for cmd, (_, handler) in MinecraftCommands.COMMANDS.items():
            self.app.add_handler(CommandHandler(cmd, handler))
        self.app.job_queue.run_once(MinecraftCommandHandler.set_commands, when=10)  # 10 seconds

        # player watcher
        self.online_players: List[str] = []
        self.app.job_queue.run_repeating(self.player_watcher, first=10, interval=5)

    @staticmethod
    async def set_commands(context: CallbackContext) -> None:
        bot: ExtBot = context.bot
        commands = []
        for cmd, (desc, _) in MinecraftCommands.COMMANDS.items():
            commands.append((cmd, desc))
        success = await bot.set_my_commands(commands)
        logger.info("set command: %s; supported: %s", success, commands)

    async def player_watcher(self, context: CallbackContext) -> None:
        logger.info("current players: %s", self.online_players)
        # TODO update players

    @MinecraftCommands.register("list", "Lists players on the server")
    @staticmethod
    async def list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("list")
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("op", "Grants operator status to a player")
    @staticmethod
    async def op(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("op", *update.message.text.split()[1:])
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("deop", "Revokes operator status from a player")
    @staticmethod
    async def deop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("deop", *update.message.text.split()[1:])
        await update.message.reply_text(
            response, reply_to_message_id=update.message.message_id
        ) @ MinecraftCommands.register("deop", "Grants operator status to a player")

    @MinecraftCommands.register("kill", "Kills entities (players, mobs, items, etc.)")
    @staticmethod
    async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("kill", *update.message.text.split()[1:])
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("kick", "Kicks a player off a server")
    @staticmethod
    async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("kick", *update.message.text.split()[1:])
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("save", "Saves the server to disk")
    @staticmethod
    async def save_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("save-all")
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("seed", "Displays the world seed")
    @staticmethod
    async def seed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("seed")
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("say", "Displays a message to multiple players")
    @staticmethod
    async def say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        content = update.message.text.split(maxsplit=1)[-1]
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("say", content)
        response = response or "sent to server"
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)


class RCONClient:
    def __init__(self, host: str, port: int, password: str, connect_timeout: int, read_timeout: int) -> None:
        self.host = host
        self.port = port
        self.password = password

        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        self.client = aiomcrcon.Client(host=self.host, port=self.port, password=self.password)

    async def send_command(self, command: str, *args, timeout: int = 0) -> str:
        timeout = timeout or self.read_timeout
        await self.client.connect(self.connect_timeout)
        response, response_type = await self.client.send_cmd(" ".join([command] + list(args)), timeout)
        logger.info("rcon command executed: [%s], response: [%s] %s", command, response_type, response)
        return response.strip()
