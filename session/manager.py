# session/manager.py
"""增强版会话管理器 - 支持跨 Channel 统一会话"""

import json
import sqlite3
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from function.func_summary import MessageSummary

logger = logging.getLogger("SessionManager")


@dataclass
class SessionConfig:
    """Session 配置 - 绑定到会话的设置"""

    model_id: int | None = None  # 绑定的模型 ID
    system_prompt: str | None = None  # 自定义 system prompt
    persona: str | None = None  # 人设文本
    max_history: int = 30  # 历史消息限制
    extra: dict = field(default_factory=dict)  # 扩展配置

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "system_prompt": self.system_prompt,
            "persona": self.persona,
            "max_history": self.max_history,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionConfig":
        return cls(
            model_id=data.get("model_id"),
            system_prompt=data.get("system_prompt"),
            persona=data.get("persona"),
            max_history=data.get("max_history", 30),
            extra=data.get("extra", {}),
        )


@dataclass
class Session:
    """增强版会话对象 - 管理单个对话的完整状态"""

    key: str  # 统一会话 key (如 "user:john" 或 "group:test")
    config: SessionConfig = field(default_factory=SessionConfig)
    messages: list[dict[str, Any]] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)  # 别名集合 (如 {"wechat:wxid_xxx", "local:john"})
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """添加消息"""
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                **kwargs,
            }
        )
        self.updated_at = datetime.now()

    def add_tool_call(
        self, role: str, content: str | None, tool_calls: list[dict]
    ) -> None:
        """添加带工具调用的消息"""
        self.messages.append(
            {
                "role": role,
                "content": content or "",
                "tool_calls": tool_calls,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.updated_at = datetime.now()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """添加工具结果"""
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int | None = None) -> list[dict]:
        """获取最近的消息历史"""
        limit = max_messages or self.config.max_history
        return self.messages[-limit:]

    def clear(self) -> None:
        """清空消息"""
        self.messages.clear()
        self.updated_at = datetime.now()

    def bind_alias(self, alias: str) -> None:
        """绑定别名"""
        self.aliases.add(alias)
        self.updated_at = datetime.now()

    def unbind_alias(self, alias: str) -> None:
        """解绑别名"""
        self.aliases.discard(alias)
        self.updated_at = datetime.now()


class SessionManager:
    """增强版会话管理器

    支持:
    - 跨 Channel 统一会话（通过别名映射）
    - Session 配置持久化
    - 绑定模型/人设/system prompt
    """

    def __init__(
        self,
        message_summary: "MessageSummary | None" = None,
        bot_id: str = "",
        db_path: str = "data/message_history.db",
    ):
        self.message_summary = message_summary
        self.bot_id = bot_id
        self.db_path = db_path
        self._cache: dict[str, Session] = {}  # key -> Session
        self._alias_map: dict[str, str] = {}  # alias -> key
        self._init_db()
        self._load_sessions()

    def _init_db(self) -> None:
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        key TEXT PRIMARY KEY,
                        config TEXT NOT NULL DEFAULT '{}',
                        aliases TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"初始化 session 表失败: {e}")

    def _load_sessions(self) -> None:
        """从数据库加载所有 session 配置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM sessions")
                for row in cursor:
                    key = row["key"]
                    config_data = json.loads(row["config"] or "{}")
                    aliases_data = json.loads(row["aliases"] or "[]")

                    session = Session(
                        key=key,
                        config=SessionConfig.from_dict(config_data),
                        aliases=set(aliases_data),
                    )
                    self._cache[key] = session

                    # 建立别名映射
                    for alias in session.aliases:
                        self._alias_map[alias] = key

            logger.info(f"已加载 {len(self._cache)} 个 session 配置")
        except Exception as e:
            logger.error(f"加载 session 失败: {e}")

    def _save_session(self, session: Session) -> None:
        """保存 session 到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions (key, config, aliases, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session.key,
                        json.dumps(session.config.to_dict(), ensure_ascii=False),
                        json.dumps(list(session.aliases), ensure_ascii=False),
                        session.created_at.isoformat(),
                        session.updated_at.isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"保存 session 失败: {e}")

    def resolve_key(self, alias: str) -> str:
        """解析别名到统一 key

        如果别名已绑定到某个 session，返回该 session 的 key
        否则返回别名本身作为 key
        """
        return self._alias_map.get(alias, alias)

    def get_or_create(
        self,
        key_or_alias: str,
        max_history: int = 30,
        load_history: bool = True,
    ) -> Session:
        """获取或创建会话

        Args:
            key_or_alias: 会话标识或别名（如 "wechat:wxid_xxx" 或 "user:john"）
            max_history: 从数据库加载的最大历史消息数
            load_history: 是否从 MessageSummary 加载历史

        Returns:
            Session 对象
        """
        # 解析别名
        key = self.resolve_key(key_or_alias)

        if key in self._cache:
            return self._cache[key]

        # 创建新 session
        session = Session(key=key)
        session.config.max_history = max_history

        # 如果输入是别名且不等于 key，自动绑定
        if key_or_alias != key:
            session.aliases.add(key_or_alias)

        # 从 MessageSummary 加载历史消息
        if load_history and self.message_summary:
            chat_id = key.split(":", 1)[1] if ":" in key else key
            history = self.message_summary.get_messages(chat_id)
            for msg in history[-max_history:]:
                role = "assistant" if msg.get("sender_wxid") == self.bot_id else "user"
                content = msg.get("content", "")
                if content:
                    session.messages.append(
                        {
                            "role": role,
                            "content": content,
                            "timestamp": msg.get("time", ""),
                            "sender_name": msg.get("sender", ""),
                        }
                    )

        self._cache[key] = session
        return session

    def get(self, key_or_alias: str) -> Session | None:
        """获取已存在的会话"""
        key = self.resolve_key(key_or_alias)
        return self._cache.get(key)

    def bind(self, session_key: str, alias: str) -> Session:
        """将别名绑定到指定 session

        Args:
            session_key: 目标 session 的 key（如 "user:john"）
            alias: 要绑定的别名（如 "wechat:wxid_xxx"）

        Returns:
            绑定后的 Session 对象
        """
        # 如果别名已绑定到其他 session，先解绑
        if alias in self._alias_map:
            old_key = self._alias_map[alias]
            if old_key != session_key and old_key in self._cache:
                self._cache[old_key].unbind_alias(alias)
                self._save_session(self._cache[old_key])

        # 获取或创建目标 session
        session = self.get_or_create(session_key, load_history=False)
        session.bind_alias(alias)
        self._alias_map[alias] = session_key
        self._save_session(session)

        logger.info(f"已绑定 {alias} -> {session_key}")
        return session

    def unbind(self, alias: str) -> bool:
        """解除别名绑定

        Returns:
            是否成功解绑
        """
        if alias not in self._alias_map:
            return False

        key = self._alias_map.pop(alias)
        if key in self._cache:
            self._cache[key].unbind_alias(alias)
            self._save_session(self._cache[key])

        logger.info(f"已解绑 {alias}")
        return True

    def set_config(
        self,
        key_or_alias: str,
        model_id: int | None = None,
        system_prompt: str | None = None,
        persona: str | None = None,
        max_history: int | None = None,
        **extra,
    ) -> Session:
        """设置 session 配置

        Args:
            key_or_alias: 会话标识或别名
            model_id: 绑定的模型 ID
            system_prompt: 自定义 system prompt
            persona: 人设文本
            max_history: 历史消息限制
            **extra: 扩展配置

        Returns:
            更新后的 Session 对象
        """
        session = self.get_or_create(key_or_alias, load_history=False)

        if model_id is not None:
            session.config.model_id = model_id
        if system_prompt is not None:
            session.config.system_prompt = system_prompt
        if persona is not None:
            session.config.persona = persona
        if max_history is not None:
            session.config.max_history = max_history
        if extra:
            session.config.extra.update(extra)

        session.updated_at = datetime.now()
        self._save_session(session)
        return session

    def remove(self, key_or_alias: str) -> bool:
        """移除会话

        Returns:
            是否成功移除
        """
        key = self.resolve_key(key_or_alias)
        if key not in self._cache:
            return False

        session = self._cache.pop(key)

        # 清理别名映射
        for alias in session.aliases:
            self._alias_map.pop(alias, None)

        # 从数据库删除
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM sessions WHERE key = ?", (key,))
                conn.commit()
        except Exception as e:
            logger.error(f"删除 session 失败: {e}")

        return True

    def list_sessions(self) -> list[dict]:
        """列出所有 session 信息"""
        result = []
        for key, session in self._cache.items():
            result.append({
                "key": key,
                "aliases": list(session.aliases),
                "model_id": session.config.model_id,
                "max_history": session.config.max_history,
                "message_count": len(session.messages),
                "updated_at": session.updated_at.isoformat(),
            })
        return result

    def clear_all(self) -> None:
        """清空所有会话缓存（不删除数据库）"""
        self._cache.clear()
        self._alias_map.clear()
