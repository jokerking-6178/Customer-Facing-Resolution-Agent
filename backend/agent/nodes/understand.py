"""Node 2 — understand: intent + sentiment + requested actions as strict JSON.

Everything the model returns here is untrusted input. It is sanitized before
it reaches the policy engine: unknown action types are dropped, numbers are
coerced, flags are forced to bool. The engine decides; the model only
proposes what the customer appeared to ask for.
"""
from __future__ import annotations

import re

from .. import prompts
from .identify import emit

VALID_INTENTS = {"rebook", "refund", "compensation", "status",
                 "complaint_or_legal", "general_disruption", "out_of_scope"}

VALID_SENTIMENTS = {"calm", "frustrated", "angry", "confused"}

# Customer-request types the classifier may propose. Anything else is dropped
# before it reaches the authority gate.
VALID_REQUEST_TYPES = {
    "refund", "rebook", "hotel", "compensation", "upgrade", "provide_status",
}

BOOL_FIELDS = ("insisting", "waiver_requested", "full_night")

# A deterministic backstop for the one prohibited action the data pack says
# must be escalated IMMEDIATELY. We do not rely on the model alone for this.
LEGAL_THREAT_PATTERNS = re.compile(
    r"\b(legal action|legal|sue|suing|lawyer|solicitor|attorney|litigat\w*|"
    r"consumer court|consumer forum|ombudsman|formal complaint|small claims)\b",
    re.IGNORECASE,
)


def _coerce_int(value) -> int:
    """Best-effort integer from whatever the model emitted. Never raises."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        if digits:
            try:
                return int(digits)
            except ValueError:
                return 0
    return 0


def sanitize_requested_actions(raw) -> list[dict]:
    """Drop anything the authority gate should never be asked to evaluate."""
    if not isinstance(raw, list):
        return []
    clean: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rtype = item.get("type")
        if not isinstance(rtype, str) or rtype not in VALID_REQUEST_TYPES:
            continue
        req: dict = {"type": rtype}

        for f in BOOL_FIELDS:
            if f in item:
                req[f] = bool(item[f])

        if rtype == "refund":
            method = item.get("payment_method", "original")
            req["payment_method"] = (
                method.strip().lower() if isinstance(method, str) else "other"
            )

        if rtype == "rebook":
            target = item.get("target", "next_available")
            req["target"] = (
                target if target in ("next_available", "specific_flight")
                else "next_available"
            )
            amount = _coerce_int(item.get("fare_difference"))
            req["fare_difference"] = amount if amount > 0 else 0
            # We hold no fare data of our own; record where this number came from.
            req["fare_difference_source"] = "customer_stated"

        clean.append(req)
    return clean


def understand(state: dict) -> dict:
    provider = state["provider"]
    raw = provider.chat_json(prompts.UNDERSTAND_SYSTEM, state["message"])
    if not isinstance(raw, dict):
        raw = {}

    intent = raw.get("intent", "general_disruption")
    if intent not in VALID_INTENTS:
        intent = "general_disruption"

    sentiment = raw.get("sentiment", "calm")
    if sentiment not in VALID_SENTIMENTS:
        sentiment = "calm"

    message = state.get("message") or ""
    legal_threat = (
        bool(raw.get("legal_threat"))
        or intent == "complaint_or_legal"
        or bool(LEGAL_THREAT_PATTERNS.search(message))
    )

    state["intent"] = intent
    state["sentiment"] = sentiment
    state["requested_actions"] = sanitize_requested_actions(raw.get("requested_actions"))
    state["legal_threat"] = legal_threat

    emit(state, "sentiment", {"intent": intent, "sentiment": sentiment})
    return state
