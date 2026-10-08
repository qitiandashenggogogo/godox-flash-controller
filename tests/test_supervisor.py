"""Exercise the actual Swift lifecycle manager against real and broken backends."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = os.environ.get('GODOX_TEST_SUPERVISOR', '/tmp/godox-startup-review/supervisor-harness')


def event(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(35):
            raise AssertionError('No supervisor event')
    raw = process.stdout.readline()
    if not raw:
        raise AssertionError('Supervisor exited: ' + process.stderr.read().decode())
    return json.loads(raw)


class SupervisorTests(unittest.TestCase):
    def launch(self, state, script):
        packed = os.environ.get('GODOX_TEST_BACKEND') if script == ROOT / 'app_backend.py' else None
        command = [HARNESS, packed, str(ROOT)] if packed else [HARNESS, sys.executable, str(ROOT), '-u', str(script)]
        process = subprocess.Popen(command, cwd=ROOT,
                                   env=dict(os.environ, GODOX_CONTROLLER_STATE_DIR=state),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process):
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()

    def test_refresh_coalesces_and_restarts_after_exit(self):
        with tempfile.TemporaryDirectory() as state:
            child = self.launch(state, ROOT / 'app_backend.py')
            first = event(child)
            self.assertEqual(first['event'], 'ready', first)
            lock = Path(state) / 'backend.lock'
            first_pid = json.loads(lock.read_text())['pid']
            child.stdin.write(b'refresh' + bytes([10]))
            refreshed = event(child)
            self.assertEqual(refreshed['instance_id'], first['instance_id'])
            self.assertEqual(json.loads(lock.read_text())['pid'], first_pid)
            os.kill(first_pid, signal.SIGTERM)
            failure = event(child)
            self.assertEqual(failure['event'], 'failed', failure)
            child.stdin.write(b'refresh' + bytes([10]))
            restarted = event(child)
            self.assertEqual(restarted['event'], 'ready', restarted)
            self.assertNotEqual(restarted['instance_id'], first['instance_id'])
            child.stdin.write(b'quit' + bytes([10]))
            child.wait(timeout=8)
            self.assertEqual(child.returncode, 0)

    def test_bad_ready_stops_owned_backend_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as state:
            script = Path(state) / 'broken.py'
            script.write_text("import sys,time" + chr(10) + "print('startup-error-marker',file=sys.stderr,flush=True)" + chr(10) + "print('GODOX_READY {}',flush=True)" + chr(10) + "time.sleep(60)")
            child = self.launch(state, script)
            failed = event(child)
            self.assertEqual(failed['event'], 'failed')
            self.assertIn('控制台启动响应无效', failed['detail'])
            terminated = event(child)
            self.assertIn('startup-error-marker', terminated['detail'])

    def test_missing_executable_has_concrete_error(self):
        with tempfile.TemporaryDirectory() as state:
            child = subprocess.Popen([HARNESS, '/nonexistent/godox-python', str(ROOT)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(self.stop, child)
            failed = event(child)
            self.assertEqual(failed['event'], 'failed')
            self.assertIn('无法启动', failed['detail'])

    def test_host_app_path_is_the_app_itself_not_its_parent(self):
        # Bundle.main.bundleURL is already the .app, so stripping another path component
        # would hand the backend the containing folder and lose the bundle identity.
        with tempfile.TemporaryDirectory() as state:
            app = Path(state) / 'Godox Controller.app'
            (app / 'Contents/Resources/backend').mkdir(parents=True)
            child = subprocess.Popen([HARNESS, '/nonexistent/godox-python', str(ROOT)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(self.stop, child)
            self.assertEqual(event(child)['event'], 'failed')
            child.stdin.write(('hostapp ' + str(app) + chr(10)).encode())
            child.stdin.flush()
            resolved = event(child)
            self.assertEqual(resolved['event'], 'host_app_bundle_path')
            self.assertTrue(resolved['value'].endswith('.app'), resolved['value'])
            self.assertNotEqual(resolved['value'], str(Path(state).resolve()),
                                'resolved to the .app parent instead of the .app')
            self.assertEqual(os.path.realpath(resolved['value']), os.path.realpath(str(app)))
            # A development launch has no .app at all and must advertise nothing.
            child.stdin.write(('hostapp ' + str(Path(state) / '.venv' / 'bin' / 'python') + chr(10)).encode())
            child.stdin.flush()
            development = event(child)
            self.assertEqual(development['event'], 'host_app_bundle_path')
            self.assertIsNone(development['value'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
