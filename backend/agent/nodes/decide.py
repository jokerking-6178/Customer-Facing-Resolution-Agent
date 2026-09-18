"""Node 5 — decide: run every request through the policy engine's authority gate.

This is the hinge of the whole system: no LLM judgment touches money,
waivers, or authority. The engine returns verdicts; the respond and clarify
nodes only phrase them.
"""
from __future__ import annotations

from ...policy import engine as pe
from ...policy.engine import Verdict


def _verdict_to_dict(v: Verdict) -> dict:
    return {
        "request_type": v.request_type,
        "status": v.status,
        "rule": v.rule,
        "reason": v.reason,
        "actions": v.actions,
        "payload": v.payload,
    }


def decide(state: dict) -> dict:
    ledger = state["ledger"]
    session_id = state["session_id"]
    ctx = {"booking": state.get("booking") or {}, "customer": state.get("customer") or {}}
    verdicts: list[dict] = []

    # ---- legal threats: escalate immediately, nothing else runs ---------------
    if state.get("legal_threat"):
        verdicts.append(_verdict_to_dict(Verdict(
            "conversation", "escalate", rule="prohibited_legal",
            reason="Customer threatened legal action or a formal complaint; "
                   "must be escalated to a human agent immediately.",
        )))
        state["verdicts"] = verdicts
        state["escalated"] = True
        return state

    booking = state.get("booking") or {}
    disruption = booking.get("disruption") or {}

    # ---- more than one disrupted booking: we must ask which one ---------------
    if "which_flight" in (state.get("missing_info") or []):
        verdicts.append(_verdict_to_dict(Verdict(
            "booking_identification", "clarify", rule="allowed_actions",
            reason="More than one of this customer's bookings is disrupted.",
            payload={"options": []},
        )))

    # ---- cancellation with no explicit ask yet: present the entitlement -------
    if booking.get("status") == "cancelled" and not state.get("requested_actions") \
            and state.get("intent") in ("general_disruption", "compensation"):
        verdicts.append(_verdict_to_dict(pe.entitle_cancellation(booking)))

    # ---- every explicitly requested action passes the authority gate ----------
    for req in state.get("requested_actions", []):
        verdicts.append(_verdict_to_dict(pe.evaluate_request(req, ctx)))

    # ---- proactive standard compensation for qualifying delays ----------------
    # (issued once per session; Sample B behaviour: "I've applied both to your
    #  account now")
    if disruption.get("type") == "delay" and disruption.get("caused_by") == "airline":
        ent = pe.delay_compensation(disruption.get("delay_hours"))
        comp_requested = any(
            v["request_type"] in ("compensation", "hotel") and v["status"] == "execute"
            for v in verdicts
        )
        if ent.meal_voucher and not comp_requested \
                and not ledger.has_action(session_id, "issue_meal_voucher"):
            verdicts.append(_verdict_to_dict(Verdict(
                "compensation", "execute", rule="delay_compensation",
                reason="Standard compensation for a {}-hour delay.".format(
                    disruption.get("delay_hours")),
                actions=ent.as_actions(),
            )))

    # ---- idempotency: never issue the same entitlement twice in one session ---
    verdicts = _drop_already_issued(verdicts, ledger, session_id)

    state["verdicts"] = verdicts
    state["escalated"] = any(v["status"] == "escalate" for v in verdicts)
    return state


# Entitlements that are granted once per session, not once per request. Asking
# for compensation a second time must not issue a second voucher.
ONCE_PER_SESSION = {
    "issue_meal_voucher",
    "grant_lounge_access",
    "arrange_hotel_delayed_hours",
    "initiate_refund",
}


def _drop_already_issued(verdicts: list[dict], ledger, session_id: str) -> list[dict]:
    out: list[dict] = []
    for v in verdicts:
        if v["status"] != "execute" or not v.get("actions"):
            out.append(v)
            continue
        kept = [
            a for a in v["actions"]
            if not (a["type"] in ONCE_PER_SESSION
                    and ledger.has_action(session_id, a["type"]))
        ]
        if kept:
            v = {**v, "actions": kept}
            out.append(v)
        else:
            # Everything in this verdict was already granted earlier in the
            # session. Grant nothing again -- but keep the original reason, so
            # the customer still hears WHAT they are entitled to rather than a
            # bare "nothing further is due".
            already = ", ".join(
                a["type"].replace("_", " ") for a in v["actions"]
            )
            out.append({
                **v,
                "status": "decline",
                "actions": [],
                "reason": "{} This was already applied to the booking earlier in "
                          "this conversation ({}), so it is not issued again."
                          .format(v.get("reason", "").rstrip(), already),
            })
    return out
