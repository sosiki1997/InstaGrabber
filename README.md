# InstaGrabber - Instagram媒体爬取工具

InstaGrabber是一个强大的Instagram媒体爬取工具，可以从指定用户的Instagram帐号爬取图片和视频内容。特别优化了对Reels视频的支持，能够成功下载通常难以获取的视频文件。

## 特性

- 支持爬取Instagram用户主页的图片和视频
- 支持爬取Instagram Reels视频
- 自动保存媒体文件，并使用原帖子ID进行命名
- 提供多种媒体提取方法，大大提高成功率
- 支持手动登录验证，避免账户安全问题
- 自动验证下载的文件类型，确保获取真实媒体文件

## 安装

### 前提条件

- Python 3.6+
- Chrome浏览器
- ChromeDriver (与Chrome版本匹配)

### 安装步骤

1. 克隆本仓库：

```bash
git clone https://github.com/yourusername/InstaGrabber.git
cd InstaGrabber
```

2. 安装所需的Python包：

```bash
pip install selenium requests pillow
```

3. 安装媒体下载工具（强烈推荐，提高视频下载成功率）：

```bash
pip install yt-dlp
```

4. 添加yt-dlp到PATH（Mac用户可能需要）：

```bash
# 对于Mac用户，可能需要添加到PATH
export PATH="$PATH:$HOME/Library/Python/3.9/bin"  # 路径可能因Python版本而异
```

5. 为特定用户（如用户名）的视频下载，建议安装ffmpeg：

```bash
# macOS (使用Homebrew)
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows
# 下载ffmpeg并添加到PATH
```

## 使用方法

### 基本用法

爬取指定用户的帖子（测试模式，只爬取少量帖子）：

```bash
python instagrabber.py -u 用户名 -t
```


### 高级选项

- `-t` 或 `--test`: 测试模式，默认只爬取3个帖子
- `-c 数量` 或 `--count 数量`: 设置测试模式下爬取的帖子数量
- `-a` 或 `--all`: 爬取所有帖子，不限制数量

例如，爬取指定数量的帖子：

```bash
python instagrabber.py -u 用户名 -c 10
```

爬取所有帖子：

```bash
python instagrabber.py -u 用户名 -a
```

## 使用技巧

1. **登录提示**：程序会打开浏览器并等待您手动登录Instagram。登录后，回到命令行按回车继续。

2. **下载位置**：所有媒体文件将保存在`data/用户名/`目录下，图片在`images/`子目录，视频在`videos/`子目录。

3. **视频下载**：
   - 对于普通帐号视频，工具会自动尝试多种方法提取
   - 对于某些特殊帐号，工具有专门的优化

4. **如遇问题**：
   - 确保已安装yt-dlp并添加到PATH
   - 某些视频可能需要ffmpeg支持
   - 检查网络连接是否稳定
   - 如果遇到验证码或登录问题，请手动解决后继续

## 常见问题排解

**Q: 为什么有些视频下载失败？**  
A: Instagram对不同帐号的视频可能采用不同的保护措施。尝试安装yt-dlp或ffmpeg，它们能大大提高成功率。

**Q: 下载的文件是HTML而不是视频怎么办？**  
A: 这表明工具无法获取真实的视频URL。更新版本已加入验证机制，会自动识别并过滤这类文件。

**Q: 为什么需要手动登录？**  
A: 为了保证账户安全，避免在代码中存储密码，同时绕过Instagram的防爬机制。

## 成功的关键

1. **安装yt-dlp**：这是成功下载视频的最关键工具
2. **手动登录**：确保账户已正确登录并解决所有验证问题
3. **足够的等待时间**：某些帖子加载可能较慢，程序已内置适当延迟
4. **特殊账户优化**：对某些特殊账户使用了专门的提取方法

## 许可证

本项目仅供教育和学习目的使用。请尊重Instagram的服务条款和内容创作者的权益。



