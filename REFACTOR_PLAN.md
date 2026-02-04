# Bubbles 改造计划

## 核心问题

Bubbles 是个单次意图分类器，不是 Agent。AI Router 做一次 `chat/function` 分类就结束了，无法多步推理、自主决策。这是"死板"的根源。

---

## 一、Agent 循环（最高优先级）

把 `processMsg` 的单次分类改成工具调用循环。AI 自己决定调什么工具、调几次、什么时候停。

**改动范围：** `robot.py` 的消息处理主流程，`commands/ai_router.py` 的路由逻辑

**目标状态：**

```
消息进入 → Agent 循环开始
  → LLM 返回工具调用 → 执行工具 → 结果喂回 LLM → 继续推理
  → LLM 返回纯文本 → 循环结束，发送回复
  → 达到最大步数 → 强制结束
```

**必须包含的防护：**
- 最大步数限制（防无限循环）
- 死循环检测：同一工具连续 3 次相同输入时中断
- 单步超时

---

## 二、工具标准化

定义统一的 Tool 接口，把现有功能改写成标准工具，让 Agent 循环能调用。

**改动范围：** 新建 `tools/` 目录，重构 `commands/ai_functions.py`、`commands/reminder_router.py`

**Tool 接口定义：**

```python
class Tool:
    name: str                  # 工具唯一标识
    description: str           # 给 LLM 看的功能描述
    parameters: dict           # JSON Schema 参数定义

    async def execute(self, params: dict, ctx: MessageContext) -> str:
        """执行工具，返回文本结果"""
```

**需要改写的现有功能：**
- `reminder_hub` → `reminder_create` / `reminder_list` / `reminder_delete`（拆开，消灭二级路由）
- `perplexity_search` → `web_search`
- `handle_chitchat` 不再是工具，而是 Agent 循环的默认文本输出路径

**工具描述走 LLM 原生的 function calling / tool_use 协议**，不再拼进提示词字符串。

---

## 三、模型 Fallback

当前模型挂了就挂了。必须加 fallback 链。

**改动范围：** `robot.py` 的模型调用层，各 `ai_providers/` 适配器

**目标状态：**

```yaml
# config.yaml
models:
  default:
    primary: deepseek
    fallbacks: [chatgpt, kimi]
```

**必须实现：**
- 区分可重试错误（429 限流、超时、服务端 500）和不可重试错误（401 密钥无效）
- 可重试错误：指数退避重试（初始 2s，最大 30s）
- 不可重试或重试耗尽：切下一个 fallback 模型
- 记录失败模型的冷却时间，短期内不再尝试

---

## 四、上下文压缩

当前 `max_history` 按条数硬截断，丢失早期重要信息。

**改动范围：** `robot.py` 的历史消息获取逻辑，`commands/handlers.py` 的对话构建

**目标状态：**
- 监控当前对话的 token 总量
- 接近模型上下文窗口上限时，对早期消息做摘要压缩
- 保留最近 N 轮完整对话 + 早期对话的 LLM 生成摘要
- 替代现在的简单条数截断

---

## 执行状态

```
一、工具标准化  ✅ 已完成 — tools/__init__.py, tools/reminder.py, tools/web_search.py, tools/history.py
二、Agent 循环  ✅ 已完成 — 移除 AI Router，LLM 直接通过 _execute_with_tools 自主调用工具
三、模型 Fallback  ✅ 已完成 — _handle_chitchat 级联候选模型，ai_providers/fallback.py 重试/冷却
四、上下文压缩  ✅ 已完成 — func_summary.get_compressed_context()，字符预算代替固定条数截断
```
