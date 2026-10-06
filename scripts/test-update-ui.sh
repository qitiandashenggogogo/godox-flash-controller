#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
SPARKLE_ROOT="$(bash scripts/ensure-sparkle.sh)"
TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/godox-update-tests.XXXXXX")"
trap 'rm -rf "$TEST_DIR"' EXIT
swiftc -swift-version 5 UpdateState.swift UpdateBridgePolicy.swift PendingReconnectStore.swift \
    tests/UpdateCoreHarness.swift -o "$TEST_DIR/update-core"
swiftc -swift-version 5 UpdateState.swift UpdateCoordinator.swift PendingReconnectStore.swift BackendSupervisor.swift \
    tests/UpdateLifecycleHarness.swift -framework AppKit -F "$SPARKLE_ROOT" -framework Sparkle \
    -Xlinker -rpath -Xlinker "$SPARKLE_ROOT" -o "$TEST_DIR/update-lifecycle"
PYTHON="${PYTHON:-.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3
GODOX_TEST_UPDATE_CORE="$TEST_DIR/update-core" \
GODOX_TEST_UPDATE_LIFECYCLE="$TEST_DIR/update-lifecycle" \
    "$PYTHON" -m unittest discover -s tests -p test_update_ui.py
