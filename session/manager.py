# session/manager.py
"""会话管理器"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from function.func_summary import MessageSummary


@dataclass
class Session:
    """会话对象 - 管理单个对话的状态"""

    key: str  # "wechat:{chat_id}"
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

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

    def get_history(self, max_messages: int = 30) -> list[dict]:
        """获取最近的消息历史"""
        return self.messages[-max_messages:]

    def clear(self) -> None:
        """清空消息"""
        self.messages.clear()
        self.updated_at = datetime.now()


class SessionManager:
    """会话管理器 - 与 MessageSummary 协作加载历史"""

    def __init__(self, message_summary: "MessageSummary", bot_wxid: str):
        self.message_summary = message_summary
        self.bot_wxid = bot_wxid
        self._cache: dict[str, Session] = {}

    def get_or_create(self, key: str, max_history: int = 100) -> Session:
        """获取或创建会话

        Args:
            key: 会话标识，格式为 "wechat:{chat_id}"
            max_history: 从数据库加载的最大历史消息数

        Returns:
            Session 对象
        """
        if key in self._cache:
            return self._cache[key]

        session = Session(key=key)

        # 从 SQLite 加载历史
        chat_id = key.split(":", 1)[1] if ":" in key else key
        if self.message_summary:
            history = self.message_summary.get_messages(chat_id)
            for msg in history[-max_history:]:
                role = (
                    "assistant"
                    if msg.get("sender_wxid") == self.bot_wxid
                    else "user"
                )
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

    def get(self, key: str) -> Session | None:
        """获取已存在的会话"""
        return self._cache.get(key)

    def remove(self, key: str) -> None:
        """移除会话"""
        self._cache.pop(key, None)

    def clear_all(self) -> None:
        """清空所有会话缓存"""
        self._cache.clear()
