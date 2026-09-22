#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    name = c.get_name()
    for m in c.get_methods():
        code = m.get_code()
        if code:
            for ins in code.get_bc().get_instructions():
                out = ins.get_output()
                if "getDecimalPower" in out or "setDecimalPower" in out:
                    print(f"{name} -> {m.get_name()} calls {out}")
