# -*- coding: utf-8 -*-

import asyncio
import logging
import re
import time as time_mod
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread
import random
import copy
from image.img_manager import ImageGenerationManager

from wcferry import Wcf, WxMsg

from ai_providers.ai_chatgpt import ChatGPT
from ai_providers.ai_deepseek import DeepSeek
from ai_providers.ai_kimi import Kimi
from ai_providers.ai_perplexity import Perplexity
from function.func_weather import Weather
from function.func_news import News
from function.func_summary import MessageSummary
from function.func_reminder import ReminderManager
from function.func_persona import (
    PersonaManager,
    fetch_persona_for_context,
    handle_persona_command,
    build_persona_system_prompt,
)
from configuration import Config
from constants import ChatType
from job_mgmt import Job
from function.func_xml_process import XmlProcessor

# 导入上下文及常用处理函数
from commands.context import MessageContext
# 旧的 handle_chitchat 已被 _handle_chitchat_async 取代
from commands.keyword_triggers import KeywordTriggerProcessor
from commands.message_forwarder import MessageForwarder

# 导入新的 Agent 系统
from agent import AgentLoop, AgentContext
from agent.tools import create_default_registry, ToolRegistry
from session import SessionManager

__version__ = "39.3.0.0"  # 升级版本号


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf, chat_type: int) -> None:
        super().__init__()

        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid() # 获取机器人自己的wxid
        self.allContacts = self.getAllContacts()
        self._msg_timestamps = []
        default_random_prob = getattr(self.config, "GROUP_RANDOM_CHITCHAT_DEFAULT", 0.0)
        try:
            self.group_random_reply_default = float(default_random_prob)
        except (TypeError, ValueError):
            self.group_random_reply_default = 0.0
        self.group_random_reply_default = max(0.0, min(1.0, self.group_random_reply_default))

        mapping_random_prob = getattr(self.config, "GROUP_RANDOM_CHITCHAT", {})
        self.group_random_reply_mapping = {}
        if isinstance(mapping_random_prob, dict):
            for room_id, rate in mapping_random_prob.items():
                try:
                    numeric_rate = float(rate)
                except (TypeError, ValueError):
                    numeric_rate = self.group_random_reply_default
                numeric_rate = max(0.0, min(1.0, numeric_rate))
                self.group_random_reply_mapping[room_id] = numeric_rate

        self.group_random_reply_state = {}

        if self.group_random_reply_default > 0:
            self.LOG.info(
                f"群聊随机闲聊默认开启，概率={self.group_random_reply_default}"
            )
        for room_id, rate in self.group_random_reply_mapping.items():
            self.LOG.info(
                f"群聊随机闲聊设置: 群={room_id}, 概率={rate}"
            )
        self.LOG.info(
            "群聊随机闲聊动态策略: 命中后概率清零，每条新消息恢复至多上限的 1/10"
        )

        try:
             db_path = "data/message_history.db"
             # 使用 getattr 安全地获取 MAX_HISTORY，如果不存在则默认为 300
             max_hist = getattr(config, 'MAX_HISTORY', 300)
             self.message_summary = MessageSummary(max_history=max_hist, db_path=db_path)
             self.LOG.info(f"消息历史记录器已初始化 (max_history={self.message_summary.max_history})")
        except Exception as e:
             self.LOG.error(f"初始化 MessageSummary 失败: {e}", exc_info=True)
             self.message_summary = None # 保持失败时的处理

        self.xml_processor = XmlProcessor(self.LOG)

        self.chat_models = {}
        self.reasoning_chat_models = {}
        self.LOG.info("开始初始化各种AI模型...")

        # 初始化ChatGPT
        if ChatGPT.value_check(self.config.CHATGPT):
            try:
                chatgpt_flash_conf = copy.deepcopy(self.config.CHATGPT)
                flash_model_name = chatgpt_flash_conf.get("model_flash", "gpt-3.5-turbo")
                chatgpt_flash_conf["model"] = flash_model_name
                self.chat_models[ChatType.CHATGPT.value] = ChatGPT(
                    chatgpt_flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.wxid
                )
                self.LOG.info(f"已加载 ChatGPT 模型: {flash_model_name}")

                reasoning_model_name = self.config.CHATGPT.get("model_reasoning")
                if reasoning_model_name and reasoning_model_name != flash_model_name:
                    chatgpt_reason_conf = copy.deepcopy(self.config.CHATGPT)
                    chatgpt_reason_conf["model"] = reasoning_model_name
                    self.reasoning_chat_models[ChatType.CHATGPT.value] = ChatGPT(
                        chatgpt_reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.wxid
                    )
                    self.LOG.info(f"已加载 ChatGPT 推理模型: {reasoning_model_name}")
            except Exception as e:
                self.LOG.error(f"初始化 ChatGPT 模型时出错: {str(e)}")
            
        # 初始化DeepSeek
        if DeepSeek.value_check(self.config.DEEPSEEK):
            try:
                deepseek_flash_conf = copy.deepcopy(self.config.DEEPSEEK)
                flash_model_name = deepseek_flash_conf.get("model_flash", "deepseek-chat")
                deepseek_flash_conf["model"] = flash_model_name
                self.chat_models[ChatType.DEEPSEEK.value] = DeepSeek(
                    deepseek_flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.wxid
                )
                self.LOG.info(f"已加载 DeepSeek 模型: {flash_model_name}")

                reasoning_model_name = self.config.DEEPSEEK.get("model_reasoning")
                if not reasoning_model_name and flash_model_name != "deepseek-reasoner":
                    reasoning_model_name = "deepseek-reasoner"

                if reasoning_model_name and reasoning_model_name != flash_model_name:
                    deepseek_reason_conf = copy.deepcopy(self.config.DEEPSEEK)
                    deepseek_reason_conf["model"] = reasoning_model_name
                    self.reasoning_chat_models[ChatType.DEEPSEEK.value] = DeepSeek(
                        deepseek_reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.wxid
                    )
                    self.LOG.info(f"已加载 DeepSeek 推理模型: {reasoning_model_name}")
            except Exception as e:
                self.LOG.error(f"初始化 DeepSeek 模型时出错: {str(e)}")
        
        # 初始化Kimi
        if Kimi.value_check(self.config.KIMI):
            try:
                kimi_flash_conf = copy.deepcopy(self.config.KIMI)
                flash_model_name = kimi_flash_conf.get("model_flash", "kimi-k2")
                kimi_flash_conf["model"] = flash_model_name
                self.chat_models[ChatType.KIMI.value] = Kimi(
                    kimi_flash_conf,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.wxid
                )
                self.LOG.info(f"已加载 Kimi 模型: {flash_model_name}")

                reasoning_model_name = self.config.KIMI.get("model_reasoning")
                if not reasoning_model_name and flash_model_name != "kimi-k2-thinking":
                    reasoning_model_name = "kimi-k2-thinking"

                if reasoning_model_name and reasoning_model_name != flash_model_name:
                    kimi_reason_conf = copy.deepcopy(self.config.KIMI)
                    kimi_reason_conf["model"] = reasoning_model_name
                    self.reasoning_chat_models[ChatType.KIMI.value] = Kimi(
                        kimi_reason_conf,
                        message_summary_instance=self.message_summary,
                        bot_wxid=self.wxid
                    )
                    self.LOG.info(f"已加载 Kimi 推理模型: {reasoning_model_name}")
            except Exception as e:
                self.LOG.error(f"初始化 Kimi 模型时出错: {str(e)}")
        
            
        # 初始化Perplexity
        if Perplexity.value_check(self.config.PERPLEXITY):
            try:
                perplexity_flash_conf = copy.deepcopy(self.config.PERPLEXITY)
                flash_model_name = perplexity_flash_conf.get("model_flash", "sonar")
                perplexity_flash_conf["model"] = flash_model_name
                self.chat_models[ChatType.PERPLEXITY.value] = Perplexity(perplexity_flash_conf)
                self.perplexity = self.chat_models[ChatType.PERPLEXITY.value]  # 单独保存一个引用用于特殊处理
                self.LOG.info(f"已加载 Perplexity 模型: {flash_model_name}")

                reasoning_model_name = self.config.PERPLEXITY.get("model_reasoning")
                if reasoning_model_name and reasoning_model_name != flash_model_name:
                    perplexity_reason_conf = copy.deepcopy(self.config.PERPLEXITY)
                    perplexity_reason_conf["model"] = reasoning_model_name
                    self.reasoning_chat_models[ChatType.PERPLEXITY.value] = Perplexity(perplexity_reason_conf)
                    self.LOG.info(f"已加载 Perplexity 推理模型: {reasoning_model_name}")
            except Exception as e:
                self.LOG.error(f"初始化 Perplexity 模型时出错: {str(e)}")
            
        # 根据chat_type参数选择默认模型
        self.current_model_id = None
        if chat_type > 0 and chat_type in self.chat_models:
            self.chat = self.chat_models[chat_type]
            self.default_model_id = chat_type
            self.current_model_id = chat_type
        else:
            # 如果没有指定chat_type或指定的模型不可用，尝试使用配置文件中指定的默认模型
            self.default_model_id = self.config.GROUP_MODELS.get('default', 0)
            if self.default_model_id in self.chat_models:
                self.chat = self.chat_models[self.default_model_id]
                self.current_model_id = self.default_model_id
            elif self.chat_models:  # 如果有任何可用模型，使用第一个
                self.default_model_id = list(self.chat_models.keys())[0]
                self.chat = self.chat_models[self.default_model_id]
                self.current_model_id = self.default_model_id
            else:
                self.LOG.warning("未配置任何可用的模型")
                self.chat = None
                self.default_model_id = 0
                self.current_model_id = None

        self.LOG.info(f"默认模型: {self.chat}，模型ID: {self.default_model_id}")
        
        # 显示群组-模型映射信息
        if hasattr(self.config, 'GROUP_MODELS'):
            # 显示群聊映射信息
            if self.config.GROUP_MODELS.get('mapping'):
                self.LOG.info("群聊-模型映射配置:")
                for mapping in self.config.GROUP_MODELS.get('mapping', []):
                    room_id = mapping.get('room_id', '')
                    model_id = mapping.get('model', 0)
                    if room_id and model_id in self.chat_models:
                        model_name = self.chat_models[model_id].__class__.__name__
                        self.LOG.info(f"  群聊 {room_id} -> 模型 {model_name}(ID:{model_id})")
                    elif room_id:
                        self.LOG.warning(f"  群聊 {room_id} 配置的模型ID {model_id} 不可用")
            
            # 显示私聊映射信息
            if self.config.GROUP_MODELS.get('private_mapping'):
                self.LOG.info("私聊-模型映射配置:")
                for mapping in self.config.GROUP_MODELS.get('private_mapping', []):
                    wxid = mapping.get('wxid', '')
                    model_id = mapping.get('model', 0)
                    if wxid and model_id in self.chat_models:
                        model_name = self.chat_models[model_id].__class__.__name__
                        contact_name = self.allContacts.get(wxid, wxid)
                        self.LOG.info(f"  私聊用户 {contact_name}({wxid}) -> 模型 {model_name}(ID:{model_id})")
                    elif wxid:
                        self.LOG.warning(f"  私聊用户 {wxid} 配置的模型ID {model_id} 不可用")
        
        # 初始化图像生成管理器
        self.image_manager = ImageGenerationManager(self.config, self.wcf, self.LOG, self.sendTextMsg)
        
        # 工具系统在首次 handle_chitchat 调用时自动加载
        self.LOG.info("Agent 工具系统就绪（延迟加载）")
        
        # 初始化提醒管理器
        try:
            # 使用与MessageSummary相同的数据库路径
            db_path = getattr(self.message_summary, 'db_path', "data/message_history.db")
            self.reminder_manager = ReminderManager(self, db_path)
            self.LOG.info("提醒管理器已初始化，与消息历史使用相同数据库。")
        except Exception as e:
            self.LOG.error(f"初始化提醒管理器失败: {e}", exc_info=True)
        
        # 初始化人设管理器
        persona_db_path = getattr(self.message_summary, 'db_path', "data/message_history.db") if getattr(self, 'message_summary', None) else "data/message_history.db"
        try:
            self.persona_manager = PersonaManager(persona_db_path)
            self.LOG.info("人设管理器已初始化。")
        except Exception as e:
            self.LOG.error(f"初始化人设管理器失败: {e}", exc_info=True)
            self.persona_manager = None
        
        # 初始化关键词触发器与消息转发器
        self.keyword_trigger_processor = KeywordTriggerProcessor(
            self.message_summary,
            self.LOG,
        )
        forwarding_conf = getattr(self.config, "MESSAGE_FORWARDING", {})
        self.message_forwarder = MessageForwarder(self, forwarding_conf, self.LOG)

        # 初始化 Agent Loop 系统
        self.tool_registry = create_default_registry()
        self.agent_loop = AgentLoop(self.tool_registry, max_iterations=20)
        self.session_manager = SessionManager(self.message_summary, self.wxid)
        self.LOG.info(f"Agent Loop 系统已初始化，工具: {self.tool_registry.get_tool_names()}")
        
    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def _is_group_enabled(self, room_id: str) -> bool:
        """判断群聊是否在配置的允许名单内。"""
        if not room_id:
            return False
        enabled_groups = getattr(self.config, "GROUPS", None) or []
        return room_id in enabled_groups

    def processMsg(self, msg: WxMsg) -> None:
        """同步入口 - 创建异步任务处理消息"""
        asyncio.run(self.process_msg_async(msg))

    async def process_msg_async(self, msg: WxMsg) -> None:
        """
        异步处理收到的微信消息
        :param msg: 微信消息对象
        """
        try:
            # 1. 使用MessageSummary记录消息
            self.message_summary.process_message_from_wxmsg(msg, self.wcf, self.allContacts, self.wxid)

            # 2. 根据消息来源选择使用的AI模型
            self._select_model_for_message(msg)

            # 3. 获取本次对话特定的历史消息限制
            specific_limit = self._get_specific_history_limit(msg)
            self.LOG.debug(f"本次对话 ({msg.sender} in {msg.roomid or msg.sender}) 使用历史限制: {specific_limit}")

            # 4. 预处理消息，生成MessageContext
            ctx = self.preprocess(msg)
            setattr(ctx, 'chat', self.chat)
            setattr(ctx, 'specific_max_history', specific_limit)
            persona_text = fetch_persona_for_context(self, ctx)
            setattr(ctx, 'persona', persona_text)
            group_enabled = ctx.is_group and self._is_group_enabled(msg.roomid)
            setattr(ctx, 'group_enabled', group_enabled)

            force_reasoning = getattr(self, '_current_force_reasoning', False)
            setattr(ctx, 'force_reasoning', force_reasoning)

            trigger_decision = None
            if getattr(self, "keyword_trigger_processor", None):
                trigger_decision = self.keyword_trigger_processor.evaluate(ctx)
                ctx.reasoning_requested = trigger_decision.reasoning_requested
                setattr(ctx, 'keyword_trigger_decision', trigger_decision)
            else:
                ctx.reasoning_requested = bool(getattr(ctx, 'reasoning_requested', False))

            if getattr(self, "message_forwarder", None):
                try:
                    self.message_forwarder.forward_if_needed(ctx)
                except Exception as forward_error:
                    self.LOG.error(f"消息转发失败: {forward_error}", exc_info=True)

            persona_allowed = not (ctx.is_group and not group_enabled)

            if persona_allowed and handle_persona_command(self, ctx):
                return

            if trigger_decision and trigger_decision.summary_requested:
                if self.keyword_trigger_processor.handle_summary(ctx):
                    return

            if ctx.reasoning_requested:
                self.LOG.info("检测到推理模式触发词，直接进入推理模式。")
                await self._handle_chitchat_async(ctx)
                return

            # 5. 特殊消息处理（非 AI 决策）
            if msg.type == 37:  # 好友请求
                if getattr(self.config, "AUTO_ACCEPT_FRIEND_REQUEST", False):
                    self.LOG.info("检测到好友请求，自动通过。")
                    self.autoAcceptFriendRequest(msg)
                else:
                    self.LOG.info("检测到好友请求，保持待处理。")
                return

            if msg.type == 10000:  # 系统消息
                if (
                    "加入了群聊" in msg.content
                    and msg.from_group()
                    and msg.roomid in getattr(self.config, "GROUPS", [])
                ):
                    new_member_match = re.search(r'"(.+?)"邀请"(.+?)"加入了群聊', msg.content)
                    if new_member_match:
                        inviter = new_member_match.group(1)
                        new_member = new_member_match.group(2)
                        welcome_msg = self.config.WELCOME_MSG.format(new_member=new_member, inviter=inviter)
                        await self.send_text_async(welcome_msg, msg.roomid)
                return

            if msg.type == 10000 and "你已添加了" in msg.content:
                self.sayHiToNewFriend(msg)
                return

            # 6. Agent 响应：LLM 自主决定调什么工具
            # 6.1 群聊：@机器人 或 随机插嘴
            if msg.from_group() and msg.roomid in self.config.GROUPS:
                if msg.is_at(self.wxid):
                    await self._handle_chitchat_async(ctx)
                else:
                    can_auto_reply = (
                        not msg.from_self()
                        and ctx.text
                        and (msg.type == 1 or (msg.type == 49 and ctx.text))
                    )
                    if can_auto_reply:
                        rate = self._prepare_group_random_reply_current_rate(msg.roomid)
                        if rate > 0:
                            rand_val = random.random()
                            if rand_val < rate:
                                self.LOG.info(
                                    f"触发群聊主动闲聊: 群={msg.roomid}, 概率={rate:.2f}, 随机值={rand_val:.2f}"
                                )
                                setattr(ctx, 'auto_random_reply', True)
                                await self._handle_chitchat_async(ctx)
                                self._apply_group_random_reply_decay(msg.roomid)

            # 6.2 私聊
            elif not msg.from_group() and not msg.from_self():
                if msg.type == 1 or (msg.type == 49 and ctx.text):
                    await self._handle_chitchat_async(ctx)

        except Exception as e:
            self.LOG.error(f"处理消息时发生错误: {str(e)}", exc_info=True)

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def enableReceivingMsg(self) -> None:
        def innerProcessMsg(wcf: Wcf):
            while wcf.is_receiving_msg():
                try:
                    msg = wcf.get_msg()
                    self.LOG.info(msg)
                    self.processMsg(msg)
                except Empty:
                    continue  # Empty message
                except Exception as e:
                    self.LOG.error(f"Receiving message error: {e}")

        self.wcf.enable_receiving_msg()
        Thread(target=innerProcessMsg, name="GetMessage", args=(self.wcf,), daemon=True).start()

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "", record_message: bool = True) -> None:
        """ 发送消息并记录（同步版本）
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        :param record_message: 是否将本条消息写入消息历史
        """
        # 延迟和频率限制
        time_mod.sleep(float(str(time_mod.time()).split('.')[-1][-2:]) / 100.0 + 0.3)
        now = time_mod.time()
        if self.config.SEND_RATE_LIMIT > 0:
            self._msg_timestamps = [t for t in self._msg_timestamps if now - t < 60]
            if len(self._msg_timestamps) >= self.config.SEND_RATE_LIMIT:
                self.LOG.warning(f"发送消息过快，已达到每分钟{self.config.SEND_RATE_LIMIT}条上限。")
                return
            self._msg_timestamps.append(now)

        # 去除 Markdown 粗体标记
        msg = msg.replace("**", "")
        ats = ""
        message_to_send = msg
        if at_list:
            if at_list == "notify@all":
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid_at in wxids:
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid_at, receiver)}"

        try:
            if ats == "":
                self.LOG.info(f"To {receiver}: {msg}")
                self.wcf.send_text(f"{msg}", receiver, at_list)
            else:
                full_msg_content = f"{ats}\n\n{msg}"
                self.LOG.info(f"To {receiver}:\n{ats}\n{msg}")
                self.wcf.send_text(full_msg_content, receiver, at_list)

            if self.message_summary and record_message:
                robot_name = self.allContacts.get(self.wxid, "机器人")
                self.message_summary.record_message(
                    chat_id=receiver,
                    sender_name=robot_name,
                    sender_wxid=self.wxid,
                    content=message_to_send
                )
                self.LOG.debug(f"已记录机器人发送的消息到 {receiver}")
            elif not self.message_summary:
                self.LOG.warning("MessageSummary 未初始化，无法记录发送的消息")

        except Exception as e:
            self.LOG.error(f"发送消息失败: {e}")

    async def send_text_async(
        self, msg: str, receiver: str, at_list: str = "", record_message: bool = True
    ) -> None:
        """异步发送消息"""
        await asyncio.to_thread(self.sendTextMsg, msg, receiver, at_list, record_message)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact;")
        return {contact["UserName"]: contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不让进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = int(xml.attrib["scene"])
            self.wcf.accept_new_friend(v3, v4, scene)

        except Exception as e:
            self.LOG.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            greeting = f"Hi {nickName[0]}，我是泡泡，很高兴认识你。"
            if getattr(self.config, "AUTO_ACCEPT_FRIEND_REQUEST", False):
                greeting = f"Hi {nickName[0]}，我是泡泡，我自动通过了你的好友请求。"
            self.sendTextMsg(greeting, msg.sender)

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            self.LOG.info("未配置定时新闻接收人，跳过。")
            return

        self.LOG.info("开始执行定时新闻推送任务...")
        # 获取新闻，解包返回的元组
        is_today, news_content = News().get_important_news()

        # 必须是当天的新闻 (is_today=True) 并且有有效内容 (news_content非空) 才发送
        if is_today and news_content:
            self.LOG.info(f"成功获取当天新闻，准备推送给 {len(receivers)} 个接收人...")
            for r in receivers:
                self.sendTextMsg(news_content, r)
            self.LOG.info("定时新闻推送完成。")
        else:
            # 记录没有发送的原因
            if not is_today and news_content:
                self.LOG.warning("获取到的是旧闻，定时推送已跳过。")
            elif not news_content:
                self.LOG.warning("获取新闻内容失败或为空，定时推送已跳过。")
            else:  # 理论上不会执行到这里
                self.LOG.warning("获取新闻失败（未知原因），定时推送已跳过。")
            
    def weatherReport(self, receivers: list = None) -> None:
        if receivers is None:
            receivers = self.config.WEATHER
        if not receivers or not self.config.CITY_CODE:
            self.LOG.warning("未配置天气城市代码或接收人")
            return

        report = Weather(self.config.CITY_CODE).get_weather()
        for r in receivers:
            self.sendTextMsg(report, r)

    def cleanup_perplexity_threads(self):
        """清理所有Perplexity线程"""
        # 如果已初始化Perplexity实例，调用其清理方法
        perplexity_instance = self.get_perplexity_instance()
        if perplexity_instance:
            perplexity_instance.cleanup()
                
    def cleanup(self):
        """清理所有资源，在程序退出前调用"""
        self.LOG.info("开始清理机器人资源...")
        
        # 清理Perplexity线程
        self.cleanup_perplexity_threads()
        
        # 关闭消息历史数据库连接
        if hasattr(self, 'message_summary') and self.message_summary:
            self.LOG.info("正在关闭消息历史数据库...")
            self.message_summary.close_db()
        if hasattr(self, 'persona_manager') and self.persona_manager:
            self.LOG.info("正在关闭人设数据库连接...")
            try:
                self.persona_manager.close()
            except Exception as e:
                self.LOG.error(f"关闭人设数据库时出错: {e}")
        
        self.LOG.info("机器人资源清理完成")
                
    def get_perplexity_instance(self):
        """获取Perplexity实例
        
        Returns:
            Perplexity: Perplexity实例，如果未配置则返回None
        """
        # 检查是否已有Perplexity实例
        if hasattr(self, 'perplexity'):
            return self.perplexity
            
        # 检查config中是否有Perplexity配置
        if hasattr(self.config, 'PERPLEXITY') and Perplexity.value_check(self.config.PERPLEXITY):
            self.perplexity = Perplexity(self.config.PERPLEXITY)
            return self.perplexity
            
        # 检查chat是否是Perplexity类型
        if isinstance(self.chat, Perplexity):
            return self.chat
            
        # 如果存在chat_models字典，尝试从中获取
        if hasattr(self, 'chat_models') and ChatType.PERPLEXITY.value in self.chat_models:
            return self.chat_models[ChatType.PERPLEXITY.value]
            
        return None
    
    def _get_reasoning_chat_model(self):
        """获取当前聊天模型对应的推理模型实例"""
        model_id = getattr(self, 'current_model_id', None)
        if model_id is None:
            return None
        return self.reasoning_chat_models.get(model_id)

    def _get_fallback_model_ids(self) -> list:
        """从配置中读取全局 fallback 模型 ID 列表。"""
        if not hasattr(self.config, "GROUP_MODELS"):
            return []
        raw = self.config.GROUP_MODELS.get("fallbacks", [])
        if isinstance(raw, list):
            return [int(x) for x in raw if isinstance(x, (int, float, str))]
        return []

    async def _handle_chitchat_async(self, ctx, auto_random_reply: bool = False) -> bool:
        """异步处理闲聊 - 使用 Agent Loop 架构"""
        # 引用图片特殊处理
        if getattr(ctx, 'is_quoted_image', False):
            return await self._handle_quoted_image_async(ctx)

        force_reasoning = bool(getattr(ctx, 'force_reasoning', False))
        reasoning_requested = bool(getattr(ctx, 'reasoning_requested', False)) or force_reasoning
        is_auto_random_reply = bool(getattr(ctx, 'auto_random_reply', False))

        # 选择模型
        chat_model = getattr(ctx, 'chat', None) or self.chat
        if reasoning_requested:
            if force_reasoning:
                self.LOG.info("群配置了 force_reasoning，将使用推理模型。")
            else:
                self.LOG.info("检测到推理模式请求，将启用深度思考。")
                await self.send_text_async("正在深度思考，请稍候...", ctx.get_receiver(), record_message=False)
            reasoning_chat = self._get_reasoning_chat_model()
            if reasoning_chat:
                chat_model = reasoning_chat
            else:
                self.LOG.warning("当前模型未配置推理模型，使用默认模型")

        if not chat_model:
            self.LOG.error("没有可用的AI模型")
            await self.send_text_async("抱歉，我现在无法进行对话。", ctx.get_receiver())
            return False

        # 获取历史消息限制
        specific_max_history = getattr(ctx, 'specific_max_history', 30)
        if specific_max_history is None:
            specific_max_history = 30

        # 获取或创建会话
        chat_id = ctx.get_receiver()
        session_key = f"wechat:{chat_id}"
        session = self.session_manager.get_or_create(session_key, max_history=specific_max_history)

        # 构建用户消息
        sender_name = ctx.sender_name
        content = ctx.text

        # 格式化消息
        if self.xml_processor:
            if ctx.is_group:
                msg_data = self.xml_processor.extract_quoted_message(ctx.msg)
            else:
                msg_data = self.xml_processor.extract_private_quoted_message(ctx.msg)
            q_with_info = self.xml_processor.format_message_for_ai(msg_data, sender_name)
            if not q_with_info:
                current_time = time_mod.strftime("%H:%M", time_mod.localtime())
                q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"
        else:
            current_time = time_mod.strftime("%H:%M", time_mod.localtime())
            q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"

        # 构建提示词
        if ctx.is_group and not ctx.is_at_bot and is_auto_random_reply:
            latest_message_prompt = (
                "# 群聊插话提醒\n"
                "你目前是在群聊里主动接话，没有人点名让你发言。\n"
                "请根据下面这句（或者你任选一句）最新消息插入一条自然、不突兀的中文回复：\n"
                f"「{q_with_info}」\n"
                "不要重复任何已知的内容，提出新的思维碰撞，也不要显得过于正式。"
            )
        else:
            latest_message_prompt = (
                "# 本轮需要回复的用户及其最新信息\n"
                "请你基于下面这条最新收到的用户讯息直接进行自然的中文回复：\n"
                f"「{q_with_info}」\n"
                "请只针对该用户进行回复。"
            )

        # 构建系统提示
        persona_text = getattr(ctx, 'persona', None)
        tool_guidance = ""
        if not is_auto_random_reply:
            tool_guidance = (
                "\n\n## 工具使用指引\n"
                "你可以调用工具来辅助回答，以下是决策原则：\n"
                "- 用户询问需要最新信息、实时数据、或你不确定的事实 → 调用 web_search\n"
                "- 用户想设置/查看/删除提醒 → 调用 reminder_create / reminder_list / reminder_delete\n"
                "- 用户提到之前聊过的内容、或你需要回顾更早的对话 → 调用 lookup_chat_history\n"
                "- 日常闲聊、观点讨论、情感交流 → 直接回复，不需要调用任何工具\n"
                "你可以在一次对话中多次调用工具。"
            )

        if persona_text:
            try:
                base_prompt = build_persona_system_prompt(chat_model, persona_text)
                system_prompt = base_prompt + tool_guidance if base_prompt else tool_guidance or None
            except Exception as persona_exc:
                self.LOG.error(f"构建人设系统提示失败: {persona_exc}", exc_info=True)
                system_prompt = tool_guidance or None
        else:
            system_prompt = tool_guidance if tool_guidance else None

        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 添加当前时间
        now_time = time_mod.strftime("%Y-%m-%d %H:%M:%S", time_mod.localtime())
        messages.append({"role": "system", "content": f"Current time is: {now_time}"})

        # 添加历史消息
        history = session.get_history(specific_max_history)
        for msg in history:
            role = msg.get("role", "user")
            msg_content = msg.get("content", "")
            if msg_content and role in ("user", "assistant"):
                messages.append({"role": role, "content": msg_content})

        # 添加当前用户消息
        messages.append({"role": "user", "content": latest_message_prompt})

        # 创建 AgentContext
        async def send_text_func(content: str, at_list: str, record_message: bool):
            await self.send_text_async(content, chat_id, at_list, record_message)

        agent_ctx = AgentContext(
            session=session,
            chat_id=chat_id,
            sender_wxid=ctx.msg.sender,
            sender_name=sender_name,
            robot_wxid=self.wxid,
            is_group=ctx.is_group,
            robot=self,
            logger=self.LOG,
            config=self.config,
            specific_max_history=specific_max_history,
            persona=persona_text,
            _send_text_func=send_text_func,
        )

        # 决定是否使用工具
        tools = self.tool_registry if not is_auto_random_reply else None

        try:
            if tools:
                # 使用 Agent Loop
                self.LOG.info(f"Agent Loop 启动，工具: {tools.get_tool_names()}")
                response = await self.agent_loop.run(
                    provider=chat_model,
                    messages=messages,
                    ctx=agent_ctx,
                )
            else:
                # 直接调用 LLM（无工具）
                llm_response = await chat_model.chat(messages, tools=None)
                response = llm_response.content

            if response:
                await self.send_text_async(response, chat_id)
                # 更新会话历史
                session.add_message("user", latest_message_prompt)
                session.add_message("assistant", response)
                return True
            else:
                self.LOG.error("无法从AI获得答案")
                return False

        except Exception as e:
            self.LOG.error(f"Agent Loop 执行失败: {e}", exc_info=True)
            if reasoning_requested:
                await self.send_text_async("抱歉，深度思考暂时遇到问题，请稍后再试。", chat_id)
            else:
                await self.send_text_async("抱歉，服务暂时不可用，请稍后再试。", chat_id)
            return False

    async def _handle_quoted_image_async(self, ctx) -> bool:
        """异步处理引用图片消息"""
        import os

        self.LOG.info("检测到引用图片消息，尝试处理图片内容...")

        chat_model = getattr(ctx, 'chat', None) or self.chat
        support_vision = False

        if isinstance(chat_model, ChatGPT):
            if hasattr(chat_model, 'support_vision') and chat_model.support_vision:
                support_vision = True
            elif hasattr(chat_model, 'model'):
                model_name = getattr(chat_model, 'model', '')
                support_vision = model_name in ("gpt-4.1-mini", "gpt-4o") or "-vision" in model_name

        if not support_vision:
            await self.send_text_async(
                "抱歉，当前 AI 模型不支持处理图片。请联系管理员配置支持视觉的模型。",
                ctx.get_receiver()
            )
            return True

        try:
            temp_dir = "temp/image_cache"
            os.makedirs(temp_dir, exist_ok=True)

            image_path = await asyncio.to_thread(
                ctx.wcf.download_image,
                id=ctx.quoted_msg_id,
                extra=ctx.quoted_image_extra,
                dir=temp_dir,
                timeout=30
            )

            if not image_path or not os.path.exists(image_path):
                await self.send_text_async("抱歉，无法下载图片进行分析。", ctx.get_receiver())
                return True

            prompt = ctx.text if ctx.text and ctx.text.strip() else "请详细描述这张图片中的内容"
            response = await asyncio.to_thread(chat_model.get_image_description, image_path, prompt)
            await self.send_text_async(response, ctx.get_receiver())

            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception:
                pass
            return True

        except Exception as e:
            self.LOG.error(f"处理引用图片出错: {e}", exc_info=True)
            await self.send_text_async(f"处理图片时发生错误: {str(e)}", ctx.get_receiver())
            return True

    def _describe_chat_model(self, chat_model, reasoning: bool = False) -> str:
        """根据配置返回模型名称，默认回退到实例类名"""
        model_id = getattr(self, 'current_model_id', None)
        config_entry = self._get_model_config(model_id) if model_id is not None else None

        if config_entry:
            if reasoning:
                label = config_entry.get("model_reasoning")
                if label:
                    return label
            label = config_entry.get("model_flash")
            if label:
                return label

        if chat_model and isinstance(getattr(chat_model, '__class__', None), type):
            return chat_model.__class__.__name__
        return "未知模型"

    def _get_model_config(self, model_id: int):
        mapping = {
            ChatType.CHATGPT.value: getattr(self.config, 'CHATGPT', None),
            ChatType.DEEPSEEK.value: getattr(self.config, 'DEEPSEEK', None),
            ChatType.KIMI.value: getattr(self.config, 'KIMI', None),
            ChatType.PERPLEXITY.value: getattr(self.config, 'PERPLEXITY', None),
        }
        return mapping.get(model_id)

    def _get_group_random_reply_base_rate(self, room_id: str) -> float:
        mapping = getattr(self, 'group_random_reply_mapping', {})
        if room_id and isinstance(mapping, dict) and room_id in mapping:
            return mapping[room_id]
        return getattr(self, 'group_random_reply_default', 0.0)

    def _prepare_group_random_reply_current_rate(self, room_id: str) -> float:
        base_rate = self._get_group_random_reply_base_rate(room_id)
        if base_rate <= 0:
            return 0.0

        current = self.group_random_reply_state.get(room_id, base_rate)
        current = max(0.0, min(base_rate, current))

        increment = max(0.0, base_rate / 10.0)
        if increment > 0 and current < base_rate:
            current = min(base_rate, current + increment)

        self.group_random_reply_state[room_id] = current
        return current

    def _apply_group_random_reply_decay(self, room_id: str) -> None:
        base_rate = self._get_group_random_reply_base_rate(room_id)
        if base_rate <= 0:
            return

        current = self.group_random_reply_state.get(room_id, base_rate)
        current = max(0.0, min(base_rate, current))

        current = 0.0
        self.group_random_reply_state[room_id] = current
        self.LOG.debug(
            f"群聊随机闲聊概率已清零: 群={room_id}"
        )

    def _select_model_for_message(self, msg: WxMsg) -> None:
        """根据消息来源选择对应的AI模型
        :param msg: 接收到的消息
        """
        # 重置 force_reasoning 标记
        self._current_force_reasoning = False

        if not hasattr(self, 'chat_models') or not self.chat_models:
            return  # 没有可用模型，无需切换

        # 获取消息来源ID
        source_id = msg.roomid if msg.from_group() else msg.sender

        # 检查配置
        if not hasattr(self.config, 'GROUP_MODELS'):
            # 没有配置，使用默认模型
            if self.default_model_id in self.chat_models:
                self.chat = self.chat_models[self.default_model_id]
                self.current_model_id = self.default_model_id
            return

        # 群聊消息处理
        if msg.from_group():
            model_mappings = self.config.GROUP_MODELS.get('mapping', [])
            for mapping in model_mappings:
                if mapping.get('room_id') == source_id:
                    model_id = mapping.get('model')
                    # 读取 force_reasoning 配置
                    self._current_force_reasoning = bool(mapping.get('force_reasoning', False))
                    if model_id in self.chat_models:
                        # 切换到指定模型
                        if self.chat != self.chat_models[model_id]:
                            self.chat = self.chat_models[model_id]
                            self.LOG.info(f"已为群 {source_id} 切换到模型: {self.chat.__class__.__name__}")
                        self.current_model_id = model_id
                    else:
                        self.LOG.warning(f"群 {source_id} 配置的模型ID {model_id} 不可用，使用默认模型")
                        if self.default_model_id in self.chat_models:
                            self.chat = self.chat_models[self.default_model_id]
                            self.current_model_id = self.default_model_id
                    return
        # 私聊消息处理
        else:
            private_mappings = self.config.GROUP_MODELS.get('private_mapping', [])
            for mapping in private_mappings:
                if mapping.get('wxid') == source_id:
                    model_id = mapping.get('model')
                    if model_id in self.chat_models:
                        # 切换到指定模型
                        if self.chat != self.chat_models[model_id]:
                            self.chat = self.chat_models[model_id]
                            self.LOG.info(f"已为私聊用户 {source_id} 切换到模型: {self.chat.__class__.__name__}")
                        self.current_model_id = model_id
                    else:
                        self.LOG.warning(f"私聊用户 {source_id} 配置的模型ID {model_id} 不可用，使用默认模型")
                        if self.default_model_id in self.chat_models:
                            self.chat = self.chat_models[self.default_model_id]
                            self.current_model_id = self.default_model_id
                    return
        
        # 如果没有找到对应配置，使用默认模型
        if self.default_model_id in self.chat_models:
            self.chat = self.chat_models[self.default_model_id]
            self.current_model_id = self.default_model_id
            
    def _get_specific_history_limit(self, msg: WxMsg) -> int:
        """根据消息来源和配置，获取特定的历史消息数量限制
        
        :param msg: 微信消息对象
        :return: 历史消息数量限制，如果没有特定配置则返回None
        """
        if not hasattr(self.config, 'GROUP_MODELS'):
            # 没有配置，使用当前模型默认值
            return getattr(self.chat, 'max_history_messages', None)
            
        # 获取消息来源ID
        source_id = msg.roomid if msg.from_group() else msg.sender
        
        # 确定查找的映射和字段名
        if msg.from_group():
            mappings = self.config.GROUP_MODELS.get('mapping', [])
            key_field = 'room_id'
        else:
            mappings = self.config.GROUP_MODELS.get('private_mapping', [])
            key_field = 'wxid'
            
        # 在映射中查找特定配置
        for mapping in mappings:
            if mapping.get(key_field) == source_id:
                # 找到了对应的配置
                if 'max_history' in mapping:
                    specific_limit = mapping['max_history']
                    self.LOG.debug(f"为 {source_id} 找到特定历史限制: {specific_limit}")
                    return specific_limit
                else:
                    # 找到了配置但没有max_history，使用模型默认值
                    self.LOG.debug(f"为 {source_id} 找到映射但无特定历史限制，使用模型默认值")
                    break
                    
        # 没有找到特定限制，使用当前模型的默认值
        default_limit = getattr(self.chat, 'max_history_messages', None)
        self.LOG.debug(f"未找到 {source_id} 的特定历史限制，使用模型默认值: {default_limit}")
        return default_limit

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def preprocess(self, msg: WxMsg) -> MessageContext:
        """
        预处理消息，生成MessageContext对象
        :param msg: 微信消息对象
        :return: MessageContext对象
        """
        is_group = msg.from_group()
        is_at_bot = False
        pure_text = msg.content  # 默认使用原始内容
        
        # 初始化引用图片相关属性
        is_quoted_image = False
        quoted_msg_id = None
        quoted_image_extra = None
        
        msg_data = None
        # 处理引用消息等特殊情况
        if msg.type == 49 and ("<title>" in msg.content or "<appmsg" in msg.content):
            # 尝试提取引用消息中的文本
            if is_group:
                msg_data = self.xml_processor.extract_quoted_message(msg)
            else:
                msg_data = self.xml_processor.extract_private_quoted_message(msg)
                
            if msg_data and msg_data.get("new_content"):
                pure_text = msg_data["new_content"]
                # 检查是否包含@机器人
                if is_group and pure_text.startswith(f"@{self.allContacts.get(self.wxid, '')}"):
                    is_at_bot = True
                    pure_text = re.sub(r"^@.*?[\u2005|\s]", "", pure_text).strip()
            elif "<title>" in msg.content:
                # 备选：直接从title标签提取
                title_match = re.search(r'<title>(.*?)</title>', msg.content)
                if title_match:
                    pure_text = title_match.group(1).strip()
                    # 检查是否@机器人
                    if is_group and pure_text.startswith(f"@{self.allContacts.get(self.wxid, '')}"):
                        is_at_bot = True
                        pure_text = re.sub(r"^@.*?[\u2005|\s]", "", pure_text).strip()
            
            # 检查并提取图片引用信息
            if msg_data and msg_data.get("media_type") == "引用图片" and \
               msg_data.get("quoted_msg_id") and \
               msg_data.get("quoted_image_extra"):
                is_quoted_image = True
                quoted_msg_id = msg_data["quoted_msg_id"]
                quoted_image_extra = msg_data["quoted_image_extra"]
                self.LOG.info(f"预处理已提取引用图片信息: msg_id={quoted_msg_id}")
        
        # 处理文本消息
        elif msg.type == 1:  # 文本消息
            # 检查是否@机器人
            if is_group and msg.is_at(self.wxid):
                is_at_bot = True
                # 移除@前缀
                pure_text = re.sub(r"^@.*?[\u2005|\s]", "", msg.content).strip()
            else:
                pure_text = msg.content.strip()
        
        # 构造上下文对象
        ctx = MessageContext(
            msg=msg,
            wcf=self.wcf,
            config=self.config,
            all_contacts=self.allContacts,
            robot_wxid=self.wxid,
            robot=self,  # 传入Robot实例本身，便于handlers访问其方法
            logger=self.LOG,
            text=pure_text,
            is_group=is_group,
            is_at_bot=is_at_bot or (is_group and msg.is_at(self.wxid)),  # 确保is_at_bot正确
        )
        
        # 将图片引用信息添加到 ctx
        setattr(ctx, 'is_quoted_image', is_quoted_image)
        if is_quoted_image:
            setattr(ctx, 'quoted_msg_id', quoted_msg_id)
            setattr(ctx, 'quoted_image_extra', quoted_image_extra)
        
        # 标记是否引用了其他消息（用于后续逻辑过滤）
        setattr(ctx, 'has_quote_reference', bool(msg_data and msg_data.get("has_quote")))
        
        # 获取发送者昵称
        ctx.sender_name = ctx.get_sender_alias_or_name()
        
        self.LOG.debug(f"预处理消息: text='{ctx.text}', is_group={ctx.is_group}, is_at_bot={ctx.is_at_bot}, sender='{ctx.sender_name}', is_quoted_image={is_quoted_image}")
        return ctx
