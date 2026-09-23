#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

bundle_backend=false
if [ "${1:-}" = "--bundle-backend" ]; then
    bundle_backend=true
fi

echo "编译 macOS 原生应用（arm64 + x86_64 双架构，最低 macOS 11）..."
swiftc -O -swift-version 5 -target arm64-apple-macos11.0 -o GodoxController-arm64 GodoxController.swift -framework WebKit -framework AppKit
swiftc -O -swift-version 5 -target x86_64-apple-macos11.0 -o GodoxController-x86_64 GodoxController.swift -framework WebKit -framework AppKit
lipo -create GodoxController-arm64 GodoxController-x86_64 -output GodoxController
rm GodoxController-arm64 GodoxController-x86_64
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
        --target-architecture universal2 \
        --paths "$PWD" \
        --add-data "$PWD/app/static:app/static" \
        --collect-all bleak \
        app_backend.py
    cp -R dist/GodoxControllerBackend "Godox Controller.app/Contents/Resources/backend"
fi

# 自签证书签名（修复 TCC 蓝牙授权跨构建失效）：
# adhoc 签名每次构建 cdhash 都变，TCC 按指纹记身份，旧授权全部作废。
# 改用稳定的自签证书 "Godox Dev"，TCC 按证书指纹匹配，授权永久有效。
# 从里到外逐层签：先动态库 → 后端可执行文件 → Swift 壳 → 整个 .app。
SIGN_IDENTITY="Godox Dev"
APP="Godox Controller.app"
if security find-identity -p codesigning 2>/dev/null | grep -q "$SIGN_IDENTITY"; then
    echo "使用证书 \"$SIGN_IDENTITY\" 从里到外签名（蓝牙授权跨构建保留）..."
    if [ -d "$APP/Contents/Resources/backend" ]; then
        find "$APP/Contents/Resources/backend" \( -name "*.so" -o -name "*.dylib" \) \
            -exec codesign --force --sign "$SIGN_IDENTITY" {} +
        codesign --force --sign "$SIGN_IDENTITY" "$APP/Contents/Resources/backend/GodoxControllerBackend"
    fi
    codesign --force --sign "$SIGN_IDENTITY" "$APP/Contents/MacOS/GodoxController"
    codesign --force --sign "$SIGN_IDENTITY" "$APP"
    echo "签名完成（证书：$SIGN_IDENTITY）"
else
    echo "未找到 \"$SIGN_IDENTITY\" 证书，跳过签名（蓝牙授权将无法跨构建保留）"
fi

echo "构建完成：Godox Controller.app"
