import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from commands.context import MessageContext
    from robot import Robot

PERSONA_PREFIX = "## 角色\n"


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


def fetch_persona_for_context(robot: "Robot", ctx: "MessageContext") -> Optional[str]:
    """Return persona text for the context receiver."""
    manager = getattr(robot, "persona_manager", None)
    if not manager:
        return None
    try:
        persona_text = manager.get_persona(ctx.get_receiver())
        if persona_text:
            persona_text = persona_text.strip()
        return persona_text or None
    except Exception as exc:
        robot.LOG.error(f"获取会话人设失败: {exc}", exc_info=True)
        return None


def handle_persona_command(robot: "Robot", ctx: "MessageContext") -> bool:
    """Process /set and /persona commands."""
    text = (ctx.text or "").strip()
    if not text or not text.startswith("/"):
        return False

    parts = text.split(None, 1)
    command = parts[0].lower()
    payload = parts[1] if len(parts) > 1 else ""

    at_list = ctx.msg.sender if ctx.is_group else ""
    scope_label = "本群" if ctx.is_group else "当前会话"

    manager = getattr(robot, "persona_manager", None)
    if command in {"/persona", "/set"} and not manager:
        ctx.send_text("❌ 人设功能暂不可用。", at_list)
        return True

    if command == "/persona":
        persona_text = getattr(ctx, "persona", None)
        if persona_text is None and manager:
            try:
                persona_text = manager.get_persona(ctx.get_receiver())
                if persona_text:
                    persona_text = persona_text.strip()
                setattr(ctx, "persona", persona_text)
            except Exception as exc:
                robot.LOG.error(f"查询人设失败: {exc}", exc_info=True)
                persona_text = None

        if persona_text:
            ctx.send_text(f"{scope_label}当前的人设是：\n{PERSONA_PREFIX}{persona_text}", at_list)
        else:
            ctx.send_text(f"{scope_label}当前没有设置人设，可发送“/set 你的人设描述”来设定。", at_list)
        return True

    if command != "/set":
        return False

    persona_body = payload.strip()
    chat_id = ctx.get_receiver()

    if not persona_body:
        current = getattr(ctx, "persona", None)
        if current:
            ctx.send_text(
                f"{scope_label}当前的人设是：\n{PERSONA_PREFIX}{current}\n发送“/set clear”可以清空，或重新发送“/set + 新人设”进行更新。\n也可以使用“/persona”随时查看当前人设。",
                at_list
            )
        else:
            ctx.send_text("请在 /set 后输入人设描述，例如：/set 你是一个幽默的机器人助手。", at_list)
        return True

    if persona_body.lower() in {"clear", "reset"}:
        cleared = manager.clear_persona(chat_id)
        setattr(ctx, "persona", None)
        if cleared:
            ctx.send_text(f"✅ 已清空{scope_label}的人设。", at_list)
        else:
            ctx.send_text(f"{scope_label}当前没有设置人设。", at_list)
        return True

    try:
        manager.set_persona(chat_id, persona_body, setter_wxid=ctx.msg.sender)
        persona_body = persona_body.strip()
        setattr(ctx, "persona", persona_body)
        preview, truncated = _build_preview(persona_body)
        ellipsis = "..." if truncated else ""
        ctx.send_text(
            f"✅ {scope_label}人设设定成功：\n{PERSONA_PREFIX}{preview}{ellipsis}\n如需查看完整内容，可发送“/persona”。",
            at_list
        )
    except Exception as exc:
        robot.LOG.error(f"设置人设失败: {exc}", exc_info=True)
        ctx.send_text("❌ 设置人设时遇到问题，请稍后再试。", at_list)
    return True


def _build_preview(persona: str, limit: int = 120) -> Tuple[str, bool]:
    if len(persona) <= limit:
        return persona, False
    return persona[:limit], True


def build_persona_system_prompt(chat_model, persona: Optional[str] = None, override_prompt: Optional[str] = None) -> Optional[str]:
    """Merge persona section with existing system prompt."""
    base_prompt = override_prompt if override_prompt is not None else _get_model_base_prompt(chat_model)
    return _merge_prompt_with_persona(base_prompt, persona)


def _get_model_base_prompt(chat_model) -> Optional[str]:
    if not chat_model:
        return None

    system_msg = getattr(chat_model, "system_content_msg", None)
    if isinstance(system_msg, dict):
        prompt = system_msg.get("content")
        if prompt:
            return prompt

    if hasattr(chat_model, "_base_prompt"):
        prompt = getattr(chat_model, "_base_prompt")
        if prompt:
            return prompt

    if hasattr(chat_model, "prompt"):
        prompt = getattr(chat_model, "prompt")
        if prompt:
            return prompt

    return None


def _merge_prompt_with_persona(prompt: Optional[str], persona: Optional[str]) -> Optional[str]:
    persona = (persona or "").strip()
    prompt = (prompt or "").strip() if prompt else ""

    if persona:
        persona_section = f"{PERSONA_PREFIX}{persona}"
        if prompt:
            return f"{persona_section}\n\n{prompt}"
        return persona_section

    return prompt or None
