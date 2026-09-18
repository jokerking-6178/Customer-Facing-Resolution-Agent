"""API smoke tests with the mock provider (no LLM, no network)."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_customers():
    r = client.get("/api/customers")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert names == {"Priya Nair", "Arvind Kulkarni", "Meher Kaur"}


def test_unknown_customer_404():
    r = client.post("/api/chat", json={"customer_id": "nobody", "message": "hi"})
    assert r.status_code == 404


def test_chat_stream_events():
    with client.stream("POST", "/api/chat", json={
        "customer_id": "arvind_kulkarni",
        "message": "My flight SK-118 is delayed 4 hours, what compensation do I get?",
    }) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in r.iter_lines():
            if line.startswith("event: "):
                events.append(line[len("event: "):])
    assert events[0] == "session"
    assert "sentiment" in events
    assert "token" in events
    assert "action" in events
    assert events[-1] == "done"


def test_session_and_actions_endpoints():
    with client.stream("POST", "/api/chat", json={
        "customer_id": "arvind_kulkarni",
        "message": "My flight is delayed 4 hours, I want a hotel for this long delay.",
    }) as r:
        session_id = None
        for line in r.iter_lines():
            if line.startswith("data: ") and "session_id" in line:
                import json
                session_id = json.loads(line[len("data: "):])["session_id"]

    assert session_id
    r = client.get(f"/api/sessions/{session_id}")
    assert r.status_code == 200
    assert r.json()["customer"]["name"] == "Arvind Kulkarni"

    r = client.get("/api/actions", params={"session_id": session_id})
    assert r.status_code == 200
    statuses = {a["status"] for a in r.json()}
    assert "executed" in statuses
    assert "declined" in statuses   # the hotel request
