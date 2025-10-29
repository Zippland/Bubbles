#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging.config
import os
import shutil

import yaml


class Config(object):
    def __init__(self) -> None:
        self.reload()

    @staticmethod
    def _normalize_random_chitchat_probability(entry, fallback_probability=0.0):
        if isinstance(entry, (int, float)):
            probability = entry
        elif isinstance(entry, dict):
            probability = entry.get("probability", fallback_probability)
        else:
            probability = fallback_probability
        try:
            probability = float(probability)
        except (TypeError, ValueError):
            probability = fallback_probability
        probability = max(0.0, min(1.0, probability))
        return probability

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
        legacy_random_conf = yconfig["groups"].get("random_chitchat", {})
        legacy_default = self._normalize_random_chitchat_probability(
            legacy_random_conf.get("default", 0.0) if isinstance(legacy_random_conf, dict) else 0.0,
            fallback_probability=0.0,
        )
        legacy_mapping = {}
        if isinstance(legacy_random_conf, dict):
            for item in legacy_random_conf.get("mapping", []) or []:
                if not isinstance(item, dict):
                    continue
                room_id = item.get("room_id")
                if not room_id:
                    continue
                legacy_mapping[room_id] = self._normalize_random_chitchat_probability(
                    item,
                    fallback_probability=legacy_default,
                )

        random_chitchat_mapping = {}
        for item in self.GROUP_MODELS.get("mapping", []) or []:
            if not isinstance(item, dict):
                continue
            room_id = item.get("room_id")
            if not room_id:
                continue
            if "random_chitchat_probability" in item:
                rate = self._normalize_random_chitchat_probability(
                    item["random_chitchat_probability"],
                    fallback_probability=legacy_default,
                )
                random_chitchat_mapping[room_id] = rate
            elif room_id in legacy_mapping:
                random_chitchat_mapping[room_id] = legacy_mapping[room_id]

        self.GROUP_RANDOM_CHITCHAT_DEFAULT = legacy_default
        self.GROUP_RANDOM_CHITCHAT = random_chitchat_mapping

        self.NEWS = yconfig["news"]["receivers"]
        self.CHATGPT = yconfig.get("chatgpt", {})
        self.DEEPSEEK = yconfig.get("deepseek", {})
        self.PERPLEXITY = yconfig.get("perplexity", {})
        self.ALIYUN_IMAGE = yconfig.get("aliyun_image", {})
        self.AI_ROUTER = yconfig.get("ai_router", {"enable": True, "allowed_groups": []})
        self.AUTO_ACCEPT_FRIEND_REQUEST = yconfig.get("auto_accept_friend_request", False)
        self.MAX_HISTORY = yconfig.get("MAX_HISTORY", 300)
        self.SEND_RATE_LIMIT = yconfig.get("send_rate_limit", 0)
