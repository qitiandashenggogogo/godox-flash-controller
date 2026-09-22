#!/usr/bin/env python3
methods = '''    async def all_off(self) -> bool:
        """一键全局 OFF：把所有可见组别设为 OFF（实体引闪器上所有组关闭闪光）"""
        if not self.is_connected or not self.client:
            return False
        success = True
        for g in list(self.visible_groups):
            data = self.groups.get(g, {})
            ok = await self.set_group(
                group=g,
                mode="OFF",
                dec_val=data.get("dec_val", 40),
                sound=data.get("sound", False),
                lamp=False,
            )
            if not ok:
                success = False
            await asyncio.sleep(0.08)
        return success

    async def sync_all_to_device(self) -> bool:
        """用户知情地一键接管：把桌面当前全部灯位配置整体写入实体引闪器"""
        if not self.is_connected or not self.client:
            return False
        ok1 = await self.send_tc_command(channel=self.channel, global_lamp=self.global_lamp, global_sound=self.global_sound)
        success = ok1
        for g in self.visible_groups:
            grp = self.groups.get(g)
            if grp:
                ok = await self.set_group(
                    group=g,
                    mode=grp.get("mode", "M"),
                    dec_val=grp.get("dec_val", 40),
                    sound=grp.get("sound", False),
                    lamp=grp.get("lamp", False),
                )
                if not ok:
                    success = False
                await asyncio.sleep(0.08)
        return success

'''

with open("app/ble_manager.py") as f:
    content = f.read()

assert "async def test_fire" in content
assert "async def all_off" not in content
content = content.replace("    async def test_fire", methods + "    async def test_fire", 1)

with open("app/ble_manager.py", "w") as f:
    f.write(content)
print("all_off + sync_all_to_device added")
