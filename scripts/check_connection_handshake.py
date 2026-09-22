#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    cname = c.get_name()
    if any(k in cname for k in ["BluetoothLinkActivity", "BluListenerCallback", "MyBluetooth"]):
        for m in c.get_methods():
            if any(k in m.get_name().lower() for k in ["connect", "state", "notify", "read"]):
                print(f"=== {cname} -> {m.get_name()} ===")
                code = m.get_code()
                if code:
                    for ins in code.get_bc().get_instructions():
                        out = ins.get_output()
                        if any(k in out for k in ["send", "write", "read", "Intent", "startActivity", "FlashMainActivity"]):
                            print("  ", ins.get_name(), out)
