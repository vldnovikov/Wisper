#!/bin/bash
# Builds Wisper.app — a thin launcher that runs menubar.py from this folder
# with this folder's .venv. Re-run after moving the project folder.
#
#   ./build_app.sh                 -> /Applications/Wisper.app
#   ./build_app.sh ~/Applications  -> ~/Applications/Wisper.app
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/Wisper.app"
PY="$DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "❌ $PY not found. Create the venv first (see README)."; exit 1
fi
if ! "$PY" -c "import rumps, mlx_whisper, pynput, sounddevice" 2>/dev/null; then
  echo "❌ Missing packages. Run:  source .venv/bin/activate && uv pip install -r requirements.txt"; exit 1
fi

# Stop a running instance so we can replace it.
pkill -f "$DIR/menubar.py" 2>/dev/null || true
pkill -x Wisper 2>/dev/null || true
sleep 0.5

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Wisper</string>
  <key>CFBundleDisplayName</key><string>Wisper</string>
  <key>CFBundleIdentifier</key><string>com.vnovikov.wisper</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Wisper</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Wisper records your voice while you hold the hotkey and transcribes it locally.</string>
</dict>
</plist>
PLIST

# --- Native launcher -------------------------------------------------------
# A tiny C program that embeds Python (libpython) in-process. The running
# process is then Wisper.app itself, so macOS shows "Wisper" (not "python") in
# privacy settings, the menu-bar icon belongs to Wisper, and Info.plist applies.
if ! command -v clang >/dev/null; then
  echo "❌ clang not found. Run: xcode-select --install"; exit 1
fi

PYHOME="$("$PY" -c 'import sys; print(sys.base_prefix)')"
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
LIB="$PYHOME/lib/libpython$PYVER.dylib"
INC="$PYHOME/include/python$PYVER"
[ -f "$LIB" ] || { echo "❌ $LIB not found (need a Python built with a shared libpython, e.g. uv's)."; exit 1; }
[ -f "$INC/Python.h" ] || { echo "❌ $INC/Python.h not found."; exit 1; }

TMPC="$(mktemp -d)"
cat > "$TMPC/launcher.c" <<'C'
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    /* Libraries (multiprocessing, tqdm locks…) re-run sys.executable with
       arguments. Hand those calls to the real Python instead of starting
       another Wisper. */
    if (argc > 1) {
        argv[0] = WISPER_PY;
        execv(WISPER_PY, argv);
        perror("execv");
        return 127;
    }
    const char *home = getenv("HOME");
    if (home) {
        char log[4096];
        snprintf(log, sizeof log, "%s/Library/Logs/Wisper.log", home);
        freopen(log, "a", stdout);
        freopen(log, "a", stderr);
        setvbuf(stdout, NULL, _IOLBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
    }
    setenv("PYTHONHOME", WISPER_PYHOME, 1);
    setenv("WISPER_SITE", WISPER_SITE_DIR, 1);
    setenv("WISPER_APP", WISPER_APP_PATH, 1);
    setenv("WISPER_PYTHON", WISPER_PY, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    unsetenv("PYTHONPATH");
    chdir(WISPER_PROJECT);
    char *args[] = { argv[0], WISPER_SCRIPT, NULL };
    return Py_BytesMain(2, args);
}
C

clang -O2 "$TMPC/launcher.c" -o "$APP/Contents/MacOS/Wisper" \
  -I"$INC" -L"$PYHOME/lib" -lpython"$PYVER" -Wl,-rpath,"$PYHOME/lib" \
  -DWISPER_PYHOME="\"$PYHOME\"" \
  -DWISPER_SITE_DIR="\"$SITE\"" \
  -DWISPER_APP_PATH="\"$APP\"" \
  -DWISPER_PROJECT="\"$DIR\"" \
  -DWISPER_SCRIPT="\"$DIR/menubar.py\"" \
  -DWISPER_PY="\"$PY\""

# Make sure the binary finds libpython regardless of its recorded install name.
LIBNAME="$(otool -D "$LIB" | tail -n 1)"
if [[ "$LIBNAME" != @rpath/* && "$LIBNAME" != "$LIB" ]]; then
  install_name_tool -change "$LIBNAME" "$LIB" "$APP/Contents/MacOS/Wisper"
fi
rm -rf "$TMPC"

# App icon (microphone SF-style emoji rendered to .icns). Optional — skipped on failure.
(
  set +e
  TMP="$(mktemp -d)"
  "$PY" - "$TMP/icon.png" <<'PY' 2>/dev/null
import sys
from AppKit import NSImage, NSBitmapImageRep, NSPNGFileType, NSColor, NSFont, NSString, NSMakeRect, NSFontAttributeName, NSBezierPath
from Foundation import NSMakeSize, NSMakePoint
size = 1024
img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
img.lockFocus()
NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.13, 0.18, 1).set()
NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(80, 80, 864, 864), 190, 190).fill()
s = NSString.stringWithString_("🎙")
attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(560)}
w, h = s.sizeWithAttributes_(attrs)
s.drawAtPoint_withAttributes_(NSMakePoint((size - w) / 2, (size - h) / 2), attrs)
img.unlockFocus()
rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(sys.argv[1], True)
PY
  if [ -f "$TMP/icon.png" ]; then
    ICONSET="$TMP/AppIcon.iconset"; mkdir -p "$ICONSET"
    for s in 16 32 128 256 512; do
      sips -z $s $s "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
      sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
  fi
  rm -rf "$TMP"
)

# Ad-hoc signature gives macOS a stable identity for privacy permissions.
codesign --force --deep --sign - --identifier com.vnovikov.wisper "$APP" >/dev/null 2>&1 || true

# Sanity check: Python starts inside the launcher binary.
if ! WISPER_SELFTEST=1 "$APP/Contents/MacOS/Wisper"; then
  echo "❌ Launcher self-test failed — see ~/Library/Logs/Wisper.log"; exit 1
fi

# A rebuilt app has a new signature, so old privacy grants no longer match it
# (the toggle looks ON but doesn't apply). Clear them so macOS asks again.
tccutil reset Accessibility com.vnovikov.wisper >/dev/null 2>&1 || true
tccutil reset ListenEvent com.vnovikov.wisper >/dev/null 2>&1 || true

echo "✅ Built $APP"
echo "   ⚠️  After every rebuild re-enable Wisper in Privacy & Security → Accessibility"
echo "      and Input Monitoring (old entries were reset), then relaunch Wisper."
echo "   Launch:  open \"$APP\""
echo "   Logs:    ~/Library/Logs/Wisper.log"
