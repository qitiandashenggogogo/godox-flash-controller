#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "BluetoothLinkActivity" == c.get_name().split("/")[-1].replace(";", ""):
        print("Found BluetoothLinkActivity")
        for m in c.get_methods():
            code = m.get_code()
            if code:
                strings = [ins.get_output() for ins in code.get_bc().get_instructions() if ins.get_name() == "const-string"]
                if strings:
                    print(f"  Method {m.get_name()}: {strings}")
