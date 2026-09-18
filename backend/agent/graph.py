"""LangGraph conversation state machine.

    START -> identify -> understand -> facts -> decide -> {clarify | escalate | respond}
                                                             -> record -> END

Every customer-facing message is produced downstream of `decide`, so there is
no path to a reply that did not pass the policy engine's authority gate.
Clarification is not an exception: the engine itself returns a verdict with
status "clarify" carrying the options the customer may choose between, and the
clarify node may say nothing else.
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from ..llm.provider import get_provider
from ..records.ledger import Ledger
from .nodes import clarify, decide, escalate, facts, identify, record, respond, understand
from .state import TurnState

MAX_CLARIFICATIONS = 2


def _route_after_decide(state: TurnState) -> str:
    """Escalations win; then a pending clarify verdict; otherwise respond."""
    if state.get("escalated"):
        return "escalate"
    wants_clarify = any(
        v.get("status") == "clarify" for v in state.get("verdicts", [])
    )
    if wants_clarify and state.get("clarify_count", 0) < MAX_CLARIFICATIONS:
        return "clarify"
    return "respond"


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(TurnState)
    g.add_node("identify", identify.identify)
    g.add_node("understand", understand.understand)
    g.add_node("facts", facts.facts)
    g.add_node("clarify", clarify.clarify)
    g.add_node("decide", decide.decide)
    g.add_node("escalate", escalate.escalate)
    g.add_node("respond", respond.respond)
    g.add_node("record", record.record)

    g.add_edge(START, "identify")
    g.add_edge("identify", "understand")
    g.add_edge("understand", "facts")
    g.add_edge("facts", "decide")
    g.add_conditional_edges(
        "decide",
        _route_after_decide,
        {"clarify": "clarify", "escalate": "escalate", "respond": "respond"},
    )
    g.add_edge("clarify", "record")
    g.add_edge("escalate", "respond")
    g.add_edge("respond", "record")
    g.add_edge("record", END)
    return g.compile()


def run_turn(session_id: str, customer_id: str, message: str,
             ledger: Ledger, provider=None, queue=None) -> dict:
    """Run one customer message through the graph and return the final state."""
    app = build_graph()
    messages = ledger.get_messages(session_id)
    messages.append({"role": "customer", "content": message})

    state: TurnState = {  # type: ignore[typeddict-item]
        "session_id": session_id,
        "customer_id": customer_id,
        "message": message,
        "messages": messages,
        "ledger": ledger,
        "provider": provider or get_provider(),
        "queue": queue,
        # Counted from the ledger, not guessed from message text: the clarify
        # node writes a "clarify" action row on every question it asks.
        "clarify_count": ledger.count_actions(session_id, "clarify"),
    }
    return app.invoke(state, config={"recursion_limit": 20})
