"""HTTP API. One Lambda behind API Gateway, fronted by CloudFront at /api/*."""
import base64
import json
import re
import traceback

from . import bots, chat, config, crawl, limits, services
from .util import ID_RE, ApiError, clip, hash_key, keys_match, new_id, now_iso

CORS = {
    # The widget runs on other people's websites, so the API is callable from
    # any origin. Owner endpoints are protected by the admin key, not by origin.
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type,x-admin-key",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Max-Age": "86400",
}
LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")
BOT = r"(?P<bot>[A-Za-z0-9_-]{4,40})"
ITEM = r"(?P<item>[A-Za-z0-9_-]{4,64})"


class Request:
    def __init__(self, event):
        http = event.get("requestContext", {}).get("http", {})
        self.method = http.get("method", "GET").upper()
        self.path = event.get("rawPath", "/")
        self.headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        self.ip = self._client_ip(http)
        self._raw = event.get("body") or ""
        self._encoded = bool(event.get("isBase64Encoded"))
        self._json = None

    def _client_ip(self, http):
        # CloudFront reports the real viewer as "ip:port". The header is only
        # trusted because direct calls that bypass CloudFront are rejected.
        viewer = self.headers.get("cloudfront-viewer-address")
        if viewer:
            return viewer.rsplit(":", 1)[0].strip("[]")
        return http.get("sourceIp", "unknown")

    @property
    def json(self):
        if self._json is None:
            raw = self._raw
            if self._encoded:
                raw = base64.b64decode(raw).decode("utf-8", "replace")
            if len(raw) > config.MAX_BODY_BYTES:
                raise ApiError(413, "That request is too large.")
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                raise ApiError(400, "The request body isn't valid JSON.")
            if not isinstance(parsed, dict):
                raise ApiError(400, "The request body must be a JSON object.")
            self._json = parsed
        return self._json


def respond(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store", **CORS},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _load_bot(store, bot_id):
    bot = bots.get(store, bot_id)
    if bot is None:
        raise ApiError(404, "That assistant doesn't exist.")
    return bot


def _owned_bot(store, req, bot_id):
    bot = _load_bot(store, bot_id)
    if not keys_match(req.headers.get("x-admin-key", ""), bot.get("keyHash", "")):
        raise ApiError(403, "That dashboard link isn't valid for this assistant.")
    return bot


# ---------------------------------------------------------------- routes

def health(store, req):
    return 200, {"ok": True, "app": config.APP_NAME, "time": now_iso()}


def create_bot(store, req):
    body = req.json
    url, text = clip(body.get("url"), 500), clip(body.get("text"), 8000)
    if url:
        try:
            url = crawl.normalize_url(url)
        except crawl.FetchError as err:
            raise ApiError(400, str(err))
        text = ""
    elif len(text) < 80:
        raise ApiError(400, "Enter your website address, or describe your business in at least a few sentences.")
    limits.require(store, "bots-ip", req.ip, config.BOTS_PER_IP_PER_DAY,
                   "You've created several assistants today. Please try again tomorrow.")
    limits.require(store, "bots", "global", config.BOTS_GLOBAL_PER_DAY,
                   "We've hit today's limit for new assistants. Please try again tomorrow.")
    bot_id, admin_key = new_id(9), new_id(24)
    store.put(bots.new_bot(bot_id, hash_key(admin_key), url=url, text=text))
    services.start_build(bot_id)
    return 202, {"botId": bot_id, "adminKey": admin_key, "status": "building"}


def bot_public(store, req, bot):
    return 200, bots.public_view(_load_bot(store, bot))


def bot_admin(store, req, bot):
    return 200, bots.admin_view(_owned_bot(store, req, bot))


def bot_update(store, req, bot):
    record = _owned_bot(store, req, bot)
    try:
        sets = bots.settings_from(req.json)
    except (ValueError, crawl.FetchError) as err:
        raise ApiError(400, str(err))
    if not sets:
        raise ApiError(400, "Nothing to update.")
    sets["customized"] = sorted(set(record.get("customized") or []) | set(sets))
    sets["updatedAt"] = now_iso()
    return 200, bots.admin_view(store.update(bots.pk(bot), "META", sets=sets))


def bot_delete(store, req, bot):
    _owned_bot(store, req, bot)
    bots.delete(store, bot)
    return 200, {"deleted": True}


def bot_rebuild(store, req, bot):
    record = _owned_bot(store, req, bot)
    if record.get("sourceType") != "url":
        raise ApiError(400, "This assistant was built from a description, so there is no site to re-read.")
    if record.get("status") == "building" or record.get("rebuilding"):
        raise ApiError(409, "This assistant is already being updated.")
    limits.require(store, "rebuild", bot, config.REBUILDS_PER_BOT_PER_DAY,
                   "This assistant has been refreshed several times today. Please try again tomorrow.")
    store.update(bots.pk(bot), "META", sets={"rebuilding": True, "stage": "queued", "error": ""})
    services.start_build(bot)
    return 202, {"status": "rebuilding"}


def webhook_test(store, req, bot):
    record = _owned_bot(store, req, bot)
    if not record.get("webhookUrl"):
        raise ApiError(400, "Save a webhook address first.")
    limits.require(store, "webhook-test", bot, 20, "Too many test requests today.")
    sample = {
        "id": "test", "name": "Test Lead", "email": "test@example.com", "need": "This is a test from your dashboard.",
        "intent": "high", "score": 80, "label": "hot", "status": "new", "createdAt": now_iso(),
    }
    try:
        status = chat.send_webhook(record["webhookUrl"], chat.webhook_payload(record, sample))
    except crawl.FetchError as err:
        raise ApiError(502, f"The webhook couldn't be reached: {err}")
    return 200, {"status": status, "ok": 200 <= status < 300}


def leads_list(store, req, bot):
    _owned_bot(store, req, bot)
    rows = store.query(bots.pk(bot), "LEAD#", limit=500)
    rows.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
    return 200, {"leads": [{k: v for k, v in r.items() if k not in ("pk", "sk")} for r in rows]}


def lead_update(store, req, bot, item):
    _owned_bot(store, req, bot)
    body, sets = req.json, {}
    if "status" in body:
        if body["status"] not in LEAD_STATUSES:
            raise ApiError(400, "Unknown lead status.")
        sets["status"] = body["status"]
    if "ownerNote" in body:
        sets["ownerNote"] = clip(body["ownerNote"], 1000)
    if not sets:
        raise ApiError(400, "Nothing to update.")
    sets["updatedAt"] = now_iso()
    updated = store.update(bots.pk(bot), f"LEAD#{item}", sets=sets)
    if updated is None:
        raise ApiError(404, "That lead doesn't exist.")
    return 200, {k: v for k, v in updated.items() if k not in ("pk", "sk")}


def sessions_list(store, req, bot):
    _owned_bot(store, req, bot)
    rows = store.query(bots.pk(bot), "SESS#", limit=300)
    rows.sort(key=lambda r: r.get("updatedAt", ""), reverse=True)
    fields = ("id", "count", "createdAt", "updatedAt", "preview", "hasLead", "pageUrl")
    return 200, {"sessions": [{k: r.get(k) for k in fields} for r in rows[:100]]}


def session_get(store, req, bot, item):
    _owned_bot(store, req, bot)
    session = store.get(bots.pk(bot), f"SESS#{item}")
    if session is None:
        raise ApiError(404, "That conversation is no longer stored.")
    return 200, {k: v for k, v in session.items() if k not in ("pk", "sk", "ttl")}


def chat_message(store, req):
    body = req.json
    bot_id, session_id = clip(body.get("botId"), 40), clip(body.get("sessionId"), 64)
    message = clip(body.get("message"), config.MAX_MESSAGE_CHARS + 1)
    if not ID_RE.match(bot_id) or not re.match(r"^[A-Za-z0-9_-]{16,64}$", session_id):
        raise ApiError(400, "Missing or malformed botId or sessionId.")
    if not message:
        raise ApiError(400, "Type a message first.")
    if len(message) > config.MAX_MESSAGE_CHARS:
        raise ApiError(400, f"Please keep messages under {config.MAX_MESSAGE_CHARS} characters.")
    bot = _load_bot(store, bot_id)
    if not bot.get("kbVersion"):
        raise ApiError(409, "This assistant is still being set up. Try again in a minute.")
    return 200, chat.reply(store, services.get_llm(), bot, session_id, message, body.get("pageUrl"), req.ip)


ROUTES = [
    ("GET", rf"^/api/health$", health),
    ("POST", rf"^/api/bots$", create_bot),
    ("POST", rf"^/api/chat$", chat_message),
    ("GET", rf"^/api/bots/{BOT}/public$", bot_public),
    ("GET", rf"^/api/bots/{BOT}$", bot_admin),
    ("PATCH", rf"^/api/bots/{BOT}$", bot_update),
    ("DELETE", rf"^/api/bots/{BOT}$", bot_delete),
    ("POST", rf"^/api/bots/{BOT}/rebuild$", bot_rebuild),
    ("POST", rf"^/api/bots/{BOT}/webhook-test$", webhook_test),
    ("GET", rf"^/api/bots/{BOT}/leads$", leads_list),
    ("PATCH", rf"^/api/bots/{BOT}/leads/{ITEM}$", lead_update),
    ("GET", rf"^/api/bots/{BOT}/sessions$", sessions_list),
    ("GET", rf"^/api/bots/{BOT}/sessions/{ITEM}$", session_get),
]
ROUTES = [(method, re.compile(pattern), fn) for method, pattern, fn in ROUTES]


def handler(event, context=None):
    try:
        req = Request(event)
        if req.method == "OPTIONS":
            return {"statusCode": 204, "headers": CORS, "body": ""}
        if config.ORIGIN_SECRET and req.headers.get("x-origin-verify") != config.ORIGIN_SECRET:
            raise ApiError(403, "Requests must come through the site.")
        path = req.path.rstrip("/") or "/"
        known_path = False
        for method, pattern, fn in ROUTES:
            match = pattern.match(path)
            if not match:
                continue
            known_path = True
            if method == req.method:
                status, body = fn(services.get_store(), req, **match.groupdict())
                return respond(status, body)
        raise ApiError(405 if known_path else 404, "Method not allowed." if known_path else "Not found.")
    except ApiError as err:
        return respond(err.status, {"error": err.message})
    except Exception:
        traceback.print_exc()
        return respond(500, {"error": "Something went wrong on our side. Please try again."})
