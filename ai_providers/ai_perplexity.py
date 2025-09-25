#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import re
import time
from typing import Optional, Dict, Callable, List
import os
from threading import Thread, Lock
from openai import OpenAI


class PerplexityThread(Thread):
    """处理Perplexity请求的线程"""
    
    def __init__(self, perplexity_instance, prompt, chat_id, send_text_func, receiver, at_user=None):
        """初始化Perplexity处理线程
        
        Args:
            perplexity_instance: Perplexity实例
            prompt: 查询内容
            chat_id: 聊天ID
            send_text_func: 发送消息的函数，接受(消息内容, 接收者ID, @用户ID)参数
            receiver: 接收消息的ID
            at_user: 被@的用户ID
        """
        super().__init__(daemon=True)
        self.perplexity = perplexity_instance
        self.prompt = prompt
        self.chat_id = chat_id
        self.send_text_func = send_text_func
        self.receiver = receiver
        self.at_user = at_user
        self.LOG = logging.getLogger("PerplexityThread")
        
        self.LOG.info(
            f"Perplexity使用模型: {self.perplexity.model_name}, 是否为reasoning模型: {self.perplexity.is_reasoning_model}"
        )
        
    def run(self):
        """线程执行函数"""
        try:
            self.LOG.info(f"开始处理Perplexity请求: {self.prompt[:30]}...")
            
            # 获取回答
            response = self.perplexity.get_answer(self.prompt, self.chat_id)
            
            if response:
                response = self.perplexity.sanitize_response(response)
                if response:
                    self.send_text_func(response, at_list=self.at_user)
                else:
                    self.send_text_func("无法从Perplexity获取回答", at_list=self.at_user)
            else:
                self.send_text_func("无法从Perplexity获取回答", at_list=self.at_user)
                
            self.LOG.info(f"Perplexity请求处理完成: {self.prompt[:30]}...")
            
        except Exception as e:
            self.LOG.error(f"处理Perplexity请求时出错: {e}")
            self.send_text_func(f"处理请求时出错: {e}", at_list=self.at_user)
    


class PerplexityManager:
    """管理Perplexity请求线程的类"""
    
    def __init__(self):
        self.threads = {}
        self.lock = Lock()
        self.LOG = logging.getLogger("PerplexityManager")
    
    def start_request(self, perplexity_instance, prompt, chat_id, send_text_func, receiver, at_user=None):
        """启动Perplexity请求线程
        
        Args:
            perplexity_instance: Perplexity实例
            prompt: 查询内容
            chat_id: 聊天ID
            send_text_func: 发送消息的函数
            receiver: 接收消息的ID
            at_user: 被@的用户ID
            
        Returns:
            bool: 是否成功启动线程
        """
        thread_key = f"{receiver}_{chat_id}"
        
        with self.lock:
            # 检查是否已有正在处理的相同请求
            if thread_key in self.threads and self.threads[thread_key].is_alive():
                send_text_func("⚠️ 已有一个Perplexity请求正在处理中，请稍后再试", at_list=at_user)
                return False
            
            # 发送等待消息
            send_text_func("正在使用Perplexity进行深度研究，请稍候...", at_list=at_user)
            
            # 创建并启动新线程处理请求
            perplexity_thread = PerplexityThread(
                perplexity_instance=perplexity_instance,
                prompt=prompt,
                chat_id=chat_id,
                send_text_func=send_text_func,
                receiver=receiver,
                at_user=at_user
            )
            
            # 添加线程完成回调，自动清理线程
            def thread_finished_callback():
                with self.lock:
                    if thread_key in self.threads:
                        del self.threads[thread_key]
                        self.LOG.info(f"已清理Perplexity线程: {thread_key}")
            
            # 保存线程引用
            self.threads[thread_key] = perplexity_thread
            
            # 启动线程
            perplexity_thread.start()
            self.LOG.info(f"已启动Perplexity请求线程: {thread_key}")
            
            return True
    
    def cleanup_threads(self):
        """清理所有Perplexity线程"""
        with self.lock:
            active_threads = []
            for thread_key, thread in self.threads.items():
                if thread.is_alive():
                    active_threads.append(thread_key)
                    
            if active_threads:
                self.LOG.info(f"等待{len(active_threads)}个Perplexity线程结束: {active_threads}")
                
                # 等待所有线程结束，但最多等待10秒
                for i in range(10):
                    active_count = 0
                    for thread_key, thread in self.threads.items():
                        if thread.is_alive():
                            active_count += 1
                    
                    if active_count == 0:
                        break
                        
                    time.sleep(1)
                
                # 记录未能结束的线程
                still_active = [thread_key for thread_key, thread in self.threads.items() if thread.is_alive()]
                if still_active:
                    self.LOG.warning(f"以下Perplexity线程在退出时仍在运行: {still_active}")
            
            # 清空线程字典
            self.threads.clear()
            self.LOG.info("Perplexity线程管理已清理")


class Perplexity:
    def __init__(self, config):
        self.config = config
        self.api_key = config.get('key')
        self.api_base = config.get('api', 'https://api.perplexity.ai')
        self.proxy = config.get('proxy')
        self.prompt = config.get('prompt', '你是智能助手Perplexity')
        self.trigger_keyword = config.get('trigger_keyword', 'ask')
        self.fallback_prompt = config.get('fallback_prompt', "请像 Perplexity 一样，以专业、客观、信息丰富的方式回答问题。不要使用任何tex或者md格式,纯文本输出。")
        self.LOG = logging.getLogger('Perplexity')
        self.model = config.get('model', 'sonar')
        self.model_name = str(self.model).lower()
        self.is_reasoning_model = 'reasoning' in self.model_name
        
        # 权限控制 - 允许使用Perplexity的群聊和个人ID
        self.allowed_groups = config.get('allowed_groups', [])
        self.allowed_users = config.get('allowed_users', [])
        
        # 可选的全局白名单模式 - 如果为True，则允许所有群聊和用户使用Perplexity
        self.allow_all = config.get('allow_all', False)
        
        # 设置编码环境变量，确保处理Unicode字符
        os.environ["PYTHONIOENCODING"] = "utf-8"
        
        # 创建线程管理器
        self.thread_manager = PerplexityManager()
        
        # 创建OpenAI客户端
        self.client = None
        if self.api_key:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.api_base
                )
                # 如果有代理设置
                if self.proxy:
                    # OpenAI客户端不直接支持代理设置，需要通过环境变量
                    os.environ["HTTPS_PROXY"] = self.proxy
                    os.environ["HTTP_PROXY"] = self.proxy
                
                self.LOG.info("Perplexity 客户端已初始化")
                
                # 记录权限配置信息
                if self.allow_all:
                    self.LOG.info("Perplexity配置为允许所有群聊和用户访问")
                else:
                    self.LOG.info(f"Perplexity允许的群聊: {len(self.allowed_groups)}个")
                    self.LOG.info(f"Perplexity允许的用户: {len(self.allowed_users)}个")
                
            except Exception as e:
                self.LOG.error(f"初始化Perplexity客户端失败: {str(e)}")
        else:
            self.LOG.warning("未配置Perplexity API密钥")
            
    def is_allowed(self, chat_id, sender, from_group):
        """检查是否允许使用Perplexity功能
        
        Args:
            chat_id: 聊天ID（群ID或用户ID）
            sender: 发送者ID
            from_group: 是否来自群聊
            
        Returns:
            bool: 是否允许使用Perplexity
        """
        # 全局白名单模式
        if self.allow_all:
            return True
            
        # 群聊消息
        if from_group:
            return chat_id in self.allowed_groups
        # 私聊消息
        else:
            return sender in self.allowed_users
            
    @staticmethod
    def value_check(args: dict) -> bool:
        if args:
            return all(value is not None for key, value in args.items() if key != 'proxy')
        return False
        
    def get_answer(self, prompt, session_id=None):
        """获取Perplexity回答
        
        Args:
            prompt: 用户输入的问题
            session_id: 会话ID，用于区分不同会话
            
        Returns:
            str: Perplexity的回答
        """
        try:
            if not self.api_key or not self.client:
                return "Perplexity API key 未配置或客户端初始化失败"
            
            # 构建消息列表
            messages = [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": prompt}
            ]
            
            # 获取模型
            model = self.model
            
            # 使用json序列化确保正确处理Unicode
            self.LOG.info(f"发送到Perplexity的消息: {json.dumps(messages, ensure_ascii=False)}")
            
            # 创建聊天完成
            response = self.client.chat.completions.create(
                model=model,
                messages=messages
            )
            
            # 返回回答内容
            return response.choices[0].message.content
                
        except Exception as e:
            self.LOG.error(f"调用Perplexity API时发生错误: {str(e)}")
            return f"发生错误: {str(e)}"

    def sanitize_response(self, text: str) -> str:
        """根据模型类型清理Perplexity响应"""
        if not isinstance(text, str):
            return ""

        cleaned = text
        if self.is_reasoning_model:
            cleaned = self._remove_thinking_content(cleaned)

        cleaned = self._remove_markdown_formatting(cleaned)
        return cleaned.strip()

    def _remove_thinking_content(self, text: str) -> str:
        try:
            has_thinking = '<think>' in text or '</think>' in text
            if has_thinking:
                self.LOG.info("检测到思考内容标签，准备移除...")

                if text.count('<think>') != text.count('</think>'):
                    self.LOG.warning(
                        f"检测到不匹配的思考标签: <think>数量={text.count('<think>')}, </think>数量={text.count('</think>')}"
                    )

                thinking_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
                thinking_matches = thinking_pattern.findall(text)
                if thinking_matches:
                    for index, thinking in enumerate(thinking_matches, start=1):
                        short_thinking = thinking[:100] + '...' if len(thinking) > 100 else thinking
                        self.LOG.debug(f"思考内容 #{index}: {short_thinking}")

                cleaned_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
                cleaned_text = re.sub(r'<think>.*?$', '', cleaned_text, flags=re.DOTALL)
                cleaned_text = re.sub(r'^.*?</think>', '', cleaned_text, flags=re.DOTALL)
                cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
                cleaned_text = cleaned_text.strip()

                self.LOG.info(
                    f"思考内容已移除，原文本长度: {len(text)} -> 清理后: {len(cleaned_text)}"
                )

                if not cleaned_text:
                    return "回答内容为空，可能是模型仅返回了思考过程。请重新提问。"

                return cleaned_text

        except Exception as exc:
            self.LOG.error(f"清理思考内容时出错: {exc}")

        return text

    def _remove_markdown_formatting(self, text: str) -> str:
        try:
            self.LOG.info("开始移除Markdown格式符号...")
            original_length = len(text)

            cleaned_text = re.sub(r'^\s*#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
            cleaned_text = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned_text)
            cleaned_text = re.sub(r'\*(.*?)\*', r'\1', cleaned_text)
            cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
            cleaned_text = cleaned_text.strip()

            self.LOG.info(
                f"Markdown格式符号已移除，原文本长度: {original_length} -> 清理后: {len(cleaned_text)}"
            )

            return cleaned_text

        except Exception as exc:
            self.LOG.error(f"移除Markdown格式符号时出错: {exc}")
            return text
    
    def process_message(self, content, chat_id, sender, roomid, from_group, send_text_func):
        """处理可能包含Perplexity触发词的消息
        
        Args:
            content: 消息内容
            chat_id: 聊天ID
            sender: 发送者ID
            roomid: 群聊ID（如果是群聊）
            from_group: 是否来自群聊
            send_text_func: 发送消息的函数
            
        Returns:
            tuple[bool, Optional[str]]: 
                - bool: 是否已处理该消息
                - Optional[str]: 无权限时的备选prompt，其他情况为None
        """
        # 检查是否包含触发词
        if content.startswith(self.trigger_keyword):
            # 检查权限
            if not self.is_allowed(chat_id, sender, from_group):
                # 不在允许列表中，返回False让普通AI处理请求
                # 但同时返回备选 prompt
                self.LOG.info(f"用户/群聊 {chat_id} 无Perplexity权限，将使用 fallback_prompt 转由普通AI处理")
                # 获取实际要问的问题内容
                prompt = content[len(self.trigger_keyword):].strip()
                if prompt:  # 确保确实有提问内容
                    return False, self.fallback_prompt  # 返回 False 表示未处理，并带上备选 prompt
                else:
                    # 如果只有触发词没有问题，还是按原逻辑处理（发送提示消息）
                    send_text_func(f"请在{self.trigger_keyword}后面添加您的问题", 
                                  roomid if from_group else sender,
                                  sender if from_group else None)
                    return True, None  # 已处理（发送了错误提示）
                
            prompt = content[len(self.trigger_keyword):].strip()
            if prompt:
                # 确定接收者和@用户
                receiver = roomid if from_group else sender
                at_user = sender if from_group else None
                
                # 启动请求处理
                request_started = self.thread_manager.start_request(
                    perplexity_instance=self,
                    prompt=prompt,
                    chat_id=chat_id,
                    send_text_func=send_text_func,
                    receiver=receiver,
                    at_user=at_user
                )
                return request_started, None  # 返回启动结果，无备选prompt
            else:
                # 触发词后没有内容
                send_text_func(f"请在{self.trigger_keyword}后面添加您的问题", 
                              roomid if from_group else sender,
                              sender if from_group else None)
                return True, None  # 已处理（发送了错误提示）
        
        # 不包含触发词
        return False, None  # 未处理，无备选prompt
    
    def cleanup(self):
        """清理所有资源"""
        self.thread_manager.cleanup_threads()
            
    def __str__(self):
        return "Perplexity" 
