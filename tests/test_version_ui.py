"""End-to-end checks of the version label against the real backend.

The backend runs as a real subprocess on a dynamically allocated port with a temporary state
directory, so the user's running console and its backend.lock are never touched. Tests reuse
the startup harness from test_startup rather than re-implementing the READY protocol.
"""
import asyncio
import html as html_module
import json
import os
import plistlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_VERSION = plistlib.loads((ROOT / 'Info.plist').read_bytes())['CFBundleShortVersionString']

# Set before importing app.main so an in-process import cannot touch the real state dir.
_IMPORT_STATE = tempfile.TemporaryDirectory()
os.environ['GODOX_CONTROLLER_STATE_DIR'] = _IMPORT_STATE.name

from test_startup import request, running  # noqa: E402


def write_bundle(root, name, short_version):
    """A real .app bundle whose Info.plist declares ``short_version``."""
    contents = Path(root) / name / 'Contents'
    contents.mkdir(parents=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'com.godoxcontroller.desktop',
        'CFBundleName': name,
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': short_version,
    }))
    return Path(root) / name


class LiveBackendVersionTests(unittest.TestCase):
    def health_version(self, port):
        status, body = request(port, '/api/health')
        self.assertEqual(status, 200)
        return json.loads(body)['version']

    def test_health_and_rendered_page_agree_and_leave_no_placeholder(self):
        with tempfile.TemporaryDirectory() as state:
            with running(state) as (_, ready):
                port = ready['port']
                reported = self.health_version(port)
                # Source-tree run has no shell-declared bundle, so the repo plist is the truth.
                self.assertEqual(reported, REPO_VERSION)

                page = request(port, '/')[1]
                self.assertIn('<span class="version-tag">v' + reported + '</span>', page)
                self.assertNotIn('__GODOX_APP_VERSION__', page)
                # Pre-existing substitutions must still work.
                self.assertNotIn('__GODOX_INSTANCE_ID__', page)
                self.assertNotIn('__GODOX_THEME__', page)
                self.assertIn(ready['instance_id'], page)

    def test_a_different_real_bundle_version_reaches_both_health_and_page(self):
        # The strongest end-to-end proof: a genuinely different declared version travels the
        # Swift environment variable -> backend -> health + markup path unchanged.
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as bundle_root:
            app = write_bundle(bundle_root, 'Godox Controller.app', '2.5.9')
            env_backup = os.environ.get('GODOX_APP_BUNDLE_PATH')
            os.environ['GODOX_APP_BUNDLE_PATH'] = str(app)
            try:
                with running(state) as (_, ready):
                    reported = self.health_version(ready['port'])
                    self.assertEqual(reported, '2.5.9')
                    self.assertNotEqual(reported, REPO_VERSION)
                    page = request(ready['port'], '/')[1]
                    self.assertIn('<span class="version-tag">v2.5.9</span>', page)
                    self.assertNotIn('v' + REPO_VERSION + '</span>', page)
                    self.assertNotIn('__GODOX_APP_VERSION__', page)
            finally:
                if env_backup is None:
                    os.environ.pop('GODOX_APP_BUNDLE_PATH', None)
                else:
                    os.environ['GODOX_APP_BUNDLE_PATH'] = env_backup


class VersionTagMarkupTests(unittest.TestCase):
    def setUp(self):
        self.page = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')

    def rule(self):
        match = re.search(r'\n    \.version-tag \{(.*?)\n    \}', self.page, re.S)
        self.assertIsNotNone(match, '.version-tag rule missing')
        return match.group(1)

    def test_label_sits_in_the_title_row_next_to_the_heading(self):
        heading = re.search(r'<h1>(.*?)</h1>', self.page, re.S)
        self.assertIsNotNone(heading)
        body = heading.group(1)
        self.assertIn('引闪控制台', body)
        self.assertIn('<span class="version-tag">v__GODOX_APP_VERSION__</span>', body)
        self.assertLess(body.index('引闪控制台'), body.index('class="version-tag"'),
                        'version tag belongs after the title, not before it')

    def test_label_styling_matches_the_intended_passive_tag(self):
        rule = self.rule()
        self.assertIn('font-size: 12px', rule)
        self.assertIn('font-weight: 500', rule)
        self.assertIn('flex-shrink: 0', rule)
        self.assertRegex(rule, r'padding: \d+px \d+px')
        self.assertRegex(rule, r'border: 1px solid var\(--border-subtle\)')

    def test_label_only_uses_existing_theme_variables(self):
        defined = set(re.findall(r'^\s*(--[\w-]+):', self.page, re.M))
        used = set(re.findall(r'var\((--[\w-]+)\)', self.rule()))
        self.assertTrue(used, 'version tag must not hardcode colors')
        self.assertEqual(used - defined, set(), 'version tag invented a variable')

    def test_narrow_window_can_wrap_the_title_row(self):
        # flex-shrink:0 only behaves because the row is allowed to wrap on narrow windows.
        self.assertRegex(self.page, r'\.title-area h1 \{ flex-wrap: wrap; \}')

    def test_no_extra_requests_or_script_dependencies_added(self):
        before = self.page.count('__GODOX_APP_VERSION__')
        self.assertEqual(before, 1, 'exactly one placeholder, substituted server-side')
        self.assertNotIn('fetchVersion', self.page)


class RenderedEscapeTests(unittest.TestCase):
    def test_version_is_html_escaped_before_interpolation(self):
        from app import main as main_module
        hostile = '<b>9.9</b>&"x"'
        with patch.object(main_module, 'read_app_version', return_value=hostile):
            response = asyncio.run(main_module.serve_index())
        body = response.body.decode('utf-8')
        self.assertIn(html_module.escape(hostile), body)
        self.assertNotIn('<b>9.9</b>', body)
        self.assertNotIn('__GODOX_APP_VERSION__', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)