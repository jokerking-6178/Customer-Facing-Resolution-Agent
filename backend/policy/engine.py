"""SkyAssist policy engine.

Every service rule from the Assignment 3 data pack, implemented as pure
Python. No LLM is involved in any decision about money, waivers, or
authority. The three scored scenarios are the unit tests for this module.

Rules (verbatim from the data pack):
- Cancellation Rebooking: airline-caused cancellation -> free rebooking on
  the next available flight within 24 hours, OR a full refund. Customer's choice.
- Delay Compensation: <3h -> Rs 500 meal voucher; >3h -> voucher + lounge;
  >5h -> voucher + hotel covering ONLY the delayed hours (never a full night).
- Refund Processing: full refund within 7 business days, original payment
  method only.
- Fare Difference: voluntary rebooking on a higher-fare flight -> customer
  pays the difference. Agents cannot waive fare differences above Rs 1,500
  without supervisor approval.
- Loyalty Tier: Gold and Platinum get priority rebooking (first access to
  next-available seats) but NO additional compensation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

MEAL_VOUCHER_AMOUNT = 500
FARE_WAIVER_LIMIT = 1500
PRIORITY_TIERS = {"gold", "platinum"}

# Delay Compensation Rule thresholds. Both are STRICT ">" comparisons: the
# data pack says "under 3 hours" / "more than 3 hours" / "more than 5 hours",
# so a delay of exactly 3h or exactly 5h does NOT cross the boundary.
DELAY_LOUNGE_HOURS = 3
DELAY_HOTEL_HOURS = 5

# The only effects this agent may ever produce. Enforced by _verdict(): a
# verdict carrying any action type outside this set is a programming error
# and raises rather than reaching the ledger.
ALLOWED_ACTION_TYPES = {
    "provide_status",
    "issue_meal_voucher",
    "grant_lounge_access",
    "arrange_hotel_delayed_hours",
    "rebook_next_available",
    "rebook_specific_flight",
    "initiate_refund",
}

# Customer request types the authority gate knows how to evaluate. Anything
# else falls through to an escalation.
KNOWN_REQUEST_TYPES = {
    "provide_status", "refund", "rebook", "compensation", "hotel",
    "upgrade", "compensation_beyond_policy", "goodwill",
}

VALID_STATUSES = {"execute", "decline", "escalate", "clarify"}


@dataclass
class Entitlement:
    """What the delay compensation rule grants for a given delay length."""
    meal_voucher: int = 0
    lounge: bool = False
    hotel_hours: float = 0.0  # >0 only when delay exceeds 5h

    def as_actions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.meal_voucher:
            out.append({"type": "issue_meal_voucher", "amount": self.meal_voucher})
        if self.lounge:
            out.append({"type": "grant_lounge_access"})
        if self.hotel_hours > 0:
            out.append({"type": "arrange_hotel_delayed_hours",
                        "hours": float(self.hotel_hours)})
        return out


@dataclass
class Verdict:
    """Result of running one requested action through the authority gate."""
    request_type: str
    status: str                 # "execute" | "decline" | "escalate" | "clarify"
    rule: str = ""              # name of the rule that decided this
    reason: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


def _verdict(request_type: str, status: str, **kw: Any) -> Verdict:
    """Construct a Verdict, enforcing the allowed-action list.

    This is the teeth behind ALLOWED_ACTION_TYPES: no code path can emit an
    effect that is not on the data pack's allowed list, and only an
    "execute" verdict may carry actions at all.
    """
    if status not in VALID_STATUSES:
        raise ValueError("invalid verdict status: {!r}".format(status))
    actions = kw.get("actions") or []
    for a in actions:
        atype = a.get("type")
        if atype not in ALLOWED_ACTION_TYPES:
            raise ValueError("action type not on the allowed list: {!r}".format(atype))
    if actions and status != "execute":
        raise ValueError("only an 'execute' verdict may carry actions (got {!r})".format(status))
    return Verdict(request_type, status, **kw)


def delay_compensation(delay_hours: Optional[float]) -> Entitlement:
    """The Delay Compensation Rule, exactly as written in the data pack."""
    if not delay_hours or delay_hours <= 0:
        return Entitlement()
    e = Entitlement(meal_voucher=MEAL_VOUCHER_AMOUNT)   # under 3h: meal voucher
    if delay_hours > DELAY_LOUNGE_HOURS:
        e.lounge = True                                 # more than 3h: + lounge
    if delay_hours > DELAY_HOTEL_HOURS:
        e.hotel_hours = float(delay_hours)              # more than 5h: + hotel, delayed hours ONLY
    return e


def entitle_cancellation(booking: dict[str, Any]) -> Verdict:
    """Cancellation Rebooking Rule: customer's choice of free rebooking or full refund.

    Validates that the booking actually qualifies rather than asserting it.
    The rule applies only to a cancellation the AIRLINE caused.
    """
    booking = booking or {}
    disruption = booking.get("disruption") or {}
    if booking.get("status") != "cancelled":
        return _verdict("cancellation_resolution", "decline",
                        rule="cancellation_rebooking",
                        reason="This booking is not cancelled, so the cancellation "
                               "rebooking rule does not apply.")
    if disruption.get("caused_by") != "airline":
        return _verdict("cancellation_resolution", "decline",
                        rule="prohibited_exception",
                        reason="The cancellation was not airline-caused; the agent "
                               "may not make an exception.")
    return _verdict(
        "cancellation_resolution",
        "clarify",
        rule="cancellation_rebooking",
        reason="Airline-caused cancellation: the customer is entitled to a free "
               "rebooking on the next available flight within 24 hours, or a full "
               "refund. Customer's choice.",
        payload={"options": ["rebook_next_available", "initiate_refund"]},
    )


def get_priority_rebooking(tier: str) -> bool:
    """Loyalty Tier Rule: Gold/Platinum get priority rebooking, nothing more."""
    return str(tier).lower() in PRIORITY_TIERS


def evaluate_request(req: dict[str, Any], ctx: dict[str, Any]) -> Verdict:
    """The single authority gate. Every requested action passes through here
    before anything executes. `ctx` carries the booking, the customer tier,
    whether the disruption is airline-caused, and the delay length."""
    rtype = req.get("type", "")
    booking = ctx.get("booking") or {}
    disruption = booking.get("disruption") or {}
    airline_caused = bool(disruption.get("caused_by") == "airline")
    delay_hours = disruption.get("delay_hours")
    tier = (ctx.get("customer") or {}).get("loyalty_tier", "")
    status = booking.get("status")

    # ---- no booking resolved: never guess -------------------------------------
    if not booking and rtype in KNOWN_REQUEST_TYPES:
        return _verdict(rtype or "unknown", "escalate", rule="authority_gate",
                        reason="No affected booking could be resolved for this "
                               "customer; a human agent must review.")

    # ---- status / booking info: always allowed --------------------------------
    if rtype == "provide_status":
        return _verdict("provide_status", "execute", rule="allowed_actions",
                        reason="Providing the customer's own booking and flight status.",
                        actions=[{"type": "provide_status"}])

    # ---- refund ---------------------------------------------------------------
    if rtype == "refund":
        method = req.get("payment_method", "original")
        if method != "original":
            return _verdict("refund", "escalate", rule="refund_processing",
                            reason="Refunds can only be issued to the original "
                                   "payment method; the agent may not process otherwise.")
        if not airline_caused or status != "cancelled":
            if req.get("insisting"):
                return _verdict("refund", "escalate", rule="prohibited_exception",
                                reason="Refund requested for a non-airline-caused "
                                       "situation; exceptions need a human agent.")
            return _verdict("refund", "decline", rule="refund_processing",
                            reason="Full refunds apply to airline-caused cancellations.")
        return _verdict("refund", "execute", rule="refund_processing",
                        reason="Airline-caused cancellation: full refund, processed "
                               "within 7 business days to the original payment method.",
                        actions=[{"type": "initiate_refund",
                                  "scope": req.get("scope", "cancelled_sector")}])

    # ---- rebooking ------------------------------------------------------------
    if rtype == "rebook":
        target = req.get("target", "next_available")
        fare_difference = req.get("fare_difference") or 0
        waiver_requested = bool(req.get("waiver_requested"))
        priority = get_priority_rebooking(tier)
        # We hold no fare data, so the fare difference is whatever the customer
        # told us. Provenance travels with the verdict so the ledger and any
        # escalation ticket record that it was never independently verified.
        fare_src = req.get("fare_difference_source", "customer_stated")

        # A waiver was asked for but no amount could be established. Never
        # guess it, and never quietly rebook onto a different flight instead.
        if waiver_requested and fare_difference <= 0 and target != "next_available":
            return _verdict("rebook", "escalate", rule="fare_difference",
                            reason="A fare-difference waiver was requested but no "
                                   "amount could be established; a human agent must "
                                   "confirm the fare difference.",
                            payload={"fare_difference_source": fare_src})

        # Free rebooking on the NEXT AVAILABLE flight: airline-caused only.
        if target == "next_available" or fare_difference <= 0:
            if airline_caused:
                return _verdict("rebook", "execute", rule="cancellation_rebooking",
                                reason="Free rebooking on the next available flight "
                                       "within 24 hours."
                                + (" Priority rebooking applies ("
                                   + str(tier) + " tier)." if priority else ""),
                                actions=[{"type": "rebook_next_available",
                                          "priority": priority}])
            if req.get("insisting"):
                return _verdict("rebook", "escalate", rule="prohibited_exception",
                                reason="Exception requested for a non-airline-caused "
                                       "disruption; needs a human agent.")
            return _verdict("rebook", "decline", rule="fare_difference",
                            reason="Free rebooking applies to airline-caused "
                                   "disruptions only; a voluntary change is payable "
                                   "by the customer.")

        # The customer wants a SPECIFIC higher-fare flight.
        #
        # Who is expected to absorb the difference is NOT a judgement we leave
        # to the language model. When the airline caused the disruption, asking
        # to be moved to another flight is implicitly asking us to absorb the
        # difference -- the same question an explicit waiver request asks. Both
        # therefore run through the agent's waiver authority, so Scenario 3
        # escalates on the amount alone rather than on how the request was
        # phrased.
        seeks_waiver = waiver_requested or airline_caused
        if seeks_waiver:
            if fare_difference <= FARE_WAIVER_LIMIT:
                return _verdict("rebook", "execute", rule="fare_difference",
                                reason="Fare difference of Rs {:,} waived (within the "
                                       "agent's Rs {:,} limit).".format(
                                           fare_difference, FARE_WAIVER_LIMIT),
                                actions=[{"type": "rebook_specific_flight",
                                          "fare_difference_waived": fare_difference,
                                          "fare_difference_source": fare_src}],
                                payload={"fare_difference_source": fare_src})
            return _verdict("rebook", "escalate", rule="fare_difference",
                            reason="Waiving a fare difference of Rs {:,} exceeds the "
                                   "agent's Rs {:,} limit; supervisor approval is "
                                   "required. Free rebooking on the next available "
                                   "flight within 24 hours remains available at no "
                                   "charge.".format(fare_difference, FARE_WAIVER_LIMIT),
                            payload={"fare_difference_source": fare_src})

        # Voluntary change, not airline-caused: the customer pays the difference.
        return _verdict("rebook", "execute", rule="fare_difference",
                        reason="Rebooking confirmed; the fare difference of Rs {:,} is "
                               "payable by the customer.".format(fare_difference),
                        actions=[{"type": "rebook_specific_flight",
                                  "fare_difference_payable": fare_difference,
                                  "fare_difference_source": fare_src}],
                        payload={"fare_difference_source": fare_src})

    # ---- compensation / vouchers ----------------------------------------------
    if rtype == "compensation":
        if not airline_caused:
            if req.get("insisting"):
                return _verdict("compensation", "escalate", rule="prohibited_exception",
                                reason="Compensation exception requested for a "
                                       "non-airline-caused situation; needs a human agent.")
            return _verdict("compensation", "decline", rule="delay_compensation",
                            reason="Standard compensation applies to airline-caused "
                                   "disruptions only.")
        ent = delay_compensation(delay_hours)
        if not ent.meal_voucher:
            return _verdict("compensation", "decline", rule="delay_compensation",
                            reason="No compensation applies (no qualifying delay).")
        return _verdict("compensation", "execute", rule="delay_compensation",
                        reason="Standard compensation for a {}-hour delay.".format(delay_hours),
                        actions=ent.as_actions())

    # ---- hotel ----------------------------------------------------------------
    if rtype == "hotel":
        full_night = bool(req.get("full_night"))
        if not airline_caused or not delay_hours or delay_hours <= DELAY_HOTEL_HOURS:
            if req.get("insisting"):
                return _verdict("hotel", "escalate", rule="prohibited_compensation",
                                reason="Hotel accommodation requested beyond the "
                                       "policy threshold; needs a human agent.")
            # Be specific about WHY. Telling a customer whose flight was
            # CANCELLED that "hotels need a delay over 5 hours" is technically
            # true and completely unhelpful.
            if not airline_caused:
                why = ("Hotel accommodation applies to airline-caused delays only.")
            elif status == "cancelled" or not delay_hours:
                why = ("This booking was cancelled rather than delayed, so the delay "
                       "compensation rule does not apply. The cancellation entitles "
                       "the customer to free rebooking or a full refund instead.")
            else:
                why = ("Hotel accommodation applies only when a delay exceeds {} "
                       "hours; this delay is {}h.".format(DELAY_HOTEL_HOURS, delay_hours))
            return _verdict("hotel", "decline", rule="delay_compensation", reason=why)
        if full_night:
            if req.get("insisting"):
                return _verdict("hotel", "escalate", rule="prohibited_compensation",
                                reason="Full-night stay requested beyond the stated "
                                       "policy (delayed hours only); needs a human agent.")
            return _verdict("hotel", "decline", rule="delay_compensation",
                            reason="Hotel accommodation covers the delayed hours only "
                                   "({}h), not a full night's stay.".format(delay_hours))
        return _verdict("hotel", "execute", rule="delay_compensation",
                        reason="Hotel arranged covering the {} delayed hours.".format(delay_hours),
                        actions=[{"type": "arrange_hotel_delayed_hours",
                                  "hours": float(delay_hours)}])

    # ---- anything beyond stated policy (upgrades, extra comp, goodwill) --------
    if rtype in {"upgrade", "compensation_beyond_policy", "goodwill"}:
        if req.get("insisting"):
            return _verdict(rtype, "escalate", rule="prohibited_compensation",
                            reason="Compensation beyond the stated policy amounts "
                                   "cannot be approved by the agent; a human agent "
                                   "must decide.")
        return _verdict(rtype, "decline", rule="prohibited_compensation",
                        reason="Beyond the stated policy: the agent may not approve "
                               "compensation beyond the standard amounts.")

    # ---- unknown request type -------------------------------------------------
    return _verdict(rtype or "unknown", "escalate", rule="authority_gate",
                    reason="Request not on the allowed action list; a human agent "
                           "must handle it.")
