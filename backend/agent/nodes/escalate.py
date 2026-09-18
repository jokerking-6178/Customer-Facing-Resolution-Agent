"""Node 6 — escalate: build the context packet AND raise a structured ticket.

The packet is not just assembled for the reply text; it is persisted as a
ticket with a reference the customer can be given and a human agent can pick
up. Without this, "I've escalated it with full context" would be a claim the
system does not back.
"""
from __future__ import annotations

# Legal threats and formal complaints jump the queue; everything else the
# agent lacks authority for is a normal-priority handover.
HIGH_PRIORITY_RULES = {"prohibited_legal"}


def escalate(state: dict) -> dict:
    escalated = [v for v in state.get("verdicts", []) if v["status"] == "escalate"]
    customer = state.get("customer") or {}

    reasons = [
        {"request_type": v["request_type"], "rule": v["rule"], "reason": v["reason"],
         "payload": v.get("payload") or {}}
        for v in escalated
    ]
    priority = "high" if any(
        r["rule"] in HIGH_PRIORITY_RULES for r in reasons
    ) else "normal"
    summary = "; ".join(r["reason"] for r in reasons) or "Escalated to a human agent."

    packet = {
        "session_id": state["session_id"],
        "customer": customer,
        "facts": state.get("facts"),
        "intent": state.get("intent"),
        "sentiment": state.get("sentiment"),
        "reasons": reasons,
        "conversation_history": state.get("messages", [])[-6:],
    }
    state["escalation_packet"] = packet

    ledger = state.get("ledger")
    if ledger is not None:
        state["ticket_id"] = ledger.create_ticket(
            session_id=state["session_id"],
            turn_id=None,          # the turn row is written after this node
            customer_id=state.get("customer_id", ""),
            priority=priority,
            summary=summary,
            packet=packet,
        )
        state["ticket_priority"] = priority
    return state
