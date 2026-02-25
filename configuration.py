#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil

import yaml


class Config(object):
    def __init__(self) -> None:
        self.reload()

    def _load_config(self) -> dict:
        pwd = os.path.dirname(os.path.abspath(__file__))
        try:
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)
        except FileNotFoundError:
            shutil.copyfile(f"{pwd}/config.yaml.template", f"{pwd}/config.yaml")
            with open(f"{pwd}/config.yaml", "rb") as fp:
                yconfig = yaml.safe_load(fp)

        return yconfig or {}

    def reload(self) -> None:
        yconfig = self._load_config()

        # 日志配置
        if "logging" in yconfig:
            logging.config.dictConfig(yconfig["logging"])

        # AI 模型配置
        self.CHATGPT = yconfig.get("chatgpt", {})
        self.DEEPSEEK = yconfig.get("deepseek", {})
        self.KIMI = yconfig.get("kimi", {})

        # 发送限制
        self.SEND_RATE_LIMIT = yconfig.get("send_rate_limit", 10)

        # Tavily 搜索
        self.TAVILY = yconfig.get("tavily", {})

        # 向后兼容（旧版 robot.py 可能用到）
        self.GROUPS = yconfig.get("groups", {}).get("enable", [])
        self.WELCOME_MSG = yconfig.get("groups", {}).get("welcome_msg", "")
        self.GROUP_MODELS = yconfig.get("groups_models", {"default": 0})
        self.MAX_HISTORY = yconfig.get("MAX_HISTORY", 300)
        self.AUTO_ACCEPT_FRIEND_REQUEST = yconfig.get("auto_accept_friend_request", False)
        self.NEWS = []
        self.WEATHER = []
        self.CITY_CODE = ""
        self.ALIYUN_IMAGE = {}
        self.MESSAGE_FORWARDING = {"enable": False, "rules": []}
        self.AI_ROUTER = {"enable": False}
        self.GROUP_RANDOM_CHITCHAT_DEFAULT = 0.0
        self.GROUP_RANDOM_CHITCHAT = {}
