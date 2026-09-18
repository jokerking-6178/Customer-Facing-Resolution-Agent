"""Loads the data pack. This is the ONLY source of facts in the system.

The supplied pack contains no flight schedules and no fares, so this module
deliberately exposes no accessor for either. Nothing downstream can name a
replacement flight, because nothing here knows one.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "datapack.json"


@lru_cache(maxsize=1)
def load_datapack() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_customers() -> list[dict]:
    return load_datapack()["customers"]


def get_customer(customer_id: str) -> dict | None:
    for c in get_customers():
        if c["id"] == customer_id:
            return c
    return None


def get_bookings_for(customer_id: str) -> list[dict]:
    return [b for b in load_datapack()["bookings"] if b["customer_id"] == customer_id]


def get_disrupted_booking(customer_id: str) -> dict | None:
    """The one booking with a disruption, if unambiguous."""
    disrupted = [b for b in get_bookings_for(customer_id) if b.get("disruption")]
    if len(disrupted) == 1:
        return disrupted[0]
    return None


def get_rules_text() -> dict:
    return load_datapack()["rules_text"]
