# agent/tools/web_search.py
"""网络搜索工具"""

import json
import re
from typing import Any, TYPE_CHECKING

from .base import Tool

if TYPE_CHECKING:
    from agent.context import AgentContext


class WebSearchTool(Tool):
    """网络搜索工具 - 使用 Perplexity 进行搜索"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "在网络上搜索信息。用于回答需要最新数据、实时信息或你不确定的事实性问题。"
            "deep_research 仅在问题非常复杂、需要深度研究时才开启。"
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
                "deep_research": {
                    "type": "boolean",
                    "description": "是否启用深度研究模式（耗时较长，仅用于复杂问题）",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    @property
    def status_text(self) -> str | None:
        return "正在联网搜索: "

    @property
    def status_arg(self) -> str | None:
        return "query"

    async def execute(
        self,
        ctx: "AgentContext",
        query: str = "",
        deep_research: bool = False,
        **_,
    ) -> str:
        perplexity_instance = getattr(ctx.robot, "perplexity", None)
        if not perplexity_instance:
            return json.dumps(
                {"error": "Perplexity 搜索功能不可用，未配置或未初始化"},
                ensure_ascii=False,
            )

        if not query:
            return json.dumps({"error": "请提供搜索关键词"}, ensure_ascii=False)

        try:
            # Perplexity.get_answer 是同步方法，需要在线程中运行
            import asyncio

            response = await asyncio.to_thread(
                perplexity_instance.get_answer,
                query,
                ctx.get_receiver(),
                deep_research,
            )

            if not response:
                return json.dumps({"error": "搜索无结果"}, ensure_ascii=False)

            # 清理 think 标签
            cleaned = re.sub(
                r"<think>.*?</think>", "", response, flags=re.DOTALL
            ).strip()
            return json.dumps(
                {"result": cleaned or response}, ensure_ascii=False
            )
        except Exception as e:
            return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)
