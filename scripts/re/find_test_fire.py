#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    for m in c.get_methods():
        name = m.get_name()
        if any(k in name.lower() for k in ["test", "fire", "trigger", "flash"]):
            code = m.get_code()
            if code:
                for ins in code.get_bc().get_instructions():
                    out = ins.get_output()
                    if any(k in out for k in ["BluetoothSendData", "sendData", "CommandWrite", "CommandPolicy"]):
                        print(f"{c.get_name()} -> {name} calls {out}")
