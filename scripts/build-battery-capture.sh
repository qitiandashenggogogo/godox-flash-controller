#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TASK_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/godox-battery-recorder-XXXXXX")"
TASK_APP="$TASK_STAGE/py-dist/Godox Battery Evidence.app"
TASK_OUTPUT="$PROJECT_DIR/dist/battery-recorder-$(date +%Y%m%d-%H%M%S)"
cd "$PROJECT_DIR"
printf 'BUILD_STAGE=%s\n' "$TASK_STAGE"
.venv/bin/python - "$TASK_STAGE/recorder.spec" "$PROJECT_DIR" <<'PY'
import sys
usage = '采集您指定引闪器的蓝牙广播、标准设备信息和通知，用于验证真实电量。'
info = {'CFBundleIdentifier': 'com.godoxcontroller.batteryevidence',
        'CFBundleName': 'Godox Battery Evidence', 'CFBundleDisplayName': '神牛电量取证',
        'CFBundleExecutable': 'GodoxBatteryEvidence', 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '0.1', 'CFBundleVersion': '1',
        'LSUIElement': True, 'NSBluetoothAlwaysUsageDescription': usage,
        'NSBluetoothPeripheralUsageDescription': usage}
from pathlib import Path
source = str(Path(sys.argv[2]) / 'scripts/capture_battery_evidence.py')
spec = f'''a = Analysis([{source!r}], pathex=[], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={{}}, runtime_hooks=[],
    excludes=['bleak.backends.winrt', 'bleak.backends.bluezdbus', 'bleak.backends.p4android'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GodoxBatteryEvidence',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, argv_emulation=False, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='GodoxBatteryEvidence')
app = BUNDLE(coll, name='Godox Battery Evidence.app',
    bundle_identifier='com.godoxcontroller.batteryevidence', info_plist={info!r})
'''
Path(sys.argv[1]).write_text(spec, encoding='utf-8')
PY
.venv/bin/python -m PyInstaller --clean --noconfirm \
  --distpath "$TASK_STAGE/py-dist" --workpath "$TASK_STAGE/py-build" \
  "$TASK_STAGE/recorder.spec" > "$TASK_STAGE/build.log" 2>&1
# Local research tool only; PyInstaller signs nested binaries ad hoc.
# This avoids accessing the production signing key or changing keychain policy.
codesign --verify --deep --strict "$TASK_APP"
mkdir -p "$TASK_OUTPUT"
ditto "$TASK_APP" "$TASK_OUTPUT/Godox Battery Evidence.app"
cp "$TASK_STAGE/build.log" "$TASK_OUTPUT/build.log"
printf '%s\n' "$TASK_APP" > "$TASK_OUTPUT/staged-app-path.txt"
printf 'STAGED_APP=%s\nLOCAL_APP=%s\n' "$TASK_APP" "$TASK_OUTPUT/Godox Battery Evidence.app"
