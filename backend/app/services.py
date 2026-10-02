"""Process-wide singletons and the hand-off to the background builder."""
import json
import threading

from . import config
from .llm import get_llm  # noqa: F401  (re-exported)
from .store import AwsStore, MemoryStore

_store = None
_lambda = None


def get_store():
    global _store
    if _store is None:
        _store = MemoryStore() if config.MODE == "local" else AwsStore()
    return _store


def start_build(bot_id):
    """Run the crawl-and-learn job without holding the HTTP request open."""
    if config.MODE == "local":
        from . import bots

        threading.Thread(target=bots.build, args=(get_store(), get_llm(), bot_id), daemon=True).start()
        return
    global _lambda
    if _lambda is None:
        import boto3

        _lambda = boto3.client("lambda")
    _lambda.invoke(
        FunctionName=config.BUILDER_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps({"action": "build", "botId": bot_id}).encode("utf-8"),
    )
