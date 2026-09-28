"""SQLite-backed conversation state store for Umber (Phase 6, 25 & Stage 3, 5).

Persists conversation state across stateless webhook calls:
- Tracks current ConversationState per sender (phone number).
- Tracks photo retake attempts (Phase 9: max 1 retake before fallback).
- Tracks escalation details (reason, timestamp, resolved status).
- Stores last analysis results and catalog matches.
- Uses SQLite with lightweight, synchronous connection management.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.states import ConversationState, EscalationReason

DB_PATH = Path(__file__).resolve().parent.parent / "umber_state.db"


class ConversationSession:
    def __init__(
        self,
        sender_id: str,
        state: ConversationState = ConversationState.RECEIVED,
        photo_retries: int = 0,
        context: Optional[Dict[str, Any]] = None,
        escalation_reason: Optional[str] = None,
        escalated_at: Optional[str] = None,
        last_updated: Optional[str] = None,
    ):
        self.sender_id = sender_id
        self.state = state
        self.photo_retries = photo_retries
        self.context = context or {}
        self.escalation_reason = escalation_reason
        self.escalated_at = escalated_at
        self.last_updated = last_updated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "state": self.state.value if isinstance(self.state, ConversationState) else str(self.state),
            "photo_retries": self.photo_retries,
            "context": self.context,
            "escalation_reason": self.escalation_reason,
            "escalated_at": self.escalated_at,
            "last_updated": self.last_updated,
        }


class ConversationStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    sender_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    photo_retries INTEGER NOT NULL DEFAULT 0,
                    context TEXT NOT NULL DEFAULT '{}',
                    escalation_reason TEXT,
                    escalated_at TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Safe column migration if existing database is present without new columns
            cursor = conn.execute("PRAGMA table_info(sessions)")
            columns = [col["name"] for col in cursor.fetchall()]
            if "escalation_reason" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN escalation_reason TEXT")
            if "escalated_at" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN escalated_at TIMESTAMP")
            conn.commit()

    def get_session(self, sender_id: str) -> ConversationSession:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT sender_id, state, photo_retries, context, escalation_reason, escalated_at, last_updated 
                FROM sessions WHERE sender_id = ?
                """,
                (sender_id,),
            ).fetchone()

            if not row:
                session = ConversationSession(sender_id=sender_id)
                self.save_session(session)
                return session

            try:
                state = ConversationState(row["state"])
            except ValueError:
                state = ConversationState.RECEIVED

            try:
                context = json.loads(row["context"]) if row["context"] else {}
            except Exception:
                context = {}

            return ConversationSession(
                sender_id=row["sender_id"],
                state=state,
                photo_retries=row["photo_retries"],
                context=context,
                escalation_reason=row["escalation_reason"],
                escalated_at=row["escalated_at"],
                last_updated=row["last_updated"],
            )

    def save_session(self, session: ConversationSession):
        state_str = session.state.value if isinstance(session.state, ConversationState) else str(session.state)
        context_str = json.dumps(session.context)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (sender_id, state, photo_retries, context, escalation_reason, escalated_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(sender_id) DO UPDATE SET
                    state = excluded.state,
                    photo_retries = excluded.photo_retries,
                    context = excluded.context,
                    escalation_reason = excluded.escalation_reason,
                    escalated_at = excluded.escalated_at,
                    last_updated = CURRENT_TIMESTAMP
                """,
                (
                    session.sender_id,
                    state_str,
                    session.photo_retries,
                    context_str,
                    session.escalation_reason,
                    session.escalated_at,
                ),
            )
            conn.commit()

    def escalate_session(self, sender_id: str, reason: str) -> ConversationSession:
        """Flag session as escalated and persist reason."""
        session = self.get_session(sender_id)
        session.state = ConversationState.ESCALATED
        session.escalation_reason = reason
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions 
                SET state = ?, escalation_reason = ?, escalated_at = CURRENT_TIMESTAMP, last_updated = CURRENT_TIMESTAMP
                WHERE sender_id = ?
                """,
                (ConversationState.ESCALATED.value, reason, sender_id),
            )
            conn.commit()
        return self.get_session(sender_id)

    def resolve_escalation(self, sender_id: str, next_state: ConversationState = ConversationState.GENERAL_REPLY) -> ConversationSession:
        """Staff resolves escalation: clears escalation flag and returns to active state."""
        session = self.get_session(sender_id)
        session.state = next_state
        session.escalation_reason = None
        session.escalated_at = None
        self.save_session(session)
        return session

    def list_escalations(self) -> List[Dict[str, Any]]:
        """List all currently escalated customer sessions for store manager dashboard."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sender_id, state, escalation_reason, escalated_at, last_updated, context
                FROM sessions 
                WHERE state = ?
                ORDER BY escalated_at DESC
                """,
                (ConversationState.ESCALATED.value,),
            ).fetchall()

            results = []
            for r in rows:
                try:
                    ctx = json.loads(r["context"]) if r["context"] else {}
                except Exception:
                    ctx = {}
                results.append({
                    "sender_id": r["sender_id"],
                    "state": r["state"],
                    "escalation_reason": r["escalation_reason"],
                    "escalated_at": r["escalated_at"],
                    "last_updated": r["last_updated"],
                    "context": ctx,
                })
            return results

    def reset_session(self, sender_id: str) -> ConversationSession:
        session = ConversationSession(
            sender_id=sender_id,
            state=ConversationState.RECEIVED,
            photo_retries=0,
            escalation_reason=None,
            escalated_at=None,
        )
        self.save_session(session)
        return session

    def clear_all(self):
        """Used in test fixtures."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions")
            conn.commit()


# Global default instance
store = ConversationStore()
