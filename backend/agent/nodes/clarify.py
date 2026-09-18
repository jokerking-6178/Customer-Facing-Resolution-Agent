"""Node — clarify: ask exactly ONE necessary question, then end the turn.

This node runs downstream of `decide`. It is handed the policy engine's own
"clarify" verdict and may phrase nothing beyond the options that verdict
carries. It never sees the raw facts dict, so it cannot name a flight, an
amount, or a policy the engine did not authorise.
"""
from __future__ import annotations

from .. import prompts
from .identify import emit

# Human wording for each option the engine may offer. Keys are the action
# types in Verdict.payload["options"].
OPTION_TEXT = {
    "rebook_next_available": "a free rebooking on the next available flight within 24 hours",
    "initiate_refund": "a full refund",
}


def _clarify_verdict(state: dict) -> dict | None:
    for v in state.get("verdicts", []):
        if v.get("status") == "clarify":
            return v
    return None


def clarify(state: dict) -> dict:
    provider = state["provider"]
    verdict = _clarify_verdict(state) or {}
    options = (verdict.get("payload") or {}).get("options") or []
    option_lines = [OPTION_TEXT.get(o, o.replace("_", " ")) for o in options]

    if option_lines:
        choices = " OR ".join(option_lines)
        hint = (
            "The customer must choose between exactly these options, and nothing else:\n"
            "  " + choices + "\n"
            "Ask one short, warm question that offers exactly those options."
        )
    else:
        hint = "Ask one short, warm question for the missing information."

    question = provider.chat_text(
        prompts.CLARIFY_SYSTEM,
        "Customer: {}\n"
        "Their message: \"{}\"\n"
        "{}\n".format(
            (state.get("customer") or {}).get("name", "the customer"),
            state.get("message", ""),
            hint,
        ),
        on_chunk=lambda t: emit(state, "token", {"text": t}),
    )
    state["clarify_question"] = question
    state["response"] = question
    return state
