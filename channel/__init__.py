# channel/__init__.py
from .base import Channel, Message, MessageType, Contact
from .local import LocalChannel

__all__ = ["Channel", "Message", "MessageType", "Contact", "LocalChannel"]

# WeChatChannel 仅在 Windows 或有 wcferry 时可用
try:
    from .wechat import WeChatChannel
    __all__.append("WeChatChannel")
except ImportError:
    WeChatChannel = None
