import os
import json
from pathlib import Path

from bot import LOGGER

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def rm_cache(channel=None):
    LOGGER.info("Cleaning Cache...")
    try:
        for file in os.listdir(CACHE_DIR):
            try:
                if file.endswith(".json") and (channel and file.startswith(channel) or not channel):
                    os.remove(CACHE_DIR / file)
                    LOGGER.info(f"Removed {file}")
            except Exception as e:
                LOGGER.error(e)
    except Exception as e:
        LOGGER.error(e)


def get_cache(channel, page):
    file_path = CACHE_DIR / f"{channel}-{page}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)["posts"]
    else:
        return None


def save_cache(channel, cache, page):
    file_path = CACHE_DIR / f"{channel}-{page}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)