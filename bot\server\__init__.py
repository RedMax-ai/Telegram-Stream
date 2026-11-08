from aiohttp.web import Application
from cryptography.fernet import Fernet
from aiohttp_session import setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from pathlib import Path

from bot.config import Telegram
from bot.helper.security import security_middleware
from bot.server.stream_routes import routes

# Static directory for SubtitlesOctopus and other assets
STATIC_DIR = Path(__file__).parent / "static"

async def web_server():
    web_app = Application(client_max_size=30000000, middlewares=[security_middleware])
    
    # Stable encrypted cookie storage with secure configuration
    fernet_key = Telegram.SECRET_KEY.encode() if isinstance(Telegram.SECRET_KEY, str) else Telegram.SECRET_KEY
    setup(web_app, EncryptedCookieStorage(
        Fernet(fernet_key),
        cookie_name="SURFTG_SESS",
        max_age=86400 * 7,
        httponly=True,
        samesite="Lax"
    ))
    
    web_app.add_routes(routes)
    
    # Add static file serving for SubtitlesOctopus WASM files
    if STATIC_DIR.exists():
        from aiohttp import web
        web_app.router.add_static('/static/', STATIC_DIR, follow_symlinks=True)
    
    return web_app
