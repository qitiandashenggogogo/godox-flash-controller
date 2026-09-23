#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========================================="
echo "神牛引闪器桌面控制台（兼容 X3 Pro / XPro II / X2T）"
echo "========================================="

# 1. 检查并建立 Python 虚拟环境
if [ ! -d ".venv" ]; then
    echo "创建 Python 虚拟环境..."
    python3 -m venv .venv
    export SSL_CERT_FILE=/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/certifi/cacert.pem
    .venv/bin/pip install --upgrade pip
fi

if ! .venv/bin/python -c 'import bleak, fastapi, uvicorn' >/dev/null 2>&1; then
    echo "安装运行依赖..."
    .venv/bin/pip install -r requirements.txt
fi

# 2. 检查原生桌面 App 是否已编译
if [ ! -d "Godox Controller.app" ]; then
    echo "正在构建 macOS 原生菜单栏应用..."
    bash build-app.sh
fi

# 3. 检查后台服务是否已运行
if ! curl --noproxy '*' -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/ | grep -q "200"; then
    echo "启动本地服务 (127.0.0.1:8765)..."
    nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 > app.log 2>&1 &
    sleep 1.5
fi

# 4. 打开原生桌面控制浮窗
echo "正在打开控制台..."
open "Godox Controller.app" || open "http://127.0.0.1:8765/"
echo "控制台已就绪！"
