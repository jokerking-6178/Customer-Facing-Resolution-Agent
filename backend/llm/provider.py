"""LLM provider layer.

One OpenAI-compatible client, switched by env var:
  LLM_PROVIDER=ollama  -> local Ollama (default, zero cost, demo video)
  LLM_PROVIDER=groq     -> Groq API (hosted Render deployment)
  LLM_PROVIDER=mock    -> deterministic canned responses (tests / CI)

The model never decides money or authority -- it only classifies intent and
sentiment (chat_json) and phrases pre-computed verdicts (chat_text).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import httpx

from .. import config  # noqa: F401  -- ensures .env is loaded

PROVIDERS = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1:8b",
        "api_key_env": None,
        "api_key_default": "ollama",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        # Groq retires hosted models periodically -- llama-3.3-70b-versatile
        # was decommissioned and now 404s. Override with LLM_MODEL, and run
        # `python -m backend.llm.provider` to list what your key can reach.
        "model": "openai/gpt-oss-120b",
        "api_key_env": "GROQ_API_KEY",
        "api_key_default": None,
    },
}


class ProviderError(Exception):
    """A language-model failure, already phrased for a customer to read.

    The raw cause (status codes, URLs, keys, stack traces) stays in the server
    log; only `message` is ever shown in the browser.
    """

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


def _friendly(exc: Exception) -> ProviderError:
    """Map a transport/HTTP failure onto something a customer can act on."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return ProviderError(
                "The assistant isn't configured correctly on our side, so I can't "
                "reply right now. Please contact support.", exc)
        if code == 404:
            return ProviderError(
                "The assistant is unavailable right now (its language model is no "
                "longer reachable). Please try again later.", exc)
        if code == 429:
            return ProviderError(
                "We're handling a lot of requests at the moment. Please wait a few "
                "seconds and send that again.", exc)
        if code >= 500:
            return ProviderError(
                "The assistant is temporarily unavailable. Please try again in a "
                "moment.", exc)
        return ProviderError(
            "The assistant couldn't complete that request. Please try again.", exc)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return ProviderError(
            "I can't reach the assistant right now. Please try again in a moment.", exc)
    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        return ProviderError(
            "That took too long to answer. Please try again.", exc)
    return ProviderError(
        "Something went wrong while preparing the reply. Please try again.", exc)


def get_provider():
    name = os.getenv("LLM_PROVIDER", "ollama").lower()
    if name == "mock":
        return MockProvider()
    if name not in PROVIDERS:
        raise ProviderError(
            "The assistant isn't configured correctly on our side "
            "(unknown provider {!r}).".format(name))
    return OpenAICompatProvider(name)


class OpenAICompatProvider:
    """Minimal OpenAI-compatible chat client (works for Ollama and Groq)."""

    def __init__(self, name: str):
        cfg = PROVIDERS[name]
        self.name = name
        self.base_url = os.getenv("LLM_BASE_URL", cfg["base_url"]).rstrip("/")
        self.model = os.getenv("LLM_MODEL", cfg["model"])
        if cfg["api_key_env"]:
            self.api_key = os.getenv(cfg["api_key_env"], cfg["api_key_default"] or "")
        else:
            self.api_key = cfg["api_key_default"] or "none"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat_json(self, system: str, user: str, retries: int = 1) -> dict:
        """Chat call that must return parseable JSON. One validated retry."""
        text = self._complete(system, user)
        for _ in range(retries + 1):
            parsed = _try_parse_json(text)
            if parsed is not None:
                return parsed
            text = self._complete(
                system + "\nRespond with a single valid JSON object and nothing else.",
                user,
            )
        # Never surface raw model output to the browser; log it instead.
        print("[llm] {} returned unparseable JSON: {!r}".format(self.name, text[:300]))
        raise ProviderError(
            "I couldn't understand that request well enough to act on it. "
            "Could you rephrase it?")

    def chat_text(self, system: str, user: str, on_chunk: Callable[[str], None] | None = None) -> str:
        """Streaming chat; optionally emits tokens through on_chunk."""
        return self._complete(system, user, on_chunk=on_chunk)

    def _complete(self, system: str, user: str, on_chunk=None) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "stream": on_chunk is not None,
        }
        if not on_chunk:
            try:
                resp = httpx.post(f"{self.base_url}/chat/completions",
                                  headers=self._headers(), json=body, timeout=120.0)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                raise _friendly(e) from e

        parts: list[str] = []
        try:
            with httpx.stream("POST", f"{self.base_url}/chat/completions",
                              headers=self._headers(), json=body, timeout=180.0) as resp:
                # Read the body before raising: a streaming error response is
                # otherwise unreadable, which loses the real cause in the log.
                if resp.status_code >= 400:
                    resp.read()
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: "):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        parts.append(delta)
                        on_chunk(delta)
        except httpx.HTTPError as e:
            raise _friendly(e) from e
        return "".join(parts)


def _try_parse_json(text: str) -> Any:
    text = text.strip()
    # strip markdown fences if the model adds them
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


class MockProvider:
    """Deterministic stand-in used by the test suite and CI.

    Keyword heuristics stand in for the understand node; a template renders
    the respond node. Good enough to exercise the whole pipeline without an
    LLM -- the policy engine makes the actual decisions anyway.
    """

    name = "mock"

    def chat_json(self, system: str, user: str, retries: int = 1) -> dict:
        if "INTENT CLASSIFIER" in system:
            return self._classify(user)
        return {}

    def chat_text(self, system: str, user: str, on_chunk=None) -> str:
        reply = self._respond(user)
        if on_chunk:
            for word in reply.split(" "):
                on_chunk(word + " ")
        return reply

    # -- understand heuristic ---------------------------------------------------
    @staticmethod
    def _classify(text: str) -> dict:
        t = text.lower()
        intent = "general_disruption"
        actions: list[dict[str, Any]] = []

        if "legal" in t or "complaint" in t or "sue" in t:
            intent = "complaint_or_legal"
        if "status" in t or "what time" in t or "when will" in t:
            intent = "status"
            actions.append({"type": "provide_status"})

        if "refund" in t or "cash back" in t:
            intent = "refund"
            actions.append({"type": "refund", "payment_method":
                            "other" if "other card" in t or "different card" in t or "different method" in t else "original"})
        if "rebook" in t or "another flight" in t or "different flight" in t \
                or "next flight" in t or "higher-fare" in t or "moved onto" in t:
            intent = "rebook"
            # only amounts with an explicit currency marker count (avoid flight numbers)
            m = re.search(r"(?:rs\.?|₹|inr)\s*([0-9][0-9,]*)", t)
            fare_difference = int(m.group(1).replace(",", "")) if m else 0
            actions.append({
                "type": "rebook",
                "target": "specific_flight" if fare_difference else "next_available",
                "fare_difference": fare_difference,
                "waiver_requested": fare_difference > 0,
            })
        if "hotel" in t:
            actions.append({"type": "hotel", "full_night": "full night" in t or "night's stay" in t or "full night's" in t})
        if "business" in t or "upgrade" in t:
            actions.append({"type": "upgrade"})
        if "voucher" in t or "compensation" in t:
            if not any(a["type"] == "compensation" for a in actions):
                actions.append({"type": "compensation"})

        insisting = ("insist" in t or "i demand" in t
                     or "unacceptable" in t) and "complaint" not in t
        for a in actions:
            a["insisting"] = insisting

        sentiment = "calm"
        if "furious" in t or "unacceptable" in t or "angry" in t or "outrage" in t:
            sentiment = "angry"
        elif "frustrat" in t or "ruined" in t or "annoyed" in t:
            sentiment = "frustrated"
        elif "confus" in t or "don't understand" in t or "not sure" in t:
            sentiment = "confused"

        return {
            "intent": intent,
            "sentiment": sentiment,
            "requested_actions": actions,
            "legal_threat": intent == "complaint_or_legal",
        }

    # -- respond template ----------------------------------------------------------
    @staticmethod
    def _respond(user_prompt: str) -> str:
        # The clarify prompt is the one with no VERDICTS block; answer it
        # with a real question built from the options it was given.
        if "VERDICTS" not in user_prompt:
            if "refund" in user_prompt.lower():
                return ("I can see your flight was cancelled due to operational reasons. "
                        "I can rebook you on the next available flight at no extra cost, "
                        "or process a full refund. Which would you prefer?")
            return "Could you confirm which flight this is about so I can help you right away?"

        # The real prompt contains a VERDICTS JSON block; render it plainly.
        m = re.search(r"VERDICTS[^:]*: (\[.*\])", user_prompt, re.DOTALL)
        if not m:
            return "I've looked into your booking and I'm here to help."
        try:
            verdicts = json.loads(m.group(1))
        except json.JSONDecodeError:
            return "I've looked into your booking and I'm here to help."

        # Lead with what we DID (Sample B style), then declines, then escalations.
        order = {"execute": 0, "decline": 1, "escalate": 2, "clarify": 3}
        verdicts = sorted(verdicts, key=lambda v: order.get(v.get("status"), 4))

        lines: list[str] = []
        first = True
        for v in verdicts:
            prefix = "" if first else " "
            status = v.get("status")
            reason = v.get("reason", "")
            if status == "execute":
                lines.append(f"{prefix}Done — {reason}")
            elif status == "decline":
                lines.append(f"{prefix}I'm unable to do that: {reason}")
            elif status == "escalate":
                lines.append(f"{prefix}I've escalated this to our specialist team for you: {reason}")
            elif status == "clarify":
                opts = (v.get("payload") or {}).get("options") or []
                if "initiate_refund" in opts:
                    lines.append(prefix + "Your flight was cancelled by the airline, so "
                                 "you can choose either a free rebooking on the next "
                                 "available flight within 24 hours, or a full refund. "
                                 "Just tell me which you would prefer.")
                else:
                    lines.append(f"{prefix}{reason}")
            first = False
        reply = " ".join(lines).strip()
        return reply or "I'm here to help with your booking."


if __name__ == "__main__":  # pragma: no cover
    # Diagnostic: `python -m backend.llm.provider`
    # Shows the resolved provider and, for a hosted provider, which models the
    # configured key can actually reach. Groq retires models periodically, so a
    # 404 on chat usually means the configured LLM_MODEL no longer exists.
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = get_provider()
    print("provider :", p.name)
    print("model    :", getattr(p, "model", "-"))
    print("base_url :", getattr(p, "base_url", "-"))
    if isinstance(p, MockProvider):
        print("\n(mock provider: no network, no models to list)")
        raise SystemExit(0)
    try:
        r = httpx.get(p.base_url + "/models", headers=p._headers(), timeout=30)
        r.raise_for_status()
        ids = sorted(m["id"] for m in r.json().get("data", []))
        print("\nModels reachable with this key ({}):".format(len(ids)))
        for i in ids:
            print("   ", i, " <-- configured" if i == p.model else "")
        if p.model not in ids:
            print("\n!! Configured model {!r} is NOT in the list above.".format(p.model))
            print("   Set LLM_MODEL in .env to one of them.")
    except Exception as e:
        print("\nCould not list models: {}: {}".format(type(e).__name__, str(e)[:200]))
