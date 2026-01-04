from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage
import astrbot.api.message_components as Comp
import urllib.request
import urllib.parse
import json
import random
import asyncio
import re
import os
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.core import FileTokenService
from datetime import datetime
from astrbot.core.message.components import Record, File
from typing import Optional, Dict, Any
import tempfile
import wave
from pydub import AudioSegment


def get_badge_text(item,a:str):
    """安全地从 item 中提取 badge_text"""
    try:
        return item.get('modules', {}).get('module_dynamic', {}).get('major', {}).get('archive', {}).get(a)
    except AttributeError:
        return None

async def get_preview_redeem_code(gamename: str):
    """Fetch preview redeem code and cover URL for a game from Bilibili asynchronously.

    Returns a tuple (desc, cover_url) or (None, None) on failure.
    """
    url = (
        "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space/search"
        "?host_mid=431073645&page=1&offset=&keyword=%E5%89%8D%E7%9E%BB"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36"
        )
    }

    retries = 3
    timeout_seconds = 8

    escaped = re.escape(gamename)

    for attempt in range(1, retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(f"[get_preview_redeem_code] HTTP {resp.status} (attempt {attempt})")
                        continue
                    text = await resp.text()
                    try:
                        json_data = json.loads(text)
                    except Exception as e:
                        logger.warning(f"[get_preview_redeem_code] JSON parse error: {e}")
                        return None, None

                    items_list = json_data.get("data", {}).get("items", []) or []
                    for item in items_list:
                        title = get_badge_text(item, "title") or ""
                        if re.search(escaped, title, re.IGNORECASE):
                            desc = get_badge_text(item, "desc")
                            cover = get_badge_text(item, "cover")
                            return desc, cover
                    return None, None

        except asyncio.TimeoutError:
            logger.warning(f"[get_preview_redeem_code] timeout (attempt {attempt})")
            await asyncio.sleep(0.5 * attempt)
            continue
        except Exception as e:
            logger.exception(f"[get_preview_redeem_code] request failed: {e}")
            await asyncio.sleep(0.5 * attempt)
            continue

    return None, None

async def tts(
    text: str,
    speaker: str = "派蒙",
    length: float = 1.0,
    noise: float = 0.667,
    noisew: float = 0.8
) -> str:
    """异步TTS函数，自动生成临时WAV文件并返回完整路径"""
    api_url = "http://117.72.170.58:8881/api/"
    params = {
        "text": text,
        "speaker": speaker,
        "length": str(length),
        "noise": str(noise),
        "noisew": str(noisew),
    }
    result = {}
    
    try:
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url, params=params) as response:
                response_text = await response.text()
                try:
                    response_data = json.loads(response_text)
                    code = response_data.get("code", 500)
                    result["code"] = code
                    if code == 200:
                        data = response_data.get("data", {})
                        if isinstance(data, dict):
                            url = data.get("url")
                            if url:
                                result["url"] = url
                                result["msg"] = "生成成功"
                            else:
                                result["msg"] = "响应数据中没有找到URL"
                                result["code"] = 500
                        else:
                            result["msg"] = "响应数据格式错误"
                            result["code"] = 500
                    else:
                        result["msg"] = response_data.get("msg", "未知错误")
                        if "exec_time" in response_data:
                            result["exec_time"] = response_data["exec_time"]
                            
                except json.JSONDecodeError:
                    result["code"] = 500
                    result["msg"] = f"响应不是有效的JSON格式: {response_text[:100]}"
                    
    except aiohttp.ClientError as e:
        result["code"] = 500
        result["msg"] = f"网络请求错误: {e}"
    except asyncio.TimeoutError:
        result["code"] = 408
        result["msg"] = "请求超时"
    except Exception as e:
        result["code"] = 500
        result["msg"] = f"其他错误: {e}"
    
    return result



async def fetch_gacha_pool():
    """获取原神祈愿池数据"""
    url = "https://api.suyanw.cn/api/mihoyo_ys_pool.php"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 检查返回状态
                    if data.get("code") == 1:
                        activities = data.get("data", [])
                        return activities

                    else:
                        logger.info(f"API返回错误: {data.get('text')}")
                        return []
                else:
                    logger.info(f"HTTP请求失败，状态码: {response.status}")
                    return []
                    
    except aiohttp.ClientError as e:
        logger.info(f"网络请求错误: {e}")
        return []
    except asyncio.TimeoutError:
        logger.info("请求超时")
        return []
    except json.JSONDecodeError as e:
        logger.info(f"JSON解析错误: {e}")
        return []
    except Exception as e:
        logger.info(f"其他错误: {e}")
        return []


@register("astrbot_plugin_miao", "miao", "一个轻量 AstrBot 插件，支持每日群打卡与批量点赞、抓取前瞻兑换码并附图、生成演示聊天节点以及检测“胡桃 + 链接”并提醒管理员。", "v0.0.7")
class MiaoPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.bot_instance = None


        self.scheduler = AsyncIOScheduler()
        self.scheduler.configure({"apscheduler.timezone": "Asia/Shanghai"})


        logger.info(f"[Miao] bot_instance{self.bot_instance}")


    async def is_Master(self,QQ_:int):
        qq_value = self.config.get("Master", 0)
        return QQ_ == qq_value

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        self.schedule_jobs()
        self.scheduler.start()
        logger.info("[Miao] APScheduler 定时任务")


    #定义每分钟的任务  
    # async def 每分任务(self):
    #    current_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    #    logger.info(f"{current_time} 一分钟 执行间隔任务")

    async def checkin_task(self):
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
            out += f"📊 统计：成功 {success_count} 个，失败 {fail_count} 个"
        
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
 
    async def like_task(self):
        try:
            send_like_list = self.config.get("send_like_list", [])
            bot = self.bot_instance
            if bot is None:
                logger.error("[Miao] bot_instance 未找到")
                return

            if not send_like_list:
                logger.warning("[点赞] 没有配置需要点赞的QQ号")
                return
        
            out = f"❤️ 自动点赞结果（共 {len(send_like_list)} 个用户）:\n"
            success_count = 0
            fail_count = 0
        
            for qq in send_like_list:
                try:
                    user_info = await bot.get_stranger_info(user_id=int(qq))
                    username = user_info.get("nickname", "未知用户")
                except Exception:
                    username = "未知用户"
        
                try:
                    # 假设 _like_single_user 返回 (success, message) 格式
                    message = await self._like_single_user(bot, qq, username)
                    out += f"✅ QQ: {qq}, 昵称: {username}\n"
                    success_count += 1
                except Exception as e:
                    error_msg = str(e)
                    out += f"❌ QQ: {qq}, 昵称: {username}\n   原因: {error_msg}\n"
                    fail_count += 1
        
            # 添加统计信息
            out += f"📊 统计：成功 {success_count} 个，失败 {fail_count} 个"
        
            # 发送给管理员
            master_qq = self.config.get("Master", 0)
            if master_qq != 0:
                try:
                    # 如果消息太长，进行截断
                    if len(out) > 4000:
                        out = out[:3900] + "\n...（消息过长已截断）"
                    
                    await bot.api.call_action(
                        'send_private_msg',
                        user_id=str(master_qq),
                        message=out
                    )
                    logger.info(f"[点赞] 已发送通知给管理员 {master_qq}")
                except Exception as e:
                    logger.error(f"[点赞] 发送通知失败: {e}")
                
        except Exception as e:
            logger.error(f"[点赞] 处理出错: {e}")

    async def daily_tasks(self, job=None):
          await self.checkin_task()
          await self.like_task()





    def schedule_jobs(self):

        # self.scheduler.add_job(
        #     self.每分任务,
        #     'interval',
        #     minutes=1,
        #     id="每分任务"
        # )
        # logger.info("添加[每分任务]定时任务")

        self.scheduler.add_job(
            self.daily_tasks,
            'cron',
            hour=0,
            minute=0,
            id="每天任务",
        )
        logger.info("添加[每天任务]定时任务")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=999)
    async def _capture_bot_instance(self, event: AstrMessageEvent):
        """捕获机器人实例"""

        if self.bot_instance is None and event.get_platform_name() == "aiocqhttp":
            try:
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                if isinstance(event, AiocqhttpMessageEvent):
                    self.bot_instance = event.bot
                    self.platform_name = "aiocqhttp"
                    logger.info(f"[Miao] 成功捕获 aiocqhttp 机器人实例")
            except ImportError:
                logger.warning(f"[Miao] 无法导入 AiocqhttpMessageEvent")

    
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
        
        yield event.plain_result(result)


    @filter.command("添加点赞列表")
    async def add_user_to_likes(self, event: AstrMessageEvent,new_user: str):
        """格式：添加点赞列表 QQ"""
        if not await self.is_Master(event.get_sender_id()):
            yield event.plain_result("只有主人才能使用此命令喵~")
            return
        # 获取当前列表
        send_like_list = self.config.get("send_like_list", [])

        try:
             user_id = int(re.search(r'\d+', new_user).group())
        except (AttributeError, ValueError):
             user_id = 0

        # 如果用户不存在于列表中，则添加
        if user_id not in send_like_list:
            send_like_list.append(user_id)
            yield event.chain_result([Comp.Plain(f"已添加[{user_id}]到点赞列表")])
            logger.info(f"已添加 {user_id} 到 send_like_list")
        else:
            logger.info(f"{user_id} 已在列表中")
        
        self.config["send_like_list"] = send_like_list
        self.config.save_config()
    


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

    @filter.command("生成语音")
    async def generate_voice(self, event: AstrMessageEvent, Avatar: str, text: str):
        """格式：生成语音 内容"""

        yield event.chain_result([Comp.Plain("请稍等片刻喵~")])

        result = await tts(text, Avatar)
        
        if result.get("code") == 200:
            await event.send(event.chain_result([Record.fromURL(result.get("url"))]))
            logger.info(f"[生成语音] 成功")
            return
        else:

            logger.info(f"[生成语音] 失败: {result.get('msg')}")
    

    @filter.command("原神卡池")
    async def genshin_gacha_pools(self, event: AstrMessageEvent):
        """格式：原神卡池"""
        nodes_list = []
        try:
            activities = await fetch_gacha_pool()
            sender_id = event.get_sender_id()
        
            info_node = Node(
                uin=sender_id,
                name="原神祈愿助手",
                content=[Plain("📢 当前原神祈愿池信息 📢")]
            )
            nodes_list.append(info_node)
        
            for i, activity in enumerate(activities, 1):
                title = activity["title"]
                pool_items = activity["pool"]
                start_time = activity["start_time"]
                end_time = activity["end_time"]
            
                # 构建节点内容
                content_parts = [
                    Plain(f"🎯 祈愿池{i}：{title}\n"),
                    Plain(f"⏰ 活动时间：{start_time} 至 {end_time}\n"),
                ]
                for j, item in enumerate(pool_items, 1):
                    try:
                        icon_url = item["icon"]
                        content_parts.append(CompImage.fromURL(icon_url))
                    except Exception as e:
                        logger.debug(f"添加图片失败: {e}")
                        content_parts.append(Plain(f"  图标{j}：[图片加载失败]\n"))
            
                # 创建节点
                node = Node(
                    uin=sender_id,
                    name="原神祈愿助手",
                    content=content_parts
                )
                nodes_list.append(node)
        
            # 创建最后一个节点：总结节点
            summary_node = Node(
                uin=sender_id,
                name="原神祈愿助手",
                content=[Plain(f"📊 当前共有 {len(activities)} 个祈愿池活动\n✨ 祝大家都能抽到想要的角色和武器！")]
            )
            nodes_list.append(summary_node)
        
            nodes = Nodes(nodes=nodes_list)
            yield event.chain_result([nodes])
        
        except Exception as e:
            logger.error(f"获取原神卡池信息失败: {e}")
            yield event.chain_result([Plain("获取原神卡池信息失败，请稍后重试！")])
    
    @filter.command("前瞻兑换码")
    async def preview_redeem_code(self, event: AstrMessageEvent, game_name: str):
        """格式：前瞻兑换码 游戏名"""
        if game_name:
            code, cover = await get_preview_redeem_code(game_name)
            if code:
                    lines = code.rstrip().split('\n')
                    lines[-1] = "By 你的影月月"
                    code = '\n'.join(lines)
                    chain = [
                        Comp.Image.fromURL(cover),
                        Comp.Plain(code)
                    ]
                    yield event.chain_result(chain)
            else:
                yield event.plain_result("获取前瞻兑换码失败，请稍后再试。")
        else:
            yield event.plain_result("参数不足！正确格式：前瞻兑换码 游戏名")
        
    @filter.command("伪造聊天记录")
    async def fake_chat_record(self, event: AstrMessageEvent, QQ:int, Nice:str, txt:str):
        """格式：伪造聊天记录 QQ号 昵称 内容"""
        qq_value = self.config.get("Master", 0)

        if QQ!= qq_value:
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
