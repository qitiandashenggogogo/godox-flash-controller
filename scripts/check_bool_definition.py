#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "BluetoothSendData" in c.get_name():
        for m in c.get_methods():
            if m.get_name() == "getSingleGroupData":
                code = m.get_code()
                insns = list(code.get_bc().get_instructions())
                for i, ins in enumerate(insns):
                    out = ins.get_output()
                    if "v17" in out or "v18" in out:
                        print(f"{i}: {ins.get_name()} {out}")
