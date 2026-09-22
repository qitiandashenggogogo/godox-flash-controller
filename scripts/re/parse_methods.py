#!/usr/bin/env python3
from androguard.core.dex import DEX

print("Loading DEX...")
d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())
print("DEX loaded.")

for c in d.get_classes():
    name = c.get_name()
    if any(k in name for k in ["BluetoothSendData"]):
        print(f"\n=================== {name} ===================")
        for m in c.get_methods():
            print(f"--- Method: {m.get_name()} ---")
            code = m.get_code()
            if code:
                bc = code.get_bc()
                for ins in bc.get_instructions():
                    print(f"    {ins.get_name()} {ins.get_output()}")
