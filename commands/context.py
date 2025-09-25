import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class MessageContext:
    """
    消息上下文，封装消息及其处理所需的所有信息
    """
    # 原始参数
    msg: Any                   # 原始 WxMsg 对象
    wcf: Any                   # Wcf 实例，方便 handler 调用 API
    config: Any                # Config 实例，方便 handler 读取配置
    all_contacts: Dict[str, str]   # 所有联系人信息
    robot_wxid: str            # 机器人自身的 wxid
    robot: Any = None          # Robot 实例，用于访问其方法和属性
    logger: Any = None         # 日志记录器

    # 预处理字段
    text: str = ""             # 预处理后的纯文本消息 (去@, 去空格)
    is_group: bool = False     # 是否群聊消息
    is_at_bot: bool = False    # 是否在群聊中 @ 了机器人
    sender_name: str = "未知用户" # 发送者昵称 (群内或私聊)
    
    # 懒加载字段
    _room_members: Optional[Dict[str, str]] = field(default=None, init=False, repr=False)

    @property
    def room_members(self) -> Dict[str, str]:
        """获取群成员列表 (仅群聊有效，懒加载)"""
        if not self.is_group:
            return {}
        if self._room_members is None:
            try:
                self._room_members = self.wcf.get_chatroom_members(self.msg.roomid)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"获取群 {self.msg.roomid} 成员失败: {e}")
                else:
                    print(f"获取群 {self.msg.roomid} 成员失败: {e}")
                self._room_members = {}  # 出错时返回空字典
        return self._room_members

    def get_sender_alias_or_name(self) -> str:
        """获取发送者在群里的昵称，如果获取失败或私聊，则返回其微信昵称"""
        if self.is_group:
            try:
                # 尝试获取群昵称
                alias = self.wcf.get_alias_in_chatroom(self.msg.sender, self.msg.roomid)
                if alias and alias.strip():
                    return alias
            except Exception as e:
                if self.logger:
                    self.logger.error(f"获取群 {self.msg.roomid} 成员 {self.msg.sender} 昵称失败: {e}")
                else:
                    print(f"获取群 {self.msg.roomid} 成员 {self.msg.sender} 昵称失败: {e}")
        
        # 群昵称获取失败或私聊，返回通讯录昵称
        return self.all_contacts.get(self.msg.sender, self.msg.sender)  # 兜底返回 wxid
    
    def get_receiver(self) -> str:
        """获取应答接收者ID (群聊返回群ID，私聊返回用户ID)"""
        return self.msg.roomid if self.is_group else self.msg.sender
    
    def send_text(self, content: str, at_list: str = "", record_message: bool = True) -> bool:
        """
        发送文本消息
        :param content: 消息内容
        :param at_list: 要@的用户列表，多个用逗号分隔
        :param record_message: 是否将消息记录到数据库
        :return: 是否发送成功
        """
        if self.robot and hasattr(self.robot, "sendTextMsg"):
            receiver = self.get_receiver()
            try:
                self.robot.sendTextMsg(content, receiver, at_list, record_message=record_message)
                return True
            except Exception as e:
                if self.logger:
                    self.logger.error(f"发送消息失败: {e}")
                else:
                    print(f"发送消息失败: {e}")
                return False
        else:
            if self.logger:
                self.logger.error("Robot实例不存在或没有sendTextMsg方法")
            else:
                print("Robot实例不存在或没有sendTextMsg方法")
            return False
