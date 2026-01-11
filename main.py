from aiohttp.helpers import IS_MACOS
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
from datetime import datetime, timedelta
from astrbot.core.message.components import Record, File
from typing import Optional, Dict, Any
import tempfile
import wave
from pydub import AudioSegment
import aiofiles
from . import BiliBili

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

def extract_b23_precisely(text):
    """使用 lookaround 确保精确匹配"""
    
    pattern = r'(?<!\w)(?:https?://)?b23\.tv/[a-zA-Z0-9]{5,10}(?!\w)'
    
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    return matches

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

async def get_silk_url(audio_url:str):
    """
    获取silk音频文件URL
    
    Returns:
        str: 如果code=1则返回message中的URL，否则返回None
    """
    api_url = "https://oiapi.net/api/Mp32Silk"
    encoded_url = urllib.parse.quote(audio_url, safe='/:?=&')
    payload = {
        "url": encoded_url,
        "type": "json",
        "format": "1"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, timeout=30) as response:
                result = await response.json()
                
                # 检查code字段
                code = result.get('code')
                if code == 1:
                    # 成功，返回message
                    return result.get('message')
                else:
                    return None
                    
    except aiohttp.ClientError as e:
        return None
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        return None
async def fetch_wangyi_music(search:str):
    url = "https://node.api.xfabe.com/api/wangyi/search"
    params = {
        "search": search,  # 搜索关键词
        "limit": 10           # 返回结果数量
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as response:
                # 检查响应状态
                if response.status == 200:
                    # 解析JSON响应
                    data = await response.json()

                    return data
                else:

                    return None
                    
        except aiohttp.ClientError as e:
            print(f"网络请求错误：{e}")
        except Exception as e:
            print(f"其他错误：{e}")
async def get_song_url( song_id: int):
    """获取歌曲URL"""
    params = {"type": "json", "id": song_id}
    base_url = "https://node.api.xfabe.com/api/wangyi/music"
    async with aiohttp.ClientSession() as session:
        try:
            # 设置超时
            timeout = aiohttp.ClientTimeout(total=30)
                
            async with session.get(base_url, params=params, timeout=timeout) as response:
                response.raise_for_status()  # 如果状态码不是200，抛出异常
                    
                data = await response.json()
                    
                if data.get('code') != 200:
                    raise None
                    
                song_data = data.get('data', {})
                song_url = song_data.get('url')
                    
                if not song_url:
                    raise None
                    
                # 返回URL和其他有用信息
                return song_url
                    
        except aiohttp.ClientError as e:
            return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return None


async def kurobbs_login(mobile, code):
    """
    库街区登录函数（异步版本）
    
    Args:
        mobile (int): 手机号码，11位数字
        code (int/str): 验证码，数字格式
        session (aiohttp.ClientSession, optional): 可复用的会话对象
        
    Returns:
        dict: 包含响应结果和数据的字典
    """
    url = 'https://api.kurobbs.com/user/sdkLogin'

    headers = {
        'osversion': 'Android',
        'devcode': '2fba3859fe9bfe9099f2696b8648c2c6',
        'distinct_id': '765485e7-30ce-4496-9a9c-a2ac1c03c02c',
        'countrycode': 'CN',
        'ip': '10.0.2.233',
        'model': '2211133C',
        'source': 'android',
        'lang': 'zh-Hans',
        'version': '1.0.9',
        'versioncode': '1090',
        'content-type': 'application/x-www-form-urlencoded',
        'accept-encoding': 'gzip',
        'user-agent': 'okhttp/3.10.0',
    }

    data = {
        'code': code,
        'devCode': '2fba3859fe9bfe9099f2696b8648c2c6',
        'gameList': '',
        'mobile': mobile
    }
    session = aiohttp.ClientSession()
    try:
        async with session.post(url, headers=headers, data=data, timeout=aiohttp.ClientTimeout(total=10)) as response:
            
            return await response.json()
            
    except asyncio.TimeoutError:
        return {
            'success': False,
            'code': None,
            'data': None,
            'msg': '请求超时，请检查网络连接'
        }
    except aiohttp.ClientConnectionError:
        return {
            'success': False,
            'code': None,
            'data': None,
            'msg': '网络连接错误，请检查网络'
        }
    except aiohttp.ClientError as error:
        return {
            'success': False,
            'code': None,
            'data': None,
            'msg': f'客户端错误: {error}'
        }
    except Exception as error:
        return {
            'success': False,
            'code': None,
            'data': None,
            'msg': f'未知错误: {error}'
        }
async def kurobbs_sign(
    token: str,
    role_id: int,
    user_id: int,
    devcode: str = "1",
):
    """
    库街区签到功能（异步版本）
    
    Args:
        token (str): 用户认证token
        role_id (int): 角色ID
        user_id (int): 用户ID
        devcode (str): 设备代码，默认为"1"
        game_id (int): 游戏ID，默认为3
        server_id (str): 服务器ID，默认为固定的值
        session (aiohttp.ClientSession, optional): 可复用的会话对象
    
    Returns:
        Dict[str, Any]: 包含签到结果的字典
    """
    # 获取当前月份
    current_month = datetime.now().strftime('%m')
    
    url = 'https://api.kurobbs.com/encourage/signIn/v2'
    
    headers = {
        'pragma': 'no-cache',
        'cache-control': 'no-cache',
        'accept': 'application/json, text/plain, */*',
        'source': 'android',
        'user-agent': 'Mozilla/5.0 (Linux; Android 13; 2211133C Build/TKQ1.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.131 Mobile Safari/537.36 Kuro/1.0.9 KuroGameBox/1.0.9',
        'token': token,
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://web-static.kurobbs.com',
        'x-requested-with': 'com.kurogame.kjq',
        'sec-fetch-site': 'same-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'accept-encoding': 'gzip, deflate, br',
        'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        "devcode": devcode
    }
    game_id: int = 3
    server_id: str = '76402e5b20be2c39f095a152090afddc'
    data = {
        'gameId': game_id,
        'serverId': server_id,
        'roleId': role_id,
        'reqMonth': current_month,
        'userId': user_id
    }

    session = aiohttp.ClientSession()
    
    try:
        async with session.post(
            url, 
            headers=headers, 
            data=data, 
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            return await response.json()

    except asyncio.TimeoutError:
        return None
    except aiohttp.ClientConnectionError:
        return None
    except aiohttp.ClientError as e:
         return None
    except Exception as e:
         return None

    return None

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
async def fetch_role_list(
    token: str,
    game_id: int = 3,
    ):
    """
    获取角色列表
    
    Args:
        token: 用户认证token
        game_id: 游戏ID，默认为3
        timeout: 请求超时时间，默认为30秒
        
    Returns:
        响应的JSON数据字典
        
    Raises:
        aiohttp.ClientError: 网络请求错误
        asyncio.TimeoutError: 请求超时
        json.JSONDecodeError: JSON解析错误
    """
    url = 'https://api.kurobbs.com/user/role/findRoleList'
    
    headers = {
        'osversion': 'Android',
        'devcode': '2fba3859fe9bfe9099f2696b8648c2c6',
        'countrycode': 'CN',
        'ip': '10.0.2.233',
        'model': '2211133C',
        'source': 'android',
        'lang': 'zh-Hans',
        'version': '1.0.9',
        'versioncode': '1090',
        'token': token,
        'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
        'accept-encoding': 'gzip',
        'user-agent': 'okhttp/3.10.0',
    }
    
    data = {
        'gameId': game_id
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                url,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                
                if response.status != 200:
                    error_msg = f'请求错误: {response.status} {response.reason}'
                    return {'code': 600, 'msg': error_msg}
                
                # 尝试解析JSON响应
                try:
                    return await response.json()
    
                except json.JSONDecodeError as e:
                    error_msg = f'JSON 解析错误: {e}'
                    return {'code': 500, 'msg': error_msg}
                    
        except asyncio.TimeoutError as e:
            error_msg = f'请求超时: {e}'
            return {'code': 400, 'msg': error_msg}
        except aiohttp.ClientError as e:
            error_msg = f'网络请求错误: {e}'
            return {'code': 300, 'msg': error_msg}


@register("astrbot_plugin_miao", "miao", "一个轻量 AstrBot 插件，支持每日群打卡与批量点赞、抓取前瞻兑换码并附图、生成演示聊天节点以及检测“胡桃 + 链接”并提醒管理员。", "v0.0.7")
class MiaoPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.bot_instance = None
        self.bilibili = BiliBili.Bilbili()
        self.scheduler = AsyncIOScheduler()
        self.scheduler.configure({"apscheduler.timezone": "Asia/Shanghai"})
        self.kurobbs_path = ""

        logger.info(f"[Miao] bot_instance{self.bot_instance}")
    
    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        self.schedule_jobs()
        self.scheduler.start()

        logger.info("[Miao] APScheduler 定时任务")
        self.kurobbs_path = os.path.join(os.getcwd(), "data", "plugins", "astrbot_plugin_miao", "kurobbs_token.json")
        logger.info(f"[Miao] kurobbs_path {self.kurobbs_path}")

        
    async def kurobbs_save(self, event: AstrMessageEvent, kurobbs):
            """库街区保存功能（异步版本）"""
            file_path =  self.kurobbs_path
            sender_id = event.get_sender_id()

            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
                # 读取现有数据（如果文件存在）
                existing_data = {}
                if os.path.exists(file_path):
                    try:
                        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                            content = await f.read()
                            existing_data = json.loads(content)
                    except (json.JSONDecodeError, FileNotFoundError):
                        existing_data = {}
                existing_data[str(sender_id)] = kurobbs

                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(existing_data, ensure_ascii=False, indent=4))
            
                return True, "保存成功！"
            
            except Exception as e:
                return False, f"保存失败: {str(e)}"
    
    async def kurobbs_load(self, sender_id:str):
        """库街区读取功能（异步版本）"""
        file_path = self.kurobbs_path

        try:
            if not os.path.exists(file_path):
                return None
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
            
            # 根据sender_id返回对应的数据
            return data.get(str(sender_id))
            
        except Exception as e:
            return None
    async def kurobbs_get_all_users(self):
        """获取所有保存的sender_id列表（异步版本）"""
        file_path = self.kurobbs_path
        logger.info(f"[Miao] file_path {file_path} self.kurobbs_path {self.kurobbs_path}")
        try:
            if not os.path.exists(file_path):
                return []
        
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
            return list(data.keys())
        
        except Exception as e:
            return []
    
    async def is_Master(self,QQ_:int):
        qq_value = self.config.get("Master", 0)
        return QQ_ == qq_value



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
          #await self.kuromi_sign_all()





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



    async def get_qq_nickname(self, event: AstrMessageEvent,sender_id:int):
        try:
            user_info = await event.bot.get_stranger_info(user_id=int(sender_id))
            username = user_info.get("nickname", "未知用户")
        except Exception:
            username = "未知用户"
        return username
    
    async def get_qq_user_id(self, new_user: str):
        try:
            # 这个正则表达式可以匹配：
            # 1. @任意字符(数字) -> 提取括号内的数字
            # 2. [At:数字] -> 提取数字
            # 3. 纯数字 -> 直接提取
            match = re.search(r'(?:@[^(]+\(|\[At:)?(\d+)(?:\)|\])?', new_user)
            user_id = int(match.group(1)) if match else 0
        except (AttributeError, ValueError):
            user_id = 0
        return user_id
    
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
    


    @filter.regex(r'(?=.*https?://(?:www\.bilibili\.com|b23\.tv))')
    async def Hutao(self, event: AstrMessageEvent):
        """检测到胡桃链接回复""" 
        message_text = event.message_str
        all_results = []
        result = await self.bilibili.process_single_text(message_text)
        if result:
            all_results.append(result)
            if result['tags']:
                for tag in result['tags']:
                    if "胡桃" in tag:
                        qq_value = self.config.get("HuTao_config",0)
                        if qq_value !=0:
                            chain = [
                                Comp.At(qq=qq_value),
                                Comp.Plain("发现胡桃链接,嗷~"),
                            ]
                            yield event.chain_result(chain)
                        break   

        # qq_value = self.config.get("HuTao_config",0)
        # if qq_value !=0:
        #     chain = [
        #         Comp.At(qq=qq_value),
        #         Comp.Plain("发现胡桃链接,嗷~"),
        #     ]
        #     yield event.chain_result(chain)

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
        


    @filter.command("库街区登录")
    async def kuromi_login(self, event: AstrMessageEvent, mobile: int, code:int):
        """格式：库街区登录 手机号 验证码"""
        # 检查参数
        if not mobile or not code:
            yield event.plain_result("参数不足！正确格式：库街区登录 手机号 验证码")
            return
    
        # 验证手机号格式
        if mobile == 0:
            yield event.plain_result("手机号错误")
            return
    
        # 验证验证码格式
        if code <= 0:
            yield event.plain_result("验证码格式错误")
            return
    
        try:
            # 调用登录函数
            result = await kurobbs_login(mobile, code)
        
            if result.get("code", 0) == 200:


                user_data = result.get("data", {})
                user_info = []
                user_name = user_data.get('userName')
                if user_name:
                    user_info.append(f"用户名: {user_name}")
                gender = user_data.get('gender')
                if gender is not None:
                    gender_map = {0: '未知', 1: '男', 2: '女', 3: '保密'}
                    gender_str = gender_map.get(gender, f'未知({gender})')
                    user_info.append(f"性别: {gender_str}")
                signature = user_data.get('signature')
                if signature:
                    user_info.append(f"签名: {signature}")

                await self.kurobbs_save(event,result)
                yield event.plain_result(f"✅ 登录成功！\n {user_info}" )

            else:
                # kurobbs_login函数返回失败（可能是网络错误等）
                error_msg = result.get('msg', '未知错误')
                msg = f"❌ 登录失败！原因: {error_msg}"
                yield event.plain_result(msg)
            
        except Exception as e:
            # 捕获其他异常
            yield event.plain_result(f"❌ 登录过程中发生异常: {str(e)}")
    @filter.command("库街区签到")
    async def kuromi_sign(self, event: AstrMessageEvent):
        """格式：库街区签到"""
    
        kurobbs_data = await self.kurobbs_load(event.get_sender_id())
        if not kurobbs_data:
            yield event.plain_result("❌ 未找到登录信息，请先使用“库街区登录 手机号 验证码”命令登录")
            return
        token =""
        traceId=""
        #yield event.plain_result(f"kurobbs_data: {kurobbs_data}")
        code = kurobbs_data.get('code')
        if code != 200:
            yield event.plain_result(kurobbs_data.get('msg'))
            return 
        try:
            token = kurobbs_data.get('data', {}).get('token')
        except (KeyError, AttributeError):
            token = None
        if not token:
            yield event.plain_result("❌ 未找到有效的登录Token，请重新登录")
            return
        sender_id = event.get_sender_id()
        userId = kurobbs_data.get('data', {}).get('userId')
        traceId = kurobbs_data.get('traceId')
        role_list_data = await fetch_role_list(token)
        roleId = None
        try:
            roleId = int(role_list_data['data'][0]['roleId'])
        except (KeyError, IndexError, AttributeError, ValueError):
            roleId = None

        #yield event.plain_result(f"token: {token} roleId: {roleId} userId: {userId} traceId: {traceId}")
        sign_data = await kurobbs_sign(token,roleId,userId,traceId)

        code = sign_data.get("code")
        if code == 200:
            nodes_list = []
            info_node = Node(
                uin=sender_id,
                name="库街区助手",
                content=[Plain("📢 当前库街区签到信息 📢")]
            )
            nodes_list.append(info_node)
            for item in sign_data['data']['todayList']:
                content_parts = []
                try:
                    icon_url = item["goodsUrl"]
                    content_parts.append(CompImage.fromURL(icon_url))
            
                    goodsNum = item.get("goodsNum", 0)
                    content_parts.append(Plain(f"数量：{goodsNum}"))
            
                except Exception as e:
                    content_parts.append(Plain(f"添加图片失败: {str(e)}\n"))
                
                node = Node(uin=sender_id, name="库街区助手", content=content_parts)
                nodes_list.append(node)
    
            nodes = Nodes(nodes=nodes_list)
            yield event.chain_result([nodes])
        else:
            msg = sign_data.get("msg", "签到失败！")
            yield event.plain_result(f"❌ {msg}")
    
    async def kuromi_sign_all(self):
        kurobbs_all_users = await self.kurobbs_get_all_users()
        for user_id in kurobbs_all_users:
            logger.info(f"[Miao] kuromi_sign_all user_id:{user_id}")
            kurobbs_data = await self.kurobbs_load(user_id)
            try:
                token = kurobbs_data.get('data', {}).get('token')
            except (KeyError, AttributeError):
                token = None
            if not token:
                await self.bot_instance.api.call_action('send_private_msg',user_id=str(user_id),message="❌ 未找到有效的登录Token，请重新登录" )
                continue
            role_list_data = await fetch_role_list(token)
            roleId = None
            try:
                roleId = int(role_list_data['data'][0]['roleId'])
            except (KeyError, IndexError, AttributeError, ValueError):
                roleId = None
            userId = kurobbs_data.get('data', {}).get('userId')
            traceId = kurobbs_data.get('traceId')
            sign_data = await kurobbs_sign(token,roleId,userId,traceId)
            code = sign_data.get("code")
            if code == 200:
                await self.bot_instance.api.call_action('send_private_msg',user_id=str(user_id),message=f"库街区: 签到成功")
            else:
                msg = sign_data.get("msg", "签到失败！")
                await self.bot_instance.api.call_action('send_private_msg',user_id=str(user_id),message=f"库街区: {msg}")


    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        '''监听所有消息并检测伪造消息请求'''
        message_text = event.message_str
    
        if not message_text.startswith("伪造消息"):
            return
        content = message_text[4:].strip()
        if not content:
            yield event.plain_result("格式错误，请使用：伪造消息 QQ号 内容 | QQ号 内容 | ...")
            return
    
        text_segments = content.split('|')
        nodes_list = []
    
        for segment in text_segments:
            segment = segment.strip()
            if not segment:
                continue
        
            text_segmentas = segment.split()
            if len(text_segmentas) < 2:
                yield event.plain_result(f"格式错误，缺少内容：{segment}")
                return
            userid = await self.get_qq_user_id(text_segmentas[0])
            if await self.is_Master(userid):
                continue
            
            nickname = await self.get_qq_nickname(event, userid)

            info_node = Node(uin=userid,name=nickname,content=[Plain(text_segmentas[1])])
            nodes_list.append(info_node)

        if nodes_list:
            nodes = Nodes(nodes=nodes_list)
            yield event.chain_result([nodes])
        else:
            yield event.plain_result("未能解析出任何有效的消息节点")
    
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        if self.scheduler.running:
            self.scheduler.shutdown()
        logger.info(f"[Miao] 插件已卸载")
