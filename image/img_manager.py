import logging
import os
import random
import shutil
import time
from wcferry import Wcf
from configuration import Config
from image import AliyunImage


class ImageGenerationManager:
    """图像生成管理器
    封装所有图像生成服务和相关功能的管理类，使主程序代码更简洁。
    """
    
    def __init__(self, config: Config, wcf: Wcf, logger: logging.Logger, send_text_callback: callable):
        """
        初始化图像生成管理器。

        Args:
            config: 配置对象
            wcf: Wcf 实例，用于发送图片
            logger: 日志记录器
            send_text_callback: 发送文本消息的回调函数 (如 Robot.sendTextMsg)
        """
        self.config = config
        self.wcf = wcf
        self.LOG = logger
        self.send_text = send_text_callback
        
        # 初始化图像生成服务
        self.aliyun_image = None
        
        self.LOG.info("开始初始化图像生成服务...")
        
        # 初始化AliyunImage服务
        if hasattr(self.config, 'ALIYUN_IMAGE') and self.config.ALIYUN_IMAGE.get('enable', False):
            try:
                self.aliyun_image = AliyunImage(self.config.ALIYUN_IMAGE)
                self.LOG.info("阿里Aliyun功能已初始化")
            except Exception as e:
                self.LOG.error(f"初始化阿里云文生图服务失败: {str(e)}")
    
    def handle_image_generation(self, service_type, prompt, receiver, at_user=None):
        """处理图像生成请求的通用函数
        :param service_type: 服务类型，当前支持 'aliyun'
        :param prompt: 图像生成提示词
        :param receiver: 接收者ID
        :param at_user: 被@的用户ID，用于群聊
        :return: 处理状态，True成功，False失败
        """
        if service_type == 'aliyun':
            if not self.aliyun_image or not hasattr(self.config, 'ALIYUN_IMAGE') or not self.config.ALIYUN_IMAGE.get('enable', False):
                self.LOG.info(f"收到阿里文生图请求但功能未启用: {prompt}")
                fallback_to_chat = self.config.ALIYUN_IMAGE.get('fallback_to_chat', False) if hasattr(self.config, 'ALIYUN_IMAGE') else False
                if not fallback_to_chat:
                    self.send_text("报一丝，阿里文生图功能没有开启，请联系管理员开启此功能。（可以贿赂他开启）", receiver, at_user)
                    return True
                return False
            service = self.aliyun_image
            model_type = self.config.ALIYUN_IMAGE.get('model', '')
            if model_type == 'wanx2.1-t2i-plus':
                wait_message = "当前模型为阿里PLUS模型，生成速度较慢，请耐心等候..."
            elif model_type == 'wanx-v1':
                wait_message = "当前模型为阿里V1模型，生成速度非常慢，可能需要等待较长时间，请耐心等候..."
            else:
                wait_message = "正在生成图像，请稍等..."
        else:
            self.LOG.error(f"未知的图像生成服务类型: {service_type}")
            return False
            
        self.LOG.info(f"收到图像生成请求 [{service_type}]: {prompt}")
        self.send_text(wait_message, receiver, at_user)
        
        image_url = service.generate_image(prompt)

        if image_url and (image_url.startswith("http") or os.path.exists(image_url)):
            try:
                self.LOG.info(f"开始处理图片: {image_url}")
                image_path = service.download_image(image_url)
                
                if image_path:
                    # 创建一个临时副本，避免文件占用问题
                    temp_dir = os.path.dirname(image_path)
                    file_ext = os.path.splitext(image_path)[1]
                    temp_copy = os.path.join(
                        temp_dir,
                        f"temp_{service_type}_{int(time.time())}_{random.randint(1000, 9999)}{file_ext}"
                    )
                    
                    try:
                        # 创建文件副本
                        shutil.copy2(image_path, temp_copy)
                        self.LOG.info(f"创建临时副本: {temp_copy}")
                        
                        # 发送临时副本
                        self.LOG.info(f"发送图片到 {receiver}: {temp_copy}")
                        self.wcf.send_image(temp_copy, receiver)
                        
                        # 等待一小段时间确保微信API完成处理
                        time.sleep(1.5)
                        
                    except Exception as e:
                        self.LOG.error(f"创建或发送临时副本失败: {str(e)}")
                        # 如果副本处理失败，尝试直接发送原图
                        self.LOG.info(f"尝试直接发送原图: {image_path}")
                        self.wcf.send_image(image_path, receiver)
                    
                    # 安全删除文件
                    self._safe_delete_file(image_path)
                    if os.path.exists(temp_copy):
                        self._safe_delete_file(temp_copy)
                               
                else:
                    self.LOG.warning(f"图片下载失败，发送URL链接作为备用: {image_url}")
                    self.send_text(f"图像已生成，但无法自动显示，点链接也能查看:\n{image_url}", receiver, at_user)
            except Exception as e:
                self.LOG.error(f"发送图片过程出错: {str(e)}")
                self.send_text(f"图像已生成，但发送过程出错，点链接也能查看:\n{image_url}", receiver, at_user)
        else:
            self.LOG.error(f"图像生成失败: {image_url}")
            self.send_text(f"图像生成失败: {image_url}", receiver, at_user)
        
        return True

    def _safe_delete_file(self, file_path, max_retries=3, retry_delay=1.0):
        """安全删除文件，带有重试机制
        
        :param file_path: 要删除的文件路径
        :param max_retries: 最大重试次数
        :param retry_delay: 重试间隔(秒)
        :return: 是否成功删除
        """
        if not os.path.exists(file_path):
            return True
            
        for attempt in range(max_retries):
            try:
                os.remove(file_path)
                self.LOG.info(f"成功删除文件: {file_path}")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    self.LOG.warning(f"删除文件 {file_path} 失败, 将在 {retry_delay} 秒后重试: {str(e)}")
                    time.sleep(retry_delay)
                else:
                    self.LOG.error(f"无法删除文件 {file_path} 经过 {max_retries} 次尝试: {str(e)}")
        
        return False 
