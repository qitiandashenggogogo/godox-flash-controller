import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.ble_manager import manager

app = FastAPI(title="Godox X3 Pro 桌面控制台")

class SetGroupRequest(BaseModel):
    group: str
    mode: str = "M"
    power: str = None
    dec_val: int = None
    sound: bool = False
    lamp: bool = False

class ConnectRequest(BaseModel):
    address: str = None

class ChannelRequest(BaseModel):
    channel: int

class GlobalLampRequest(BaseModel):
    lamp_on: bool

class GlobalSoundRequest(BaseModel):
    sound_on: bool

class AdjustAllRequest(BaseModel):
    delta: int = 1

class DisplayModeRequest(BaseModel):
    mode: str # "fraction", "decimal", "dual"

class ActiveGroupRequest(BaseModel):
    group: str # "ALL", "A", "B", "C", "D", "E"

class GroupManageRequest(BaseModel):
    group: str

@app.get("/api/status")
async def get_status():
    return manager.get_status()

@app.post("/api/scan_devices")
async def scan_devices():
    devs = await manager.scan_devices()
    return {"devices": devs, "status": manager.get_status()}

@app.post("/api/connect")
async def connect(req: ConnectRequest = ConnectRequest()):
    success = await manager.connect(req.address)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/disconnect")
async def disconnect():
    await manager.disconnect()
    return {"success": True, "status": manager.get_status()}

@app.post("/api/set_group")
async def set_group(req: SetGroupRequest):
    success = await manager.set_group(
        group=req.group,
        mode=req.mode,
        power=req.power,
        dec_val=req.dec_val,
        sound=req.sound,
        lamp=req.lamp,
    )
    return {"success": success, "status": manager.get_status()}

@app.post("/api/add_group")
async def add_group(req: GroupManageRequest):
    success = manager.add_group(req.group)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/remove_group")
async def remove_group(req: GroupManageRequest):
    success = manager.remove_group(req.group)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/set_channel")
async def set_channel(req: ChannelRequest):
    if req.channel < 1 or req.channel > 32:
        raise HTTPException(status_code=400, detail="频道范围必须在 1-32 之间")
    success = await manager.send_tc_command(channel=req.channel)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/set_global_lamp")
async def set_global_lamp(req: GlobalLampRequest):
    success = await manager.send_tc_command(global_lamp=req.lamp_on)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/set_global_sound")
async def set_global_sound(req: GlobalSoundRequest):
    success = await manager.send_tc_command(global_sound=req.sound_on)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/adjust_all")
async def adjust_all(req: AdjustAllRequest):
    success = await manager.adjust_all_groups(req.delta)
    return {"success": success, "status": manager.get_status()}

@app.post("/api/set_display_mode")
async def set_display_mode(req: DisplayModeRequest):
    manager.power_display_mode = req.mode
    return {"success": True, "status": manager.get_status()}

@app.post("/api/set_active_group")
async def set_active_group(req: ActiveGroupRequest):
    manager.active_group = req.group.upper()
    return {"success": True, "status": manager.get_status()}


@app.post("/api/all_off")
async def all_off():
    success = await manager.all_off()
    return {"success": success, "status": manager.get_status()}

@app.post("/api/all_off_form", response_class=HTMLResponse)
async def all_off_form():
    success = await manager.all_off()
    html = ("<!doctype html><meta charset=utf-8><title>OFF</title>"
             "<body style='font-family:system-ui;background:#0d0f12;color:#fff;padding:40px;text-align:center'>"
             "<h2>" + ("✓ 已全部 OFF，功率已保留" if success else "× OFF 失败") + "</h2>"
             "<a href='/' style='color:#e58e26'>← 返回</a></body>")
    return HTMLResponse(html)

@app.post("/api/sync_to_device")
async def sync_to_device():
    success = await manager.sync_all_to_device()
    return {"success": success, "status": manager.get_status()}

@app.post("/api/sync_to_device_form", response_class=HTMLResponse)
async def sync_to_device_form():
    success = await manager.sync_all_to_device()
    html = ("<!doctype html><meta charset=utf-8><title>Sync</title>"
             "<body style='font-family:system-ui;background:#0d0f12;color:#fff;padding:40px;text-align:center'>"
             "<h2>" + ("✓ 桌面配置已写入实体引闪器（A~E 按桌面设置生效）" if success else "× 同步失败") + "</h2>"
             "<a href='/' style='color:#e58e26'>← 返回</a></body>")
    return HTMLResponse(html)

@app.post("/api/test_fire")
async def test_fire():
    success = await manager.test_fire()
    return {"success": success}

@app.post("/api/save_screenshot")
async def save_screenshot(request: Request):
    data = await request.body()
    target_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "screenshots")
    os.makedirs(target_dir, exist_ok=True)
    out_path = os.path.join(target_dir, "m3_ui_mvp.png")
    with open(out_path, "wb") as f:
        f.write(data)
    return {"success": True, "path": out_path, "size": len(data)}

@app.post("/api/reset_all")
async def reset_all():
    results = {}
    for g in manager.visible_groups:
        mode = "M" if g in ["A", "B", "C"] else "OFF"
        ok = await manager.set_group(g, mode, dec_val=30)
        results[g] = ok
    return {"success": True, "results": results, "status": manager.get_status()}

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(
            index_file,
            headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
        )
    return HTMLResponse("<h1>Godox X3 Pro 桌面控制台</h1><p>请配置 static/index.html</p>")
