"""Exercise shutdown with absent tasks and errors without touching real Bluetooth."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = '''
import asyncio, json, sys
from app.main import manager, lifespan

async def main():
    mode = sys.argv[1]
    events = []
    class Client:
        is_connected = True
    manager.client = Client()
    manager.auto_reconnect = True
    manager.battery_refresh_task = None
    manager.reconnect_task = None
    async def disconnect():
        events.append('disconnected')
        manager.client.is_connected = False
    manager.disconnect = disconnect
    async def background():
        try:
            await asyncio.Event().wait()
        finally:
            events.append('task-finished')
    if mode == 'one-task':
        manager.reconnect_task = asyncio.create_task(background())
        await asyncio.sleep(0)
    try:
        async with lifespan(None):
            if mode == 'exception':
                raise ValueError('application-error')
    except ValueError as exc:
        events.append(str(exc))
    print(json.dumps({'events': events, 'connected': manager.client.is_connected,
                      'auto_reconnect': manager.auto_reconnect,
                      'task_cancelled': manager.reconnect_task.cancelled()
                          if manager.reconnect_task is not None else None}))
asyncio.run(main())
'''


class LifespanTests(unittest.TestCase):
    def probe(self, mode):
        with tempfile.TemporaryDirectory() as state:
            result = subprocess.run([sys.executable, '-c', PROBE, mode], cwd=ROOT,
                                    env=dict(os.environ, GODOX_CONTROLLER_STATE_DIR=state),
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['connected'])
        self.assertFalse(report['auto_reconnect'])
        self.assertIn('disconnected', report['events'])
        return report

    def test_no_background_tasks_still_disconnects(self):
        report = self.probe('no-tasks')
        self.assertEqual(report['events'], ['disconnected'])

    def test_present_task_is_awaited_when_other_task_is_absent(self):
        report = self.probe('one-task')
        self.assertTrue(report['task_cancelled'])
        self.assertEqual(report['events'], ['task-finished', 'disconnected'])

    def test_cleanup_runs_when_application_context_raises(self):
        report = self.probe('exception')
        self.assertEqual(report['events'], ['disconnected', 'application-error'])
