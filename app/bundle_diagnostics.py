"""Reports how the backend process sees its own code identity. Rebinds nothing.

The observed TCC logs attribute backend Bluetooth requests to the responsible shell
and check its code signature. Setting an associated object on the NSBundle class
does not alter what ``mainBundle`` returns; changing that lookup alone would not
prove Bluetooth authorization is repaired. This module only observes and reports,
and writes strictly to stderr because stdout carries the GODOX_READY protocol.
"""
import json
import os
import sys

EXPECTED_BUNDLE_IDENTIFIER = "com.godoxcontroller.desktop"
LOG_PREFIX = "[bundle-diag]"


def enclosing_app_bundle(executable):
    """The nearest ancestor directory of ``executable`` that is an .app, or None."""
    current = os.path.dirname(os.path.realpath(executable))
    while current and current != "/":
        if current.endswith(".app"):
            return current
        current = os.path.dirname(current)
    return None


def declared_app_bundle(environ=None):
    """The .app path the Swift shell advertised, or None when absent or not a directory."""
    environ = os.environ if environ is None else environ
    value = (environ.get("GODOX_APP_BUNDLE_PATH") or "").strip()
    if not value or not os.path.isdir(value):
        return None
    return os.path.realpath(value)


def bundle_identifier(path):
    """The bundle identifier Foundation reports for ``path``, or None when unreadable."""
    if not path:
        return None
    try:
        from Foundation import NSBundle
    except Exception:
        return None
    try:
        bundle = NSBundle.bundleWithPath_(path)
    except Exception:
        return None
    if bundle is None:
        return None
    return bundle.bundleIdentifier()


def process_main_bundle():
    """What this process actually sees as its main bundle, truthfully reported."""
    try:
        from Foundation import NSBundle
    except Exception:
        return None, None
    try:
        bundle = NSBundle.mainBundle()
    except Exception:
        return None, None
    if bundle is None:
        return None, None
    return bundle.bundlePath(), bundle.bundleIdentifier()


def collect_report(executable=None):
    """Describe bundle identity without changing it.

    ``host_app_verified`` is true only when a candidate .app really carries
    ``com.godoxcontroller.desktop``; a plain directory that merely ends in .app does not
    qualify. ``main_bundle_rebound`` is always false: nothing here attempts to change it.
    """
    resolved_executable = os.path.realpath(executable or sys.executable)
    derived = enclosing_app_bundle(resolved_executable)
    declared = declared_app_bundle()
    main_path, main_identifier = process_main_bundle()
    declared_identifier = bundle_identifier(declared)
    derived_identifier = bundle_identifier(derived)
    return {
        "executable": resolved_executable,
        "main_bundle_path": main_path,
        "main_bundle_identifier": main_identifier,
        "declared_app_bundle": declared,
        "declared_app_bundle_identifier": declared_identifier,
        "derived_app_bundle": derived,
        "derived_app_bundle_identifier": derived_identifier,
        "app_bundle_sources_agree": declared is None or derived is None or declared == derived,
        "host_app_verified": EXPECTED_BUNDLE_IDENTIFIER in (declared_identifier, derived_identifier),
        "main_bundle_rebound": False,
    }


def emit(report, stream=None):
    """Write the report to stderr only. stdout stays reserved for GODOX_READY."""
    stream = sys.stderr if stream is None else stream
    stream.write(LOG_PREFIX + " " + json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    stream.flush()
    return report


def diagnose(executable=None, stream=None):
    report = collect_report(executable)
    try:
        emit(report, stream)
    except Exception:
        # Diagnostics must never take the backend down.
        pass
    return report


if __name__ == "__main__":
    diagnose()
