"""Static help text utility."""
from __future__ import annotations

HELP_LINES = [
    "🤖 泡泡的指令列表 🤖",
    "",
    "【实用工具】",
    "- 天气/温度 [城市名]",
    "- 天气预报/预报 [城市名]",
    "- 新闻",
    "- ask [问题]",
    "",
    "【提醒】",
    "- 提醒xxxxx：一次性、每日、每周",
    "- 查看提醒/我的提醒/提醒列表",
    "- 删..提醒..",
    "",
    "【群聊工具】",
    "- summary/总结",
    "- clearmessages/清除历史",
]


def build_help_text() -> str:
    """Return formatted help text."""
    return "\n".join(HELP_LINES)
