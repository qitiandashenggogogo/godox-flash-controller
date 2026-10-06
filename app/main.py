import os
import sys
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.ble_manager import manager

# macOS 关键修复：当本进程从 .app/Contents/Resources/backend/GodoxControllerBackend 启动时，
# NSBundle.mainBundle() 指向的是 Python.framework，不是 com.godoxcontroller.desktop。
# CoreBluetooth 的权限授权会绑到这个错误的 Bundle 上 → 用户点「允许」无效。
# 这里强制用真正的 .app Bundle 替换 mainBundle，让后续所有 BLE 调用都绑到正确的 Bundle ID。
try:
    from Foundation import NSBundle, NSURL
    from objc import setAssociatedObject
    executable_path = os.path.realpath(sys.executable)
    app_bundle_path = None
    # 1) 标准启动路径：python 嵌在 .app/Contents/Resources/backend/ 里
    if executable_path.endswith("/Contents/Resources/" + os.path.basename(executable_path)) or "/Contents/Resources/" in executable_path:
        candidate = executable_path
        while candidate and not candidate.endswith(".app"):
            candidate = os.path.dirname(candidate)
            if candidate == "/" or not candidate:
                break
        if candidate and candidate.endswith(".app"):
            app_bundle_path = candidate
    # 2) 兜底：环境变量允许 Swift 外壳显式告诉后端它是谁
    if not app_bundle_path:
        env_bundle = os.environ.get("GODOX_APP_BUNDLE_PATH", "").strip()
        if env_bundle and os.path.isdir(env_bundle):
            app_bundle_path = env_bundle
    if app_bundle_path and os.path.isdir(app_bundle_path):
        real_bundle = NSBundle.bundleWithPath_(app_bundle_path)
        if real_bundle is not None and real_bundle.bundleIdentifier() == "com.godoxcontroller.desktop":
            # 把真实 Bundle 挂到 mainBundle 的关联对象上，让所有 NSBundle.mainBundle() 返回它
            setAssociatedObject(NSBundle, "mainBundle", real_bundle, 1)  # OBJC_ASSOCIATION_RETAIN_NONATOMIC
            # ble_manager 里的 bleak → CoreBluetooth 后续会读到正确的 Bundle ID
            print(f"[bundle-fix] Main bundle rebound to: {app_bundle_path}")
        else:
            bid = real_bundle.bundleIdentifier() if real_bundle else "nil"
            print(f"[bundle-fix] WARN: candidate {app_bundle_path} bundleIdentifier={bid}", file=sys.stderr)
except Exception as e:
    print(f"[bundle-fix] non-fatal: {e}", file=sys.stderr)

app = FastAPI(title="Godox 引闪器桌面控制台")

@app.get("/api/health")
async def health():
    return {"app": "godox-controller", "version": "1.1"}

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
    if req.mode not in {"fraction", "decimal", "dual"}:
        raise HTTPException(status_code=400, detail="不支持的功率显示格式")
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
        raise HTTPException(status_code=404, detail="未找到该方案")
    return {"success": True, "status": manager.get_status()}

@app.post("/api/presets/{preset_id}/default")
async def set_default_preset(preset_id: str):
    if not manager.set_default_preset(preset_id):
        raise HTTPException(status_code=404, detail="未找到该方案")
    return {"success": True, "status": manager.get_status()}

@app.post("/api/presets/apply_default")
async def apply_default_preset():
    if not manager.apply_default_preset():
        raise HTTPException(status_code=404, detail="尚未设定默认方案")
    return {"success": True, "status": manager.get_status()}

@app.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: str):
    if not manager.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="未找到该方案")
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
    message = "✓ 已恢复关闭前的全部组别设置" if result["action"] == "restored" else "✓ 已全部 OFF，已保存恢复点"
    html = ("<!doctype html><meta charset=utf-8><title>OFF</title>"
             "<body style='font-family:system-ui;background:#0d0f12;color:#fff;padding:40px;text-align:center'>"
             "<h2>" + (message if success else "× 操作失败") + "</h2>"
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
        return FileResponse(
            index_file,
            headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
        )
    return HTMLResponse("<h1>Godox 引闪器桌面控制台</h1><p>请配置 static/index.html</p>")
