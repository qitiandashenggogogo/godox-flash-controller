#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "FlashGroupActivity" == c.get_name().split("/")[-1].replace(";", ""):
        for m in c.get_methods():
            if m.get_name() == "onClick":
                code = m.get_code()
                insns = list(code.get_bc().get_instructions())
                for i, ins in enumerate(insns):
                    if "setLamp" in ins.get_output():
                        for j in range(max(0, i-5), i+2):
                            print(f"{j}: {insns[j].get_name()} {insns[j].get_output()}")
                        print("---")
