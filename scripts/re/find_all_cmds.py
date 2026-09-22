#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "BluetoothSendData" in c.get_name() or "CommandPolicy" in c.get_name():
        print(f"=== {c.get_name()} ===")
        for m in c.get_methods():
            code = m.get_code()
            if code:
                insns = code.get_bc().get_instructions()
                strings = [ins.get_output() for ins in insns if ins.get_name() == "const-string"]
                print(f"  Method {m.get_name()}: strings={strings}")
