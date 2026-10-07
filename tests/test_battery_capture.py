import asyncio
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as N
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("battery_capture", Path(__file__).resolve().parents[1] / "scripts/capture_battery_evidence.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_reads_are_opt_in_scoped_and_not_parsed_as_percent(self):
        def char(uuid, handle, properties):
            return N(uuid=capture.BASE.format(uuid), handle=handle, properties=properties, descriptors=[])
        services = [N(uuid=capture.BASE.format("fec0"), handle=0, characteristics=[
            char("fec7", 1, ["read", "write"]), char("fec8", 2, ["read"])]),
            N(uuid=capture.BASE.format("fff0"), handle=3, characteristics=[char("fff1", 4, ["read", "write"])]),
            N(uuid=capture.BAS, handle=5, characteristics=[char("fec7", 6, ["read"])]),
            N(uuid=capture.BASE.format("fec0"), handle=7, characteristics=[char("fec7", 8, ["write"])])]
        for enabled in (False, True):
            read_handles, events = [], []
            class Client:
                def __init__(self, *args, **kwargs):self.services = services
                async def connect(self):pass
                async def disconnect(self):pass
                async def read_gatt_char(self, selected):
                    read_handles.append(selected.handle)
                    return b"\x59"  # A coincidental 89 is not established telemetry.
                async def write_gatt_char(self, *args, **kwargs):raise AssertionError("application write prohibited")
            counts = await capture.capture_connection(N(address="target"), .001,
                lambda kind, **data: events.append({"kind":kind, **data}), Client, read_control_values=enabled)
            self.assertEqual(read_handles, [1, 4] if enabled else [])
            self.assertEqual(counts["reads"], 2 if enabled else 0)
            self.assertTrue(all(x["standard_battery_percent"] is None for x in events if x["kind"] == "read_response"))
            self.assertTrue(all(x["read_source"] == "control_characteristic" for x in events if x["kind"] == "read_response"))

    async def test_records_raw_without_application_writes_and_discards_late_notify(self):
        events = []
        characteristics = [N(uuid=capture.LEVEL, handle=1, properties=["read", "notify"], descriptors=[]),
                           N(uuid=capture.BASE.format("fec8"), handle=2, properties=["notify"], descriptors=[]),
                           N(uuid=capture.BASE.format("fec7"), handle=3, properties=["read", "write"], descriptors=[])]
        class Client:
            def __init__(self, *args, **kwargs):
                self.services = [N(uuid=capture.BAS, handle=0, characteristics=characteristics)]
                self.callbacks = {}
                self.on_disconnect = kwargs["disconnected_callback"]
            async def connect(self):pass
            async def disconnect(self):self.on_disconnect(self)
            async def read_gatt_char(self, char):
                if char.handle != 1:raise AssertionError("unexpected private read")
                return b"\x00"
            async def write_gatt_char(self, *args, **kwargs):raise AssertionError("application write prohibited")
            async def start_notify(self, char, cb):
                self.callbacks[char.handle] = cb
                cb(char, b"\xf0\xa1\x64")
            async def stop_notify(self, char):
                self.callbacks[char.handle](char, b"late")
        counts = await capture.capture_connection(N(address="exact-target"), .001,
                                                  lambda kind, **data: events.append({"kind": kind, **data}), Client)
        self.assertEqual(counts["notifications"], 2)
        reads = [x for x in events if x["kind"] == "read_response"]
        self.assertEqual(reads[0]["standard_battery_percent"], 0)
        late = [x for x in events if x.get("raw_hex") == b"late".hex()]
        self.assertEqual(len(late), 2)
        self.assertTrue(all(x["discarded"] for x in late))
        self.assertTrue(any(x["kind"] == "disconnected" and x["expected"] for x in events))

    async def test_subscription_failure_visible_and_other_notifications_continue(self):
        events = []
        chars = [N(uuid=capture.LEVEL, handle=1, properties=["notify"], descriptors=[]),
                 N(uuid=capture.BASE.format("fff4"), handle=2, properties=["notify"], descriptors=[])]
        class Client:
            def __init__(self, *args, **kwargs):self.services = [N(uuid=capture.BAS, handle=0, characteristics=chars)]
            async def connect(self):pass
            async def disconnect(self):pass
            async def start_notify(self, char, cb):
                if char.handle == 1:raise RuntimeError("unsupported notification")
                cb(char, b"ack")
            async def stop_notify(self, char):pass
        counts = await capture.capture_connection(N(address="target"), .001,
                                                  lambda kind, **data: events.append({"kind": kind, **data}), Client)
        self.assertEqual(counts["subscription_errors"], 1)
        self.assertEqual(counts["notifications"], 1)
        self.assertTrue(any(x["kind"] == "subscription_error" for x in events))

    def test_production_lock_is_held_and_identity_bytes_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp)/"lock"
            lock.write_text('{"pid":123}')
            with capture.exclusive_backend(lock):
                with self.assertRaises(RuntimeError):
                    with capture.exclusive_backend(lock):pass
                self.assertEqual(lock.read_text(), '{"pid":123}')
            with capture.exclusive_backend(lock):pass
            self.assertEqual(lock.read_text(), '{"pid":123}')

    def test_custom_state_directory_matches_runtime(self):
        with patch.dict("os.environ", {"GODOX_CONTROLLER_STATE_DIR": "/tmp/example-state"}):
            self.assertEqual(capture.production_lock_path(), Path("/tmp/example-state/backend.lock"))

    async def test_cancel_during_enumeration_cleans_all_attempted_subscriptions(self):
        events, stopped = [], []
        reached = asyncio.Event()
        class Client:
            def __init__(self, *args, **kwargs):
                self.services = [N(uuid=capture.BAS, handle=0, characteristics=[
                    N(uuid=capture.BASE.format("fec8"), handle=1, properties=["notify"], descriptors=[]),
                    N(uuid=capture.BASE.format("fff4"), handle=2, properties=["notify"], descriptors=[])])]
            async def connect(self):pass
            async def disconnect(self):events.append({"kind":"fake_disconnected"})
            async def start_notify(self, char, cb):
                if char.handle == 2:
                    reached.set()
                    await asyncio.Event().wait()
            async def stop_notify(self, char):stopped.append(char.handle)
        task = asyncio.create_task(capture.capture_connection(N(address="target"), 1,
                                  lambda kind, **data: events.append({"kind":kind, **data}), Client))
        await asyncio.wait_for(reached.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(stopped, [1, 2])
        self.assertTrue(any(x["kind"] == "fake_disconnected" for x in events))

    async def test_subscribe_and_unsubscribe_hangs_are_bounded(self):
        events = []
        class Client:
            def __init__(self, *args, **kwargs):
                self.services = [N(uuid=capture.BAS, handle=0, characteristics=[
                    N(uuid=capture.BASE.format("fec8"), handle=1, properties=["notify"], descriptors=[])])]
            async def connect(self):pass
            async def disconnect(self):pass
            async def start_notify(self, *args):await asyncio.Event().wait()
            async def stop_notify(self, *args):await asyncio.Event().wait()
        with patch.object(capture, "OPERATION_TIMEOUT", .005), patch.object(capture, "CLEANUP_TIMEOUT", .005):
            counts = await asyncio.wait_for(capture.capture_connection(N(address="target"), .001,
                           lambda kind, **data: events.append({"kind":kind, **data}), Client), .5)
        self.assertEqual(counts["subscription_errors"], 1)
        self.assertTrue(any(x["kind"] == "subscription_timeout" for x in events))
        self.assertTrue(any(x["kind"] == "unsubscribe_timeout" for x in events))

    async def test_total_deadline_records_and_disconnects(self):
        events = []
        class Client:
            def __init__(self, *args, **kwargs):
                self.services = [N(uuid=capture.BAS, handle=0, characteristics=[
                    N(uuid=capture.LEVEL, handle=1, properties=["read"], descriptors=[])])]
            async def connect(self):pass
            async def disconnect(self):events.append({"kind":"fake_disconnected"})
            async def read_gatt_char(self, *args):await asyncio.Event().wait()
        with patch.object(capture, "SETUP_BUDGET", .001):
            with self.assertRaises(TimeoutError):
                await capture.capture_connection(N(address="target"), .001,
                      lambda kind, **data: events.append({"kind":kind, **data}), Client)
        self.assertTrue(any(x["kind"] == "capture_deadline" for x in events))
        self.assertTrue(any(x["kind"] == "fake_disconnected" for x in events))

    async def test_unexpected_disconnect_invalidates_late_notifications(self):
        events = []
        class Client:
            def __init__(self, *args, **kwargs):
                self.on_disconnect = kwargs["disconnected_callback"]
                self.services = [N(uuid=capture.BAS, handle=0, characteristics=[
                    N(uuid=capture.BASE.format("fec8"), handle=1, properties=["notify"], descriptors=[])])]
            async def connect(self):pass
            async def disconnect(self):pass
            async def start_notify(self, char, cb):
                self.on_disconnect(self)
                cb(char, b"late")
            async def stop_notify(self, *args):pass
        counts = await capture.capture_connection(N(address="target"), 1,
                      lambda kind, **data: events.append({"kind":kind, **data}), Client)
        self.assertEqual(counts["notifications"], 0)
        self.assertTrue(any(x["kind"] == "disconnected" and not x["expected"] for x in events))
        self.assertTrue(any(x["kind"] == "notification_after_inactive" for x in events))

    def test_recording_does_not_overwrite_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"events.jsonl"
            recorder = capture.Recording(path)
            recorder.emit("notification", raw_hex="f0a1")
            recorder.close()
            event = json.loads(path.read_text())
            self.assertIn("generation", event)
            self.assertIn("monotonic_ns", event)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):capture.Recording(path)

    def test_timeout_cli_reports_reason_without_claiming_evidence_created(self):
        args = N(output=Path('/tmp/not-created.jsonl'))
        def timed_out(coroutine):
            coroutine.close()
            raise TimeoutError()
        stderr = io.StringIO()
        with patch('argparse.ArgumentParser.parse_args', return_value=args), \
             patch.object(capture.asyncio, 'run', side_effect=timed_out), redirect_stderr(stderr):
            self.assertEqual(capture.main(), 1)
        self.assertIn('超过总时限', stderr.getvalue())
        self.assertIn('本次未创建记录文件', stderr.getvalue())


if __name__ == "__main__":unittest.main()
