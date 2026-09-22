#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "Coun" == c.get_name().split("/")[-1].replace(";", ""):
        print("Found Coun")
        for m in c.get_methods():
            print(f"--- Method: {m.get_name()} ---")
            code = m.get_code()
            if code:
                for ins in code.get_bc().get_instructions():
                    print("   ", ins.get_name(), ins.get_output())
