#!/usr/bin/env python3
"""
24/7 Persistent Supervisor & Watchdog for Telegram-Stream CDN.
Ensures zero-downtime streaming, auto-restarts on crash, and monitors health.
"""
import sys
import os
import time
import subprocess
import signal
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
os.chdir(ROOT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WATCHDOG] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("watchdog")

running = True

def handle_signal(sig, frame):
    global running
    logger.info("Shutdown signal received. Stopping services gracefully...")
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def main():
    global running
    logger.info("Starting Telegram-Stream 24/7 Watchdog Supervisor...")
    logger.info(f"Working Directory: {ROOT_DIR}")

    python_executable = sys.executable
    consecutive_failures = 0

    while running:
        try:
            logger.info("Launching Telegram-Stream bot server (`python -m bot`)...")
            start_time = time.time()

            # Launch bot process
            proc = subprocess.Popen(
                [python_executable, "-m", "bot"],
                cwd=str(ROOT_DIR),
                stdout=None,
                stderr=None
            )

            # Monitor process
            while running:
                ret = proc.poll()
                if ret is not None:
                    # Process exited
                    runtime = time.time() - start_time
                    logger.warning(f"Process exited with code {ret} after {runtime:.1f}s.")
                    if runtime < 10:
                        consecutive_failures += 1
                        backoff = min(2 ** consecutive_failures, 30)
                        logger.warning(f"Fast crash detected ({consecutive_failures}). Backing off for {backoff}s...")
                        time.sleep(backoff)
                    else:
                        consecutive_failures = 0
                        time.sleep(2)
                    break
                time.sleep(1)

        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            time.sleep(3)

    # Clean termination
    if 'proc' in locals() and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    logger.info("Watchdog supervisor stopped cleanly.")

if __name__ == "__main__":
    main()

