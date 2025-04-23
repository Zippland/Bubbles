from enum import IntEnum, unique


@unique
class ChatType(IntEnum):
    # UnKnown = 0  # 未知, 即未设置
    CHATGPT = 1  # ChatGPT
    DEEPSEEK = 2  # DeepSeek
    PERPLEXITY = 3  # Perplexity

    @staticmethod
    def is_in_chat_types(chat_type: int) -> bool:
        if chat_type in [ChatType.CHATGPT.value,
                        ChatType.DEEPSEEK.value,
                         ChatType.PERPLEXITY.value]:
            return True
        return False

    @staticmethod
    def help_hint() -> str:
        return str({member.value: member.name for member in ChatType}).replace('{', '').replace('}', '')
