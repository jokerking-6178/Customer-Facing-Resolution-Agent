"""End-to-end graph tests with the deterministic mock provider.

Runs the three scored scenarios through the full LangGraph pipeline
without any LLM and asserts the verdicts and ledger contents.
"""
import json

import pytest

from backend.agent import run_turn
from backend.llm.provider import MockProvider
from backend.records.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    return Ledger(tmp_path / "test.db")


def _run(ledger, customer_id, message, session_id):
    return run_turn(session_id, customer_id, message,
                    ledger=ledger, provider=MockProvider())


def _statuses(state):
    return {(v["request_type"], v["status"]) for v in state["verdicts"]}


def _action_types(ledger, session_id, status="executed"):
    return {a["type"] for a in ledger.get_actions(session_id) if a["status"] == status}


# --------------------------------------------------------------------------
# Scenario 1 — Priya Nair
# --------------------------------------------------------------------------
def test_scenario_1_priya_refund_executed_upgrade_declined(ledger):
    sid = ledger.create_session("priya_nair")
    state = _run(ledger, "priya_nair",
                 "My flight SK-204 got cancelled and I am furious! "
                 "I want a full cash refund and a free upgrade to business class "
                 "on my return flight for the trouble.", sid)

    assert state["sentiment"] == "angry"
    assert ("refund", "execute") in _statuses(state)
    assert ("upgrade", "decline") in _statuses(state)
    assert "initiate_refund" in _action_types(ledger, sid)
    # nothing beyond policy was executed
    executed = _action_types(ledger, sid)
    assert "upgrade_to_business" not in executed


def test_scenario_1_priya_insisting_escalates(ledger):
    sid = ledger.create_session("priya_nair")
    _run(ledger, "priya_nair",
         "My flight got cancelled and I want a full refund.", sid)
    state = _run(ledger, "priya_nair",
                 "No, I insist — I want the business class upgrade for the trouble.", sid)
    assert ("upgrade", "escalate") in _statuses(state) or state["escalated"]


# --------------------------------------------------------------------------
# Scenario 2 — Arvind Kulkarni
# --------------------------------------------------------------------------
def test_scenario_2_arvind_voucher_lounge_hotel_declined(ledger):
    sid = ledger.create_session("arvind_kulkarni")
    state = _run(ledger, "arvind_kulkarni",
                 "This delay ruined my whole day — my flight SK-118 is delayed 4 hours "
                 "and I missed my connecting meeting. I want hotel accommodation "
                 "since it's been such a long delay.", sid)

    assert state["sentiment"] == "frustrated"
    executed = _action_types(ledger, sid)
    assert "issue_meal_voucher" in executed
    assert "grant_lounge_access" in executed
    assert "arrange_hotel_delayed_hours" not in executed
    declined = _action_types(ledger, sid, status="declined")
    assert "hotel" in declined


# --------------------------------------------------------------------------
# Scenario 3 — Meher Kaur
# --------------------------------------------------------------------------
def test_scenario_3_meher_split_verdicts(ledger):
    sid = ledger.create_session("meher_kaur")
    state = _run(ledger, "meher_kaur",
                 "My flight SK-305 is delayed 6 hours. I want a full night's hotel stay "
                 "rather than coverage for just the delayed hours, and I want to be moved "
                 "onto a different, higher-fare flight instead of waiting — "
                 "the fare difference for that flight is ₹2,000.", sid)

    statuses = _statuses(state)
    executed = _action_types(ledger, sid)
    declined = _action_types(ledger, sid, status="declined")
    escalated = _action_types(ledger, sid, status="escalated")

    # standard compensation for 6h delay: voucher + lounge + hotel for delayed hours
    assert "issue_meal_voucher" in executed
    assert "grant_lounge_access" in executed
    assert "arrange_hotel_delayed_hours" in executed
    # full night's stay declined
    assert "hotel" in declined
    # Rs 2,000 fare waiver escalated
    assert "rebook" in escalated
    assert state["escalated"] is True
    assert state["escalation_packet"]["reasons"]


def test_legal_threat_escalates_immediately(ledger):
    sid = ledger.create_session("priya_nair")
    state = _run(ledger, "priya_nair",
                 "This is unacceptable, I'm going to file a formal complaint "
                 "and consider legal action over this.", sid)
    assert state["escalated"] is True
    assert any(v["rule"] == "prohibited_legal" for v in state["verdicts"])


def test_cancellation_without_preference_asks_one_question(ledger):
    sid = ledger.create_session("priya_nair")
    state = _run(ledger, "priya_nair",
                 "My Goa flight got cancelled and no one told me anything!", sid)
    # clarify path: response is a question and nothing was granted yet
    assert state.get("clarify_question")
    assert state["response"].endswith("?")
    acts = ledger.get_actions(sid)
    # The question itself is recorded (this is what bounds the 2-question cap
    # and proves the question came from the policy engine), but no entitlement
    # was executed.
    assert [a["type"] for a in acts] == ["clarify"]
    assert all(a["status"] == "clarified" for a in acts)
    assert ledger.count_actions(sid, "clarify") == 1


def test_conversation_record_is_replayable(ledger):
    sid = ledger.create_session("arvind_kulkarni")
    _run(ledger, "arvind_kulkarni",
         "My flight SK-118 is delayed 4 hours, what compensation do I get?", sid)
    turns = ledger.get_turns(sid)
    assert len(turns) == 1
    assert turns[0]["sentiment"] in ("calm", "frustrated")
    assert turns[0]["customer_message"].startswith("My flight SK-118")
    assert turns[0]["agent_message"]


# --------------------------------------------------------------------------
# The LLM's output is untrusted input to the authority gate
# --------------------------------------------------------------------------
def test_sanitizer_drops_unknown_action_types():
    from backend.agent.nodes.understand import sanitize_requested_actions
    out = sanitize_requested_actions([
        {"type": "refund"},
        {"type": "wire_money_to_me"},
        {"type": "delete_account"},
    ])
    assert [a["type"] for a in out] == ["refund"]


def test_sanitizer_survives_malformed_action_lists():
    from backend.agent.nodes.understand import sanitize_requested_actions
    assert sanitize_requested_actions(None) == []
    assert sanitize_requested_actions("refund please") == []
    assert sanitize_requested_actions(["refund", 42, None]) == []


def test_sanitizer_coerces_a_string_fare_difference():
    """A string here used to raise TypeError inside the engine."""
    from backend.agent.nodes.understand import sanitize_requested_actions
    out = sanitize_requested_actions([
        {"type": "rebook", "target": "specific_flight",
         "fare_difference": "Rs 2,000", "waiver_requested": True},
    ])
    assert out[0]["fare_difference"] == 2000
    assert out[0]["fare_difference_source"] == "customer_stated"


def test_sanitizer_rejects_a_nonsense_fare_difference():
    from backend.agent.nodes.understand import sanitize_requested_actions
    out = sanitize_requested_actions([
        {"type": "rebook", "target": "specific_flight",
         "fare_difference": "lots", "waiver_requested": True},
    ])
    assert out[0]["fare_difference"] == 0


def test_legal_threat_is_caught_even_if_the_model_misses_it():
    """Deterministic backstop for a prohibited action that must escalate."""
    from backend.agent.nodes.understand import LEGAL_THREAT_PATTERNS
    for msg in ("I'm speaking to my lawyer about this",
                "see you in consumer court",
                "I will sue your airline"):
        assert LEGAL_THREAT_PATTERNS.search(msg)


# --------------------------------------------------------------------------
# Escalations become structured tickets
# --------------------------------------------------------------------------
def test_escalation_creates_a_structured_ticket(ledger):
    sid = ledger.create_session("meher_kaur")
    state = _run(ledger, "meher_kaur",
                 "Move me onto the higher-fare flight instead of waiting, "
                 "the fare difference is Rs 2,000.", sid)
    assert state["escalated"] is True
    assert state["ticket_id"].startswith("SKY-")

    tickets = ledger.get_tickets(sid)
    assert len(tickets) == 1
    t = tickets[0]
    assert t["status"] == "open"
    assert t["customer_id"] == "meher_kaur"
    # the packet a human agent picks up
    assert t["packet"]["facts"]["pnr"] == "WL7742"
    assert t["packet"]["reasons"]
    assert t["packet"]["conversation_history"]


def test_legal_threat_ticket_is_high_priority(ledger):
    sid = ledger.create_session("priya_nair")
    _run(ledger, "priya_nair",
         "This is unacceptable, I'm going to file a formal complaint "
         "and consider legal action over this.", sid)
    assert ledger.get_tickets(sid)[0]["priority"] == "high"


# --------------------------------------------------------------------------
# Clarification is bounded, and it goes THROUGH the policy engine
# --------------------------------------------------------------------------
def test_clarification_is_capped_at_two_questions(ledger):
    sid = ledger.create_session("priya_nair")
    vague = "My Goa flight got cancelled and no one told me anything!"
    for _ in range(4):
        state = _run(ledger, "priya_nair", vague, sid)
    assert ledger.count_actions(sid, "clarify") <= 2
    # once the cap is reached the agent must decide rather than keep asking
    assert not state.get("clarify_question")


def test_clarify_question_came_from_a_policy_engine_verdict(ledger):
    sid = ledger.create_session("priya_nair")
    state = _run(ledger, "priya_nair",
                 "My Goa flight got cancelled and no one told me anything!", sid)
    clarify_verdicts = [v for v in state["verdicts"] if v["status"] == "clarify"]
    assert clarify_verdicts, "the question must originate from a verdict"
    assert clarify_verdicts[0]["rule"] == "cancellation_rebooking"


# --------------------------------------------------------------------------
# Entitlements are granted once per session
# --------------------------------------------------------------------------
def test_asking_for_compensation_twice_does_not_issue_two_vouchers(ledger):
    sid = ledger.create_session("arvind_kulkarni")
    msg = "My flight SK-118 is delayed 4 hours, what compensation do I get?"
    _run(ledger, "arvind_kulkarni", msg, sid)
    _run(ledger, "arvind_kulkarni", msg, sid)
    vouchers = [a for a in ledger.get_actions(sid)
                if a["type"] == "issue_meal_voucher" and a["status"] == "executed"]
    assert len(vouchers) == 1


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
def test_turn_record_exposes_the_verdicts_that_drove_it(ledger):
    sid = ledger.create_session("arvind_kulkarni")
    _run(ledger, "arvind_kulkarni",
         "My flight is delayed 4 hours and I want a hotel.", sid)
    turn = ledger.get_turns(sid)[0]
    assert turn["verdicts"], "verdicts must be readable back, not write-only"
    assert any(v["rule"] == "delay_compensation" for v in turn["verdicts"])
