#!/usr/bin/env python3
with open("app/static/index.html", "r") as f:
    content = f.read()
content = content.replace('"D": { mode: "OFF"', '"D": { mode: "M"')
content = content.replace('"E": { mode: "OFF"', '"E": { mode: "M"')
with open("app/static/index.html", "w") as f:
    f.write(content)
print("Updated defaults in app/static/index.html")
