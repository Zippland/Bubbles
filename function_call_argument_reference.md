# Function Call 参数调用参考

## 调用流程概览
- Function Call 路由器会将所有消息交给 `FunctionCallLLM.run`，模型基于已注册的函数规格选择要调用的工具（`function_calls/router.py:47`）。
- 每个处理器都通过 `@tool_function` 装饰器注册，它会读取参数类型注解并生成 JSON Schema，用于 LLM 约束和运行期验证（`function_calls/handlers.py:24`, `function_calls/registry.py:64`）。
- LLM 返回的参数会在 `_create_args_instance` 中转为对应的 Pydantic 模型；若字段缺失或类型不符则会抛错并被记录（`function_calls/router.py:147`）。

下表总结了当前仍启用的 5 个函数及其参数 Schema 与业务用途。
所有关键字段已通过 Pydantic `Field(..., description=...)` 写入属性说明，LLM 在工具定义中可以读取这些 `description` 以理解含义。

## 函数明细

### reminder_set
- **Handler**：`function_calls/handlers.py:24`
- **模型**：`ReminderArgs`（`function_calls/models.py:19`）
- **Schema 摘要**：
  ```json
  {
    "type": "object",
    "required": ["type", "time", "content"],
    "properties": {
      "type": {
        "type": "string",
        "enum": ["once", "daily", "weekly"],
        "description": "提醒类型：once=一次性提醒，daily=每天，weekly=每周"
      },
      "time": {
        "type": "string",
        "description": "提醒时间。once 使用 'YYYY-MM-DD HH:MM'，daily/weekly 使用 'HH:MM'"
      },
      "content": {
        "type": "string",
        "description": "提醒内容，将直接发送给用户"
      },
      "weekday": {
        "type": ["integer", "null"],
        "default": null,
        "description": "当 type=weekly 时的星期索引，0=周一 … 6=周日"
      }
    }
  }
  ```
- **参数含义**：
  - `type`：提醒频率。一次性（`once`）用于绝对时间点；`daily` 为每天定时；`weekly` 需要同时给出星期索引。
  - `time`：触发时间。一次性提醒要求未来时间，格式 `YYYY-MM-DD HH:MM`；每日/每周提醒使用 `HH:MM` 24 小时制。
  - `content`：提醒内容文本，最终会被发送给触发对象。
  - `weekday`：仅在 `type=weekly` 时有效，使用 0-6 表示周一到周日。
- **调用方式**：处理器从 `args.model_dump()` 得到完整参数字典并传给提醒服务的 `create_reminder`（`function_calls/handlers.py:37`）。`weekday` 仅在 `type="weekly"` 时使用；未提供值时默认为 `null`。

### reminder_list
- **Handler**：`function_calls/handlers.py:46`
- **模型**：`ReminderListArgs`（`function_calls/models.py:28`）
- **Schema 摘要**：空对象，没有任何必填字段。
- **调用方式**：函数只验证请求体为空对象，然后调用 `list_reminders` 读取当前用户/群的提醒列表（`function_calls/handlers.py:59`）。

### reminder_delete
- **Handler**：`function_calls/handlers.py:63`
- **模型**：`ReminderDeleteArgs`（`function_calls/models.py:33`）
- **Schema 摘要**：
  ```json
  {
    "type": "object",
    "required": ["reminder_id"],
    "properties": {
      "reminder_id": {
        "type": "string",
        "description": "提醒列表中的 ID（日志或界面可显示前几位帮助用户复制）"
      }
    }
  }
  ```
- **参数含义**：`reminder_id` 即提醒列表返回的唯一 ID，用于定位要删除的记录。
- **调用方式**：直接读取 `args.reminder_id` 并转交给 `delete_reminder` 执行删除逻辑（`function_calls/handlers.py:76`）。

### perplexity_search
- **Handler**：`function_calls/handlers.py:80`
- **模型**：`PerplexityArgs`（`function_calls/models.py:39`）
- **Schema 摘要**：
  ```json
  {
    "type": "object",
    "required": ["query"],
    "properties": {
      "query": {
        "type": "string",
        "description": "要搜索的问题或主题"
      }
    }
  }
  ```
- **参数含义**：`query` 即用户想让 Perplexity 查找的自然语言问题或主题。
- **调用方式**：使用 `args.query` 调用 `run_perplexity`，若外部服务已自行回复则返回空消息，否则把搜索结果转成回复文本（`function_calls/handlers.py:87`）。

### summary
- **Handler**：`function_calls/handlers.py:96`
- **模型**：`SummaryArgs`（`function_calls/models.py:49`）
- **Schema 摘要**：空对象，无需参数。
- **调用方式**：只要模型选择该函数即执行 `summarize_messages(ctx)`，返回群聊近期消息总结（`function_calls/handlers.py:104`）。

## 运行时验证逻辑
1. **模型侧约束**：`FunctionCallLLM` 会把上述 Schema 转成 OpenAI 样式的工具定义，使模型在生成参数时遵循字段、类型与枚举限制（`function_calls/llm.py:112`）。
2. **路由二次校验**：收到工具调用后，路由器会再次调用 `validate_arguments` 确认必填字段存在且类型正确（`function_calls/llm.py:215`）。
3. **Pydantic 转换**：最后在 `_create_args_instance` 中实例化 Pydantic 模型，确保所有字段通过严格校验并可在 handler 中以 `args` 访问（`function_calls/router.py:147`）。

若未来新增函数，只需为 handler 的 `args` 参数提供 Pydantic 模型或 dataclass，装饰器会自动生成相应 Schema 并同步到本流程中。
