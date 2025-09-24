# -*- coding: utf-8 -*-

import logging
import re
import time
import xml.etree.ElementTree as ET
from queue import Empty
from threading import Thread
import os
import random
import shutil
from image import AliyunImage, GeminiImage
from image.img_manager import ImageGenerationManager

from wcferry import Wcf, WxMsg

from ai_providers.ai_chatgpt import ChatGPT
from ai_providers.ai_deepseek import DeepSeek
from ai_providers.ai_gemini import Gemini
from ai_providers.ai_perplexity import Perplexity
from function.func_weather import Weather
from function.func_news import News
from function.func_summary import MessageSummary  # 导入新的MessageSummary类
from function.func_reminder import ReminderManager  # 导入ReminderManager类
from configuration import Config
from constants import ChatType
from job_mgmt import Job
from function.func_xml_process import XmlProcessor

# 导入Function Call系统
from commands.context import MessageContext
from commands.ai_router import ai_router
import commands.ai_functions  # 导入以注册所有AI功能

__version__ = "39.2.4.0"


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
        self.LOG.info("开始初始化各种AI模型...")

        # 初始化ChatGPT
        if ChatGPT.value_check(self.config.CHATGPT):
            try:
                # 传入 message_summary 和 wxid
                self.chat_models[ChatType.CHATGPT.value] = ChatGPT(
                    self.config.CHATGPT,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.wxid
                )
                self.LOG.info(f"已加载 ChatGPT 模型")
            except Exception as e:
                self.LOG.error(f"初始化 ChatGPT 模型时出错: {str(e)}")
            
        # 初始化DeepSeek
        if DeepSeek.value_check(self.config.DEEPSEEK):
            try:
                 # 传入 message_summary 和 wxid
                 self.chat_models[ChatType.DEEPSEEK.value] = DeepSeek(
                     self.config.DEEPSEEK,
                     message_summary_instance=self.message_summary,
                     bot_wxid=self.wxid
                 )
                 self.LOG.info(f"已加载 DeepSeek 模型")
            except Exception as e:
                 self.LOG.error(f"初始化 DeepSeek 模型时出错: {str(e)}")
        
        # 初始化Gemini
        if Gemini.value_check(self.config.GEMINI):
            try:
                # 传入 message_summary 和 wxid
                self.chat_models[ChatType.GEMINI.value] = Gemini(
                    self.config.GEMINI,
                    message_summary_instance=self.message_summary,
                    bot_wxid=self.wxid
                )
                self.LOG.info(f"已加载 Gemini 模型")
            except Exception as e:
                self.LOG.error(f"初始化 Gemini 模型时出错: {str(e)}")
            
        # 初始化Perplexity
        if Perplexity.value_check(self.config.PERPLEXITY):
            self.chat_models[ChatType.PERPLEXITY.value] = Perplexity(self.config.PERPLEXITY)
            self.perplexity = self.chat_models[ChatType.PERPLEXITY.value]  # 单独保存一个引用用于特殊处理
            self.LOG.info(f"已加载 Perplexity 模型")
            
        # 根据chat_type参数选择默认模型
        if chat_type > 0 and chat_type in self.chat_models:
            self.chat = self.chat_models[chat_type]
            self.default_model_id = chat_type
        else:
            # 如果没有指定chat_type或指定的模型不可用，尝试使用配置文件中指定的默认模型
            self.default_model_id = self.config.GROUP_MODELS.get('default', 0)
            if self.default_model_id in self.chat_models:
                self.chat = self.chat_models[self.default_model_id]
            elif self.chat_models:  # 如果有任何可用模型，使用第一个
                self.default_model_id = list(self.chat_models.keys())[0]
                self.chat = self.chat_models[self.default_model_id]
            else:
                self.LOG.warning("未配置任何可用的模型")
                self.chat = None
                self.default_model_id = 0

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
        
        # Function Call系统已自动加载
        self.LOG.info(f"🚀 Function Call系统初始化完成，共加载 {len(ai_router.functions)} 个智能功能")
        
        # 初始化提醒管理器
        try:
            # 使用与MessageSummary相同的数据库路径
            db_path = getattr(self.message_summary, 'db_path', "data/message_history.db")
            self.reminder_manager = ReminderManager(self, db_path)
            self.LOG.info("提醒管理器已初始化，与消息历史使用相同数据库。")
        except Exception as e:
            self.LOG.error(f"初始化提醒管理器失败: {e}", exc_info=True)
        
        # 输出AI功能列表信息，便于调试
        if self.LOG.isEnabledFor(logging.DEBUG):
            for name, func in ai_router.functions.items():
                self.LOG.debug(f"AI功能: {name} - {func.description} (scope: {func.scope}, need_at: {func.need_at})")

    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False

    def processMsg(self, msg: WxMsg) -> None:
        """
        处理收到的微信消息 - 纯Function Call实现
        :param msg: 微信消息对象
        """
        try:
            # 1. 使用MessageSummary记录消息
            self.message_summary.process_message_from_wxmsg(msg, self.wcf, self.allContacts, self.wxid)

            # 2. 预处理消息，生成MessageContext
            ctx = self.preprocess(msg)
            setattr(ctx, 'chat', self.chat)

            # 3. 直接使用Function Call系统处理所有消息
            handled = ai_router.dispatch(ctx)
            if handled:
                return

            # 4. 特殊系统消息处理
            if msg.type == 37:  # 好友请求
                self.autoAcceptFriendRequest(msg)
                return

            elif msg.type == 10000:
                # 处理新成员入群
                if "加入了群聊" in msg.content and msg.from_group():
                    new_member_match = re.search(r'"(.+?)"邀请"(.+?)"加入了群聊', msg.content)
                    if new_member_match:
                        inviter = new_member_match.group(1)
                        new_member = new_member_match.group(2)
                        welcome_msg = self.config.WELCOME_MSG.format(new_member=new_member, inviter=inviter)
                        self.sendTextMsg(welcome_msg, msg.roomid)
                        self.LOG.info(f"已发送欢迎消息给新成员 {new_member} 在群 {msg.roomid}")
                    return
                # 处理新好友添加
                elif "你已添加了" in msg.content:
                    self.sayHiToNewFriend(msg)
                    return

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

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息并记录
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：notify@all
        """
        # 延迟和频率限制 (逻辑不变)
        time.sleep(float(str(time.time()).split('.')[-1][-2:]) / 100.0 + 0.3)
        now = time.time()
        if self.config.SEND_RATE_LIMIT > 0:
            self._msg_timestamps = [t for t in self._msg_timestamps if now - t < 60]
            if len(self._msg_timestamps) >= self.config.SEND_RATE_LIMIT:
                self.LOG.warning(f"发送消息过快，已达到每分钟{self.config.SEND_RATE_LIMIT}条上限。")
                return
            self._msg_timestamps.append(now)

        ats = ""
        message_to_send = msg # 保存原始消息用于记录
        if at_list:
            if at_list == "notify@all":
                ats = " @所有人"
            else:
                wxids = at_list.split(",")
                for wxid_at in wxids: # Renamed variable
                    ats += f" @{self.wcf.get_alias_in_chatroom(wxid_at, receiver)}"

        try:
            # 发送消息 (逻辑不变)
            if ats == "":
                self.LOG.info(f"To {receiver}: {msg}")
                self.wcf.send_text(f"{msg}", receiver, at_list)
            else:
                full_msg_content = f"{ats}\n\n{msg}"
                self.LOG.info(f"To {receiver}:\n{ats}\n{msg}")
                self.wcf.send_text(full_msg_content, receiver, at_list)

            if self.message_summary: # 检查 message_summary 是否初始化成功
                 # 确定机器人的名字
                 robot_name = self.allContacts.get(self.wxid, "机器人")
                 # 使用 self.wxid 作为 sender_wxid
                 # 注意：这里不生成时间戳，让 record_message 内部生成
                 self.message_summary.record_message(
                     chat_id=receiver,
                     sender_name=robot_name,
                     sender_wxid=self.wxid, # 传入机器人自己的 wxid
                     content=message_to_send
                 )
                 self.LOG.debug(f"已记录机器人发送的消息到 {receiver}")
            else:
                self.LOG.warning("MessageSummary 未初始化，无法记录发送的消息")

        except Exception as e:
            self.LOG.error(f"发送消息失败: {e}")

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
            self.sendTextMsg(f"Hi {nickName[0]}，我是泡泡，我自动通过了你的好友请求。", msg.sender)

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

    def _select_model_for_message(self, msg: WxMsg) -> None:
        """根据消息来源选择对应的AI模型
        :param msg: 接收到的消息
        """
        if not hasattr(self, 'chat_models') or not self.chat_models:
            return  # 没有可用模型，无需切换

        # 获取消息来源ID
        source_id = msg.roomid if msg.from_group() else msg.sender

        # 检查配置
        if not hasattr(self.config, 'GROUP_MODELS'):
            # 没有配置，使用默认模型
            if self.default_model_id in self.chat_models:
                self.chat = self.chat_models[self.default_model_id]
            return

        # 群聊消息处理
        if msg.from_group():
            model_mappings = self.config.GROUP_MODELS.get('mapping', [])
            for mapping in model_mappings:
                if mapping.get('room_id') == source_id:
                    model_id = mapping.get('model')
                    if model_id in self.chat_models:
                        # 切换到指定模型
                        if self.chat != self.chat_models[model_id]:
                            self.chat = self.chat_models[model_id]
                            self.LOG.info(f"已为群 {source_id} 切换到模型: {self.chat.__class__.__name__}")
                    else:
                        self.LOG.warning(f"群 {source_id} 配置的模型ID {model_id} 不可用，使用默认模型")
                        if self.default_model_id in self.chat_models:
                            self.chat = self.chat_models[self.default_model_id]
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
                    else:
                        self.LOG.warning(f"私聊用户 {source_id} 配置的模型ID {model_id} 不可用，使用默认模型")
                        if self.default_model_id in self.chat_models:
                            self.chat = self.chat_models[self.default_model_id]
                    return

        # 如果没有找到对应配置，使用默认模型
        if self.default_model_id in self.chat_models:
            self.chat = self.chat_models[self.default_model_id]

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
        
        # 获取发送者昵称
        ctx.sender_name = ctx.get_sender_alias_or_name()
        
        self.LOG.debug(f"预处理消息: text='{ctx.text}', is_group={ctx.is_group}, is_at_bot={ctx.is_at_bot}, sender='{ctx.sender_name}', is_quoted_image={is_quoted_image}")
        return ctx

