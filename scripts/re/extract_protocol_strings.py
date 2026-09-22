#!/usr/bin/env python3
import re

with open("/tmp/godox_flash_apk_extracted/classes.dex", "rb") as f:
    d = f.read()

targets = [b"BluetoothSendData", b"CommandPolicy", b"CRC8Util", b"000000", b"PHONE->BLE"]
for t in targets:
    print(f"=== Target: {t.decode()} ===")
    idx = 0
    count = 0
    while count < 5:
        idx = d.find(t, idx)
        if idx == -1:
            break
        start = max(0, idx - 100)
        end = min(len(d), idx + 200)
        chunk = d[start:end]
        clean = "".join(chr(b) if 32 <= b <= 126 else " " for b in chunk)
        print(f"  [{hex(idx)}] {clean}")
        idx += len(t)
        count += 1
