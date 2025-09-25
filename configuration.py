#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil
from typing import Dict, List

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

        return yconfig

    def reload(self) -> None:
        yconfig = self._load_config()
        logging.config.dictConfig(yconfig["logging"])
        self.CITY_CODE = yconfig["weather"]["city_code"]
        self.WEATHER = yconfig["weather"]["receivers"]
        self.GROUPS = yconfig["groups"]["enable"]
        self.WELCOME_MSG = yconfig["groups"].get("welcome_msg", "欢迎 {new_member} 加入群聊！")
        self.GROUP_MODELS = yconfig["groups"].get("models", {"default": 0, "mapping": []})
        self.NEWS = yconfig["news"]["receivers"]
        self.REPORT_REMINDERS = yconfig["report_reminder"]["receivers"]

        self.CHATGPT = yconfig.get("chatgpt", {})
        self.DEEPSEEK = yconfig.get("deepseek", {})
        self.PERPLEXITY = yconfig.get("perplexity", {})
        self.ALIYUN_IMAGE = yconfig.get("aliyun_image", {})
        self.MAX_HISTORY = yconfig.get("MAX_HISTORY", 300)
        self.SEND_RATE_LIMIT = yconfig.get("send_rate_limit", 0)
