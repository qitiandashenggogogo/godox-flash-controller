#!/bin/bash
# 下载并缓存经过 SHA-256 校验的 Sparkle 2.9.6 构建依赖。
set -euo pipefail

VERSION=2.9.6
SHA256=52bf9e88cdd972fc0c81501377a880e90d47031bd8ca5462488f843e2609e192
URL="https://github.com/sparkle-project/Sparkle/releases/download/${VERSION}/Sparkle-${VERSION}.tar.xz"
CACHE_ROOT="${HOME}/Library/Caches/GodoxController/Sparkle-${VERSION}"

if [ -d "$CACHE_ROOT" ]; then
    if [ ! -f "$CACHE_ROOT/.verified-sha256" ] ||
       [ "$(<"$CACHE_ROOT/.verified-sha256")" != "$SHA256" ] ||
       [ ! -d "$CACHE_ROOT/Sparkle.framework" ] ||
       [ ! -f "$CACHE_ROOT/LICENSE" ]; then
        echo "Sparkle 缓存不完整或未通过校验：$CACHE_ROOT" >&2
        exit 1
    fi
    codesign --verify --deep --strict "$CACHE_ROOT/Sparkle.framework" >&2
    printf '%s\n' "$CACHE_ROOT"
    exit 0
fi

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/godox-sparkle.XXXXXX")
cleanup() { rm -r "$TMP_ROOT"; }
trap cleanup EXIT

echo "下载 Sparkle ${VERSION}（固定 SHA-256）..." >&2
curl --fail --location --retry 2 --silent --show-error "$URL" -o "$TMP_ROOT/Sparkle.tar.xz"
ACTUAL_SHA=$(shasum -a 256 "$TMP_ROOT/Sparkle.tar.xz" | awk '{print $1}')
if [ "$ACTUAL_SHA" != "$SHA256" ]; then
    echo "Sparkle 下载校验失败：预期 $SHA256，实际 $ACTUAL_SHA" >&2
    exit 1
fi

mkdir "$TMP_ROOT/extracted"
tar -xJf "$TMP_ROOT/Sparkle.tar.xz" -C "$TMP_ROOT/extracted"
codesign --verify --deep --strict "$TMP_ROOT/extracted/Sparkle.framework" >&2
mkdir -p "$(dirname "$CACHE_ROOT")"
mkdir "$TMP_ROOT/cache"
ditto "$TMP_ROOT/extracted/Sparkle.framework" "$TMP_ROOT/cache/Sparkle.framework"
ditto "$TMP_ROOT/extracted/bin" "$TMP_ROOT/cache/bin"
cp "$TMP_ROOT/extracted/LICENSE" "$TMP_ROOT/cache/LICENSE"
printf '%s\n' "$SHA256" > "$TMP_ROOT/cache/.verified-sha256"
mv "$TMP_ROOT/cache" "$CACHE_ROOT"
printf '%s\n' "$CACHE_ROOT"
