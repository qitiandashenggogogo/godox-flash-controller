#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "编译 macOS 原生应用..."
swiftc -O -swift-version 5 -o GodoxController GodoxController.swift -framework WebKit -framework AppKit
mkdir -p "Godox Controller.app/Contents/MacOS"
cp Info.plist "Godox Controller.app/Contents/"
cp GodoxController "Godox Controller.app/Contents/MacOS/GodoxController"
echo "构建完成：Godox Controller.app"
