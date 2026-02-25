# agent/tools/__init__.py
from .base import Tool
from .registry import ToolRegistry
from .web_search import WebSearchTool
from .reminder import ReminderCreateTool, ReminderListTool, ReminderDeleteTool
from .chat_history import ChatHistoryTool

__all__ = [
    "Tool",
    "ToolRegistry",
    "WebSearchTool",
    "ReminderCreateTool",
    "ReminderListTool",
    "ReminderDeleteTool",
    "ChatHistoryTool",
]


def create_default_registry(tavily_api_key: str | None = None) -> ToolRegistry:
    """创建包含所有默认工具的注册表"""
    registry = ToolRegistry()
    registry.register(WebSearchTool(api_key=tavily_api_key))
    registry.register(ReminderCreateTool())
    registry.register(ReminderListTool())
    registry.register(ReminderDeleteTool())
    registry.register(ChatHistoryTool())
    return registry
