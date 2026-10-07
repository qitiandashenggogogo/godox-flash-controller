#!/usr/bin/env python3
"""Targeted BLE evidence capture; no application command writes or reconnects."""
import argparse
import asyncio
from contextlib import contextmanager, nullcontext
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

BASE = "0000{}-0000-1000-8000-00805f9b34fb"
BAS = BASE.format("180f")
DIS = BASE.format("180a")
LEVEL = BASE.format("2a19")
NOTIFICATIONS = {LEVEL, BASE.format("fec8"), BASE.format("fff4")}
DIS_READS = {BASE.format(x) for x in ("2a24", "2a25", "2a26", "2a27", "2a28", "2a29", "2a23")}
CONTROL_READS = {(BASE.format("fec0"), BASE.format("fec7")),
                 (BASE.format("fff0"), BASE.format("fff1"))}
OPERATION_TIMEOUT = 5
CLEANUP_TIMEOUT = 3
SETUP_BUDGET = 60


def production_lock_path():
    return Path(os.environ.get("GODOX_CONTROLLER_STATE_DIR") or
                Path.home() / "Library/Application Support/Godox Controller") / "backend.lock"


def duration_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or not 1 <= seconds <= 120:
        raise argparse.ArgumentTypeError("录制时长应为 1–120 秒")
    return seconds


@contextmanager
def exclusive_backend(path=None):
    check_legacy = path is None and not os.environ.get("GODOX_CONTROLLER_STATE_DIR")
    path = path or production_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("正式后端仍在运行，请先正常退出 Godox Controller；工具不会抢占连接") from None
        if check_legacy:
            import urllib.request
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open("http://127.0.0.1:8765/api/health", timeout=.5) as response:
                    legacy = json.load(response)
            except (OSError, ValueError):
                legacy = None
            if isinstance(legacy, dict) and legacy.get("app") == "godox-controller":
                raise RuntimeError("旧版正式后端仍在运行，请先正常退出旧控制台")
        # Same inode/lock as runtime.py; preserve the existing identity bytes.
        yield
    finally:
        handle.close()


def production_busy():
    try:
        with exclusive_backend():
            return False
    except RuntimeError:
        return True


class Recording:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.file = os.fdopen(fd, "w", encoding="utf-8")
        self.generation = str(uuid.uuid4())
        self.closed = False

    def emit(self, kind, **data):
        if self.closed:
            return
        event = {"kind": kind, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "unix_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns(),
                 "generation": self.generation, **data}
        self.file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.file.flush()

    def close(self):
        self.closed = True
        self.file.close()


async def scan_target(address, seconds, emit, scanner_factory):
    seen = []
    def callback(device, adv):
        if device.address.casefold() != address.casefold():
            return
        seen.append(device)
        emit("advertisement", address=device.address, name=adv.local_name or device.name,
             rssi=adv.rssi, service_uuids=adv.service_uuids,
             manufacturer_data={str(k): bytes(v).hex() for k, v in adv.manufacturer_data.items()},
             service_data={k: bytes(v).hex() for k, v in adv.service_data.items()})
    async with scanner_factory(detection_callback=callback):
        await asyncio.sleep(seconds)
    emit("scan_complete", target_observations=len(seen),
         limitation="仅记录 macOS API 暴露的目标广播；未观察到不证明设备不广播")
    return seen[-1] if seen else None


async def capture_connection(device, seconds, emit, client_factory, read_control_values=False):
    ended = asyncio.Event()
    active = False
    expected_disconnect = False
    accepting = True
    attempted = []
    cleanup_success = True
    counts = {"notifications": 0, "reads": 0, "subscription_errors": 0}
    def disconnected(client):
        nonlocal active
        active = False
        ended.set()
        if accepting:
            emit("disconnected", expected=expected_disconnect)
    client = client_factory(device, timeout=12, disconnected_callback=disconnected)
    try:
        async with asyncio.timeout(seconds + SETUP_BUDGET):
            await asyncio.wait_for(client.connect(), timeout=12)
            active = True
            emit("connected", address=device.address)
            for service in client.services:
                emit("service", uuid=service.uuid, handle=service.handle)
                for char in service.characteristics:
                    properties = list(char.properties)
                    emit("characteristic", service_uuid=service.uuid, uuid=char.uuid,
                         handle=char.handle, properties=properties,
                         descriptors=[{"uuid": d.uuid, "handle": d.handle} for d in char.descriptors])
                    suuid, cuuid = service.uuid.lower(), char.uuid.lower()
                    is_battery = suuid == BAS and cuuid == LEVEL
                    is_control_read = read_control_values and (suuid, cuuid) in CONTROL_READS
                    if "read" in properties and (is_battery or (suuid == DIS and cuuid in DIS_READS) or is_control_read):
                        try:
                            raw = bytes(await asyncio.wait_for(client.read_gatt_char(char), OPERATION_TIMEOUT))
                            parsed = raw[0] if is_battery and len(raw) == 1 and raw[0] <= 100 else None
                            emit("read_response", uuid=char.uuid, handle=char.handle,
                                 raw_hex=raw.hex(), standard_battery_percent=parsed,
                                 read_source="control_characteristic" if is_control_read else "standard_characteristic")
                            counts["reads"] += 1
                        except Exception as error:
                            emit("read_error", uuid=char.uuid, error_type=type(error).__name__, message=str(error))
                    if cuuid not in NOTIFICATIONS or not {"notify", "indicate"}.intersection(properties):
                        continue
                    def on_notify(sender, data, selected=char):
                        if not accepting:
                            return
                        if not active:
                            emit("notification_after_inactive", uuid=selected.uuid, handle=selected.handle,
                                 raw_hex=bytes(data).hex(), discarded=True)
                            return
                        counts["notifications"] += 1
                        emit("notification", uuid=selected.uuid, handle=selected.handle, raw_hex=bytes(data).hex())
                    try:
                        attempted.append(char)
                        await asyncio.wait_for(client.start_notify(char, on_notify), OPERATION_TIMEOUT)
                        emit("subscribed", uuid=char.uuid, operation="CCCD 控制订阅，非应用查询命令")
                    except TimeoutError:
                        counts["subscription_errors"] += 1
                        emit("subscription_timeout", uuid=char.uuid, timeout_seconds=OPERATION_TIMEOUT)
                    except Exception as error:
                        counts["subscription_errors"] += 1
                        emit("subscription_error", uuid=char.uuid, error_type=type(error).__name__, message=str(error))
            emit("enumeration_complete")
            try:
                await asyncio.wait_for(ended.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass
    except TimeoutError:
        emit("capture_deadline", body_budget_seconds=seconds + SETUP_BUDGET)
        raise
    finally:
        active = False
        expected_disconnect = True
        for char in attempted:
            try:
                await asyncio.wait_for(client.stop_notify(char), CLEANUP_TIMEOUT)
                emit("unsubscribed", uuid=char.uuid)
            except TimeoutError:
                emit("unsubscribe_timeout", uuid=char.uuid, timeout_seconds=CLEANUP_TIMEOUT)
            except Exception as error:
                emit("unsubscribe_error", uuid=char.uuid, error_type=type(error).__name__, message=str(error))
        try:
            await asyncio.wait_for(client.disconnect(), OPERATION_TIMEOUT)
        except Exception as error:
            cleanup_success = False
            emit("disconnect_error", error_type=type(error).__name__, message=str(error))
        accepting = False
        emit("capture_summary", **counts, application_command_writes_by_construction=0,
             cleanup_success=cleanup_success,
             limitation="无通知或无标准电量只能说明本观察窗口未取得，不能判定私有协议不存在")
    if not cleanup_success:
        raise RuntimeError("连接清理未确认完成，请查看 disconnect_error 记录")
    return counts


async def run(args):
    from bleak import BleakClient, BleakScanner
    args.recording_created = False
    with nullcontext() if args.scan_only else exclusive_backend():
        busy = production_busy() if args.scan_only else False
        recorder = Recording(args.output)
        args.recording_created = True
        try:
            recorder.emit("session", address=args.address, model=args.model, firmware=args.firmware,
                          screen_battery=args.screen_battery, scan_only=args.scan_only,
                          read_control_values=getattr(args, "read_control_values", False),
                          production_backend_busy=busy, received_time_source="host_receive_time",
                          limitation="机身读数为人工标注；不等于已验证蓝牙电量；手机占用未自动验证")
            async with asyncio.timeout(args.scan_seconds + args.seconds + 90):
                device = await scan_target(args.address, args.scan_seconds, recorder.emit, BleakScanner)
                if args.scan_only:
                    return
                if device is None:
                    raise RuntimeError("本次扫描未找到指定设备；请确认引闪器开机、蓝牙开启及手机连接已释放")
                await capture_connection(device, args.seconds, recorder.emit, BleakClient,
                                         read_control_values=getattr(args, "read_control_values", False))
        except BaseException as error:
            recorder.emit("session_error", error_type=type(error).__name__, message=str(error))
            raise
        finally:
            recorder.emit("session_end")
            recorder.close()


def main():
    parser = argparse.ArgumentParser(description="定向录制引闪器蓝牙证据，不发送应用命令")
    parser.add_argument("--address", required=True, help="macOS 设备 UUID，精确指定目标")
    parser.add_argument("--output", required=True, type=Path, help="新建本机 JSONL，不覆盖已有文件")
    parser.add_argument("--scan-only", action="store_true", help="仅观察广播，不建立设备连接")
    parser.add_argument("--read-control-values", action="store_true",
                        help="另各读取一次可读FEC0/FEC7及FFF0/FFF1原值；不写命令，不解析为电量")
    parser.add_argument("--scan-seconds", type=duration_seconds, default=8)
    parser.add_argument("--seconds", type=duration_seconds, default=20)
    parser.add_argument("--model", default="unverified")
    parser.add_argument("--firmware", default="unverified")
    parser.add_argument("--screen-battery", default="unrecorded", help="同时间机身电量，人工标注")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        result = f"本次记录保留在 {args.output}" if getattr(args, "recording_created", False) else "本次未创建记录文件"
        reason = str(error) or ("录制超过总时限，请检查蓝牙授权提示或设备状态" if isinstance(error, TimeoutError)
                                else type(error).__name__)
        print(f"录制未完成：{reason}。{result}", file=sys.stderr)
        return 1
    print(f"录制结束：{args.output}；请按原始证据验证，结束不代表已取得电量。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
