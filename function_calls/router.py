"""Function Call 路由器"""

import logging
from typing import Any, Dict

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

            # 使用 LLM 执行函数调用流程
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
