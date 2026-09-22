#!/usr/bin/env python3
import pypdf

reader = pypdf.PdfReader("/tmp/Godox_X3Pro.pdf")
print(f"Total pages: {len(reader.pages)}")
for idx, page in enumerate(reader.pages):
    text = page.extract_text()
    if any(k in text.lower() for k in ["bluetooth", "app", "蓝牙", "配对", "pin", "password", "密码"]):
        print(f"--- Page {idx+1} ---")
        for line in text.splitlines():
            if any(k in line.lower() for k in ["bluetooth", "app", "蓝牙", "配对", "pin", "password", "mac", "code", "reset", "连接"]):
                print("  ", line.strip())
