# channel/wechat.py
"""微信 Channel - 基于 wcferry"""

import asyncio
import logging
import re
from datetime import datetime
from queue import Empty
from typing import Callable, Any

from .base import Channel, Message, MessageType, Contact

logger = logging.getLogger(__name__)

# 尝试导入 wcferry（仅 Windows 可用）
try:
    from wcferry import Wcf, WxMsg
    WCFERRY_AVAILABLE = True
except ImportError:
    WCFERRY_AVAILABLE = False
    Wcf = None
    WxMsg = None


def _convert_message_type(wx_type: int) -> MessageType:
    """转换微信消息类型到统一类型"""
    mapping = {
        1: MessageType.TEXT,
        3: MessageType.IMAGE,
        34: MessageType.VOICE,
        43: MessageType.VIDEO,
        47: MessageType.EMOJI,
        48: MessageType.LOCATION,
        49: MessageType.LINK,
        37: MessageType.FRIEND_REQUEST,
        10000: MessageType.SYSTEM,
    }
    return mapping.get(wx_type, MessageType.UNKNOWN)


class WeChatChannel(Channel):
    """微信 Channel - 封装 wcferry"""

    def __init__(self, wcf: "Wcf" = None, debug: bool = False):
        if not WCFERRY_AVAILABLE:
            raise ImportError("wcferry 不可用，请在 Windows 环境下安装")

        self._wcf = wcf or Wcf(debug=debug)
        self._bot_id = self._wcf.get_self_wxid()
        self._running = False
        self._contacts_cache: dict[str, Contact] = {}
        self._load_contacts()

    def _load_contacts(self) -> None:
        """加载联系人缓存"""
        try:
            contacts = self._wcf.query_sql(
                "MicroMsg.db",
                "SELECT UserName, NickName FROM Contact;"
            )
            for c in contacts:
                user_id = c["UserName"]
                self._contacts_cache[user_id] = Contact(
                    id=user_id,
                    name=c["NickName"],
                )
        except Exception as e:
            logger.error(f"加载联系人失败: {e}")

    @property
    def name(self) -> str:
        return "wechat"

    @property
    def bot_id(self) -> str:
        return self._bot_id

    @property
    def wcf(self) -> "Wcf":
        """获取原始 wcf 对象（兼容旧代码）"""
        return self._wcf

    async def send_text(
        self,
        content: str,
        receiver: str,
        at_list: list[str] | None = None,
    ) -> bool:
        try:
            at_str = ",".join(at_list) if at_list else ""
            await asyncio.to_thread(
                self._wcf.send_text,
                content,
                receiver,
                at_str
            )
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def send_image(self, path: str, receiver: str) -> bool:
        try:
            await asyncio.to_thread(self._wcf.send_image, path, receiver)
            return True
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            return False

    async def receive_messages(self) -> list[Message]:
        """非阻塞获取消息"""
        messages = []
        try:
            wx_msg = await asyncio.to_thread(self._wcf.get_msg)
            if wx_msg:
                msg = self._convert_wx_msg(wx_msg)
                if msg:
                    messages.append(msg)
        except Empty:
            pass
        except Exception as e:
            logger.error(f"接收消息失败: {e}")
        return messages

    async def start(self, on_message: Callable[[Message], Any]) -> None:
        """启动消息接收循环"""
        self._running = True
        self._wcf.enable_receiving_msg()

        logger.info("WeChatChannel 已启动")

        while self._running:
            try:
                # 在线程中获取消息（阻塞操作）
                wx_msg = await asyncio.to_thread(self._get_msg_with_timeout)
                if wx_msg is None:
                    continue

                msg = self._convert_wx_msg(wx_msg)
                if msg is None:
                    continue

                logger.debug(f"收到消息: {msg.sender}: {msg.content[:50]}")

                # 调用消息处理器
                if asyncio.iscoroutinefunction(on_message):
                    await on_message(msg)
                else:
                    on_message(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)

    def _get_msg_with_timeout(self) -> "WxMsg | None":
        """带超时的消息获取"""
        try:
            if self._wcf.is_receiving_msg():
                return self._wcf.get_msg()
        except Empty:
            pass
        return None

    def _convert_wx_msg(self, wx_msg: "WxMsg") -> Message | None:
        """转换微信消息到统一格式"""
        try:
            is_group = wx_msg.from_group()
            room_id = wx_msg.roomid if is_group else None

            # 检查是否 @ 机器人
            is_at_bot = False
            content = wx_msg.content
            if is_group and wx_msg.is_at(self._bot_id):
                is_at_bot = True
                # 移除 @ 前缀
                content = re.sub(r"^@.*?[\u2005\s]", "", content).strip()

            # 获取发送者名称
            sender_name = self.get_user_name(wx_msg.sender, room_id)

            return Message(
                id=str(wx_msg.id),
                sender=wx_msg.sender,
                content=content,
                type=_convert_message_type(wx_msg.type),
                room_id=room_id,
                is_group=is_group,
                is_at_bot=is_at_bot,
                sender_name=sender_name,
                timestamp=datetime.now(),
                raw=wx_msg,
            )
        except Exception as e:
            logger.error(f"转换消息失败: {e}")
            return None

    async def stop(self) -> None:
        self._running = False
        logger.info("WeChatChannel 已停止")

    def get_contact(self, user_id: str) -> Contact | None:
        return self._contacts_cache.get(user_id)

    def get_all_contacts(self) -> dict[str, Contact]:
        return self._contacts_cache.copy()

    def get_user_name(self, user_id: str, room_id: str | None = None) -> str:
        """获取用户显示名称"""
        # 尝试获取群昵称
        if room_id:
            try:
                alias = self._wcf.get_alias_in_chatroom(user_id, room_id)
                if alias and alias.strip():
                    return alias
            except Exception:
                pass

        # 回退到通讯录
        contact = self.get_contact(user_id)
        if contact:
            return contact.alias or contact.name or user_id
        return user_id

    def refresh_contacts(self) -> None:
        """刷新联系人缓存"""
        self._load_contacts()

    def cleanup(self) -> None:
        """清理资源"""
        try:
            self._wcf.cleanup()
        except Exception as e:
            logger.error(f"清理 wcf 失败: {e}")
