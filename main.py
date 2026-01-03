from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
from astrbot.api.message_components import Node, Plain, Image
import astrbot.api.message_components as Comp
import urllib.request
import urllib.parse
import json
import random
import asyncio
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.core import FileTokenService
from datetime import datetime

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
class MiaoPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config


        self.bot_instance = None

        self.scheduler = AsyncIOScheduler()
        self.scheduler.configure({"apscheduler.timezone": "Asia/Shanghai"})



    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # 先设置任务
        self.投递任务()
        # 然后才启动调度器
        self.scheduler.start()
        logger.info("[Miao] APScheduler 定时任务")


    #定义每分钟的任务  
    # async def 每分任务(self):
    #    current_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    #    logger.info(f"{current_time} 一分钟 执行间隔任务")

   
       # 定义一个每天任务    
    async def 每天任务(self, job=None):
        try:
            bot = self.bot_instance
            if bot is None:
                logger.error("[Miao] bot_instance 未找到")
                return

            group_list = await bot.get_group_list()
        
            if not group_list:
                logger.error("未找到任何群组")
                return
        
            out = f"📋 打卡结果（共 {len(group_list)} 个群组）:\n"
            success_count = 0
            fail_count = 0
        
            for group in group_list:
                group_id = group['group_id']
                group_name = group['group_name']
            
                try:
                    await bot.api.call_action(
                        'send_group_sign',
                        group_id=str(group_id)
                    )
                    out += f"✅ 群号: {group_id}, 群名: {group_name}\n"
                    success_count += 1
                
                except Exception as e:
                    error_msg = str(e)
                    out += f"❌ 群号: {group_id}, 群名: {group_name}\n   原因: {error_msg}\n"
                    fail_count += 1
        
            # 添加统计信息
            out += f"\n📊 统计：成功 {success_count} 个，失败 {fail_count} 个"
        
            # 发送给管理员
            qq_value = self.config.get("Master", 0)
            if qq_value != 0:
                try:
                    # 如果消息太长，进行截断
                    if len(out) > 4000:
                        out = out[:3900] + "\n...（消息过长已截断）"
                    
                    await bot.api.call_action(
                        'send_private_msg',
                        user_id=str(qq_value),
                        message=out
                    )
                    logger.info(f"[打卡] 已发送通知给管理员 {qq_value}")
                except Exception as e:
                    logger.error(f"[打卡] 发送通知失败: {e}")
        except Exception as e:
            logger.error(f"[打卡] 处理出错: {e}")




    def 投递任务(self):

        # self.scheduler.add_job(
        #     self.每分任务,
        #     'interval',
        #     minutes=1,
        #     id="每分任务"
        # )
        # logger.info("添加[每分任务]定时任务")

        self.scheduler.add_job(
            self.每天任务,
            'cron',
            hour=0,
            minute=0,
            id="每天任务",
        )
        logger.info("添加[每天任务]定时任务")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=999)
    async def _capture_bot_instance(self, event: AstrMessageEvent):
        """捕获机器人实例和管理员ID"""
        if self.bot_instance is None and event.get_platform_name() == "aiocqhttp":
            try:
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                if isinstance(event, AiocqhttpMessageEvent):
                    self.bot_instance = event.bot
                    self.platform_name = "aiocqhttp"
                    logger.info(f"[Miao] 成功捕获 aiocqhttp 机器人实例")
            except ImportError:
                logger.warning(f"[Miao] 无法导入 AiocqhttpMessageEvent")

         # 捕获管理员ID
        # if self.admin_user_id is None and event.is_admin():
        #     self.admin_user_id = event.get_sender_id()
        #     self._save_data()
        #     logger.info(f"[GroupSignin] 已记录管理员ID: {self.admin_user_id}")


    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    # @filter.command("helloworld")
    # async def helloworld(self, event: AstrMessageEvent):
    #     """这是一个 hello world 指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
    #     user_name = event.get_sender_name()
    #     message_str = event.message_str # 用户发的纯文本消息字符串
    #     message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
    #     logger.info(message_chain)
    #     yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!") # 发送一条纯文本消息
    
    async def _execute_like_for_user(self, client, user_id: str) -> tuple[int, str]:
        # 点赞数到达上限回复
        limit_responses = [
            "今天给{username}的赞已达上限",
            "赞了那么多还不够吗？",
            "{username}别太贪心哟~",
            "今天赞过啦！",
            "今天已经赞过啦~",
            "已经赞过啦~",
            "还想要赞？不给了！",
            "已经赞过啦，别再点啦！",
            "今日赞力已耗尽，明天再来吧~",
            "{username}今天已经收获满满啦！",
            "赞力不足，请明日再战！",
            "今日点赞任务已完成✓",
            "赞力恢复中，请稍后再试",
            "今日份的赞已经给{username}啦",
            "赞力有限，明天继续哦~",
            "{username}今天已经被赞爆啦！",
            "赞力CD中，请耐心等待",
            "今日点赞额度已用完",
            "赞力值归零，需要重新充能",
            "{username}今天太受欢迎啦！",
            "赞力过载，系统保护启动",
            "今日点赞成就已达成！",
        ]
        """执行单个用户的点赞逻辑 - 核心点赞函数"""
        total_likes = 0
        error_reply = ""
        remaining_likes = 60
        
        while remaining_likes > 0:
            try:
                like_times = min(10, remaining_likes)
                await client.send_like(user_id=int(user_id), times=like_times)
                total_likes += like_times
                remaining_likes -= like_times
                await asyncio.sleep(1)  # 每次调用后适当休眠
                
            except Exception as e:
                error_message = str(e)
                if "已达" in error_message:
                    error_reply = random.choice(limit_responses)
                elif "权限" in error_message:
                    error_reply = "点赞权限受限，你好像没开陌生人点赞"
                else:
                    error_reply = f"点赞失败: {error_message}"
                break

        return total_likes, error_reply

    async def _like_single_user(self, client, user_id: str, username: str = "未知用户") -> str:
        """给单个用户点赞 - 复用核心逻辑"""
        success_responses = [
            "👍{total_likes}",
            "赞了赞了",
            "点赞成功！",
            "给{username}点了{total_likes}个赞",
            "赞送出去啦！一共{total_likes}个哦！",
            "为{username}点赞成功！总共{total_likes}个！",
            "点了{total_likes}个，快查收吧！",
            "赞已送达，请注意查收~ 一共{total_likes}个！",
            "给{username}点了{total_likes}个赞，记得回赞哟！",
            "赞了{total_likes}次，看看收到没？",
            "点了{total_likes}赞，没收到可能是我被风控了",
            "✨ {total_likes}个赞已到账，请查收~",
            "叮咚！{total_likes}个赞已送达{username}",
            "赞力全开！给{username}送了{total_likes}个赞",
            "biu~ {total_likes}个赞发射成功！",
            "{username}的赞+{total_likes}，声望提升！",
            "赞赞赞！一口气点了{total_likes}个",
            "今日份的{total_likes}个赞已安排~",
            "赞不完，根本赞不完！又点了{total_likes}个",
            "赞气满满！{total_likes}个赞请收好",
            "赞力觉醒！给{username}狂点{total_likes}个赞",
            "赞到成功！{total_likes}个赞已送达",
            "赞不绝口！又给{username}点了{total_likes}个",
            "赞力爆棚！今日{total_likes}个赞已送出",
        ]
        total_likes, error_reply = await self._execute_like_for_user(client, user_id)
        
        if total_likes > 0:
            reply = random.choice(success_responses)
            if "{username}" in reply:
                reply = reply.replace("{username}", username)
            if "{total_likes}" in reply:
                reply = reply.replace("{total_likes}", str(total_likes))
            return reply
        elif error_reply:
            if "{username}" in error_reply:
                error_reply = error_reply.replace("{username}", username)
            return error_reply
        
        return "点赞失败"
   
    @filter.regex(r"^赞我$")
    async def like_me_public(self, event: AstrMessageEvent):
        """赞我功能 - 任何人都可以使用，不需要加好友"""
        sender_id = event.get_sender_id()
        client = event.bot
        
        try:
            user_info = await client.get_stranger_info(user_id=int(sender_id))
            username = user_info.get("nickname", "未知用户")
        except Exception:
            username = "未知用户"
        
        result = await self._like_single_user(client, sender_id, username)
        
        # 简化回复，只保留点赞结果
        yield event.plain_result(result)


    @filter.regex(r"^打卡$")
    async def 打卡(self, event: AstrMessageEvent):
        """测试机器人的打卡"""
        try:
            bot = self.bot_instance
            group_list = await bot.get_group_list()
        
            if not group_list:
                logger.error("未找到任何群组")
                return
        
            # 初始化输出
            out = f"📋 打卡结果（共 {len(group_list)} 个群组）:\n\n"
            success_count = 0
            fail_count = 0
        
            for group in group_list:
                group_id = group['group_id']
                group_name = group['group_name']
            
                try:
                    await bot.api.call_action(
                        'send_group_sign',
                        group_id=str(group_id)
                    )
                    out += f"✅ 群号: {group_id}, 群名: {group_name}\n"
                    success_count += 1
                
                except Exception as e:
                    error_msg = str(e)
                    out += f"❌ 群号: {group_id}, 群名: {group_name}\n   原因: {error_msg}\n"
                    fail_count += 1
        
            # 添加统计信息
            out += f"\n📊 统计：成功 {success_count} 个，失败 {fail_count} 个"
        
            # 发送给管理员
            qq_value = self.config.get("Master", 0)
            if qq_value != 0:
                try:
                    # 如果消息太长，进行截断
                    if len(out) > 4000:
                        out = out[:3900] + "\n...（消息过长已截断）"
                    
                    await bot.api.call_action(
                        'send_private_msg',
                        user_id=str(qq_value),
                        message=out
                    )
                    logger.info(f"[打卡] 已发送通知给管理员 {qq_value}")
                except Exception as e:
                    logger.error(f"[打卡] 发送通知失败: {e}")
        except Exception as e:
            logger.error(f"[打卡] 处理出错: {e}")

    @filter.regex(r'(?=.*胡桃)(?=.*http)')
    async def Hutao(self, event: AstrMessageEvent):
        """检测到胡桃链接回复""" 
        qq_value = self.config.get("HuTao_config",0)
        if qq_value !=0:
            chain = [
                Comp.At(qq=qq_value),
                Comp.Plain("发现胡桃链接,嗷~"),
            ]
            yield event.chain_result(chain)

    @filter.command("前瞻兑换码")
    async def 前瞻兑换码(self, event: AstrMessageEvent, Gamename:str):
        """格式：前瞻兑换码 游戏名""" 
        if Gamename:
            code ,cover = get_qianzhanduihuanma(Gamename)
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
        else:
            yield event.plain_result("参数不足！正确格式：前瞻兑换码 游戏名")
        
    @filter.command("伪造聊天记录")#伪造聊天记录 2824779102 喵帕斯 123
    async def 伪造聊天记录(self, event: AstrMessageEvent, QQ:int, Nice:str, txt:str):
        """格式：伪造聊天记录 QQ号 昵称 内容""" 
        if QQ!=2824779102:
            if Nice:
                if txt:
                    node = Node(
                        uin=QQ,
                        name=Nice,
                        content=[
                            Plain(txt)
                        ]
                    )
                    yield event.chain_result([node])
            else:
                yield event.plain_result("参数不足！正确格式：伪造聊天记录 QQ号 昵称 内容")
        else:
            yield event.plain_result("不能伪造这个QQ号的聊天记录")


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        if self.scheduler.running:
            self.scheduler.shutdown()
        logger.info(f"[Miao] 插件已卸载")
