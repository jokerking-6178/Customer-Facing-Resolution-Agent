"""Append-only action ledger + conversation transcripts (SQLite).

Every executed, declined, or escalated action is recorded here together
with the authorizing rule. Rows are never updated or deleted.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    started_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    customer_message TEXT NOT NULL,
    agent_message TEXT NOT NULL,
    intent TEXT,
    sentiment TEXT,
    verdicts_json TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id INTEGER,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL,           -- executed | declined | escalated | clarified
    detail TEXT,
    rule TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id INTEGER,
    customer_id TEXT,
    priority TEXT NOT NULL,         -- high | normal
    status TEXT NOT NULL,           -- open
    summary TEXT,
    packet_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def _now() -> float:
    return time.time()


class Ledger:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- sessions ---------------------------------------------------------------
    def create_session(self, customer_id: str) -> str:
        sid = "SES-" + uuid.uuid4().hex[:8]
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, customer_id, started_at) VALUES (?, ?, ?)",
                (sid, customer_id, _now()),
            )
            self._conn.commit()
        return sid

    def get_session(self, session_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT id, customer_id, started_at FROM sessions WHERE id = ?", (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "customer_id": row[1], "started_at": row[2]}

    # -- turns ------------------------------------------------------------------
    def next_turn_index(self, session_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(idx), 0) + 1 FROM turns WHERE session_id = ?", (session_id,)
        )
        return cur.fetchone()[0]

    def record_turn(self, session_id: str, idx: int, customer_message: str,
                    agent_message: str, intent: str, sentiment: str,
                    verdicts: list[dict]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO turns (session_id, idx, customer_message, agent_message, "
                "intent, sentiment, verdicts_json, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, idx, customer_message, agent_message, intent, sentiment,
                 json.dumps(verdicts), _now()),
            )
            self._conn.commit()
        return cur.lastrowid

    def get_turns(self, session_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT idx, customer_message, agent_message, intent, sentiment, ts, "
            "verdicts_json FROM turns WHERE session_id = ? ORDER BY idx", (session_id,)
        )
        out = []
        for row in cur.fetchall():
            out.append({
                "idx": row[0], "customer_message": row[1], "agent_message": row[2],
                "intent": row[3], "sentiment": row[4], "ts": row[5],
                "verdicts": json.loads(row[6]) if row[6] else [],
            })
        return out

    def get_messages(self, session_id: str) -> list[dict]:
        """Conversation as [{"role": "customer"|"agent", "content": ...}]"""
        msgs = []
        for t in self.get_turns(session_id):
            msgs.append({"role": "customer", "content": t["customer_message"]})
            msgs.append({"role": "agent", "content": t["agent_message"]})
        return msgs

    # -- actions ----------------------------------------------------------------
    def record_action(self, session_id: str, turn_id: int | None, action_type: str,
                      status: str, detail: str, rule: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO actions (session_id, turn_id, action_type, status, detail, rule, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, turn_id, action_type, status, detail, rule, _now()),
            )
            self._conn.commit()
        return cur.lastrowid

    def get_actions(self, session_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, turn_id, action_type, status, detail, rule, ts FROM actions "
            "WHERE session_id = ? ORDER BY id", (session_id,)
        )
        return [
            {"id": r[0], "turn_id": r[1], "type": r[2], "status": r[3],
             "detail": r[4], "rule": r[5], "ts": r[6]}
            for r in cur.fetchall()
        ]

    def has_action(self, session_id: str, action_type: str, status: str = "executed") -> bool:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM actions WHERE session_id = ? AND action_type = ? AND status = ?",
            (session_id, action_type, status),
        )
        return cur.fetchone()[0] > 0

    def count_actions(self, session_id: str, action_type: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM actions WHERE session_id = ? AND action_type = ?",
            (session_id, action_type),
        )
        return cur.fetchone()[0]

    def get_all_actions(self, limit: int = 500) -> list[dict]:
        """The whole audit trail, newest first."""
        cur = self._conn.execute(
            "SELECT id, session_id, turn_id, action_type, status, detail, rule, ts "
            "FROM actions ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [
            {"id": r[0], "session_id": r[1], "turn_id": r[2], "type": r[3],
             "status": r[4], "detail": r[5], "rule": r[6], "ts": r[7]}
            for r in cur.fetchall()
        ]

    def get_sessions(self, limit: int = 200) -> list[dict]:
        cur = self._conn.execute(
            "SELECT s.id, s.customer_id, s.started_at, "
            "(SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id), "
            "(SELECT COUNT(*) FROM actions a WHERE a.session_id = s.id) "
            "FROM sessions s ORDER BY s.started_at DESC LIMIT ?", (limit,)
        )
        return [
            {"id": r[0], "customer_id": r[1], "started_at": r[2],
             "turns": r[3], "actions": r[4]}
            for r in cur.fetchall()
        ]

    # -- escalation tickets -----------------------------------------------------
    def create_ticket(self, session_id: str, turn_id: int | None, customer_id: str,
                      priority: str, summary: str, packet: dict) -> str:
        """Persist an escalation as a structured ticket and return its reference."""
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM tickets")
            tid = "SKY-{:04d}".format(cur.fetchone()[0] + 1)
            self._conn.execute(
                "INSERT INTO tickets (id, session_id, turn_id, customer_id, priority, "
                "status, summary, packet_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (tid, session_id, turn_id, customer_id, priority, summary,
                 json.dumps(packet, default=str), _now()),
            )
            self._conn.commit()
        return tid

    def get_tickets(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            cur = self._conn.execute(
                "SELECT id, session_id, turn_id, customer_id, priority, status, "
                "summary, packet_json, created_at FROM tickets WHERE session_id = ? "
                "ORDER BY created_at DESC", (session_id,)
            )
        else:
            cur = self._conn.execute(
                "SELECT id, session_id, turn_id, customer_id, priority, status, "
                "summary, packet_json, created_at FROM tickets ORDER BY created_at DESC"
            )
        return [
            {"id": r[0], "session_id": r[1], "turn_id": r[2], "customer_id": r[3],
             "priority": r[4], "status": r[5], "summary": r[6],
             "packet": json.loads(r[7]), "created_at": r[8]}
            for r in cur.fetchall()
        ]

    def close(self):
        self._conn.close()
