# agent/context.py
"""Agent 上下文"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from session.manager import Session


@dataclass
class AgentContext:
    """Agent 上下文 - 封装一次对话所需的所有信息"""

    # 核心依赖
    session: "Session"
    chat_id: str  # 会话 ID（群 ID 或私聊用户 ID）
    sender_wxid: str  # 消息发送者 wxid
    sender_name: str  # 消息发送者昵称
    robot_wxid: str  # 机器人 wxid
    is_group: bool  # 是否群聊

    # 可选依赖
    robot: Any = None  # Robot 实例
    logger: Any = None  # 日志记录器
    config: Any = None  # 配置对象

    # 状态
    specific_max_history: int = 30  # 历史消息数量限制
    persona: str | None = None  # 人设文本

    # 内部
    _send_text_func: Callable[[str, str, bool], Awaitable[None]] | None = field(
        default=None, repr=False
    )

    async def send_text(
        self, content: str, at_list: str = "", record_message: bool = True
    ) -> bool:
        """发送文本消息"""
        if self._send_text_func:
            try:
                await self._send_text_func(content, at_list, record_message)
                return True
            except Exception as e:
                if self.logger:
                    self.logger.error(f"发送消息失败: {e}")
                return False
        return False

    async def send_status(self, status: str) -> None:
        """发送状态提示（不记录到历史）"""
        await self.send_text(status, record_message=False)

    def get_receiver(self) -> str:
        """获取消息接收者 ID"""
        return self.chat_id
