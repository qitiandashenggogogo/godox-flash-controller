#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    for m in c.get_methods():
        code = m.get_code()
        if code:
            for ins in code.get_bc().get_instructions():
                out = ins.get_output()
                if "1/128" in out or "1/64" in out or "1/256" in out or "PowerSeekbar" in c.get_name():
                    print(f"{c.get_name()} -> {m.get_name()} : {ins.get_name()} {out}")
