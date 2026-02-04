"""网络搜索工具 —— 通过 Perplexity 联网搜索。

直接调用 perplexity.get_answer() 获取同步结果，
结果回传给 LLM 做综合回答，而非直接发送给用户。
"""

import json
import re

from tools import Tool, tool_registry


def _handle_web_search(ctx, query: str = "", deep_research: bool = False, **_) -> str:
    if not query:
        return json.dumps({"error": "请提供搜索关键词"}, ensure_ascii=False)

    perplexity_instance = getattr(ctx.robot, "perplexity", None)
    if not perplexity_instance:
        return json.dumps({"error": "Perplexity 搜索功能不可用，未配置或未初始化"}, ensure_ascii=False)

    try:
        chat_id = ctx.get_receiver()
        response = perplexity_instance.get_answer(query, chat_id, deep_research=deep_research)

        if not response:
            return json.dumps({"error": "搜索无结果"}, ensure_ascii=False)

        # 清理 <think> 标签（reasoning 模型可能返回）
        cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        if not cleaned:
            cleaned = response

        return json.dumps({"result": cleaned}, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)


tool_registry.register(Tool(
    name="web_search",
    description=(
        "在网络上搜索信息。用于回答需要最新数据、实时信息或你不确定的事实性问题。"
        "deep_research 仅在问题非常复杂、需要深度研究时才开启。"
    ),
    parameters={
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
    },
    handler=_handle_web_search,
))
