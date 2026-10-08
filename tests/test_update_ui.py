"""Behaviour of the gentle update reminder, driven against the shipping Swift sources.

The Swift harness is compiled from ``UpdateState.swift``, ``UpdateBridgePolicy.swift`` and
``PendingReconnectStore.swift`` themselves, so these are assertions about the code that
ships, not about a description of it. It needs no window, no menu bar, no network and no
appcast: a background check that finds a version, a click, a deferral and a relaunch are all
pure state transitions, and the whole point of the split is that they can be checked as such.
"""
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = os.environ.get('GODOX_TEST_UPDATE_CORE', '/tmp/godox-update-core/update-core-harness')


def _event(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(20):
            raise AssertionError('No update-core event')
    raw = process.stdout.readline()
    if not raw:
        raise AssertionError('Update-core harness exited: ' + process.stderr.read().decode())
    payload = json.loads(raw)
    if payload.get('event') == 'error':
        raise AssertionError(payload['detail'])
    return payload


class UpdateCore:
    """One harness process, so a test can assert on the transitions between events."""

    def __init__(self, directory):
        self.process = subprocess.Popen([HARNESS, str(directory)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.process.stdout.close()
        self.process.stderr.close()

    def send(self, command):
        self.process.stdin.write((command + chr(10)).encode())
        self.process.stdin.flush()
        return _event(self.process)

    def state(self, *events):
        result = self.send('state ' + ' '.join(events) if events else 'state')
        return result['state']

    def bridge(self, main_frame, protocol, host, port, base_url):
        return self.send('bridge %d %s %s %d %s' % (
            1 if main_frame else 0,
            protocol or '-', host or '-', port if port is not None else -1,
            base_url or '-'))['accepted']

    def bridge_name(self, name):
        return self.send('bridgeName ' + name)['accepted']


class IndicatorLifecycleTests(unittest.TestCase):
    """Discovering a version, offering it, deferring it, and failing — none of which may
    ever end up claiming the update already happened."""

    def test_a_quiet_app_shows_nothing_at_all(self):
        with UpdateCore('/tmp') as core:
            fresh = core.state('started')
            self.assertFalse(fresh['showsIndicator'])
            self.assertIsNone(fresh['latestVersion'])
            # The menu keeps its original wording when there is nothing to update to.
            self.assertEqual(fresh['menuItemTitle'], '检查更新…')
            self.assertIsNone(fresh['consoleEntryTitle'])

    def test_a_background_discovery_produces_a_dot_named_after_the_found_version(self):
        with UpdateCore('/tmp') as core:
            found = core.state('started', 'updateFound')
            self.assertTrue(found['showsIndicator'])
            self.assertEqual(found['latestVersion'], '1.6.2')
            # VoiceOver and the tooltip both have to name the version, not just "有更新".
            self.assertEqual(found['accessibilityDescription'], '发现新版 v1.6.2')
            self.assertEqual(found['menuItemTitle'], '更新到 v1.6.2…')
            self.assertEqual(found['consoleEntryTitle'], '更新到 v1.6.2')
            self.assertEqual(found['consoleEntryAccessibleLabel'], '更新到 v1.6.2')

    def test_checking_with_nothing_new_leaves_the_quiet_app_quiet(self):
        with UpdateCore('/tmp') as core:
            fresh = core.state('started', 'noUpdateFound')
            self.assertFalse(fresh['showsIndicator'])
            self.assertEqual(fresh['availability'], 'upToDate')
            self.assertIn('已是最新版', fresh['accessibilityDescription'])

    def test_deferring_clears_the_dot_but_keeps_the_entry_working(self):
        with UpdateCore('/tmp') as core:
            deferred = core.state('started', 'updateFound', 'later')
            self.assertFalse(deferred['showsIndicator'], 'a deferred update is not a new discovery')
            self.assertEqual(deferred['availability'], 'later(version: "1.6.2")')
            # Still actionable: putting an update off must stay reversible.
            self.assertTrue(deferred['isUpdateActionable'])
            self.assertEqual(deferred['consoleEntryTitle'], '更新到 v1.6.2')
            # And explicitly not a claim that the update is done.
            self.assertNotIn('已是最新', deferred['accessibilityDescription'])

    def test_cancelling_a_window_settles_into_deferred_not_updated(self):
        with UpdateCore('/tmp') as core:
            cancelled = core.state('started', 'updateFound', 'cancel', 'sessionWillFinish')
            self.assertFalse(cancelled['showsIndicator'])
            self.assertNotEqual(cancelled['availability'], 'upToDate')
            self.assertNotIn('已是最新', cancelled['accessibilityDescription'])

    def test_skipping_stops_the_reminder_but_not_the_entry(self):
        with UpdateCore('/tmp') as core:
            skipped = core.state('started', 'updateFound', 'skip')
            self.assertFalse(skipped['showsIndicator'])
            self.assertTrue(skipped['isUpdateActionable'])

    def test_a_failed_check_never_reports_the_version_as_installed(self):
        with UpdateCore('/tmp') as core:
            failed = core.state('started', 'updateFound', 'aborted')
            self.assertFalse(failed['showsIndicator'])
            self.assertIsNone(failed['latestVersion'], 'a failed attempt must not keep a version claim')
            self.assertEqual(failed['availability'], 'failed')
            self.assertNotIn('已是最新', failed['accessibilityDescription'])
            self.assertIn('未成功', failed['accessibilityDescription'])

    def test_a_finished_session_after_a_failure_does_not_upgrade_to_up_to_date(self):
        # The dangerous shape: an error, then a session close, must not read as "all good".
        with UpdateCore('/tmp') as core:
            after = core.state('started', 'updateFound', 'aborted', 'sessionWillFinish')
            self.assertNotEqual(after['availability'], 'upToDate')
            self.assertNotIn('已是最新', after['accessibilityDescription'])

    def test_installing_is_visible_as_work_in_progress_not_as_done(self):
        with UpdateCore('/tmp') as core:
            installing = core.state('started', 'updateFound', 'install')
            self.assertFalse(installing['showsIndicator'], 'Sparkle shows its own progress UI')
            self.assertEqual(installing['availability'], 'installing(version: "1.6.2")')
            self.assertNotIn('已是最新', installing['accessibilityDescription'])

    def test_relaunching_drops_everything_learned_about_the_old_bundle(self):
        with UpdateCore('/tmp') as core:
            after = core.state('started', 'updateFound', 'relaunching')
            self.assertEqual(after['availability'], 'unchecked')
            self.assertFalse(after['showsIndicator'])
            self.assertIsNone(after['latestVersion'])

    def test_a_new_discovery_after_a_relaunch_is_a_real_change(self):
        # Proves the reducer reports change, not merely the resulting value: the harness
        # returns the per-event changed flags.
        with UpdateCore('/tmp') as core:
            result = core.send('state started updateFound')
            self.assertEqual(result['changed'], [False, True],
                             'starting is a no-op; a discovery is a real change')
            quiet = core.send('state noUpdateFound')
            self.assertEqual(quiet['changed'], [True])
            again = core.send('state noUpdateFound')
            self.assertEqual(again['changed'], [False], 'a repeated identical check repaints nothing')


class ConsoleBridgeTests(unittest.TestCase):
    """Only the console's own top-level document may reach the native update action."""

    CONSOLE = 'http://127.0.0.1:8765/'

    def test_the_console_may_ask_and_may_act(self):
        with UpdateCore('/tmp') as core:
            self.assertTrue(core.bridge(True, 'http', '127.0.0.1', 8765, self.CONSOLE))
            self.assertTrue(core.bridge_name('godoxUpdateAction'))
            self.assertTrue(core.bridge_name('godoxUpdateStateRequest'))

    def test_an_iframe_is_refused_even_from_the_console_origin(self):
        # A page that embeds content must not be able to borrow the shell's authority.
        with UpdateCore('/tmp') as core:
            self.assertFalse(core.bridge(False, 'http', '127.0.0.1', 8765, self.CONSOLE))

    def test_another_loopback_port_is_refused(self):
        # A stale backend from a previous launch, or anything else on loopback, is not us.
        with UpdateCore('/tmp') as core:
            self.assertFalse(core.bridge(True, 'http', '127.0.0.1', 9999, self.CONSOLE))

    def test_a_remote_origin_is_refused(self):
        with UpdateCore('/tmp') as core:
            self.assertFalse(core.bridge(True, 'https', 'evil.example', 443, self.CONSOLE))
            self.assertFalse(core.bridge(True, 'http', 'localhost', 8765, self.CONSOLE))
            self.assertFalse(core.bridge(True, 'https', '127.0.0.1', 8765, self.CONSOLE))

    def test_a_message_with_no_backend_behind_it_is_refused(self):
        with UpdateCore('/tmp') as core:
            self.assertFalse(core.bridge(True, 'http', '127.0.0.1', 8765, None))

    def test_unknown_message_names_fail_closed(self):
        with UpdateCore('/tmp') as core:
            self.assertFalse(core.bridge_name('godoxAnything'))
            self.assertFalse(core.bridge_name(''))


class ConsoleMarkupTests(unittest.TestCase):
    """The page and the shell must agree on the channel names, in both directions."""

    def setUp(self):
        self.page = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
        with UpdateCore('/tmp') as core:
            self.names = core.send('names')

    def test_the_page_sends_exactly_the_names_the_shell_accepts(self):
        self.assertIn('window.webkit.messageHandlers', self.page)
        self.assertIn("'" + self.names['stateRequest'] + "'", self.page)
        self.assertIn("'" + self.names['action'] + "'", self.page)

    def test_the_page_receives_state_through_the_function_the_shell_calls(self):
        self.assertIn('window.' + self.names['stateSink'] + ' = function', self.page)

    def test_asking_for_state_never_goes_through_the_action_channel(self):
        # The action channel is what starts an install. A page refresh must not be able to
        # reach it, or reloading the console would silently begin an update.
        def channel_of(needle):
            index = self.page.index(needle)
            before = self.page[:index]
            start = before.rindex("godoxNativeHandler('") + len("godoxNativeHandler('")
            return before[start:before.index("')", start)]

        self.assertEqual(channel_of("postMessage('state')"), self.names['stateRequest'])
        self.assertEqual(channel_of("postMessage('update')"), self.names['action'])
        self.assertNotEqual(channel_of("postMessage('state')"), self.names['action'])

    def test_the_entry_starts_hidden_so_a_plain_browser_shows_no_dead_control(self):
        self.assertRegex(self.page, r'<button[^>]*id="godoxUpdateEntry"[^>]*hidden')
        self.assertIn('.update-entry[hidden] { display: none; }', self.page)

    def test_the_entry_only_appears_when_the_shell_says_there_is_something(self):
        self.assertIn('if (!state.actionable || !state.title', self.page)

    def test_the_entry_is_announced_with_the_version_not_with_technical_words(self):
        self.assertIn('state.accessibleLabel', self.page)
        # Product copy only: no appcast, feed, signature or Sparkle wording in the console.
        markup = self.page[self.page.index('class="update-entry"'):self.page.index('</button>', self.page.index('class="update-entry"'))]
        for word in ('appcast', 'Sparkle', 'feed', '签名', '清单'):
            self.assertNotIn(word, markup)


class PostUpdateRestoreTests(unittest.TestCase):
    """Reconnecting after an update is allowed exactly once, only to the exact address that
    was connected, and never on an ordinary launch."""

    ADDRESS = '628A1160-0E76-D5A7-CCB6-5DA73EC96391'

    def harness(self, directory):
        return UpdateCore(directory)

    def test_an_ordinary_launch_with_no_note_never_connects(self):
        with tempfile.TemporaryDirectory() as state, self.harness(state) as core:
            self.assertFalse(core.send('hasPending')['value'])
            self.assertIsNone(core.send('restorePlan 1')['value'])
            self.assertFalse(core.send('hasPending')['value'])

    def test_a_recorded_update_restores_that_exact_address_once(self):
        with tempfile.TemporaryDirectory() as state, self.harness(state) as core:
            self.assertTrue(core.send('record ' + self.ADDRESS)['recorded'])
            self.assertTrue(core.send('hasPending')['value'])
            self.assertEqual(core.send('restorePlan 1')['value'], self.ADDRESS)
            # Consumed: a second launch must not reconnect by itself.
            self.assertFalse(core.send('hasPending')['value'])
            self.assertIsNone(core.send('restorePlan 1')['value'])

    def test_a_slow_backend_leaves_the_note_for_the_moment_it_is_ready(self):
        with tempfile.TemporaryDirectory() as state, self.harness(state) as core:
            core.send('record ' + self.ADDRESS)
            self.assertIsNone(core.send('restorePlan 0')['value'])
            self.assertTrue(core.send('hasPending')['value'], 'an early attempt must not burn the note')
            self.assertEqual(core.send('restorePlan 1')['value'], self.ADDRESS)

    def test_a_normal_quit_clears_a_stale_note(self):
        with tempfile.TemporaryDirectory() as state, self.harness(state) as core:
            core.send('record ' + self.ADDRESS)
            self.assertTrue(core.send('hasPending')['value'])
            self.assertFalse(core.send('clear')['value'])
            self.assertIsNone(core.send('restorePlan 1')['value'])

    def test_only_a_credible_device_address_is_ever_stored(self):
        with tempfile.TemporaryDirectory() as state, self.harness(state) as core:
            self.assertTrue(core.send('plausible ' + self.ADDRESS)['accepted'])
            self.assertTrue(core.send('plausible AA:BB:CC:DD:EE:FF')['accepted'])
            for bad in ('', '   ', 'not a device', '*', 'rm -rf /', '../../etc/passwd', 'a' * 65):
                self.assertFalse(core.send('plausible ' + bad.replace(' ', '_'))['accepted'], bad)
            self.assertFalse(core.send('record ' + 'nope'.replace(' ', '_'))['recorded'])
            self.assertFalse(core.send('hasPending')['value'])

    def test_the_note_lives_its_own_file_next_to_the_backend_lock(self):
        store = (ROOT / 'PendingReconnectStore.swift').read_text(encoding='utf-8')
        self.assertIn('"pending-reconnect-after-update.json"', store)
        self.assertIn('Application Support/Godox Controller', store)
        # It must not be part of anything the user configures, since consuming it deletes it.
        self.assertNotIn('appearance.json', store)

    def test_an_ordinary_quit_path_clears_the_note(self):
        source = (ROOT / 'GodoxController.swift').read_text(encoding='utf-8')
        terminate = source[source.index('func applicationShouldTerminate'):]
        terminate = terminate[:terminate.index('\n    }')]
        self.assertIn('reconnectStore.clear()', terminate)

    def test_the_restore_is_gated_on_the_one_shot_plan_not_on_a_boolean(self):
        source = (ROOT / 'GodoxController.swift').read_text(encoding='utf-8')
        self.assertIn('postUpdateRestore.addressToReconnect(', source)
        self.assertIn('backend.connect(address: address)', source)
        # No scanning, no device substitution, no test fire on this path.
        restore = source[source.index('private func restoreConnectedDeviceAfterUpdateIfNeeded'):]
        restore = restore[:restore.index(chr(10) + '    }')]
        for forbidden in ('scan', 'testFire', 'test_fire'):
            self.assertNotIn(forbidden, restore)



class RestoreAdmissionTests(unittest.TestCase):
    ADDRESS = PostUpdateRestoreTests.ADDRESS

    def test_same_build_and_wrong_target_are_consumed_without_connecting(self):
        for current in ('7', '9'):
            with tempfile.TemporaryDirectory() as state, UpdateCore(state) as core:
                core.send('record ' + self.ADDRESS)
                self.assertIsNone(core.send('restorePlan 1 ' + current)['value'])
                self.assertFalse(core.send('hasPending')['value'])

    def test_expired_future_and_unchanged_build_notes_are_refused(self):
        with tempfile.TemporaryDirectory() as state, UpdateCore(state) as core:
            for command in ('honourable 7 8 8 1000000 43201',
                            'honourable 7 8 8 1000000 -1',
                            'honourable 8 8 8 1000000 1',
                            'honourable 7 8 7 1000000 1'):
                self.assertFalse(core.send(command)['accepted'], command)
            self.assertTrue(core.send('honourable 7 8 8 1000000 10')['accepted'])

    def test_short_hex_strings_are_not_peripheral_addresses(self):
        with tempfile.TemporaryDirectory() as state, UpdateCore(state) as core:
            for address in ('a', 'abcd', 'AA:BB', '1-2-3'):
                self.assertFalse(core.send('plausible ' + address)['accepted'])


class NativeLifecycleTests(unittest.TestCase):
    def test_real_objc_callbacks_consent_and_relaunch_preparation(self):
        harness = os.environ.get('GODOX_TEST_UPDATE_LIFECYCLE', '/tmp/godox-update-core/update-lifecycle-harness')
        result = subprocess.run([harness], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CONSENT_ONE_SHOT CONNECTED_ONLY PREPARATION_CANCEL_TIMEOUT', result.stdout)

def strip_swift_comments(source):
    """Drops // and /// lines so code-level assertions are not satisfied or broken by prose."""
    return '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('//'))


class ProductionWiringTests(unittest.TestCase):
    """The reminder must stay a reminder: no auto-install, no forced preference writes, and
    no second scheduler or version comparison of our own."""

    def setUp(self):
        self.coordinator = (ROOT / 'UpdateCoordinator.swift').read_text(encoding='utf-8')
        self.code = strip_swift_comments(self.coordinator)
        self.delegate = (ROOT / 'GodoxController.swift').read_text(encoding='utf-8')
        self.plist = (ROOT / 'Info.plist').read_text(encoding='utf-8')

    def test_scheduled_reminders_are_ours_and_never_a_window(self):
        self.assertIn('var supportsGentleScheduledUpdateReminders: Bool { true }', self.code)
        body = strip_swift_comments(self.code[self.code.index('func standardUserDriverShouldHandleShowingScheduledUpdate'):])
        self.assertRegex(body[:400], r'andInImmediateFocus immediateFocus: Bool\) -> Bool \{\s*false')

    def test_the_user_check_preference_is_never_written(self):
        for writable in ('automaticallyChecksForUpdates', 'automaticallyDownloadsUpdates',
                         'SUEnableAutomaticChecks', 'SUAutomaticallyUpdate',
                         'defaults.write', 'UserDefaults'):
            self.assertNotIn(writable, self.code, writable)
            self.assertNotIn(writable, strip_swift_comments(self.delegate), writable)

    def test_nothing_schedules_its_own_update_polling(self):
        for forbidden in ('Timer.scheduledTimer', 'checkForUpdatesInBackground', 'DispatchSource.makeTimerSource'):
            self.assertNotIn(forbidden, self.code, forbidden)
            self.assertNotIn(forbidden, strip_swift_comments(self.delegate), forbidden)

    def test_there_is_no_second_version_comparison_or_downloader(self):
        for forbidden in ('compare(', 'SUStandardVersionComparator', 'URLSession', 'SecKey', 'ed25519'):
            self.assertNotIn(forbidden, self.code, forbidden)

    def test_the_shipped_plist_still_says_check_in_background_install_on_click(self):
        self.assertIn('<key>SUEnableAutomaticChecks</key>', self.plist)
        self.assertIn('<key>SUAutomaticallyUpdate</key>', self.plist)
        # Signature verification stays on; a gentle reminder must not weaken the chain.
        self.assertIn('<key>SUPublicEDKey</key>', self.plist)
        self.assertIn('<key>SURequireSignedFeed</key>', self.plist)
        self.assertIn('<key>SUVerifyUpdateBeforeExtraction</key>', self.plist)

    def test_the_menu_item_keeps_its_original_title_without_a_known_version(self):
        self.assertIn('state?.menuItemTitle ?? "检查更新…"', self.delegate)

    def test_the_updater_is_started_after_launch_not_before(self):
        launch = self.delegate[self.delegate.index('func applicationDidFinishLaunching'):]
        launch = launch[:launch.index('func applicationDidBecomeActive')]
        self.assertIn('installUpdateCoordinator()', launch)
        self.assertLess(launch.index('installUpdateCoordinator()'), launch.index('warmUpCoreBluetooth()'))

    def test_a_reload_republishes_the_state_to_the_fresh_document(self):
        self.assertIn('func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!)', self.delegate)
        self.assertIn('consoleBridge?.consoleDidFinishLoading()', self.delegate)
        self.assertIn('wv.navigationDelegate = self', self.delegate)

    def test_the_menu_bar_dot_is_drawn_not_appended_to_the_title(self):
        artwork = (ROOT / 'StatusItemArtwork.swift').read_text(encoding='utf-8')
        # A real filled circle, painted into the image and kept out of template tinting.
        self.assertIn('NSBezierPath(ovalIn:', artwork)
        self.assertIn('image.isTemplate = false', artwork)
        # The dot's slot is always reserved so discovering an update moves nothing.
        self.assertIn('dotGap + dotDiameter', artwork)
        # The glyph fallback may append a bullet, but only when AppKit cannot lay out at all.
        self.assertIn('state.showsIndicator ? label + " ●" : label', artwork)


if __name__ == '__main__':
    unittest.main(verbosity=2)
