"""
初始化所有Function Call处理器
导入这个模块会自动注册所有处理器到全局注册表
"""
from . import handlers  # 导入handlers模块会自动执行所有装饰器注册

# 可以在这里添加一些初始化日志
import logging
logger = logging.getLogger(__name__)
logger.info("Function Call 处理器初始化完成")