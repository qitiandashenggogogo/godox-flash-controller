# NOTES.md — 踩坑记录

<!-- 新记录插在这一行下面 -->

## 2026-09-23 改了前端页面，打包版 App 里却没变

- **问题描述**：修改 `app/static/index.html` 后运行 `bash build-app.sh` 并重启 App，页面仍是旧内容。
- **原因分析**：`build-app.sh` 默认只重编译 Swift 外壳；打包版 App 显示的是 PyInstaller 打进 `Godox Controller.app/Contents/Resources/backend` 里的那份 `app/static` 副本，不带 `--bundle-backend` 就不会更新。另外旧的后端进程如果没被杀掉，Swift 外壳检测到健康服务会直接复用，新包也不会生效。
- **解决方案**：改前端/后端代码后要打包生效，必须 `bash build-app.sh --bundle-backend`；重启前先 `pkill -f "Godox Controller.app"` 和 `pkill -f GodoxControllerBackend`，再 `open -n "Godox Controller.app"`，最后用 `curl --noproxy '*' -s http://127.0.0.1:8765/ | grep '<title>'` 验证。
