# 从正则/路由体系迁移到标准 Function Call 的实施手册

## 1. 改造目标与约束
- 完全淘汰 `commands` 目录下的正则匹配路由 (`CommandRouter`) 与 `commands/ai_router.py` 中的自定义决策逻辑，统一改为标准化的 Function Call 协议。
- 让所有机器人工具能力都以“结构化函数定义 + 参数 JSON schema”的形式暴露，既能让 LLM 函数调用，也能被程序直接调用。
- 保持现有业务能力完整可用（天气、新闻、提醒、Perplexity 搜索、群管理等），迁移过程中不影响线上稳定性。
- 兼容现有上下文对象 `MessageContext`，并保留与微信客户端交互所需的最小耦合。

## 2. 现有架构梳理
### 2.1 指令流
1. `robot.py` 中 `Robot.processMsg` 获取消息后构造 `MessageContext`，先交给 `CommandRouter.dispatch`（见 `commands/router.py:13`）。
2. `CommandRouter` 遍历 `COMMANDS` 列表（`commands/registry.py:15` 起），用正则匹配执行对应 handler，例如 `handle_reminder`（`commands/handlers.py`）。
3. Handler 内部通常继续调用 `function/` 下的模块完成业务。

### 2.2 AI 路由流
1. `commands/ai_router.py` 提供 `AIRouter`，通过 `_build_ai_prompt` 把功能描述写进提示词。
2. `route` 调用聊天模型的 `get_answer`，要求模型返回 `{"action_type": "function", ...}` 格式的 JSON，再根据返回字符串里的 params 调 handler。
3. 该流程依旧依赖字符串解析和弱结构的参数传递（例如 `params` 直接拼在 handler 里处理）。

### 2.3 问题痛点
- 功能元数据散落：正则、示例、参数说明分布在多个文件，新增能力需要多处编辑。
- 参数结构模糊：当前 `params` 仅是字符串，handler 内自行拆分，容易出错。
- 与 LLM 的交互不标准：靠提示词提醒模型返回 JSON，缺乏 schema 约束，易产生格式错误。
- 双路由并存：命令路由与 AI 路由行为不一致，重复注册、维护成本高。

## 3. 目标架构设想
```
WxMsg -> MessageContext -> FunctionCallRouter
                               |-- Registry (FunctionSpec, schema, handler)
                               |-- FunctionCallLLM (统一 function call API)
                               '-- Local invoker / fallback (无 LLM)
```
- **FunctionSpec**：定义函数名、描述、参数 JSON schema、返回结构、权限等元数据。
- **FunctionCallRouter**：单一入口，负责：
  1. 根据上下文（是否命令关键字、是否@）决定是否直接调用或交给 LLM 选函数。
  2. 如果由 LLM 决定，则调用支持 function call 的接口（OpenAI / DeepSeek / 自建），拿到带函数名与参数 JSON 的结构化响应。
  3. 校验参数，调用真实 handler，统一处理返回。
- **Handlers**：全部改造成签名规范的函数（例如接收 `ctx: MessageContext, args: TypedModel`），禁止在 handler 内再解析自然语言。

## 4. 迁移阶段概览
| 阶段 | 目标 | 关键输出 | 风险控制 |
| ---- | ---- | -------- | -------- |
| P0 现状盘点 | 梳理所有功能与依赖 | 功能清单、调用图、可迁移性评估 | 标注遗留 / 暂缓功能 |
| P1 构建 Function Spec | 落地函数描述模型与注册中心 | `function_calls/spec.py`、`registry.py` | 先只收录已实现能力 |
| P2 新路由内核 | 新的 `FunctionCallRouter` 与 LLM 适配层 | `function_calls/router.py`、`llm.py` | 与老路由并行跑灰度 |
| P3 Handler 适配 | 将现有 handler 改为结构化参数 | 类型化参数模型、转换器 | 保留回退入口、渐进式替换 |
| P4 切换与清理 | 替换 `Robot.processMsg` 流程，删除旧代码 | 配置开关、文档 | 全量回归测试 |

## 5. 各阶段详细操作
### 阶段 P0：能力盘点 & 前置准备
1. **提取功能列表**：
   - 从 `commands/registry.py` 抽出每个 `Command` 的 `name/description/pattern`。
   - 从 `commands/ai_functions.py` 抽出 `@ai_router.register` 的功能信息。
2. **梳理依赖**：确认每个 handler 调用的模块，如 `function/func_weather.py`、数据库访问、外部 API。
3. **分类能力**：区分“纯文本问答”、“需要结构化参数的工具调用”、“需要调度/持久化的事务型能力”。
4. **定义统一字段**：初步罗列每个功能需要的字段（例如天气需要 `city`，提醒需要 `time_spec` + `content`）。
5. **技术选型**：确定使用的 function call 接口：
   - 若沿用 OpenAI/DeepSeek/gpt-4o 等需确认其 function call JSON schema 支持。
   - 若需自定义，可在 `ai_providers` 中新增 `call_with_functions` 方法。

### 阶段 P1：定义 FunctionSpec 与注册中心
1. **创建模块结构**：建议新增 `function_calls/` 目录，包含：
   - `spec.py`：定义核心数据结构。
   - `registry.py`：集中注册所有函数。
   - `llm.py`：统一封装 LLM 函数调用接口。
2. **定义数据结构**（示例）：
   ```python
   # function_calls/spec.py
   from dataclasses import dataclass
   from typing import Callable, Any, Dict

   @dataclass
   class FunctionSpec:
       name: str
       description: str
       parameters_schema: Dict[str, Any]
       handler: Callable[[MessageContext, Dict[str, Any]], bool]
       examples: list[str] = None
       scope: str = "both"  # group / private / both
       require_at: bool = False
       auth: str | None = None  # 权限标签（可选）
   ```
3. **写注册器**：用装饰器或显式方法统一注册：
   ```python
   # function_calls/registry.py
   FUNCTION_REGISTRY: dict[str, FunctionSpec] = {}

   def register_function(spec: FunctionSpec) -> None:
       if spec.name in FUNCTION_REGISTRY:
           raise ValueError(f"duplicate function: {spec.name}")
       FUNCTION_REGISTRY[spec.name] = spec
   ```
4. **构建 JSON schema**：
   - 使用标准 Draft-07 schema，字段包括 `type`, `properties`, `required`。
   - 设计工具函数，将 Pydantic/自定义 dataclass 自动转 schema（便于 handler 书写类型定义）。
5. **迁移功能描述**：P0 中梳理的功能，逐一写成 `FunctionSpec`，暂时把 handler 指向旧 handler 的包装函数（下一阶段重写）。

### 阶段 P2：实现 FunctionCallRouter 与 LLM 适配
1. **Router 结构**：
   - 在 `function_calls/router.py` 新建 `FunctionCallRouter`，替代旧 `CommandRouter` 和 `AIRouter`。
   - 公开 `dispatch(ctx: MessageContext) -> bool` 接口，供 `Robot.processMsg` 调用。
2. **决策流程**：
   - 如果消息符合“显式命令”格式，可以在本地直接确定函数（例如以 `/` 开头、或命中关键字表），避免调用 LLM。
   - 否则调用 LLM 函数选择：统一走 `FunctionCallLLM.select_function(ctx, registry)`。
3. **LLM 适配**：
   - 在 `llm.py` 内封装：
     1. 将 `FunctionSpec` 列表转换成 OpenAI 函数调用所需的 `functions` 参数（包含 `name`, `description`, `parameters` schema）。
     2. 调用具体模型（例如 `chat_model.call_with_functions(...)`）。如当前模型类没有，需在 `ai_providers` 对应文件内加包装。
   - 处理返回：
     ```python
     response = chat_model.call_with_functions([...])
     function_name = response.choices[0].message.tool_calls[0].function.name
     arguments = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
     ```
   - 若模型不支持函数调用，退化到 prompt + JSON parsing，但要封装在适配层可替换。
4. **参数校验**：
   - 在 router 中对 `arguments` 做 schema 验证（使用 `jsonschema` / `pydantic`）。失败时给出可读错误并返回聊天 fallback。
5. **并行运行策略**：
   - 在 `Robot` 里保留旧路由开关，例如 `ENABLE_FUNCTION_ROUTER`。
   - 灰度期间可先调用新 router，如失败再回退旧 `CommandRouter.dispatch`。
6. **日志与追踪**：统一记录：选择的函数、输入参数、执行耗时、是否成功，方便对比新旧行为。

### 阶段 P3：Handler 结构化改造
1. **参数模型化**：为每个功能定义数据模型（使用 `pydantic.BaseModel` 或 dataclass）：
   ```python
   class WeatherArgs(BaseModel):
       city: str
   ```
2. **重写 handler 签名**：
   - 新 handler 统一为 `def handle(ctx: MessageContext, args: WeatherArgs) -> FunctionResult`。
   - `FunctionResult` 可包含 `handled: bool`, `reply: str | None`, `attachments: list[...]` 等，便于拓展。
3. **包装旧逻辑**：将 `commands/handlers.py` 中的旧函数迁到新目录或拆分：
   - 对于仍然有效的业务代码，提取核心逻辑到 `services/` 或 `function/` 保留位置，减少重复。
   - Handler 仅负责：记录日志 → 调用 service → 发送回复 → 返回结果。
4. **删除自然语言解析**：所有参数应由 LLM 生成的 JSON 直接提供，handler 不再解析中文描述。
5. **权限 & 场景**：在 `FunctionSpec` 中配置 `scope`/`require_at` 等字段，在 router 层校验，handler 内不再判断。

### 阶段 P4：切换入口与清理遗留
1. **替换 `Robot.processMsg` 流程**：
   - 将调用链切换为 `FunctionCallRouter.dispatch(ctx)`。
   - 如果返回 `False` 且 `ctx.chat` 存在，则调用默认聊天模型兜底（原 `handle_chitchat`）。
2. **移除旧模块**：
   - 删除 `commands/router.py`、`commands/models.py`、`commands/registry.py`、`commands/ai_router.py`、`commands/ai_functions.py`。
   - 将保留的业务 handler 根据需要移动到 `function_calls/handlers/` 或 `services/`。
3. **配置与文档更新**：同步更新 `README.MD`、配置项示例，说明如何新增函数、如何控制启用状态。

## 6. 关键实现细节建议
### 6.1 函数清单与元数据
- 建议维护清单表格（CSV/Notion/markdown），列出：函数名、描述、输入字段、输出、依赖模块、是否对群开放、是否需要异步调度。
- 对提醒类功能，注明需要访问数据库（`function/func_reminder.py`），关注事务边界。

### 6.2 Schema 构建工具链
- 提供装饰器，自动从参数模型生成 `FunctionSpec`：
  ```python
  def tool_function(name: str, description: str, examples: list[str] = None, **meta):
      def wrapper(func):
          schema = build_schema_from_model(func.__annotations__['args'])
          register_function(FunctionSpec(
              name=name,
              description=description,
              parameters_schema=schema,
              handler=func,
              examples=examples or [],
              **meta,
          ))
          return func
      return wrapper
  ```
- `build_schema_from_model` 可以基于 `pydantic` 的 `model_json_schema()` 实现。

### 6.3 FunctionResult 规范
- 统一约定 handler 返回内容：
  ```python
  class FunctionResult(BaseModel):
      handled: bool
      messages: list[str] = []
      at_list: list[str] = []
      metadata: dict[str, Any] = {}
  ```
- Router 根据返回决定是否向微信发送消息、是否继续 fallback。

### 6.4 兼容旧入参场景
- 对于仍由系统内部触发（非用户输入）的调用（例如定时提醒触发），也复用新的 handler，确保所有入口一致。
- 若暂时无法结构化，可定义 `raw_text: str` 字段，作为临时措施；在后续迭代中逐步替换。

### 6.5 日志与观测
- 在 router 层记录：
  - LLM 请求/响应 ID、耗时。
  - 选中的函数名、参数、handler 执行耗时。
  - 异常统一捕获并落盘。
- 可在 `logs/` 目录新建 function-call 专属日志，方便分析差异。

## 7. Prompt 与 LLM 策略
1. **系统提示词**：基于 `FunctionSpec` 自动生成。如目标模型支持原生 function call，可省略大量提示词，改用 `functions` 参数。
2. **多轮策略**：对不确定的响应，可以：
   - 若模型返回 `none` 或 `insufficient_arguments`，让 router 回退到聊天或引导用户补全。
   - 对重要函数设置 `confirmation_prompt`，在参数缺失时自动追问。
3. **上下文拼接**：继续使用 `MessageContext` 中的群聊消息、时间等信息，作为 LLM 输入的一部分。
4. **安全校验**：对高风险函数（如“骂人”类）可增加 LLM 分类或黑名单过滤。

## 8. 测试计划
### 8.1 单元测试
- 为每个 handler 编写结构化入参测试，确保直接调用函数即能得到正确输出。
- 为 schema 生成器写测试，保证 JSON schema 与模型字段同步。

### 8.2 集成测试
- 对 `FunctionCallRouter` 构建伪造的 `MessageContext`，模拟关键场景：天气、提醒、新闻等。
- Mock LLM 返回特定函数名和参数，验证 Router 行为正确。
- 针对权限/Scope/need_at 校验写覆盖测试。

### 8.3 回归测试
- 梳理历史日志，挑选典型输入，构建回归用例。
- 增加脚本：读取样本输入 → 调用 router（跳过真实 LLM，直接指定函数）→ 核对输出。

### 8.4 线上灰度验证
- 启用双写模式：新 router 实际处理，旧 router 记录判定结果但不执行，用于对比。
- 制作监控面板（成功率、异常率、响应时间）。

## 9. 发布与回滚策略
- 配置化开关（例如 `config.AI_ROUTER["enable_function_call"]`）。上线时默认灰度群聊，逐步扩大。
- 保留旧命令表与 handler 至至少一个版本周期，确认无回滚需求后再彻底移除。
- 出现问题时，关闭新开关，恢复 `CommandRouter` 行为，确保稳定。

## 10. 验收清单
- [ ] 所有功能均在 `FUNCTION_REGISTRY` 中有唯一条目。
- [ ] 每个函数的参数 schema 通过 `jsonschema.validate` 校验。
- [ ] Handler 不再包含自然语言解析逻辑。
- [ ] LLM 响应处理支持至少一种原生 function call 协议。
- [ ] 所有单测、集测通过，回归样本验证通过。
- [ ] 文档更新：新增功能如何注册、如何编写参数模型、如何调试。

---

> 按上述阶段实施，可在保持现有业务能力的前提下，将整个机器人指令体系迁移到统一的 Function Call 架构，实现更易维护、更稳定的工具调用体系。
