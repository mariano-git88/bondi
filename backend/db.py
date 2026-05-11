"""
db.py — Persistencia SQLite para logs de conversación + feedback operador.

Tablas:
  conversations — un row por turn (user_msg + assistant_msg + tool calls).
  feedback      — rating operador (good/bad/flag) + nota libre.

Diseño:
  - SQLite local en data/bondi.db. Un solo archivo, sin servicio separado.
  - WAL mode + thread-safe lock para que backend y backoffice puedan leer
    en simultáneo sin lockup.
  - turn_id autoincremental sirve como ID único; el frontend no lo conoce.

Uso:
    from backend.db import init_db, log_turn, list_recent_turns
    init_db()
    turn_id = log_turn(session_id="abc", user_msg="...", assistant_msg="...",
                       tool_calls=[...], hard_rules_version=1)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/bondi.db")
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db() -> None:
    """Idempotente. Llamar al startup del backend y del backoffice."""
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                user_msg TEXT NOT NULL,
                assistant_msg TEXT NOT NULL,
                tool_calls_json TEXT,
                hard_rules_version INTEGER,
                meta_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
            CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversations(ts DESC);

            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                rating TEXT NOT NULL,
                note TEXT,
                operator TEXT,
                FOREIGN KEY(turn_id) REFERENCES conversations(turn_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_turn ON feedback(turn_id);
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_turn(
    session_id: str,
    user_msg: str,
    assistant_msg: str,
    tool_calls: list[dict] | None = None,
    hard_rules_version: int | None = None,
    meta: dict | None = None,
) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO conversations
               (session_id, ts, user_msg, assistant_msg, tool_calls_json, hard_rules_version, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                _now(),
                user_msg,
                assistant_msg,
                json.dumps(tool_calls or [], ensure_ascii=False),
                hard_rules_version,
                json.dumps(meta, ensure_ascii=False) if meta else None,
            ),
        )
        return cur.lastrowid


def list_recent_turns(limit: int = 100, session_id: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        if session_id:
            rows = conn.execute(
                """SELECT c.*, COUNT(f.feedback_id) AS feedback_count
                   FROM conversations c
                   LEFT JOIN feedback f ON f.turn_id = c.turn_id
                   WHERE c.session_id = ?
                   GROUP BY c.turn_id
                   ORDER BY c.ts DESC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.*, COUNT(f.feedback_id) AS feedback_count
                   FROM conversations c
                   LEFT JOIN feedback f ON f.turn_id = c.turn_id
                   GROUP BY c.turn_id
                   ORDER BY c.ts DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_turn(turn_id: int) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE turn_id = ?", (turn_id,)
        ).fetchone()
        if not row:
            return None
        fb_rows = conn.execute(
            "SELECT * FROM feedback WHERE turn_id = ? ORDER BY ts DESC", (turn_id,)
        ).fetchall()
        d = dict(row)
        d["feedback"] = [dict(fr) for fr in fb_rows]
        return d


def save_feedback(
    turn_id: int,
    rating: str,
    note: str | None = None,
    operator: str | None = None,
) -> int:
    if rating not in ("good", "bad", "flag"):
        raise ValueError(f"Rating inválido: {rating}")
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO feedback (turn_id, ts, rating, note, operator)
               VALUES (?, ?, ?, ?, ?)""",
            (turn_id, _now(), rating, note, operator),
        )
        return cur.lastrowid


def stats() -> dict:
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM conversations").fetchone()["c"]
        sessions = conn.execute("SELECT COUNT(DISTINCT session_id) c FROM conversations").fetchone()["c"]
        feedback_total = conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"]
        good = conn.execute("SELECT COUNT(*) c FROM feedback WHERE rating='good'").fetchone()["c"]
        bad = conn.execute("SELECT COUNT(*) c FROM feedback WHERE rating='bad'").fetchone()["c"]
        return {
            "turns": total,
            "sessions": sessions,
            "feedback_total": feedback_total,
            "feedback_good": good,
            "feedback_bad": bad,
        }
