import os
import asyncio
import html
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.runtime import acquire_backend_lock, INSTANCE_ID, PROTOCOL_VERSION, read_theme, save_theme
from app.version import read_app_version

# Direct uvicorn imports must also acquire ownership before touching state.
acquire_backend_lock()
# Report bundle identity before CoreBluetooth is imported; stderr only, never touches
# NSBundle.mainBundle(), so it cannot change how Bluetooth authorization is attributed.
from app.bundle_diagnostics import diagnose
diagnose()
from app.ble_manager import manager

@asynccontextmanager
async def lifespan(application):
    try:
        yield
    finally:
        manager.auto_reconnect = False
        tasks = [task for task in (manager.battery_refresh_task, manager.reconnect_task)
                 if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if manager.client and manager.client.is_connected:
            await asyncio.wait_for(manager.disconnect(), timeout=2)


app = FastAPI(title="引闪控制台", lifespan=lifespan)


class InstanceGuard:
    """ASGI middleware that pins every mutating API call to a single page instance."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/") and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            headers = dict(scope.get("headers", []))
            if headers.get(b"x-godox-instance") != INSTANCE_ID.encode():
                from fastapi.responses import JSONResponse
                response = JSONResponse(status_code=409, content={"detail": "页面已过期，请重新打开控制台。"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(InstanceGuard)


class ThemeRequest(BaseModel):
    theme: str


@app.post("/api/theme")
async def set_theme(req: ThemeRequest):
    if req.theme not in {"dark", "light", "system"}:
        raise HTTPException(status_code=400, detail="请选择可用的外观")
    save_theme(req.theme)
    return {"success": True}


@app.get("/api/health")
async def health():
    # Info.plist is the only version source; the UI renders exactly this value.
    return {"app": "godox-controller", "version": read_app_version(), "instance_id": INSTANCE_ID, "protocol_version": PROTOCOL_VERSION}


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
    mode: str  # "fraction", "decimal", "dual"


class ActiveGroupRequest(BaseModel):
    group: str  # "ALL", "A", "B", "C", "D", "E"


class GroupManageRequest(BaseModel):
    group: str


class PresetCreateRequest(BaseModel):
    name: str


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
        raise HTTPException(status_code=400, detail="频道只能是 1 到 32")
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
    if req.mode not in {"fraction", "decimal", "dual"}:
        raise HTTPException(status_code=400, detail="请选择可用的功率格式")
    manager.set_display_mode(req.mode)
    return {"success": True, "status": manager.get_status()}


@app.post("/api/set_active_group")
async def set_active_group(req: ActiveGroupRequest):
    manager.set_active_group(req.group)
    return {"success": True, "status": manager.get_status()}


@app.get("/api/presets")
async def list_presets():
    return {"presets": manager.list_presets(), "default_preset_id": manager.default_preset_id}


@app.post("/api/presets")
async def create_preset(req: PresetCreateRequest):
    try:
        preset = manager.create_preset(req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "preset": preset, "status": manager.get_status()}


@app.post("/api/presets/{preset_id}/apply")
async def apply_preset(preset_id: str):
    if not manager.apply_preset(preset_id):
        raise HTTPException(status_code=404, detail="找不到这个预设")
    return {"success": True, "status": manager.get_status()}


@app.post("/api/presets/{preset_id}/default")
async def set_default_preset(preset_id: str):
    if not manager.set_default_preset(preset_id):
        raise HTTPException(status_code=404, detail="找不到这个预设")
    return {"success": True, "status": manager.get_status()}


@app.post("/api/presets/apply_default")
async def apply_default_preset():
    if not manager.apply_default_preset():
        raise HTTPException(status_code=404, detail="还没有常用预设")
    return {"success": True, "status": manager.get_status()}


@app.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: str):
    if not manager.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="找不到这个预设")
    return {"success": True, "status": manager.get_status()}


@app.post("/api/all_off")
async def all_off():
    success = await manager.all_off()
    return {"success": success, "status": manager.get_status()}


@app.post("/api/toggle_all_off")
async def toggle_all_off():
    result = await manager.toggle_all_off()
    return {**result, "status": manager.get_status()}


@app.post("/api/all_off_form", response_class=HTMLResponse)
async def all_off_form():
    result = await manager.toggle_all_off()
    success = result["success"]
    message = "✓ 关闭前设置已发送" if result["action"] == "restored" else "✓ 面板内灯组已设为 OFF，可恢复"
    html = ("<!doctype html><meta charset=utf-8><title>闪光开关</title>"
             "<body style='font-family:system-ui;background:#0d0f12;color:#fff;padding:40px;text-align:center'>"
             "<h2>" + (message if success else "× 操作未成功") + "</h2>"
             "<a href='/' style='color:#e58e26'>← 返回</a></body>")
    return HTMLResponse(html)


@app.post("/api/sync_to_device")
async def sync_to_device():
    success = await manager.sync_all_to_device()
    return {"success": success, "status": manager.get_status()}


@app.post("/api/sync_to_device_form", response_class=HTMLResponse)
async def sync_to_device_form():
    success = await manager.sync_all_to_device()
    html = ("<!doctype html><meta charset=utf-8><title>写入设置</title>"
             "<body style='font-family:system-ui;background:#0d0f12;color:#fff;padding:40px;text-align:center'>"
             "<h2>" + ("✓ 面板内灯组设置已发送" if success else "× 设置未发送") + "</h2>"
             "<a href='/' style='color:#e58e26'>← 返回</a></body>")
    return HTMLResponse(html)


@app.post("/api/test_fire")
async def test_fire():
    return await manager.test_fire()


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
        with open(index_file, encoding="utf-8") as handle:
            page = handle.read()
        # Version comes from Info.plist, escaped because it is interpolated into markup.
        page = (page.replace("__GODOX_INSTANCE_ID__", INSTANCE_ID)
                    .replace("__GODOX_THEME__", read_theme())
                    .replace("__GODOX_APP_VERSION__", html.escape(read_app_version())))
        return HTMLResponse(page, headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})
    return HTMLResponse("<h1>引闪控制台</h1><p>缺少界面文件：static/index.html</p>")
