# -*- coding: utf-8 -*-

import sqlite3
import uuid
import time
import schedule
from datetime import datetime, timedelta
import logging
import threading
from typing import Optional, Dict, Tuple  # 添加类型提示导入

# 获取 Logger 实例
logger = logging.getLogger("ReminderManager")

class ReminderManager:
    # 使用线程锁确保数据库操作的线程安全
    _db_lock = threading.Lock()

    def __init__(self, robot, db_path: str, check_interval_minutes=1):
        """
        初始化 ReminderManager。
        :param robot: Robot 实例，用于发送消息。
        :param db_path: SQLite 数据库文件路径。
        :param check_interval_minutes: 检查提醒任务的频率（分钟）。
        """
        self.robot = robot
        self.db_path = db_path
        self._create_table() # 初始化时确保表存在

        # 注册周期性检查任务
        schedule.every(check_interval_minutes).minutes.do(self.check_and_trigger_reminders)
        logger.info(f"提醒管理器已初始化，连接到数据库 '{db_path}'，每 {check_interval_minutes} 分钟检查一次。")

    def _get_db_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        try:
            # connect_timeout 增加等待时间，check_same_thread=False 允许其他线程使用 (配合锁)
            conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row # 让查询结果可以像字典一样访问列
            return conn
        except sqlite3.Error as e:
            logger.error(f"无法连接到 SQLite 数据库 '{self.db_path}': {e}", exc_info=True)
            raise # 连接失败是严重问题，直接抛出异常

    def _create_table(self):
        """创建 reminders 表（如果不存在）"""
        sql = """
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            wxid TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('once', 'daily', 'weekly')),
            time_str TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_triggered_at TEXT,
            weekday INTEGER,
            roomid TEXT
        );
        """
        # 创建索引的 SQL
        index_sql_wxid = "CREATE INDEX IF NOT EXISTS idx_reminders_wxid ON reminders (wxid);"
        index_sql_type = "CREATE INDEX IF NOT EXISTS idx_reminders_type ON reminders (type);"
        index_sql_roomid = "CREATE INDEX IF NOT EXISTS idx_reminders_roomid ON reminders (roomid);"

        try:
            with self._db_lock: # 加锁保护数据库连接和操作
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()
                    # 1. 先确保表存在
                    cursor.execute(sql)
                    
                    # 2. 尝试添加新列（如果表已存在且没有该列）
                    try:
                        # 检查列是否存在
                        cursor.execute("PRAGMA table_info(reminders);")
                        columns = [col['name'] for col in cursor.fetchall()]
                        
                        # 添加 weekday 列（如果不存在）
                        if 'weekday' not in columns:
                            cursor.execute("ALTER TABLE reminders ADD COLUMN weekday INTEGER;")
                            logger.info("成功添加 'weekday' 列到 'reminders' 表。")
                            
                        # 添加 roomid 列（如果不存在）
                        if 'roomid' not in columns:
                            cursor.execute("ALTER TABLE reminders ADD COLUMN roomid TEXT;")
                            logger.info("成功添加 'roomid' 列到 'reminders' 表。")
                    except sqlite3.OperationalError as e:
                        # 如果列已存在，会报错误，可以忽略
                        logger.warning(f"尝试添加列时发生错误: {e}")
                    
                    # 3. 创建索引
                    cursor.execute(index_sql_wxid)
                    cursor.execute(index_sql_type)
                    cursor.execute(index_sql_roomid)
                    conn.commit()
            logger.info("数据库表 'reminders' 检查/创建 完成。")
        except sqlite3.Error as e:
            logger.error(f"创建/检查数据库表 'reminders' 失败: {e}", exc_info=True)

    # --- 对外接口 ---
    def add_reminder(self, wxid: str, data: dict, roomid: Optional[str] = None) -> Tuple[bool, str]:
        """
        将解析后的提醒数据添加到数据库。
        :param wxid: 用户的微信 ID。
        :param data: 包含 type, time, content 的字典。
        :param roomid: 群聊ID，如果在群聊中设置提醒则不为空
        :return: (是否成功, 提醒 ID 或 错误信息)
        """
        reminder_id = str(uuid.uuid4())
        created_at_iso = datetime.now().isoformat()

        # 校验数据 (基本)
        required_keys = {"type", "time", "content"}
        if not required_keys.issubset(data.keys()):
            return False, "AI 返回的 JSON 缺少必要字段 (type, time, content)"
        if data["type"] not in ["once", "daily", "weekly"]:
            return False, f"不支持的提醒类型: {data['type']}"

        # 进一步校验时间格式 (根据类型)
        weekday_val = None # 初始化 weekday
        time_value = data.get("time", "")
        if data["type"] == "once":
            # 尝试解析，确保格式正确，并且是未来的时间
            trigger_dt = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    trigger_dt = datetime.strptime(time_value, fmt)
                    break
                except ValueError:
                    continue
            if not trigger_dt:
                return False, f"一次性提醒时间格式错误 ({time_value})，需要 'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD HH:MM:SS'"
            if trigger_dt <= datetime.now():
                return False, f"一次性提醒时间 ({time_value}) 必须是未来的时间"
            # 统一保存为分钟精度
            data["time"] = trigger_dt.strftime("%Y-%m-%d %H:%M")
        elif data["type"] == "daily":
            parsed_time = None
            for fmt in ("%H:%M", "%H:%M:%S"):
                try:
                    parsed_time = datetime.strptime(time_value, fmt)
                    break
                except ValueError:
                    continue
            if not parsed_time:
                return False, f"每日提醒时间格式错误 ({time_value})，需要 'HH:MM' 或 'HH:MM:SS'"
            data["time"] = parsed_time.strftime("%H:%M")
        elif data["type"] == "weekly":
            parsed_time = None
            for fmt in ("%H:%M", "%H:%M:%S"):
                try:
                    parsed_time = datetime.strptime(time_value, fmt)
                    break
                except ValueError:
                    continue
            if not parsed_time:
                return False, f"每周提醒时间格式错误 ({time_value})，需要 'HH:MM' 或 'HH:MM:SS'"
            data["time"] = parsed_time.strftime("%H:%M")
            if "weekday" not in data or not isinstance(data["weekday"], int) or not (0 <= data["weekday"] <= 6):
                return False, "每周提醒必须提供有效的 weekday 字段 (0-6)"
            weekday_val = data["weekday"] # 获取 weekday 值

        # 准备插入数据库
        sql = """
        INSERT INTO reminders (id, wxid, type, time_str, content, created_at, last_triggered_at, weekday, roomid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            reminder_id,
            wxid,
            data["type"],
            data["time"],
            data["content"],
            created_at_iso,
            None, # last_triggered_at 初始为 NULL
            weekday_val, # weekday 字段
            roomid  # 新增：roomid 参数
        )

        try:
            with self._db_lock: # 加锁
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, params)
                    conn.commit()
            # 记录日志时包含群聊信息
            log_target = f"用户 {wxid}" + (f" 在群聊 {roomid}" if roomid else "")
            logger.info(f"成功添加提醒 {reminder_id} for {log_target} 到数据库。")
            return True, reminder_id
        except sqlite3.IntegrityError as e: # 例如，如果 UUID 冲突 (极不可能)
            logger.error(f"添加提醒失败 (数据冲突): {e}", exc_info=True)
            return False, f"添加提醒失败 (数据冲突): {e}"
        except sqlite3.Error as e:
            logger.error(f"添加提醒到数据库失败: {e}", exc_info=True)
            return False, f"数据库错误: {e}"

    # --- 核心检查逻辑 ---
    def check_and_trigger_reminders(self):
        """由 schedule 定期调用。检查数据库，触发到期的提醒。"""
        now = datetime.now()
        now_iso = now.isoformat()
        current_weekday = now.weekday() # 获取今天是周几 (0-6)
        current_hm = now.strftime("%H:%M") # 当前时分
        
        reminders_to_delete = [] # 存储需要删除的 once 提醒 ID
        reminders_to_update = [] # 存储需要更新 last_triggered_at 的 daily/weekly 提醒 ID

        try:
            with self._db_lock: # 加锁
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()

                    # 1. 查询到期的一次性提醒
                    sql_once = """
                    SELECT id, wxid, content, roomid FROM reminders
                    WHERE type = 'once' AND time_str <= ?
                    """
                    cursor.execute(sql_once, (now.strftime("%Y-%m-%d %H:%M"),))
                    due_once_reminders = cursor.fetchall()

                    for reminder in due_once_reminders:
                        self._send_reminder(reminder["wxid"], reminder["content"], reminder["id"], reminder["roomid"])
                        reminders_to_delete.append(reminder["id"])
                        logger.info(f"一次性提醒 {reminder['id']} 已触发并标记删除。")

                    # 2. 查询到期的每日提醒
                    # a. 获取当前时间 HH:MM
                    # b. 查询所有 daily 提醒
                    sql_daily_all = "SELECT id, wxid, content, time_str, last_triggered_at, roomid FROM reminders WHERE type = 'daily'"
                    cursor.execute(sql_daily_all)
                    all_daily_reminders = cursor.fetchall()

                    for reminder in all_daily_reminders:
                        # 检查时间是否到达或超过 daily 设置的 HH:MM
                        if current_hm >= reminder["time_str"]:
                            last_triggered_dt = None
                            if reminder["last_triggered_at"]:
                                try:
                                    last_triggered_dt = datetime.fromisoformat(reminder["last_triggered_at"])
                                except ValueError:
                                    logger.warning(f"无法解析 daily 提醒 {reminder['id']} 的 last_triggered_at: {reminder['last_triggered_at']}")

                            # 计算今天应该触发的时间点 (用于比较)
                            trigger_hm_dt = datetime.strptime(reminder["time_str"], "%H:%M").time()
                            today_trigger_dt = now.replace(hour=trigger_hm_dt.hour, minute=trigger_hm_dt.minute, second=0, microsecond=0)

                            # 如果从未触发过，或者上次触发是在今天的触发时间点之前，则应该触发
                            if last_triggered_dt is None or last_triggered_dt < today_trigger_dt:
                                self._send_reminder(reminder["wxid"], reminder["content"], reminder["id"], reminder["roomid"])
                                reminders_to_update.append(reminder["id"])
                                logger.info(f"每日提醒 {reminder['id']} 已触发并标记更新触发时间。")
                                
                    # 3. 查询并处理到期的 'weekly' 提醒
                    sql_weekly = """
                    SELECT id, wxid, content, time_str, last_triggered_at, roomid FROM reminders
                    WHERE type = 'weekly' AND weekday = ? AND time_str <= ?
                    """
                    cursor.execute(sql_weekly, (current_weekday, current_hm))
                    due_weekly_reminders = cursor.fetchall()

                    for reminder in due_weekly_reminders:
                        last_triggered_dt = None
                        if reminder["last_triggered_at"]:
                            try:
                                last_triggered_dt = datetime.fromisoformat(reminder["last_triggered_at"])
                            except ValueError:
                                logger.warning(f"无法解析 weekly 提醒 {reminder['id']} 的 last_triggered_at")

                        # 计算今天应该触发的时间点 (用于比较)
                        trigger_hm_dt = datetime.strptime(reminder["time_str"], "%H:%M").time()
                        today_trigger_dt = now.replace(hour=trigger_hm_dt.hour, minute=trigger_hm_dt.minute, second=0, microsecond=0)

                        # 如果今天是设定的星期几，时间已到，且今天还未触发过
                        if last_triggered_dt is None or last_triggered_dt < today_trigger_dt:
                            self._send_reminder(reminder["wxid"], reminder["content"], reminder["id"], reminder["roomid"])
                            reminders_to_update.append(reminder["id"]) # 每周提醒也需要更新触发时间
                            logger.info(f"每周提醒 {reminder['id']} (周{current_weekday+1}) 已触发并标记更新触发时间。")

                    # 4. 在事务中执行删除和更新
                    if reminders_to_delete:
                        # 使用 executemany 提高效率
                        sql_delete = "DELETE FROM reminders WHERE id = ?"
                        cursor.executemany(sql_delete, [(rid,) for rid in reminders_to_delete])
                        logger.info(f"从数据库删除了 {len(reminders_to_delete)} 条一次性提醒。")

                    if reminders_to_update:
                        sql_update = "UPDATE reminders SET last_triggered_at = ? WHERE id = ?"
                        cursor.executemany(sql_update, [(now_iso, rid) for rid in reminders_to_update])
                        logger.info(f"更新了 {len(reminders_to_update)} 条提醒的最后触发时间。")

                    # 提交事务
                    if reminders_to_delete or reminders_to_update:
                        conn.commit()

        except sqlite3.Error as e:
            logger.error(f"检查并触发提醒时数据库出错: {e}", exc_info=True)
        except Exception as e: # 捕获其他潜在错误
            logger.error(f"检查并触发提醒时发生意外错误: {e}", exc_info=True)


    def _send_reminder(self, wxid: str, content: str, reminder_id: str, roomid: Optional[str] = None):
        """
        安全地发送提醒消息。
        根据roomid是否存在决定发送方式：
        - 如果roomid存在，则发送到群聊并@用户
        - 如果roomid不存在，则发送私聊消息
        """
        try:
            message = f"⏰ 提醒：{content}"
            
            if roomid:
                # 群聊提醒: 发送到群聊并@设置提醒的用户
                self.robot.sendTextMsg(message, roomid, wxid)
                logger.info(f"已尝试发送群聊提醒 {reminder_id} 到群 {roomid} @ 用户 {wxid}")
            else:
                # 私聊提醒: 直接发送给用户
                self.robot.sendTextMsg(message, wxid)
                logger.info(f"已尝试发送私聊提醒 {reminder_id} 给用户 {wxid}")
        except Exception as e:
            target = f"群 {roomid} @ 用户 {wxid}" if roomid else f"用户 {wxid}"
            logger.error(f"发送提醒 {reminder_id} 给 {target} 失败: {e}", exc_info=True)

    # --- 查看和删除提醒功能 ---
    def list_reminders(self, wxid: str) -> list:
        """列出用户的所有提醒（包括私聊和群聊中设置的），按类型和时间排序"""
        reminders = []
        try:
            with self._db_lock:
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()
                    # 按类型(once->daily->weekly)，再按时间排序
                    sql = """
                    SELECT id, type, time_str, content, created_at, last_triggered_at, weekday, roomid
                    FROM reminders
                    WHERE wxid = ?
                    ORDER BY
                        CASE type
                            WHEN 'once' THEN 1
                            WHEN 'daily' THEN 2
                            WHEN 'weekly' THEN 3
                            ELSE 4 END ASC,
                        time_str ASC
                    """
                    cursor.execute(sql, (wxid,))
                    results = cursor.fetchall()
                    # 将 sqlite3.Row 对象转换为普通字典列表
                    reminders = [dict(row) for row in results]
            logger.info(f"为用户 {wxid} 查询到 {len(reminders)} 条提醒。")
            return reminders
        except sqlite3.Error as e:
            logger.error(f"为用户 {wxid} 列出提醒时数据库出错: {e}", exc_info=True)
            return [] # 出错返回空列表

    def delete_reminder(self, wxid: str, reminder_id: str) -> Tuple[bool, str]:
        """
        删除用户的特定提醒。
        用户可以删除自己的任何提醒，无论是在私聊还是群聊中设置的。
        :return: (是否成功, 消息)
        """
        try:
            with self._db_lock:
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()
                    # 确保用户只能删除自己的提醒
                    sql_check = "SELECT COUNT(*), roomid FROM reminders WHERE id = ? AND wxid = ? GROUP BY roomid"
                    cursor.execute(sql_check, (reminder_id, wxid))
                    result = cursor.fetchone()
                    
                    if not result or result[0] == 0:
                        logger.warning(f"用户 {wxid} 尝试删除不存在或不属于自己的提醒 {reminder_id}")
                        return False, f"未找到 ID 为 {reminder_id[:6]}... 的提醒，或该提醒不属于您。"
                    
                    # 获取roomid用于日志记录
                    roomid = result[1] if len(result) > 1 else None

                    sql_delete = "DELETE FROM reminders WHERE id = ? AND wxid = ?"
                    cursor.execute(sql_delete, (reminder_id, wxid))
                    conn.commit()
                    
                    # 在日志中记录位置信息
                    location_info = f"在群聊 {roomid}" if roomid else "在私聊"
                    logger.info(f"用户 {wxid} 成功删除了{location_info}设置的提醒 {reminder_id}")
                    return True, f"已成功删除提醒 (ID: {reminder_id[:6]}...)"

        except sqlite3.Error as e:
            logger.error(f"用户 {wxid} 删除提醒 {reminder_id} 时数据库出错: {e}", exc_info=True)
            return False, f"删除提醒时发生数据库错误: {e}"
        except Exception as e:
            logger.error(f"用户 {wxid} 删除提醒 {reminder_id} 时发生意外错误: {e}", exc_info=True)
            return False, f"删除提醒时发生未知错误: {e}"

    def delete_all_reminders(self, wxid: str) -> Tuple[bool, str, int]:
        """
        删除用户的所有提醒（包括群聊和私聊中设置的）。
        :param wxid: 用户的微信ID
        :return: (是否成功, 消息, 删除的提醒数量)
        """
        try:
            with self._db_lock:
                with self._get_db_conn() as conn:
                    cursor = conn.cursor()
                    
                    # 先查询用户有多少条提醒
                    count_sql = "SELECT COUNT(*) FROM reminders WHERE wxid = ?"
                    cursor.execute(count_sql, (wxid,))
                    count = cursor.fetchone()[0]
                    
                    if count == 0:
                        return False, "您当前没有任何提醒。", 0
                    
                    # 删除用户的所有提醒
                    delete_sql = "DELETE FROM reminders WHERE wxid = ?"
                    cursor.execute(delete_sql, (wxid,))
                    conn.commit()
                    
                    logger.info(f"用户 {wxid} 删除了其所有 {count} 条提醒")
                    return True, f"已成功删除您的所有提醒（共 {count} 条）。", count
                    
        except sqlite3.Error as e:
            logger.error(f"用户 {wxid} 删除所有提醒时数据库出错: {e}", exc_info=True)
            return False, f"删除提醒时发生数据库错误: {e}", 0
        except Exception as e:
            logger.error(f"用户 {wxid} 删除所有提醒时发生意外错误: {e}", exc_info=True)
            return False, f"删除提醒时发生未知错误: {e}", 0 
