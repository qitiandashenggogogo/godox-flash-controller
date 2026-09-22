#!/usr/bin/env python3
endpoints = '''
@app.post("/api/all_off")
async def all_off():
    success = await manager.all_off()
    return {"success": success, "status": manager.get_status()}

@app.post("/api/sync_to_device")
async def sync_to_device():
    success = await manager.sync_all_to_device()
    return {"success": success, "status": manager.get_status()}

'''

with open("app/main.py") as f:
    content = f.read()

assert '"/api/all_off"' not in content
content = content.replace('@app.post("/api/test_fire")', endpoints + '@app.post("/api/test_fire")', 1)

with open("app/main.py", "w") as f:
    f.write(content)
print("api endpoints added")
