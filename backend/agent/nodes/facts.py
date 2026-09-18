"""Node 3 — facts: deterministic reads from the data pack. No LLM.

The data pack supplies no flight schedules, so this node never produces a
replacement flight number or departure time. The agent speaks of "the next
available flight within 24 hours" exactly as the Cancellation Rebooking Rule
words it, and nothing more specific.
"""
from __future__ import annotations


def facts(state: dict) -> dict:
    booking = state.get("booking") or {}
    customer = state.get("customer") or {}
    disruption = booking.get("disruption") or {}

    state["facts"] = {
        "customer_name": customer.get("name"),
        "loyalty_tier": customer.get("loyalty_tier"),
        "pnr": booking.get("pnr"),
        "flight": booking.get("flight"),
        "route_display": booking.get("route_display"),
        "date": booking.get("date"),
        "scheduled_departure": booking.get("scheduled_departure"),
        "status": booking.get("status"),
        "disruption_type": disruption.get("type"),
        "disruption_reason": disruption.get("reason"),
        "airline_caused": disruption.get("caused_by") == "airline",
        "delay_hours": disruption.get("delay_hours"),
        "new_departure": disruption.get("new_departure"),
    }
    return state
