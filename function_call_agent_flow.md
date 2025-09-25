# Function Call Agent 消息流程

## 概览
- 所有传入的微信消息都会先由机器人入口处理，并在路由前写入消息记录（`robot.py:190-274`）。
- 使用装饰器注册的函数处理器在运行时组成结构化的注册表，供路由器查询（`function_calls/init_handlers.py:1-9`, `function_calls/handlers.py:37-180`）。
- 路由器优先采用确定性的命令解析，只有在必要时才升级到 LLM 编排循环（`function_calls/router.py:81-200`）。
- LLM 协调器同时支持原生函数调用模型和基于提示词的回退模式，统一返回 `LLMRunResult`（`function_calls/llm.py:33-186`）。
- 结构化处理器返回 `FunctionResult`，路由器可以直接发送回复或将 JSON 结果反馈给 LLM（`function_calls/spec.py:12-36`）。

## 流程图
```mermaid
flowchart TD
    A[来自 Wcf 的 WxMsg] --> B[Robot.processMsg]
    B --> C[MessageSummary 记录消息]
    B --> D[_select_model_for_message]
    B --> E[_get_specific_history_limit]
    B --> F[preprocess → MessageContext]
    F --> G{FunctionCallRouter.dispatch}
    G -->|直接匹配| H[_check_scope & require_at]
    H --> I[_extract_arguments]
    I --> J[_invoke_function]
    J --> K{FunctionResult.handled?}
    K -->|是| L[FunctionResult.dispatch → ctx.send_text]
    K -->|否| M[升级到 LLM]
    G -->|无直接匹配| M
    M --> N[FunctionCallLLM.run]
    N --> O{模型是否支持 call_with_functions?}
    O -->|是| P[原生工具循环]
    P --> Q[调用 call_with_functions]
    Q --> R{是否返回 tool call?}
    R -->|是| S[_invoke_function → FunctionResult]
    S --> T[formatter → 追加工具 JSON]
    T --> P
    R -->|否| U[模型最终回答]
    U --> V[ctx.send_text 最终回复]
    P --> W[达到最大轮次]
    W --> X[handled = False]
    O -->|否| Y[提示词回退]
    Y --> Z[get_answer + 解析 JSON]
    Z --> AA{action_type == "function"?}
    AA -->|是| S
    AA -->|否| X
    X --> AB[路由返回 False]
    AB --> AC[回退：闲聊/帮助路径]
```

## 分步说明
### 1. 消息接入（`robot.py:190-274`）
- 每条消息都会通过 `MessageSummary.process_message_from_wxmsg` 持久化，方便后续上下文检索。
- 机器人依据群聊/私聊映射与历史限制选择 AI 模型，再构建包含发送者信息与清洗文本的 `MessageContext`。
- 在进入路由前，Context 会注入当前 `chat` 模型及会话级的历史上限。

### 2. 函数注册（`function_calls/init_handlers.py:1-9`）
- 机器人启动时导入 `function_calls.init_handlers`，所有 `@tool_function` 装饰器即被执行。
- 每个处理器声明名称、描述、JSON Schema、作用域以及是否需要 @，注册表因此具备自描述能力。

### 3. 直接命令快路（`function_calls/router.py:81-175`）
- 路由器先对 `ctx.text` 归一化，再走 `_try_direct_command_match` 匹配已知关键词。
- 作用域、@ 以及（待实现的）权限检查会阻止不符合条件的调用。参数会按 JSON Schema 校验，避免脏数据。
- 命中后处理器立即执行，`FunctionResult.dispatch` 会直接向聊天对象推送，无需经过模型。

### 4. LLM 编排（`function_calls/llm.py:33-186`）
- 若无直接命中，`FunctionCallLLM.run` 会判断当前模型是否支持 OpenAI 风格的工具调用。
- **原生循环**：协调器不断发送最新对话，执行指定工具，并把结构化 JSON 响应回灌给模型，直到拿到最终回复或达到轮次上限。
- **提示词回退**：不支持原生工具的模型会收到列出所有函数的 system prompt，必须返回 JSON 决策供路由器执行。
- 两种路径最终都返回 `LLMRunResult`，路由器据此决定是否直接回复或继续走其他兜底逻辑。

### 5. 处理器执行（`function_calls/handlers.py:37-180`）
- 处理器依赖 `function_calls/services` 中的业务封装，统一返回 `FunctionResult`。
- 群聊场景会在 `at` 字段写入 `ctx.msg.sender`，确保回复时点名原始请求者。

### 6. 兜底逻辑（`robot.py:229-273`）
- 当路由返回未处理状态时，机器人会回退到旧流程：自动通过好友请求、发送欢迎消息或调用 `handle_chitchat`。
- 即使 Function Call 路由失败，整体对话体验依旧有保障。

## 优势
- 对已知命令走直连路径，既避免额外的模型耗时，又能通过 JSON Schema 保证参数质量（`function_calls/router.py:103-175`）。
- LLM 协调器清晰区分原生工具与提示词回退，后续替换模型时无需大改（`function_calls/llm.py:33-186`）。
- `FunctionResult` 既可直接回复，也能作为工具输出反馈给模型，减少重复实现（`function_calls/spec.py:12-36`）。

## 仍需关注的点
- 进入 LLM 流程后，工具输出依赖模型二次组织文本；关键函数可考虑直接派发 `FunctionResult`，避免模型返回空字符串时用户无感知（`function_calls/llm.py:83-136`）。
- 天气命令的直接路径默认关键词与城市之间存在空格；若要支持“天气北京”这类写法，需要放宽解析逻辑（`function_calls/router.py:148-156`）。
- 权限检查字段（`spec.auth`）仍是占位符，新增高权限工具前需补齐校验实现（`function_calls/router.py:35-38`）。

---
为快速理解全新的 Function Call Agent 流程而生成。
