import logging
import re
import html
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

# wcferry 仅在 Windows 可用
try:
    from wcferry import WxMsg
except ImportError:
    WxMsg = None

if TYPE_CHECKING:
    from wcferry import WxMsg as WxMsgType

class XmlProcessor:
    """处理微信消息XML解析的工具类"""
    
    def __init__(self, logger=None):
        """初始化XML处理器
        
        Args:
            logger: 日志对象，如果不提供则创建一个新的
        """
        self.logger = logger or logging.getLogger("XmlProcessor")
    
    def extract_quoted_message(self, msg: Any) -> dict:
        """从微信消息中提取引用内容
        
        Args:
            msg: 微信消息对象
            
        Returns:
            dict: {
                "new_content": "",     # 用户新发送的内容
                "quoted_content": "",  # 引用的内容
                "quoted_sender": "",   # 被引用消息的发送者
                "media_type": "",      # 媒体类型（文本/图片/视频/链接等）
                "has_quote": False,    # 是否包含引用
                "is_card": False,      # 是否为卡片消息
                "card_type": "",       # 卡片类型
                "card_title": "",      # 卡片标题
                "card_description": "", # 卡片描述
                "card_url": "",        # 卡片链接
                "card_appname": "",    # 卡片来源应用
                "card_sourcedisplayname": "", # 来源显示名称
                "quoted_is_card": False,    # 被引用的内容是否为卡片
                "quoted_card_type": "",     # 被引用的卡片类型
                "quoted_card_title": "",    # 被引用的卡片标题
                "quoted_card_description": "", # 被引用的卡片描述
                "quoted_card_url": "",      # 被引用的卡片链接
                "quoted_card_appname": "",  # 被引用的卡片来源应用
                "quoted_card_sourcedisplayname": "" # 被引用的来源显示名称
            }
        """
        result = {
            "new_content": "",
            "quoted_content": "",
            "quoted_sender": "",
            "media_type": "文本",
            "has_quote": False,
            "is_card": False,
            "card_type": "",
            "card_title": "",
            "card_description": "",
            "card_url": "",
            "card_appname": "",
            "card_sourcedisplayname": "",
            "quoted_is_card": False,
            "quoted_card_type": "",
            "quoted_card_title": "",
            "quoted_card_description": "",
            "quoted_card_url": "",
            "quoted_card_appname": "",
            "quoted_card_sourcedisplayname": ""
        }
        
        try:
            # 检查消息类型
            if msg.type != 0x01 and msg.type != 49:  # 普通文本消息或APP消息
                return result
            
            self.logger.info(f"处理群聊消息: 类型={msg.type}, 发送者={msg.sender}")
            
            # 检查是否为引用消息类型 (type 57)
            is_quote_msg = False
            appmsg_type_match = re.search(r'<appmsg.*?type="(\d+)"', msg.content, re.DOTALL)
            if appmsg_type_match and appmsg_type_match.group(1) == "57":
                is_quote_msg = True
                self.logger.info("检测到引用类型消息 (type 57)")
            
            # 检查是否包含refermsg标签
            has_refermsg = "<refermsg>" in msg.content
            
            # 确定是否是引用操作
            is_referring = is_quote_msg or has_refermsg
            
            # 处理App类型消息（类型49）
            if msg.type == 49:
                if not is_referring:
                    # 如果不是引用消息，按普通卡片处理
                    card_details = self.extract_card_details(msg.content)
                    result.update(card_details)
                    
                    # 根据卡片类型更新媒体类型
                    if card_details["is_card"] and card_details["card_type"]:
                        result["media_type"] = card_details["card_type"]
                
                # 引用消息情况下，我们不立即更新result的卡片信息，因为外层appmsg是引用容器
            
            # 处理用户新输入内容
            # 优先检查是否有<title>标签内容
            title_match = re.search(r'<title>(.*?)</title>', msg.content)
            if title_match:
                # 对于引用消息，从title标签提取用户新输入
                if is_referring:
                    result["new_content"] = title_match.group(1).strip()
                    self.logger.info(f"引用消息中的新内容: {result['new_content']}")
                else:
                    # 对于普通卡片消息，避免将card_title重复设为new_content
                    extracted_title = title_match.group(1).strip()
                    if not (result["is_card"] and result["card_title"] == extracted_title):
                        result["new_content"] = extracted_title
                        self.logger.info(f"从title标签提取到用户新消息: {result['new_content']}")
            elif msg.type == 0x01:  # 纯文本消息
                # 检查是否有XML标签，如果没有则视为普通消息
                if not ("<" in msg.content and ">" in msg.content):
                    result["new_content"] = msg.content
                    return result
            
            # 如果是引用消息，处理refermsg部分
            if is_referring:
                result["has_quote"] = True
                
                # 提取refermsg内容
                refer_data = self.extract_refermsg(msg.content)
                result["quoted_sender"] = refer_data.get("sender", "")
                
                # 新增代码开始
                is_quoted_image = False
                quoted_msg_id = None
                quoted_image_extra = None
                
                # 尝试从原始消息内容中解析 refermsg 结构，获取引用类型和svrid
                refermsg_match = re.search(r'<refermsg>(.*?)</refermsg>', msg.content, re.DOTALL)
                if refermsg_match:
                    refermsg_inner_xml = refermsg_match.group(1)
                    refer_type_match = re.search(r'<type>(\d+)</type>', refermsg_inner_xml)
                    refer_svrid_match = re.search(r'<svrid>(\d+)</svrid>', refermsg_inner_xml)
                    
                    if refer_type_match and refer_type_match.group(1) == '3' and refer_svrid_match:
                        # 确认是引用图片 (type=3)
                        is_quoted_image = True
                        try:
                            quoted_msg_id = int(refer_svrid_match.group(1))
                            # refer_data["raw_content"] 应该就是解码后的 <msg><img...> XML
                            quoted_image_extra = refer_data.get("raw_content", "")
                            self.logger.info(f"识别到引用图片消息，原消息ID: {quoted_msg_id}")
                        except ValueError:
                            self.logger.error(f"无法将svrid '{refer_svrid_match.group(1)}' 转换为整数")
                        except Exception as e:
                            self.logger.error(f"提取引用图片信息时出错: {e}")

                if is_quoted_image and quoted_msg_id is not None and quoted_image_extra:
                    # 如果是引用图片，更新 result 字典
                    result["media_type"] = "引用图片"         # 更新媒体类型
                    result["quoted_msg_id"] = quoted_msg_id  # 存储原图片消息 ID
                    result["quoted_image_extra"] = quoted_image_extra # 存储原图片消息 XML (用于下载)
                    result["quoted_content"] = "[引用的图片]" # 使用占位符文本
                    result["quoted_is_card"] = False # 明确不是卡片
                else:
                    # 原有的代码继续
                    result["quoted_content"] = refer_data.get("content", "")
                # 新增代码结束
                
                # 从raw_content尝试解析被引用内容的卡片信息
                raw_content = refer_data.get("raw_content", "")
                if raw_content and "<appmsg" in raw_content and not is_quoted_image: # 添加了 not is_quoted_image 条件
                    quoted_card_details = self.extract_card_details(raw_content)
                    
                    # 将引用的卡片详情存储到quoted_前缀的字段
                    result["quoted_is_card"] = quoted_card_details["is_card"]
                    result["quoted_card_type"] = quoted_card_details["card_type"]
                    result["quoted_card_title"] = quoted_card_details["card_title"]
                    result["quoted_card_description"] = quoted_card_details["card_description"]
                    result["quoted_card_url"] = quoted_card_details["card_url"]
                    result["quoted_card_appname"] = quoted_card_details["card_appname"]
                    result["quoted_card_sourcedisplayname"] = quoted_card_details["card_sourcedisplayname"]
                    
                    # 如果没有提取到有效内容，使用卡片标题作为quoted_content
                    if not result["quoted_content"] and quoted_card_details["card_title"]:
                        result["quoted_content"] = quoted_card_details["card_title"]
                        
                    self.logger.info(f"成功从引用内容中提取卡片信息: {quoted_card_details['card_type']}")
                else:
                    # 如果未发现卡片特征，尝试fallback方法
                    if not result["quoted_content"] and not is_quoted_image: # 添加了 not is_quoted_image 条件
                        fallback_content = self.extract_quoted_fallback(msg.content)
                        if fallback_content:
                            if fallback_content.startswith("引用内容:") or fallback_content.startswith("相关内容:"):
                                result["quoted_content"] = fallback_content.split(":", 1)[1].strip()
                            else:
                                result["quoted_content"] = fallback_content
            
            # 设置媒体类型
            if result["is_card"] and result["card_type"]:
                result["media_type"] = result["card_type"]
            elif is_referring and result["quoted_is_card"]:
                # 如果当前消息是引用，且引用的是卡片，则媒体类型设为"引用消息"
                result["media_type"] = "引用消息"
            else:
                # 普通消息，使用群聊消息类型识别
                result["media_type"] = self.identify_message_type(msg.content)
            
            return result
            
        except Exception as e:
            self.logger.error(f"处理群聊引用消息时出错: {e}")
            return result
    
    def extract_private_quoted_message(self, msg: Any) -> dict:
        """专门处理私聊引用消息，返回结构化数据
        
        Args:
            msg: 微信消息对象
            
        Returns:
            dict: {
                "new_content": "",     # 用户新发送的内容
                "quoted_content": "",  # 引用的内容
                "quoted_sender": "",   # 被引用消息的发送者
                "media_type": "",      # 媒体类型（文本/图片/视频/链接等）
                "has_quote": False,    # 是否包含引用
                "is_card": False,      # 是否为卡片消息
                "card_type": "",       # 卡片类型
                "card_title": "",      # 卡片标题
                "card_description": "", # 卡片描述
                "card_url": "",        # 卡片链接
                "card_appname": "",    # 卡片来源应用
                "card_sourcedisplayname": "", # 来源显示名称
                "quoted_is_card": False,    # 被引用的内容是否为卡片
                "quoted_card_type": "",     # 被引用的卡片类型
                "quoted_card_title": "",    # 被引用的卡片标题
                "quoted_card_description": "", # 被引用的卡片描述
                "quoted_card_url": "",      # 被引用的卡片链接
                "quoted_card_appname": "",  # 被引用的卡片来源应用
                "quoted_card_sourcedisplayname": "" # 被引用的来源显示名称
            }
        """
        result = {
            "new_content": "",
            "quoted_content": "",
            "quoted_sender": "",
            "media_type": "文本",
            "has_quote": False,
            "is_card": False,
            "card_type": "",
            "card_title": "",
            "card_description": "",
            "card_url": "",
            "card_appname": "",
            "card_sourcedisplayname": "",
            "quoted_is_card": False,
            "quoted_card_type": "",
            "quoted_card_title": "",
            "quoted_card_description": "",
            "quoted_card_url": "",
            "quoted_card_appname": "",
            "quoted_card_sourcedisplayname": ""
        }
        
        try:
            # 检查消息类型
            if msg.type != 0x01 and msg.type != 49:  # 普通文本消息或APP消息
                return result
            
            self.logger.info(f"处理私聊消息: 类型={msg.type}, 发送者={msg.sender}")
            
            # 检查是否为引用消息类型 (type 57)
            is_quote_msg = False
            appmsg_type_match = re.search(r'<appmsg.*?type="(\d+)"', msg.content, re.DOTALL)
            if appmsg_type_match and appmsg_type_match.group(1) == "57":
                is_quote_msg = True
                self.logger.info("检测到引用类型消息 (type 57)")
            
            # 检查是否包含refermsg标签
            has_refermsg = "<refermsg>" in msg.content
            
            # 确定是否是引用操作
            is_referring = is_quote_msg or has_refermsg
            
            # 处理App类型消息（类型49）
            if msg.type == 49:
                if not is_referring:
                    # 如果不是引用消息，按普通卡片处理
                    card_details = self.extract_card_details(msg.content)
                    result.update(card_details)
                    
                    # 根据卡片类型更新媒体类型
                    if card_details["is_card"] and card_details["card_type"]:
                        result["media_type"] = card_details["card_type"]
                
                # 引用消息情况下，我们不立即更新result的卡片信息，因为外层appmsg是引用容器
            
            # 处理用户新输入内容
            # 优先检查是否有<title>标签内容
            title_match = re.search(r'<title>(.*?)</title>', msg.content)
            if title_match:
                # 对于引用消息，从title标签提取用户新输入
                if is_referring:
                    result["new_content"] = title_match.group(1).strip()
                    self.logger.info(f"引用消息中的新内容: {result['new_content']}")
                else:
                    # 对于普通卡片消息，避免将card_title重复设为new_content
                    extracted_title = title_match.group(1).strip()
                    if not (result["is_card"] and result["card_title"] == extracted_title):
                        result["new_content"] = extracted_title
                        self.logger.info(f"从title标签提取到用户新消息: {result['new_content']}")
            elif msg.type == 0x01:  # 纯文本消息
                # 检查是否有XML标签，如果没有则视为普通消息
                if not ("<" in msg.content and ">" in msg.content):
                    result["new_content"] = msg.content
                    return result
            
            # 如果是引用消息，处理refermsg部分
            if is_referring:
                result["has_quote"] = True
                
                # 提取refermsg内容
                refer_data = self.extract_private_refermsg(msg.content)
                result["quoted_sender"] = refer_data.get("sender", "")
                
                # 新增代码开始
                is_quoted_image = False
                quoted_msg_id = None
                quoted_image_extra = None
                
                # 尝试从原始消息内容中解析 refermsg 结构，获取引用类型和svrid
                refermsg_match = re.search(r'<refermsg>(.*?)</refermsg>', msg.content, re.DOTALL)
                if refermsg_match:
                    refermsg_inner_xml = refermsg_match.group(1)
                    refer_type_match = re.search(r'<type>(\d+)</type>', refermsg_inner_xml)
                    refer_svrid_match = re.search(r'<svrid>(\d+)</svrid>', refermsg_inner_xml)
                    
                    if refer_type_match and refer_type_match.group(1) == '3' and refer_svrid_match:
                        # 确认是引用图片 (type=3)
                        is_quoted_image = True
                        try:
                            quoted_msg_id = int(refer_svrid_match.group(1))
                            # refer_data["raw_content"] 应该就是解码后的 <msg><img...> XML
                            quoted_image_extra = refer_data.get("raw_content", "")
                            self.logger.info(f"识别到引用图片消息，原消息ID: {quoted_msg_id}")
                        except ValueError:
                            self.logger.error(f"无法将svrid '{refer_svrid_match.group(1)}' 转换为整数")
                        except Exception as e:
                            self.logger.error(f"提取引用图片信息时出错: {e}")

                if is_quoted_image and quoted_msg_id is not None and quoted_image_extra:
                    # 如果是引用图片，更新 result 字典
                    result["media_type"] = "引用图片"         # 更新媒体类型
                    result["quoted_msg_id"] = quoted_msg_id  # 存储原图片消息 ID
                    result["quoted_image_extra"] = quoted_image_extra # 存储原图片消息 XML (用于下载)
                    result["quoted_content"] = "[引用的图片]" # 使用占位符文本
                    result["quoted_is_card"] = False # 明确不是卡片
                else:
                    # 原有的代码继续
                    result["quoted_content"] = refer_data.get("content", "")
                # 新增代码结束
                
                # 从raw_content尝试解析被引用内容的卡片信息
                raw_content = refer_data.get("raw_content", "")
                if raw_content and "<appmsg" in raw_content and not is_quoted_image: # 添加了 not is_quoted_image 条件
                    quoted_card_details = self.extract_card_details(raw_content)
                    
                    # 将引用的卡片详情存储到quoted_前缀的字段
                    result["quoted_is_card"] = quoted_card_details["is_card"]
                    result["quoted_card_type"] = quoted_card_details["card_type"]
                    result["quoted_card_title"] = quoted_card_details["card_title"]
                    result["quoted_card_description"] = quoted_card_details["card_description"]
                    result["quoted_card_url"] = quoted_card_details["card_url"]
                    result["quoted_card_appname"] = quoted_card_details["card_appname"]
                    result["quoted_card_sourcedisplayname"] = quoted_card_details["card_sourcedisplayname"]
                    
                    # 如果没有提取到有效内容，使用卡片标题作为quoted_content
                    if not result["quoted_content"] and quoted_card_details["card_title"]:
                        result["quoted_content"] = quoted_card_details["card_title"]
                        
                    self.logger.info(f"成功从引用内容中提取卡片信息: {quoted_card_details['card_type']}")
                else:
                    # 如果未发现卡片特征，尝试fallback方法
                    if not result["quoted_content"] and not is_quoted_image: # 添加了 not is_quoted_image 条件
                        fallback_content = self.extract_quoted_fallback(msg.content)
                        if fallback_content:
                            if fallback_content.startswith("引用内容:") or fallback_content.startswith("相关内容:"):
                                result["quoted_content"] = fallback_content.split(":", 1)[1].strip()
                            else:
                                result["quoted_content"] = fallback_content
            
            # 设置媒体类型
            if result["is_card"] and result["card_type"]:
                result["media_type"] = result["card_type"]
            elif is_referring and result["quoted_is_card"]:
                # 如果当前消息是引用，且引用的是卡片，则媒体类型设为"引用消息"
                result["media_type"] = "引用消息"
            else:
                # 普通消息，使用私聊消息类型识别
                result["media_type"] = self.identify_private_message_type(msg.content)
            
            return result
            
        except Exception as e:
            self.logger.error(f"处理私聊引用消息时出错: {e}")
            return result
    
    def extract_refermsg(self, content: str) -> dict:
        """专门提取群聊refermsg节点内容，包括HTML解码
        
        Args:
            content: 消息内容
            
        Returns:
            dict: {
                "sender": "",     # 发送者
                "content": "",    # 引用内容
                "raw_content": "" # 解码后的原始XML内容，用于后续解析
            }
        """
        result = {"sender": "", "content": "", "raw_content": ""}
        
        try:
            # 使用正则表达式精确提取refermsg内容，避免完整XML解析
            refermsg_match = re.search(r'<refermsg>(.*?)</refermsg>', content, re.DOTALL)
            if not refermsg_match:
                return result
                
            refermsg_content = refermsg_match.group(1)
            
            # 提取发送者
            displayname_match = re.search(r'<displayname>(.*?)</displayname>', refermsg_content, re.DOTALL)
            if displayname_match:
                result["sender"] = displayname_match.group(1).strip()
            
            # 提取内容并进行HTML解码
            content_match = re.search(r'<content>(.*?)</content>', refermsg_content, re.DOTALL)
            if content_match:
                # 获取引用的原始内容（可能是HTML编码的XML）
                extracted_content = content_match.group(1)
                
                # 保存解码后的原始内容，用于后续解析
                decoded_content = html.unescape(extracted_content)
                result["raw_content"] = decoded_content
                
                # 清理内容中的HTML标签，用于文本展示
                cleaned_content = re.sub(r'<.*?>', '', extracted_content)
                # 清理HTML实体编码和多余空格
                cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
                # 解码HTML实体
                cleaned_content = html.unescape(cleaned_content)
                result["content"] = cleaned_content
                
            return result
            
        except Exception as e:
            self.logger.error(f"提取群聊refermsg内容时出错: {e}")
            return result
    
    def extract_private_refermsg(self, content: str) -> dict:
        """专门提取私聊refermsg节点内容，包括HTML解码
        
        Args:
            content: 消息内容
            
        Returns:
            dict: {
                "sender": "",     # 发送者
                "content": "",    # 引用内容
                "raw_content": "" # 解码后的原始XML内容，用于后续解析
            }
        """
        result = {"sender": "", "content": "", "raw_content": ""}
        
        try:
            # 使用正则表达式精确提取refermsg内容，避免完整XML解析
            refermsg_match = re.search(r'<refermsg>(.*?)</refermsg>', content, re.DOTALL)
            if not refermsg_match:
                return result
                
            refermsg_content = refermsg_match.group(1)
            
            # 提取发送者
            displayname_match = re.search(r'<displayname>(.*?)</displayname>', refermsg_content, re.DOTALL)
            if displayname_match:
                result["sender"] = displayname_match.group(1).strip()
            
            # 提取内容并进行HTML解码
            content_match = re.search(r'<content>(.*?)</content>', refermsg_content, re.DOTALL)
            if content_match:
                # 获取引用的原始内容（可能是HTML编码的XML）
                extracted_content = content_match.group(1)
                
                # 保存解码后的原始内容，用于后续解析
                decoded_content = html.unescape(extracted_content)
                result["raw_content"] = decoded_content
                
                # 清理内容中的HTML标签，用于文本展示
                cleaned_content = re.sub(r'<.*?>', '', extracted_content)
                # 清理HTML实体编码和多余空格
                cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
                # 解码HTML实体
                cleaned_content = html.unescape(cleaned_content)
                result["content"] = cleaned_content
                
            return result
            
        except Exception as e:
            self.logger.error(f"提取私聊refermsg内容时出错: {e}")
            return result
    
    def identify_message_type(self, content: str) -> str:
        """识别群聊消息的媒体类型
        
        Args:
            content: 消息内容
            
        Returns:
            str: 媒体类型描述
        """
        try:
            if "<appmsg type=\"2\"" in content:
                return "图片"
            elif "<appmsg type=\"5\"" in content:
                return "文件"
            elif "<appmsg type=\"4\"" in content:
                return "链接分享"
            elif "<appmsg type=\"3\"" in content:
                return "音频"
            elif "<appmsg type=\"6\"" in content:
                return "视频"
            elif "<appmsg type=\"8\"" in content:
                return "动画表情"
            elif "<appmsg type=\"1\"" in content:
                return "文本卡片"
            elif "<appmsg type=\"7\"" in content:
                return "位置分享"
            elif "<appmsg type=\"17\"" in content:
                return "实时位置分享"
            elif "<appmsg type=\"19\"" in content:
                return "频道消息"
            elif "<appmsg type=\"33\"" in content:
                return "小程序"
            elif "<appmsg type=\"57\"" in content:
                return "引用消息"
            else:
                return "文本"
        except Exception as e:
            self.logger.error(f"识别消息类型时出错: {e}")
            return "文本"
    
    def identify_private_message_type(self, content: str) -> str:
        """识别私聊消息的媒体类型
        
        Args:
            content: 消息内容
            
        Returns:
            str: 媒体类型描述
        """
        try:
            if "<appmsg type=\"2\"" in content:
                return "图片"
            elif "<appmsg type=\"5\"" in content:
                return "文件"
            elif "<appmsg type=\"4\"" in content:
                return "链接分享"
            elif "<appmsg type=\"3\"" in content:
                return "音频"
            elif "<appmsg type=\"6\"" in content:
                return "视频"
            elif "<appmsg type=\"8\"" in content:
                return "动画表情"
            elif "<appmsg type=\"1\"" in content:
                return "文本卡片"
            elif "<appmsg type=\"7\"" in content:
                return "位置分享"
            elif "<appmsg type=\"17\"" in content:
                return "实时位置分享"
            elif "<appmsg type=\"19\"" in content:
                return "频道消息"
            elif "<appmsg type=\"33\"" in content:
                return "小程序"
            elif "<appmsg type=\"57\"" in content:
                return "引用消息"
            else:
                return "文本"
        except Exception as e:
            self.logger.error(f"识别消息类型时出错: {e}")
            return "文本"
    
    def extract_quoted_fallback(self, content: str) -> str:
        """当XML解析失败时的后备提取方法
        
        Args:
            content: 原始消息内容
            
        Returns:
            str: 提取的引用内容，如果未找到返回空字符串
        """
        try:
            # 使用正则表达式直接从内容中提取
            # 查找<content>标签内容
            content_match = re.search(r'<content>(.*?)</content>', content, re.DOTALL)
            if content_match:
                extracted = content_match.group(1)
                # 清理可能存在的XML标签
                extracted = re.sub(r'<.*?>', '', extracted)
                # 去除换行符和多余空格
                extracted = re.sub(r'\s+', ' ', extracted).strip()
                # 解码HTML实体
                extracted = html.unescape(extracted)
                return extracted
                
            # 查找displayname和content的组合
            display_name_match = re.search(r'<displayname>(.*?)</displayname>', content, re.DOTALL)
            content_match = re.search(r'<content>(.*?)</content>', content, re.DOTALL)
            
            if display_name_match and content_match:
                name = re.sub(r'<.*?>', '', display_name_match.group(1))
                text = re.sub(r'<.*?>', '', content_match.group(1))
                # 去除换行符和多余空格
                text = re.sub(r'\s+', ' ', text).strip()
                # 解码HTML实体
                name = html.unescape(name)
                text = html.unescape(text)
                return f"{name}: {text}"
                
            # 查找引用或回复的关键词
            if "引用" in content or "回复" in content:
                # 寻找引用关键词后的内容
                match = re.search(r'[引用|回复].*?[:：](.*?)(?:<|$)', content, re.DOTALL)
                if match:
                    text = match.group(1).strip()
                    text = re.sub(r'<.*?>', '', text)
                    # 去除换行符和多余空格
                    text = re.sub(r'\s+', ' ', text).strip()
                    # 解码HTML实体
                    text = html.unescape(text)
                    return text
            
            return ""
        except Exception as e:
            self.logger.error(f"后备提取引用内容时出错: {e}")
            return ""
    
    def extract_card_details(self, content: str) -> dict:
        """从消息内容中提取卡片详情 (使用 ElementTree 解析)

        Args:
            content: 消息内容 (XML 字符串)

        Returns:
            dict: 包含卡片详情的字典
        """
        result = {
            "is_card": False,
            "card_type": "",
            "card_title": "",
            "card_description": "",
            "card_url": "",
            "card_appname": "",
            "card_sourcedisplayname": ""
        }

        try:
            # 1. 定位并提取 <appmsg> 标签内容
            #    正则表达式用于精确找到 <appmsg>...</appmsg> 部分，避免解析整个消息体可能引入的错误
            appmsg_match = re.search(r'<appmsg.*?>(.*?)</appmsg>', content, re.DOTALL | re.IGNORECASE)
            if not appmsg_match:
                # 有些简单的 appmsg 可能没有闭合标签，尝试匹配自闭合或非标准格式
                appmsg_match_simple = re.search(r'(<appmsg[^>]*>)', content, re.IGNORECASE)
                if not appmsg_match_simple:
                     # 尝试查找 <msg> 下的 <appmsg> 作为根
                     msg_match = re.search(r'<msg>(.*?)</msg>', content, re.DOTALL | re.IGNORECASE)
                     if msg_match:
                         inner_content = msg_match.group(1)
                         try:
                             # 尝试将<msg>内的内容解析为根，然后查找appmsg
                             # 为了容错，添加一个虚拟根标签
                             root = ET.fromstring(f"<root>{inner_content}</root>")
                             appmsg_node = root.find('.//appmsg')
                             if appmsg_node is None:
                                 self.logger.debug("在 <msg> 内未找到 <appmsg> 标签")
                                 return result # 未找到 appmsg，不是标准卡片
                             # 将 Element 对象转回字符串以便后续统一处理（或直接使用 Element对象查找）
                             # 为简化后续流程，我们还是转回字符串交给下面的ET.fromstring处理
                             # 注意：这里需要重新构造 appmsg 标签本身，ET.tostring只包含内容
                             appmsg_xml_str = ET.tostring(appmsg_node, encoding='unicode', method='xml')


                         except ET.ParseError as parse_error:
                             self.logger.debug(f"解析 <msg> 内容时出错: {parse_error}")
                             return result # 解析失败

                     else:
                        self.logger.debug("未找到 <appmsg> 标签")
                        return result # 未找到 appmsg，不是标准卡片
                else:
                    # 对于 <appmsg ... /> 这种简单情况，可能无法提取内部标签，但也标记为卡片
                    appmsg_xml_str = appmsg_match_simple.group(1)
                    result["is_card"] = True # 标记为卡片，即使可能无法提取详细信息
            else:
                # 需要重新包含 <appmsg ...> 标签本身来解析属性
                appmsg_outer_match = re.search(r'(<appmsg[^>]*>).*?</appmsg>', content, re.DOTALL | re.IGNORECASE)
                if not appmsg_outer_match:
                     # 如果上面的正则失败，尝试简单匹配开始标签
                     appmsg_outer_match = re.search(r'(<appmsg[^>]*>)', content, re.IGNORECASE)

                if appmsg_outer_match:
                    appmsg_tag_start = appmsg_outer_match.group(1)
                    appmsg_inner_content = appmsg_match.group(1)
                    appmsg_xml_str = f"{appmsg_tag_start}{appmsg_inner_content}</appmsg>"
                else:
                     self.logger.warning("无法提取完整的 <appmsg> 标签结构")
                     return result # 结构不完整

            # 2. 使用 ElementTree 解析 <appmsg> 内容
            try:
                # 尝试解析提取出的 <appmsg> XML 字符串
                # 使用 XML 而不是 fromstring，因为它对根元素要求更宽松
                appmsg_root = ET.XML(appmsg_xml_str)
                result["is_card"] = True # 解析成功，确认是卡片

                # 3. 提取卡片类型 (来自 <appmsg> 标签的 type 属性)
                card_type_num = appmsg_root.get('type', '') # 安全获取属性
                if card_type_num:
                    result["card_type"] = self.get_card_type_name(card_type_num)
                else:
                     # 尝试从内部 <type> 标签获取 (兼容旧格式或特殊格式)
                     type_node = appmsg_root.find('./type')
                     if type_node is not None and type_node.text:
                         result["card_type"] = self.get_card_type_name(type_node.text.strip())


                # 4. 提取标题 (<title>)
                title = appmsg_root.findtext('./title', default='').strip()
                if title:
                    result["card_title"] = html.unescape(title)

                # 5. 提取描述 (<des>)
                description = appmsg_root.findtext('./des', default='').strip()
                if description:
                    cleaned_desc = re.sub(r'<.*?>', '', description) # 清理HTML标签
                    result["card_description"] = html.unescape(cleaned_desc)

                # 6. 提取链接 (<url>)
                url = appmsg_root.findtext('./url', default='').strip()
                if url:
                    result["card_url"] = html.unescape(url)

                # 7. 提取应用名称 (<appinfo/appname> 或 <sourcedisplayname>)
                # 优先尝试 <appinfo><appname>
                appname_node = appmsg_root.find('./appinfo/appname')
                if appname_node is not None and appname_node.text:
                    appname = appname_node.text.strip()
                    result["card_appname"] = html.unescape(appname)
                # 如果没找到，或者为空，尝试 <sourcedisplayname>
                sourcedisplayname_node = appmsg_root.find('./sourcedisplayname')
                if sourcedisplayname_node is not None and sourcedisplayname_node.text:
                     sourcedisplayname = sourcedisplayname_node.text.strip()
                     result["card_sourcedisplayname"] = html.unescape(sourcedisplayname)
                     # 如果 appname 为空，使用 sourcedisplayname 作为 appname
                     if not result["card_appname"]:
                         result["card_appname"] = result["card_sourcedisplayname"]
                # 兼容直接在 appmsg 下的 appname
                if not result["card_appname"]:
                    appname_direct = appmsg_root.findtext('./appname', default='').strip()
                    if appname_direct:
                         result["card_appname"] = html.unescape(appname_direct)

                # 记录提取结果用于调试
                self.logger.debug(f"ElementTree 解析结果: type={result['card_type']}, title={result['card_title']}, desc_len={len(result['card_description'])}, url_len={len(result['card_url'])}, app={result['card_appname']}, source={result['card_sourcedisplayname']}")

            except ET.ParseError as e:
                self.logger.error(f"使用 ElementTree 解析 <appmsg> 时出错: {e}\nXML 内容片段: {appmsg_xml_str[:500]}...", exc_info=True)
                # 即使解析<appmsg>出错，如果正则找到了<appmsg>，仍然标记为卡片
                if result["is_card"] == False and ('<appmsg' in content or '<msg>' in content):
                     result["is_card"] = True # 基本判断是卡片，但细节提取失败
                     # 尝试用正则提取基础信息作为后备
                     type_match_fallback = re.search(r'<type>(\d+)</type>', content)
                     title_match_fallback = re.search(r'<title>(.*?)</title>', content, re.DOTALL)
                     if type_match_fallback:
                         result["card_type"] = self.get_card_type_name(type_match_fallback.group(1))
                     if title_match_fallback:
                         result["card_title"] = html.unescape(title_match_fallback.group(1).strip())
                     self.logger.warning("ElementTree 解析失败，已尝试正则后备提取基础信息")


        except Exception as e:
            self.logger.error(f"提取卡片详情时发生意外错误: {e}", exc_info=True)
            # 尽量判断是否是卡片
            if not result["is_card"] and ('<appmsg' in content or '<msg>' in content):
                result["is_card"] = True

        return result
    
    def get_card_type_name(self, type_num: str) -> str:
        """根据卡片类型编号获取类型名称
        
        Args:
            type_num: 类型编号
            
        Returns:
            str: 类型名称
        """
        card_types = {
            "1": "文本卡片",
            "2": "图片",
            "3": "音频",
            "4": "视频",
            "5": "链接",
            "6": "文件",
            "7": "位置",
            "8": "表情动画",
            "17": "实时位置",
            "19": "频道消息",
            "33": "小程序",
            "36": "转账",
            "50": "视频号",
            "51": "直播间",
            "57": "引用消息",
            "62": "视频号直播",
            "63": "视频号商品",
            "87": "群收款",
            "88": "语音通话"
        }
        
        return card_types.get(type_num, f"未知类型({type_num})")
    
    def format_message_for_ai(self, msg_data: dict, sender_name: str) -> str:
        """将提取的消息数据格式化为发送给AI的最终文本
        
        Args:
            msg_data: 提取的消息数据
            sender_name: 发送者名称
            
        Returns:
            str: 格式化后的文本
        """
        result = []
        current_time = time.strftime("%H:%M", time.localtime())
        
        # 添加用户新消息
        if msg_data["new_content"]:
            result.append(f"[{current_time}] {sender_name}: {msg_data['new_content']}")
        
        # 处理当前消息的卡片信息（如果不是引用消息而是直接分享的卡片）
        if msg_data["is_card"] and not msg_data["has_quote"]:
            card_info = []
            card_info.append(f"[卡片信息]")
            
            if msg_data["card_type"]:
                card_info.append(f"类型: {msg_data['card_type']}")
            
            if msg_data["card_title"]:
                card_info.append(f"标题: {msg_data['card_title']}")
            
            if msg_data["card_description"]:
                # 如果描述过长，截取一部分
                description = msg_data["card_description"]
                if len(description) > 100:
                    description = description[:97] + "..."
                card_info.append(f"描述: {description}")
            
            if msg_data["card_appname"] or msg_data["card_sourcedisplayname"]:
                source = msg_data["card_appname"] or msg_data["card_sourcedisplayname"]
                card_info.append(f"来源: {source}")
            
            if msg_data["card_url"]:
                # 如果URL过长，截取一部分
                url = msg_data["card_url"]
                if len(url) > 80:
                    url = url[:77] + "..."
                card_info.append(f"链接: {url}")
            
            # 只有当有实质性内容时才添加卡片信息
            if len(card_info) > 1:  # 不只有[卡片信息]这一行
                result.append("\n".join(card_info))
        
        # 添加引用内容（如果有）
        if msg_data["has_quote"]:
            quoted_header = f"[用户引用]"
            if msg_data["quoted_sender"]:
                quoted_header += f" {msg_data['quoted_sender']}"
            
            # 检查被引用内容是否为卡片
            if msg_data["quoted_is_card"]:
                # 格式化被引用的卡片信息
                quoted_info = [quoted_header]
                
                if msg_data["quoted_card_type"]:
                    quoted_info.append(f"类型: {msg_data['quoted_card_type']}")
                
                if msg_data["quoted_card_title"]:
                    quoted_info.append(f"标题: {msg_data['quoted_card_title']}")
                
                if msg_data["quoted_card_description"]:
                    # 如果描述过长，截取一部分
                    description = msg_data["quoted_card_description"]
                    if len(description) > 100:
                        description = description[:97] + "..."
                    quoted_info.append(f"描述: {description}")
                
                if msg_data["quoted_card_appname"] or msg_data["quoted_card_sourcedisplayname"]:
                    source = msg_data["quoted_card_appname"] or msg_data["quoted_card_sourcedisplayname"]
                    quoted_info.append(f"来源: {source}")
                
                if msg_data["quoted_card_url"]:
                    # 如果URL过长，截取一部分
                    url = msg_data["quoted_card_url"]
                    if len(url) > 80:
                        url = url[:77] + "..."
                    quoted_info.append(f"链接: {url}")
                
                result.append("\n".join(quoted_info))
            elif msg_data["quoted_content"]:
                # 如果是普通文本引用
                result.append(f"{quoted_header}: {msg_data['quoted_content']}")
        
        # 如果没有任何内容，但有媒体类型，添加基本信息
        if not result and msg_data["media_type"] and msg_data["media_type"] != "文本":
            result.append(f"[{current_time}] {sender_name} 发送了 [{msg_data['media_type']}]")
        
        # 如果完全没有内容，返回一个默认消息
        if not result:
            result.append(f"[{current_time}] {sender_name} 发送了消息")
        
        return "\n\n".join(result) 