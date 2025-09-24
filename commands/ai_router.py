import re
import json
import logging
from typing import Dict, Callable, Optional, Any, Tuple
from dataclasses import dataclass, field
from .context import MessageContext

logger = logging.getLogger(__name__)

@dataclass
class AIFunction:
    """AI可调用的功能定义 - 最原生实现"""
    name: str                          # 功能唯一标识名
    handler: Callable                  # 处理函数
    description: str                   # 功能描述（给AI看的）
    parameters: dict = field(default_factory=dict)  # OpenAI function call参数定义

    def to_function_schema(self) -> dict:
        """转换为OpenAI function call schema格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
class AIRouter:
    """AI智能路由器"""
    
    def __init__(self):
        self.functions: Dict[str, AIFunction] = {}
        self.logger = logger
        
    def register(self, name: str, description: str, parameters: dict = None):
        """
        装饰器：注册一个功能到AI路由器 - 最原生实现

        Args:
            name: 功能名称
            description: 功能描述
            parameters: OpenAI function call参数定义

        @ai_router.register(
            name="weather_query",
            description="查询指定城市的天气预报",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                },
                "required": ["city"]
            }
        )
        def handle_weather(ctx: MessageContext, **kwargs) -> bool:
            city = kwargs.get('city')
            # 实现天气查询逻辑
            pass
        """
        def decorator(func: Callable) -> Callable:
            ai_func = AIFunction(
                name=name,
                handler=func,
                description=description,
                parameters=parameters or {}
            )
            self.functions[name] = ai_func
            self.logger.info(f"注册Function Call功能: {name} - {description}")
            return func

        return decorator
    
    def _build_function_tools(self, functions: Dict[str, AIFunction]) -> list:
        """构建function call的tools参数"""
        return [func.to_function_schema() for func in functions.values()]
    
    def handle_standard_function_call(self, ctx: MessageContext) -> bool:
        """
        标准的OpenAI Function Call实现
        支持多轮调用、函数结果反馈、AI最终回复
        """
        if not ctx.text:
            return False

        # 获取AI模型
        chat_model = getattr(ctx, 'chat', None) or getattr(ctx.robot, 'chat', None)
        if not chat_model:
            self.logger.error("无可用的AI模型")
            return False

        try:
            # 构建所有可用函数的tools
            tools = self._build_function_tools(self.functions)
            specific_max_history = getattr(ctx, 'specific_max_history', None)

            # 初始化对话历史
            conversation = [{"role": "user", "content": ctx.text}]

            # 最多5轮function call，防止无限循环
            max_iterations = 5

            for iteration in range(max_iterations):
                self.logger.debug(f"Function Call第{iteration+1}轮")

                # 调用AI模型
                response = chat_model.get_answer(
                    question="",  # 使用conversation模式，question可以为空
                    wxid=ctx.get_receiver(),
                    tools=tools,
                    specific_max_history=specific_max_history,
                    conversation_history=conversation  # 传递完整对话历史
                )

                # 如果AI直接回复文本（不调用函数）
                if isinstance(response, str):
                    at_list = ctx.msg.sender if ctx.is_group else ""
                    ctx.send_text(response, at_list)
                    return True

                # 如果AI调用函数
                if isinstance(response, dict) and 'tool_calls' in response:
                    tool_calls = response['tool_calls']

                    # 添加assistant消息到对话历史
                    conversation.append({
                        "role": "assistant",
                        "tool_calls": tool_calls
                    })

                    # 执行所有函数调用
                    for tool_call in tool_calls:
                        function_name = tool_call['function']['name']
                        arguments = json.loads(tool_call['function']['arguments'])

                        self.logger.info(f"执行函数: {function_name}, 参数: {arguments}")

                        # 执行函数
                        func = self.functions.get(function_name)
                        if func:
                            try:
                                # 调用函数处理器
                                success = func.handler(ctx, **arguments)
                                function_result = "执行成功" if success else "执行失败"
                            except Exception as e:
                                self.logger.error(f"函数{function_name}执行错误: {e}")
                                function_result = f"执行错误: {str(e)}"
                        else:
                            function_result = f"函数{function_name}不存在"

                        # 添加函数结果到对话历史
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get('id', f"call_{function_name}"),
                            "content": function_result
                        })

                    # 继续下一轮，让AI基于函数结果继续思考
                    continue

                # 如果响应格式异常，跳出循环
                break

            # 如果达到最大迭代次数，让AI生成最终回复
            if iteration == max_iterations - 1:
                final_response = chat_model.get_answer(
                    question="请基于以上函数调用结果，生成最终回复。",
                    wxid=ctx.get_receiver(),
                    specific_max_history=specific_max_history,
                    conversation_history=conversation
                )

                if isinstance(final_response, str):
                    at_list = ctx.msg.sender if ctx.is_group else ""
                    ctx.send_text(final_response, at_list)
                    return True

            return True

        except Exception as e:
            self.logger.error(f"标准Function Call处理异常: {e}")
            return False
    
    def dispatch(self, ctx: MessageContext) -> bool:
        """
        标准Function Call分发器
        """
        if not ctx.text:
            return False

        # 调用标准Function Call处理
        success = self.handle_standard_function_call(ctx)

        if not success:
            # 如果Function Call失败，回退到聊天模式
            return self._handle_chitchat(ctx)

        return True

    def _handle_chitchat(self, ctx: MessageContext) -> bool:
        """
        处理闲聊逻辑 - 最简实现
        """
        try:
            if not ctx.text:
                return False

            # 调用闲聊处理器
            from .handlers import handle_chitchat
            return handle_chitchat(ctx, None)
        except Exception as e:
            self.logger.error(f"闲聊处理出错: {e}")
            return False

# 创建全局AI路由器实例
ai_router = AIRouter()