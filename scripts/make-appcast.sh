#!/bin/bash
# 为单个 GitHub Release DMG 生成 Sparkle EdDSA 签名更新目录；不上传。
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' Info.plist)
DMG_PATH="${1:-dist/GodoxController-v${VERSION}.dmg}"
OUTPUT_PATH="${OUTPUT_PATH:-dist/appcast.xml}"
ACCOUNT=com.godoxcontroller.desktop

if [ ! -f "$DMG_PATH" ]; then
    echo "找不到 DMG：$DMG_PATH" >&2
    exit 1
fi
if [ -e "$OUTPUT_PATH" ]; then
    echo "输出文件已存在，拒绝覆盖：$OUTPUT_PATH" >&2
    exit 1
fi

SPARKLE_ROOT="$(bash scripts/ensure-sparkle.sh)"
STAGING=$(mktemp -d "${TMPDIR:-/tmp}/godox-appcast.XXXXXX")
MOUNTED=false
cleanup() {
    if [ "$MOUNTED" = true ]; then
        hdiutil detach -quiet "$STAGING/mounted" || true
    fi
    rm -r "$STAGING"
}
trap cleanup EXIT
mkdir "$STAGING/mounted"
hdiutil attach -nobrowse -readonly -quiet -mountpoint "$STAGING/mounted" "$DMG_PATH"
MOUNTED=true
PACKAGED_APP="$STAGING/mounted/Godox Controller.app"
codesign --verify --deep --strict "$PACKAGED_APP"
if [ ! -d "$PACKAGED_APP/Contents/Frameworks/Sparkle.framework" ]; then
    echo "DMG 未包含 Sparkle，拒绝生成更新目录" >&2
    exit 1
fi
PACKAGED_VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PACKAGED_APP/Contents/Info.plist")
PACKAGED_KEY=$(/usr/libexec/PlistBuddy -c 'Print :SUPublicEDKey' "$PACKAGED_APP/Contents/Info.plist")
KEYCHAIN_KEY=$("$SPARKLE_ROOT/bin/generate_keys" --account "$ACCOUNT" -p)
if [ "$PACKAGED_VERSION" != "$VERSION" ] || [ "$PACKAGED_KEY" != "$KEYCHAIN_KEY" ]; then
    echo "DMG 版本或更新公钥与当前发布配置不匹配，拒绝生成更新目录" >&2
    exit 1
fi
hdiutil detach -quiet "$STAGING/mounted"
MOUNTED=false
cp "$DMG_PATH" "$STAGING/"

"$SPARKLE_ROOT/bin/generate_appcast" \
    --account "$ACCOUNT" \
    --maximum-versions 0 \
    --maximum-deltas 0 \
    --download-url-prefix "https://github.com/qitiandashenggogogo/godox-flash-controller/releases/download/v${VERSION}/" \
    -o "$STAGING/appcast.xml" "$STAGING"

xmllint --noout "$STAGING/appcast.xml"
if ! grep -q 'sparkle:edSignature' "$STAGING/appcast.xml"; then
    echo "appcast 缺少 EdDSA 签名，拒绝输出" >&2
    exit 1
fi
mkdir -p "$(dirname "$OUTPUT_PATH")"
cp "$STAGING/appcast.xml" "$OUTPUT_PATH"
echo "已生成签名更新目录：${OUTPUT_PATH}（尚未发布）"
