# channel/base.py
"""Channel 抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Callable, Any


class MessageType(IntEnum):
    """消息类型"""
    TEXT = 1
    IMAGE = 3
    VOICE = 34
    VIDEO = 43
    EMOJI = 47
    LOCATION = 48
    LINK = 49  # 链接/引用/小程序等
    FRIEND_REQUEST = 37
    SYSTEM = 10000
    UNKNOWN = 0


@dataclass
class Message:
    """统一消息格式"""
    id: str                          # 消息 ID
    sender: str                      # 发送者 ID
    content: str                     # 消息内容
    type: MessageType = MessageType.TEXT
    room_id: str | None = None       # 群聊 ID（私聊为 None）
    is_group: bool = False           # 是否群聊
    is_at_bot: bool = False          # 是否 @了机器人
    sender_name: str = ""            # 发送者昵称
    timestamp: datetime = field(default_factory=datetime.now)
    raw: Any = None                  # 原始消息对象（平台特定）
    extra: dict = field(default_factory=dict)  # 扩展字段

    def get_chat_id(self) -> str:
        """获取会话 ID（群聊返回群 ID，私聊返回发送者 ID）"""
        return self.room_id if self.is_group else self.sender


@dataclass
class Contact:
    """联系人信息"""
    id: str
    name: str
    alias: str = ""  # 备注名
    avatar: str = ""
    extra: dict = field(default_factory=dict)


class Channel(ABC):
    """Channel 抽象基类 - 定义消息收发接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel 名称"""
        ...

    @property
    @abstractmethod
    def bot_id(self) -> str:
        """机器人自身 ID"""
        ...

    @abstractmethod
    async def send_text(
        self,
        content: str,
        receiver: str,
        at_list: list[str] | None = None,
    ) -> bool:
        """发送文本消息

        Args:
            content: 消息内容
            receiver: 接收者 ID（用户 ID 或群 ID）
            at_list: 要 @ 的用户 ID 列表

        Returns:
            是否发送成功
        """
        ...

    @abstractmethod
    async def send_image(self, path: str, receiver: str) -> bool:
        """发送图片"""
        ...

    @abstractmethod
    async def receive_messages(self) -> list[Message]:
        """接收消息（非阻塞，返回当前待处理消息列表）"""
        ...

    @abstractmethod
    async def start(self, on_message: Callable[[Message], Any]) -> None:
        """启动消息接收循环

        Args:
            on_message: 消息处理回调（可以是 async 函数）
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止消息接收"""
        ...

    @abstractmethod
    def get_contact(self, user_id: str) -> Contact | None:
        """获取联系人信息"""
        ...

    @abstractmethod
    def get_all_contacts(self) -> dict[str, Contact]:
        """获取所有联系人"""
        ...

    def get_user_name(self, user_id: str, room_id: str | None = None) -> str:
        """获取用户显示名称

        Args:
            user_id: 用户 ID
            room_id: 群 ID（用于获取群昵称，子类可重写以支持）

        Returns:
            用户名称
        """
        # room_id 参数供子类重写时使用（如获取群内昵称）
        _ = room_id
        contact = self.get_contact(user_id)
        if contact:
            return contact.alias or contact.name or user_id
        return user_id
