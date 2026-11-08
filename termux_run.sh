#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Surf-TG 24/7 Mobile Stream Server Auto-Runner for Android Termux
# ==============================================================================

echo "=========================================================="
echo "    🚀 STARTING TELEGRAM STREAM SERVER ON ANDROID TERMUX  "
echo "=========================================================="

# 1. Prevent Android from killing Termux when screen is turned off
termux-wake-lock 2>/dev/null || true

# 2. Check & Install Python and dependencies
if ! command -v python &> /dev/null; then
    echo "[*] Installing Python, Git, and build tools..."
    pkg update -y
    pkg install -y python git clang libffi openssl make ffmpeg curl
    pip install --upgrade pip setuptools wheel
fi

# 3. Create config.env if missing
if [ ! -f "config.env" ]; then
    echo "[*] Creating production config.env..."
    cat << 'EOF' > config.env
API_ID = "36419832"
API_HASH = "df58e78317d56ea2ea0ff57af4d3e8ce"
BOT_TOKEN = "9163410676:AAEdIeCpfjQc0CVaOvTQqidaEesRjtt7dm4"
AUTH_CHANNEL = "-1003904027623"
DATABASE_URL = ""
PORT = 8085
BASE_URL = ""
USERNAME = "babyjhon"
PASSWORD = "jhonwick123123"
ADMIN_USERNAME = "babyjhon"
ADMIN_PASSWORD = "jhonwick123123"
STREAM_AUTH_KEY = ""
ALLOWED_DOMAINS = ""
CACHE_ENABLED = True
CACHE_DIR = "media_cache"
CACHE_MAX_SIZE_GB = 5
SLEEP_THRESHOLD = 60
WORKERS = 10
MULTI_CLIENT = False
HIDE_CHANNEL = False
EOF
fi

# 4. Install dependencies (Pre-compiled packages for Termux)
echo "[*] Verifying Python dependencies..."
pkg install -y python-cryptography 2>/dev/null || true
pip install aiofiles aiohttp aiohttp_session pyrofork python-dotenv bcrypt aiosqlite pymongo motor 2>/dev/null || pip install -r requirements.txt

# 5. Download Cloudflare Tunnel binary for Android ARM64 if missing
if [ ! -f "cloudflared" ]; then
    echo "[*] Downloading Cloudflare Tunnel for Android..."
    curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
    chmod +x cloudflared
fi

echo "=========================================================="
echo "    ✅ SETUP COMPLETE! STARTING 24/7 STREAM SERVER        "
echo "=========================================================="

# Kill any existing zombie processes
pkill -9 -f "python -m bot" 2>/dev/null || true
pkill -9 -f "cloudflared" 2>/dev/null || true

# Start Telegram Bot in background
python -m bot &
BOT_PID=$!

sleep 4

# Start Cloudflare Tunnel
echo "[*] Starting Cloudflare Public CDN Tunnel..."
./cloudflared tunnel --url http://127.0.0.1:8085

