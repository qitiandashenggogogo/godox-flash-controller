#!/usr/bin/env python3
import re
import glob

for dex in glob.glob("/tmp/godox_flash_apk_extracted/classes*.dex"):
    with open(dex, "rb") as f:
        data = f.read()
    classes = set(re.findall(rb"Lcom/linking/godoxflash/[a-zA-Z0-9_$/]+;", data))
    print(f"=== {dex} ===")
    for c in sorted(classes):
        c_str = c.decode("ascii", errors="ignore")
        if any(k in c_str.lower() for k in ["ble", "bluetooth", "flash", "cmd", "protocol", "data", "send"]):
            print("  ", c_str)
