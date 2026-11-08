import os
from os import getenv
from dotenv import load_dotenv
from pathlib import Path
from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parent.parent

if (ROOT_DIR / "config.env").exists():
    load_dotenv(ROOT_DIR / "config.env", override=True)
elif (ROOT_DIR / ".env").exists():
    load_dotenv(ROOT_DIR / ".env", override=True)

def _get_or_create_secret_key() -> str:
    key_from_env = getenv("SECRET_KEY", "")
    if key_from_env:
        return key_from_env
    secret_file = ROOT_DIR / ".secret.key"
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except Exception:
            pass
    new_key = Fernet.generate_key().decode()
    try:
        secret_file.write_text(new_key)
    except Exception:
        pass
    return new_key

class Telegram:
    API_ID = int(getenv("API_ID", "36419832") or "36419832")
    API_HASH = getenv("API_HASH", "df58e78317d56ea2ea0ff57af4d3e8ce")
    BOT_TOKEN = getenv("BOT_TOKEN", "9163410676:AAEdIeCpfjQc0CVaOvTQqidaEesRjtt7dm4")
    PORT = int(getenv("PORT", 7860) or 7860)
    SESSION_STRING = getenv("SESSION_STRING", "")
    BASE_URL = getenv("BASE_URL", "").rstrip('/')
    DATABASE_URL = getenv("DATABASE_URL", "mongodb+srv://ffxani531_db_user:Darkpaki123@cluster0.tmmbyls.mongodb.net/?retryWrites=true&w=majority")
    AUTH_CHANNEL = [channel.strip() for channel in getenv("AUTH_CHANNEL", "-1003904027623").split(",") if channel.strip()]
    BIN_CHANNEL = getenv("BIN_CHANNEL", "").strip() or (AUTH_CHANNEL[0] if AUTH_CHANNEL else "-1003904027623")
    THEME = getenv("THEME", "quartz").lower()
    USERNAME = getenv("USERNAME", "babyjhon")
    PASSWORD = getenv("PASSWORD", "jhonwick123123")
    ADMIN_USERNAME = getenv("ADMIN_USERNAME", "babyjhon")
    ADMIN_PASSWORD = getenv("ADMIN_PASSWORD", "jhonwick123123")
    SECRET_KEY = _get_or_create_secret_key()
    SLEEP_THRESHOLD = int(getenv('SLEEP_THRESHOLD', '60') or 60)
    WORKERS = int(getenv('WORKERS', '10') or 10)
    MULTI_CLIENT = getenv('MULTI_CLIENT', 'False')
    HIDE_CHANNEL = getenv('HIDE_CHANNEL', 'False')
    # Stream Security & Exclusive Access Control
    STREAM_AUTH_KEY = getenv("STREAM_AUTH_KEY", "").strip()
    ALLOWED_DOMAINS = [d.strip().lower() for d in getenv("ALLOWED_DOMAINS", "").split(",") if d.strip()]

    # Media Cache Settings
    CACHE_ENABLED = getenv('CACHE_ENABLED', 'True').lower() == 'true'
    _raw_cache_dir = getenv('CACHE_DIR', 'media_cache')
    CACHE_DIR = str(Path(_raw_cache_dir) if Path(_raw_cache_dir).is_absolute() else (ROOT_DIR / _raw_cache_dir))
    CACHE_MAX_SIZE_GB = int(getenv('CACHE_MAX_SIZE_GB', '150') or 150)
