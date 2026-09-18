"""Shared state passed through every node of the conversation graph."""
from __future__ import annotations

from typing import Any, Optional, TypedDict


class TurnState(TypedDict, total=False):
    # identity + context
    session_id: str
    customer_id: str
    customer: dict              # profile from the data pack
    booking: dict               # the affected booking, if resolved
    ledger: Any                # Ledger instance (runtime ref)
    queue: Any                 # optional event queue for SSE streaming
    provider: Any               # LLM provider instance

    # conversation
    message: str               # this turn's customer message
    messages: list[dict]        # full history [{"role","content"}]

    # understanding
    intent: str
    sentiment: str
    requested_actions: list[dict]
    legal_threat: bool

    # facts (from the data pack)
    facts: dict

    # clarification
    missing_info: list[str]
    clarify_count: int
    clarify_question: str

    # decision
    verdicts: list[dict]
    escalated: bool
    escalation_packet: Optional[dict]
    ticket_id: Optional[str]        # structured escalation ticket reference
    ticket_priority: str            # high | normal

    # output
    response: str
    turn_idx: int
    record_turn_id: Optional[int]
