# commands package
"""
消息处理组件包

模块说明:
- context: 消息上下文类 (MessageContext)
- handlers: 功能处理函数 (保留旧版兼容)

新架构 (agent/):
- agent.loop: Agent Loop 核心
- agent.context: AgentContext
- agent.tools: 工具定义和注册

已废弃 (保留兼容):
- ai_router: AI 智能路由核心 -> 被 agent.loop 取代
- ai_functions: 面向 AI 路由的功能注册 -> 被 agent.tools 取代
""" 
