# Godox Controller 更新发布

当前源码使用 Sparkle 2.9.6：控制台显示当前版本；后台发现更新后，菜单栏出现橙点，控制台提供“更新到 vX”入口。用户确认一次安装后，自动下载、验签、安装并重启。默认只后台检查，保留已有用户更新偏好。更新清单与 DMG 使用 EdDSA 签名；私钥仅在本机钥匙串的 `com.godoxcontroller.desktop` 账户中，不得放入仓库或发布包。

## 首次启用

已安装包含 Sparkle 的 v1.6 或后续版本，可以通过“检查更新…”获取更新。不含更新器的更早版本必须先手动安装一次新版。橙点提示从 v1.6.2 开始提供，旧版的提示形式沿用旧版界面。应用仍需保持相同的 Bundle ID、有效签名身份和单调递增的 `CFBundleVersion`。

## 每次发布

1. 在唯一版本来源 `Info.plist` 更新版本号与 `CFBundleVersion`；后端显示版本和 DMG 文件名从该文件读取。构建号必须大于已发布版本。
2. 执行 `bash build-app.sh --bundle-backend`，再执行 `bash build-dmg.sh`；检查签名、打开应用及主要控制流程。
3. 执行 `bash scripts/make-appcast.sh`。脚本会验证 DMG 中的版本、Sparkle 组件、代码签名和公钥，再输出 `dist/appcast.xml`。不要手工改动签名后的 XML。
4. 经用户批准发布后，推送 main 与 `v<版本号>` 标签，在同一 GitHub Release 上传 `GodoxController-v<版本号>.dmg` 与 `appcast.xml`。两者文件名、标签和 XML 内下载地址必须一致。先完成草稿 Release 的资产上传并校验，再公开发布并确认下载链接与 `releases/latest/download/appcast.xml` 可访问。
5. 用已安装上一版本的测试机实际走一遍“检查更新…”、下载、验签、替换和重启，再通知同事。仅生成 DMG 或 XML 不等于自动更新已可用。

## 限制

- 当前分发使用自签的 `Godox Dev` 证书，而非 Apple Developer ID 公证包。不同 Mac 的 Gatekeeper/权限状态可能阻止无交互安装；在真实同事设备验证前，不承诺完全静默更新。
- 不要丢失或更换 Sparkle 私钥；否则已安装版本无法验证后续更新。备份/迁移私钥须单独按凭据流程处理，不应导出到仓库。
- 每次发布都需要匹配的签名 `appcast.xml`；仅上传源码或 DMG，不会产生应用内更新提醒。
