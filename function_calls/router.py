"""Function Call 路由器"""

import logging
from typing import Any, Dict, Optional

from commands.context import MessageContext

from .spec import FunctionResult, FunctionSpec
from .registry import list_functions
from .llm import FunctionCallLLM

logger = logging.getLogger(__name__)


class FunctionCallRouter:
    """函数调用路由器"""

    def __init__(self, robot_instance=None):
        self.robot_instance = robot_instance
        self.llm = FunctionCallLLM()
        self.logger = logger

    def _check_scope_and_permissions(self, ctx: MessageContext, spec: FunctionSpec) -> bool:
        """检查作用域和权限"""
        # 1. 检查作用域
        if spec.scope != "both":
            if (spec.scope == "group" and not ctx.is_group) or \
               (spec.scope == "private" and ctx.is_group):
                return False

        # 2. 检查是否需要@机器人（仅在群聊中有效）
        if ctx.is_group and spec.require_at and not ctx.is_at_bot:
            return False

        # 3. 检查权限（如果有auth字段）
        if spec.auth:
            # TODO: 实现权限检查逻辑
            pass

        return True

    def _try_direct_command_match(self, ctx: MessageContext) -> Optional[str]:
        """
        尝试直接命令匹配，避免不必要的LLM调用

        返回匹配的函数名，如果没有匹配则返回None
        """
        text = ctx.text.strip().lower()

        # 定义一些明确的命令关键字映射
        direct_commands = {
            "help": "help",
            "帮助": "help",
            "指令": "help",
            "新闻": "news_query",
            "summary": "summary",
            "总结": "summary",
            "clearmessages": "clear_messages",
            "清除历史": "clear_messages"
        }

        # 检查完全匹配
        if text in direct_commands:
            return direct_commands[text]

        # 检查以特定前缀开头的命令
        if text.startswith("ask ") and len(text) > 4:
            return "perplexity_search"

        if text.startswith("天气") or text.startswith("天气预报"):
            return "weather_query"

        if text in ["查看提醒", "我的提醒", "提醒列表"]:
            return "reminder_list"

        if text.startswith("骂一下"):
            return "insult"

        return None

    def dispatch(self, ctx: MessageContext) -> bool:
        """
        分发消息到函数处理器

        返回: 是否成功处理
        """
        try:
            # 确保context可以访问到robot实例
            if self.robot_instance and not ctx.robot:
                ctx.robot = self.robot_instance
                if hasattr(self.robot_instance, 'LOG') and not ctx.logger:
                    ctx.logger = self.robot_instance.LOG

            if ctx.logger:
                ctx.logger.debug(f"FunctionCallRouter 开始处理: '{ctx.text}', 来自: {ctx.sender_name}")

            # 获取所有可用函数
            functions = list_functions()
            if not functions:
                self.logger.warning("没有注册任何函数")
                return False

            # 第一步：尝试直接命令匹配
            direct_function = self._try_direct_command_match(ctx)
            if direct_function and direct_function in functions:
                spec = functions[direct_function]

                if not self._check_scope_and_permissions(ctx, spec):
                    return False

                arguments = self._extract_arguments_for_direct_command(ctx, direct_function)
                if not self.llm.validate_arguments(arguments, spec.parameters_schema):
                    self.logger.warning(f"直接命令 {direct_function} 参数验证失败")
                    return False

                result = self._invoke_function(ctx, spec, arguments)
                if result.handled:
                    result.dispatch(ctx)
                    return True
                # 如果没有处理成功，继续尝试LLM流程

            # 第二步：使用LLM执行多轮函数调用
            llm_result = self.llm.run(
                ctx,
                functions,
                lambda spec, args: self._invoke_function(ctx, spec, args),
                self._format_tool_response,
            )

            if not llm_result.handled:
                return False

            if llm_result.final_response:
                at = ctx.msg.sender if ctx.is_group else ""
                ctx.send_text(llm_result.final_response, at)
                return True

            return True

        except Exception as e:
            self.logger.error(f"FunctionCallRouter dispatch 异常: {e}")
            return False

    def _extract_arguments_for_direct_command(self, ctx: MessageContext, function_name: str) -> Dict[str, Any]:
        """为直接命令提取参数"""
        text = ctx.text.strip()

        if function_name == "weather_query":
            # 提取城市名
            if text.startswith("天气预报 "):
                city = text[4:].strip()
            elif text.startswith("天气 "):
                city = text[3:].strip()
            else:
                city = ""
            return {"city": city}

        elif function_name == "perplexity_search":
            # 提取搜索查询
            if text.startswith("ask "):
                query = text[4:].strip()
            else:
                query = text
            return {"query": query}

        elif function_name == "insult":
            # 提取要骂的用户
            import re
            match = re.search(r"骂一下\s*@([^\s@]+)", text)
            target_user = match.group(1) if match else ""
            return {"target_user": target_user}

        # 对于不需要参数的函数，返回空字典
        return {}

    def _invoke_function(self, ctx: MessageContext, spec: FunctionSpec, arguments: Dict[str, Any]) -> FunctionResult:
        """调用函数处理器，返回结构化结果"""
        try:
            if ctx.logger:
                ctx.logger.info(f"执行函数: {spec.name}, 参数: {arguments}")

            args_instance = self._create_args_instance(spec, arguments)
            result = spec.handler(ctx, args_instance)

            if not isinstance(result, FunctionResult):
                raise TypeError(f"函数 {spec.name} 返回了非 FunctionResult 类型: {type(result)}")

            if ctx.logger and not result.handled:
                ctx.logger.warning(f"函数 {spec.name} 返回未处理状态")

            return result

        except Exception as exc:
            self.logger.error(f"执行函数 {spec.name} 异常: {exc}")
            return FunctionResult(
                handled=False,
                messages=[f"函数 {spec.name} 执行失败: {exc}"],
                metadata={"error": str(exc)},
            )

    def _create_args_instance(self, spec: FunctionSpec, arguments: Dict[str, Any]):
        """根据函数规格创建参数实例"""
        try:
            # 获取函数的类型注解
            from typing import get_type_hints
            hints = get_type_hints(spec.handler)
            args_type = hints.get('args')

            if args_type:
                # 如果是Pydantic模型
                if hasattr(args_type, 'model_validate'):
                    return args_type.model_validate(arguments)
                elif hasattr(args_type, '__init__'):
                    # 普通类
                    return args_type(**arguments)

            # 如果没有类型注解，返回参数字典
            return arguments

        except Exception as exc:
            self.logger.error(f"创建参数实例失败: {exc}")
            raise

    @staticmethod
    def _format_tool_response(result: FunctionResult) -> str:
        """将 FunctionResult 格式化为供 LLM 读取的 tool 响应"""
        return result.to_tool_content()
