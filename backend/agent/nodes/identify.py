"""Node 1 — identify: resolve customer + affected booking from the session."""
from __future__ import annotations

from ...data import loader


def emit(state: dict, event: str, data: dict) -> None:
    q = state.get("queue")
    if q is not None:
        q.put((event, data))


def identify(state: dict) -> dict:
    customer = loader.get_customer(state["customer_id"])
    bookings = loader.get_bookings_for(state["customer_id"]) if customer else []
    disrupted = [b for b in bookings if b.get("disruption")]

    booking = None
    missing: list[str] = []
    if len(disrupted) == 1:
        booking = disrupted[0]
    elif len(disrupted) > 1:
        # not the case in this data pack, but stay honest
        missing.append("which_flight")

    # An unknown customer, or a customer with no disrupted booking, must never
    # fall through to a confident verdict about a booking we never found. The
    # authority gate escalates on an empty booking; keep the state honest here.
    state["customer"] = customer or {}
    state["booking"] = booking
    state["missing_info"] = missing
    state["clarify_count"] = state.get("clarify_count", 0)
    return state
