# A simple Telegram bot for Minecraft players

A simple Telegram bot for:
1. Executing Minecraft commands within Telegram chat;
2. Chat with players in Minecraft server: send messages to players in the server and also receive their messages;
3. Backuping up the world to Telegram chat.

## Setup

Enable RCON in Minecraft server and clone this repo.

1. copy `config.template.yml` to `config.prod.yml`
2. fill in blanks under `telegram` and `mc-server` sections
3. install dependencies and run with `IS_PROD=1 python3 main.py`
