#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    if "HomePageFragment" == c.get_name().split("/")[-1].replace(";", ""):
        for m in c.get_methods():
            if any(k in m.get_name() for k in ["initData", "initView", "onStart", "onResume"]):
                print(f"=== {m.get_name()} ===")
                code = m.get_code()
                if code:
                    for ins in code.get_bc().get_instructions():
                        out = ins.get_output()
                        if any(k in out for k in ["SharedPreferences", "flashdata", "sendAll", "TCCommand"]):
                            print("  ", ins.get_name(), out)
