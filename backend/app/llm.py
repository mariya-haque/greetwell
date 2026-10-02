"""The model behind the assistant.

`BedrockLLM` calls Claude on Amazon Bedrock through the Anthropic SDK, signing
requests with the Lambda's IAM role. `MockLLM` is a small deterministic
stand-in so the app and its tests run with no AWS account.
"""
import json
import re

from . import config

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A 400 that means "this account can't use this model" rather than "bad request".
_MODEL_UNAVAILABLE = re.compile(
    r"model (identifier|id) is invalid|access to (the|this) model|model.{0,40}not (found|available|enabled|accessible)",
    re.I,
)


class LLMError(Exception):
    """The model could not be reached or did not answer."""


class LLMResult:
    def __init__(self, text="", tool_calls=None, content=None, stop_reason="end_turn", model="", usage=None):
        self.text = text
        self.tool_calls = tool_calls or []
        # The assistant turn as the API needs it replayed when tool results
        # are sent back: every block, unmodified.
        self.content = content if content is not None else []
        self.stop_reason = stop_reason
        self.model = model
        self.usage = usage or {}


class BedrockLLM:
    def __init__(self):
        import anthropic
        from anthropic import AnthropicBedrockMantle, BetaFallbackState, BetaRefusalFallbackMiddleware

        self._sdk = anthropic
        self._state_cls = BetaFallbackState
        self._models = [config.MODEL_ID] + [m for m in config.MODEL_FALLBACKS if m != config.MODEL_ID]
        self._index = 0
        self._client = AnthropicBedrockMantle(aws_region=config.BEDROCK_REGION)
        # Bedrock has no server-side refusal fallback, so the SDK middleware
        # retries a policy decline on a second model client-side.
        self._refusal_model = config.REFUSAL_FALLBACK_MODEL
        self._fallback_client = None
        if self._refusal_model:
            self._fallback_client = AnthropicBedrockMantle(
                aws_region=config.BEDROCK_REGION,
                middleware=[BetaRefusalFallbackMiddleware([{"model": self._refusal_model}])],
            )

    @property
    def model(self):
        return self._models[self._index]

    def _request(self, model, system, messages, tools, max_tokens, effort, timeout, retries):
        kwargs = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        # Haiku 4.5 rejects the effort parameter; every other current model takes it.
        if "haiku" not in model:
            kwargs["output_config"] = {"effort": effort}
        if self._fallback_client is not None and model != self._refusal_model:
            client = self._fallback_client.with_options(timeout=timeout, max_retries=retries)
            try:
                with self._state_cls():
                    return client.beta.messages.create(**kwargs)
            except self._sdk.BadRequestError as err:
                if _MODEL_UNAVAILABLE.search(str(err)):
                    raise
                # If this account's endpoint rejects the fallback beta, carry on without it.
                print(json.dumps({"event": "refusal_fallback_disabled", "error": str(err)[:300]}))
                self._fallback_client = None
        client = self._client.with_options(timeout=timeout, max_retries=retries)
        return client.messages.create(**kwargs)

    def complete(self, system, messages, tools=None, max_tokens=4096, effort="low", timeout=22, retries=0):
        sdk = self._sdk
        while True:
            model = self.model
            try:
                message = self._request(model, system, messages, tools, max_tokens, effort, timeout, retries)
                break
            except (sdk.PermissionDeniedError, sdk.NotFoundError, sdk.BadRequestError) as err:
                if isinstance(err, sdk.BadRequestError) and not _MODEL_UNAVAILABLE.search(str(err)):
                    raise LLMError(f"Model error 400: {str(err)[:300]}") from err
                # No access to this model on this account: move down the chain and stay there.
                if self._index + 1 >= len(self._models):
                    raise LLMError(f"No configured model is available: {err}") from err
                print(json.dumps({"event": "model_unavailable", "model": model, "error": str(err)[:300]}))
                self._index += 1
            except sdk.RateLimitError as err:
                raise LLMError("The model is busy.") from err
            except sdk.APIStatusError as err:
                raise LLMError(f"Model error {err.status_code}: {str(err)[:300]}") from err
            except sdk.APIConnectionError as err:
                raise LLMError("The model could not be reached.") from err

        text_parts, tool_calls, content = [], [], []
        for block in message.content:
            if block.type == "fallback":
                continue
            content.append(block)
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input or {}})
        usage = message.usage
        stats = {
            "input": getattr(usage, "input_tokens", 0) or 0,
            "output": getattr(usage, "output_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        print(json.dumps({"event": "llm", "model": message.model, "stop": message.stop_reason, **stats}))
        return LLMResult(
            text="\n".join(p.strip() for p in text_parts if p.strip()),
            tool_calls=tool_calls,
            content=content,
            stop_reason=message.stop_reason,
            model=message.model,
            usage=stats,
        )


class MockLLM:
    """Rule-based stand-in. It exercises the same tool-call paths as the real model."""

    model = "mock"

    def complete(self, system, messages, tools=None, **_):
        names = {tool["name"] for tool in tools or []}
        last = messages[-1]["content"]

        if "save_profile" in names:
            if isinstance(last, list):
                return LLMResult(text="Saved.")
            return self._tool("save_profile", self._profile(last))

        if isinstance(last, list):  # tool results coming back
            return LLMResult(text="Thanks, I've passed that to the team. Anything else I can help with?")

        email = _EMAIL.search(last)
        if email and "save_lead" in names:
            return self._tool(
                "save_lead",
                {"email": email.group(0), "need": last[:200], "intent": "high"},
                text="Thanks! I've passed your details to the team and they'll be in touch.",
            )
        return LLMResult(text=self._answer(system, last))

    @staticmethod
    def _tool(name, payload, text=""):
        call = {"id": "mock_tool_1", "name": name, "input": payload}
        content = [{"type": "tool_use", **call}]
        if text:
            content.insert(0, {"type": "text", "text": text})
        return LLMResult(text=text, tool_calls=[call], content=content, stop_reason="tool_use", model="mock")

    @staticmethod
    def _profile(prompt):
        title = re.search(r"^Site title: (.+)$", prompt, re.M)
        name = (title.group(1) if title else "This business").split("|")[0].split(" - ")[0].strip()[:60]
        return {
            "business_name": name or "This business",
            "one_liner": f"{name} helps its customers get things done.",
            "summary": f"{name} is a business with a public website.",
            "offerings": ["Products and services described on the website"],
            "ideal_customers": "People looking for what the business offers.",
            "faqs": [{"q": f"What does {name} do?", "a": "See the website for details."}],
            "qualifying_questions": ["What are you looking for help with?", "When do you need it?"],
            "greeting": f"Hi! I'm the {name} assistant. How can I help?",
            "starter_prompts": ["What do you offer?", "How much does it cost?", "How do I get started?"],
            "language": "en",
        }

    @staticmethod
    def _answer(system, question):
        joined = "\n".join(block["text"] for block in system)
        material = joined.split("<reference_material>")[-1].split("</reference_material>")[0]
        words = set(re.findall(r"\w{4,}", question.lower()))
        best, best_score = "", 0
        for line in material.split("\n"):
            score = len(words & set(re.findall(r"\w{4,}", line.lower())))
            if score > best_score and not line.startswith("###"):
                best, best_score = line.strip("-# "), score
        if best:
            return f"{best[:280]} What are you hoping to get done?"
        return "I don't have that detail, but I can pass your question to the team. What's the best email to reach you?"


_instance = None


def get_llm():
    global _instance
    if _instance is None:
        _instance = MockLLM() if config.LLM_BACKEND == "mock" else BedrockLLM()
    return _instance
