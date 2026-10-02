"""Background worker Lambda: reads a site and builds the assistant.

Invoked asynchronously by the API so the HTTP request returns at once and the
dashboard polls for progress. Also seeds the demo assistant shown on the
landing page.
"""
from . import bots, services
from .demo import DEMO_BOT_ID, DEMO_TEXT


def handler(event, context=None):
    store, llm = services.get_store(), services.get_llm()
    action = event.get("action", "build")
    if action == "seed_demo":
        existing = bots.get(store, DEMO_BOT_ID)
        # The demo has no admin key, so nobody can open a dashboard for it.
        bot = bots.new_bot(DEMO_BOT_ID, "", text=DEMO_TEXT)
        if existing:
            # Keep the counters, and keep the live demo answering while it re-learns.
            for field in ("conversations", "messages", "leads", "createdAt", "kbVersion"):
                bot[field] = existing.get(field, bot[field])
            if bot["kbVersion"]:
                bot["status"] = "ready"
        store.put(bot)
        bots.build(store, llm, DEMO_BOT_ID)
        ready = bots.get(store, DEMO_BOT_ID)
        return {
            "botId": DEMO_BOT_ID,
            "status": ready["status"],
            "name": ready.get("name"),
            "profileFromModel": ready.get("profileFromModel"),
            "model": getattr(llm, "model", ""),
            "error": ready.get("error", ""),
        }
    bots.build(store, llm, event["botId"])
    return {"botId": event["botId"]}
