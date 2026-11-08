import sys
import asyncio

if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from asyncio import sleep as asleep, gather
from traceback import format_exc

from aiohttp import web
from pyrogram import idle

from bot import __version__, LOGGER
from bot.config import Telegram
from bot.server import web_server
from bot.telegram import StreamBot, UserBot
from bot.telegram.clients import initialize_clients
from bot.helper.media_cache import media_cache
from bot.helper.subtitle_cache import subtitle_cache

LOGGER.info(f"Media cache module loaded, enabled={media_cache.enabled}")

async def start_services():
    LOGGER.info(f'Initializing Surf-TG v-{__version__}')
    
    # 1. START WEB SERVER FIRST (Instant port binding for Render & Cloud zero-downtime)
    LOGGER.info('Starting Web Server immediately on port %s...', Telegram.PORT)
    server = web.AppRunner(await web_server())
    await server.setup()
    await web.TCPSite(server, '0.0.0.0', Telegram.PORT).start()
    LOGGER.info("Surf Web Server Online & Listening on 0.0.0.0:%s !", Telegram.PORT)
    
    # 2. Synchronize Pyrogram event loops with running asyncio loop
    active_loop = asyncio.get_running_loop()
    for client in (StreamBot, UserBot):
        if client:
            client.loop = active_loop
            if hasattr(client, 'dispatcher') and client.dispatcher:
                client.dispatcher.loop = active_loop

    # 3. Asynchronously initialize Database Indexes & Telegram Clients in Background
    async def init_backend():
        try:
            from bot.helper.database import Database
            await Database().create_indexes()
            LOGGER.info("Database indexes ready.")
        except Exception as e:
            LOGGER.warning(f"Database index creation error: {e}")
            
        bot_connected = False
        if Telegram.BOT_TOKEN and Telegram.API_ID and Telegram.API_HASH:
            try:
                LOGGER.info("Connecting Telegram Bot client...")
                await StreamBot.start()
                StreamBot.username = StreamBot.me.username
                LOGGER.info(f"Bot Client connected: [@{StreamBot.username}]")
                bot_connected = True
                if len(Telegram.SESSION_STRING) != 0:
                    await UserBot.start()
                    UserBot.username = UserBot.me.username or UserBot.me.first_name or UserBot.me.id
                    LOGGER.info(f"User Client connected: {UserBot.username}")
            except Exception as e:
                LOGGER.warning(f"Telegram client startup skipped/failed: {e}")
        else:
            LOGGER.info("Telegram credentials not configured. Running in Web/Standalone Mode.")
        
        if bot_connected:
            LOGGER.info("Initializing Multi Clients...")
            try:
                await initialize_clients()
            except Exception as e:
                LOGGER.warning(f"Multi-client init error: {e}")
                
        # Start cache cleanup background tasks
        if media_cache.enabled:
            loop.create_task(cache_cleanup_task())
            LOGGER.info(f"Media cache enabled: max {Telegram.CACHE_MAX_SIZE_GB}GB at {media_cache.cache_dir}")
        else:
            LOGGER.info("Media cache is disabled")
            
        loop.create_task(subtitle_cache.periodic_cleanup())
        LOGGER.info("Subtitle cache cleanup task started")
        
        # 4. Anti-Sleep 24/7 Keep-Alive Pinger (Prevents free tier spin down)
        loop.create_task(keep_alive_task())

    loop.create_task(init_backend())
    
    LOGGER.info("Surf-TG Started Revolving !")
    await idle()


async def keep_alive_task():
    """Pings server every 10 minutes to prevent cloud sleep / spin down."""
    import aiohttp
    LOGGER.info("24/7 Self-Keepalive task activated (Anti-Sleep)")
    while True:
        await asleep(10 * 60) # 10 minutes
        try:
            target_url = f"http://127.0.0.1:{Telegram.PORT}/favicon.ico"
            async with aiohttp.ClientSession() as session:
                async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    LOGGER.debug(f"Keepalive ping response: {resp.status}")
        except Exception as e:
            LOGGER.debug(f"Keepalive ping note: {e}")


async def cache_cleanup_task():
    """Background task to cleanup cache every 30 minutes."""
    while True:
        await asleep(30 * 60)  # 30 minutes
        try:
            LOGGER.info("Running scheduled cache cleanup...")
            media_cache.cleanup_expired()
            LOGGER.info("Scheduled cache cleanup completed")
        except Exception as e:
            LOGGER.error(f"Error in cache cleanup task: {e}")


if __name__ == "__main__":
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info("---------------- Service Stopped ----------------")
    except Exception as e:
        LOGGER.critical(format_exc())
        LOGGER.critical("-------------- Service Terminated --------------")
