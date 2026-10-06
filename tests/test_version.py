"""Version display reads real Info.plist metadata, and never invents a number.

Every case below pins behaviour a naive implementation would get wrong: hardcoding "1.6",
trusting any file named Info.plist, or reporting a plausible number when the metadata is
unreadable. The expected versions for simulated bundles are deliberately different from the
repository's real one, so a test cannot pass by echoing a constant.
"""
import os
import plistlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import version  # noqa: E402

REPO_PLIST = ROOT / 'Info.plist'
REPO_VERSION = plistlib.loads(REPO_PLIST.read_bytes())['CFBundleShortVersionString']


def write_bundle(root, name, short_version=None, identifier=version.EXPECTED_BUNDLE_IDENTIFIER, raw=None):
    """A minimal but real .app carrying one Info.plist."""
    contents = Path(root) / name / 'Contents'
    contents.mkdir(parents=True)
    plist = contents / 'Info.plist'
    if raw is not None:
        plist.write_bytes(raw)
    else:
        plist.write_bytes(plistlib.dumps({
            'CFBundleIdentifier': identifier,
            'CFBundleName': name,
            'CFBundlePackageType': 'APPL',
            'CFBundleShortVersionString': short_version,
        }))
    return Path(root) / name


class SourceVersionTests(unittest.TestCase):
    def test_reads_the_repository_plist(self):
        self.assertEqual(version.read_app_version(environ={}, executable='/nonexistent/backend'),
                         REPO_VERSION)

    def test_repository_plist_is_the_expected_one(self):
        # Guards the fallback path itself: if the shipped plist stops parsing, tests above
        # would silently degrade into asserting UNKNOWN_VERSION.
        self.assertTrue(REPO_VERSION)
        self.assertEqual(version.source_plist(), REPO_PLIST)

    def test_repository_identifier_matches_the_one_we_accept(self):
        self.assertEqual(plistlib.loads(REPO_PLIST.read_bytes())['CFBundleIdentifier'],
                         version.EXPECTED_BUNDLE_IDENTIFIER)

    def test_plist_beside_the_package_is_readable(self):
        self.assertEqual(version._read_bundle_version(REPO_PLIST), REPO_VERSION)


class DeclaredBundleTests(unittest.TestCase):
    def test_shell_declared_bundle_wins(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Godox Controller.app', '2.4.7')
            env = {'GODOX_APP_BUNDLE_PATH': str(app)}
            self.assertEqual(version.read_app_version(environ=env, executable='/nonexistent/backend'),
                             '2.4.7')

    def test_declared_bundle_is_winner_even_with_trailing_slash_and_space(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Godox Controller.app', '3.1.0')
            env = {'GODOX_APP_BUNDLE_PATH': '  ' + str(app) + '/  '}
            self.assertEqual(version.read_app_version(environ=env), '3.1.0')

    def test_missing_declared_path_falls_back_to_source(self):
        env = {'GODOX_APP_BUNDLE_PATH': '/nonexistent/Godox Controller.app'}
        self.assertEqual(version.read_app_version(environ=env, executable='/nonexistent/backend'),
                         REPO_VERSION)

    def test_blank_declared_value_falls_back_to_source(self):
        self.assertEqual(version.read_app_version(environ={'GODOX_APP_BUNDLE_PATH': '   '},
                                                  executable='/nonexistent/backend'),
                         REPO_VERSION)


class ExecutableAncestorTests(unittest.TestCase):
    def test_host_app_found_from_the_backend_executable(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Godox Controller.app', '1.9.2')
            backend = app / 'Contents/Resources/backend/GodoxControllerBackend'
            backend.parent.mkdir(parents=True)
            backend.write_text('#!/bin/sh\n')
            self.assertEqual(version.read_app_version(environ={}, executable=str(backend)), '1.9.2')

    def test_nearest_app_ancestor_is_used(self):
        with tempfile.TemporaryDirectory() as root:
            write_bundle(root, 'Outer.app', '5.0.0')
            inner = write_bundle(root, 'Outer.app/Contents/Frameworks/Inner.app', '5.1.0')
            backend = inner / 'Contents/Resources/backend'
            backend.mkdir(parents=True)
            self.assertEqual(version.read_app_version(environ={}, executable=str(backend)), '5.1.0')

    def test_declared_bundle_outranks_executable_ancestor(self):
        with tempfile.TemporaryDirectory() as root:
            write_bundle(root, 'Godox Controller.app', '1.9.2')
            executable = Path(root) / 'Godox Controller.app/Contents/Resources/backend/GodoxControllerBackend'
            executable.parent.mkdir(parents=True)
            executable.write_text('#!/bin/sh\n')
            declared = write_bundle(root, 'Copy/Godox Controller.app', '4.2.0')
            self.assertEqual(version.read_app_version(
                environ={'GODOX_APP_BUNDLE_PATH': str(declared)}, executable=str(executable)), '4.2.0')

    def test_executable_outside_any_bundle_is_not_a_source(self):
        with tempfile.TemporaryDirectory() as root:
            backend = Path(root) / 'backend/GodoxControllerBackend'
            backend.parent.mkdir(parents=True)
            self.assertIsNone(version.enclosing_app_bundle(str(backend)))
            self.assertEqual(version.read_app_version(environ={}, executable=str(backend)),
                             REPO_VERSION)


class RejectionTests(unittest.TestCase):
    def test_foreign_bundle_identifier_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            write_bundle(root, 'Impostor.app', '9.9.9', identifier='com.example.other')
            self.assertEqual(version.read_app_version(environ={}, executable='/nonexistent/backend'),
                             REPO_VERSION)

    def test_foreign_declared_bundle_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Impostor.app', '9.9.9', identifier='com.example.other')
            self.assertEqual(version.read_app_version(
                environ={'GODOX_APP_BUNDLE_PATH': str(app)}, executable='/nonexistent/backend'),
                REPO_VERSION)

    def test_corrupt_declared_plist_falls_back_to_source(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Godox Controller.app', raw=b'<?xml version="1.0"?><plist><dict')
            self.assertEqual(version.read_app_version(environ={'GODOX_APP_BUNDLE_PATH': str(app)}, executable='/nonexistent/backend'),
                             REPO_VERSION)

    def test_bundle_without_version_key_falls_back_to_source(self):
        with tempfile.TemporaryDirectory() as root:
            contents = Path(root) / 'Godox Controller.app/Contents'
            contents.mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps(
                {'CFBundleIdentifier': version.EXPECTED_BUNDLE_IDENTIFIER, 'CFBundleVersion': '6'}))
            self.assertEqual(version.read_app_version(environ={'GODOX_APP_BUNDLE_PATH': str(contents.parent)}, executable='/nonexistent/backend'),
                             REPO_VERSION)

    def test_blank_version_value_falls_back_to_source(self):
        with tempfile.TemporaryDirectory() as root:
            app = write_bundle(root, 'Godox Controller.app', '   ')
            self.assertEqual(version.read_app_version(environ={'GODOX_APP_BUNDLE_PATH': str(app)}, executable='/nonexistent/backend'),
                             REPO_VERSION)


class UnknownVersionTests(unittest.TestCase):
    def test_unreadable_everywhere_reports_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / 'Info.plist'
            self.assertEqual(version.read_app_version(environ={}, executable='/nonexistent/backend',
                                                      plist=missing),
                             version.UNKNOWN_VERSION)

    def test_corrupt_source_plist_reports_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            broken = Path(root) / 'Info.plist'
            broken.write_bytes(b'not a plist at all')
            self.assertEqual(version.read_app_version(environ={}, executable='/nonexistent/backend',
                                                      plist=broken),
                             version.UNKNOWN_VERSION)

    def test_unknown_is_not_a_version_number(self):
        self.assertFalse(version.UNKNOWN_VERSION.strip()[:1].isdigit())
        self.assertTrue(version.UNKNOWN_VERSION)


if __name__ == '__main__':
    unittest.main(verbosity=2)
