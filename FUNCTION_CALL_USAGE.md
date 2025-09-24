# Function Call 系统使用指南

## 概述

已成功完成从正则/路由体系到标准 Function Call 的迁移，新系统提供了更标准化、更易维护的函数调用能力。

## 系统架构

```
用户消息 -> FunctionCallRouter -> (直接命令匹配 / LLM选择函数) -> 参数验证 -> 执行Handler -> 返回结果
```

## 已迁移的功能

| 函数名 | 描述 | 作用域 | 需要@ |
|-------|------|--------|-------|
| `weather_query` | 查询城市天气预报 | both | 是 |
| `news_query` | 获取今日新闻 | both | 是 |
| `help` | 显示帮助信息 | both | 否 |
| `summary` | 总结群聊消息 | group | 是 |
| `reminder_set` | 设置提醒 | both | 是 |
| `reminder_list` | 查看提醒列表 | both | 是 |
| `reminder_delete` | 删除提醒 | both | 是 |
| `perplexity_search` | Perplexity搜索 | both | 是 |
| `clear_messages` | 清除消息历史 | group | 是 |
| `insult` | 骂人功能 | group | 是 |

## 配置说明

在 `config.yaml` 中添加了以下配置：

```yaml
function_call_router:
  enable: true   # 是否启用Function Call路由
  debug: false  # 是否启用调试日志
```

## 如何添加新功能

1. **定义参数模型** (在 `function_calls/models.py`)：
```python
class MyFunctionArgs(BaseModel):
    param1: str
    param2: int
```

2. **实现处理器** (在 `function_calls/handlers.py`)：
```python
@tool_function(
    name="my_function",
    description="我的功能描述",
    examples=["示例1", "示例2"],
    scope="both",
    require_at=True
)
def handle_my_function(ctx: MessageContext, args: MyFunctionArgs) -> FunctionResult:
    # 实现功能逻辑
    return FunctionResult(
        handled=True,
        messages=["处理结果"],
        at=ctx.msg.sender if ctx.is_group else ""
    )
```

## 工作原理

1. **直接命令匹配**：对于明确的命令（如"help"、"新闻"），仍可直接调用对应函数。
2. **多轮函数调用**：在原生 function call 模型下，助手会循环选择函数→等待工具输出→再决定是否继续调用或生成最终答复。
3. **参数提取与验证**：每次调用前都会根据 JSON Schema 校验参数，确保类型与必填字段正确。
4. **统一回复**：最终的用户回复由模型生成，工具返回的 `FunctionResult` 只作为 LLM 的工具消息输入。
5. **无回退逻辑**：系统已移除传统正则路由与 AI 路由，所有功能均通过 Function Call 管理。

## 测试验证

系统通过了完整的集成测试：
- ✅ 函数注册表正常工作
- ✅ 直接命令匹配准确
- ✅ 参数提取正确
- ✅ 类型验证有效

## 兼容性

- 保持与现有业务逻辑完全兼容
- 精简路由体系，不再依赖旧正则路由
- 不影响现有的微信客户端交互

## 性能优势

- 减少不必要的LLM调用（直接命令匹配）
- 标准化的参数处理
- 统一的错误处理和日志记录
- 更好的代码可维护性
