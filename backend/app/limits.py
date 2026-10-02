"""Daily counters that keep a public, unauthenticated app inside a budget."""
from .util import ApiError, epoch, today

_TWO_DAYS = 2 * 24 * 3600


def allow(store, scope, key, limit):
    """Count one event against today's allowance for (scope, key)."""
    return store.bump(f"RATE#{scope}#{key}", today(), limit, epoch() + _TWO_DAYS)


def require(store, scope, key, limit, message):
    if not allow(store, scope, key, limit):
        raise ApiError(429, message)
