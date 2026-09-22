#!/usr/bin/env python3
import os
import glob
import re

dex_files = glob.glob("/tmp/godox_flash_apk_extracted/classes*.dex")
print(f"Found {len(dex_files)} DEX files.")

keywords = ["0000fff", "0000ffe", "godox", "ble", "power", "flash", "trigger", "x3", "xpro", "x2t"]

for dex in dex_files:
    with open(dex, "rb") as f:
        data = f.read()

    # Find all printable ASCII strings >= 4 chars
    strings = re.findall(b"[\x20-\x7e]{4,}", data)
    print(f"File {dex}: {len(strings)} strings")

    # Filter for interesting class names or protocol tags
    for s in strings:
        s_str = s.decode("ascii", errors="ignore")
        if any(target in s_str.lower() for target in ["sendcmd", "senddata", "writechar", "fff1", "fff2", "fff4", "ffe1"]):
            print("  [CMD MATCH]", s_str)
        elif s_str.startswith("Lcom/godox") or s_str.startswith("Lcom/linking"):
            if "ble" in s_str.lower() or "protocol" in s_str.lower() or "cmd" in s_str.lower():
                print("  [CLASS]", s_str)
