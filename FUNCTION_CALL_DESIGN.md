# Function Call 架构说明

## 总览
新架构围绕 `function_calls/` 目录构建，所有业务能力都以 Function Call 的形式注册和执行：

- **FunctionSpec / FunctionResult** (`function_calls/spec.py`)：描述函数的元数据（名称、描述、JSON Schema 参数定义、作用域、是否要求 @ 等）以及标准化的执行结果。
- **Registry** (`function_calls/registry.py`)：集中注册函数，通过 `@tool_function(...)` 装饰器将 handler、参数模型、示例等元信息写入全局注册表，供路由器查询。
- **Handlers** (`function_calls/handlers.py`)：每个函数的入口，签名统一为 `(ctx: MessageContext, args: TypedModel) -> FunctionResult`，内部调用业务服务，返回结构化结果。
- **Services** (`function_calls/services/`)：纯业务逻辑层，如提醒、Perplexity、群总结、闲聊兜底等，避免 handler 直接处理外部依赖。
- **Router** (`function_calls/router.py`)：处理消息分发，负责：
  1. 准备函数注册表与执行器
  2. 调用 FunctionCallLLM 与模型交互
  3. 执行 handler 并发送结果
- **LLM 协调器** (`function_calls/llm.py`)：包装模型函数调用接口，负责 message 拼装、tool 调用循环、错误处理，确保 schema 传递给支持 function calling 的模型。

`robot.py` 中 `Robot.processMsg` 仅构造 `MessageContext`，传给 `FunctionCallRouter`；若函数调用链返回 `False`，则执行好友申请/欢迎词等特殊逻辑，并最终调用 `run_chat_fallback` 完成闲聊。

## 执行流程
1. **消息预处理**：`Robot.processMsg` 从 `WxMsg` 构建 `MessageContext`（`commands/context.py`），附带文本内容、群信息、引用图片、历史限制等。
2. **Function Call 分发**：
   - `FunctionCallRouter.dispatch` 检索注册函数（`list_functions()`）。
   - 调用 `FunctionCallLLM.run`，传入 `ctx`、注册表、执行器、tool formatter。
3. **LLM 协调**：
   - `_build_functions_for_openai` 将所有函数的 `parameters_schema`、描述、名称转成 OpenAI/DeepSeek 接口的 `functions` 列表。
   - `_run_native_loop` 调用模型的 `call_with_functions`，处理多轮函数调用：模型返回 `tool_calls` ⇒ executor 调 handler ⇒ formatter 将 `FunctionResult` 序列化后回传，直到模型给出最终回答或达到轮数上限。
   - 若模型不支持 `call_with_functions`，直接返回 `no_function_call_support` 错误。
4. **Handler 执行**：
   - 每个 handler 通过 `@tool_function` 注册，使用 Pydantic 参数模型（`function_calls/models.py`）进行 schema 校验。
   - 不同功能调用 `function_calls/services` 下的业务函数，如 `create_reminder`、`run_perplexity`、`summarize_messages`，最终返回 `FunctionResult`。
   - `FunctionResult.dispatch()` 可用于直接下发消息，或统一序列化给 LLM。
5. **兜底逻辑**：
   - Model 返回失败或无结果时，`Robot.processMsg` 会处理好友请求、欢迎新成员等特殊事件。
   - 仍未回应则调用 `run_chat_fallback(ctx)`：使用当前 chat 模型生成闲聊回复，可处理引用图片、XML 格式化历史等。

## 目录结构
```
function_calls/
├── __init__.py
├── handlers.py            # 统一注册的 Function handlers
├── init_handlers.py       # 导入 handlers 以触发注册
├── llm.py                 # 与模型进行函数调用循环
├── models.py              # Pydantic 参数模型
├── registry.py            # 全局函数注册表 + 装饰器
├── router.py              # 对外暴露的 Function Call 分发器
├── services/              # 业务逻辑模块
│   ├── __init__.py
│   ├── chat.py            # 闲聊兜底逻辑
│   ├── group_tools.py     # 群总结、清理缓存等
│   ├── perplexity.py      # Perplexity 服务封装
│   ├── reminder.py        # 提醒业务
│   └── ...
└── spec.py                # FunctionSpec / FunctionResult 定义
```

## 模型支持
当前架构仅支持原生函数调用接口的模型：
- `ai_providers/ai_chatgpt.py`
- `ai_providers/ai_deepseek.py`（新增 `call_with_functions`）

若模型不具备 `call_with_functions` 方法，`FunctionCallLLM.run` 会返回 `no_function_call_support`，提示配置支持函数调用的模型。已移除提示词 fallback 与 JSON 判决逻辑。

## 闲聊兜底
`function_calls/services/chat.py`：
- 优先使用 XML 解析器 (`ctx.robot.xml_processor`) 格式化消息。
- 若引用了图片且模型支持视觉能力，走 `get_image_description`。
- 否则构造 `[HH:MM] Sender: Content` 提示词，调用 chat 模型生成回复并发送。
- 缺少 chat 模型或生成失败时会给出基本提示。

## FunctionSpec 与参数 Schema
- `FunctionSpec.parameters_schema` 由 Pydantic 模型的 `model_json_schema()` 得到，封装为标准 JSON Schema。
- `_build_functions_for_openai` 会把 schema、函数名、描述传给模型的 `call_with_functions` 接口，使模型在生成函数调用参数时受 schema 约束。
- handler 通过 `_create_args_instance` 将 JSON 参数加载成 Pydantic 对象，若校验失败会记录日志并把错误信息返回给 LLM。

## 典型 handler 示例
```python
@tool_function(
    name="reminder_set",
    description="设置提醒",
    scope="both",
    require_at=True,
)
def handle_reminder_set(ctx: MessageContext, args: ReminderArgs) -> FunctionResult:
    manager = getattr(ctx.robot, "reminder_manager", None)
    at = ctx.msg.sender if ctx.is_group else ""
    if not manager:
        return FunctionResult(handled=True, messages=["❌ 内部错误：提醒管理器未初始化。"], at=at)

    service_result = create_reminder(
        manager=manager,
        sender_wxid=ctx.msg.sender,
        data=args.model_dump(),
        roomid=ctx.msg.roomid if ctx.is_group else None,
    )
    return FunctionResult(handled=True, messages=service_result.messages, at=at)
```

## 机器人主流程片段（`robot.py:172-236`）
1. 记录消息历史 → 选择模型 → 构建 `MessageContext`。
2. 调用 `FunctionCallRouter.dispatch(ctx)`，若 `handled` 为 `True` 直接返回。
3. 若未处理，处理好友请求/欢迎词等系统消息；否则执行 `run_chat_fallback(ctx)`。

## 健康检查脚本
`check_system.py` 被更新为校验：
- Function Call 核心模块导入
- handler 注册数量（5 个核心函数）
- `FunctionCallRouter` 初始化
- 配置模板包含 Function Call 配置

## 保留的 legacy 内容
`commands` 目录仅保留 `context.py`（消息上下文定义）和简化后的 `__init__.py`。其余旧路由、正则 handler 已移除，防止双体系并存。

---
该文档覆盖了当前 Function Call 架构的主要模块、数据流、模型依赖以及兜底策略，供后续扩展与维护参考。
