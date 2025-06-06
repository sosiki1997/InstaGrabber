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
import shutil

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

def download_media(media_urls, save_dir):
    """下载媒体文件
    
    Args:
        media_urls: 包含图片和视频URL的字典
        save_dir: 保存目录
    """
    img_urls = media_urls.get('images', set())
    video_urls = media_urls.get('videos', set())
    
    img_dir = os.path.join(save_dir, "images")
    video_dir = os.path.join(save_dir, "videos")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    
    # 下载视频封面图片
    if img_urls:
        print("开始下载视频封面图片...")
        
        success_count = 0
        fail_count = 0
        
        # 创建一个临时的浏览器实例用于下载
        driver = get_browser_instance()
        try:
            for i, img_url in enumerate(img_urls):
                # 只处理视频封面图片
                if img_url.startswith('poster:'):
                    if download_image_with_browser(driver, img_url, img_dir, i):
                        success_count += 1
                    else:
                        fail_count += 1
        finally:
            driver.quit()
        
        print(f"视频封面图片下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    else:
        print("未找到视频封面图片")
    
    # 下载视频
    if video_urls:
        print("开始下载视频...")
        
        success_count = 0
        fail_count = 0
        
        # 创建一个临时的浏览器实例用于下载
        driver = get_browser_instance()
        try:
            for i, video_url in enumerate(video_urls):
                if download_video_with_browser(driver, video_url, video_dir, i):
                    success_count += 1
                else:
                    fail_count += 1
        finally:
            driver.quit()
        
        print(f"视频下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    else:
        print("未找到视频URL")

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
    """从Instagram帖子中提取媒体URL
    
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
        time.sleep(5)  # 增加等待时间确保页面完全加载
        
        # 提取帖子ID
        post_id = None
        if '/p/' in post_url:
            post_id = post_url.split('/p/')[1].split('/')[0]
        elif '/reel/' in post_url:
            post_id = post_url.split('/reel/')[1].split('/')[0]
        
        if post_id:
            print(f"  - 帖子ID: {post_id}")
        
        # 检测是否为视频帖子
        is_video = False
        
        # 方法1: 检查URL类型 - Reels几乎总是视频
        if '/reel/' in post_url:
            is_video = True
            print("  - 检测到Reel视频帖子")
        
        # 方法2: 检查视频元素
        if not is_video:
            try:
                video_elements = driver.find_elements(By.TAG_NAME, "video")
                if video_elements and len(video_elements) > 0:
                    is_video = True
                    print("  - 检测到视频元素")
            except Exception as e:
                print(f"  - 检查视频元素失败: {e}")
        
        # 方法3: 检查页面元素和属性
        if not is_video:
            try:
                # 查找可能表明这是视频的元素
                video_indicators = driver.find_elements(By.XPATH, 
                    "//span[contains(@aria-label, 'video') or contains(@aria-label, 'Video')]")
                if video_indicators and len(video_indicators) > 0:
                    is_video = True
                    print("  - 通过页面元素检测到视频")
            except:
                pass
                
        # 方法4: 使用JavaScript检测视频
        if not is_video:
            try:
                is_video_js = driver.execute_script("""
                    // 检查是否存在video标签
                    if (document.querySelector('video')) return true;
                    
                    // 检查是否有视频相关的属性
                    const videoAttrs = ['aria-label', 'alt', 'title'];
                    for (const attr of videoAttrs) {
                        const elements = document.querySelectorAll(`[${attr}*="video" i]`);
                        if (elements.length > 0) return true;
                    }
                    
                    // 检查meta标签
                    const ogType = document.querySelector('meta[property="og:type"]');
                    if (ogType && ogType.content && ogType.content.includes('video')) return true;
                    
                    // 检查SVG图标（播放按钮等）
                    const svgIcons = document.querySelectorAll('svg');
                    for (const svg of svgIcons) {
                        if (svg.innerHTML.includes('polygon') || svg.innerHTML.includes('path')) {
                            const rect = svg.getBoundingClientRect();
                            // 如果SVG图标大小合适，可能是播放按钮
                            if (rect.width > 20 && rect.height > 20) return true;
                        }
                    }
                    
                    return false;
                """)
                
                if is_video_js:
                    is_video = True
                    print("  - 通过JavaScript检测到视频")
            except:
                pass
        
        # 方法5: 强制假设所有帖子都可能包含视频
        # 这是最激进的方法，但可以确保不会漏掉视频
        if not is_video and post_id:
            print("  - 未检测到视频特征，但仍尝试下载视频")
            is_video = True
        
        # 如果是视频帖子，提取视频URL
        if is_video:
            # 提取视频URL
            try:
                # 使用特殊标记，表示这是帖子URL
                video_url = f"video:{post_id}:post_url:{post_url}"
                video_urls.add(video_url)
                print("  - 已添加视频URL到下载列表")
            except Exception as e:
                print(f"  - 提取视频URL失败: {e}")
                
            if len(video_urls) == 0:
                print("  - 检测到视频但未能提取URL")
        else:
            print("  - 未检测到视频，可能是图片帖子")
        
        return img_urls, video_urls
    except Exception as e:
        print(f"  - 提取媒体失败: {e}")
        return set(), set()

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

def download_image_with_browser(driver, img_url, save_dir, idx):
    """下载图片
    
    Args:
        driver: Selenium WebDriver实例
        img_url: 图片URL
        save_dir: 保存目录
        idx: 图片索引
    
    Returns:
        bool: 是否成功下载
    """
    try:
        # 确保目录存在
        os.makedirs(save_dir, exist_ok=True)
        
        # 处理带标记的URL
        if img_url.startswith('poster:'):
            # 提取帖子ID和真实URL
            parts = img_url.split(':', 2)
            if len(parts) == 3:
                post_id = parts[1]
                real_url = parts[2]
                
                # 构建文件名，使用帖子ID
                filename = os.path.join(save_dir, f"poster_{post_id}.jpg")
            else:
                # 构建默认文件名
                filename = os.path.join(save_dir, f"image_{idx:04d}.jpg")
        else:
            # 构建默认文件名
            filename = os.path.join(save_dir, f"image_{idx:04d}.jpg")
        
        # 检查文件是否已存在
        if os.path.exists(filename):
            print(f"文件已存在，跳过: {filename}")
            return True
            
        print(f"下载图片: {os.path.basename(filename)}")
        
        # 处理本地文件URL
        if img_url.startswith('file://'):
            local_path = img_url[7:]
            if os.path.exists(local_path):
                shutil.copy(local_path, filename)
                print(f"  - 已复制本地文件: {os.path.basename(filename)}")
                return True
            else:
                print(f"  - 本地文件不存在: {local_path}")
                return False
        
        # 方法1: 使用requests下载
        try:
            print("  - 方法1: 使用requests下载...")
            
            # 如果是带标记的URL，提取真实URL
            if img_url.startswith('poster:'):
                parts = img_url.split(':', 2)
                if len(parts) == 3:
                    real_url = parts[2]
                    img_url = real_url
            
            # 构建自定义请求头
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Referer': 'https://www.instagram.com/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
            }
            
            resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
            if resp.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                # 验证文件是否为图片
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    print(f"  - 成功下载图片: {os.path.basename(filename)}")
                    return True
            else:
                print(f"  - 请求失败: {resp.status_code}")
        except Exception as e:
            print(f"  - 请求下载失败: {e}")
        
        # 方法2: 使用curl命令下载
        try:
            print("  - 方法2: 使用curl命令下载...")
            
            # 如果是带标记的URL，提取真实URL
            if img_url.startswith('poster:'):
                parts = img_url.split(':', 2)
                if len(parts) == 3:
                    real_url = parts[2]
                    img_url = real_url
            
            # 构建curl命令
            curl_cmd = [
                'curl',
                '-L',
                '-o', filename,
                '-H', f'User-Agent: {CONFIG["user_agent"]}',
                '-H', 'Referer: https://www.instagram.com/',
                img_url
            ]
            
            # 执行命令
            import subprocess
            subprocess.run(curl_cmd, check=True, timeout=30, capture_output=True)
            
            # 验证文件
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                print(f"  - 成功下载图片: {os.path.basename(filename)}")
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

                    # 对特定账号使用特殊处理
                    if "voidstomper" in post_url.lower():
                        print(f"  - 检测到特殊账号的视频，使用特殊处理")
                        
                        # 给页面更多时间加载，确保视频元素可见
                        time.sleep(3)
                        
                        # 尝试点击视频元素以触发加载
                        try:
                            video_elements = driver.find_elements(By.TAG_NAME, "video")
                            if video_elements:
                                driver.execute_script("arguments[0].scrollIntoView();", video_elements[0])
                                time.sleep(2)
                                actions = ActionChains(driver)
                                actions.move_to_element(video_elements[0]).click().perform()
                                time.sleep(3)
                        except Exception as e:
                            print(f"  - 点击视频元素失败: {e}")
                    
                    # 使用yt-dlp下载视频（最有效的方法）
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
                        
                        # 检查是否安装了yt-dlp
                        try:
                            subprocess.run(['which', 'yt-dlp'], check=True, capture_output=True)
                            print("  - 检测到yt-dlp，尝试使用它下载...")
                            subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                            
                            if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                # 验证文件是否为视频
                                import mimetypes
                                mime_type, _ = mimetypes.guess_type(filename)
                                if mime_type and mime_type.startswith('video/'):
                                    print(f"  - 使用yt-dlp成功下载视频: {os.path.basename(filename)}")
                                    return True
                                
                                # 使用file命令检查文件类型
                                try:
                                    file_check = subprocess.run(['file', '-b', '--mime-type', filename], 
                                                              capture_output=True, text=True, check=True)
                                    file_type = file_check.stdout.strip()
                                    if file_type.startswith('video/'):
                                        print(f"  - 使用yt-dlp成功下载视频: {os.path.basename(filename)}")
                                        return True
                                    else:
                                        print(f"  - 警告：下载的文件不是视频 ({file_type})，尝试其他方法")
                                        os.remove(filename)
                                except:
                                    # 无法确定类型但文件存在，假设成功
                                    print(f"  - 使用yt-dlp成功下载视频: {os.path.basename(filename)}")
                                    return True
                        except:
                            # 如果没有yt-dlp，尝试使用youtube-dl
                            try:
                                cmd[0] = 'youtube-dl'
                                subprocess.run(['which', 'youtube-dl'], check=True, capture_output=True)
                                print("  - 检测到youtube-dl，尝试使用它下载...")
                                subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                                
                                if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                    print(f"  - 使用youtube-dl成功下载视频: {os.path.basename(filename)}")
                                    return True
                            except:
                                print("  - 系统中未安装yt-dlp或youtube-dl")
                                print("  - 建议安装yt-dlp以获取视频: pip install yt-dlp")
                    except Exception as e:
                        print(f"  - 使用第三方工具下载失败: {e}")
                    
                    # 尝试使用JavaScript提取视频URL (备选方法)
                    print("方法2: 尝试从页面提取视频URL...")
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
                        
                        return null;
                    }
                    
                    return getVideoUrl();
                    """)
                    
                    if js_video_url and is_valid_url(js_video_url) and not js_video_url.startswith('blob:'):
                        print(f"  - 从页面中提取到视频URL: {js_video_url}")
                        
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
                                if 'video/' in content_type or 'application/octet-stream' in content_type:
                                    with open(filename, 'wb') as f:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                f.write(chunk)
                                    
                                    if os.path.exists(filename) and os.path.getsize(filename) > 10000:
                                        print(f"  - 成功下载视频: {os.path.basename(filename)}")
                                        return True
                                else:
                                    print(f"  - 内容类型不是视频: {content_type}")
                        except Exception as e:
                            print(f"  - 下载视频失败: {e}")
                    
                    print("  - 所有视频提取方法都失败")
                    print("  - 建议安装yt-dlp工具以获取更好的视频下载支持")
                    print("  - 命令: pip install yt-dlp")
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
        
        # 使用requests下载
        try:
            print("  - 使用requests下载...")
            
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
                if 'video/' in content_type or 'application/octet-stream' in content_type:
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
        
        print("  - 下载失败")
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
            const reelLinks = [];
            
            // 方法1：查找所有链接
            const allLinks = document.querySelectorAll('a');
            allLinks.forEach(a => {
                const href = a.getAttribute('href');
                if (href) {
                    // 优先处理Reels视频
                    if (href.includes('/reel/')) {
                        const fullUrl = href.startsWith('http') ? href : 'https://www.instagram.com' + href;
                        reelLinks.push(fullUrl);
                    } 
                    // 然后处理普通帖子
                    else if (href.includes('/p/')) {
                        const fullUrl = href.startsWith('http') ? href : 'https://www.instagram.com' + href;
                        links.push(fullUrl);
                    }
                }
            });
            
            // 方法2：查找图片容器并获取父级链接
            const imgContainers = document.querySelectorAll('div[role="button"]');
            imgContainers.forEach(container => {
                const parent = container.closest('a');
                if (parent) {
                    const href = parent.getAttribute('href');
                    if (href) {
                        // 优先处理Reels视频
                        if (href.includes('/reel/')) {
                            const fullUrl = href.startsWith('http') ? href : 'https://www.instagram.com' + href;
                            reelLinks.push(fullUrl);
                        } 
                        // 然后处理普通帖子
                        else if (href.includes('/p/')) {
                            const fullUrl = href.startsWith('http') ? href : 'https://www.instagram.com' + href;
                            links.push(fullUrl);
                        }
                    }
                }
            });
            
            // 合并结果，确保Reels视频在前面
            const uniqueReels = [...new Set(reelLinks)];
            const uniqueLinks = [...new Set(links)];
            return [...uniqueReels, ...uniqueLinks];
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
                
                # 先查找Reels链接
                reel_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/reel/')]")
                post_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/p/')]")
                
                post_links = []
                
                # 优先添加Reels链接
                for element in reel_elements:
                    href = element.get_attribute("href")
                    if href and "instagram.com/reel/" in href:
                        post_links.append(href)
                
                # 然后添加普通帖子链接
                for element in post_elements:
                    href = element.get_attribute("href")
                    if href and "instagram.com/p/" in href:
                        post_links.append(href)
        
        # 去重
        post_links = list(dict.fromkeys(post_links))
        
        # 优先处理Reels视频
        reel_links = [link for link in post_links if '/reel/' in link]
        post_links = reel_links + [link for link in post_links if '/reel/' not in link]
        
        # 如果是测试模式，限制爬取数量
        if test_mode and len(post_links) > count:
            print(f"测试模式: 限制爬取 {count}/{len(post_links)} 个帖子")
            post_links = post_links[:count]
        
        print(f"共提取到 {len(post_links)} 个帖子链接，其中 {len(reel_links)} 个Reels视频")
        
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
        os.makedirs(save_dir, exist_ok=True)
        
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
                if download_video_with_browser(driver, video_url, save_dir, i):
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

