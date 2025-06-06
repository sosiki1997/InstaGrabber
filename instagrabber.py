import os
import time
import re
import json
import requests
import random
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# 配置参数
CONFIG = {
    'data_dir': 'data',  # 数据存储根目录
    'cookie_file': 'config/cookie.txt',  # cookie配置文件路径
    'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'query_hashes': {
        'user_posts': '003056d32c2554def87228bc3fd9668a',  # 用户发帖GraphQL查询hash
        'user_reels': '31c169c9212683643d3dac3ca0b5b8dd',  # 用户Reels GraphQL查询hash
        'user_tagged': 'e6306cc3dbe69d6a82ef8b5f8654c50b'   # 用户被标记GraphQL查询hash
    },
    'ig_app_id': '936619743392459',  # Instagram应用ID
    'request_delay': 2,  # 请求间隔时间(秒)
    'request_timeout': 20,  # 请求超时时间(秒)
    'max_retries': 3,  # 最大重试次数
    'test_mode': False,  # 测试模式
    'max_posts': 0,  # 最大爬取帖子数量，0表示不限制
}

# 确保配置目录存在
os.makedirs(os.path.dirname(CONFIG['cookie_file']), exist_ok=True)
os.makedirs(CONFIG['data_dir'], exist_ok=True)

def load_cookie():
    """从文件加载cookie配置"""
    if os.path.exists(CONFIG['cookie_file']):
        try:
            with open(CONFIG['cookie_file'], 'r') as f:
                return f.read().strip()
        except Exception as e:
            print(f"读取Cookie文件失败: {e}")
            return None
    return None

def save_cookie(cookie):
    """保存cookie到配置文件"""
    with open(CONFIG['cookie_file'], 'w') as f:
        f.write(cookie)

def get_cookies_dict(raw_cookie):
    """将原始cookie字符串转换为字典格式"""
    cookies = {}
    for item in raw_cookie.split(';'):
        if '=' in item:
            key, value = item.strip().split('=', 1)
            cookies[key] = value
    return cookies

def graphql_fetch_all_posts(user_id, cookie, max_count=300):
    """使用GraphQL API获取用户所有帖子
    
    Args:
        user_id: 用户ID
        cookie: 认证cookie
        max_count: 最大获取帖子数量
        
    Returns:
        list: 帖子节点列表
    """
    headers = {
        'user-agent': CONFIG['user_agent'],
        'cookie': cookie,
        'referer': 'https://www.instagram.com/',
        'x-ig-app-id': CONFIG['ig_app_id'],
        'x-requested-with': 'XMLHttpRequest',
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8'
    }
    query_hash = CONFIG['query_hashes']['user_posts']
    has_next = True
    end_cursor = ''
    posts = []
    count = 0
    retries = 0
    
    while has_next and count < max_count:
        variables = {
            "id": user_id,
            "first": 50,
            "after": end_cursor
        }
        url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={json.dumps(variables)}"
        
        try:
            print(f"正在请求第 {count//50 + 1} 页数据...")
            resp = requests.get(url, headers=headers, timeout=CONFIG['request_timeout'])
            
            # 检查响应状态
            if resp.status_code != 200:
                print(f"API请求失败: HTTP {resp.status_code}")
                if retries < CONFIG['max_retries']:
                    retries += 1
                    print(f"正在进行第 {retries}/{CONFIG['max_retries']} 次重试...")
                    time.sleep(CONFIG['request_delay'] * 2)
                    continue
                else:
                    print("达到最大重试次数，切换到备用方法")
                    break
                    
            # 重置重试计数
            retries = 0
                
            # 检查是否是JSON响应
            content_type = resp.headers.get('content-type', '')
            if 'application/json' not in content_type and 'text/javascript' not in content_type:
                print(f"API返回非JSON内容: {content_type}")
                break
                
            data = resp.json()
            if not data:
                print("API返回空数据")
                break
                
            try:
                edges = data['data']['user']['edge_owner_to_timeline_media']['edges']
                page_info = data['data']['user']['edge_owner_to_timeline_media']['page_info']
            except KeyError as e:
                print(f"API返回数据结构异常: {e}")
                # 不再保存debug文件
                break
                
            for edge in edges:
                node = edge['node']
                posts.append(node)
                count += 1
            
            has_next = page_info['has_next_page']
            end_cursor = page_info['end_cursor']
            print(f"已获取 {count} 个帖子")
            
            if not has_next:
                break
                
            # 添加请求延迟，避免触发限流
            time.sleep(CONFIG['request_delay'])
            
        except requests.exceptions.Timeout:
            print("API请求超时")
            if retries < CONFIG['max_retries']:
                retries += 1
                print(f"正在进行第 {retries}/{CONFIG['max_retries']} 次重试...")
                time.sleep(CONFIG['request_delay'] * 2)
                continue
            else:
                break
        except requests.exceptions.RequestException as e:
            print(f"API请求网络错误: {e}")
            break
        except json.JSONDecodeError:
            print("API返回数据解析失败")
            break
        except Exception as e:
            print(f"API请求处理异常: {e}")
            break
            
    return posts

def extract_media_from_nodes(nodes):
    """从GraphQL节点中提取媒体URL
    
    Args:
        nodes: GraphQL返回的节点列表
        
    Returns:
        tuple: (图片URL列表, 视频URL列表)
    """
    img_urls = set()
    video_urls = set()
    
    for node in nodes:
        try:
            # 处理视频
            if node.get('is_video'):
                if 'video_url' in node:
                    video_urls.add(node['video_url'])
            
            # 处理图片
            if 'display_url' in node:
                img_urls.add(node['display_url'])
            
            # 处理多媒体帖子
            if 'edge_sidecar_to_children' in node:
                for child in node['edge_sidecar_to_children']['edges']:
                    cnode = child['node']
                    if cnode.get('is_video') and 'video_url' in cnode:
                        video_urls.add(cnode['video_url'])
                    if 'display_url' in cnode:
                        img_urls.add(cnode['display_url'])
        except Exception as e:
            print(f"处理媒体节点异常: {e}")
            continue
            
    return list(img_urls), list(video_urls)

def download_media(urls, save_dir, cookies, prefix):
    """下载媒体文件
    
    Args:
        urls: 媒体URL列表
        save_dir: 保存目录
        cookies: 请求cookie
        prefix: 文件名前缀
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    success_count = 0
    failed_count = 0
    
    # 构建请求头
    headers = {
        'user-agent': CONFIG['user_agent'],
        'referer': 'https://www.instagram.com/',
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'accept-encoding': 'gzip, deflate, br',
        'origin': 'https://www.instagram.com',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'sec-ch-ua': '"Chromium";v="112", "Google Chrome";v="112"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"'
    }
    
    # 使用会话保持连接
    session = requests.Session()
    session.headers.update(headers)
    
    # 设置cookie
    for k, v in cookies.items():
        session.cookies.set(k, v)
    
    for idx, url in enumerate(urls):
        try:
            # 从URL解析文件扩展名
            ext = url.split('?')[0].split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'mp4', 'webp']:
                if 'video' in prefix:
                    ext = 'mp4'  # 默认视频扩展名
                else:
                    ext = 'jpg'  # 默认图片扩展名
                
            filename = os.path.join(save_dir, f"{prefix}_{idx:04d}.{ext}")
            
            # 检查文件是否已存在
            if os.path.exists(filename):
                print(f"文件已存在，跳过: {filename}")
                success_count += 1
                continue
                
            print(f"下载: {idx+1}/{len(urls)} - {os.path.basename(filename)}")
            
            # 重试机制
            max_retries = 3
            retry_delay = 2
            
            for retry in range(max_retries):
                try:
                    # 添加随机延迟，避免被检测
                    time.sleep(1 + random.random() * 2)
                    
                    # 构建特定URL的请求头
                    url_headers = headers.copy()
                    url_headers['referer'] = 'https://www.instagram.com/'
                    
                    # 发送请求
                    resp = session.get(url, headers=url_headers, timeout=CONFIG['request_timeout'], stream=True)
                    
                    if resp.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in resp.iter_content(chunk_size=1024):
                                if chunk:
                                    f.write(chunk)
                        success_count += 1
                        break
                    elif resp.status_code == 403:
                        print(f"访问受限 (HTTP 403)，尝试重试 {retry+1}/{max_retries}")
                        # 增加延迟
                        time.sleep(retry_delay * (retry + 1))
                        # 更换请求头
                        url_headers['user-agent'] = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(100, 120)}.0.0.0 Safari/537.36"
                    else:
                        print(f"下载失败: HTTP {resp.status_code}")
                        if retry < max_retries - 1:
                            print(f"尝试重试 {retry+1}/{max_retries}")
                            time.sleep(retry_delay * (retry + 1))
                        else:
                            failed_count += 1
                            break
                except (requests.exceptions.RequestException, IOError) as e:
                    print(f"下载异常: {e}")
                    if retry < max_retries - 1:
                        print(f"尝试重试 {retry+1}/{max_retries}")
                        time.sleep(retry_delay * (retry + 1))
                    else:
                        failed_count += 1
                        break
            
            # 每个文件下载后添加随机延迟
            time.sleep(0.5 + random.random())
            
        except Exception as e:
            print(f"处理文件异常: {e}")
            failed_count += 1
            
    print(f"下载完成: 成功 {success_count} 个, 失败 {failed_count} 个")

def get_user_id(username, cookie):
    """获取Instagram用户ID，尝试多种API方式
    
    Args:
        username: Instagram用户名
        cookie: 认证cookie
        
    Returns:
        str: 用户ID，失败返回None
    """
    headers_base = {
        'user-agent': CONFIG['user_agent'],
        'cookie': cookie,
        'referer': f'https://www.instagram.com/{username}/',
        'x-ig-app-id': CONFIG['ig_app_id'],
        'x-requested-with': 'XMLHttpRequest',
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8'
    }
    
    # 尝试多种API获取用户ID
    api_endpoints = [
        # 新版API
        {
            'url': f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            'parser': lambda data: data['data']['user']['id']
        },
        # 老版API (带__d=dis)
        {
            'url': f"https://www.instagram.com/{username}/?__a=1&__d=dis",
            'parser': lambda data: data['graphql']['user']['id']
        },
        # 老版API (不带__d=dis)
        {
            'url': f"https://www.instagram.com/{username}/?__a=1",
            'parser': lambda data: data['graphql']['user']['id']
        }
    ]
    
    for api in api_endpoints:
        try:
            print(f"尝试通过 {api['url']} 获取用户ID...")
            resp = requests.get(api['url'], headers=headers_base, timeout=CONFIG['request_timeout'])
            
            if resp.status_code == 200:
                data = resp.json()
                user_id = api['parser'](data)
                print(f"成功获取用户ID: {user_id}")
                return user_id
        except requests.exceptions.RequestException as e:
            print(f"请求异常: {e}")
            continue
        except json.JSONDecodeError:
            print(f"JSON解析失败")
            continue
        except Exception as e:
            print(f"处理异常: {e}")
            continue
    
    print("获取用户ID失败，所有API均未成功")
    return None

def extract_media_from_post(driver, post_url):
    """从帖子页面提取媒体URL
    
    Args:
        driver: Selenium WebDriver实例
        post_url: 帖子URL
    
    Returns:
        tuple: (图片URL集合, 视频URL集合)
    """
    img_urls = set()
    video_urls = set()
    
    try:
        # 访问帖子页面
        driver.get(post_url)
        time.sleep(5)  # 增加等待时间，确保页面完全加载
        
        # 获取帖子ID用于关联
        post_id = post_url.split('/')[-2]
        print(f"  - 帖子ID: {post_id}")
        
        # 检查是否有视频标志
        has_video = False
        is_reel = '/reel/' in post_url
        
        if is_reel:
            has_video = True
            print(f"  - 检测到视频帖子")
        
        # 获取页面源码
        page_source = driver.page_source
        
        # 方法1: 使用JavaScript提取所有图片和视频URL
        js_script = """
        function getAllMedia() {
            const media = {
                images: [],
                videos: []
            };
            
            // 获取所有图片
            const images = document.querySelectorAll('img');
            images.forEach(img => {
                if (img.src && img.src.includes('instagram') && !img.src.includes('profile_pic')) {
                    media.images.push(img.src);
                }
                
                // 尝试获取srcset属性中的高分辨率图像
                if (img.srcset) {
                    const srcset = img.srcset.split(',');
                    const highResImg = srcset[srcset.length - 1].trim().split(' ')[0];
                    if (highResImg && highResImg.includes('instagram')) {
                        media.images.push(highResImg);
                    }
                }
            });
            
            // 获取所有视频
            const videos = document.querySelectorAll('video');
            videos.forEach(video => {
                if (video.src) {
                    media.videos.push(video.src);
                    
                    // 添加视频封面
                    if (video.poster) {
                        media.images.push(video.poster);
                    }
                }
                
                // 检查source子元素
                const sources = video.querySelectorAll('source');
                sources.forEach(source => {
                    if (source.src) {
                        media.videos.push(source.src);
                    }
                });
            });
            
            // 尝试从meta标签提取
            const videoMeta = document.querySelector('meta[property="og:video"]');
            if (videoMeta && videoMeta.content) {
                media.videos.push(videoMeta.content);
            }
            
            const imgMeta = document.querySelector('meta[property="og:image"]');
            if (imgMeta && imgMeta.content) {
                media.images.push(imgMeta.content);
            }
            
            // 去重
            media.images = [...new Set(media.images)];
            media.videos = [...new Set(media.videos)];
            
            return media;
        }
        
        return getAllMedia();
        """
        
        result = driver.execute_script(js_script)
        
        # 处理JavaScript结果
        js_images = result.get('images', [])
        js_videos = result.get('videos', [])
        
        # 添加图片URL
        for img_url in js_images:
            if is_valid_url(img_url):
                print(f"  - 从JavaScript找到图片URL")
                img_urls.add(f"poster:{post_id}:{img_url}")
        
        # 添加视频URL
        for video_url in js_videos:
            if is_valid_url(video_url):
                if video_url.startswith('blob:'):
                    print(f"  - 检测到blob视频URL")
                    has_video = True
                else:
                    print(f"  - 从JavaScript找到视频URL")
                    video_urls.add(f"video:{post_id}:{video_url}")
                    has_video = True
        
        # 方法2: 从页面源码中提取图片URL
        if not img_urls:
            # 尝试提取og:image元标签
            meta_img_matches = re.findall(r'<meta property="og:image" content="([^"]+)"', page_source)
            if meta_img_matches:
                img_url = meta_img_matches[0]
                if is_valid_url(img_url):
                    print(f"  - 从og:image元标签找到图片URL")
                    img_urls.add(f"poster:{post_id}:{img_url}")
            
            # 尝试提取display_url字段
            display_url_matches = re.findall(r'"display_url":"(https:[^"]+)"', page_source)
            if display_url_matches:
                for url in display_url_matches:
                    img_url = url.replace('\\u0026', '&')
                    if is_valid_url(img_url):
                        print(f"  - 从display_url字段找到图片URL")
                        img_urls.add(f"poster:{post_id}:{img_url}")
            
            # 尝试提取display_resources字段
            display_resources = re.findall(r'"display_resources":\[(.*?)\]', page_source)
            if display_resources:
                for resources in display_resources:
                    urls = re.findall(r'"src":"(https:[^"]+)"', resources)
                    if urls:
                        # 通常最后一个URL是最高分辨率
                        img_url = urls[-1].replace('\\u0026', '&')
                        if is_valid_url(img_url):
                            print(f"  - 从display_resources字段找到图片URL")
                            img_urls.add(f"poster:{post_id}:{img_url}")
        
        # 方法3: 从页面源码中提取视频URL
        if has_video and not video_urls:
            # 视频URL的正则表达式模式
            video_patterns = [
                r'"video_url":"(https:[^"]+)"',
                r'"video_versions":\[(.*?)\]',
                r'"progressive_url":"(https:[^"]+)"',
                r'property="og:video" content="([^"]+)"',
                r'property="og:video:secure_url" content="([^"]+)"',
                r'<source src="([^"]+)"'
            ]
            
            for pattern in video_patterns:
                matches = re.findall(pattern, page_source)
                if matches:
                    if pattern == r'"video_versions":\[(.*?)\]' and matches:
                        # 需要进一步解析
                        url_matches = re.findall(r'"url":"(https:[^"]+)"', matches[0])
                        if url_matches:
                            video_url = url_matches[0].replace('\\u0026', '&')
                            print(f"  - 从video_versions字段找到视频URL")
                            if is_valid_url(video_url):
                                video_urls.add(f"video:{post_id}:{video_url}")
                    else:
                        # 直接使用匹配到的URL
                        video_url = matches[0].replace('\\u0026', '&')
                        print(f"  - 从{pattern}找到视频URL")
                        if is_valid_url(video_url):
                            video_urls.add(f"video:{post_id}:{video_url}")
        
        # 方法4: 如果仍然没有图片，尝试截取帖子区域
        if not img_urls:
            try:
                # 尝试找到主图像区域
                main_element = None
                
                # 尝试各种可能的选择器
                selectors = [
                    "article img", 
                    "div._aagv img", 
                    "div[role='button'] img",
                    "div[data-visualcompletion='loading-state'] img"
                ]
                
                for selector in selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements and len(elements) > 0:
                            main_element = elements[0]
                            break
                    except:
                        pass
                
                if main_element:
                    # 创建文件名
                    timestamp = int(time.time())
                    screenshot_file = f"post_image_{post_id}_{timestamp}.png"
                    
                    # 截取元素
                    main_element.screenshot(screenshot_file)
                    print(f"  - 已截取帖子图像: {screenshot_file}")
                    
                    # 添加为本地文件URL，带标记
                    img_urls.add(f"poster:{post_id}:file://{os.path.abspath(screenshot_file)}")
                else:
                    # 如果没有找到元素，截取整个页面
                    timestamp = int(time.time())
                    screenshot_file = f"post_page_{post_id}_{timestamp}.png"
                    driver.save_screenshot(screenshot_file)
                    print(f"  - 已保存帖子页面截图: {screenshot_file}")
                    img_urls.add(f"poster:{post_id}:file://{os.path.abspath(screenshot_file)}")
            except Exception as e:
                print(f"  - 截取帖子区域失败: {e}")
                # 如果截取失败，保存整个页面截图
                timestamp = int(time.time())
                screenshot_file = f"post_page_{post_id}_{timestamp}.png"
                driver.save_screenshot(screenshot_file)
                print(f"  - 已保存帖子页面截图: {screenshot_file}")
                img_urls.add(f"poster:{post_id}:file://{os.path.abspath(screenshot_file)}")
        
        # 如果检测到视频但没有提取到URL，记录特殊标记
        if has_video and not video_urls:
            print("  - 检测到视频但未能提取URL")
            # 将帖子URL添加为特殊标记
            video_urls.add(f"video:{post_id}:post_url:{post_url}")
    except Exception as e:
        print(f"提取媒体异常: {e}")
        # 尝试保存当前页面截图
        try:
            timestamp = int(time.time())
            screenshot_file = f"error_page_{post_id}_{timestamp}.png"
            driver.save_screenshot(screenshot_file)
            print(f"  - 已保存错误页面截图: {screenshot_file}")
            img_urls.add(f"poster:{post_id}:file://{os.path.abspath(screenshot_file)}")
        except:
            pass
    
    return img_urls, video_urls

def filter_media_urls(img_urls, video_urls):
    """过滤媒体URL，去除重复和低质量的媒体
    
    Args:
        img_urls: 图片URL集合
        video_urls: 视频URL集合
    
    Returns:
        tuple: (过滤后的图片URL集合, 过滤后的视频URL集合)
    """
    # 过滤图片URL
    filtered_img_urls = set()
    for url in img_urls:
        # 保留本地文件URL (快照)
        if url.startswith('file://'):
            filtered_img_urls.add(url)
            continue
            
        # 过滤掉头像和小尺寸图片
        if any(x in url for x in ['/profile_pic/', '_s150x150/']):
            continue
            
        # 保留来自Instagram CDN的图片
        if 'scontent' in url or 'cdninstagram' in url:
            filtered_img_urls.add(url)
    
    # 过滤视频URL
    filtered_video_urls = set()
    for url in video_urls:
        # 保留特殊标记
        if url.startswith('post_url:'):
            filtered_video_urls.add(url)
            continue
            
        # 过滤掉blob URL
        if url.startswith('blob:'):
            continue
            
        # 保留Instagram视频
        if 'instagram' in url or 'cdninstagram' in url:
            filtered_video_urls.add(url)
    
    return filtered_img_urls, filtered_video_urls

def download_image_with_browser(driver, image_url, save_dir, idx):
    """使用浏览器直接下载图片
    
    Args:
        driver: Selenium WebDriver实例
        image_url: 图片URL
        save_dir: 保存目录
        idx: 图片索引
    
    Returns:
        bool: 是否成功下载
    """
    try:
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        # 处理带标记的URL
        if image_url.startswith('poster:'):
            # 提取帖子ID和真实URL
            parts = image_url.split(':', 2)
            if len(parts) == 3:
                post_id = parts[1]
                real_url = parts[2]
                
                # 处理本地文件URL
                if real_url.startswith('file://'):
                    # 从URL中提取文件路径
                    file_path = real_url[7:]
                    if os.path.exists(file_path):
                        # 构建目标文件名，使用帖子ID
                        target_file = os.path.join(save_dir, f"poster_{post_id}.png")
                        
                        # 复制文件
                        import shutil
                        shutil.copy2(file_path, target_file)
                        print(f"  - 已保存视频封面图: {os.path.basename(target_file)}")
                        
                        # 删除原始截图文件
                        os.remove(file_path)
                        
                        return True
                    return False
                
                # 构建文件名，使用帖子ID
                ext = real_url.split('?')[0].split('.')[-1]
                if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                    ext = 'jpg'
                    
                filename = os.path.join(save_dir, f"poster_{post_id}.{ext}")
                
                # 更新image_url为真实URL
                image_url = real_url
            else:
                # 构建默认文件名
                filename = os.path.join(save_dir, f"img_{idx:04d}.jpg")
        else:
            # 构建默认文件名
            ext = image_url.split('?')[0].split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                ext = 'jpg'
                
            filename = os.path.join(save_dir, f"img_{idx:04d}.{ext}")
        
        # 检查文件是否已存在
        if os.path.exists(filename):
            print(f"文件已存在，跳过: {filename}")
            return True
            
        print(f"下载图片: {os.path.basename(filename)}")
        
        # 方法1: 直接使用requests下载
        try:
            print("  - 方法1: 使用requests下载...")
            
            # 构建自定义请求头
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Referer': 'https://www.instagram.com/',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
            }
            
            resp = requests.get(image_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # 验证是否是图片
                content_type = resp.headers.get('Content-Type', '')
                if content_type.startswith('image/'):
                    with open(filename, 'wb') as f:
                        f.write(resp.content)
                    
                    # 验证是否为有效图片
                    if os.path.exists(filename) and os.path.getsize(filename) > 5000:
                        return True
                else:
                    print(f"  - 不是图片内容: {content_type}")
            else:
                print(f"  - 请求失败: {resp.status_code}")
        except Exception as e:
            print(f"  - 请求下载失败: {e}")
        
        # 方法2: 使用curl命令下载
        try:
            print("  - 方法2: 使用curl命令下载...")
            
            # 构建curl命令
            curl_cmd = [
                'curl',
                '-L',
                '-o', filename,
                '-H', f'User-Agent: {CONFIG["user_agent"]}',
                '-H', 'Referer: https://www.instagram.com/',
                image_url
            ]
            
            # 执行命令
            import subprocess
            subprocess.run(curl_cmd, check=True, timeout=15, capture_output=True)
            
            # 验证文件
            if os.path.exists(filename) and os.path.getsize(filename) > 5000:
                return True
        except Exception as e:
            print(f"  - Curl下载失败: {e}")
        
        print("  - 所有方法都失败了")
        return False
    except Exception as e:
        print(f"图片下载总体失败: {e}")
        return False

def download_video_with_browser(driver, video_url, save_dir, idx):
    """使用浏览器直接下载视频
    
    Args:
        driver: Selenium WebDriver实例
        video_url: 视频URL
        save_dir: 保存目录
        idx: 视频索引
    
    Returns:
        bool: 是否成功下载
    """
    try:
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        # 处理带标记的URL
        if video_url.startswith('video:'):
            # 提取帖子ID和真实URL
            parts = video_url.split(':', 2)
            if len(parts) == 3:
                post_id = parts[1]
                real_url = parts[2]
                
                # 处理特殊标记
                if real_url.startswith('post_url:'):
                    # 提取帖子URL
                    post_url = real_url[9:]
                    print(f"下载视频: 从帖子URL下载视频 - {post_id}")
                    
                    # 构建文件名，使用帖子ID
                    filename = os.path.join(save_dir, f"video_{post_id}.mp4")
                    
                    # 访问帖子页面
                    driver.get(post_url)
                    time.sleep(5)  # 增加等待时间确保页面完全加载

                    # 检测是否是voidstomper的视频，使用特殊方法处理
                    if "voidstomper" in post_url.lower():
                        print("  - 检测到voidstomper账号的视频，使用特殊方法处理")
                        
                        # 使用更多的等待时间确保页面完全加载
                        time.sleep(3)
                        
                        # 尝试点击视频区域以确保视频加载
                        try:
                            # 尝试点击视频元素
                            video_elements = driver.find_elements(By.TAG_NAME, "video")
                            if video_elements:
                                # 滚动到视频元素
                                driver.execute_script("arguments[0].scrollIntoView();", video_elements[0])
                                time.sleep(2)
                                
                                # 点击视频元素
                                actions = ActionChains(driver)
                                actions.move_to_element(video_elements[0]).click().perform()
                                time.sleep(3)
                                
                                # 获取视频地址
                                video_src = driver.execute_script("""
                                const videos = document.querySelectorAll('video');
                                for(let v of videos) {
                                    if(v.src && v.src !== "") {
                                        return v.src;
                                    }
                                    
                                    // 检查video的currentSrc属性
                                    if(v.currentSrc && v.currentSrc !== "") {
                                        return v.currentSrc;
                                    }
                                }
                                return null;
                                """)
                                
                                if video_src and not video_src.startswith("blob:"):
                                    print(f"  - 直接从视频元素找到链接: {video_src}")
                                    
                                    # 使用ffmpeg直接下载视频流
                                    try:
                                        print("  - 尝试使用ffmpeg下载视频流")
                                        import subprocess
                                        cmd = [
                                            'ffmpeg',
                                            '-i', video_src,
                                            '-c', 'copy',
                                            '-y',
                                            filename
                                        ]
                                        
                                        # 执行ffmpeg命令
                                        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                                        
                                        if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                            print(f"  - 使用ffmpeg成功下载视频: {os.path.basename(filename)}")
                                            return True
                                    except Exception as e:
                                        print(f"  - 使用ffmpeg下载失败: {e}")
                        except Exception as e:
                            print(f"  - 点击视频元素失败: {e}")
                        
                        # 尝试直接从网页HTML获取真实视频URL
                        print("  - 尝试从网页源码中提取真实视频URL")
                        page_source = driver.page_source
                        
                        # 视频URL模式匹配 - 专门针对Instagram Reels
                        reels_patterns = [
                            r'"video_url":"(https:[^"]+)"',
                            r'"video_versions":\[\{"type":[0-9]+,"width":[0-9]+,"height":[0-9]+,"url":"([^"]+)"',
                            r'"progressive_url":"(https:[^"]+)"',
                            r'"permalinkUrl":"[^"]+","video":{"contentUrl":"([^"]+)"',
                            r'<meta property="og:video" content="([^"]+)"',
                            r'<meta property="og:video:secure_url" content="([^"]+)"'
                        ]
                        
                        # 优先尝试提取video_url字段
                        for pattern in reels_patterns:
                            matches = re.findall(pattern, page_source)
                            if matches and len(matches) > 0:
                                video_url = matches[0]
                                # 处理转义字符
                                video_url = video_url.replace('\\u0026', '&').replace('\\/', '/')
                                
                                print(f"  - 从源码中提取到真实视频URL: {video_url}")
                                
                                # 使用curl下载
                                try:
                                    import subprocess
                                    curl_cmd = [
                                        'curl',
                                        '-L',
                                        '-A', CONFIG['user_agent'],
                                        '-o', filename,
                                        video_url
                                    ]
                                    
                                    subprocess.run(curl_cmd, check=True, timeout=60, capture_output=True)
                                    
                                    if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                        # 验证文件是否为视频
                                        file_type_cmd = ['file', '-b', '--mime-type', filename]
                                        file_type = subprocess.run(file_type_cmd, check=True, capture_output=True, text=True).stdout.strip()
                                        
                                        if file_type.startswith('video/'):
                                            print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                            return True
                                        else:
                                            print(f"  - 下载的文件不是视频: {file_type}")
                                            os.remove(filename)
                                except Exception as e:
                                    print(f"  - 使用curl下载失败: {e}")
                        
                        # 如果上述方法失败，尝试最后的办法 - 使用ffmpeg录制屏幕中的视频
                        try:
                            print("  - 尝试使用ffmpeg录制屏幕中的视频")
                            
                            # 获取视频元素的位置和大小
                            video_element = driver.find_element(By.TAG_NAME, "video")
                            location = video_element.location
                            size = video_element.size
                            
                            # 计算视频元素在屏幕上的坐标
                            x = location['x']
                            y = location['y']
                            width = size['width']
                            height = size['height']
                            
                            # 准备ffmpeg命令 - 使用屏幕录制
                            # 注意：这种方法需要系统支持屏幕录制，可能不适用于所有系统
                            import subprocess
                            import platform
                            
                            if platform.system() == 'Darwin':  # macOS
                                # 点击视频元素开始播放
                                actions = ActionChains(driver)
                                actions.move_to_element(video_element).click().perform()
                                time.sleep(1)
                                
                                # 使用QuickTime Player录制
                                # 由于这需要UI交互，这里只提供一个提示
                                print("  - 无法自动下载，请尝试手动步骤:")
                                print("  - 1. 使用QuickTime Player进行屏幕录制")
                                print(f"  - 2. 捕获位置: x={x}, y={y}, 宽={width}, 高={height}")
                                print(f"  - 3. 将录制的视频保存为: {filename}")
                                
                                # 保存一个视频封面图片作为参考
                                thumbnail_file = filename.replace('.mp4', '_thumbnail.png')
                                video_element.screenshot(thumbnail_file)
                                print(f"  - 已保存视频缩略图: {os.path.basename(thumbnail_file)}")
                        except Exception as e:
                            print(f"  - 录制视频失败: {e}")
                    
                    # 首先尝试使用yt-dlp下载（首选方法）
                    print("方法1: 尝试使用第三方工具下载...")
                    try:
                        # 使用yt-dlp/youtube-dl下载
                        import subprocess
                        cmd = [
                            'yt-dlp',
                            '--quiet',
                            '--no-warnings',
                            '-o', filename,
                            post_url
                        ]
                        
                        # 首先检查是否安装了yt-dlp
                        try:
                            subprocess.run(['which', 'yt-dlp'], check=True, capture_output=True)
                            print("  - 检测到yt-dlp，尝试使用它下载...")
                            subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                            
                            if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                print(f"  - 使用yt-dlp成功下载视频: {os.path.basename(filename)}")
                                
                                # 验证下载的文件是否为真实视频文件
                                import mimetypes
                                mime_type, _ = mimetypes.guess_type(filename)
                                if mime_type and mime_type.startswith('video/'):
                                    return True
                                
                                # 使用file命令检查文件类型
                                try:
                                    file_check = subprocess.run(['file', '-b', '--mime-type', filename], 
                                                              capture_output=True, text=True, check=True)
                                    file_type = file_check.stdout.strip()
                                    if file_type.startswith('video/'):
                                        return True
                                    else:
                                        print(f"  - 警告：下载的文件不是视频 ({file_type})，尝试其他方法")
                                        # 如果不是视频文件，删除它并尝试其他方法
                                        os.remove(filename)
                                except:
                                    pass
                        except:
                            # 如果没有yt-dlp，尝试使用youtube-dl
                            try:
                                cmd[0] = 'youtube-dl'
                                subprocess.run(['which', 'youtube-dl'], check=True, capture_output=True)
                                print("  - 检测到youtube-dl，尝试使用它下载...")
                                subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                                
                                if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                    print(f"  - 使用youtube-dl成功下载视频: {os.path.basename(filename)}")
                                    
                                    # 验证下载的文件是否为真实视频文件
                                    import mimetypes
                                    mime_type, _ = mimetypes.guess_type(filename)
                                    if mime_type and mime_type.startswith('video/'):
                                        return True
                                    
                                    # 使用file命令检查文件类型
                                    try:
                                        file_check = subprocess.run(['file', '-b', '--mime-type', filename], 
                                                                  capture_output=True, text=True, check=True)
                                        file_type = file_check.stdout.strip()
                                        if file_type.startswith('video/'):
                                            return True
                                        else:
                                            print(f"  - 警告：下载的文件不是视频 ({file_type})，尝试其他方法")
                                            # 如果不是视频文件，删除它并尝试其他方法
                                            os.remove(filename)
                                    except:
                                        pass
                            except:
                                print("  - 系统中未安装yt-dlp或youtube-dl")
                    except Exception as e:
                        print(f"  - 使用第三方工具下载失败: {e}")
                    
                    # 使用浏览器开发工具获取视频URL
                    print("方法2: 使用浏览器开发工具获取视频URL...")
                    
                    # 在页面上点击视频区域，尝试触发视频加载
                    try:
                        # 尝试点击视频元素
                        video_elements = driver.find_elements(By.TAG_NAME, "video")
                        if video_elements:
                            # 滚动到视频元素
                            driver.execute_script("arguments[0].scrollIntoView();", video_elements[0])
                            time.sleep(2)
                            
                            # 点击视频元素
                            actions = ActionChains(driver)
                            actions.move_to_element(video_elements[0]).click().perform()
                            time.sleep(3)
                    except:
                        pass
                    
                    # 获取网络请求日志中的视频URL
                    logs = driver.execute_script("""
                    var videoUrls = [];
                    var performance = window.performance || window.mozPerformance || window.msPerformance || window.webkitPerformance || {};
                    var network = performance.getEntries() || [];
                    
                    network.forEach(function(entry) {
                        var url = entry.name || '';
                        if(url.endsWith('.mp4') || 
                           url.includes('/video_url') || 
                           url.includes('/video/') || 
                           url.includes('videoplayback') ||
                           url.includes('blob:')) {
                            videoUrls.push(url);
                        }
                    });
                    
                    return videoUrls;
                    """)
                    
                    if logs and len(logs) > 0:
                        for log_url in logs:
                            if log_url.startswith('blob:'):
                                print(f"  - 发现blob视频URL，尝试处理: {log_url}")
                                continue
                                
                            # 过滤掉伪造的视频URL
                            if 'unified_cvc' in log_url or not (log_url.endswith('.mp4') or '/progressive_download/' in log_url):
                                print(f"  - 忽略无效视频URL: {log_url}")
                                continue
                                
                            if is_valid_url(log_url) and ('.mp4' in log_url or '/video/' in log_url or '/progressive_download/' in log_url):
                                print(f"  - 从网络日志中找到视频URL: {log_url}")
                                
                                # 直接下载
                                try:
                                    headers = {
                                        'User-Agent': CONFIG['user_agent'],
                                        'Referer': post_url,
                                        'Accept': '*/*'
                                    }
                                    
                                    resp = requests.get(log_url, headers=headers, timeout=30, stream=True)
                                    if resp.status_code == 200:
                                        # 检查Content-Type
                                        content_type = resp.headers.get('Content-Type', '')
                                        if not ('video/' in content_type or 'application/octet-stream' in content_type):
                                            print(f"  - 内容类型不是视频: {content_type}")
                                            continue
                                            
                                        with open(filename, 'wb') as f:
                                            for chunk in resp.iter_content(chunk_size=8192):
                                                if chunk:
                                                    f.write(chunk)
                                        
                                        if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                            # 验证下载的文件是否为真实视频文件
                                            import mimetypes
                                            mime_type, _ = mimetypes.guess_type(filename)
                                            if mime_type and mime_type.startswith('video/'):
                                                print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                                return True
                                            
                                            # 使用file命令检查文件类型
                                            try:
                                                file_check = subprocess.run(['file', '-b', '--mime-type', filename], 
                                                                         capture_output=True, text=True, check=True)
                                                file_type = file_check.stdout.strip()
                                                if file_type.startswith('video/'):
                                                    print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                                    return True
                                                else:
                                                    print(f"  - 警告：下载的文件不是视频 ({file_type})，尝试其他方法")
                                                    # 如果不是视频文件，删除它并尝试其他方法
                                                    os.remove(filename)
                                            except:
                                                # 无法确定文件类型，假设成功
                                                print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                                return True
                                except Exception as e:
                                    print(f"  - 下载视频失败: {e}")
                    
                    # 尝试方法3：使用JavaScript提取视频URL
                    print("方法3: 尝试使用JavaScript提取视频URL...")
                    js_video_url = driver.execute_script("""
                    function getVideoUrl() {
                        // 尝试方法1: 寻找所有的视频元素
                        const videos = document.querySelectorAll('video');
                        for (const video of videos) {
                            // 检查视频源
                            if (video.src && !video.src.startsWith('blob:')) {
                                return video.src;
                            }
                            
                            // 检查source子元素
                            const sources = video.querySelectorAll('source');
                            for (const source of sources) {
                                if (source.src && !source.src.startsWith('blob:')) {
                                    return source.src;
                                }
                            }
                            
                            // 检查video的currentSrc属性
                            if (video.currentSrc && !video.currentSrc.startsWith('blob:')) {
                                return video.currentSrc;
                            }
                        }
                        
                        // 尝试方法2: 从meta标签提取
                        const videoMeta = document.querySelector('meta[property="og:video"]');
                        if (videoMeta && videoMeta.content) {
                            return videoMeta.content;
                        }
                        
                        // 尝试方法3: 从页面脚本中提取
                        const scripts = document.querySelectorAll('script');
                        for (const script of scripts) {
                            const content = script.textContent || '';
                            
                            // 检查是否包含video_url字段
                            const videoUrlMatch = content.match(/"video_url":"([^"]+)"/);
                            if (videoUrlMatch && videoUrlMatch[1]) {
                                return videoUrlMatch[1].replace(/\\u0026/g, '&');
                            }
                            
                            // 检查是否包含progressive_url字段
                            const progressiveUrlMatch = content.match(/"progressive_url":"([^"]+)"/);
                            if (progressiveUrlMatch && progressiveUrlMatch[1]) {
                                return progressiveUrlMatch[1].replace(/\\u0026/g, '&');
                            }
                        }
                        
                        return null;
                    }
                    
                    return getVideoUrl();
                    """)
                    
                    if js_video_url and is_valid_url(js_video_url) and not js_video_url.startswith('blob:'):
                        print(f"  - 从JavaScript中提取到视频URL: {js_video_url}")
                        
                        # 下载视频
                        try:
                            headers = {
                                'User-Agent': CONFIG['user_agent'],
                                'Referer': post_url,
                                'Accept': '*/*'
                            }
                            
                            resp = requests.get(js_video_url, headers=headers, timeout=30, stream=True)
                            if resp.status_code == 200:
                                # 检查Content-Type
                                content_type = resp.headers.get('Content-Type', '')
                                if not ('video/' in content_type or 'application/octet-stream' in content_type):
                                    print(f"  - 内容类型不是视频: {content_type}")
                                else:
                                    with open(filename, 'wb') as f:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                f.write(chunk)
                                    
                                    if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                        # 验证下载的文件是否为真实视频文件
                                        import mimetypes
                                        mime_type, _ = mimetypes.guess_type(filename)
                                        if mime_type and mime_type.startswith('video/'):
                                            print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                            return True
                                        
                                        # 使用file命令检查文件类型
                                        try:
                                            file_check = subprocess.run(['file', '-b', '--mime-type', filename], 
                                                                     capture_output=True, text=True, check=True)
                                            file_type = file_check.stdout.strip()
                                            if file_type.startswith('video/'):
                                                print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                                return True
                                            else:
                                                print(f"  - 警告：下载的文件不是视频 ({file_type})，尝试其他方法")
                                                # 如果不是视频文件，删除它并尝试其他方法
                                                os.remove(filename)
                                        except:
                                            # 无法确定文件类型，假设成功
                                            print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                            return True
                        except Exception as e:
                            print(f"  - 下载视频失败: {e}")
                    
                    # 如果所有方法都失败，截取视频截图并提示安装工具
                    print("  - 所有视频提取方法都失败!")
                    print("  - 建议安装yt-dlp工具以获取更好的视频下载支持")
                    print("  - 命令: pip install yt-dlp")
                    
                    # 保存视频截图
                    screenshot_file = filename.replace('.mp4', '.png')
                    driver.save_screenshot(screenshot_file)
                    print(f"  - 已保存视频界面截图: {os.path.basename(screenshot_file)}")
                    return False
                
                # 更新video_url为真实URL
                video_url = real_url
                
                # 构建文件名，使用帖子ID
                filename = os.path.join(save_dir, f"video_{post_id}.mp4")
            else:
                # 构建默认文件名
                filename = os.path.join(save_dir, f"video_{idx:04d}.mp4")
        else:
            # 构建默认文件名
            filename = os.path.join(save_dir, f"video_{idx:04d}.mp4")
        
        # 检查文件是否已存在
        if os.path.exists(filename):
            print(f"文件已存在，跳过: {filename}")
            return True
            
        print(f"下载视频: {os.path.basename(filename)}")
        
        # 方法1: 直接使用requests下载
        try:
            print("  - 方法1: 使用requests下载...")
            
            # 构建自定义请求头
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Referer': 'https://www.instagram.com/',
                'Accept': '*/*'
            }
            
            resp = requests.get(video_url, headers=headers, timeout=30, stream=True)
            if resp.status_code == 200:
                # 验证是否是视频
                content_type = resp.headers.get('Content-Type', '')
                if 'video/' in content_type or 'octet-stream' in content_type:
                    with open(filename, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # 验证是否为有效视频
                    if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                        print(f"  - 成功下载视频: {os.path.basename(filename)}")
                        return True
                else:
                    print(f"  - 不是视频内容: {content_type}")
            else:
                print(f"  - 请求失败: {resp.status_code}")
        except Exception as e:
            print(f"  - 请求下载失败: {e}")
        
        # 方法2: 使用curl命令下载
        try:
            print("  - 方法2: 使用curl命令下载...")
            
            # 构建curl命令
            curl_cmd = [
                'curl',
                '-L',
                '-o', filename,
                '-H', f'User-Agent: {CONFIG["user_agent"]}',
                '-H', 'Referer: https://www.instagram.com/',
                video_url
            ]
            
            # 执行命令
            import subprocess
            subprocess.run(curl_cmd, check=True, timeout=30, capture_output=True)
            
            # 验证文件
            if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                print(f"  - 成功下载视频: {os.path.basename(filename)}")
                return True
        except Exception as e:
            print(f"  - Curl下载失败: {e}")
        
        print("  - 所有方法都失败了")
        return False
    except Exception as e:
        print(f"视频下载总体失败: {e}")
        return False

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Instagram媒体采集工具')
    parser.add_argument('--username', '-u', type=str, help='Instagram用户名')
    parser.add_argument('--test', '-t', action='store_true', help='测试模式，只爬取少量帖子')
    parser.add_argument('--count', '-c', type=int, default=3, help='测试模式下爬取的帖子数量，默认为3')
    parser.add_argument('--all', '-a', action='store_true', help='爬取所有媒体，不限制数量')
    return parser.parse_args()

def main():
    """主函数"""
    args = parse_args()
    username = args.username
    test_mode = args.test
    count = args.count
    download_all = args.all
    
    print("=" * 50)
    print("Instagram媒体采集工具")
    print("=" * 50)
    
    if test_mode:
        print(f"测试模式已启用，最多爬取 {count} 个帖子")
    
    if not username:
        username = input("请输入Instagram用户名: ")
    
    print(f"正在获取用户 {username} 的数据...")
    
    # 初始化浏览器
    driver = get_browser_instance()
    
    try:
        # 首先打开Instagram并等待用户手动登录
        print("正在打开Instagram登录页面...")
        driver.get("https://www.instagram.com/")
        
        # 检查是否需要登录
        time.sleep(3)
        login_required = True
        
        # 检查是否已经登录
        try:
            profile_icon = driver.find_element(By.XPATH, "//div[@role='button' and contains(@aria-label, 'profile')]")
            if profile_icon:
                print("检测到您已经登录Instagram")
                login_required = False
        except:
            login_required = True
        
        # 等待用户手动登录
        if login_required:
            print("\n" + "="*50)
            print("请在浏览器中手动登录Instagram账号")
            print("登录成功后，请在此处按回车键继续...")
            print("="*50 + "\n")
            input("等待登录完成，按回车继续...")
        
        # 直接访问用户主页
        user_url = f"https://www.instagram.com/{username}/"
        print(f"正在访问用户主页: {user_url}")
        driver.get(user_url)
        time.sleep(5)  # 稍微增加等待时间
        
        # 尝试获取用户信息
        print("尝试获取用户信息...")
        
        # 无限滚动加载更多内容
        print("正在滚动页面加载所有内容...")
        scroll_count = 0
        max_scrolls = 50  # 限制滚动次数
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        while scroll_count < max_scrolls:
            scroll_count += 1
            print(f"滚动进度: {scroll_count}/{max_scrolls}")
            
            # 滚动到页面底部
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # 计算新的滚动高度并与上一个滚动高度进行比较
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                # 如果高度没有变化，尝试点击"加载更多"按钮
                try:
                    load_more_button = driver.find_element(By.XPATH, "//button[contains(., 'Load more')]")
                    load_more_button.click()
                    time.sleep(2)
                except:
                    # 如果没有找到按钮或者点击失败，则退出循环
                    break
            
            last_height = new_height
        
        # 提取帖子链接
        print("正在提取帖子链接...")
        
        # 使用增强的JavaScript提取所有帖子链接
        js_script = """
        function getPostLinks() {
            const links = [];
            
            // 方法1：查找所有链接
            const allLinks = document.querySelectorAll('a');
            allLinks.forEach(a => {
                const href = a.getAttribute('href');
                if (href && (href.includes('/p/') || href.includes('/reel/'))) {
                    // 确保是完整URL
                    if (href.startsWith('http')) {
                        links.push(href);
                    } else {
                        links.push('https://www.instagram.com' + href);
                    }
                }
            });
            
            // 方法2：查找图片容器并获取父级链接
            const imgContainers = document.querySelectorAll('div[role="button"]');
            imgContainers.forEach(container => {
                const parent = container.closest('a');
                if (parent) {
                    const href = parent.getAttribute('href');
                    if (href && (href.includes('/p/') || href.includes('/reel/'))) {
                        if (href.startsWith('http')) {
                            links.push(href);
                        } else {
                            links.push('https://www.instagram.com' + href);
                        }
                    }
                }
            });
            
            // 方法3：查找带有图片的链接
            const imgLinks = document.querySelectorAll('a:has(img)');
            imgLinks.forEach(a => {
                const href = a.getAttribute('href');
                if (href && (href.includes('/p/') || href.includes('/reel/'))) {
                    if (href.startsWith('http')) {
                        links.push(href);
                    } else {
                        links.push('https://www.instagram.com' + href);
                    }
                }
            });
            
            return [...new Set(links)]; // 去重
        }
        
        return getPostLinks();
        """
        
        post_links = driver.execute_script(js_script)
        
        # 如果JavaScript方法失败，尝试其他方法
        if not post_links:
            print("JavaScript方法未提取到链接，尝试直接提取图片元素...")
            
            # 保存整个页面截图
            timestamp = int(time.time())
            screenshot_file = f"profile_{username}_{timestamp}.png"
            driver.save_screenshot(screenshot_file)
            print(f"已保存用户主页截图: {screenshot_file}")
            
            # 查找所有图片元素，点击它们以进入帖子
            img_elements = driver.find_elements(By.CSS_SELECTOR, "img[crossorigin='anonymous']")
            print(f"找到 {len(img_elements)} 个图片元素")
            
            if img_elements and len(img_elements) > 0:
                post_links = []
                
                # 限制最多处理的元素数量
                max_elements = min(count * 2 if test_mode else 10, len(img_elements))
                
                for i in range(max_elements):
                    try:
                        # 滚动到元素位置
                        driver.execute_script("arguments[0].scrollIntoView();", img_elements[i])
                        time.sleep(1)
                        
                        # 尝试点击图片
                        try:
                            img_elements[i].click()
                            time.sleep(3)
                            
                            # 获取当前URL
                            current_url = driver.current_url
                            if '/p/' in current_url or '/reel/' in current_url:
                                post_links.append(current_url)
                                print(f"  - 成功点击进入帖子: {current_url}")
                            
                            # 返回主页
                            driver.back()
                            time.sleep(2)
                        except:
                            print(f"  - 无法点击第 {i+1} 个图片元素")
                            continue
                    except:
                        continue
            
            # 如果还是没有找到任何链接，使用常规方法
            if not post_links:
                print("尝试使用常规方法提取链接...")
                
                # 查找所有帖子链接元素
                post_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/p/') or contains(@href, '/reel/')]")
                
                post_links = []
                for element in post_elements:
                    href = element.get_attribute("href")
                    if href and ("instagram.com/p/" in href or "instagram.com/reel/" in href):
                        post_links.append(href)
        
        # 去重
        post_links = list(dict.fromkeys(post_links))
        
        # 如果是测试模式，限制爬取数量
        if test_mode and len(post_links) > count:
            print(f"测试模式: 限制爬取 {count}/{len(post_links)} 个帖子")
            post_links = post_links[:count]
        
        print(f"共提取到 {len(post_links)} 个帖子链接")
        
        # 访问每个帖子并提取媒体
        img_urls = set()
        video_urls = set()
        
        print("正在访问帖子提取媒体...")
        for i, post_url in enumerate(post_links):
            print(f"处理帖子 {i+1}/{len(post_links)}: {post_url}")
            post_img_urls, post_video_urls = extract_media_from_post(driver, post_url)
            
            # 合并媒体URL
            img_urls.update(post_img_urls)
            video_urls.update(post_video_urls)
            
            print(f"  - 提取到 {len(post_img_urls)} 张图片, {len(post_video_urls)} 个视频")
            
            # 添加一点延迟，避免请求过快
            time.sleep(1)
        
        print(f"浏览器模拟完成: 共提取到 {len(img_urls)} 张图片, {len(video_urls)} 个视频")
    
        # 创建保存目录
        save_dir = os.path.join("data", username)
        img_dir = os.path.join(save_dir, "images")
        video_dir = os.path.join(save_dir, "videos")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)
        
        # 下载图片
        if img_urls:
            print("开始下载图片...")
            
            # 如果是测试模式且图片数量大于限制，则只下载部分
            download_img_urls = list(img_urls)
            if test_mode and len(download_img_urls) > count:
                print(f"限制下载 {count}/{len(download_img_urls)} 张图片，避免过多请求")
                download_img_urls = download_img_urls[:count]
            
            success_count = 0
            fail_count = 0
            
            for i, img_url in enumerate(download_img_urls):
                if download_image_with_browser(driver, img_url, img_dir, i):
                    success_count += 1
                else:
                    fail_count += 1
            
            print(f"图片下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
        else:
            print("未找到图片URL")
        
        # 下载视频
        if video_urls:
            print("开始下载视频...")
            
            # 如果是测试模式且视频数量大于限制，则只下载部分
            download_video_urls = list(video_urls)
            if test_mode and len(download_video_urls) > count:
                print(f"限制下载 {count}/{len(download_video_urls)} 个视频，避免过多请求")
                download_video_urls = download_video_urls[:count]
            
            success_count = 0
            fail_count = 0
            
            for i, video_url in enumerate(download_video_urls):
                if download_video_with_browser(driver, video_url, video_dir, i):
                    success_count += 1
                else:
                    fail_count += 1
            
            print(f"视频下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
        else:
            print("未找到视频URL")
            
        # 完成前等待用户确认
        print("\n" + "="*50)
        print("采集任务已完成!")
        print("按回车键关闭浏览器并退出...")
        print("="*50 + "\n")
        input("按回车键继续...")
    finally:
        # 确保无论如何都关闭浏览器
        try:
            driver.quit()
        except:
            pass
    
    print("=" * 50)
    print("采集任务完成")
    print("=" * 50)

def get_user_media(username, user_id, cookies):
    """通过API获取用户媒体数据
    
    Args:
        username: Instagram用户名
        user_id: 用户ID
        cookies: cookie字典
    
    Returns:
        tuple: (图片URL列表, 视频URL列表) 或 (None, None)
    """
    print("正在通过API获取用户媒体数据...")
    
    # 初始化媒体URL集合
    img_urls = set()
    video_urls = set()
    
    try:
        # 初始化请求
        headers = {
            'User-Agent': CONFIG['user_agent'],
            'X-IG-App-ID': CONFIG['ig_app_id'],
            'Referer': f'https://www.instagram.com/{username}/'
        }
        
        # 获取用户首页帖子
        end_cursor = None
        page = 1
        has_next_page = True
        
        while has_next_page:
            print(f"正在请求第 {page} 页数据...")
            
            # 构建GraphQL查询
            variables = {
                'id': user_id,
                'first': 50
            }
            
            if end_cursor:
                variables['after'] = end_cursor
            
            # 将变量转换为JSON字符串并进行URL编码
            variables_str = json.dumps(variables)
            
            # 构建请求URL
            url = f"https://www.instagram.com/graphql/query/?query_hash={CONFIG['query_hashes']['user_posts']}&variables={variables_str}"
            
            # 发送请求
            resp = requests.get(url, headers=headers, cookies=cookies, timeout=CONFIG['request_timeout'])
            
            # 检查响应
            if resp.status_code != 200:
                print(f"API请求失败: HTTP {resp.status_code}")
                break
            
            # 解析JSON响应
            try:
                data = resp.json()
            except:
                print(f"API返回非JSON内容: {resp.headers.get('Content-Type', '')}")
                break
            
            # 提取媒体数据
            try:
                edge_owner_to_timeline_media = data['data']['user']['edge_owner_to_timeline_media']
                edges = edge_owner_to_timeline_media['edges']
                page_info = edge_owner_to_timeline_media['page_info']
                
                # 提取媒体URL
                for edge in edges:
                    node = edge['node']
                    
                    # 提取图片URL
                    if 'display_url' in node:
                        img_urls.add(node['display_url'])
                    
                    # 提取视频URL
                    if node.get('is_video', False) and 'video_url' in node:
                        video_urls.add(node['video_url'])
                    
                    # 提取多媒体帖子
                    if 'edge_sidecar_to_children' in node:
                        children = node['edge_sidecar_to_children']['edges']
                        for child in children:
                            child_node = child['node']
                            
                            # 提取图片URL
                            if 'display_url' in child_node:
                                img_urls.add(child_node['display_url'])
                            
                            # 提取视频URL
                            if child_node.get('is_video', False) and 'video_url' in child_node:
                                video_urls.add(child_node['video_url'])
                
                # 检查是否有下一页
                has_next_page = page_info.get('has_next_page', False)
                end_cursor = page_info.get('end_cursor')
                
                # 增加页码
                page += 1
                
                # 添加延迟
                time.sleep(CONFIG['request_delay'])
            except Exception as e:
                print(f"解析媒体数据异常: {e}")
                break
        
        # 过滤媒体URL
        filtered_img_urls, filtered_video_urls = filter_media_urls(img_urls, video_urls)
        
        # 返回媒体URL
        return filtered_img_urls, filtered_video_urls
    except Exception as e:
        print(f"获取用户媒体异常: {e}")
        return None, None

def selenium_fallback(username, cookies, save_dir):
    """当API方法失败时的浏览器模拟方法
    
    Args:
        username: Instagram用户名
        cookies: cookie字典
        save_dir: 保存目录
    """
    print("API方法失败，正在启动浏览器模拟...")
    
    # 配置Chrome选项
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--lang=zh-CN")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"user-agent={CONFIG['user_agent']}")
    
    # 设置下载路径
    prefs = {
        "download.default_directory": os.path.abspath(os.path.join(save_dir, 'videos')),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    # 初始化媒体URL集合
    img_urls = set()
    video_urls = set()
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        
        # 访问Instagram并设置cookie
        print("正在初始化浏览器会话...")
        driver.get("https://www.instagram.com/")
        for k, v in cookies.items():
            driver.add_cookie({'name': k, 'value': v})
            
        # 访问用户主页
        url = f"https://www.instagram.com/{username}/"
        print(f"正在访问用户主页: {url}")
        driver.get(url)
        time.sleep(5)
        
        # 检查是否成功加载
        if "Page Not Found" in driver.title or "页面不存在" in driver.title:
            print(f"用户 {username} 不存在或已被删除")
            driver.quit()
            return
        
        # 获取用户信息
        print("尝试获取用户信息...")
        
        # 滚动页面加载所有内容
        print("正在滚动页面加载所有内容...")
        scroll_count = 50  # 最大滚动次数
        for i in range(scroll_count):
            print(f"滚动进度: {i+1}/{scroll_count}")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
        
        # 提取帖子链接
        print("正在提取帖子链接...")
        all_links = []
        a_elements = driver.find_elements(By.TAG_NAME, "a")
        for a in a_elements:
            href = a.get_attribute("href")
            if href:
                all_links.append(href)
        
        # 尝试直接从页面提取媒体
        print("尝试直接从页面提取媒体...")
        
        # 过滤并处理链接
        post_links = []
        for link in all_links:
            # 确保链接是完整的URL
            if not link.startswith('http'):
                link = 'https://www.instagram.com' + link
            
            # 确保链接是帖子链接
            if '/p/' in link or '/reel/' in link or '/tv/' in link:
                # 移除查询参数
                clean_link = link.split('?')[0]
                post_links.append(clean_link)
        
        # 去重
        post_links = list(set(post_links))
        
        # 访问每个帖子并提取媒体
        if post_links:
            # 根据测试模式和最大帖子数量限制帖子数
            if CONFIG['test_mode'] and CONFIG['max_posts'] > 0:
                original_count = len(post_links)
                post_links = post_links[:CONFIG['max_posts']]
                print(f"测试模式: 限制爬取 {len(post_links)}/{original_count} 个帖子")
            
            print(f"共提取到 {len(post_links)} 个帖子链接")
            all_img_urls = set(img_urls)  # 合并已经提取到的媒体URL
            all_video_urls = set(video_urls)
            
            print("正在访问帖子提取媒体...")
            for idx, post_url in enumerate(post_links):
                print(f"处理帖子 {idx+1}/{len(post_links)}: {post_url}")
                
                # 访问帖子页面
                try:
                    # 提取媒体URL
                    post_imgs, post_videos = extract_media_from_post(driver, post_url)
                    
                    # 合并到总集合
                    all_img_urls.update(post_imgs)
                    all_video_urls.update(post_videos)
                    
                    print(f"  - 提取到 {len(post_imgs)} 张图片, {len(post_videos)} 个视频")
                except Exception as e:
                    print(f"  - 处理帖子异常: {e}")
            
            # 统计结果
            print(f"浏览器模拟完成: 共提取到 {len(all_img_urls)} 张图片, {len(all_video_urls)} 个视频")
            
            # 下载媒体
            if all_img_urls:
                print("开始下载图片...")
                print("正在使用浏览器直接下载图片，这样可以绕过Instagram的反爬虫限制...")
                img_dir = os.path.join(save_dir, 'images')
                os.makedirs(img_dir, exist_ok=True)
                
                success_count = 0
                failed_count = 0
                
                # 限制下载数量，避免过多请求
                download_limit = 20 if not CONFIG['test_mode'] else min(len(all_img_urls), 10)
                limited_img_urls = list(all_img_urls)[:download_limit]
                
                print(f"限制下载 {len(limited_img_urls)}/{len(all_img_urls)} 张图片，避免过多请求")
                
                for idx, img_url in enumerate(limited_img_urls):
                    if download_image_with_browser(driver, img_url, img_dir, idx):
                        success_count += 1
                    else:
                        failed_count += 1
                        
                print(f"图片下载完成: 成功 {success_count} 个, 失败 {failed_count} 个")
            
            if all_video_urls:
                print("开始下载视频...")
                print("正在使用浏览器直接下载视频，这样可以绕过Instagram的反爬虫限制...")
                video_dir = os.path.join(save_dir, 'videos')
                os.makedirs(video_dir, exist_ok=True)
                
                success_count = 0
                failed_count = 0
                
                for idx, video_url in enumerate(all_video_urls):
                    if download_video_with_browser(driver, video_url, video_dir, idx):
                        success_count += 1
                    else:
                        failed_count += 1
                
                print(f"视频下载完成: 成功 {success_count} 个, 失败 {failed_count} 个")
            
            print("浏览器模拟下载完成")
        else:
            print("未找到任何帖子链接")
            
            # 尝试直接从主页提取媒体
            print("尝试直接从主页提取媒体...")
            
            # 尝试查找媒体元素
            img_elements = driver.find_elements(By.TAG_NAME, "img")
            for img in img_elements:
                src = img.get_attribute("src")
                if src and is_valid_url(src) and src not in img_urls:
                    img_urls.add(src)
            
            video_elements = driver.find_elements(By.TAG_NAME, "video")
            for video in video_elements:
                src = video.get_attribute("src")
                if src and is_valid_url(src) and src not in video_urls:
                    video_urls.add(src)
            
            # 统计结果
            print(f"直接提取: 共提取到 {len(img_urls)} 张图片, {len(video_urls)} 个视频")
            
            # 下载媒体
            if img_urls:
                print("开始下载图片...")
                print("正在使用浏览器直接下载图片，这样可以绕过Instagram的反爬虫限制...")
                img_dir = os.path.join(save_dir, 'images')
                os.makedirs(img_dir, exist_ok=True)
                
                success_count = 0
                failed_count = 0
                
                # 限制下载数量，避免过多请求
                download_limit = 20 if not CONFIG['test_mode'] else min(len(img_urls), 10)
                limited_img_urls = list(img_urls)[:download_limit]
                
                print(f"限制下载 {len(limited_img_urls)}/{len(img_urls)} 张图片，避免过多请求")
                
                for idx, img_url in enumerate(limited_img_urls):
                    if download_image_with_browser(driver, img_url, img_dir, idx):
                        success_count += 1
                    else:
                        failed_count += 1
                        
                print(f"图片下载完成: 成功 {success_count} 个, 失败 {failed_count} 个")
            
            if video_urls:
                print("开始下载视频...")
                print("正在使用浏览器直接下载视频，这样可以绕过Instagram的反爬虫限制...")
                video_dir = os.path.join(save_dir, 'videos')
                os.makedirs(video_dir, exist_ok=True)
                
                success_count = 0
                failed_count = 0
                
                for idx, video_url in enumerate(video_urls):
                    if download_video_with_browser(driver, video_url, video_dir, idx):
                        success_count += 1
                    else:
                        failed_count += 1
                
                print(f"视频下载完成: 成功 {success_count} 个, 失败 {failed_count} 个")
        
        driver.quit()
    except Exception as e:
        print(f"浏览器模拟异常: {e}")
        try:
            driver.quit()
        except:
            pass
        return False
    
    return True

def is_valid_url(url):
    """检查URL是否有效
    
    Args:
        url: 待检查的URL
    
    Returns:
        bool: URL是否有效
    """
    if not url:
        return False
    
    # 检查URL是否以http或https开头
    if not url.startswith(('http://', 'https://')):
        return False
    
    # 检查URL是否包含非法字符
    if '"' in url or "'" in url or '<' in url or '>' in url:
        return False
    
    # 检查URL是否过短
    if len(url) < 10:
        return False
    
    return True

def get_browser_instance():
    """获取一个浏览器实例
    
    Returns:
        WebDriver: Selenium WebDriver实例
    """
    options = Options()
    # 设置无头模式，不显示浏览器窗口
    # options.add_argument("--headless")
    
    # 设置UA
    options.add_argument(f"user-agent={CONFIG['user_agent']}")
    
    # 禁用图片加载以提高速度（但对于我们的任务需要加载图片）
    # options.add_argument("--blink-settings=imagesEnabled=false")
    
    # 禁用扩展
    options.add_argument("--disable-extensions")
    
    # 禁用GPU加速
    options.add_argument("--disable-gpu")
    
    # 禁用开发者工具
    options.add_argument("--disable-dev-shm-usage")
    
    # 禁用沙盒
    options.add_argument("--no-sandbox")
    
    # 其他优化选项
    options.add_argument("--disable-features=NetworkService")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    
    # 初始化浏览器
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # 设置隐式等待时间
    driver.implicitly_wait(10)
    
    # 最大化窗口
    driver.maximize_window()
    
    return driver

# 为了兼容性，将init_browser设置为get_browser_instance的别名
init_browser = get_browser_instance

if __name__ == "__main__":
    main()

