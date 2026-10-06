"""Bundle-identity diagnostics: honest reporting, no rebinding, stderr only.

Each test pins a behaviour that a wrong implementation would violate, so a future edit
that reintroduces the main-project "rebind mainBundle" patch fails here.
"""
import io
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import bundle_diagnostics  # noqa: E402

def fake_app(root, name):
    """A directory that ends in .app but carries no Info.plist, so it has no identifier."""
    app = Path(root) / name
    (app / 'Contents/Resources/backend').mkdir(parents=True)
    return app


class BundleDiagnosticsTests(unittest.TestCase):
    def test_development_run_reports_no_app_and_never_rebinds(self):
        report = bundle_diagnostics.collect_report()
        self.assertIsNone(report['declared_app_bundle'])
        self.assertIsNone(report['derived_app_bundle'])
        self.assertFalse(report['host_app_verified'])
        self.assertTrue(report['app_bundle_sources_agree'])
        # The honest value is the process's own bundle, never the shell's.
        self.assertFalse(report['main_bundle_rebound'])
        self.assertNotEqual(report['main_bundle_identifier'], bundle_diagnostics.EXPECTED_BUNDLE_IDENTIFIER)

    def test_directory_ending_in_app_is_not_verified(self):
        with tempfile.TemporaryDirectory() as root:
            app = fake_app(root, 'Impostor.app')
            backend = app / 'Contents/Resources/backend/GodoxControllerBackend'
            backend.write_text('#!/bin/sh\n')
            report = bundle_diagnostics.collect_report(executable=str(backend))
            self.assertEqual(report['derived_app_bundle'], os.path.realpath(str(app)))
            self.assertIsNone(report['derived_app_bundle_identifier'])
            self.assertFalse(report['host_app_verified'],
                             'a directory merely named *.app must not count as the host app')

    def test_verified_only_when_identifier_matches(self):
        before = bundle_diagnostics.process_main_bundle()
        with tempfile.TemporaryDirectory() as root:
            for name, identifier in [('Godox.app', bundle_diagnostics.EXPECTED_BUNDLE_IDENTIFIER),
                                     ('Other.app', 'com.example.other')]:
                app = fake_app(root, name)
                (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleIdentifier': identifier, 'CFBundlePackageType': 'APPL',
                    'CFBundleName': name,
                }))
                with patch.dict(os.environ, {'GODOX_APP_BUNDLE_PATH': str(app)}):
                    report = bundle_diagnostics.collect_report()
                self.assertEqual(report['declared_app_bundle_identifier'], identifier)
                self.assertEqual(report['host_app_verified'],
                                 identifier == bundle_diagnostics.EXPECTED_BUNDLE_IDENTIFIER)
                self.assertEqual(bundle_diagnostics.process_main_bundle(), before)
                self.assertFalse(report['main_bundle_rebound'])

    def test_enclosing_app_bundle_walks_up_from_the_backend_executable(self):
        with tempfile.TemporaryDirectory() as root:
            app = fake_app(root, 'Wrapped.app')
            backend = app / 'Contents/Resources/backend/GodoxControllerBackend'
            backend.write_text('#!/bin/sh\n')
            self.assertEqual(bundle_diagnostics.enclosing_app_bundle(str(backend)),
                             os.path.realpath(str(app)))
            self.assertIsNone(bundle_diagnostics.enclosing_app_bundle(str(Path(root) / 'a/b/c')))

    def test_disagreeing_bundle_sources_are_reported(self):
        with tempfile.TemporaryDirectory() as root:
            declared = fake_app(root, 'Declared.app')
            derived = fake_app(root, 'Derived.app')
            backend = derived / 'Contents/Resources/backend/GodoxControllerBackend'
            backend.write_text('#!/bin/sh\n')
            environ = {'GODOX_APP_BUNDLE_PATH': str(declared)}
            self.assertEqual(bundle_diagnostics.declared_app_bundle(environ), os.path.realpath(str(declared)))
            original = os.environ.get('GODOX_APP_BUNDLE_PATH')
            os.environ['GODOX_APP_BUNDLE_PATH'] = str(declared)
            try:
                report = bundle_diagnostics.collect_report(executable=str(backend))
            finally:
                if original is None:
                    os.environ.pop('GODOX_APP_BUNDLE_PATH', None)
                else:
                    os.environ['GODOX_APP_BUNDLE_PATH'] = original
            self.assertFalse(report['app_bundle_sources_agree'])
            self.assertFalse(report['host_app_verified'])

    def test_bogus_declared_path_is_ignored(self):
        self.assertIsNone(bundle_diagnostics.declared_app_bundle({'GODOX_APP_BUNDLE_PATH': '   '}))
        self.assertIsNone(bundle_diagnostics.declared_app_bundle({'GODOX_APP_BUNDLE_PATH': '/nonexistent/Godox.app'}))
        self.assertIsNone(bundle_diagnostics.declared_app_bundle({}))

    def test_reports_go_to_stderr_and_stdout_stays_reserved_for_ready(self):
        probe = ('import sys; sys.path.insert(0, %r)\n'
                 'from app.bundle_diagnostics import diagnose\n'
                 'diagnose()\n' % str(ROOT))
        finished = subprocess.run([sys.executable, '-c', probe], cwd=ROOT, capture_output=True, timeout=60,
                                  env=dict(os.environ, GODOX_CONTROLLER_STATE_DIR=tempfile.mkdtemp()))
        self.assertEqual(finished.returncode, 0, finished.stderr.decode())
        self.assertEqual(finished.stdout, b'', 'stdout must stay reserved for the READY protocol')
        self.assertIn(bundle_diagnostics.LOG_PREFIX.encode(), finished.stderr)
        line = finished.stderr.decode().strip().splitlines()[-1]
        self.assertEqual(json.loads(line[len(bundle_diagnostics.LOG_PREFIX):])['main_bundle_rebound'], False)

    def test_emit_targets_the_given_stream(self):
        buffer = io.StringIO()
        report = {'host_app_verified': True}
        self.assertIs(bundle_diagnostics.emit(report, buffer), report)
        self.assertIn(bundle_diagnostics.LOG_PREFIX, buffer.getvalue())

    def test_diagnose_never_raises_on_a_broken_stream(self):
        class Hostile:
            def write(self, _):
                raise OSError('stderr closed')

            def flush(self):
                raise OSError('stderr closed')

        self.assertIsInstance(bundle_diagnostics.diagnose(stream=Hostile()), dict)


if __name__ == '__main__':
    unittest.main(verbosity=2)
