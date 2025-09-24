# Function Call 改造代码审核

## 阻塞问题（必须修复）
- **[已完成] FunctionResult 结果封装统一**  
  - 处理位置：`function_calls/spec.py:9`、`function_calls/router.py:195`、`commands/context.py:66`、`robot.py:296`  
  - 现状：结果模型已改为 `at: str` 并提供 `dispatch` 方法，路由器不再手动拼接 `@` 列表。`python3 -m compileall function_calls` 验证通过，群聊场景使用新的 `at` 字段。  

- **[已完成] 提醒功能使用结构化参数**  
  - 处理位置：`function_calls/models.py:19`、`function_calls/services/reminder.py:36`、`function_calls/handlers.py:70`、`function_calls/router.py:70`  
  - 将 `ReminderArgs` 改为 `type/time/content/weekday` 等字段，移除了对旧 `commands.handlers` 的依赖，并删除路由层对提醒的直接自然语言拼装。  

## 重要改进项
- **[已完成] Handler 逻辑脱离旧命令体系**  
  - 现状：所有 handler 均迁移到 `function_calls/services`（天气、新闻、提醒、Perplexity、骂人、群工具等），不再篡改 `ctx.msg.content` 或调用旧命令模块。 

- **[已完成] 直接命令路径参数校验**  
  - 现状：`function_calls/router.py:102-119` 对直接匹配的函数调用 `validate_arguments`，与 LLM 分支保持一致。 

- **[已完成] FunctionSpec 类型标注同步**  
  - 现状：`function_calls/spec.py:27-34` 中的 `handler` 类型现为 `Callable[[MessageContext, Any], FunctionResult]`。 

## 架构一致性评估
- 当前所有功能均通过 Function Call 服务层完成，提醒/骂人/搜索等不再依赖自然语言解析。 
- LLM 适配层维持兼容，必要时可扩展 jsonschema 校验和重试策略。 
- `robot.py:163-231` 仅初始化和调用 `FunctionCallRouter`，旧的命令/AI 路由器已移除，配置项也同步精简。 

## 建议的下一步
1. 扩充 `function_calls/services` 层的单元测试（例如提醒设置、Perplexity fallback 等），确保服务纯函数行为稳定。  
2. 若后续新增工具函数，遵循 `FunctionResult` + service 的模式，并及时更新 `FUNCTION_CALL_USAGE.md`。  
3. 观察线上日志，确认精简后的路由无遗漏场景；如需更多指令，优先在 direct-match 表中补充结构化参数生成逻辑。 

如按以上步骤推进，可逐步达到“标准 Function Call 模式”预期：所有工具能力通过结构化 schema 暴露，handler 仅消费结构化参数，无需再回退自然语言解析。
