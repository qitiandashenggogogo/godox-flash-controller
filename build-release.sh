#!/bin/bash
# 生成可交给同事内测的 macOS 包（不执行签名/公证）。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "缺少 .venv；请先运行 启动控制台.command" >&2
    exit 1
fi

.venv/bin/pip install -r requirements-build.txt
bash build-app.sh --bundle-backend

mkdir -p dist
rm -f "dist/Godox Controller-macos-unsigned.zip"
ditto -c -k --sequesterRsrc --keepParent "Godox Controller.app" "dist/Godox Controller-macos-unsigned.zip"
echo "已生成：dist/Godox Controller-macos-unsigned.zip"
echo "提示：这是未签名内测包；正式无阻碍分发仍需 Apple 开发者签名与公证。"
