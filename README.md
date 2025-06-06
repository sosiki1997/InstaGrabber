# Instagram视频下载工具

这是一个专门用于从Instagram下载视频的工具，特别优化了对Reels视频的支持。

## 主要功能

- 爬取Instagram用户发布的视频，优先处理Reels视频
- 使用yt-dlp工具高效下载Instagram视频
- 自动处理特殊账号的视频
- 将视频直接保存到用户目录下，便于管理

## 安装依赖

```bash
pip3 install selenium beautifulsoup4 requests webdriver-manager
pip3 install yt-dlp
```

## 使用方法

推荐使用提供的启动脚本，它会自动设置环境变量并检查依赖：

```bash
# 给脚本添加执行权限
chmod +x run.sh

# 运行脚本下载视频
./run.sh -u <Instagram用户名>
```

或者直接使用Python运行（需要确保yt-dlp在PATH中）：

```bash
export PATH="$PATH:$HOME/Library/Python/3.9/bin"
python3 instagrabber.py --username <Instagram用户名>
```

### 参数说明

- `--username` 或 `-u`: 指定Instagram用户名
- `--test` 或 `-t`: 测试模式，只爬取少量帖子
- `--count` 或 `-c`: 测试模式下爬取的帖子数量，默认为3
- `--all` 或 `-a`: 爬取所有媒体，不限制数量

### 测试模式

如果你只想下载1个视频进行测试，可以使用以下命令：

```bash
./run.sh -u <Instagram用户名> -t -c 1
```

这将限制程序只下载1个视频（优先下载Reels视频）。

## 注意事项

1. 首次运行时需要手动登录Instagram账号
2. 视频文件保存在data/<用户名>目录下
3. 本工具使用yt-dlp下载视频，启动脚本会自动检查并安装
4. 对于特殊账号有专门的处理逻辑

## 工作原理

1. 使用Selenium模拟浏览器访问Instagram
2. 优先提取Reels视频链接，然后是普通帖子
3. 访问每个帖子并检测视频内容
4. 使用yt-dlp下载视频到指定目录

## 许可证

本项目仅供教育和学习目的使用。请尊重Instagram的服务条款和内容创作者的权益。



