#!/usr/bin/env python3
with open("app/ble_manager.py", "r") as f:
    content = f.read()
content = content.replace('"mode": "OFF"', '"mode": "M"')
with open("app/ble_manager.py", "w") as f:
    f.write(content)
print("Updated defaults in app/ble_manager.py")
