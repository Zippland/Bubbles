# agent/tools/web_search.py
"""网络搜索工具 - 使用 Tavily"""

import json
import os
from typing import Any, TYPE_CHECKING

from .base import Tool

if TYPE_CHECKING:
    from agent.context import AgentContext

# Tavily API
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    TavilyClient = None


class WebSearchTool(Tool):
    """网络搜索工具 - 使用 Tavily 搜索引擎"""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        self._client = None
        if TAVILY_AVAILABLE and self._api_key:
            self._client = TavilyClient(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "在网络上搜索最新信息。用于回答需要实时数据、新闻、或你不确定的事实性问题。"
            "返回多个搜索结果，包含标题、内容摘要和来源链接。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    @property
    def status_text(self) -> str | None:
        return "正在搜索: "

    @property
    def status_arg(self) -> str | None:
        return "query"

    async def execute(
        self,
        ctx: "AgentContext",
        query: str = "",
        **_,
    ) -> str:
        if not query:
            return json.dumps({"error": "请提供搜索关键词"}, ensure_ascii=False)

        if not TAVILY_AVAILABLE:
            return json.dumps(
                {"error": "Tavily 未安装，请运行: pip install tavily-python"},
                ensure_ascii=False,
            )

        if not self._client:
            return json.dumps(
                {"error": "Tavily API key 未配置，请在 config.yaml 中设置 tavily.key 或环境变量 TAVILY_API_KEY"},
                ensure_ascii=False,
            )

        try:
            import asyncio

            response = await asyncio.to_thread(
                self._client.search,
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=False,
            )

            results = response.get("results", [])
            if not results:
                return json.dumps({"error": "未找到相关结果"}, ensure_ascii=False)

            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "content": r.get("content", ""),
                    "url": r.get("url", ""),
                })

            return json.dumps({"results": formatted, "query": query}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)
