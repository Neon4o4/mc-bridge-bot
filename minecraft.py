import asyncio
from dataclasses import dataclass
from datetime import datetime
from datetime import time as datetime_time
from datetime import timezone
import errno
import logging
from functools import wraps
import os
import re
import socket
from sys import stderr
from typing import List, Dict, Tuple
from urllib import response

import aiomcrcon
from telegram import Message, Update
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
                    logger.info("[%s] command executed in chat [%s] message [%s]", cmd, cmd_chat_id, cmd_msg_id)
                except Exception as e:
                    logger.exception("[%s] command failed in chat [%s] message [%s]:", cmd, cmd_chat_id, cmd_msg_id)
                    try:
                        await context.bot.send_message(
                            chat_id=cmd_chat_id,
                            reply_to_message_id=cmd_msg_id,
                            text=f"Error: {e}",
                        )
                    except Exception:
                        logger.exception(
                            "[%s] failed to send error message; chat [%s] message [%s]", cmd, cmd_chat_id, cmd_msg_id
                        )

            MinecraftCommands.COMMANDS[cmd] = (desc, wrapped)
            logger.info("[%s][%s] registered", cmd, desc)
            return wrapped

        return wrapper


@dataclass
class MCConfig:
    base_dir: str
    logfile: str
    world_dir: str
    rcon_host: str
    rcon_port: int
    rcon_password: str
    tg_chat_id: int
    daily_backup: str


class MinecraftCommandHandler:
    MC_CONFIG: MCConfig = None
    RCON_CLIENT: "RCONClient" = None

    def __init__(
        self,
        app: Application,
        mc_dir: str,
        mc_logfile: str,
        mc_world_dir: str,
        rcon_host: str,
        rcon_port: int,
        rcon_password: str,
        tg_chat_id: int,
        daily_backup: str,
    ) -> None:
        MinecraftCommandHandler.MC_CONFIG = MCConfig(
            mc_dir, mc_logfile, mc_world_dir, rcon_host, rcon_port, rcon_password, tg_chat_id, daily_backup
        )

        MinecraftCommandHandler.RCON_CLIENT = RCONClient(MinecraftCommandHandler.MC_CONFIG, 5, 5)

        self.app = app
        for cmd, (_, handler) in MinecraftCommands.COMMANDS.items():
            self.app.add_handler(CommandHandler(cmd, handler))
        self.app.job_queue.run_once(MinecraftCommandHandler.set_commands, when=10)  # 10 seconds

        # player watcher
        self.online_players: List[str] = []
        # self.app.job_queue.run_repeating(self.player_watcher, first=10, interval=5)

        # backup job
        self.app.job_queue.run_daily(
            MinecraftCommandHandler.backup_job,
            datetime_time(2, 30, 0, tzinfo=datetime.now().astimezone().tzinfo),
        )

        # mc log bridge
        self.current_log_tell = None
        self.log_bridge_lock = asyncio.Lock()
        self.app.job_queue.run_repeating(self.mc_log_bridge, first=10, interval=3)

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

    async def mc_log_bridge(self, context: CallbackContext) -> None:
        chat_id = MinecraftCommandHandler.MC_CONFIG.tg_chat_id
        bot: ExtBot = context.bot

        async with self.log_bridge_lock:
            await self.mc_log_bridge_inner(bot, chat_id)

    async def mc_log_bridge_inner(self, bot: ExtBot, chat_id: int) -> None:
        logfile = os.path.join(MinecraftCommandHandler.MC_CONFIG.base_dir, MinecraftCommandHandler.MC_CONFIG.logfile)
        if not os.path.exists(logfile):
            logger.warning("log file does not exist: %s", logfile)
            return

        lines: List[str] = []
        with open(logfile, "r") as f:
            f.seek(0, os.SEEK_END)
            current_end = f.tell()
            if self.current_log_tell is None:
                self.current_log_tell = current_end
                logger.info("set current log tell to file end: %s", current_end)

            if current_end < self.current_log_tell:
                logger.warning("file reset. reading from the begining")
                self.current_log_tell = 0

            # seek to (last) read position
            f.seek(self.current_log_tell)

            current_tell = f.tell()
            while True:
                line = f.readline()
                if not line:
                    f.seek(current_tell)
                    break
                lines.append(line)
                current_tell = f.tell()

            logger.info("read %s lines", len(lines))
            logger.info("set current log tell [%s] to: [%s]", self.current_log_tell, current_tell)
            self.current_log_tell = current_tell

        # find useful lines and send to chat
        PATTERN_CHAT = re.compile(
            r"\[Server thread/INFO] \[net.minecraft.server.MinecraftServer/]:\s+(?:\[Not Secure]\s+)?<(.+)>\s+(.+)"
        )
        PATTERN_EVENT = re.compile(r"\[Server thread/INFO] \[net.minecraft.server.MinecraftServer/]:\s+(?!\[)(.+)")
        for line in lines:
            found_chat = PATTERN_CHAT.findall(line)
            for who, what in found_chat:
                await bot.send_message(chat_id=chat_id, text=f"{who}: {what}")
                logger.info("server chat: [%s] %s", who, what)
            found_event = PATTERN_EVENT.findall(line)
            for what in found_event:
                await bot.send_message(chat_id=chat_id, text=what)
                logger.info("server event: %s", what)

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
        progress_msg = await update.message.reply_text("Saving...", reply_to_message_id=update.message.message_id)
        await MinecraftCommandHandler.backup_world(progress_msg)

    @staticmethod
    async def backup_job(context: CallbackContext) -> None:
        logger.info("backup_job started")
        chat_id = MinecraftCommandHandler.MC_CONFIG.tg_chat_id
        bot: ExtBot = context.bot
        progress_msg = await bot.send_message(chat_id, "Backing up...")
        await MinecraftCommandHandler.backup_world(progress_msg)
        await progress_msg.delete()

    @staticmethod
    async def backup_world(progress_msg: Message) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("save-all")
        logger.info("backup response: %s", response)

        await progress_msg.edit_text("World saved. Backing up...")
        # backup
        mc_config = MinecraftCommandHandler.MC_CONFIG

        backup_time = datetime.now()
        backup_filename = f"{mc_config.world_dir}.{backup_time.strftime('%Y-%m-%d_%H-%M-%S')}.tar.gz"
        try:
            proc = await asyncio.create_subprocess_exec(
                "tar",
                "-czf",
                backup_filename,
                os.path.join(mc_config.base_dir, mc_config.world_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            err = proc.returncode
            if err:
                stderr = stderr.decode().strip()
                logger.error("backup failed: [%s] %s", err, stderr)
                if os.path.exists(backup_filename):
                    os.remove(backup_filename)
                logger.info("backup removed: %s", backup_filename)
                await progress_msg.edit_text(f"Backup failed: [{err}] {stderr}")
            else:
                stdout = stdout.decode().strip()
                logger.info("backup succeeded: %s", stdout)
                await progress_msg.edit_text(f"Backup succeeded {stdout}. Uploading...")
                # upload
                bot: ExtBot = progress_msg.get_bot()
                await bot.send_document(
                    chat_id=progress_msg.chat_id,
                    document=backup_filename,
                    reply_to_message_id=progress_msg.message_id,
                    caption=f'Backup of [{mc_config.world_dir}] @ {backup_time.strftime("%Y-%m-%d %H:%M:%S")}',
                    connect_timeout=15,
                    read_timeout=30,
                    write_timeout=300,
                )
                logger.info("backup uploaded: %s", backup_filename)
                await progress_msg.edit_text("Backup finished.")
        except Exception:
            logger.exception("backup failed")
        finally:
            if os.path.exists(backup_filename):
                os.remove(backup_filename)
                logger.info("backup removed: %s", backup_filename)

    @MinecraftCommands.register("seed", "Displays the world seed")
    @staticmethod
    async def seed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command("seed")
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)

    @MinecraftCommands.register("say", "Displays a message to multiple players")
    @staticmethod
    async def say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        content = update.message.text.split(maxsplit=1)[-1]
        response = await MinecraftCommandHandler.RCON_CLIENT.send_command(
            "say", f"[{update.message.from_user.full_name}]: ", content
        )
        response = response or "sent to server"
        await update.message.reply_text(response, reply_to_message_id=update.message.message_id)


class RCONClient:
    def __init__(self, server_config: MCConfig, connect_timeout: int, read_timeout: int) -> None:
        self.server_config = server_config

        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        self.reset_client()

    def reset_client(self):
        self.client = aiomcrcon.Client(
            self.server_config.rcon_host, self.server_config.rcon_port, self.server_config.rcon_password
        )

    async def send_command(self, command: str, *args, timeout: int = 0, retry: int = 2) -> str:
        timeout = timeout or self.read_timeout
        await self.client.connect(self.connect_timeout)
        try:
            response, response_type = await self.client.send_cmd(" ".join([command] + list(args)), timeout)
        except socket.error as e:
            if e.errno == errno.EPIPE:
                logger.warning("Connection closed. Reset client and try again")
                if retry > 0:
                    self.reset_client()
                    await asyncio.sleep(1)
                    return await self.send_command(command, *args, timeout=timeout, retry=retry - 1)
                else:
                    logger.exception("Connection closed. Max retries reached")
                    raise
            else:
                logger.exception("Socket error")
                raise
        logger.info("rcon command executed: [%s], response: [%s] %s", command, response_type, response)
        return response.strip()
