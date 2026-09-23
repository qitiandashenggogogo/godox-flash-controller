# NOTES.md — 踩坑记录

<!-- 新记录插在这一行下面 -->

## 2026-09-23 codesign 报 "resource fork, Finder information, or similar detritus not allowed"，是扩展属性拦路

- **问题描述**：自签证书从里到外签完所有动态库和可执行文件后，最后签整个 `.app` 时报 `resource fork, Finder information, or similar detritus not allowed`，签名失败。
- **原因分析**：`.app` 根目录和 `Contents/Resources/backend/_internal/Python.framework` 上挂着 `com.apple.FinderInfo`、`com.apple.fileprovider.fpfs#P` 这类扩展属性（Finder 标记 / iCloud 占位），codesign 拒绝给带扩展属性的 bundle 签名。
- **解决方案**：签名前必须 `xattr -cr "<App>.app"` 清干净（顽固的单条用 `xattr -d com.apple.FinderInfo <路径>` 定点删）。已固化进 `build-app.sh` 签名段第一行。验证：`codesign --verify --deep --strict` 通过才算数。

## 2026-09-23 security find-identity -v 会把"未受信任"的自签证书过滤成假阴性

- **问题描述**：openssl 自签的 "Godox Dev" 证书明明已导入钥匙串，`security find-identity -v -p codesigning` 却报 `0 valid identities found`，一度以为证书没法用。
- **原因分析**：`-v`（valid only）会把信任链验证失败的证书直接排除；自签证书没有系统信任的根，标着 `(CSSMERR_TP_NOT_TRUSTED)` 就被滤掉了。但 codesign 签名并不要求证书被系统信任，只要求钥匙串里有 证书+私钥。
- **解决方案**：查自签证书用 `security find-identity -p codesigning`（**不带 `-v`**），能看到带 `CSSMERR_TP_NOT_TRUSTED` 标记的条目就说明可用。签名后 `codesign -dv` 应显示 `Authority=<证书名>`。

## 2026-09-23 OpenSSL 3.x 导出的 .p12 在 macOS 导入报 MAC verification failed

- **问题描述**：`openssl pkcs12 -export` 生成的 .p12 用 `security import` 导入钥匙串时报 `MAC verification failed`。
- **原因分析**：OpenSSL 3.x 默认改用 SHA256 MAC 等新算法，macOS 的 `security` 命令只认旧的 PKCS#12 算法族。
- **解决方案**：导出时加 `-legacy` 参数（`openssl pkcs12 -export -legacy ...`），macOS 即可正常导入。

## 2026-09-23 adhoc 签名导致 macOS 蓝牙授权"点了允许也没反应"——每次重打包指纹变、旧授权全作废

- **问题描述**：打包版 App 点「连接引闪器/切换引闪器」弹出系统蓝牙授权，点「允许」后无任何反应，扫描接口返回 500；系统设置「隐私与安全性→蓝牙」里攒了 5 个 Godox 条目且全部打开也没用。Intel 老 macOS 正常，macOS 26/27 都复现。
- **原因分析**：App 是 adhoc 签名（等于无签名），TCC（隐私权限系统）只能按二进制的 cdhash 指纹记身份。每次 `build-app.sh` 重打包 cdhash 就变，旧授权条目全部失配——tccd 日志铁证是反复输出 `Failed to match existing code requirement for subject com.godoxcontroller.desktop and service kTCCServiceBluetoothAlways`；随后 CoreBluetooth 报 `XPC connection invalid`，BLE 通道在进程生命周期内永久死亡，之后的扫描全部抛异常。日志同时证明归因链条本身是好的（responsible=Swift 壳、requesting=Python 后端），排除"授权给壳、子进程不继承"的架构病。
- **解决方案**：根修只有让签名身份跨构建稳定——Apple Developer ID 签名 + 公证（$99/年），TCC 按证书身份匹配，授权永久有效且同事机器双击可用。本机临时续命可 `tccutil reset Bluetooth com.godoxcontroller.desktop` 后重授权，但下次打包即失效，治标不治本。

## 2026-09-23 zsh 把 macOS 的 log 命令劫持成内建，排查日志全是假阴性

- **问题描述**：用 `log show --last 5m --predicate ...` 查 macOS 统一日志，连续多次返回空，误以为系统没记录。实际上 tccd / CoreBluetooth 的报错一直都在。
- **原因分析**：本机 zsh 配置里 `log` 是 shell 内建（`type log` 显示 `log is a shell builtin`），直接写 `log show` 走的是内建、报 "too many arguments"；命令尾部带 `2>/dev/null` 时错误被吞掉，表现为"查询成功但没结果"——最阴的假阴性，导致前两次日志排查全部白跑。
- **解决方案**：调 macOS 日志工具一律写绝对路径 `/usr/bin/log show ...` / `/usr/bin/log stream ...`；排查类命令先去掉 `2>/dev/null` 跑一次确认不是命令本身报错，再收窄输出。

## 2026-09-23 git push 到 GitHub 报 Permission denied (publickey)，gh 已登录却推不动

- **问题描述**：`gh auth status` 显示已登录、仓库也建好了，但 `git push -u origin HEAD:main` 报 `git@github.com: Permission denied (publickey)`。
- **原因分析**：gh CLI 的登录态是 HTTPS token，存在自己的凭据存储里；而 remote 默认按 SSH（git@github.com）拼，本机没有配置 GitHub SSH 公钥，两条认证通道互不相干，所以 gh 能用、git 推不动。
- **解决方案**：把 remote 切成 HTTPS 并让 gh 给 git 做凭据代理：`git remote set-url origin https://github.com/<用户>/<仓库>.git`，再 `gh auth setup-git`（写入 credential helper），重新 push 即成功。反过来想用 SSH 就得先去 GitHub 后台挂公钥，二选一。

## 2026-09-23 打 universal2 包时 pydantic-core 只发了分架构 wheel，PyInstaller 收集不到 x86_64 版

- **问题描述**：`build-app.sh --bundle-backend` 加 `--target-architecture universal2` 后，打出的包里 `pydantic_core/_pydantic_core.*.so` 仍是 arm64 单架构，Intel Mac 上会 import 失败；用 `pip download --platform macosx_10_13_universal2` 想直接下 universal wheel 时报「from versions: 0.0.1」。
- **原因分析**：pydantic-core 只发布分架构 wheel（`macosx_11_0_arm64` / `macosx_10_12_x86_64`），没有 universal2 wheel，所以 venv 里本来就只有 arm64 的 .so，PyInstaller 原样收集，universal2 打包缺一块拼图。
- **解决方案**：单独 `pip download pydantic-core==<当前版本> --platform macosx_10_12_x86_64 --python-version 3.12 --no-deps -d <临时目录>`，解出 x86_64 的 .so，用 `lipo -create` 与 venv 里的 arm64 .so 合成 fat 二进制后覆盖回 venv（留 .bak 备份）；随后 PyInstaller 就能收集到 universal2 .so。验证：构建后 `find 包内 -name "*.so" | xargs lipo -info` 全部显示 x86_64+arm64，并用 `arch -x86_64 <后端二进制>` 在 Rosetta 下实测启动 + curl /api/health。

## 2026-09-23 用 SVG 官方标志做 App 图标，qlmanage 转出的 PNG 带白底且内容缩在角落

- **问题描述**：想把 `assets/icon/godox.svg` 合成图标 PNG，先用 `qlmanage -t -s` 把 SVG 转 PNG 再拿 AppKit 合成，结果转出的图是不透明白底、标志只在左上角一小块，合成出来的图标是白方块里一个迷你 logo。
- **原因分析**：qlmanage 的 SVG 缩略图渲染不尊重 SVG 自身的透明背景与 viewBox 排版，输出是带白底的整幅画布；按 alpha 通道扫描包围盒会铺满全图，裁切逻辑失效。另外直接在 Chrome 里打开 `.svg` 文件得到的是纯 SVG XML 文档，`document.createElement('canvas')` 产不出可用的 HTMLCanvasElement，合成脚本要在 HTML 页面（如 about:blank）里跑。
- **解决方案**：不经过 qlmanage，把 SVG 源码内联成字符串，在 Chrome 普通页面里用 Blob → Image → canvas 画圆角深色底再 drawImage 标志，`toDataURL('image/png')` 导出后用 python3 标准库 base64 解码落盘，再 `sips -z` 出 iconset 各尺寸、`iconutil -c icns` 打包。全程零新依赖（不装 Pillow）。

## 2026-09-23 改了前端页面，打包版 App 里却没变

- **问题描述**：修改 `app/static/index.html` 后运行 `bash build-app.sh` 并重启 App，页面仍是旧内容。
- **原因分析**：`build-app.sh` 默认只重编译 Swift 外壳；打包版 App 显示的是 PyInstaller 打进 `Godox Controller.app/Contents/Resources/backend` 里的那份 `app/static` 副本，不带 `--bundle-backend` 就不会更新。另外旧的后端进程如果没被杀掉，Swift 外壳检测到健康服务会直接复用，新包也不会生效。
- **解决方案**：改前端/后端代码后要打包生效，必须 `bash build-app.sh --bundle-backend`；重启前先 `pkill -f "Godox Controller.app"` 和 `pkill -f GodoxControllerBackend`，再 `open -n "Godox Controller.app"`，最后用 `curl --noproxy '*' -s http://127.0.0.1:8765/ | grep '<title>'` 验证。
