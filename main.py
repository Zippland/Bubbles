#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import signal
import logging
import sys  # 导入 sys 模块
import os
from argparse import ArgumentParser

# 确保日志目录存在
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 配置 logging
log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
logging.basicConfig(
    level=logging.WARNING,  # 提高默认日志级别为 WARNING，只显示警告和错误信息
    format=log_format,
    handlers=[
        # logging.FileHandler(os.path.join(log_dir, "app.log"), encoding='utf-8'), # 将所有日志写入文件
        # logging.StreamHandler(sys.stdout) # 同时输出到控制台
    ]
)

# 为特定模块设置更具体的日志级别
logging.getLogger("requests").setLevel(logging.ERROR)  # 提高为 ERROR
logging.getLogger("urllib3").setLevel(logging.ERROR)   # 提高为 ERROR
logging.getLogger("httpx").setLevel(logging.ERROR)     # 提高为 ERROR

# 常见的自定义模块日志设置，按需修改
logging.getLogger("Weather").setLevel(logging.WARNING)
logging.getLogger("ai_providers").setLevel(logging.WARNING)
logging.getLogger("commands").setLevel(logging.WARNING)
# 临时调试：为AI路由器设置更详细的日志级别
logging.getLogger("commands.ai_router").setLevel(logging.INFO)

from configuration import Config
from constants import ChatType
from robot import Robot, __version__
from wcferry import Wcf

def main(chat_type: int):
    config = Config()
    wcf = Wcf(debug=False)  # 将 debug 设置为 False 减少 wcf 的调试输出
    
    # 定义全局变量robot，使其在handler中可访问
    global robot
    robot = Robot(config, wcf, chat_type)

    def handler(sig, frame):
        # 先清理机器人资源（包括关闭数据库连接）
        if 'robot' in globals() and robot:
            robot.LOG.info("程序退出，开始清理资源...")
            robot.cleanup()
            
        # 再清理wcf环境
        wcf.cleanup()  # 退出前清理环境
        exit(0)

    signal.signal(signal.SIGINT, handler)

    robot.LOG.info(f"WeChatRobot【{__version__}】成功启动···")

    # # 机器人启动发送测试消息
    # robot.sendTextMsg("机器人启动成功！", "filehelper")

    # 接收消息
    # robot.enableRecvMsg()     # 可能会丢消息？
    robot.enableReceivingMsg()  # 加队列

    # 每天 7 点发送天气预报
    robot.onEveryTime("07:00", robot.weatherReport)

    # 每天 7:30 发送新闻
    robot.onEveryTime("07:30", robot.newsReport)


    # 让机器人一直跑
    robot.keepRunningAndBlockProcess()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('-c', type=int, default=0, 
                        help=f'选择默认模型参数序号: {ChatType.help_hint()}（可通过配置文件为不同群指定模型）')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='启用调试模式，输出更详细的日志信息')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='安静模式，只输出错误信息')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='详细输出模式，显示所有信息日志')
    args = parser.parse_args()
    
    # 处理日志级别参数
    if args.debug:
        # 调试模式优先级最高
        logging.getLogger().setLevel(logging.DEBUG)
        print("已启用调试模式，将显示所有详细日志信息")
    elif args.quiet:
        # 安静模式，控制台只显示错误
        logging.getLogger().setLevel(logging.ERROR)
        print("已启用安静模式，控制台只显示错误信息")
    elif args.verbose:
        # 详细模式，显示所有 INFO 级别日志
        logging.getLogger().setLevel(logging.INFO)
        print("已启用详细模式，将显示所有信息日志")
    
    main(args.c)
