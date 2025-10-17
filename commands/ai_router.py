import re
import json
import logging
from typing import Dict, Callable, Optional, Any, Tuple
from dataclasses import dataclass, field
from .context import MessageContext

logger = logging.getLogger(__name__)

ROUTING_HISTORY_LIMIT = 30
CHAT_HISTORY_MIN = 10
CHAT_HISTORY_MAX = 300

@dataclass
class AIFunction:
    """AI可调用的功能定义"""
    name: str                          # 功能唯一标识名
    handler: Callable                  # 处理函数
    description: str                   # 功能描述（给AI看的）
    examples: list[str] = field(default_factory=list)  # 示例用法
    params_description: str = ""       # 参数说明
    
class AIRouter:
    """AI智能路由器"""
    
    def __init__(self):
        self.functions: Dict[str, AIFunction] = {}
        self.logger = logger
        
    def register(self, name: str, description: str, examples: list[str] = None, params_description: str = ""):
        """
        装饰器：注册一个功能到AI路由器
        
        @ai_router.register(
            name="reminder_set",
            description="设置提醒",
            examples=["提醒我下午3点开会", "每天早上8点提醒我吃早饭"],
            params_description="提醒时间和内容"
        )
        def handle_reminder(ctx: MessageContext, params: str) -> bool:
            # 实现提醒设置逻辑
            pass
        """
        def decorator(func: Callable) -> Callable:
            ai_func = AIFunction(
                name=name,
                handler=func,
                description=description,
                examples=examples or [],
                params_description=params_description
            )
            self.functions[name] = ai_func
            self.logger.info(f"AI路由器注册功能: {name} - {description}")
            return func
        
        return decorator
    
    def _build_ai_prompt(self) -> str:
        """构建给AI的系统提示词，包含所有可用功能的信息"""
        prompt = """你是一个智能路由助手。根据用户的输入，判断用户的意图并返回JSON格式的响应。

        ### 注意：
        1. 你需要优先判断自己是否可以直接回答用户的问题，如果你可以直接回答，则返回 "chat"，无需返回 "function"
        2. 如果用户输入中包含多个功能，请优先匹配最符合用户意图的功能。如果无法判断，则返回 "chat"。
        3. 优先考虑使用 chat 处理，需要外部资料或其他功能逻辑时，再返回 "function"。

        ### 可用的功能列表：
        """
        for name, func in self.functions.items():
            prompt += f"\n- {name}: {func.description}"
            if func.params_description:
                prompt += f"\n  参数: {func.params_description}"
            if func.examples:
                prompt += f"\n  示例: {', '.join(func.examples[:3])}"
            prompt += "\n"

        prompt += """
        请你分析用户输入，严格按照以下格式返回JSON：

        ### 返回格式：

        1. 如果用户只是聊天或者不匹配任何功能，返回：
        {
            "action_type": "chat"
        }
3        另外，请判断该问题需不需要被认真对待，如果是比较严肃的问题，需要被认真对待，那么请通过参数配置开启深度思考，需要额外提供：
        {
            "action_type": "chat",
            "enable_reasoning": true
        }
        
        2.如果用户需要使用上述功能之一，返回：
        {
            "action_type": "function",
            "function_name": "上述功能列表中的功能名",
            "params": "从用户输入中提取的参数"
        }

        #### 示例：
        - 用户输入"提醒我下午3点开会" -> {"action_type": "function", "function_name": "reminder_hub", "params": "提醒我下午3点开会"}
        - 用户输入"查看我的提醒" -> {"action_type": "function", "function_name": "reminder_hub", "params": "查看我的提醒"}
        - 用户输入"你好" -> {"action_type": "chat"}
        - 用户输入"帮我认真想想这道题" -> {"action_type": "chat", "enable_reasoning": true}
        - 用户输入"查一下Python教程" -> {"action_type": "function", "function_name": "perplexity_search", "params": "Python教程"}

        #### 格式注意事项：
        1. action_type 只能是 "function" 或 "chat"
        2. 只返回JSON，无需其他解释
        3. function_name 必须完全匹配上述功能列表中的名称
        """
        return prompt
    
    def route(self, ctx: MessageContext) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        AI路由决策
        
        返回: (是否处理成功, AI决策结果)
        """
        self.logger.debug(f"[AI路由器] route方法被调用")
        
        if not ctx.text:
            self.logger.debug("[AI路由器] ctx.text为空，返回False")
            return False, None
            
        # 获取AI模型
        chat_model = getattr(ctx, 'chat', None)
        if not chat_model:
            chat_model = getattr(ctx.robot, 'chat', None) if ctx.robot else None
            
        if not chat_model:
            self.logger.error("[AI路由器] 无可用的AI模型")  
            return False, None
        
        self.logger.debug(f"[AI路由器] 找到AI模型: {type(chat_model)}")
        
        try:
            # 构建系统提示词
            system_prompt = self._build_ai_prompt()
            self.logger.debug(f"[AI路由器] 已构建系统提示词，长度: {len(system_prompt)}")
            
            # 让AI分析用户意图
            user_input = f"用户输入：{ctx.text}"
            self.logger.debug(f"[AI路由器] 准备调用AI分析意图: {user_input}")
            
            ai_response = chat_model.get_answer(
                user_input, 
                wxid=ctx.get_receiver(),
                system_prompt_override=system_prompt,
                specific_max_history=ROUTING_HISTORY_LIMIT
            )
            
            self.logger.debug(f"[AI路由器] AI响应: {ai_response}")
            
            # 解析AI返回的JSON
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if not json_match:
                self.logger.warning(f"AI路由器：无法从AI响应中提取JSON - {ai_response}")
                return False, None
                
            decision = json.loads(json_match.group(0))
            
            # 验证决策格式
            action_type = decision.get("action_type")
            if action_type not in ["chat", "function"]:
                self.logger.warning(f"AI路由器：未知的action_type - {action_type}")
                return False, None
            
            # 如果是功能调用，验证功能名
            if action_type == "function":
                function_name = decision.get("function_name")
                if function_name not in self.functions:
                    self.logger.warning(f"AI路由器：未知的功能名 - {function_name}")
                    return False, None
            else:
                # 聊天模式下检查是否请求推理
                if "enable_reasoning" in decision:
                    raw_value = decision.get("enable_reasoning")
                    if isinstance(raw_value, str):
                        decision["enable_reasoning"] = raw_value.strip().lower() in ("true", "1", "yes", "y")
                    else:
                        decision["enable_reasoning"] = bool(raw_value)
            
            self.logger.info(f"AI路由决策: {decision}")
            return True, decision
            
        except json.JSONDecodeError as e:
            self.logger.error(f"AI路由器：解析JSON失败 - {e}")
            return False, None
        except Exception as e:
            self.logger.error(f"AI路由器：处理异常 - {e}")
            return False, None
    
    def _check_permission(self, ctx: MessageContext) -> bool:
        """
        检查是否有权限使用AI路由功能
        
        :param ctx: 消息上下文
        :return: 是否有权限
        """
        # 检查是否启用AI路由
        ai_router_config = getattr(ctx.config, 'AI_ROUTER', {})
        if not ai_router_config.get('enable', True):
            self.logger.info("AI路由功能已禁用")
            return False
        
        # 私聊始终允许
        if not ctx.is_group:
            return True
        
        # 群聊需要检查白名单
        allowed_groups = ai_router_config.get('allowed_groups', [])
        current_group = ctx.get_receiver()
        
        if current_group in allowed_groups:
            self.logger.info(f"群聊 {current_group} 在AI路由白名单中，允许使用")
            return True
        else:
            self.logger.info(f"群聊 {current_group} 不在AI路由白名单中，禁止使用")
            return False

    def dispatch(self, ctx: MessageContext) -> bool:
        """
        执行AI路由分发
        
        返回: 是否成功处理
        """
        self.logger.debug(f"[AI路由器] dispatch被调用，消息内容: {ctx.text}")
        
        # 检查权限
        if not self._check_permission(ctx):
            self.logger.info("[AI路由器] 权限检查失败，返回False")
            return False
        
        # 获取AI路由决策
        success, decision = self.route(ctx)
        ctx.router_decision = decision if success else None
        self.logger.debug(f"[AI路由器] route返回 - success: {success}, decision: {decision}")
        
        if not success or not decision:
            self.logger.info("[AI路由器] route失败或无决策，返回False")
            return False
        
        action_type = decision.get("action_type")
        
        # 如果是聊天，返回False让后续处理器处理
        if action_type == "chat":
            self.logger.info("AI路由器：识别为聊天意图，交给聊天处理器处理。")
            return False
        
        # 如果是功能调用
        if action_type == "function":
            function_name = decision.get("function_name")
            params = decision.get("params", "")
            
            func = self.functions.get(function_name)
            if not func:
                self.logger.error(f"AI路由器：功能 {function_name} 未找到")
                return False
            
            try:
                self.logger.info(f"AI路由器：调用功能 {function_name}，参数: {params}")
                result = func.handler(ctx, params)
                return result
            except Exception as e:
                self.logger.error(f"AI路由器：执行功能 {function_name} 出错 - {e}")
                return False
        
        return False

# 创建全局AI路由器实例
ai_router = AIRouter()
