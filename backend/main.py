"""SkyAssist — FastAPI service.

Endpoints:
  POST /api/chat            SSE stream: session, sentiment, token, action, done
  GET  /api/customers       the three profiles (masked) for the picker
  GET  /api/sessions        every session (audit trail index)
  GET  /api/sessions/{id}   full conversation record incl. per-turn verdicts
  GET  /api/actions         action ledger (all, or filter: ?session_id=)
  GET  /api/tickets         escalation tickets (all, or filter: ?session_id=)
  GET  /healthz             status + LLM provider
  /                         serves the built React frontend (frontend/dist)
"""
from __future__ import annotations

import json
import os
import queue as thread_queue
import traceback
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config  # noqa: F401  -- loads .env before anything reads os.getenv
from .agent import run_turn
from .data import loader
from .llm.provider import ProviderError, get_provider
from .records.ledger import Ledger

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().parent / "data" / "skyassist.db"))
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="SkyAssist", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ledger = Ledger(DB_PATH)


class ChatBody(BaseModel):
    session_id: Optional[str] = None
    customer_id: str
    message: str


@app.get("/healthz")
def healthz():
    """Liveness probe. Reports the configured engine without calling it."""
    try:
        provider = get_provider()
        name = getattr(provider, "name", "unknown")
        model = getattr(provider, "model", "built-in")
    except ProviderError as e:
        name, model = "misconfigured", e.message
    return {
        "status": "ok",
        "llm_provider": name,
        "llm_model": model,
        "exercise_date": loader.load_datapack()["exercise_date"],
    }


@app.get("/api/customers")
def customers():
    """The three profiles for the picker, each with its disrupted booking.

    The sidebar shows the flight and what went wrong, so the reviewer can see
    at a glance which scenario each customer represents.
    """
    out = []
    for c in loader.get_customers():
        booking = loader.get_disrupted_booking(c["id"]) or {}
        disruption = booking.get("disruption") or {}
        status = booking.get("status")
        if disruption.get("type") == "delay" and disruption.get("delay_hours"):
            summary = "delayed {}h".format(disruption["delay_hours"])
        elif status == "cancelled":
            summary = "cancelled"
        else:
            summary = status or ""
        out.append({
            "id": c["id"],
            "name": c["name"],
            "loyalty_tier": c["loyalty_tier"],
            "booking_reference": c["booking_reference"],
            "flight": booking.get("flight"),
            "route_display": booking.get("route_display"),
            "status_summary": summary,
        })
    return out


@app.post("/api/chat")
def chat(body: ChatBody):
    if not loader.get_customer(body.customer_id):
        raise HTTPException(404, "Unknown customer")

    session_id = body.session_id
    if not session_id or not _ledger.get_session(session_id):
        session_id = _ledger.create_session(body.customer_id)

    def event_stream():
        q: thread_queue.Queue = thread_queue.Queue()

        def worker():
            try:
                run_turn(session_id, body.customer_id, body.message,
                         ledger=_ledger, queue=q)
            except ProviderError as e:
                # Already phrased for a customer. Log the real cause.
                traceback.print_exception(e.cause or e)
                q.put(("error", {"detail": e.message}))
            except Exception as e:  # keep the stream alive even on failure
                # Never leak an exception string to the browser: it can carry
                # URLs, model names and internal paths.
                traceback.print_exception(e)
                q.put(("error", {"detail": "Something went wrong on our side "
                                           "handling that message. Please try again."}))
            finally:
                q.put(None)

        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/sessions")
def sessions():
    """Audit-trail index: every session this deployment has handled."""
    return _ledger.get_sessions()


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    s = _ledger.get_session(session_id)
    if not s:
        raise HTTPException(404, "Unknown session")
    customer = loader.get_customer(s["customer_id"]) or {}
    return {
        "session_id": session_id,
        "customer": {"id": customer.get("id"), "name": customer.get("name"),
                     "loyalty_tier": customer.get("loyalty_tier")},
        "turns": _ledger.get_turns(session_id),
    }


@app.get("/api/actions")
def actions(session_id: Optional[str] = None):
    if session_id:
        if not _ledger.get_session(session_id):
            raise HTTPException(404, "Unknown session")
        return _ledger.get_actions(session_id)
    return _ledger.get_all_actions()


@app.get("/api/tickets")
def tickets(session_id: Optional[str] = None):
    """Structured escalation tickets handed to human agents."""
    return _ledger.get_tickets(session_id)


# Serve the built frontend (single-service deployment). The directory is
# created if absent so that a build produced after startup is picked up without
# needing a restart.
DIST_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
