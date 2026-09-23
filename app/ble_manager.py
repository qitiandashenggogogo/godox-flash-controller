import asyncio
import copy
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from bleak import BleakClient, BleakScanner

logger = logging.getLogger("godox_ble")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_STATE_FILE = PROJECT_ROOT / "config" / "studio_state.json"
# 配置不能写在 .app 或源码目录：升级/替换应用时，用户的布光方案必须保留。
# 环境变量仅供自动化验证使用，正常用户始终使用自己的 Application Support 目录。
STATE_DIR = Path(os.environ.get("GODOX_CONTROLLER_STATE_DIR", "")) if os.environ.get("GODOX_CONTROLLER_STATE_DIR") else Path.home() / "Library" / "Application Support" / "Godox Controller"
STATE_FILE = STATE_DIR / "studio_state.json"
STATE_SCHEMA_VERSION = 2

SERVICE_FEC0 = "0000fec0-0000-1000-8000-00805f9b34fb"
CHAR_FEC7 = "0000fec7-0000-1000-8000-00805f9b34fb"
CHAR_FEC8 = "0000fec8-0000-1000-8000-00805f9b34fb"

SERVICE_FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
CHAR_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"

CRC8_TABLE = [
    0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83, 0xc2, 0x9c, 0x7e, 0x20, 0xa3, 0xfd, 0x1f, 0x41,
    0x9d, 0xc3, 0x21, 0x7f, 0xfc, 0xa2, 0x40, 0x1e, 0x5f, 0x01, 0xe3, 0xbd, 0x3e, 0x60, 0x82, 0xdc,
    0x23, 0x7d, 0x9f, 0xc1, 0x42, 0x1c, 0xfe, 0xa0, 0xe1, 0xbf, 0x5d, 0x03, 0x80, 0xde, 0x3c, 0x62,
    0xbe, 0xe0, 0x02, 0x5c, 0xdf, 0x81, 0x63, 0x3d, 0x7c, 0x22, 0xc0, 0x9e, 0x1d, 0x43, 0xa1, 0xff,
    0x46, 0x18, 0xfa, 0xa4, 0x27, 0x79, 0x9b, 0xc5, 0x84, 0xda, 0x38, 0x66, 0xe5, 0xbb, 0x59, 0x07,
    0xdb, 0x85, 0x67, 0x39, 0xba, 0xe4, 0x06, 0x58, 0x19, 0x47, 0xa5, 0xfb, 0x78, 0x26, 0xc4, 0x9a,
    0x65, 0x3b, 0xd9, 0x87, 0x04, 0x5a, 0xb8, 0xe6, 0xa7, 0xf9, 0x1b, 0x45, 0xc6, 0x98, 0x7a, 0x24,
    0xf8, 0xa6, 0x44, 0x1a, 0x99, 0xc7, 0x25, 0x7b, 0x3a, 0x64, 0x86, 0xd8, 0x5b, 0x05, 0xe7, 0xb9,
    0x8c, 0xd2, 0x30, 0x6e, 0xed, 0xb3, 0x51, 0x0f, 0x4e, 0x10, 0xf2, 0xac, 0x2f, 0x71, 0x93, 0xcd,
    0x11, 0x4f, 0xad, 0xf3, 0x70, 0x2e, 0xcc, 0x92, 0xd3, 0x8d, 0x6f, 0x31, 0xb2, 0xec, 0x0e, 0x50,
    0xaf, 0xf1, 0x13, 0x4d, 0xce, 0x90, 0x72, 0x2c, 0x6d, 0x33, 0xd1, 0x8f, 0x0c, 0x52, 0xb0, 0xee,
    0x32, 0x6c, 0x8e, 0xd0, 0x53, 0x0d, 0xef, 0xb1, 0xf0, 0xae, 0x4c, 0x12, 0x91, 0xcf, 0x2d, 0x73,
    0xca, 0x94, 0x76, 0x28, 0xab, 0xf5, 0x17, 0x49, 0x08, 0x56, 0xb4, 0xea, 0x69, 0x37, 0xd5, 0x8b,
    0x57, 0x09, 0xeb, 0xb5, 0x36, 0x68, 0x8a, 0xd4, 0x95, 0xcb, 0x29, 0x77, 0xf4, 0xaa, 0x48, 0x16,
    0xe9, 0xb7, 0x55, 0x0b, 0x88, 0xd6, 0x34, 0x6a, 0x2b, 0x75, 0x97, 0xc9, 0x4a, 0x14, 0xf6, 0xa8,
    0x74, 0x2a, 0xc8, 0x96, 0x15, 0x4b, 0xa9, 0xf7, 0xb6, 0xe8, 0x0a, 0x54, 0xd7, 0x89, 0x6b, 0x35
]

POWER_TABLE = [
    {"fraction": "1/256", "decimal": "2.0", "dec_val": 20},
    {"fraction": "1/256+0.3", "decimal": "2.3", "dec_val": 23},
    {"fraction": "1/256+0.7", "decimal": "2.7", "dec_val": 27},
    {"fraction": "1/128", "decimal": "3.0", "dec_val": 30},
    {"fraction": "1/128+0.3", "decimal": "3.3", "dec_val": 33},
    {"fraction": "1/128+0.7", "decimal": "3.7", "dec_val": 37},
    {"fraction": "1/64", "decimal": "4.0", "dec_val": 40},
    {"fraction": "1/64+0.3", "decimal": "4.3", "dec_val": 43},
    {"fraction": "1/64+0.7", "decimal": "4.7", "dec_val": 47},
    {"fraction": "1/32", "decimal": "5.0", "dec_val": 50},
    {"fraction": "1/32+0.3", "decimal": "5.3", "dec_val": 53},
    {"fraction": "1/32+0.7", "decimal": "5.7", "dec_val": 57},
    {"fraction": "1/16", "decimal": "6.0", "dec_val": 60},
    {"fraction": "1/16+0.3", "decimal": "6.3", "dec_val": 63},
    {"fraction": "1/16+0.7", "decimal": "6.7", "dec_val": 67},
    {"fraction": "1/8", "decimal": "7.0", "dec_val": 70},
    {"fraction": "1/8+0.3", "decimal": "7.3", "dec_val": 73},
    {"fraction": "1/8+0.7", "decimal": "7.7", "dec_val": 77},
    {"fraction": "1/4", "decimal": "8.0", "dec_val": 80},
    {"fraction": "1/4+0.3", "decimal": "8.3", "dec_val": 83},
    {"fraction": "1/4+0.7", "decimal": "8.7", "dec_val": 87},
    {"fraction": "1/2", "decimal": "9.0", "dec_val": 90},
    {"fraction": "1/2+0.3", "decimal": "9.3", "dec_val": 93},
    {"fraction": "1/2+0.7", "decimal": "9.7", "dec_val": 97},
    {"fraction": "1/1", "decimal": "10.0", "dec_val": 100},
]

GROUP_MAP = {
    "0": 0x00, "1": 0x01, "2": 0x02, "3": 0x03, "4": 0x04,
    "5": 0x05, "6": 0x06, "7": 0x07, "8": 0x08, "9": 0x09,
    "A": 0x0A, "B": 0x0B, "C": 0x0C, "D": 0x0D, "E": 0x0E, "F": 0x0F,
}
REVERSE_GROUP_MAP = {v: k for k, v in GROUP_MAP.items()}

ALL_AVAILABLE_GROUPS = ["A", "B", "C", "D", "E", "F", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
MODE_MAP = {"M": 0x01, "TTL": 0x00, "OFF": 0x03}
REVERSE_MODE_MAP = {0x01: "M", 0x00: "TTL", 0x03: "OFF"}

def calc_crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = CRC8_TABLE[crc ^ b]
    return crc

def dec_to_fraction(dec_val: int) -> str:
    closest = min(POWER_TABLE, key=lambda x: abs(x["dec_val"] - dec_val))
    return closest["fraction"]

class BleManager:
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.device_address: Optional[str] = None
        self.device_name: str = "未选择引闪器"
        self.is_connected: bool = False
        self.last_rssi: Optional[int] = None
        self.last_ack: Optional[str] = None
        self.last_msg: str = "空闲"
        self.reconnect_task: Optional[asyncio.Task] = None
        self.auto_reconnect: bool = True
        self._lock = asyncio.Lock()
        self._test_fire_lock = asyncio.Lock()
        self._test_fire_ack_event = asyncio.Event()
        self.last_test_fire_ack: Optional[str] = None

        self.discovered_devices: List[Dict[str, Any]] = []

        # Defaults
        self.channel: int = 6
        self.wireless_id: int = 0
        self.global_lamp: bool = False
        self.global_sound: bool = True
        self.power_display_mode: str = "decimal"
        self.active_group: str = "ALL"

        # 新安装也必须可直接使用；旧用户的 state 会在 load_state_from_disk 中覆盖这些通用初值。
        self.visible_groups: List[str] = ["A", "B", "C", "D", "E"]
        self.groups: Dict[str, Dict[str, Any]] = {
            group: {
                "mode": "M",
                "power": "1/64",
                "decimal_power": "4.0",
                "dec_val": 40,
                "sound": False,
                "lamp": False,
            }
            for group in self.visible_groups
        }

        self.load_state_from_disk()

    def _current_state(self) -> Dict[str, Any]:
        """仅保存桌面工作状态；命名方案会保存这份状态的独立快照。"""
        return {
            "channel": self.channel,
            "wireless_id": self.wireless_id,
            "global_lamp": self.global_lamp,
            "global_sound": self.global_sound,
            "power_display_mode": self.power_display_mode,
            "active_group": self.active_group,
            "visible_groups": copy.deepcopy(self.visible_groups),
            "groups": copy.deepcopy(self.groups),
        }

    def _apply_current_state(self, state: Dict[str, Any]) -> None:
        self.channel = int(state.get("channel", self.channel))
        self.wireless_id = int(state.get("wireless_id", self.wireless_id))
        self.global_lamp = bool(state.get("global_lamp", self.global_lamp))
        self.global_sound = bool(state.get("global_sound", self.global_sound))
        self.power_display_mode = state.get("power_display_mode", self.power_display_mode)
        self.active_group = state.get("active_group", self.active_group)
        visible = state.get("visible_groups", self.visible_groups)
        self.visible_groups = [g for g in visible if g in ALL_AVAILABLE_GROUPS]
        groups = state.get("groups", {})
        self.groups = {g: copy.deepcopy(data) for g, data in groups.items() if g in ALL_AVAILABLE_GROUPS and isinstance(data, dict)}

    def _state_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "current_state": self._current_state(),
            "presets": copy.deepcopy(self.presets),
            "default_preset_id": self.default_preset_id,
            "device": {"address": self.device_address, "name": self.device_name},
        }

    def _load_payload(self, data: Dict[str, Any]) -> None:
        # 兼容 1.0 版本：旧文件把当前状态直接放在根层。
        current_state = data.get("current_state", data)
        if isinstance(current_state, dict):
            self._apply_current_state(current_state)
        device = data.get("device", data)
        if isinstance(device, dict):
            self.device_address = device.get("address", data.get("device_address", self.device_address))
            self.device_name = device.get("name", data.get("device_name", self.device_name)) or "未选择引闪器"
        raw_presets = data.get("presets", [])
        self.presets = [p for p in raw_presets if isinstance(p, dict) and p.get("id") and p.get("name") and isinstance(p.get("state"), dict)]
        self.default_preset_id = data.get("default_preset_id")
        if self.default_preset_id and not any(p["id"] == self.default_preset_id for p in self.presets):
            self.default_preset_id = None

    def load_state_from_disk(self):
        self.presets: List[Dict[str, Any]] = []
        self.default_preset_id: Optional[str] = None
        try:
            source = STATE_FILE
            migrated_from_legacy = False
            if not source.exists() and LEGACY_STATE_FILE.exists():
                source = LEGACY_STATE_FILE
                migrated_from_legacy = True
            if source.exists():
                with source.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._load_payload(data)
                    logger.info("Loaded studio state from %s.", source)
                    if migrated_from_legacy:
                        self.save_state_to_disk()
                        logger.info("Migrated legacy studio state into %s.", STATE_FILE)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def save_state_to_disk(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = STATE_DIR / f".{STATE_FILE.name}.{os.getpid()}.tmp"
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(self._state_payload(), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, STATE_FILE)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def list_presets(self) -> List[Dict[str, Any]]:
        return [
            {"id": p["id"], "name": p["name"], "is_default": p["id"] == self.default_preset_id}
            for p in self.presets
        ]

    def create_preset(self, name: str) -> Dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("方案名称不能为空")
        if len(clean_name) > 40:
            raise ValueError("方案名称不能超过 40 个字符")
        if any(p["name"] == clean_name for p in self.presets):
            raise ValueError("已有同名方案，请换一个名称")
        preset = {"id": uuid.uuid4().hex, "name": clean_name, "state": self._current_state()}
        self.presets.append(preset)
        self.save_state_to_disk()
        return {"id": preset["id"], "name": preset["name"], "is_default": False}

    def _find_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        return next((p for p in self.presets if p["id"] == preset_id), None)

    def apply_preset(self, preset_id: str) -> bool:
        preset = self._find_preset(preset_id)
        if not preset:
            return False
        self._apply_current_state(preset["state"])
        self.save_state_to_disk()
        return True

    def set_default_preset(self, preset_id: str) -> bool:
        if not self._find_preset(preset_id):
            return False
        self.default_preset_id = preset_id
        self.save_state_to_disk()
        return True

    def apply_default_preset(self) -> bool:
        return bool(self.default_preset_id and self.apply_preset(self.default_preset_id))

    def delete_preset(self, preset_id: str) -> bool:
        preset = self._find_preset(preset_id)
        if not preset:
            return False
        self.presets.remove(preset)
        if self.default_preset_id == preset_id:
            self.default_preset_id = None
        self.save_state_to_disk()
        return True

    def set_display_mode(self, mode: str) -> None:
        self.power_display_mode = mode
        self.save_state_to_disk()

    def set_active_group(self, group: str) -> None:
        self.active_group = group.upper()
        self.save_state_to_disk()

    def _on_fec8_notify(self, sender, data: bytearray):
        self.last_ack = data.hex(" ")
        logger.info(f"Received FEC8 notify: {self.last_ack}")
        # Parse A1 ack from device (could be an actual state update or group confirmation)
        if len(data) >= 10 and data[0] == 0xF0 and data[1] == 0xA1:
            group_byte = data[3]
            group_letter = REVERSE_GROUP_MAP.get(group_byte)
            if group_letter and group_letter in self.groups:
                mode_byte = data[4]
                power_byte = data[5]
                mode = REVERSE_MODE_MAP.get(mode_byte, "M")
                dec_val = (100 - power_byte) if mode_byte != 0x00 else 50
                if group_letter in self.groups:
                    self.groups[group_letter]["mode"] = mode
                    self.groups[group_letter]["dec_val"] = max(10, min(100, dec_val))
                    self.groups[group_letter]["decimal_power"] = f"{self.groups[group_letter]['dec_val'] / 10.0:.1f}"
                    self.groups[group_letter]["power"] = dec_to_fraction(self.groups[group_letter]['dec_val'])
                    self.groups[group_letter]["lamp"] = (data[8] == 0x02)
                    self.groups[group_letter]["sound"] = (data[7] == 0x01)

    def _on_fff4_notify(self, sender, data: bytearray):
        self.last_test_fire_ack = bytes(data).decode("ascii", errors="replace").strip()
        logger.info("Received FFF4 notify: %s (%s)", self.last_test_fire_ack, data.hex(" "))
        self._test_fire_ack_event.set()

    def _on_disconnected(self, client):
        logger.warning("BLE device disconnected!")
        self.is_connected = False
        self.last_msg = "已断开连接"
        if self.auto_reconnect and not (self.reconnect_task and not self.reconnect_task.done()):
            self.reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        while self.auto_reconnect and not self.is_connected:
            self.last_msg = "正在尝试自动重连..."
            ok = await self.connect(self.device_address)
            if ok:
                self.last_msg = f"已重连: {self.device_name}"
                break
            await asyncio.sleep(4.0)

    async def scan_devices(self) -> List[Dict[str, Any]]:
        self.last_msg = "正在扫描附近的神牛引闪器..."
        devs = await BleakScanner.discover(timeout=4.0)
        results = []
        for d in devs:
            name = d.name or ""
            is_godox = name.startswith("GDBH-") or any(k in name.lower() for k in ["x3", "xpro", "x2t", "godox"])
            if is_godox or d.address == "628A1160-0E76-D5A7-CCB6-5DA73EC96391":
                results.append({
                    "name": name if name else "Godox Trigger",
                    "address": d.address,
                    "rssi": getattr(d, "rssi", None),
                    "is_current": (d.address == self.device_address and self.is_connected)
                })
        if self.is_connected and self.device_address:
            if not any(d["address"] == self.device_address for d in results):
                results.insert(0, {
                    "name": self.device_name,
                    "address": self.device_address,
                    "rssi": self.last_rssi,
                    "is_current": True
                })
        self.discovered_devices = results
        return results

    async def connect(self, target_address: Optional[str] = None) -> bool:
        async with self._lock:
            if self.client and self.client.is_connected:
                if not target_address or target_address == self.device_address:
                    return True
                await self.client.disconnect()

            addr = target_address or self.device_address
            if not addr:
                devs = await self.scan_devices()
                if not devs:
                    self.last_msg = "未扫描到神牛引闪器设备"
                    return False
                addr = devs[0]["address"]
                self.device_name = devs[0]["name"]

            self.device_address = addr
            self.last_msg = f"正在连接 {addr}..."
            try:
                self.client = BleakClient(
                    addr,
                    timeout=10.0,
                    disconnected_callback=self._on_disconnected
                )
                await self.client.connect()
                self.is_connected = self.client.is_connected
                if self.is_connected:
                    try:
                        await self.client.start_notify(CHAR_FEC8, self._on_fec8_notify)
                    except Exception:
                        pass
                    try:
                        await self.client.start_notify(CHAR_FFF4, self._on_fff4_notify)
                    except Exception:
                        pass
                    self.last_msg = f"已连接: {self.device_name}"
                    self.save_state_to_disk()
                    return True
            except Exception as e:
                logger.error(f"Connect error: {e}")
                self.is_connected = False
                self.last_msg = f"连接失败: {e}"
                return False
            return False

    async def disconnect(self):
        self.auto_reconnect = False
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.is_connected = False
        self.last_msg = "已手动断开"

    def add_group(self, group: str):
        g_up = group.upper()
        if g_up not in ALL_AVAILABLE_GROUPS:
            return False
        if g_up not in self.visible_groups:
            self.visible_groups.append(g_up)
        if g_up not in self.groups:
            self.groups[g_up] = {
                "mode": "M",
                "power": "1/64",
                "decimal_power": "4.0",
                "dec_val": 40,
                "sound": False,
                "lamp": False,
            }
        self.save_state_to_disk()
        return True

    def remove_group(self, group: str):
        g_up = group.upper()
        if g_up in self.visible_groups and len(self.visible_groups) > 1:
            self.visible_groups.remove(g_up)
            if self.active_group == g_up:
                self.active_group = "ALL"
            self.save_state_to_disk()
            return True
        return False

    async def set_group(self, group: str, mode: str, power: str = None, dec_val: int = None, sound: bool = False, lamp: bool = False) -> bool:
        if not self.is_connected or not self.client:
            return False

        g_up = group.upper()
        g_byte = GROUP_MAP.get(g_up, 0x0A)
        m_byte = MODE_MAP.get(mode.upper(), 0x01)

        resolved_dec_val = 40
        if dec_val is not None:
            resolved_dec_val = max(10, min(100, dec_val))
        elif power is not None:
            try:
                f_val = float(power)
                resolved_dec_val = int(round(f_val * 10))
                resolved_dec_val = max(10, min(100, resolved_dec_val))
            except ValueError:
                for item in POWER_TABLE:
                    if item["fraction"] == power or item["decimal"] == power:
                        resolved_dec_val = item["dec_val"]
                        break

        power_byte = (100 - resolved_dec_val) & 0xFF
        if m_byte == 0x00:
            power_byte = 0x32

        if lamp and not self.global_lamp:
            await self.send_tc_command(global_lamp=True)

        lamp_level = 100 if lamp else 0
        lamp_mode_byte = 0x02 if lamp else 0x00
        sound_byte = 0x01 if sound else 0x00

        payload = [
            0xF0,
            0xA1,
            0x07,
            g_byte,
            m_byte,
            power_byte,
            lamp_level,
            sound_byte,
            lamp_mode_byte,
            0x00,
        ]
        crc = calc_crc8(bytes(payload))
        payload.append(crc)
        frame = bytes(payload)

        try:
            await self.client.write_gatt_char(CHAR_FEC7, frame, response=True)
            fraction_str = dec_to_fraction(resolved_dec_val)
            decimal_str = f"{resolved_dec_val / 10.0:.1f}"
            self.groups[g_up] = {
                "mode": mode,
                "power": fraction_str,
                "decimal_power": decimal_str,
                "dec_val": resolved_dec_val,
                "sound": sound,
                "lamp": lamp,
            }
            self.save_state_to_disk()
            return True
        except Exception as e:
            logger.error(f"Set group error: {e}")
            return False

    async def send_tc_command(self, channel: Optional[int] = None, global_lamp: Optional[bool] = None, global_sound: Optional[bool] = None, all_adjust_step: int = 0) -> bool:
        if not self.is_connected or not self.client:
            return False

        ch = channel if channel is not None else self.channel
        lamp = global_lamp if global_lamp is not None else self.global_lamp
        sound = global_sound if global_sound is not None else self.global_sound

        payload = [
            0xF0,
            0xA0,
            0x0A,
            ch & 0xFF,
            0x01 if sound else 0x00,
            0x01 if lamp else 0x00,
            all_adjust_step & 0xFF,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
        crc = calc_crc8(bytes(payload))
        payload.append(crc)
        frame = bytes(payload)

        try:
            await self.client.write_gatt_char(CHAR_FEC7, frame, response=True)
            if channel is not None:
                self.channel = channel
            if global_lamp is not None:
                self.global_lamp = global_lamp
            if global_sound is not None:
                self.global_sound = global_sound
            self.save_state_to_disk()
            return True
        except Exception as e:
            logger.error(f"Send TC Command error: {e}")
            return False

    async def adjust_all_groups(self, delta_dec: int) -> bool:
        success = True
        for g in self.visible_groups:
            data = self.groups.get(g)
            if data and data["mode"] != "OFF":
                cur_val = data.get("dec_val", 50)
                new_val = max(10, min(100, cur_val + delta_dec))
                ok = await self.set_group(
                    group=g,
                    mode=data["mode"],
                    dec_val=new_val,
                    sound=data.get("sound", False),
                    lamp=data.get("lamp", False)
                )
                if not ok:
                    success = False
        return success

    async def all_off(self) -> bool:
        """一键全局 OFF：把所有可见组别设为 OFF（实体引闪器上所有组关闭闪光）"""
        if not self.is_connected or not self.client:
            return False
        success = True
        for g in list(self.visible_groups):
            data = self.groups.get(g, {})
            ok = await self.set_group(
                group=g,
                mode="OFF",
                dec_val=data.get("dec_val", 40),
                sound=data.get("sound", False),
                lamp=False,
            )
            if not ok:
                success = False
            await asyncio.sleep(0.08)
        return success

    async def sync_all_to_device(self) -> bool:
        """用户知情地一键接管：把桌面当前全部灯位配置整体写入实体引闪器"""
        if not self.is_connected or not self.client:
            return False
        ok1 = await self.send_tc_command(channel=self.channel, global_lamp=self.global_lamp, global_sound=self.global_sound)
        success = ok1
        for g in self.visible_groups:
            grp = self.groups.get(g)
            if grp:
                ok = await self.set_group(
                    group=g,
                    mode=grp.get("mode", "M"),
                    dec_val=grp.get("dec_val", 40),
                    sound=grp.get("sound", False),
                    lamp=grp.get("lamp", False),
                )
                if not ok:
                    success = False
                await asyncio.sleep(0.08)
        return success

    async def test_fire(self) -> Dict[str, Any]:
        if not self.is_connected or not self.client:
            self.last_msg = "试闪失败：引闪器未连接"
            return {"success": False, "detail": "引闪器未连接，请先点击“连接引闪器”"}
        async with self._test_fire_lock:
            base_ms = 1483228800000
            diff_ms = int(time.time() * 1000) - base_ms
            cmd = f"{diff_ms},Test".encode("ascii")
            self.last_test_fire_ack = None
            self._test_fire_ack_event.clear()
            try:
                await self.client.write_gatt_char(CHAR_FFF1, cmd, response=False)
            except Exception as e:
                logger.error("Test fire write error: %s", e)
                self.last_msg = f"试闪写入失败：{e}"
                return {"success": False, "detail": "试闪指令写入失败，请重新连接后重试"}
            try:
                await asyncio.wait_for(self._test_fire_ack_event.wait(), timeout=1.8)
            except asyncio.TimeoutError:
                self.last_msg = "试闪未收到引闪器确认"
                return {"success": False, "detail": "未收到引闪器确认，请检查蓝牙距离、连接状态和实体闪光灯"}
            self.last_msg = "引闪器已确认试闪指令"
            return {"success": True, "ack": self.last_test_fire_ack, "detail": "已收到引闪器确认；请观察实体闪光灯是否触发"}

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected,
            "device_name": self.device_name,
            "device_address": self.device_address,
            "rssi": self.last_rssi,
            "last_ack": self.last_ack,
            "last_test_fire_ack": self.last_test_fire_ack,
            "message": self.last_msg,
            "channel": self.channel,
            "wireless_id": self.wireless_id,
            "global_lamp": self.global_lamp,
            "global_sound": self.global_sound,
            "power_display_mode": self.power_display_mode,
            "active_group": self.active_group,
            "visible_groups": self.visible_groups,
            "all_available_groups": ALL_AVAILABLE_GROUPS,
            "groups": self.groups,
            "power_table": POWER_TABLE,
            "discovered_devices": self.discovered_devices,
            "presets": self.list_presets(),
            "default_preset_id": self.default_preset_id,
        }

manager = BleManager()
