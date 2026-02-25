#!/usr/bin/env python3
# local_main.py
"""本地调试入口 - 无需微信环境"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from channel import LocalChannel
from bot import BubblesBot
from configuration import Config


def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 降低一些模块的日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


async def main():
    """主函数"""
    setup_logging()
    logger = logging.getLogger("LocalMain")

    # 加载配置
    try:
        config = Config()
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        logger.info("请确保 config.yaml 文件存在且配置正确")
        return

    # 创建本地 Channel
    channel = LocalChannel(bot_name="Bubbles", user_name="User")

    # 创建机器人
    bot = BubblesBot(channel=channel, config=config)

    # 启动
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
    finally:
        await bot.stop()
        bot.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
