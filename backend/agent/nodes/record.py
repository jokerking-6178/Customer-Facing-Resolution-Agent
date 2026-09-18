"""Node 8 — record: append-only turn + action ledger entries.

Every verdict leaves a trace, including the clarifying questions: the clarify
row is what bounds the two-question cap across turns, and it is what proves
the question came from the policy engine rather than around it.
"""
from __future__ import annotations

import json

from .identify import emit

LEDGER_STATUS = {
    "execute": "executed",
    "decline": "declined",
    "escalate": "escalated",
    "clarify": "clarified",
}


def record(state: dict) -> dict:
    ledger = state["ledger"]
    session_id = state["session_id"]
    idx = ledger.next_turn_index(session_id)
    ticket_id = state.get("ticket_id")

    verdicts = state.get("verdicts", [])

    turn_id = ledger.record_turn(
        session_id, idx, state["message"], state.get("response", ""),
        state.get("intent", ""), state.get("sentiment", ""),
        verdicts,
    )

    if ticket_id:
        emit(state, "ticket", {
            "ticket_id": ticket_id,
            "priority": state.get("ticket_priority", "normal"),
            "summary": (state.get("escalation_packet") or {}).get("intent", ""),
        })

    for v in verdicts:
        status = LEDGER_STATUS.get(v.get("status"), "declined")

        if v.get("status") == "clarify":
            asked = bool(state.get("clarify_question"))
            # Only a question actually put to the customer is logged as a
            # "clarify" action, because graph.run_turn counts those rows to
            # enforce the two-question cap. Once the cap is reached the
            # verdict is still recorded for audit, under its own request type,
            # but it must not inflate the counter.
            ledger.record_action(
                session_id, turn_id,
                "clarify" if asked else v.get("request_type", "clarify"),
                "clarified",
                state.get("clarify_question") if asked else v.get("reason", ""),
                v.get("rule", ""),
            )
            continue

        detail_suffix = " [ticket {}]".format(ticket_id) if (
            ticket_id and v["status"] == "escalate") else ""

        for a in v.get("actions", []):
            ledger.record_action(
                session_id, turn_id, a["type"], status,
                "{}: {} :: {}".format(v["request_type"], v["reason"],
                                      json.dumps(a, default=str)),
                v["rule"],
            )
            emit(state, "action", {"type": a["type"], "status": status,
                                   "rule": v["rule"], "detail": v["reason"]})
        if not v.get("actions"):
            ledger.record_action(
                session_id, turn_id, v["request_type"], status,
                v["reason"] + detail_suffix, v["rule"],
            )
            emit(state, "action", {"type": v["request_type"], "status": status,
                                   "rule": v["rule"],
                                   "detail": v["reason"] + detail_suffix,
                                   "ticket_id": ticket_id if v["status"] == "escalate" else None})

    state["turn_idx"] = idx
    state["record_turn_id"] = turn_id
    emit(state, "done", {"turn_id": turn_id, "turn_idx": idx})
    return state
