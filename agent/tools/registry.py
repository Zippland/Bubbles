# agent/tools/registry.py
"""工具注册表"""

import json
import logging
from typing import TYPE_CHECKING

from .base import Tool

if TYPE_CHECKING:
    from agent.context import AgentContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表 - 管理所有可用工具"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """获取工具"""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        """获取所有工具的 OpenAI 格式定义"""
        return [t.to_openai_schema() for t in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())

    async def execute(
        self, name: str, ctx: "AgentContext", params: dict
    ) -> str:
        """执行工具

        Args:
            name: 工具名称
            ctx: Agent 上下文
            params: 工具参数

        Returns:
            JSON 格式的执行结果
        """
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)

        # 发送状态提示
        if tool.status_text:
            status = tool.status_text
            arg_name = tool.status_arg
            if arg_name and arg_name in params:
                val = params[arg_name]
                if isinstance(val, list):
                    val = "、".join(str(k) for k in val[:3])
                status = f"{status}{val}"
            await ctx.send_status(status)

        try:
            result = await tool.execute(ctx, **params)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            return result
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
