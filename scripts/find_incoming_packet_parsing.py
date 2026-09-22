#!/usr/bin/env python3
from androguard.core.dex import DEX

d = DEX(open("/tmp/godox_flash_apk_extracted/classes.dex", "rb").read())

for c in d.get_classes():
    cname = c.get_name()
    if any(k in cname for k in ["CommandPolicy", "BluetoothLeService", "BlutoothLE", "BlueToothCallBack", "MyBluetooth", "HomePageFragment"]):
        for m in c.get_methods():
            code = m.get_code()
            if code:
                for ins in code.get_bc().get_instructions():
                    out = ins.get_output()
                    if any(k in out for k in ["aget-byte", "onCharacteristicChanged", "sendSucceed", "OnNotificationCallback"]):
                        print(f"{cname} -> {m.get_name()}: {ins.get_name()} {out}")
