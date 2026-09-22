#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "BluetoothSendData" in c.get_name():
        for m in c.get_methods():
            if m.get_name() == "getSingleGroupData":
                print("--- getSingleGroupData instructions ---")
                code = m.get_code()
                for ins in code.get_bc().get_instructions():
                    out = ins.get_output()
                    if any(k in ins.get_name() for k in ["aput", "const", "sub", "add"]):
                        print("  ", ins.get_name(), out)
