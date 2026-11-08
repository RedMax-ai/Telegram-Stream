

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Mandatory Hugging Face Port
os.environ["PORT"] = "7860"

# Auto-configure config.env to ensure PORT = 7860 and clean BASE_URL
cfg_path = ROOT_DIR / "config.env"
if cfg_path.exists():
    try:
        text = cfg_path.read_text(encoding="utf-8")
        new_text = text.replace("PORT = 8085", "PORT = 7860").replace("PORT = 8080", "PORT = 7860")
        if new_text != text:
            cfg_path.write_text(new_text, encoding="utf-8")
            print("✅ Auto-set config.env to PORT = 7860")
    except Exception as e:
        print(f"Notice: {e}")

from bot import LOGGER
from bot.__main__ import start_services, stop_clients, loop

if __name__ == "__main__":
    try:
        LOGGER.info("🚀 Launching Telegram Stream CDN on Hugging Face Port 7860...")
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info("Service Stopping...")
    except Exception as e:
        LOGGER.error(f"Fatal error in app.py: {e}")
    finally:
        loop.run_until_complete(stop_clients())
        loop.stop()
