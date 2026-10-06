#!/bin/bash
# 打包一个只用来"看效果"的原生预览：/tmp/Godox Update Preview.app
#
# 与正式版严格隔离：独立 Bundle ID、独立名字、独立 UserDefaults 域、独立状态目录；
# 不带 SUFeedURL / SUPublicEDKey（即使误启动更新器也无源可查）；不启动后端、
# 不预热 CoreBluetooth、不创建 UpdateCoordinator。产物里复用的是正在评审的那几个组件
# （StatusItemArtwork 的菜单栏点、ConsoleUpdateBridge + UpdateBridgePolicy 的桥与来源校验、
# 控制台自己的 index.html），所以看到的就是上线后的样子。
#
# 预览专用代码只在这个脚本里编译，正式 build-app.sh 永远不编译 UpdatePreviewEnvironment.swift。
set -euo pipefail
cd "$(dirname "$0")/.."

OUTPUT="/tmp/Godox Update Preview.app"
BUNDLE_ID="com.godoxcontroller.updatepreview"
PYTHON="${PYTHON:-.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

echo "打包更新提醒效果预览（隔离 Bundle ID：${BUNDLE_ID}）..."

# 预览与正式版共用这些源文件；只多编译一个 preview-only 的文件，并打开预览编译开关。
SOURCES=(GodoxController.swift BackendSupervisor.swift UpdateState.swift UpdateBridgePolicy.swift PendingReconnectStore.swift StatusItemArtwork.swift ConsoleUpdateBridge.swift UpdateCoordinator.swift UpdatePreviewEnvironment.swift)
DEFINES=(-D GODOX_UPDATE_UI_PREVIEW)
SPARKLE_ROOT="$(bash scripts/ensure-sparkle.sh 2>/dev/null)"
FRAMEWORKS=(-framework WebKit -framework AppKit)
# 与正式包同一条链接路径（含 Sparkle），但预览从不实例化更新器。
SPARKLE_FLAGS=(-F "$SPARKLE_ROOT" -framework Sparkle -Xlinker -rpath -Xlinker '@executable_path/../Frameworks')

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT/Contents/MacOS" "$OUTPUT/Contents/Resources/Console" "$OUTPUT/Contents/Frameworks"

# /tmp 之外的暂存目录只是为了让 lipo 有地方落脚；iCloud 的 xattr 会在签名前清掉。
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/godox-preview-build.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

swiftc -swift-version 5 -target arm64-apple-macos11.0 -o "$STAGE/preview-arm64" \
    "${DEFINES[@]}" "${SOURCES[@]}" "${FRAMEWORKS[@]}" "${SPARKLE_FLAGS[@]}"
swiftc -swift-version 5 -target x86_64-apple-macos11.0 -o "$STAGE/preview-x86_64" \
    "${DEFINES[@]}" "${SOURCES[@]}" "${FRAMEWORKS[@]}" "${SPARKLE_FLAGS[@]}"
lipo -create "$STAGE/preview-arm64" "$STAGE/preview-x86_64" -output "$OUTPUT/Contents/MacOS/GodoxUpdatePreview"

# 预览 Info.plist：版本号沿用正式版（要显示"当前 1.6.1"），但刻意不带任何更新源配置。
"$PYTHON" - "$OUTPUT/Contents/Info.plist" "$BUNDLE_ID" <<'PYTHON'
import plistlib
import sys
from pathlib import Path

target, bundle_id = Path(sys.argv[1]), sys.argv[2]
source = plistlib.loads(Path('Info.plist').read_bytes())
target.write_bytes(plistlib.dumps({
    'CFBundleExecutable': 'GodoxUpdatePreview',
    'CFBundleName': 'Godox Update Preview',
    'CFBundleDisplayName': 'Godox Update Preview',
    'CFBundlePackageType': 'APPL',
    'CFBundleIdentifier': bundle_id,
    'CFBundleShortVersionString': source['CFBundleShortVersionString'],
    'CFBundleVersion': source['CFBundleVersion'],
    'LSMinimumSystemVersion': source['LSMinimumSystemVersion'],
    'LSUIElement': True,
    # 刻意不写 SUFeedURL / SUPublicEDKey / SUEnableAutomaticChecks / SUAutomaticallyUpdate：
    # 预览域里根本没有更新器配置，即便误启动 Sparkle 也只会报"未配置"，不会联网。
}))
PYTHON

ditto "$SPARKLE_ROOT/Sparkle.framework" "$OUTPUT/Contents/Frameworks/Sparkle.framework"
cp "$SPARKLE_ROOT/LICENSE" "$OUTPUT/Contents/Resources/Sparkle-LICENSE.txt"
# 控制台页面直接用真实的 index.html，预览只在运行时替换版本/实例/主题占位符。
cp app/static/index.html "$OUTPUT/Contents/Resources/Console/index.html"

# ad-hoc 签名：预览不需要（也不应该）借用正式版的证书身份。
# 从里到外逐层签，签完立刻验证，避免坏包被当成"预览通过"。
xattr -cr "$OUTPUT"
SPARKLE_BUNDLE="$OUTPUT/Contents/Frameworks/Sparkle.framework/Versions/B"
codesign --force --sign - "$SPARKLE_BUNDLE/XPCServices/Installer.xpc"
codesign --force --sign - --preserve-metadata=entitlements "$SPARKLE_BUNDLE/XPCServices/Downloader.xpc"
codesign --force --sign - "$SPARKLE_BUNDLE/Autoupdate"
codesign --force --sign - "$SPARKLE_BUNDLE/Updater.app"
codesign --force --sign - "$SPARKLE_BUNDLE"
codesign --force --sign - "$OUTPUT/Contents/MacOS/GodoxUpdatePreview"
codesign --force --sign - "$OUTPUT"
codesign --verify --deep --strict "$OUTPUT"

echo "预览包已生成：$OUTPUT"
echo "启动方式：open \"$OUTPUT\" --args --preview-update-ui"
echo "提醒：预览不启动后端、不连蓝牙、不连接任何更新源；按钮只显示「不会下载或安装」的说明。"
