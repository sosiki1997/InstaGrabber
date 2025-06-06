#!/bin/bash

echo "============================================"
echo "Instagram视频下载工具启动脚本"
echo "============================================"

# 设置PATH环境变量，包含yt-dlp路径
USER_BIN_PATH="$HOME/Library/Python/3.9/bin"
export PATH="$PATH:$USER_BIN_PATH"
echo "已设置PATH环境变量: $PATH"

# 检查Python版本
echo "检查Python版本..."
python3 --version

# 检查yt-dlp是否可用
echo "检查yt-dlp..."
if command -v yt-dlp &> /dev/null; then
    echo "yt-dlp已安装: $(which yt-dlp)"
    echo "yt-dlp版本: $(yt-dlp --version)"
else
    echo "警告: yt-dlp未找到，尝试安装..."
    pip3 install yt-dlp
    
    # 再次检查安装结果
    if command -v yt-dlp &> /dev/null; then
        echo "yt-dlp安装成功: $(which yt-dlp)"
    else
        echo "错误: yt-dlp安装失败，请手动安装: pip3 install yt-dlp"
        echo "或者添加到PATH: export PATH=\"\$PATH:\$HOME/Library/Python/3.9/bin\""
    fi
fi

echo "============================================"
echo "运行Instagram视频下载工具..."
echo "命令: python3 instagrabber.py $@"
echo "============================================"

# 运行程序
python3 instagrabber.py "$@"

echo "============================================"
echo "程序执行完成"
echo "============================================" 