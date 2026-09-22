#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "HomePageFragment" in c.get_name() or "FlashGroup" in c.get_name():
        for m in c.get_methods():
            code = m.get_code()
            if code:
                for ins in code.get_bc().get_instructions():
                    out = ins.get_output()
                    if "setLampOn" in out or "isLampOn" in out:
                        print(f"{c.get_name()} -> {m.get_name()} calls {out}")
