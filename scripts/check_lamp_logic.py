#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "FlashGroupActivity" in c.get_name() or "HomePageFragment" in c.get_name():
        for m in c.get_methods():
            if any(k in m.get_name().lower() for k in ["lamp", "model"]):
                print(f"=== {c.get_name()} -> {m.get_name()} ===")
                code = m.get_code()
                if code:
                    for ins in code.get_bc().get_instructions():
                        out = ins.get_output()
                        if any(k in out for k in ["Lamp", "lamp", "PROP", "100%", "25%"]):
                            print("   ", ins.get_name(), out)
