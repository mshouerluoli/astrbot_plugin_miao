import aiohttp
import asyncio
import re
class Bilbili:
    def __init__(self):
        pass    
    async def process_single_text(self,single_text):
        """
        处理单条文本，识别并处理其中的B站链接。
        """
        # 1. 识别并提取链接
        short_pattern = r'(?:https?://)?b23\.tv/[\w]+(?:[?&][^\s]*)?'
        bv_pattern = r'(?:https?://)?www\.bilibili\.com/video/(BV[\w]+)(?:[?&][^\s]*)?'
    
        # 使用re.search查找匹配（只找第一个）
        short_match = re.search(short_pattern, single_text, re.IGNORECASE)
        bv_match = re.search(bv_pattern, single_text, re.IGNORECASE)
    
        # 2. 确定要处理的链接
        target_bvid = None
        target_short_link = None
        link_type = None
        original_url = None
    
        # 优先处理短链（如果存在）
        if short_match:
            target_short_link = short_match.group(0)
            link_type = 'short_link'
            original_url = target_short_link
            #print(f"识别到短链: {target_short_link}")
        
            # 展开短链获取BV号
            expanded = await self.expand_b23_url(target_short_link)
            if expanded and expanded.startswith('BV'):
                target_bvid = expanded
            elif expanded:
                # 如果返回的是URL而不是BV号，尝试从中提取BV号
                bv_match_expanded = re.search(r'(BV[\w]{10})', expanded)
                if bv_match_expanded:
                    target_bvid = bv_match_expanded.group(1)
        # 如果没有短链，查找直接BV号链接
        elif bv_match:
            original_url = bv_match.group(0)  # 获取完整匹配的URL
            target_bvid = bv_match.group(1)   # 获取分组1的BV号
            link_type = 'direct_bvid'
            #print(f"识别到直接BV号链接: {original_url}")
    
        # 3. 如果没有找到任何有效链接，返回None
        if not target_bvid and not target_short_link:
            #print(f"未在文本中发现有效B站链接: {single_text[:50]}...")
            return None
    
        # 4. 获取标签（如果有BV号）
        tags = []
        if target_bvid:
            tags = await self.get_tag_names(target_bvid)
    
        # 5. 构建结果
        result = {
            'original_text': single_text[:100] + ('...' if len(single_text) > 100 else ''),
            'link_type': link_type,
            'tags': tags
        }
    
        # 添加原始URL
        if original_url:
            result['original_url'] = original_url
    
        # 根据链接类型添加相应信息
        if link_type == 'short_link' and target_short_link:
            result['short_link'] = target_short_link
            if target_bvid:
                result['expanded_bvid'] = target_bvid
    
        if target_bvid and link_type == 'direct_bvid':
            result['bvid'] = target_bvid
    
        return result

    async def expand_b23_url(self,short_url):
        """短链接展开函数（异步版本）"""
        try:
            # 添加用户代理，模拟浏览器请求
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
        
            # 使用GET方法，设置最大重定向次数
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    short_url, 
                    headers=headers, 
                    allow_redirects=True,  # 允许重定向
                    max_redirects=10,      # 最大重定向次数
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    final_url = str(response.url)
                    return final_url
        except Exception as e:
            #print(f"展开链接时出错: {e}")
            return short_url

    async def get_tag_names(self,bvid):
        """根据BV号获取视频标签"""
        api_url = f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': f'https://www.bilibili.com/video/{bvid}'
        }
    
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('code') == 0:
                            return [tag.get('tag_name', '') for tag in data.get('data', []) if tag.get('tag_name')]
        except Exception as e:
            print(f"获取标签时出错: {e}")
        return []
