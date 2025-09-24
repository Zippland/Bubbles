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
    "【决斗 & 偷袭】",
    "- 决斗@XX",
    "- 偷袭@XX",
    "- 决斗排行/排行榜",
    "- 我的战绩/决斗战绩",
    "- 我的装备/查看装备",
    "- 改名 [旧名] [新名]",
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
