"""
Function Call 参数模型定义
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class WeatherArgs(BaseModel):
    """天气查询参数"""
    city: str


class NewsArgs(BaseModel):
    """新闻查询参数 - 无需参数"""
    pass


class ReminderArgs(BaseModel):
    """设置提醒参数"""

    type: Literal["once", "daily", "weekly"] = Field(
        ..., description="提醒类型：once=一次性提醒，daily=每天，weekly=每周"
    )
    time: str = Field(
        ..., description="提醒时间。once 使用 'YYYY-MM-DD HH:MM'，daily/weekly 使用 'HH:MM'"
    )
    content: str = Field(..., description="提醒内容，将直接发送给用户")
    weekday: Optional[int] = Field(
        default=None,
        description="当 type=weekly 时的星期索引，0=周一 … 6=周日",
    )


class ReminderListArgs(BaseModel):
    """查看提醒列表参数 - 无需参数"""
    pass


class ReminderDeleteArgs(BaseModel):
    """删除提醒参数"""

    reminder_id: str = Field(..., description="提醒列表中的 ID（前端可展示前几位）")


class PerplexityArgs(BaseModel):
    """Perplexity搜索参数"""

    query: str = Field(..., description="要搜索的问题或主题")


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
