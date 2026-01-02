from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Node, Plain, Image
import astrbot.api.message_components as Comp
import re


@register("astrbot_plugin_miao", "miao", "AstrBot 插件示例", "v0.0.7")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        """这是一个 hello world 指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!") # 发送一条纯文本消息
    



    #event.get_sender_id() = QQ号
    #群和私聊都可以触发该指令 引用回复
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.QQOFFICIAL)
    async def on_aiocqhttp(self, event: AstrMessageEvent):
        '''只接收 AIOCQHTTP 和 QQOFFICIAL 的消息'''
        message_str = event.message_str

        pattern = r'(?=.*胡桃)(?=.*http)'
        if re.search(pattern, message_str, re.DOTALL):
            chain = [
                Comp.At(qq=1969207693),
                Comp.Plain(" 发现胡桃链接,嗷~"),
            ]
            yield event.chain_result(chain)
            #yield event.plain_result(f"发现胡桃链接,嗷~ {event.get_sender_id()}")




        result = message_str.split()
        # 判断数组数量是否大于等于2（索引0和1都需要存在）
        if len(result) >= 2 and result[0] == "伪造聊天记录":
            if result[1] != "2824779102":
                # 确保有足够的数据来构建node
                if len(result) >= 4:
                    # 合并第4个及之后的内容作为聊天内容（因为内容可能有空格）
                    content = ' '.join(result[3:])
                    node = Node(
                        uin=result[1],
                        name=result[2],
                        content=[
                            Plain(content)
                        ]
                    )
                    yield event.chain_result([node])
                else:
                    # 参数不足时的提示
                    yield event.plain_result("参数不足！正确格式：伪造聊天记录 QQ号 昵称 内容")
            else:
                # 如果QQ号等于2824779102的情况
                yield event.plain_result("不能伪造这个QQ号的聊天记录")


        



    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
