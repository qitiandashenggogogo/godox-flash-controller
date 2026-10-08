"""Real subprocess checks; all state and diagnostics stay in temporary directories."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
BACKEND = os.environ.get('GODOX_TEST_BACKEND')
COMMAND = [BACKEND] if BACKEND else [sys.executable, '-u', str(ROOT / 'app_backend.py')]


def request(port, path, identity=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if identity is not None:
        headers['X-Godox-Instance'] = identity
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:' + str(port) + path, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


@contextlib.contextmanager
def running(state_dir, managed=True):
    env = dict(os.environ, GODOX_CONTROLLER_STATE_DIR=str(state_dir), GODOX_STARTUP_NONCE='test-nonce')
    with tempfile.TemporaryFile() as logs:
        process = subprocess.Popen(COMMAND + (['--managed'] if managed else []), cwd=ROOT,
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=logs)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(30):
                    logs.seek(0)
                    raise AssertionError('Backend did not send READY: ' + logs.read().decode())
            line = process.stdout.readline().decode()
            if not line.startswith('GODOX_READY '):
                logs.seek(0)
                raise AssertionError('Missing READY: ' + line + logs.read().decode())
            ready = json.loads(line.removeprefix('GODOX_READY '))
            assert ready['nonce'] == 'test-nonce'
            assert ready['protocol_version'] == 1
            # Mirror the shell's bounded read-only health check after READY.
            for attempt in range(5):
                try:
                    status, health = request(ready['port'], '/api/health')
                    break
                except (OSError, urllib.error.URLError):
                    if attempt == 4 or process.poll() is not None:
                        logs.seek(0)
                        raise AssertionError('Health check failed: ' + logs.read().decode())
                    time.sleep(0.2)
            assert status == 200 and json.loads(health)['instance_id'] == ready['instance_id']
            yield process, ready
        finally:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stdout.close()


class StartupTests(unittest.TestCase):
    def test_occupied_8765_and_instance_guard_and_persistent_theme(self):
        occupied = socket.socket()
        try:
            try:
                occupied.bind(('127.0.0.1', 8765))
                occupied.listen()
            except OSError:
                occupied.close()  # The user's existing service is left alone.
            with tempfile.TemporaryDirectory() as state:
                with running(state) as (child, first):
                    self.assertNotEqual(first['port'], 8765)
                    self.assertEqual(request(first['port'], '/api/theme', body={'theme': 'dark'})[0], 409)
                    self.assertEqual(request(first['port'], '/api/theme', 'old-instance', {'theme': 'dark'})[0], 409)
                    self.assertFalse((Path(state) / 'appearance.json').exists())
                    self.assertEqual(request(first['port'], '/api/theme', first['instance_id'], {'theme': 'dark'})[0], 200)
                    self.assertEqual(request(first['port'], '/api/theme', first['instance_id'], {'theme': 'bad'})[0], 400)
                    page = request(first['port'], '/')[1]
                    self.assertIn(first['instance_id'], page)
                    self.assertNotIn('__GODOX_INSTANCE_ID__', page)
                    self.assertIn("let themeChoice = 'dark'", page)
                    child.stdin.close()
                    child.wait(timeout=5)
                    self.assertEqual(child.returncode, 0)
                with running(state) as (_, second):
                    self.assertNotEqual(first['instance_id'], second['instance_id'])
                    self.assertEqual(request(second['port'], '/api/theme', first['instance_id'], {'theme': 'light'})[0], 409)
                    self.assertIn("let themeChoice = 'dark'", request(second['port'], '/')[1])
        finally:
            occupied.close()

    def test_duplicate_blocked_before_state_migration(self):
        with tempfile.TemporaryDirectory() as state:
            with running(state) as (_, first):
                before = {p.name: p.read_bytes() for p in Path(state).iterdir() if p.is_file()}
                env = dict(os.environ, GODOX_CONTROLLER_STATE_DIR=state)
                duplicate = subprocess.run(COMMAND, cwd=ROOT, env=env, input=b'', capture_output=True, timeout=20)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertNotIn(b'GODOX_READY', duplicate.stdout)
                self.assertIn('已有控制台运行', duplicate.stderr.decode())
                after = {p.name: p.read_bytes() for p in Path(state).iterdir() if p.is_file()}
                self.assertEqual(before, after)
                self.assertEqual(request(first['port'], '/api/health')[0], 200)
                if not BACKEND:
                    direct = subprocess.run([sys.executable, '-c', 'import app.main'], cwd=ROOT, env=env, capture_output=True, timeout=20)
                    self.assertNotEqual(direct.returncode, 0)
                    self.assertIn('已有控制台运行', direct.stderr.decode())

    def test_old_page_rejected_after_exact_port_reuse(self):
        with tempfile.TemporaryDirectory() as state:
            with running(state) as (_, old):
                pass
            env = dict(os.environ, GODOX_CONTROLLER_STATE_DIR=state)
            with tempfile.TemporaryFile() as logs:
                replacement = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(old['port'])], cwd=ROOT, env=env, stdout=logs, stderr=logs)
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            code, body = request(old['port'], '/api/health')
                            if code == 200:
                                break
                        except (OSError, urllib.error.URLError):
                            pass
                        if time.monotonic() > deadline:
                            self.fail('Replacement backend did not listen on old port')
                        time.sleep(0.05)
                    self.assertNotEqual(json.loads(body)['instance_id'], old['instance_id'])
                    self.assertEqual(request(old['port'], '/api/theme', old['instance_id'], {'theme': 'light'})[0], 409)
                    self.assertFalse((Path(state) / 'appearance.json').exists())
                finally:
                    replacement.terminate()
                    replacement.wait(timeout=5)

    def test_cli_ignores_stdin_eof(self):
        with tempfile.TemporaryDirectory() as state:
            with running(state, managed=False) as (child, ready):
                child.stdin.close()
                time.sleep(0.3)
                self.assertIsNone(child.poll())
                self.assertEqual(request(ready['port'], '/api/health')[0], 200)

    def test_parent_sigkill_closes_control_pipe(self):
        # Simulates abrupt loss of the UI; only the disposable parent is killed.
        with tempfile.TemporaryDirectory() as state:
            record = Path(state) / 'ready.json'
            parent_code = '''import subprocess,sys,json,time
p=subprocess.Popen(json.loads(sys.argv[1])+['--managed'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
line=p.stdout.readline().decode()
open(sys.argv[2],'w').write(line.removeprefix('GODOX_READY '))
time.sleep(60)
'''
            parent = subprocess.Popen([sys.executable, '-c', parent_code, json.dumps(COMMAND), str(record)], cwd=ROOT,
                                      env=dict(os.environ, GODOX_CONTROLLER_STATE_DIR=state))
            try:
                deadline = time.monotonic() + 30
                while not record.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(record.exists())
                ready = json.loads(record.read_text())
                parent.kill()
                parent.wait(timeout=3)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        request(ready['port'], '/api/health')
                    except (OSError, urllib.error.URLError):
                        break
                    time.sleep(0.05)
                else:
                    self.fail('Backend remained reachable after parent SIGKILL')
                with (Path(state) / 'backend.lock').open('a+') as probe:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            fcntl.flock(probe, fcntl.LOCK_UN)
                            break
                        except BlockingIOError:
                            if time.monotonic() > deadline:
                                self.fail('Backend did not release ownership after parent SIGKILL')
                            time.sleep(0.05)
                # A fresh process acquiring the same lock proves ownership was released.
                with running(state):
                    pass
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
