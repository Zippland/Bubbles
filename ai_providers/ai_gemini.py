# ai_providers/ai_gemini.py
#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import time
import httpx
import pathlib # 用于处理文件路径
import mimetypes # 用于猜测图片类型
import google.generativeai as genai
from google.generativeai.types import generation_types, safety_types # 显式导入需要的类型
from google.api_core.exceptions import GoogleAPICallError, ClientError

# 引入 MessageSummary 类型提示
try:
    from function.func_summary import MessageSummary
except ImportError:
    MessageSummary = object # Fallback

class Gemini:
    DEFAULT_MODEL = "gemini-1.5-pro-latest"
    DEFAULT_PROMPT = "You are a helpful assistant."
    DEFAULT_MAX_HISTORY = 30
    SAFETY_SETTINGS = { # 默认安全设置 - 可根据需要调整或从配置加载
        safety_types.HarmCategory.HARM_CATEGORY_HARASSMENT: safety_types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        safety_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: safety_types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        safety_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: safety_types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        safety_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: safety_types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    }

    def __init__(self, conf: dict, message_summary_instance: MessageSummary = None, bot_wxid: str = None) -> None:
        self.LOG = logging.getLogger("Gemini")
        self._api_key = conf.get("api_key")
        self._model_name = conf.get("model_name", self.DEFAULT_MODEL)
        # 存储原始配置的 prompt，用于初始化和可能的重载
        self._base_prompt = conf.get("prompt", self.DEFAULT_PROMPT)
        self._proxy = conf.get("proxy")
        self.max_history_messages = conf.get("max_history_messages", self.DEFAULT_MAX_HISTORY)

        self.message_summary = message_summary_instance
        self.bot_wxid = bot_wxid
        self._model = None
        self.support_vision = False # 初始化时假设不支持，成功加载模型后再判断

        if not self._api_key:
            self.LOG.error("Gemini API Key 未在配置中提供！")
            return # 没有 API Key 无法继续

        if not self.message_summary:
             self.LOG.warning("MessageSummary 实例未提供给 Gemini，上下文功能将不可用！")
        if not self.bot_wxid:
             self.LOG.warning("bot_wxid 未提供给 Gemini，可能无法正确识别机器人自身消息！")

        try:
            # 1. 配置代理 (如果提供)
            transport = None
            if self._proxy:
                try:
                    transport = httpx.HTTPTransport(proxy=self._proxy)
                    self.LOG.info(f"Gemini 使用代理: {self._proxy}")
                except Exception as proxy_err:
                    self.LOG.error(f"配置 Gemini 代理失败: {proxy_err}", exc_info=True)
                    # 代理配置失败，可以选择不使用代理继续或直接失败
                    # 这里选择继续，不使用代理
                    transport = None

            # 2. 配置 Google AI Client
            genai.configure(api_key=self._api_key, transport=transport)

            # 3. 初始化模型
            # 将基础 prompt 作为 system_instruction 传递
            self._model = genai.GenerativeModel(
                self._model_name,
                system_instruction=self._base_prompt,
                safety_settings=self.SAFETY_SETTINGS # 应用安全设置
            )
            self.LOG.info(f"已加载 Gemini 模型")

            # 4. 检查视觉能力 (依赖模型名称的简单检查)
            # 注意：更可靠的方式是调用 list_models 并检查支持的方法
            if "vision" in self._model_name or "pro" in self._model_name or "gemini-1.5" in self._model_name or "flash" in self._model_name:
                 self.support_vision = True
                 self.LOG.info(f"模型 {self._model_name} 被认为支持视觉能力。")
            else:
                 self.LOG.info(f"模型 {self._model_name} 根据名称判断可能不支持视觉能力。")

        except (GoogleAPICallError, ClientError) as api_error:
            self.LOG.error(f"初始化 Gemini 时发生 API 错误: {api_error}", exc_info=True)
            self._model = None
        except Exception as e:
            self.LOG.error(f"初始化 Gemini 时发生未知错误: {e}", exc_info=True)
            self._model = None

    def __repr__(self):
        return f'Gemini(model={self._model_name}, initialized={self._model is not None})'

    @staticmethod
    def value_check(conf: dict) -> bool:
        # 只需要 API Key 是必须的
        return bool(conf and conf.get("api_key"))

    def _format_history(self, history: list) -> list:
        """将数据库历史消息转换为 Gemini API 的 contents 格式"""
        contents = []
        for msg in history:
            role = "model" if msg.get("sender_wxid") == self.bot_wxid else "user"
            content = msg.get('content', '')
            sender_name = msg.get('sender', '未知用户') # 获取发送者名称

            if content: # 避免添加空内容
                # Gemini 推荐 user role 包含发言者信息，model role 不需要
                if role == "user":
                    formatted_content = f"[{sender_name}]: {content}" # 添加发送者标记
                    contents.append({'role': role, 'parts': [{'text': formatted_content}]})
                else: # role == "model"
                    contents.append({'role': role, 'parts': [{'text': content}]})
        return contents

    def _generate_response(self, contents: list, generation_config_override: generation_types.GenerationConfig | None = None) -> str:
        """内部方法，用于调用 Gemini API 并处理响应"""
        if not self._model:
            return "Gemini 模型未成功初始化，请检查配置和网络。"

        # 配置生成参数 (可以从 config 中读取更多参数)
        # 默认使用适中的温度，可以根据需要调整
        default_config = generation_types.GenerationConfig(temperature=0.7)
        config_to_use = generation_config_override if generation_config_override else default_config

        self.LOG.debug(f"发送给 Gemini API 的内容条数: {len(contents)}")
        # self.LOG.debug(f"使用的 GenerationConfig: {config_to_use}")
        # self.LOG.debug(f"发送内容详情: {contents}") # DEBUG: 打印发送内容

        rsp_text = ""
        try:
            # 调用 API
            response = self._model.generate_content(
                contents=contents,
                generation_config=config_to_use,
                # safety_settings=... # 如果需要覆盖初始化时的安全设置
                stream=False # 非流式响应
            )

            # 1. 检查 Prompt 是否被阻止 (在获取 candidates 之前)
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                reason = response.prompt_feedback.block_reason.name
                self.LOG.warning(f"Gemini 提示被阻止，原因: {reason}")
                return f"抱歉，您的请求因包含不适内容而被阻止 (原因: {reason})。"

            # 2. 检查 Candidates 和 Finish Reason
            # 尝试从 response 中安全地提取文本
            try:
                rsp_text = response.text # .text 是获取聚合文本的便捷方式
            except ValueError:
                # 如果 .text 不可用 (例如，因为 finish_reason 不是 STOP 或 MAX_TOKENS)
                # 检查具体的 finish_reason
                if response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = candidate.finish_reason # 类型是 FinishReason 枚举
                    finish_reason_name = finish_reason.name

                    if finish_reason == generation_types.FinishReason.SAFETY:
                        self.LOG.warning(f"Gemini 响应被安全策略阻止。")
                        # 可以尝试查看 safety_ratings 获取更详细信息
                        ratings_info = getattr(candidate, 'safety_ratings', [])
                        self.LOG.debug(f"Safety Ratings: {ratings_info}")
                        return "抱歉，生成的响应可能包含不安全内容，已被阻止。"
                    elif finish_reason == generation_types.FinishReason.RECITATION:
                        self.LOG.warning(f"Gemini 响应因引用保护被阻止。")
                        return "抱歉，回答可能包含受版权保护的内容，已被部分阻止。"
                    elif finish_reason == generation_types.FinishReason.OTHER:
                         self.LOG.warning(f"Gemini 响应因未知原因停止 (FinishReason: OTHER)")
                         return "抱歉，生成响应时遇到未知问题。"
                    else:
                        # 包括 MAX_TOKENS, STOP 等预期情况，但没有文本
                        self.LOG.warning(f"Gemini 未返回文本内容，但完成原因可接受: {finish_reason_name}")
                        return f"生成内容时遇到问题 (完成原因: {finish_reason_name})"
                else:
                    # 没有 candidates，也没有 prompt block，未知情况
                    self.LOG.error("Gemini API 调用成功但未返回任何候选内容或提示反馈。")
                    return "抱歉，Gemini未能生成响应。"

        except (GoogleAPICallError, ClientError) as api_error:
             self.LOG.error(f"Gemini API 调用错误：{api_error}", exc_info=True)
             if "API key not valid" in str(api_error):
                  return "Gemini API 密钥无效或已过期。"
             elif "quota" in str(api_error).lower():
                  return "Gemini API 调用已达配额限制。"
             elif "Model not found" in str(api_error):
                  return f"配置的 Gemini 模型 '{self._model_name}' 未找到或不可用。"
             elif "Resource has been exhausted" in str(api_error):
                 return "Gemini API 资源耗尽，请稍后再试或检查配额。"
             else:
                  return f"与 Gemini 通信时出错: {type(api_error).__name__}"
        except generation_types.StopCandidateException as sce: # 明确捕获这个
             self.LOG.error(f"Gemini API 响应被停止 (StopCandidateException): {sce}", exc_info=True)
             # 通常在流式处理中遇到，但也可能在非流式中因某些原因触发
             return "抱歉，Gemini 生成的响应被意外停止了。"
        # BlockedPromptException 似乎不直接抛出，而是通过 prompt_feedback 反馈
        # except generation_types.BlockedPromptException as bpe:
        #      self.LOG.error(f"Gemini API 提示被阻止：{bpe}", exc_info=True)
        #      return "抱歉，您的请求内容被 Gemini 阻止了。"
        except Exception as e:
             self.LOG.error(f"调用 Gemini 时发生未知错误: {e}", exc_info=True)
             return f"处理您的请求时发生未知错误: {type(e).__name__}"

        return rsp_text.strip()

    def get_answer(
        self,
        question: str,
        wxid: str,
        system_prompt_override=None,
        specific_max_history=None,
        tools=None,
        tool_handler=None,
        tool_choice=None,
        tool_max_iterations: int = 10
    ) -> str:
        if not self._model:
            return "Gemini 模型未成功初始化，请检查配置和网络。"

        if not question:
            self.LOG.warning(f"尝试为 wxid={wxid} 获取答案，但问题为空。")
            return "您没有提问哦。"

        if tools:
            self.LOG.debug("Gemini 提供的实现暂不支持工具调用，请忽略 tools 参数。")

        # 1. 准备历史消息
        contents = []
        if self.message_summary and self.bot_wxid:
            history = self.message_summary.get_messages(wxid)
            limit = specific_max_history if specific_max_history is not None else self.max_history_messages
            self.LOG.debug(f"获取 Gemini 历史 for {wxid}, 原始条数: {len(history)}, 使用限制: {limit}")

            if limit > 0:
                history = history[-limit:]
            elif limit == 0:
                history = [] # 明确清空历史

            self.LOG.debug(f"应用限制后 Gemini 历史条数: {len(history)}")
            contents.extend(self._format_history(history))
        else:
            self.LOG.warning(f"无法为 wxid={wxid} 获取 Gemini 历史记录。")

        # 2. 添加当前用户问题
        # 注意：格式化时已包含发送者信息
        contents.append({'role': 'user', 'parts': [{'text': question}]})

        # 3. 处理 System Prompt Override (如果提供)
        # 注意：Gemini API 目前不直接支持在 generate_content 中覆盖 system_instruction
        # 如果需要动态改变系统提示，通常需要重新初始化模型或在用户消息前插入一条 'user' role 的指令
        # 这里我们暂时忽略 system_prompt_override，因为标准 API 调用不支持
        if system_prompt_override:
             self.LOG.warning("Gemini API 当前不支持单次请求覆盖系统提示，将使用初始化时的提示。")
        # 可以考虑在这里将 override 的内容作为一条 user message 添加到 contents 开头
        # 例如: contents.insert(0, {'role': 'user', 'parts': [{'text': f"[System Instruction Override]: {system_prompt_override}"}]})
        # 但这会影响对话历史的结构，需要谨慎使用

        # 4. 添加当前时间信息（可选，作为用户消息的一部分）
        now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        # 可以将时间信息添加到最近的用户消息中，或作为一条新的 user message
        # 为了简单，暂不自动添加时间信息到内容中，如果需要，可以在 prompt 中说明

        # 5. 调用内部生成方法
        return self._generate_response(contents)

    def get_image_description(self, image_path: str, prompt: str = "请详细描述这张图片中的内容") -> str:
         if not self._model:
             return "Gemini 模型未初始化。"
         if not self.support_vision:
             return f"当前 Gemini 模型 '{self._model_name}' 不支持图片理解。"

         image_path_obj = pathlib.Path(image_path)
         if not image_path_obj.is_file():
             self.LOG.error(f"图片文件不存在或不是文件: {image_path}")
             return "无法读取图片文件"

         try:
             # 猜测 MIME 类型
             mime_type, _ = mimetypes.guess_type(image_path_obj)
             if not mime_type or not mime_type.startswith("image/"):
                 self.LOG.warning(f"无法确定图片 MIME 类型或类型不是 image/*: {image_path}, 猜测为 jpeg")
                 mime_type = "image/jpeg" # 使用默认值

             self.LOG.info(f"使用 Gemini 分析图片: {image_path} (MIME: {mime_type})")

             # 使用 pathlib 生成 file URI
             image_uri = image_path_obj.absolute().as_uri()

             image_part = {'mime_type': mime_type, 'data': image_path_obj.read_bytes()}

             # 构建包含文本提示和图片的消息
             contents = [
                 # Gemini 处理多模态输入时，推荐 prompt 和 image 都在 user role 的 parts 里
                 {'role': 'user', 'parts': [
                     {'text': prompt},
                     image_part
                     # 或者使用 from_uri (如果 API 支持且网络可访问该文件 URI):
                     # genai.types.Part.from_uri(mime_type=mime_type, uri=image_uri)
                     # 使用原始字节通常更可靠
                 ]}
             ]

             # 可以为图片分析设置不同的生成参数，例如更低的温度以获得更客观的描述
             image_gen_config = generation_types.GenerationConfig(temperature=0.4)

             # 调用内部生成方法
             return self._generate_response(contents, generation_config_override=image_gen_config)

         except FileNotFoundError:
             self.LOG.error(f"读取图片文件时发生 FileNotFoundError: {image_path}", exc_info=True)
             return "读取图片文件时出错。"
         except Exception as e:
             self.LOG.error(f"使用 Gemini 分析图片时发生未知错误: {e}", exc_info=True)
             return f"分析图片时发生未知错误: {type(e).__name__}"

# --- Main 测试部分 ---
if __name__ == "__main__":
    print("--- 运行 Gemini 本地测试 ---")
    # 配置日志记录
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # --- 配置加载 ---
    # !!! 强烈建议从环境变量或安全的配置文件加载 API Key !!!
    # 例如: api_key = os.environ.get("GEMINI_API_KEY")
    # 不要将 API Key 硬编码在代码中提交
    api_key_from_env = os.environ.get("GEMINI_API_KEY")
    proxy_from_env = os.environ.get("HTTP_PROXY") # 支持 http/https 代理

    if not api_key_from_env:
         print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
         print("!!! 警告：环境变量 GEMINI_API_KEY 未设置。请设置该变量。   !!!")
         print("!!! 测试将无法连接到 Gemini API。                          !!!")
         print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
         # 可以选择退出或继续（如果只想测试初始化逻辑）
         # exit(1)
         api_key_to_use = "DUMMY_KEY_FOR_INIT_TEST" # 仅用于测试初始化日志，无法实际调用
    else:
        api_key_to_use = api_key_from_env

    mock_config = {
        "api_key": api_key_to_use,
        "model_name": "gemini-1.5-flash-latest", # 使用较快的模型测试
        "prompt": "你是一个风趣幽默的AI助手，擅长讲冷笑话。",
        "proxy": proxy_from_env,
        "max_history_messages": 3 # 测试时减少历史记录
    }
    print(f"测试配置: Model={mock_config['model_name']}, Proxy={'已设置' if mock_config['proxy'] else '未设置'}")

    # --- 初始化 Gemini ---
    # 在测试中不依赖 MessageSummary
    print("\n--- 初始化 Gemini 实例 ---")
    gemini_assistant = Gemini(mock_config, bot_wxid="test_bot_wxid") # 提供一个测试 bot_wxid

    # --- 测试文本生成 ---
    if gemini_assistant._model: # 检查模型是否成功初始化
        print("\n--- 测试文本生成 (get_answer) ---")
        test_question = "你好！今天天气怎么样？给我讲个关于程序员的冷笑话吧。"
        print(f"提问: {test_question}")
        start_time = time.time()
        answer = gemini_assistant.get_answer(test_question, "test_user_wxid") # 提供测试 wxid
        end_time = time.time()
        print(f"\nGemini 回答 (耗时: {end_time - start_time:.2f}s):\n{answer}")

        # 测试空问题
        print("\n--- 测试空问题 ---")
        empty_answer = gemini_assistant.get_answer("", "test_user_wxid")
        print(f"空问题回答: {empty_answer}")

        # 测试长对话历史（如果需要，可以手动构建一个 contents 列表来模拟）
        # print("\n--- 模拟长对话测试 ---")
        # mock_history = [
        #     {'role': 'user', 'parts': [{'text': "[UserA]: 第一次提问"}]},
        #     {'role': 'model', 'parts': [{'text': "第一次回答"}]},
        #     {'role': 'user', 'parts': [{'text': "[UserB]: 第二次提问"}]},
        #     {'role': 'model', 'parts': [{'text': "第二次回答"}]},
        #     {'role': 'user', 'parts': [{'text': "[UserA]: 第三次提问，关于第一次提问的内容"}]},
        # ]
        # mock_history.append({'role': 'user', 'parts': [{'text': "当前的第四个问题"}]})
        # long_hist_answer = gemini_assistant._generate_response(mock_history)
        # print(f"长历史回答:\n{long_hist_answer}")

    else:
        print("\n--- Gemini 初始化失败，跳过文本生成测试 ---")

    # --- 测试图片描述 (可选) ---
    if gemini_assistant._model and gemini_assistant.support_vision:
        print("\n--- 测试图片描述 (get_image_description) ---")
        # 将 'path/to/your/test_image.jpg' 替换为实际的图片路径
        image_test_path_str = "test_image.jpg" # 假设图片在脚本同目录下
        image_test_path = pathlib.Path(image_test_path_str)

        if image_test_path.exists():
            desc_prompt = "详细描述这张图片里的所有元素和场景氛围。"
            print(f"图片路径: {image_test_path.absolute()}")
            print(f"描述提示: {desc_prompt}")
            start_time = time.time()
            description = gemini_assistant.get_image_description(str(image_test_path), desc_prompt)
            end_time = time.time()
            print(f"\n图片描述 (耗时: {end_time - start_time:.2f}s):\n{description}")
        else:
            print(f"\n跳过图片测试，测试图片文件未找到: {image_test_path.absolute()}")
            print("请将一张名为 test_image.jpg 的图片放在脚本相同目录下进行测试。")
    elif gemini_assistant._model:
         print(f"\n--- 跳过图片测试，当前模型 {gemini_assistant._model_name} 不支持视觉 ---")
    else:
        print("\n--- Gemini 初始化失败，跳过图片描述测试 ---")

    print("\n--- Gemini 本地测试结束 ---")
