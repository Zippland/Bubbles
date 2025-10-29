import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional


class PersonaManager:
    """Manage persona profiles per chat session."""

    def __init__(self, db_path: str = "data/message_history.db") -> None:
        self.LOG = logging.getLogger("PersonaManager")
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        self._connect()
        self._prepare_table()

    def _connect(self) -> None:
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                self.LOG.info(f"Created persona database directory: {db_dir}")

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.conn.cursor()
            self.LOG.info(f"PersonaManager connected to database: {self.db_path}")
        except sqlite3.Error as exc:
            self.LOG.error(f"Failed to connect persona database: {exc}")
            raise

    def _prepare_table(self) -> None:
        assert self.cursor is not None
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    chat_id TEXT PRIMARY KEY,
                    persona TEXT NOT NULL,
                    setter_wxid TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            self.LOG.error(f"Failed to ensure personas table exists: {exc}")
            raise

    def set_persona(self, chat_id: str, persona: str, setter_wxid: Optional[str] = None) -> None:
        if not chat_id:
            raise ValueError("chat_id must not be empty when setting persona")
        if persona is None:
            raise ValueError("persona must not be None when setting persona")

        persona = persona.strip()
        assert self.cursor is not None

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.cursor.execute(
                """
                INSERT INTO personas (chat_id, persona, setter_wxid, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    persona=excluded.persona,
                    setter_wxid=excluded.setter_wxid,
                    updated_at=excluded.updated_at
                """,
                (chat_id, persona, setter_wxid, timestamp),
            )
            self.conn.commit()
            self.LOG.info(f"Persona updated for chat_id={chat_id}")
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.LOG.error(f"Failed to set persona for {chat_id}: {exc}")
            raise

    def clear_persona(self, chat_id: str) -> bool:
        if not chat_id:
            return False
        assert self.cursor is not None
        try:
            self.cursor.execute("DELETE FROM personas WHERE chat_id = ?", (chat_id,))
            deleted = self.cursor.rowcount
            self.conn.commit()
            if deleted:
                self.LOG.info(f"Persona cleared for chat_id={chat_id}")
            return bool(deleted)
        except sqlite3.Error as exc:
            self.conn.rollback()
            self.LOG.error(f"Failed to clear persona for {chat_id}: {exc}")
            return False

    def get_persona(self, chat_id: str) -> Optional[str]:
        if not chat_id:
            return None
        assert self.cursor is not None
        try:
            self.cursor.execute("SELECT persona FROM personas WHERE chat_id = ?", (chat_id,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as exc:
            self.LOG.error(f"Failed to fetch persona for {chat_id}: {exc}")
            return None

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.commit()
                self.conn.close()
                self.LOG.info("PersonaManager database connection closed")
            except sqlite3.Error as exc:
                self.LOG.error(f"Failed to close persona database connection: {exc}")
