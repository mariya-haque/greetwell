"""Runtime configuration, read once from the environment."""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


APP_NAME = "Greetwell"

# "aws" uses DynamoDB, S3 and Bedrock. "local" keeps everything in memory so the
# whole app runs on a laptop with no AWS account.
MODE = os.environ.get("APP_MODE", "aws")

TABLE_NAME = os.environ.get("TABLE_NAME", "")
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")
BUILDER_FUNCTION = os.environ.get("BUILDER_FUNCTION", "")

# CloudFront sends this header to the API origin. Requests without it did not
# come through the distribution and are rejected. Empty disables the check.
ORIGIN_SECRET = os.environ.get("ORIGIN_SECRET", "")

LLM_BACKEND = os.environ.get("LLM_BACKEND", "mock" if MODE == "local" else "bedrock")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-opus-5-5")
# Tried in order when the account has no access to MODEL_ID.
MODEL_FALLBACKS = _list("MODEL_FALLBACKS", "anthropic.claude-opus-4-8,anthropic.claude-haiku-4-5")
# Served instead when the primary model declines a request on policy grounds.
REFUSAL_FALLBACK_MODEL = os.environ.get("REFUSAL_FALLBACK_MODEL", "anthropic.claude-opus-4-8")

# Abuse and cost guards. The app is public and unauthenticated, so every path
# that reaches the model is capped.
BOTS_PER_IP_PER_DAY = _int("BOTS_PER_IP_PER_DAY", 6)
BOTS_GLOBAL_PER_DAY = _int("BOTS_GLOBAL_PER_DAY", 60)
REBUILDS_PER_BOT_PER_DAY = _int("REBUILDS_PER_BOT_PER_DAY", 5)
MSGS_PER_SESSION = _int("MSGS_PER_SESSION", 40)
MSGS_PER_BOT_PER_DAY = _int("MSGS_PER_BOT_PER_DAY", 300)
MSGS_PER_IP_PER_DAY = _int("MSGS_PER_IP_PER_DAY", 120)
LLM_CALLS_GLOBAL_PER_DAY = _int("LLM_CALLS_GLOBAL_PER_DAY", 600)

MAX_MESSAGE_CHARS = 1000
MAX_BODY_BYTES = 64 * 1024
HISTORY_MESSAGES = 16
SESSION_TTL_DAYS = 45

CRAWL_MAX_PAGES = _int("CRAWL_MAX_PAGES", 8)
CRAWL_PAGE_CHARS = 8000
CRAWL_SECONDS = 40

# Knowledge bases up to this size go into the prompt whole (and are cached).
# Larger ones are narrowed per question with lexical retrieval.
KB_WHOLE_CHARS = 30000
KB_RETRIEVAL_CHARS = 14000

# Test and local-dev escape hatch for the SSRF guard. Never set in AWS.
ALLOW_PRIVATE_FETCH = os.environ.get("ALLOW_PRIVATE_FETCH") == "1"
