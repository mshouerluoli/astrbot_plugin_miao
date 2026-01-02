from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
from astrbot.api.message_components import Node, Plain, Image
import astrbot.api.message_components as Comp
import urllib.request
import urllib.parse
import json

import re

def get_badge_text(item,a:str):
    """安全地从 item 中提取 badge_text"""
    try:
        return item.get('modules', {}).get('module_dynamic', {}).get('major', {}).get('archive', {}).get(a)
    except AttributeError:
        return None

def get_qianzhanduihuanma(gamename:str):
    url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space/search?host_mid=431073645&page=1&offset=&keyword=%E5%89%8D%E7%9E%BB"
    try:
        # 发送请求
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36')
        with urllib.request.urlopen(req) as response:
            data = response.read().decode('utf-8')
            json_data = json.loads(data)
            badge_text = None
            cover_url = None
            if json_data.get('data') and json_data['data'].get('items'):
                items_list = json_data['data']['items']
                if items_list:
                    for item in items_list:
                        title = get_badge_text(item,"title")
                        pattern = r'(?=.*)' + gamename
                        if re.search(pattern, title, re.DOTALL):
                            badge_text=get_badge_text(item,"desc")
                            cover_url=get_badge_text(item,"cover")
                            break


            
            if badge_text:
                return badge_text,cover_url
            else:
                return None, None
                
    except urllib.error.URLError as e:
       return None, None
    except json.JSONDecodeError as e:
        return None, None
    except Exception as e:
        return None, None



@register("astrbot_plugin_miao", "miao", "AstrBot 插件示例", "v0.0.7")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config


    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    # @filter.command("helloworld")
    # async def helloworld(self, event: AstrMessageEvent):
    #     """这是一个 hello world 指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
    #     user_name = event.get_sender_name()
    #     message_str = event.message_str # 用户发的纯文本消息字符串
    #     message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
    #     logger.info(message_chain)
    #     yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!") # 发送一条纯文本消息
    


    #event.get_sender_id() = QQ号
    #群和私聊都可以触发该指令 引用回复
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.QQOFFICIAL)
    async def on_aiocqhttp(self, event: AstrMessageEvent):
        '''只接收 AIOCQHTTP 和 QQOFFICIAL 的消息'''
        message_str = event.message_str
        
        pattern = r'(?=.*胡桃)(?=.*http)'
        if re.search(pattern, message_str, re.DOTALL):
            qq_value = self.config.get("HuTao_config",0)
            if qq_value !=0:
                chain = [
                    Comp.At(qq=qq_value),
                    Comp.Plain("发现胡桃链接,嗷~"),
                ]
                yield event.chain_result(chain)


        game_pattern = r"^(.*?)前瞻兑换码"
        game_match = re.search(game_pattern, message_str)
        if game_match:
            game_name = game_match.group(1)
            code ,cover = get_qianzhanduihuanma(game_name)
            if code:
                    lines = code.rstrip().split('\n')
                    lines[-1] = "By 你的影月月" #替换最后一行的url
                    code = '\n'.join(lines)
                    chain = [
                        Comp.Image.fromURL(cover), # 从 URL 发送图片
                        Comp.Plain(code)
                    ]
                    yield event.chain_result(chain)
            else:
                yield event.plain_result("获取前瞻兑换码失败，请稍后再试。")
            return




        result = message_str.split()
        if len(result) >= 2 and result[0] == "伪造聊天记录":
            if result[1] != "2824779102":
                if len(result) >= 4:
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
                    yield event.plain_result("参数不足！正确格式：伪造聊天记录 QQ号 昵称 内容")
            else:
                yield event.plain_result("不能伪造这个QQ号的聊天记录")


        



    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
