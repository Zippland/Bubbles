# bot.py
"""BubblesBot - 基于 Channel 抽象的聊天机器人"""

import asyncio
import logging
import re
import time as time_mod
import copy
from typing import Any

from channel import Channel, Message, MessageType
from ai_providers.ai_chatgpt import ChatGPT
from ai_providers.ai_deepseek import DeepSeek
from ai_providers.ai_kimi import Kimi
from ai_providers.ai_perplexity import Perplexity
from function.func_summary import MessageSummary
from function.func_reminder import ReminderManager
from function.func_persona import (
    PersonaManager,
    build_persona_system_prompt,
)
from configuration import Config
from constants import ChatType
from agent import AgentLoop, AgentContext
from agent.tools import create_default_registry
from session import SessionManager

__version__ = "40.0.0.0"

logger = logging.getLogger("BubblesBot")


class BubblesBot:
    """基于 Channel 抽象的聊天机器人"""

    def __init__(self, channel: Channel, config: Config):
        self.channel = channel
        self.config = config
        self.LOG = logger
        self.bot_id = channel.bot_id

        # 初始化消息历史
        db_path = "data/message_history.db"
        max_hist = getattr(config, "MAX_HISTORY", 300)
        try:
            self.message_summary = MessageSummary(max_history=max_hist, db_path=db_path)
            self.LOG.info(f"消息历史记录器已初始化 (max_history={max_hist})")
        except Exception as e:
            self.LOG.error(f"初始化 MessageSummary 失败: {e}")
            self.message_summary = None

        # 初始化 AI 模型
        self.chat_models = {}
        self.reasoning_chat_models = {}
        self._init_chat_models()

        # 根据配置选择默认模型
        self.default_model_id = self.config.GROUP_MODELS.get("default", 0) if hasattr(self.config, "GROUP_MODELS") else 0
        if self.default_model_id in self.chat_models:
            self.chat = self.chat_models[self.default_model_id]
            self.current_model_id = self.default_model_id
        elif self.chat_models:
            self.default_model_id = list(self.chat_models.keys())[0]
            self.chat = self.chat_models[self.default_model_id]
            self.current_model_id = self.default_model_id
        else:
            self.LOG.warning("未配置任何可用的模型")
            self.chat = None
            self.current_model_id = None

        # 初始化提醒管理器
        try:
            reminder_db = getattr(self.message_summary, "db_path", db_path) if self.message_summary else db_path
            self.reminder_manager = ReminderManager(self, reminder_db)
            self.LOG.info("提醒管理器已初始化")
        except Exception as e:
            self.LOG.error(f"初始化提醒管理器失败: {e}")
            self.reminder_manager = None

        # 初始化人设管理器
        try:
            persona_db = getattr(self.message_summary, "db_path", db_path) if self.message_summary else db_path
            self.persona_manager = PersonaManager(persona_db)
            self.LOG.info("人设管理器已初始化")
        except Exception as e:
            self.LOG.error(f"初始化人设管理器失败: {e}")
            self.persona_manager = None

        # 初始化 Agent Loop 系统
        self.tool_registry = create_default_registry()
        self.agent_loop = AgentLoop(self.tool_registry, max_iterations=20)
        self.session_manager = SessionManager(self.message_summary, self.bot_id)
        self.LOG.info(f"Agent Loop 系统已初始化，工具: {self.tool_registry.get_tool_names()}")

    def _init_chat_models(self) -> None:
        """初始化所有 AI 模型"""
        self.LOG.info("开始初始化 AI 模型...")

        # ChatGPT
        if ChatGPT.value_check(self.config.CHATGPT):
            try:
                flash_conf = copy.deepcopy(self.config.CHATGPT)
                flash_model = flash_conf.get("model_flash", "gpt-3.5-turbo")
                flash_conf["model"] = flash_model
                self.chat_models[ChatType.CHATGPT.value] = ChatGPT(
                    flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.bot_id,
                )
                self.LOG.info(f"已加载 ChatGPT: {flash_model}")

                reasoning_model = self.config.CHATGPT.get("model_reasoning")
                if reasoning_model and reasoning_model != flash_model:
                    reason_conf = copy.deepcopy(self.config.CHATGPT)
                    reason_conf["model"] = reasoning_model
                    self.reasoning_chat_models[ChatType.CHATGPT.value] = ChatGPT(
                        reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.bot_id,
                    )
                    self.LOG.info(f"已加载 ChatGPT 推理模型: {reasoning_model}")
            except Exception as e:
                self.LOG.error(f"初始化 ChatGPT 失败: {e}")

        # DeepSeek
        if DeepSeek.value_check(self.config.DEEPSEEK):
            try:
                flash_conf = copy.deepcopy(self.config.DEEPSEEK)
                flash_model = flash_conf.get("model_flash", "deepseek-chat")
                flash_conf["model"] = flash_model
                self.chat_models[ChatType.DEEPSEEK.value] = DeepSeek(
                    flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.bot_id,
                )
                self.LOG.info(f"已加载 DeepSeek: {flash_model}")

                reasoning_model = self.config.DEEPSEEK.get("model_reasoning")
                if not reasoning_model and flash_model != "deepseek-reasoner":
                    reasoning_model = "deepseek-reasoner"
                if reasoning_model and reasoning_model != flash_model:
                    reason_conf = copy.deepcopy(self.config.DEEPSEEK)
                    reason_conf["model"] = reasoning_model
                    self.reasoning_chat_models[ChatType.DEEPSEEK.value] = DeepSeek(
                        reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.bot_id,
                    )
                    self.LOG.info(f"已加载 DeepSeek 推理模型: {reasoning_model}")
            except Exception as e:
                self.LOG.error(f"初始化 DeepSeek 失败: {e}")

        # Kimi
        if Kimi.value_check(self.config.KIMI):
            try:
                flash_conf = copy.deepcopy(self.config.KIMI)
                flash_model = flash_conf.get("model_flash", "kimi-k2")
                flash_conf["model"] = flash_model
                self.chat_models[ChatType.KIMI.value] = Kimi(
                    flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.bot_id,
                )
                self.LOG.info(f"已加载 Kimi: {flash_model}")

                reasoning_model = self.config.KIMI.get("model_reasoning")
                if not reasoning_model and flash_model != "kimi-k2-thinking":
                    reasoning_model = "kimi-k2-thinking"
                if reasoning_model and reasoning_model != flash_model:
                    reason_conf = copy.deepcopy(self.config.KIMI)
                    reason_conf["model"] = reasoning_model
                    self.reasoning_chat_models[ChatType.KIMI.value] = Kimi(
                        reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.bot_id,
                    )
                    self.LOG.info(f"已加载 Kimi 推理模型: {reasoning_model}")
            except Exception as e:
                self.LOG.error(f"初始化 Kimi 失败: {e}")

        # Perplexity
        if Perplexity.value_check(self.config.PERPLEXITY):
            try:
                flash_conf = copy.deepcopy(self.config.PERPLEXITY)
                flash_model = flash_conf.get("model_flash", "sonar")
                flash_conf["model"] = flash_model
                self.chat_models[ChatType.PERPLEXITY.value] = Perplexity(flash_conf)
                self.LOG.info(f"已加载 Perplexity: {flash_model}")

                reasoning_model = self.config.PERPLEXITY.get("model_reasoning")
                if reasoning_model and reasoning_model != flash_model:
                    reason_conf = copy.deepcopy(self.config.PERPLEXITY)
                    reason_conf["model"] = reasoning_model
                    self.reasoning_chat_models[ChatType.PERPLEXITY.value] = Perplexity(reason_conf)
                    self.LOG.info(f"已加载 Perplexity 推理模型: {reasoning_model}")
            except Exception as e:
                self.LOG.error(f"初始化 Perplexity 失败: {e}")

    async def start(self) -> None:
        """启动机器人"""
        self.LOG.info(f"BubblesBot v{__version__} 启动中...")
        await self.channel.start(self._on_message)

    async def stop(self) -> None:
        """停止机器人"""
        await self.channel.stop()
        self.LOG.info("BubblesBot 已停止")

    async def _on_message(self, msg: Message) -> None:
        """消息处理入口"""
        try:
            # 跳过自己发送的消息
            if msg.sender == self.bot_id:
                return

            # 只处理文本消息
            if msg.type != MessageType.TEXT:
                return

            # 记录消息
            if self.message_summary:
                self.message_summary.record_message(
                    chat_id=msg.get_chat_id(),
                    sender_name=msg.sender_name,
                    sender_wxid=msg.sender,
                    content=msg.content,
                )

            # 处理消息
            await self._handle_message(msg)

        except Exception as e:
            self.LOG.error(f"处理消息时出错: {e}", exc_info=True)

    async def _handle_message(self, msg: Message) -> None:
        """处理单条消息"""
        # 私聊或 @机器人 时响应
        should_respond = not msg.is_group or msg.is_at_bot

        if not should_respond:
            return

        chat_id = msg.get_chat_id()
        content = msg.content

        # 获取会话
        session_key = f"{self.channel.name}:{chat_id}"
        session = self.session_manager.get_or_create(session_key, max_history=30)

        # 构建用户消息
        current_time = time_mod.strftime("%H:%M", time_mod.localtime())
        user_message = f"[{current_time}] {msg.sender_name}: {content}"

        # 构建系统提示
        tool_guidance = (
            "\n\n## 工具使用指引\n"
            "你可以调用工具来辅助回答，以下是决策原则：\n"
            "- 用户询问需要最新信息、实时数据、或你不确定的事实 → 调用 web_search\n"
            "- 用户想设置/查看/删除提醒 → 调用 reminder_create / reminder_list / reminder_delete\n"
            "- 用户提到之前聊过的内容、或你需要回顾更早的对话 → 调用 lookup_chat_history\n"
            "- 日常闲聊、观点讨论、情感交流 → 直接回复，不需要调用任何工具\n"
        )

        # 获取人设
        persona_text = None
        if self.persona_manager:
            try:
                persona_text = self.persona_manager.get_persona(chat_id)
            except Exception:
                pass

        if persona_text:
            system_prompt = build_persona_system_prompt(self.chat, persona_text) + tool_guidance
        else:
            system_prompt = tool_guidance

        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        now_time = time_mod.strftime("%Y-%m-%d %H:%M:%S", time_mod.localtime())
        messages.append({"role": "system", "content": f"Current time is: {now_time}"})

        # 添加历史消息
        history = session.get_history(30)
        for hist_msg in history:
            role = hist_msg.get("role", "user")
            hist_content = hist_msg.get("content", "")
            if hist_content and role in ("user", "assistant"):
                messages.append({"role": role, "content": hist_content})

        # 添加当前消息
        latest_prompt = (
            "# 本轮需要回复的用户及其最新信息\n"
            "请你基于下面这条最新收到的用户讯息直接进行自然的中文回复：\n"
            f"「{user_message}」\n"
            "请只针对该用户进行回复。"
        )
        messages.append({"role": "user", "content": latest_prompt})

        # 创建 AgentContext
        async def send_func(content: str, at_list: str = "", record_message: bool = True):
            await self.channel.send_text(content, chat_id)
            if record_message and self.message_summary:
                self.message_summary.record_message(
                    chat_id=chat_id,
                    sender_name="Bot",
                    sender_wxid=self.bot_id,
                    content=content,
                )

        agent_ctx = AgentContext(
            session=session,
            chat_id=chat_id,
            sender_wxid=msg.sender,
            sender_name=msg.sender_name,
            robot_wxid=self.bot_id,
            is_group=msg.is_group,
            robot=self,
            logger=self.LOG,
            config=self.config,
            specific_max_history=30,
            persona=persona_text,
            _send_text_func=send_func,
        )

        # 执行 Agent Loop
        try:
            chat_model = self.chat
            if not chat_model:
                await self.channel.send_text("抱歉，没有可用的 AI 模型。", chat_id)
                return

            self.LOG.info(f"Agent Loop 启动，工具: {self.tool_registry.get_tool_names()}")
            response = await self.agent_loop.run(
                provider=chat_model,
                messages=messages,
                ctx=agent_ctx,
            )

            if response:
                await self.channel.send_text(response, chat_id)
                session.add_message("user", latest_prompt)
                session.add_message("assistant", response)

                if self.message_summary:
                    self.message_summary.record_message(
                        chat_id=chat_id,
                        sender_name="Bot",
                        sender_wxid=self.bot_id,
                        content=response,
                    )
            else:
                self.LOG.error("Agent Loop 未返回响应")

        except Exception as e:
            self.LOG.error(f"Agent Loop 执行失败: {e}", exc_info=True)
            await self.channel.send_text("抱歉，处理消息时出错了。", chat_id)

    def cleanup(self) -> None:
        """清理资源"""
        self.LOG.info("正在清理 BubblesBot 资源...")
        if self.message_summary:
            self.message_summary.close_db()
        if self.persona_manager:
            try:
                self.persona_manager.close()
            except Exception:
                pass
        self.LOG.info("BubblesBot 资源清理完成")
