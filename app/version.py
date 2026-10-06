"""Reads the displayed version from the one publishing source: the app's Info.plist.

The shipped app already declares ``CFBundleShortVersionString`` in ``Info.plist``, which is
what the bundle presents to Finder and to Sparkle. There is deliberately no second version
string here and no hardcoded default: a version is either read from real bundle metadata or
reported as unknown. Guessing a number that looks plausible is worse than admitting we could
not read the metadata, because a wrong version in the UI is indistinguishable from a real one.

Three sources are tried in order, each verified as actually being this product:

1. ``GODOX_APP_BUNDLE_PATH`` — the .app the Swift shell advertises to the backend it spawns.
2. The nearest ``.app`` ancestor of the running backend executable — how a bundled backend
   running directly, with no shell, finds its host.
3. ``<package parent>/Info.plist`` — the source tree, and the PyInstaller onedir layout where
   ``build-app.sh`` copies the same plist next to ``app/``.

A plist only counts when its ``CFBundleIdentifier`` is ours, so a directory that merely ends
in ``.app``, or an unrelated bundle, can never supply a version. Anything unreadable, empty or
foreign is skipped, and exhausting all three sources yields ``UNKNOWN_VERSION``.
"""
import os
import plistlib
import sys
from pathlib import Path
from xml.parsers.expat import ExpatError

EXPECTED_BUNDLE_IDENTIFIER = "com.godoxcontroller.desktop"
UNKNOWN_VERSION = "未知版本"
_PLIST_NAME = "Info.plist"


def _read_bundle_version(plist_path):
    """The version ``plist_path`` declares, or None when it is absent, broken or not ours."""
    if not plist_path:
        return None
    try:
        with open(plist_path, "rb") as handle:
            metadata = plistlib.load(handle)
    except (OSError, ValueError, TypeError, ExpatError):
        # OSError covers missing/unreadable files; plistlib raises InvalidFileException
        # (a ValueError) and ExpatError for malformed XML. None of them are fatal here.
        return None
    if not isinstance(metadata, dict):
        return None
    if metadata.get("CFBundleIdentifier") != EXPECTED_BUNDLE_IDENTIFIER:
        return None
    version = metadata.get("CFBundleShortVersionString")
    if not isinstance(version, str):
        return None
    version = version.strip()
    return version or None


def _bundle_plist(bundle):
    """The Info.plist inside a .app bundle, or None when there is no bundle to look in."""
    if not bundle:
        return None
    return Path(bundle) / "Contents" / _PLIST_NAME


def declared_app_bundle(environ=None):
    """The .app path the Swift shell advertised, or None when absent or not a directory."""
    environ = os.environ if environ is None else environ
    value = (environ.get("GODOX_APP_BUNDLE_PATH") or "").strip()
    if not value or not os.path.isdir(value):
        return None
    return os.path.realpath(value)


def enclosing_app_bundle(executable=None):
    """The nearest .app ancestor of ``executable``, or None when it does not run inside one."""
    resolved = os.path.realpath(executable or sys.executable)
    current = os.path.dirname(resolved)
    while current and current != os.path.dirname(current):
        if current.endswith(".app"):
            return current
        current = os.path.dirname(current)
    return None


def source_plist():
    """Info.plist beside the package: the source tree, and PyInstaller's onedir root."""
    return Path(__file__).resolve().parents[1] / _PLIST_NAME


def read_app_version(environ=None, executable=None, plist=None):
    """The version to display, read from real bundle metadata or ``UNKNOWN_VERSION``.

    The arguments exist so callers in this project can be tested against real metadata
    instead of mocks; production reads them from the environment and the running process.
    """
    for candidate in (_bundle_plist(declared_app_bundle(environ)),
                      _bundle_plist(enclosing_app_bundle(executable)),
                      Path(plist) if plist is not None else source_plist()):
        version = _read_bundle_version(candidate)
        if version:
            return version
    return UNKNOWN_VERSION
