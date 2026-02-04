"""
模型 Fallback 机制 —— 主模型失败时自动切到备选模型。

参考 OpenClaw 的 model-fallback.ts 设计：
  - 区分可重试错误（限流、超时、服务端 500）和不可重试错误（密钥无效）
  - 可重试：指数退避重试
  - 不可重试或重试耗尽：切下一个 fallback 模型
  - 记录失败模型的冷却时间
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 冷却时间（秒）：模型失败后暂时不再尝试
_MODEL_COOLDOWN: Dict[int, float] = {}  # model_id -> 冷却结束时间戳
COOLDOWN_DURATION = 60  # 60秒冷却

# 重试参数
RETRY_INITIAL_DELAY = 2.0
RETRY_BACKOFF_FACTOR = 2.0
RETRY_MAX_DELAY = 30.0
MAX_RETRIES_PER_MODEL = 2


def _is_retryable(error: Exception) -> bool:
    """判断错误是否可重试。"""
    error_str = str(error).lower()
    error_type = type(error).__name__

    # 限流
    if "rate" in error_str and "limit" in error_str:
        return True
    if "429" in error_str:
        return True
    # 超时
    if "timeout" in error_str or "timed out" in error_str:
        return True
    # 服务端错误
    if "500" in error_str or "502" in error_str or "503" in error_str:
        return True
    if "server" in error_str and "error" in error_str:
        return True
    # 连接错误
    if "connection" in error_str:
        return True
    # OpenAI 特定
    if error_type in ("APIConnectionError", "APITimeoutError", "InternalServerError"):
        return True

    return False


def _is_in_cooldown(model_id: int) -> bool:
    """检查模型是否在冷却中。"""
    deadline = _MODEL_COOLDOWN.get(model_id)
    if deadline is None:
        return False
    if time.time() < deadline:
        return True
    # 冷却结束，清除
    _MODEL_COOLDOWN.pop(model_id, None)
    return False


def _set_cooldown(model_id: int) -> None:
    """将模型加入冷却。"""
    _MODEL_COOLDOWN[model_id] = time.time() + COOLDOWN_DURATION
    logger.info(f"模型 {model_id} 进入冷却（{COOLDOWN_DURATION}秒）")


def call_with_fallback(
    primary_model_id: int,
    chat_models: Dict[int, Any],
    fallback_ids: List[int],
    call_fn: Callable[[Any], str],
) -> Tuple[str, int]:
    """
    带 Fallback 的模型调用。

    :param primary_model_id: 主模型 ID
    :param chat_models: 所有可用模型 {id: instance}
    :param fallback_ids: 按优先级排序的 fallback 模型 ID 列表
    :param call_fn: 实际调用函数，接收模型实例，返回回复文本
    :return: (回复文本, 实际使用的模型ID)
    """
    # 构建候选列表：主模型 + fallbacks，跳过冷却中的
    candidates = []
    for mid in [primary_model_id] + fallback_ids:
        if mid not in chat_models:
            continue
        if mid in [c[0] for c in candidates]:
            continue  # 去重
        if _is_in_cooldown(mid):
            logger.info(f"模型 {mid} 处于冷却中，跳过")
            continue
        candidates.append((mid, chat_models[mid]))

    if not candidates:
        # 所有模型都在冷却，强制使用主模型
        if primary_model_id in chat_models:
            candidates = [(primary_model_id, chat_models[primary_model_id])]
        else:
            return "所有模型暂时不可用，请稍后再试。", primary_model_id

    last_error = None
    for model_id, model_instance in candidates:
        # 对每个候选模型，尝试最多 MAX_RETRIES_PER_MODEL 次
        for attempt in range(MAX_RETRIES_PER_MODEL + 1):
            try:
                result = call_fn(model_instance)
                if result:
                    return result, model_id
                # 空结果视为失败，但不重试
                break
            except Exception as e:
                last_error = e
                model_name = getattr(model_instance, '__class__', type(model_instance)).__name__
                logger.warning(
                    f"模型 {model_name}(ID:{model_id}) 第 {attempt + 1} 次调用失败: {e}"
                )

                if not _is_retryable(e):
                    logger.info(f"不可重试错误，跳过模型 {model_id}")
                    _set_cooldown(model_id)
                    break

                if attempt < MAX_RETRIES_PER_MODEL:
                    delay = min(
                        RETRY_INITIAL_DELAY * (RETRY_BACKOFF_FACTOR ** attempt),
                        RETRY_MAX_DELAY,
                    )
                    logger.info(f"等待 {delay:.1f}s 后重试...")
                    time.sleep(delay)
                else:
                    _set_cooldown(model_id)

    # 所有候选都失败了
    error_msg = f"模型调用失败: {last_error}" if last_error else "无法获取回复"
    logger.error(error_msg)
    return f"抱歉，服务暂时不可用，请稍后再试。", primary_model_id
