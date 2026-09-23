#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

bundle_backend=false
if [ "${1:-}" = "--bundle-backend" ]; then
    bundle_backend=true
fi

echo "编译 macOS 原生应用..."
swiftc -O -swift-version 5 -o GodoxController GodoxController.swift -framework WebKit -framework AppKit
mkdir -p "Godox Controller.app/Contents/MacOS" "Godox Controller.app/Contents/Resources"
cp Info.plist "Godox Controller.app/Contents/"
cp GodoxController "Godox Controller.app/Contents/MacOS/GodoxController"
if [ -f assets/icon/GodoxController.icns ]; then
    cp assets/icon/GodoxController.icns "Godox Controller.app/Contents/Resources/GodoxController.icns"
fi

if [ "$bundle_backend" = true ]; then
    if [ ! -x ".venv/bin/python" ]; then
        echo "缺少 .venv；请先运行 启动控制台.command 或执行 python3 -m venv .venv" >&2
        exit 1
    fi
    if ! .venv/bin/python -c 'import PyInstaller' >/dev/null 2>&1; then
        echo "缺少 PyInstaller；请先运行 .venv/bin/pip install -r requirements-build.txt" >&2
        exit 1
    fi
    echo "封装内置后端（同事无需 Python 或 AI）..."
    rm -rf build dist/GodoxControllerBackend "Godox Controller.app/Contents/Resources/backend"
    .venv/bin/python -m PyInstaller --noconfirm --clean --onedir \
        --name GodoxControllerBackend \
        --paths "$PWD" \
        --add-data "$PWD/app/static:app/static" \
        --collect-all bleak \
        app_backend.py
    cp -R dist/GodoxControllerBackend "Godox Controller.app/Contents/Resources/backend"
fi

echo "构建完成：Godox Controller.app"
