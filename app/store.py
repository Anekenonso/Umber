"""SQLite-backed conversation state store for Umber (Phase 6, 25 & Stage 3).

Persists conversation state across stateless webhook calls:
- Tracks current ConversationState per sender (phone number).
- Tracks photo retake attempts (Phase 9: max 1 retake before fallback).
- Stores last analysis results (skin color hex, undertone).
- Uses SQLite with lightweight, synchronous connection management.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from app.states import ConversationState

DB_PATH = Path(__file__).resolve().parent.parent / "umber_state.db"


class ConversationSession:
    def __init__(
        self,
        sender_id: str,
        state: ConversationState = ConversationState.RECEIVED,
        photo_retries: int = 0,
        context: Optional[Dict[str, Any]] = None,
        last_updated: Optional[str] = None,
    ):
        self.sender_id = sender_id
        self.state = state
        self.photo_retries = photo_retries
        self.context = context or {}
        self.last_updated = last_updated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "state": self.state.value if isinstance(self.state, ConversationState) else str(self.state),
            "photo_retries": self.photo_retries,
            "context": self.context,
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
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def get_session(self, sender_id: str) -> ConversationSession:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT sender_id, state, photo_retries, context, last_updated FROM sessions WHERE sender_id = ?",
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
                last_updated=row["last_updated"],
            )

    def save_session(self, session: ConversationSession):
        state_str = session.state.value if isinstance(session.state, ConversationState) else str(session.state)
        context_str = json.dumps(session.context)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (sender_id, state, photo_retries, context, last_updated)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(sender_id) DO UPDATE SET
                    state = excluded.state,
                    photo_retries = excluded.photo_retries,
                    context = excluded.context,
                    last_updated = CURRENT_TIMESTAMP
                """,
                (session.sender_id, state_str, session.photo_retries, context_str),
            )
            conn.commit()

    def reset_session(self, sender_id: str) -> ConversationSession:
        session = ConversationSession(sender_id=sender_id, state=ConversationState.RECEIVED, photo_retries=0)
        self.save_session(session)
        return session

    def clear_all(self):
        """Used in test fixtures."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions")
            conn.commit()


# Global default instance
store = ConversationStore()
