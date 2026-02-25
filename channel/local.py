# channel/local.py
"""本地命令行 Channel - 用于调试"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import Callable, Any

from .base import Channel, Message, MessageType, Contact

logger = logging.getLogger(__name__)


class LocalChannel(Channel):
    """本地命令行 Channel - 用于在没有微信的环境下调试"""

    def __init__(self, bot_name: str = "Bubbles", user_name: str = "User"):
        self._bot_id = "local_bot"
        self._bot_name = bot_name
        self._user_id = "local_user"
        self._user_name = user_name
        self._running = False
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._contacts: dict[str, Contact] = {
            self._bot_id: Contact(id=self._bot_id, name=bot_name),
            self._user_id: Contact(id=self._user_id, name=user_name),
        }
        self._msg_counter = 0

    @property
    def name(self) -> str:
        return "local"

    @property
    def bot_id(self) -> str:
        return self._bot_id

    async def send_text(
        self,
        content: str,
        receiver: str,
        at_list: list[str] | None = None,
    ) -> bool:
        # 在命令行打印机器人回复
        print(f"\n\033[36m[{self._bot_name}]\033[0m {content}\n")
        return True

    async def send_image(self, path: str, receiver: str) -> bool:
        print(f"\n\033[36m[{self._bot_name}]\033[0m [图片: {path}]\n")
        return True

    async def receive_messages(self) -> list[Message]:
        messages = []
        while not self._message_queue.empty():
            try:
                msg = self._message_queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages

    async def start(self, on_message: Callable[[Message], Any]) -> None:
        """启动命令行交互循环"""
        self._running = True
        print(f"\n{'='*50}")
        print(f"  {self._bot_name} Local Channel 已启动")
        print(f"  输入消息与机器人对话，输入 'quit' 退出")
        print(f"{'='*50}\n")

        # 启动输入读取任务
        input_task = asyncio.create_task(self._read_input_loop())

        # 消息处理循环
        while self._running:
            try:
                # 等待用户输入
                msg = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=0.5
                )
                # 调用消息处理器
                if asyncio.iscoroutinefunction(on_message):
                    await on_message(msg)
                else:
                    on_message(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)

        input_task.cancel()
        try:
            await input_task
        except asyncio.CancelledError:
            pass

    async def _read_input_loop(self) -> None:
        """异步读取命令行输入"""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                # 在线程中读取输入（避免阻塞事件循环）
                line = await loop.run_in_executor(None, self._read_line)
                if line is None:
                    continue

                line = line.strip()
                if not line:
                    continue

                if line.lower() in ('quit', 'exit', 'q'):
                    print("\n再见！")
                    self._running = False
                    break

                # 创建消息
                self._msg_counter += 1
                msg = Message(
                    id=f"local_{self._msg_counter}",
                    sender=self._user_id,
                    content=line,
                    type=MessageType.TEXT,
                    is_group=False,
                    is_at_bot=True,  # 本地模式默认视为 @机器人
                    sender_name=self._user_name,
                    timestamp=datetime.now(),
                )
                await self._message_queue.put(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"读取输入时出错: {e}")

    def _read_line(self) -> str | None:
        """同步读取一行输入"""
        try:
            print(f"\033[33m[{self._user_name}]\033[0m ", end="", flush=True)
            return input()
        except EOFError:
            return None
        except KeyboardInterrupt:
            return "quit"

    async def stop(self) -> None:
        self._running = False

    def get_contact(self, user_id: str) -> Contact | None:
        return self._contacts.get(user_id)

    def get_all_contacts(self) -> dict[str, Contact]:
        return self._contacts.copy()

    def add_contact(self, user_id: str, name: str, alias: str = "") -> None:
        """添加联系人（用于模拟）"""
        self._contacts[user_id] = Contact(id=user_id, name=name, alias=alias)

    def simulate_message(
        self,
        content: str,
        sender: str | None = None,
        room_id: str | None = None,
        is_at_bot: bool = True,
    ) -> Message:
        """模拟收到消息（用于测试）"""
        self._msg_counter += 1
        sender = sender or self._user_id
        sender_name = self.get_user_name(sender)

        msg = Message(
            id=f"local_{self._msg_counter}",
            sender=sender,
            content=content,
            type=MessageType.TEXT,
            room_id=room_id,
            is_group=room_id is not None,
            is_at_bot=is_at_bot,
            sender_name=sender_name,
            timestamp=datetime.now(),
        )
        return msg
