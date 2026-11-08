import asyncio
from pyrogram import Client
from bot.config import Telegram

def sync_client_loop(client):
    try:
        active_loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            active_loop = asyncio.get_event_loop()
        except RuntimeError:
            active_loop = None
    if active_loop and client:
        client.loop = active_loop
        if hasattr(client, 'dispatcher') and client.dispatcher:
            client.dispatcher.loop = active_loop

plugins = {"root": "bot/telegram/plugins"}

StreamBot = Client(
    name='bot',
    api_id=Telegram.API_ID,
    api_hash=Telegram.API_HASH,
    bot_token=Telegram.BOT_TOKEN,
    in_memory=True,
    plugins=plugins,
    sleep_threshold=Telegram.SLEEP_THRESHOLD,
    workers=Telegram.WORKERS,
    ipv6=False,
    max_concurrent_transmissions=1000
)
UserBot = Client(
    name='user',
    api_id=Telegram.API_ID,
    api_hash=Telegram.API_HASH,
    session_string=Telegram.SESSION_STRING,
    sleep_threshold=Telegram.SLEEP_THRESHOLD,
    no_updates=True,
    in_memory=True,
)

multi_clients = {}
work_loads = {}
