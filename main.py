#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bubbles - 基于 Channel 抽象的聊天机器人
"""

import asyncio
import signal
import logging
import sys
import os
from argparse import ArgumentParser

from configuration import Config
from bot import BubblesBot, __version__


def setup_logging(level: int = logging.INFO):
    """配置日志"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 降低第三方库日志级别
    for name in ["httpx", "httpcore", "openai", "urllib3", "requests"]:
        logging.getLogger(name).setLevel(logging.WARNING)


async def run_wechat():
    """微信模式"""
    from channel import WeChatChannel

    if WeChatChannel is None:
        print("错误: wcferry 不可用，请在 Windows 环境下运行")
        print("如需本地调试，请运行: python local_main.py")
        sys.exit(1)

    config = Config()
    channel = WeChatChannel(debug=False)
    bot = BubblesBot(channel=channel, config=config)

    # 信号处理
    def handle_signal(sig, frame):
        logging.info("收到退出信号，正在清理...")
        asyncio.create_task(shutdown(bot, channel))

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logging.info(f"Bubbles v{__version__} 启动中...")

    try:
        await bot.start()
    except Exception as e:
        logging.error(f"运行出错: {e}", exc_info=True)
    finally:
        await shutdown(bot, channel)


async def shutdown(bot: BubblesBot, channel):
    """清理资源"""
    await bot.stop()
    bot.cleanup()
    if hasattr(channel, "cleanup"):
        channel.cleanup()


def main():
    parser = ArgumentParser(description="Bubbles 聊天机器人")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="调试模式"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="安静模式"
    )
    parser.add_argument(
        "--local", action="store_true", help="本地调试模式（无需微信）"
    )
    args = parser.parse_args()

    # 日志级别
    if args.debug:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.ERROR
    else:
        level = logging.INFO

    setup_logging(level)

    if args.local:
        # 本地模式
        import local_main
        asyncio.run(local_main.main())
    else:
        # 微信模式
        asyncio.run(run_wechat())


if __name__ == "__main__":
    main()
