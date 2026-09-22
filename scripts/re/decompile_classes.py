#!/usr/bin/env python3
from androguard.misc import AnalyzeAPK

print("Analyzing APK with androguard...")
a, d, dx = AnalyzeAPK("/tmp/godox_flash.apk")
print("Analysis complete.")

target_classes = ["BluetoothSendData", "CommandPolicy", "CRC8Util"]

with open("/tmp/decompiled_protocol.java", "w") as out_f:
    for c in dx.get_classes():
        if any(t in c.name for t in target_classes):
            out_f.write(f"\n\n// =================== CLASS: {c.name} ===================\n")
            print(f"Decompiling class: {c.name}")
            for m in c.get_methods():
                out_f.write(f"\n// Method: {m.name}\n")
                try:
                    src = m.get_source()
                    out_f.write(str(src) + "\n")
                except Exception as e:
                    out_f.write(f"// Decompile error: {e}\n")

print("Decompilation finished. Saved to /tmp/decompiled_protocol.java")
