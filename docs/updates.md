# Godox Controller 更新发布

当前源码使用 Sparkle 2.9.6：菜单提供“检查更新…”，后台定期检查并允许自动安装。更新清单与 DMG 使用 EdDSA 签名；私钥仅在本机登录钥匙串的 `com.godoxcontroller.desktop` 账户中，不得放入仓库或发布包。

## 首次启用

现有已安装的旧版本没有更新器，无法自己收到第一次更新。必须先让同事手动安装一次包含 Sparkle 的新版本。安装后才能通过更新清单收到后续版本。应用仍需保持相同的 Bundle ID、有效签名身份和单调递增的 `CFBundleVersion`。

## 每次发布

1. 先确定新版本号，同时更新 `Info.plist`、`app/main.py` 和 `build-dmg.sh`；`CFBundleVersion` 必须大于已发布版本。
2. 执行 `bash build-app.sh --bundle-backend`，再执行 `bash build-dmg.sh`；检查签名、打开应用及主要控制流程。
3. 执行 `bash scripts/make-appcast.sh`。脚本会验证 DMG 中的版本、Sparkle 组件、代码签名和公钥，再输出 `dist/appcast.xml`。不要手工改动签名后的 XML。
4. 经用户批准发布后，在同一 GitHub Release（标签 `v<版本号>`）上传 `GodoxController-v<版本号>.dmg` 与 `appcast.xml`。两者文件名、标签和 XML 内下载地址必须一致。正式发布前先检查目标 URL 可访问；旧版的 `releases/latest/download/appcast.xml` 此时才会成为有效更新源。
5. 用已安装上一版本的测试机实际走一遍“检查更新…”、下载、验签、替换和重启，再通知同事。仅生成 DMG 或 XML 不等于自动更新已可用。

## 限制

- 当前分发使用自签的 `Godox Dev` 证书，而非 Apple Developer ID 公证包。不同 Mac 的 Gatekeeper/权限状态可能阻止无交互安装；在真实同事设备验证前，不承诺完全静默更新。
- 不要丢失或更换 Sparkle 私钥；否则已安装版本无法验证后续更新。备份/迁移私钥须单独按凭据流程处理，不应导出到仓库。
- 旧版发布页尚无 `appcast.xml`，因此仅把更新器代码放到本地或发布 DMG 而不上传清单，并不会产生更新提醒。
