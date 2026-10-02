import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ApiError(Exception):
    """An error with an HTTP status and a message that is safe to show."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def epoch():
    return int(time.time())


def new_id(nbytes=9):
    return secrets.token_urlsafe(nbytes)


def hash_key(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def keys_match(key, key_hash):
    if not key or not key_hash:
        return False
    return hmac.compare_digest(hash_key(key), key_hash)


def clip(value, limit):
    """Coerce to a single trimmed string of at most `limit` characters."""
    if value is None:
        return ""
    text = _CONTROL.sub("", str(value)).strip()
    return text[:limit]


def clip_list(values, max_items, item_limit):
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for value in values:
        text = clip(value, item_limit)
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def plain(obj):
    """Turn DynamoDB's Decimals back into ints and floats, recursively."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    return obj
