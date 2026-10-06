"""Per-user backend ownership and process identity."""
import fcntl
import json
import os
import uuid
from pathlib import Path

STATE_DIR = Path(os.environ.get("GODOX_CONTROLLER_STATE_DIR") or Path.home() / "Library/Application Support/Godox Controller")
INSTANCE_ID = uuid.uuid4().hex
PROTOCOL_VERSION = 1
_lock_file = None


def acquire_backend_lock():
    global _lock_file
    if _lock_file is not None:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    handle = (STATE_DIR / "backend.lock").open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("已有神牛后端正在运行，请先退出对应控制台后再重试。") from None
    # Old releases did not participate in this lock. Never silently adopt them.
    if not os.environ.get("GODOX_CONTROLLER_STATE_DIR"):
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open("http://127.0.0.1:8765/api/health", timeout=0.5) as response:
                legacy = json.load(response)
        except (OSError, ValueError):
            legacy = None
        if isinstance(legacy, dict) and legacy.get("app") == "godox-controller":
            handle.close()
            raise RuntimeError("检测到旧版神牛后端正在运行，请退出旧控制台后再重试。")
    handle.seek(0)
    handle.truncate()
    json.dump({"pid": os.getpid(), "instance_id": INSTANCE_ID}, handle)
    handle.flush()
    # Keep the inode and descriptor alive; unlinking a held lock breaks exclusion.
    _lock_file = handle


def update_lock_port(port):
    if _lock_file is None:
        return
    _lock_file.seek(0)
    _lock_file.truncate()
    json.dump({"pid": os.getpid(), "instance_id": INSTANCE_ID, "port": port, "protocol_version": PROTOCOL_VERSION}, _lock_file)
    _lock_file.flush()


def read_theme():
    try:
        theme = json.loads((STATE_DIR / "appearance.json").read_text())["theme"]
        return theme if theme in {"dark", "light", "system"} else "system"
    except (OSError, ValueError, KeyError, TypeError):
        return "system"


def save_theme(theme):
    target = STATE_DIR / "appearance.json"
    temporary = STATE_DIR / (".appearance." + str(os.getpid()) + ".tmp")
    with temporary.open("w") as handle:
        json.dump({"theme": theme}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
