#!/usr/bin/env python3
with open("app/static/index.html", encoding="utf-8") as f:
    html = f.read()

# 1. 在「一键安全复位」旁插入 全局OFF + 一键同步 按钮
old_row = '''      <div style="display:flex; gap:12px;">
        <button class="btn" onclick="resetAll()">一键安全复位 (1/128 M)</button>
        <button class="test-fire-btn" onclick="testFire()">
          ⚡ 立即试闪 (TEST FIRE)
        </button>
      </div>'''
new_row = '''      <div style="display:flex; gap:12px;">
        <button class="btn" onclick="syncToDevice()" title="把桌面当前全部灯位配置整体写入实体引闪器（接管控制权）">⇓ 一键同步到引闪器</button>
        <button class="btn btn-danger" onclick="allOff()" title="关闭所有组别的闪光输出（功率设置保留，可再开回）">⏻ 一键全局 OFF</button>
        <button class="test-fire-btn" onclick="testFire()">
          ⚡ 立即试闪 (TEST FIRE)
        </button>
      </div>'''
assert old_row in html
html = html.replace(old_row, new_row)

# 2. 提示条改为诚实说明单向通道现实
old_notice_start = html.find('<div class="notice-bar">')
old_notice_end = html.find('</div>', old_notice_start) + len('</div>')
assert old_notice_start != -1
new_notice = '''<div class="notice-bar">
      <strong>同步模型说明（实测结论）</strong>：X3 Pro 蓝牙是<strong>单向命令通道</strong>（与官方 App 同机制），实体端不回传状态——桌面上显示的数值以「本机记忆」为准，连接后不会覆盖你的实体设置；你在桌面做的任何调整会立即写入实体。如需以桌面配置整体接管实体，点「⇓ 一键同步到引闪器」。
    </div>'''
html = html[:old_notice_start] + new_notice + html[old_notice_end:]

# 3. 增加 JS 函数 allOff / syncToDevice
old_js = '''    async function resetAll() {'''
new_js = '''    async function allOff() {
      if (!confirm("一键全局 OFF：关闭所有组别的闪光输出？（各组功率数值会保留，可逐个开回）")) return;
      await fetch('/api/all_off', { method: 'POST' });
      fetchStatus();
    }

    async function syncToDevice() {
      if (!confirm("把桌面当前全部灯位配置整体写入实体引闪器（接管控制权）？\n注意：实体引闪器屏幕上各组将被刷新为桌面当前数值。")) return;
      await fetch('/api/sync_to_device', { method: 'POST' });
      fetchStatus();
    }

    async function resetAll() {'''
assert old_js in html
html = html.replace(old_js, new_js, 1)

with open("app/static/index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("UI updated")
