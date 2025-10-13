# -*- coding: utf-8 -*-

import logging
import time
import re
from collections import deque
# from threading import Lock  # 不再需要锁，使用SQLite的事务机制
import sqlite3  # 添加sqlite3模块
import os  # 用于处理文件路径
from function.func_xml_process import XmlProcessor  # 导入XmlProcessor

MAX_DB_HISTORY_LIMIT = 10000


class MessageSummary:
    """消息总结功能类 (使用SQLite持久化)
    用于记录、管理和生成聊天历史消息的总结
    """

    def __init__(self, max_history=MAX_DB_HISTORY_LIMIT, db_path="data/message_history.db"):
        """初始化消息总结功能

        Args:
            max_history: 每个聊天保存的最大消息数量
            db_path: SQLite数据库文件路径
        """
        self.LOG = logging.getLogger("MessageSummary")
        try:
            parsed_history_limit = int(max_history)
        except (TypeError, ValueError):
            parsed_history_limit = MAX_DB_HISTORY_LIMIT

        if parsed_history_limit <= 0:
            parsed_history_limit = MAX_DB_HISTORY_LIMIT

        if parsed_history_limit > MAX_DB_HISTORY_LIMIT:
            self.LOG.warning(
                f"传入的 max_history={parsed_history_limit} 超过上限，将截断为 {MAX_DB_HISTORY_LIMIT}"
            )
            parsed_history_limit = MAX_DB_HISTORY_LIMIT

        self.max_history = parsed_history_limit
        self.db_path = db_path

        # 实例化XML处理器用于提取引用消息
        self.xml_processor = XmlProcessor(self.LOG)

        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
                self.LOG.info(f"创建数据库目录: {db_dir}")

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.conn.cursor()
            self.LOG.info(f"已连接到 SQLite 数据库: {self.db_path}")

            # 检查并添加 sender_wxid 列 (如果不存在)
            self.cursor.execute("PRAGMA table_info(messages)")
            columns = [col[1] for col in self.cursor.fetchall()]
            if 'sender_wxid' not in columns:
                try:
                    self.cursor.execute("ALTER TABLE messages ADD COLUMN sender_wxid TEXT")
                    self.conn.commit()
                    self.LOG.info("已向 messages 表添加 sender_wxid 列")
                except sqlite3.OperationalError as e:
                     # 如果表是空的，直接删除重建可能更简单
                     self.LOG.warning(f"添加 sender_wxid 列失败 ({e})，可能是因为表非空且有主键？尝试重建表。")
                     # 注意：这会丢失现有数据！
                     self.cursor.execute("DROP TABLE IF EXISTS messages")
                     self.conn.commit()


            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    sender_wxid TEXT, -- 新增: 存储发送者wxid
                    content TEXT NOT NULL,
                    timestamp_float REAL NOT NULL,
                    timestamp_str TEXT NOT NULL -- 存储完整时间格式 YYYY-MM-DD HH:MM:SS
                )
            """)

            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_time ON messages (chat_id, timestamp_float)
            """)
            # 新增 sender_wxid 索引 (可选，如果经常需要按wxid查询)
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sender_wxid ON messages (sender_wxid)
            """)
            self.conn.commit() # 提交更改
            self.LOG.info("消息表已准备就绪")

        except sqlite3.Error as e:
            self.LOG.error(f"数据库初始化失败: {e}")
            raise ConnectionError(f"无法连接或初始化数据库: {e}") from e
        except OSError as e:
            self.LOG.error(f"创建数据库目录失败: {e}")
            raise OSError(f"无法创建数据库目录: {e}") from e

    def close_db(self):
        """关闭数据库连接"""
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.commit() # 确保所有更改都已保存
                self.conn.close()
                self.LOG.info("数据库连接已关闭")
            except sqlite3.Error as e:
                self.LOG.error(f"关闭数据库连接时出错: {e}")

    def record_message(self, chat_id, sender_name, sender_wxid, content, timestamp=None):
        """记录单条消息到数据库

        Args:
            chat_id: 聊天ID（群ID或用户ID）
            sender_name: 发送者名称
            sender_wxid: 发送者wxid
            content: 消息内容
            timestamp: 外部提供的时间字符串（优先使用），否则生成
        """
        try:
            current_time_float = time.time()

            if not timestamp:
                # 默认使用完整时间格式
                timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time_float))
            else:
                 # 如果传入的时间戳只有时分，转换为完整格式
                 if len(timestamp) <= 5:  # 如果格式是 "HH:MM"
                     today = time.strftime("%Y-%m-%d", time.localtime(current_time_float))
                     timestamp_str = f"{today} {timestamp}:00" # 补上秒
                 elif len(timestamp) == 8 and timestamp.count(':') == 2: # 如果格式是 "HH:MM:SS"
                     today = time.strftime("%Y-%m-%d", time.localtime(current_time_float))
                     timestamp_str = f"{today} {timestamp}"
                 elif len(timestamp) == 16 and timestamp.count('-') == 2 and timestamp.count(':') == 1: # "YYYY-MM-DD HH:MM"
                     timestamp_str = f"{timestamp}:00" # 补上秒
                 else:
                     timestamp_str = timestamp # 假设是完整格式

            # 插入新消息，包含 sender_wxid
            self.cursor.execute("""
                INSERT INTO messages (chat_id, sender, sender_wxid, content, timestamp_float, timestamp_str)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, sender_name, sender_wxid, content, current_time_float, timestamp_str))

            # 删除超出 max_history 的旧消息
            self.cursor.execute("""
                DELETE FROM messages
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY timestamp_float DESC
                    LIMIT ?
                )
            """, (chat_id, chat_id, self.max_history))

            self.conn.commit() # 提交事务

        except sqlite3.Error as e:
            self.LOG.error(f"记录消息到数据库时出错: {e}")
            try:
                self.conn.rollback()
            except:
                pass

    def clear_message_history(self, chat_id):
        """清除指定聊天的消息历史记录

        Args:
            chat_id: 聊天ID（群ID或用户ID）

        Returns:
            bool: 是否成功清除
        """
        try:
            self.cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            rows_deleted = self.cursor.rowcount
            self.conn.commit()
            self.LOG.info(f"为 chat_id={chat_id} 清除了 {rows_deleted} 条历史消息")
            return True

        except sqlite3.Error as e:
            self.LOG.error(f"清除消息历史时出错 (chat_id={chat_id}): {e}")
            return False

    def get_message_count(self, chat_id):
        """获取指定聊天的消息数量

        Args:
            chat_id: 聊天ID（群ID或用户ID）

        Returns:
            int: 消息数量
        """
        try:
            self.cursor.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 0

        except sqlite3.Error as e:
            self.LOG.error(f"获取消息数量时出错 (chat_id={chat_id}): {e}")
            return 0

    def get_messages(self, chat_id):
        """获取指定聊天的所有消息 (按时间升序)，包含发送者wxid和完整时间戳

        Args:
            chat_id: 聊天ID（群ID或用户ID）

        Returns:
            list: 消息列表，格式为 [{"sender": ..., "sender_wxid": ..., "content": ..., "time": ...}]
        """
        messages = []
        try:
            # 查询需要的字段，包括 sender_wxid 和 timestamp_str
            self.cursor.execute("""
                SELECT sender, sender_wxid, content, timestamp_str
                FROM messages
                WHERE chat_id = ?
                ORDER BY timestamp_float ASC
                LIMIT ?
            """, (chat_id, self.max_history))

            rows = self.cursor.fetchall()

            # 将数据库行转换为期望的字典列表格式
            for row in rows:
                messages.append({
                    "sender": row[0],
                    "sender_wxid": row[1], # 添加 sender_wxid
                    "content": row[2],
                    "time": row[3] # 使用存储的完整 timestamp_str
                })

        except sqlite3.Error as e:
            self.LOG.error(f"获取消息列表时出错 (chat_id={chat_id}): {e}")

        return messages

    def search_messages_with_context(self, chat_id, keywords, context_window=5, max_groups=20):
        """根据关键词搜索消息，返回包含前后上下文的结果

        Args:
            chat_id (str): 聊天ID（群ID或用户ID）
            keywords (Union[str, list[str]]): 需要搜索的关键词或关键词列表
            context_window (int): 每条匹配消息前后额外提供的消息数量
            max_groups (int): 返回的最多结果组数（按时间倒序，优先最新消息）

        Returns:
            list[dict]: 搜索结果列表，每个元素包含匹配关键词、锚点消息及上下文消息
        """
        if not keywords:
            return []

        if isinstance(keywords, str):
            keywords = [keywords]

        normalized_keywords = []
        for kw in keywords:
            if kw is None:
                continue
            kw_str = str(kw).strip()
            if kw_str:
                normalized_keywords.append((kw_str, kw_str.lower()))

        if not normalized_keywords:
            return []

        try:
            context_window = int(context_window)
        except (TypeError, ValueError):
            context_window = 5
        context_window = max(0, min(context_window, 10))  # 限制上下文窗口大小，避免过长

        try:
            max_groups = int(max_groups)
        except (TypeError, ValueError):
            max_groups = 20
        max_groups = max(1, min(max_groups, 20))

        messages = self.get_messages(chat_id)
        if not messages:
            return []

        results = []
        total_messages = len(messages)
        used_indices = set()

        for idx in range(total_messages - 1, -1, -1):
            message = messages[idx]
            content = message.get("content", "")
            if not content:
                continue

            lower_content = content.lower()
            matched_keywords = [orig for orig, lower in normalized_keywords if lower in lower_content]
            if not matched_keywords:
                continue

            if idx in used_indices:
                continue

            start = max(0, idx - context_window)
            end = min(total_messages, idx + context_window + 1)
            segment_messages = []

            for pos in range(start, end):
                msg = messages[pos]
                segment_messages.append({
                    "time": msg.get("time"),
                    "sender": msg.get("sender"),
                    "sender_wxid": msg.get("sender_wxid"),
                    "content": msg.get("content"),
                    "relative_offset": pos - idx,
                    "is_match": pos == idx
                })

            results.append({
                "matched_keywords": matched_keywords,
                "anchor_index": idx,
                "anchor_time": message.get("time"),
                "anchor_sender": message.get("sender"),
                "anchor_sender_wxid": message.get("sender_wxid"),
                "messages": segment_messages
            })

            for off in range(start, end):
                used_indices.add(off)

            if len(results) >= max_groups:
                break

        return results

    def _basic_summarize(self, messages):
        """基本的消息总结逻辑，不使用AI

        Args:
            messages: 消息列表 (格式同 get_messages 返回值)

        Returns:
            str: 消息总结
        """
        if not messages:
            return "没有可以总结的历史消息。"

        res = ["以下是近期聊天记录摘要：\n"]
        for msg in messages:
            # 使用新的时间格式和发送者
            res.append(f"[{msg['time']}]{msg['sender']}: {msg['content']}")

        return "\n".join(res)

    def _ai_summarize(self, messages, chat_model, chat_id):
        """使用AI模型生成消息总结

        Args:
            messages: 消息列表 (格式同 get_messages 返回值)
            chat_model: AI聊天模型对象
            chat_id: 聊天ID

        Returns:
            str: 消息总结
        """
        if not messages:
            return "没有可以总结的历史消息。"

        formatted_msgs = []
        for msg in messages:
            # 使用新的时间格式和发送者
            formatted_msgs.append(f"[{msg['time']}]{msg['sender']}: {msg['content']}")

        # 构建提示词 ... (保持不变)
        prompt = (
            "你是泡泡，请仔细阅读并分析以下聊天记录，生成一简要的、结构清晰且抓住重点的摘要。\n\n"
            "摘要格式要求：\n"
            "1. 使用数字编号列表 (例如 1., 2., 3.) 来组织内容，每个编号代表一个独立的主要讨论主题，不要超过3个主题。\n"
            "2. 在每个编号的主题下，写成一段不带格式的文字，每个主题单独成段并空行，需包含以下内容：\n"
            "    - 这个讨论的核心的简要描述。\n"
            "    - 该讨论的关键成员 (用括号 [用户名] 格式) 和他们的关键发言内容、成员之间的关键互动。\n"
            "    - 该讨论的讨论结果。\n"
            "3. 总结需客观、精炼、简短精悍，直接呈现最核心且精简的事实，尽量不要添加额外的评论或分析，不要总结有关自己的事情。\n"
            "4. 不要暴露出格式，不要说核心是xxx参与者是xxx结果是xxx，自然一点。\n\n"
            "聊天记录如下：\n" + "\n".join(formatted_msgs)
        )

        try:
            # 调用AI部分保持不变，但现在AI模型内部应使用数据库历史记录
            # 确保调用 get_answer 时，AI模型实例已经关联了 MessageSummary
            summary = chat_model.get_answer(prompt, f"summary_{chat_id}") # 使用特殊 wxid 避免冲突


            if not summary:
                return self._basic_summarize(messages)

            return summary
        except Exception as e:
            self.LOG.error(f"使用AI生成总结失败: {e}")
            return self._basic_summarize(messages)

    def summarize_messages(self, chat_id, chat_model=None):
        """生成消息总结

        Args:
            chat_id: 聊天ID（群ID或用户ID）
            chat_model: AI聊天模型对象，如果为None则使用基础总结

        Returns:
            str: 消息总结
        """
        messages = self.get_messages(chat_id)
        if not messages:
            return "没有可以总结的历史消息。"

        if chat_model:
             # 检查 chat_model 是否具有 get_answer 方法并且已经初始化了 message_summary
            if hasattr(chat_model, 'get_answer') and hasattr(chat_model, 'message_summary') and chat_model.message_summary:
                return self._ai_summarize(messages, chat_model, chat_id)
            else:
                self.LOG.warning(f"提供的 chat_model ({type(chat_model)}) 不支持基于数据库历史的总结或未正确初始化。将使用基础总结。")
                return self._basic_summarize(messages)
        else:
            return self._basic_summarize(messages)

    def process_message_from_wxmsg(self, msg, wcf, all_contacts, bot_wxid=None):
        """从微信消息对象中处理并记录与总结相关的文本消息
        记录所有群聊和私聊的文本(1)和App/卡片(49)消息。
        使用 XmlProcessor 提取用户实际输入的新内容或卡片标题。

        Args:
            msg: 微信消息对象(WxMsg)
            wcf: 微信接口对象
            all_contacts: 所有联系人字典
            bot_wxid: 机器人自己的wxid (必须提供以正确记录 sender_wxid)
        """
        if msg.type != 0x01 and msg.type != 49:
            return

        chat_id = msg.roomid if msg.from_group() else msg.sender
        if not chat_id:
            self.LOG.warning(f"无法确定消息的chat_id (msg.id={msg.id}), 跳过记录")
            return

        sender_wxid = msg.sender
        if not sender_wxid:
             # 理论上不应发生，但做个防护
             self.LOG.error(f"消息 (id={msg.id}) 缺少 sender wxid，无法记录！")
             return

        # 确定发送者名称 (逻辑不变)
        sender_name = ""
        if msg.from_group():
            sender_name = wcf.get_alias_in_chatroom(sender_wxid, chat_id)
            if not sender_name:
                sender_name = all_contacts.get(sender_wxid, sender_wxid)
        else:
            if bot_wxid and sender_wxid == bot_wxid:
                 sender_name = all_contacts.get(bot_wxid, "机器人")
            else:
                 sender_name = all_contacts.get(sender_wxid, sender_wxid)

        # 使用 XmlProcessor 提取消息详情 (逻辑不变)
        extracted_data = None
        try:
            if msg.from_group():
                extracted_data = self.xml_processor.extract_quoted_message(msg)
            else:
                extracted_data = self.xml_processor.extract_private_quoted_message(msg)
        except Exception as e:
            self.LOG.error(f"使用XmlProcessor提取消息内容时出错 (msg.id={msg.id}, type={msg.type}): {e}")
            if msg.type == 0x01 and not ("<" in msg.content and ">" in msg.content):
                 content_to_record = msg.content.strip()
                 source_info = "来自 纯文本消息 (XML解析失败后备)"
                 self.LOG.warning(f"XML解析失败，但记录纯文本消息: {content_to_record[:50]}...")
                 current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                 # 调用 record_message 时需要 sender_wxid
                 self.record_message(chat_id, sender_name, sender_wxid, content_to_record, current_time_str)
            return

        # 确定要记录的内容 (content_to_record) - 复用之前的逻辑
        content_to_record = ""
        source_info = "未知来源"
        # 优先使用提取到的新内容 (来自回复或普通文本或<title>)
        temp_new_content = extracted_data.get("new_content", "").strip()
        if temp_new_content:
            content_to_record = temp_new_content
            source_info = "来自 new_content (回复/文本/标题)"

            # 如果是引用类型消息，添加引用标记和引用内容的简略信息
            if extracted_data.get("has_quote", False):
                quoted_sender = extracted_data.get("quoted_sender", "")
                quoted_content = extracted_data.get("quoted_content", "")

                # 处理被引用内容
                if quoted_content:
                    # 对较长的引用内容进行截断
                    max_quote_length = 30
                    if len(quoted_content) > max_quote_length:
                        quoted_content = quoted_content[:max_quote_length] + "..."

                    # 如果被引用的是卡片，则使用标准卡片格式
                    if extracted_data.get("quoted_is_card", False):
                        quoted_card_title = extracted_data.get("quoted_card_title", "")
                        quoted_card_type = extracted_data.get("quoted_card_type", "")

                        # 根据卡片类型确定内容类型
                        card_type = "卡片"
                        if "链接" in quoted_card_type or "消息" in quoted_card_type:
                            card_type = "链接"
                        elif "视频" in quoted_card_type or "音乐" in quoted_card_type:
                            card_type = "媒体"
                        elif "位置" in quoted_card_type:
                            card_type = "位置"
                        elif "图片" in quoted_card_type:
                            card_type = "图片"
                        elif "文件" in quoted_card_type:
                            card_type = "文件"

                        # 整个卡片内容包裹在【】中
                        quoted_content = f"【{card_type}: {quoted_card_title}】"

                    # 根据是否有被引用者信息构建引用前缀
                    if quoted_sender:
                        content_to_record = f"{content_to_record} 【回复 {quoted_sender}：{quoted_content}】"
                    else:
                        content_to_record = f"{content_to_record} 【回复：{quoted_content}】"

        # 其次，如果新内容为空，但这是一个卡片且有标题，则使用卡片标题
        elif extracted_data.get("is_card") and extracted_data.get("card_title", "").strip():
            card_title = extracted_data.get("card_title", "").strip()
            card_description = extracted_data.get("card_description", "").strip()
            card_type = extracted_data.get("card_type", "")
            card_source = extracted_data.get("card_appname") or extracted_data.get("card_sourcedisplayname", "")

            if "链接" in card_type or "消息" in card_type: content_type = "链接"
            elif "视频" in card_type or "音乐" in card_type: content_type = "媒体"
            elif "位置" in card_type: content_type = "位置"
            elif "图片" in card_type: content_type = "图片"
            elif "文件" in card_type: content_type = "文件"
            else: content_type = "卡片"

            card_content = f"{content_type}: {card_title}"
            if card_description:
                max_desc_length = 50
                if len(card_description) > max_desc_length:
                    card_description = card_description[:max_desc_length] + "..."
                card_content += f" - {card_description}"
            if card_source:
                card_content += f" (来自:{card_source})"
            content_to_record = f"【{card_content}】"
            source_info = "来自 卡片(标题+描述)"

        # 普通文本消息的保底处理
        elif msg.type == 0x01 and not ("<" in msg.content and ">" in msg.content): # 再次确认是纯文本
             content_to_record = msg.content.strip() # 使用原始纯文本
             source_info = "来自 纯文本消息"


        # 如果最终没有提取到有效内容，则不记录 (逻辑不变)
        if not content_to_record:
            self.LOG.debug(f"未能提取到有效文本内容用于记录，跳过 (msg.id={msg.id}, type={msg.type}) - IsCard: {extracted_data.get('is_card', False)}, HasQuote: {extracted_data.get('has_quote', False)}")
            return

        # 获取当前时间字符串 (使用完整格式)
        current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        self.LOG.debug(f"记录消息 (来源: {source_info}, 类型: {'群聊' if msg.from_group() else '私聊'}): '[{current_time_str}]{sender_name}({sender_wxid}): {content_to_record}' (来自 msg.id={msg.id})")
        # 调用 record_message 时传入 sender_wxid
        self.record_message(chat_id, sender_name, sender_wxid, content_to_record, current_time_str)
