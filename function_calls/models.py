"""
Function Call 参数模型定义
"""
from typing import Literal, Optional

from pydantic import BaseModel


class WeatherArgs(BaseModel):
    """天气查询参数"""
    city: str


class NewsArgs(BaseModel):
    """新闻查询参数 - 无需参数"""
    pass


class ReminderArgs(BaseModel):
    """设置提醒参数"""

    type: Literal["once", "daily", "weekly"]
    time: str
    content: str
    weekday: Optional[int] = None


class ReminderListArgs(BaseModel):
    """查看提醒列表参数 - 无需参数"""
    pass


class ReminderDeleteArgs(BaseModel):
    """删除提醒参数"""

    reminder_id: str


class PerplexityArgs(BaseModel):
    """Perplexity搜索参数"""
    query: str


class HelpArgs(BaseModel):
    """帮助信息参数 - 无需参数"""
    pass


class SummaryArgs(BaseModel):
    """消息总结参数 - 无需参数"""
    pass


class ClearMessagesArgs(BaseModel):
    """清除消息参数 - 无需参数"""
    pass


class InsultArgs(BaseModel):
    """骂人功能参数"""
    target_user: str
