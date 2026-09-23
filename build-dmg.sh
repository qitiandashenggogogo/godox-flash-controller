#!/bin/bash
# 打包 macOS dmg：把 .app 和 /Applications 快捷方式放在同一层窗口里，
# 同事双击挂载后能直接看到「拖到 Applications」的引导，符合 macOS 标准分发习惯。
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${VERSION:-1.1}"
APP_NAME="Godox Controller.app"
DMG_NAME="GodoxController-v${VERSION}.dmg"
STAGING="$(mktemp -d -t godox-dmg)"
LAYOUT_DIR="${STAGING}/layout"
DMG_STAGING="${STAGING}/dmg"

cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT

mkdir -p "$LAYOUT_DIR" "$DMG_STAGING"

# 1) 把 .app 拷进布局目录
cp -R "$APP_NAME" "$LAYOUT_DIR/$APP_NAME"

# 2) 在布局目录建一个名为「Applications」的 symlink，指向系统 /Applications。
# dmg 挂载后 Finder 会展示成一个可拖拽进去的快捷方式（蓝色 alias 图标）。
ln -s /Applications "$LAYOUT_DIR/Applications"

# 3) 把布局目录里的内容打成一个 UDRO 临时 dmg（可读写、无压缩），
#    这样可以在 dmg 文件本身上设置 Finder 窗口布局（图标位置）。
TMP_DMG="${DMG_STAGING}/tmp.dmg"
hdiutil create -ov -format UDRO -volname "GodoxController-v${VERSION}" -srcfolder "$LAYOUT_DIR" "$TMP_DMG"

# 4) 把临时 dmg 转成最终压缩 dmg（UDZO）。
mkdir -p dist
rm -f "dist/$DMG_NAME"
hdiutil convert "$TMP_DMG" -format UDZO -o "dist/$DMG_NAME"

echo "打包完成：dist/$DMG_NAME"
ls -lh "dist/$DMG_NAME"