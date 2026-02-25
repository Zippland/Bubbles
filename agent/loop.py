# agent/loop.py
"""Agent Loop 核心"""

import logging
from typing import Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from providers.base import LLMProvider
    from agent.context import AgentContext
    from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentLoop:
    """Agent Loop - 实现工具调用循环"""

    def __init__(self, tools: "ToolRegistry", max_iterations: int = 20):
        self.tools = tools
        self.max_iterations = max_iterations

    async def run(
        self,
        provider: "LLMProvider",
        messages: list[dict],
        ctx: "AgentContext",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """运行 Agent Loop

        Args:
            provider: LLM Provider
            messages: 初始消息列表（会被修改）
            ctx: Agent 上下文
            on_progress: 进度回调（用于发送中间内容）

        Returns:
            最终响应文本，或 None 表示失败
        """
        iteration = 0
        tool_definitions = self.tools.get_definitions()

        while iteration < self.max_iterations:
            iteration += 1

            # 调用 LLM
            response = await provider.chat(messages, tool_definitions)

            if response.tool_calls:
                # 有工具调用
                if on_progress and response.content:
                    await on_progress(response.content)

                # 添加 assistant 消息
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [tc.to_dict() for tc in response.tool_calls],
                    }
                )

                # 执行所有工具
                for tc in response.tool_calls:
                    logger.info(f"执行工具: {tc.name}, 参数: {tc.arguments}")
                    result = await self.tools.execute(tc.name, ctx, tc.arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )

                continue

            # 没有工具调用，返回最终响应
            return response.content

        logger.warning(f"达到最大迭代次数 {self.max_iterations}")
        return "抱歉，处理过程中遇到了问题，请稍后再试。"
