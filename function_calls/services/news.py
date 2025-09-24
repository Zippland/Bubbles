"""News related service helpers for Function Call handlers."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from function.func_news import News


logger = logging.getLogger(__name__)


@dataclass
class NewsResult:
    success: bool
    message: str
    is_today: Optional[bool] = None


def get_news_digest() -> NewsResult:
    """Fetch latest news digest."""
    try:
        news_instance = News()
        is_today, content = news_instance.get_important_news()
        if is_today:
            message = f"📰 今日要闻来啦：\n{content}"
        else:
            if content:
                message = f"ℹ️ 今日新闻暂未发布，为您找到最近的一条新闻：\n{content}"
            else:
                message = "❌ 获取新闻失败，请稍后重试"
        return NewsResult(success=True, message=message, is_today=is_today)
    except Exception as exc:
        logger.error(f"获取新闻失败: {exc}")
        return NewsResult(success=False, message="❌ 获取新闻时发生错误")
