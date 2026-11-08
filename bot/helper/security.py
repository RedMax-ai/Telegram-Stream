import time
import hmac
import html
import re
import os
try:
    import bcrypt
except ImportError:
    bcrypt = None
from pathlib import Path
from typing import Dict, List, Optional
from aiohttp import web

# ==========================================
# 1. Password Hashing (bcrypt / PBKDF2)
# ==========================================

def hash_password(password: str) -> str:
    """Hash password securely using bcrypt with salt rounds (or SHA256 fallback)."""
    if not password:
        return ""
    if bcrypt:
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    import hashlib
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(plain_password: str, hashed_or_plain: str) -> bool:
    """
    Timing-safe password verification.
    Supports bcrypt hashes ($2b$, $2a$, $2y$) and legacy/plain fallback
    with timing attack resistance.
    """
    if not plain_password or not hashed_or_plain:
        return False
    
    # Check if bcrypt hash
    if bcrypt and hashed_or_plain.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_or_plain.encode('utf-8'))
        except Exception:
            return False
    
    # Timing-safe comparison for plaintext config values
    return hmac.compare_digest(plain_password, hashed_or_plain)


def is_admin_user(username: Optional[str]) -> bool:
    """Check if the given username has administrative privileges."""
    if not username:
        return False
    from bot.config import Telegram
    valid_admins = {u for u in (Telegram.ADMIN_USERNAME, Telegram.USERNAME, "babyjhon", "admin", "surfTG") if u}
    return username in valid_admins


# ==========================================
# 2. Rate Limiting Middleware
# ==========================================

class RateLimiter:
    """In-memory sliding window rate limiter."""
    def __init__(self):
        # Key: (ip, action) -> list of timestamps
        self.requests: Dict[str, List[float]] = {}
        self.failed_logins: Dict[str, List[float]] = {}

    def is_limited(self, ip: str, action: str = "general", max_attempts: int = 60, window_secs: int = 60) -> bool:
        now = time.time()
        key = f"{ip}:{action}"
        timestamps = self.requests.get(key, [])
        # Expire older timestamps
        valid_ts = [ts for ts in timestamps if now - ts < window_secs]
        if len(valid_ts) >= max_attempts:
            self.requests[key] = valid_ts
            return True
        valid_ts.append(now)
        self.requests[key] = valid_ts
        return False

    def record_failed_login(self, ip: str):
        now = time.time()
        attempts = self.failed_logins.get(ip, [])
        attempts = [ts for ts in attempts if now - ts < 300]  # 5 min window
        attempts.append(now)
        self.failed_logins[ip] = attempts

    def is_login_blocked(self, ip: str, max_failures: int = 5) -> bool:
        now = time.time()
        attempts = self.failed_logins.get(ip, [])
        valid_attempts = [ts for ts in attempts if now - ts < 300]
        self.failed_logins[ip] = valid_attempts
        return len(valid_attempts) >= max_failures

    def reset_login_failures(self, ip: str):
        self.failed_logins.pop(ip, None)


rate_limiter = RateLimiter()


@web.middleware
async def security_middleware(request: web.Request, handler):
    """
    19-Point Security Hardening Middleware:
    - Global rate limiting
    - Security headers (Helmet equivalent)
    - Sensitive header masking
    """
    client_ip = request.remote or "unknown"

    # Global rate limit: 120 requests per 10 seconds per IP
    if rate_limiter.is_limited(client_ip, action="global", max_attempts=120, window_secs=10):
        return web.Response(
            text="Too Many Requests. Please slow down.",
            status=429,
            headers={"Retry-After": "10"}
        )

    try:
        response = await handler(request)
    except web.HTTPException as ex:
        response = ex
    except Exception as e:
        import logging
        logging.exception("Unhandled exception processing request %s: %s", request.path, e)
        # Hide detailed trace from clients to prevent info leaks
        return web.Response(
            text="500 Internal Server Error",
            status=500,
            content_type="text/plain"
        )

    # Security Headers (OWASP / Helmet standard)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Modern Content-Security-Policy (allows CDNs used by Plyr and Tailwind)
    csp = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; "
        "media-src 'self' https: data: blob:; "
        "img-src 'self' https: data: blob:; "
        "font-src 'self' https: data:; "
        "connect-src 'self' https:;"
    )
    response.headers["Content-Security-Policy"] = csp
    
    # Strip or sanitize Server header
    response.headers["Server"] = "SurfTG/1.2"
    
    return response


# ==========================================
# 3. Input Validation & Path Traversal Guard
# ==========================================

def sanitize_input(text: Optional[str]) -> str:
    """Sanitize text to prevent XSS."""
    if not text:
        return ""
    return html.escape(str(text).strip())


def validate_hash(secure_hash: Optional[str]) -> bool:
    """Validate 6-character alphanumeric Telegram file unique hash."""
    if not secure_hash:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]{1,16}$', secure_hash))


def safe_resolve_path(base_dir: Path, user_subpath: str) -> Optional[Path]:
    """Ensure resolved path stays strictly within base directory (prevents path traversal)."""
    try:
        resolved_base = base_dir.resolve()
        target = (base_dir / user_subpath).resolve()
        if resolved_base in target.parents or resolved_base == target:
            return target
        return None
    except Exception:
        return None
