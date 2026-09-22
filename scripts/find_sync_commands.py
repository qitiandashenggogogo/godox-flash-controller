#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    cname = c.get_name()
    if any(k in cname for k in ["BluetoothLink", "HomePageFragment", "FlashMainActivity", "BluetoothSendData", "CommandPolicy", "BlueToothManage"]):
        for m in c.get_methods():
            mname = m.get_name()
            if any(k in mname.lower() for k in ["sync", "read", "query", "request", "init", "login", "connect", "getdata"]):
                code = m.get_code()
                if code:
                    for ins in code.get_bc().get_instructions():
                        out = ins.get_output()
                        if any(k in out for k in ["send", "write", "TCCommand", "FlashCommand", "CommandWrite"]):
                            print(f"{cname} -> {mname}: {ins.get_name()} {out}")
