# Function Call 架构改进指南

## 1. 架构一致性如何提升？
- **现状诊断**
  - 业务逻辑已集中到 Function Call 体系，但闲聊兜底、服务层抽象仍需持续完善。
  - router 与服务层的职责边界要保持清晰：router 负责模型交互与参数校验，业务细节放在 `function_calls/services/`。
- **建议的架构骨架**
  1. **分层组织代码**：
     - `function_calls/spec.py`：仅保留数据结构。
     - `function_calls/registry.py`：集中注册所有函数。
     - `function_calls/router.py`：只负责入口路由、模型互操作和参数校验。
     - `function_calls/services/`（新增目录）：存放与业务相关的纯函数（例如天气、提醒、骂人等），对外只接受结构化参数。
     - `function_calls/handlers/`（可拆分模块）：每个 handler 只做 (ctx, args) → 调 service → 组装 FunctionResult。
  2. **统一入口**：`robot.py` 只初始化 `FunctionCallRouter`，其余旧路由移除，避免双写状态。
  3. **约束约定**：所有 handler 必须声明 `args` 的 Pydantic 模型；禁止 handler 内再次解析自然语言或修改 `ctx.msg.content`。
  4. **配置与日志**：为 `FunctionCallRouter` 添加统一的日志上下文（如 request_id），方便追踪函数调用链路。

## 2. 如何让 function 直接填参数、避免重复 LLM 解析？
- **目标**：路由阶段完成所有参数解析与校验，handler 全部消费结构化 `args`，不再依赖二次自然语言处理。
- **改造步骤**：
  1. **强制类型转换**：在 `_create_args_instance` 后无论 direct/LLM 均执行 `args_type.model_validate`，并捕获校验错误，向用户返回提示。
  2. **拆分提醒业务逻辑**：
     - 编写 `function_calls/services/reminder.py`，内含 `create_reminder(ctx, ReminderArgs)` 等函数，直接调用 `ctx.robot.reminder_manager`。
     - 调整 `ReminderArgs` 为真正的结构字段（例如 `schedule: ScheduleArgs`），由 FunctionCallRouter/LLM 负责生成 JSON。
     - 对 direct 命令的需求，若要保留，可做一个轻量的自然语言 → `ReminderArgs` 的解析器，独立成 util，避免回写 `ctx.msg.content`。
  3. **其他 handler 同理**：
     - `insult`：直接调用封装好的 `generate_random_insult(target_user)`，不要构造 fake match（见 `function_calls/handlers.py:216`）。
     - `perplexity_search`：把 `query` 直接传给 service，service 负责与 `ctx.robot.perplexity` 交互。
  4. **落地校验**：在 `function_calls/llm.py:123` 的决策结果里，若 schema 校验不通过，构建友好错误提示并返回 `FunctionResult`。
  5. **测试**：为每个 handler 编写参数驱动的单测，例如 `test_reminder_set_structured_args` → 传 `ReminderArgs(time_spec="2024-05-01 15:00", content="开会")`，验证生成的提醒记录。

## 3. 目前改造是否达标？还需修什么？
- **仍存在的问题**：
  - Handler 依赖旧命令逻辑（`function_calls/handlers.py:147`, `:189`, `:216`），说明“function 直接消费参数”的目标尚未实现。
  - 直接命令分支跳过 `validate_arguments`，导致 `ReminderArgs` 这类模型的必填字段不会被校验（`function_calls/router.py:118`）。
  - `FunctionResult.at_list` 虽已在 `_execute_function` 中 join，但数据类仍声明为 `list[str]`。如果后续有人直接调用 `ctx.send_text(message, result.at_list)` 将再次踩坑。建议统一改成 `str` 或封装发送逻辑。
  - 仍缺少针对新路由的自动化测试，仅有打印式脚本（`test_function_calls.py`）。建议补充 pytest 单测或集成测试。
- **建议修复顺序**：
  1. 清理 handler 对旧命令的依赖，迁移业务逻辑到 service 层。
  2. 在 router 中统一调用 `validate_arguments` → `_create_args_instance` → handler。
  3. 更新 `FunctionResult` 类型定义，提供 helper 方法如 `result.send_via(ctx)` 集中处理消息发送。
  4. 编写覆盖天气/新闻/提醒/骂人等核心流程的单测，确保 Function Call 路径稳定。

## 4. 只保留 Function Call，旧路由是否移除到位？
- **现状**：`robot.py:172-272` 仍初始化并调用 `CommandRouter`、`ai_router`，函数回退逻辑依旧存在。
- **移除建议**：
  1. 删除 `self.command_router = CommandRouter(...)` 及相关 import；同时移除 `CommandRouter.dispatch` 调用与辅助日志。
  2. 移除 `ai_router` 回退逻辑和配置项 `FUNCTION_CALL_ROUTER.fallback_to_legacy`。确保配置文件同步更新（`config.yaml.template:151`）。
  3. 将闲聊 fallback 改为：当 `FunctionCallRouter` 返回 `False` 时直接走 `run_chat_fallback`，并记录原因日志。
  4. 清理不再使用的命令注册表与正则代码（`commands/registry.py`、`commands/router.py` 等），确认没有别的模块引用后可删。
  5. 回归测试：运行原有功能用例，确保删除旧路由不会影响提醒、天气等功能；同时观察日志，确认不再出现“命令路由器”相关输出。

## 5. 推荐行动清单（按优先级）
1. **剥离 handler 对旧命令体系的依赖**：完成 service 层拆分，更新所有 handler 为结构化实现。
2. **统一参数校验与错误返回**：调整 router 逻辑，新增校验失败提示，并完善 `FunctionResult` 类型。
3. **移除旧路由与配置**：清理 `robot.py` 中的命令/AI 路由初始化与 fallback，更新配置模板。
4. **补全测试**：为 Function Call 核心流程编写 pytest 单元与集成测试，覆盖 direct/LLM 两条路径。
5. **整理文档**：更新开发文档，说明如何新增 function、如何编写参数模型与 service，确保团队成员按统一规范扩展功能。

执行完以上步骤后，你将拥有一套纯 Function Call、结构化且易维护的机器人指令体系，满足题述的四个目标。
