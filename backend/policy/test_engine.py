"""The three scored scenarios + edge cases, tested against the policy engine.

These are the assignment's acceptance tests. No LLM is involved.
"""
import pytest

from backend.data import loader
from backend.policy.engine import (
    DELAY_HOTEL_HOURS,
    DELAY_LOUNGE_HOURS,
    FARE_WAIVER_LIMIT,
    MEAL_VOUCHER_AMOUNT,
    delay_compensation,
    entitle_cancellation,
    evaluate_request,
    get_priority_rebooking,
)


def _ctx(customer_id):
    """Build the engine context straight from the real data pack.

    Hand-copied fixtures cannot catch data-pack drift; these can.
    """
    customer = loader.get_customer(customer_id)
    booking = loader.get_disrupted_booking(customer_id)
    return {"booking": booking, "customer": customer}


PRIYA_CTX = _ctx("priya_nair")
ARVIND_CTX = _ctx("arvind_kulkarni")
MEHER_CTX = _ctx("meher_kaur")


def test_fixtures_match_the_data_pack():
    """Guards the scenario numbers the whole suite depends on."""
    assert PRIYA_CTX["booking"]["status"] == "cancelled"
    assert PRIYA_CTX["customer"]["loyalty_tier"] == "Gold"
    assert ARVIND_CTX["booking"]["disruption"]["delay_hours"] == 4
    assert ARVIND_CTX["customer"]["loyalty_tier"] == "Silver"
    assert MEHER_CTX["booking"]["disruption"]["delay_hours"] == 6
    assert MEHER_CTX["customer"]["loyalty_tier"] == "Platinum"


def test_datapack_holds_no_invented_schedule_or_fare_data():
    """The supplied pack has no flights/fares; we must not have added any."""
    pack = loader.load_datapack()
    assert "flights" not in pack
    assert not hasattr(loader, "get_next_available_flight")


# --------------------------------------------------------------------------
# Delay compensation rule
# --------------------------------------------------------------------------
def test_delay_under_3h_meal_voucher_only():
    e = delay_compensation(2)
    assert e.meal_voucher == MEAL_VOUCHER_AMOUNT and not e.lounge and e.hotel_hours == 0


def test_delay_over_3h_adds_lounge():
    e = delay_compensation(4)
    assert e.meal_voucher == MEAL_VOUCHER_AMOUNT and e.lounge and e.hotel_hours == 0


def test_delay_over_5h_hotel_covers_delayed_hours_not_a_night():
    e = delay_compensation(6)
    assert e.meal_voucher and e.lounge and e.hotel_hours == 6.0


def test_no_delay_no_compensation():
    e = delay_compensation(0)
    assert not e.meal_voucher and not e.lounge and e.hotel_hours == 0


# --------------------------------------------------------------------------
# Scenario 1 — Priya (Gold, cancelled SK-204)
# --------------------------------------------------------------------------
def test_priya_refund_is_executed():
    v = evaluate_request({"type": "refund"}, PRIYA_CTX)
    assert v.status == "execute"
    assert v.rule == "refund_processing"
    assert any(a["type"] == "initiate_refund" for a in v.actions)


def test_priya_upgrade_is_beyond_policy():
    v = evaluate_request({"type": "upgrade"}, PRIYA_CTX)
    assert v.status == "decline"
    assert v.rule == "prohibited_compensation"


def test_priya_upgrade_escalates_when_she_insists():
    v = evaluate_request({"type": "upgrade", "insisting": True}, PRIYA_CTX)
    assert v.status == "escalate"


def test_priya_free_rebooking_on_next_available():
    v = evaluate_request({"type": "rebook", "target": "next_available"}, PRIYA_CTX)
    assert v.status == "execute"
    assert v.rule == "cancellation_rebooking"
    assert v.actions[0]["priority"] is True   # Gold tier


# --------------------------------------------------------------------------
# Scenario 2 — Arvind (Silver, 4h delay)
# --------------------------------------------------------------------------
def test_arvind_gets_voucher_and_lounge_not_hotel():
    v = evaluate_request({"type": "hotel"}, ARVIND_CTX)
    assert v.status == "decline"
    assert "5 hours" in v.reason


def test_arvind_standard_compensation():
    v = evaluate_request({"type": "compensation"}, ARVIND_CTX)
    assert v.status == "execute"
    types = [a["type"] for a in v.actions]
    assert "issue_meal_voucher" in types and "grant_lounge_access" in types
    assert "arrange_hotel_delayed_hours" not in types


# --------------------------------------------------------------------------
# Scenario 3 — Meher (Platinum, 6h delay, Rs 2,000 fare difference)
# --------------------------------------------------------------------------
def test_meher_hotel_covers_delayed_hours_only():
    v = evaluate_request({"type": "hotel"}, MEHER_CTX)
    assert v.status == "execute"
    assert v.actions[0]["hours"] == 6


def test_meher_full_night_hotel_is_declined():
    v = evaluate_request({"type": "hotel", "full_night": True}, MEHER_CTX)
    assert v.status == "decline"
    assert "full night" in v.reason


def test_meher_full_night_escalates_when_she_insists():
    v = evaluate_request({"type": "hotel", "full_night": True, "insisting": True}, MEHER_CTX)
    assert v.status == "escalate"


def test_meher_fare_waiver_2000_exceeds_agent_limit():
    v = evaluate_request({"type": "rebook", "target": "specific_flight",
                          "fare_difference": 2000, "waiver_requested": True}, MEHER_CTX)
    assert v.status == "escalate"
    assert v.rule == "fare_difference"
    assert "1,500" in v.reason


def test_meher_fare_waiver_at_limit_is_allowed():
    v = evaluate_request({"type": "rebook", "target": "specific_flight",
                          "fare_difference": FARE_WAIVER_LIMIT, "waiver_requested": True}, MEHER_CTX)
    assert v.status == "execute"


def test_meher_platinum_priority_rebooking_free():
    v = evaluate_request({"type": "rebook", "target": "next_available"}, MEHER_CTX)
    assert v.status == "execute"
    assert v.actions[0]["priority"] is True  # Platinum tier


# --------------------------------------------------------------------------
# Prohibited actions (the escalation matrix)
# --------------------------------------------------------------------------
def test_refund_to_different_payment_method_escalates():
    v = evaluate_request({"type": "refund", "payment_method": "other"}, PRIYA_CTX)
    assert v.status == "escalate"


def test_non_airline_caused_exception_declined_then_escalated():
    ctx = {"booking": {"status": "delayed",
                       "disruption": {"type": "delay", "caused_by": "customer", "delay_hours": 0}},
           "customer": {"loyalty_tier": "Silver"}}
    v = evaluate_request({"type": "compensation"}, ctx)
    assert v.status == "decline"
    v = evaluate_request({"type": "compensation", "insisting": True}, ctx)
    assert v.status == "escalate"


def test_unknown_request_type_escalates():
    v = evaluate_request({"type": "delete_customer_account"}, PRIYA_CTX)
    assert v.status == "escalate"
    assert v.rule == "authority_gate"


def test_loyalty_priority_only_for_gold_and_platinum():
    assert get_priority_rebooking("Gold") and get_priority_rebooking("Platinum")
    assert not get_priority_rebooking("Silver")


# --------------------------------------------------------------------------
# Threshold boundaries (the data pack says "under" / "more than", so exactly
# 3h and exactly 5h do NOT cross)
# --------------------------------------------------------------------------
def test_delay_of_exactly_3h_gets_no_lounge():
    e = delay_compensation(DELAY_LOUNGE_HOURS)
    assert e.meal_voucher == MEAL_VOUCHER_AMOUNT
    assert not e.lounge
    assert e.hotel_hours == 0


def test_delay_of_exactly_5h_gets_no_hotel():
    e = delay_compensation(DELAY_HOTEL_HOURS)
    assert e.meal_voucher == MEAL_VOUCHER_AMOUNT
    assert e.lounge
    assert e.hotel_hours == 0


def test_hotel_request_at_exactly_5h_is_declined():
    ctx = {"booking": {"status": "delayed",
                       "disruption": {"type": "delay", "caused_by": "airline",
                                      "delay_hours": DELAY_HOTEL_HOURS}},
           "customer": {"loyalty_tier": "Gold"}}
    v = evaluate_request({"type": "hotel"}, ctx)
    assert v.status == "decline"


def test_fare_waiver_one_rupee_over_the_limit_escalates():
    v = evaluate_request({"type": "rebook", "target": "specific_flight",
                          "fare_difference": FARE_WAIVER_LIMIT + 1,
                          "waiver_requested": True}, MEHER_CTX)
    assert v.status == "escalate"
    assert v.rule == "fare_difference"


# --------------------------------------------------------------------------
# entitle_cancellation validates rather than asserts
# --------------------------------------------------------------------------
def test_entitle_cancellation_offers_both_options_for_priya():
    v = entitle_cancellation(PRIYA_CTX["booking"])
    assert v.status == "clarify"
    assert v.payload["options"] == ["rebook_next_available", "initiate_refund"]


def test_entitle_cancellation_declines_a_booking_that_is_not_cancelled():
    v = entitle_cancellation(ARVIND_CTX["booking"])
    assert v.status == "decline"


def test_entitle_cancellation_declines_when_not_airline_caused():
    booking = {"status": "cancelled",
               "disruption": {"type": "cancellation", "caused_by": "customer"}}
    v = entitle_cancellation(booking)
    assert v.status == "decline"
    assert v.rule == "prohibited_exception"


# --------------------------------------------------------------------------
# The authority gate's own guarantees
# --------------------------------------------------------------------------
def test_no_booking_resolved_escalates_rather_than_guessing():
    v = evaluate_request({"type": "refund"}, {"booking": {}, "customer": {}})
    assert v.status == "escalate"
    assert v.rule == "authority_gate"


def test_waiver_requested_without_an_amount_escalates():
    """A waiver with no established figure must never auto-approve."""
    v = evaluate_request({"type": "rebook", "target": "specific_flight",
                          "fare_difference": 0, "waiver_requested": True}, MEHER_CTX)
    assert v.status == "escalate"


def test_fare_difference_provenance_is_recorded():
    v = evaluate_request({"type": "rebook", "target": "specific_flight",
                          "fare_difference": 2000, "waiver_requested": True}, MEHER_CTX)
    assert v.payload["fare_difference_source"] == "customer_stated"


def test_only_allowed_action_types_can_ever_be_emitted():
    """Every executable verdict across the scenarios stays on the allowed list."""
    from backend.policy.engine import ALLOWED_ACTION_TYPES
    reqs = [
        ({"type": "refund"}, PRIYA_CTX),
        ({"type": "rebook", "target": "next_available"}, PRIYA_CTX),
        ({"type": "compensation"}, ARVIND_CTX),
        ({"type": "hotel"}, MEHER_CTX),
        ({"type": "provide_status"}, MEHER_CTX),
        ({"type": "rebook", "target": "specific_flight",
          "fare_difference": 1000, "waiver_requested": True}, MEHER_CTX),
    ]
    for req, ctx in reqs:
        v = evaluate_request(req, ctx)
        for a in v.actions:
            assert a["type"] in ALLOWED_ACTION_TYPES


def test_declined_and_escalated_verdicts_never_carry_actions():
    reqs = [
        ({"type": "upgrade"}, PRIYA_CTX),
        ({"type": "hotel", "full_night": True}, MEHER_CTX),
        ({"type": "hotel"}, ARVIND_CTX),
        ({"type": "refund", "payment_method": "other"}, PRIYA_CTX),
        ({"type": "delete_customer_account"}, PRIYA_CTX),
    ]
    for req, ctx in reqs:
        v = evaluate_request(req, ctx)
        assert v.status in ("decline", "escalate")
        assert v.actions == []
