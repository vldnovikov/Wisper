#!/bin/bash
# Builds a SELF-CONTAINED Wisper.app you can give to other people:
# Python runtime, all packages and the code live inside the bundle.
# Nothing from this folder or .venv is needed on the target Mac.
#
#   ./package_app.sh          -> dist/Wisper.app + dist/Wisper.zip
#
# Target Mac requirements: Apple Silicon (M1+), macOS 13+.
# The Whisper model (~3 GB) is downloaded on first launch.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
VERSION="${WISPER_VERSION:-0.1}"
VERSION="${VERSION#v}"   # tag "v0.2.0" -> "0.2.0"
DIST="$DIR/dist"
APP="$DIST/Wisper.app"
C="$APP/Contents"
RES="$C/Resources"

[ -x "$PY" ] || { echo "❌ $PY not found. Create the venv first (see README)."; exit 1; }
"$PY" -c "import rumps, mlx_whisper, pynput, sounddevice" 2>/dev/null \
  || { echo "❌ Missing packages: source .venv/bin/activate && uv pip install -r requirements.txt"; exit 1; }
command -v clang >/dev/null || { echo "❌ clang not found. Run: xcode-select --install"; exit 1; }

PYHOME="$("$PY" -c 'import sys; print(sys.base_prefix)')"
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
VENV_SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
[ -f "$PYHOME/lib/libpython$PYVER.dylib" ] || { echo "❌ Need a relocatable Python with libpython (uv's Python works)."; exit 1; }

echo "→ Cleaning dist/"
rm -rf "$APP" "$DIST/Wisper.zip"
mkdir -p "$C/MacOS" "$RES/app"

echo "→ Copying Python runtime ($PYHOME)"
rsync -a \
  --exclude "lib/python$PYVER/test" --exclude "lib/python$PYVER/idlelib" \
  --exclude "lib/python$PYVER/tkinter" --exclude "lib/python$PYVER/turtledemo" \
  --exclude "lib/python$PYVER/ensurepip" --exclude "lib/python$PYVER/site-packages" \
  --exclude "lib/tcl*" --exclude "lib/tk*" --exclude "lib/itcl*" --exclude "lib/thread*" \
  --exclude "lib/libtcl*" --exclude "lib/libtk*" --exclude "lib/python$PYVER/lib-dynload/_tkinter*" \
  --exclude "share" --exclude "__pycache__" \
  "$PYHOME/" "$RES/python/"

echo "→ Copying packages (without torch — only needed for model conversion)"
rsync -a \
  --exclude "torch" --exclude "torch-*" --exclude "functorch" --exclude "torchgen" \
  --exclude "pip" --exclude "pip-*" --exclude "uv" --exclude "uv-*" \
  --exclude "_virtualenv*" --exclude "__pycache__" \
  "$VENV_SITE/" "$RES/site-packages/"

echo "→ Copying app code"
cp "$DIR/dictate.py" "$DIR/menubar.py" "$DIR/cloud.py" "$RES/app/"

echo "→ Making the bundle self-contained (symlinks, permissions)"
# Some files in the Python runtime are read-only (codesign then can't sign them)
# and some symlinks point to absolute paths that exist only on the build
# machine (e.g. etc/openssl/cert.pem). Such a dangling link breaks the app's
# signature on every other Mac. Replace links that leave the bundle with real
# copies; drop links whose target doesn't exist.
chmod -R u+w "$APP"
"$PY" - "$APP" <<'PYFIX'
import os, shutil, sys
root = os.path.realpath(sys.argv[1])
fixed = dropped = 0
for dirpath, dirnames, filenames in os.walk(root):
    for name in dirnames + filenames:
        p = os.path.join(dirpath, name)
        if not os.path.islink(p):
            continue
        target = os.path.realpath(p)
        inside = target == root or target.startswith(root + os.sep)
        if inside and os.path.exists(target):
            continue
        os.unlink(p)
        if os.path.isdir(target):
            shutil.copytree(target, p, symlinks=False)
            fixed += 1
        elif os.path.isfile(target):
            shutil.copy2(target, p)
            fixed += 1
        else:
            dropped += 1
print(f"   symlinks: {fixed} replaced with copies, {dropped} dangling removed")
PYFIX

cat > "$C/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Wisper</string>
  <key>CFBundleDisplayName</key><string>Wisper</string>
  <key>CFBundleIdentifier</key><string>com.vnovikov.wisper</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Wisper</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Wisper records your voice while you hold the hotkey and transcribes it locally.</string>
</dict>
</plist>
PLIST

echo "→ Compiling launcher"
TMPC="$(mktemp -d)"
cat > "$TMPC/launcher.c" <<'CSRC'
#include <Python.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* All paths are resolved relative to the bundle, so the app can live anywhere. */
int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX], tmp[PATH_MAX];
    uint32_t sz = sizeof exe;
    if (_NSGetExecutablePath(exe, &sz) != 0 || !realpath(exe, real)) return 1;

    char macos[PATH_MAX], contents[PATH_MAX], app[PATH_MAX];
    strcpy(tmp, real);     strcpy(macos, dirname(tmp));      /* .../Contents/MacOS */
    strcpy(tmp, macos);    strcpy(contents, dirname(tmp));   /* .../Contents       */
    strcpy(tmp, contents); strcpy(app, dirname(tmp));        /* .../Wisper.app     */

    char pyhome[PATH_MAX], site[PATH_MAX], script[PATH_MAX], appdir[PATH_MAX], python[PATH_MAX];
    snprintf(pyhome, sizeof pyhome, "%s/Resources/python", contents);
    snprintf(site,   sizeof site,   "%s/Resources/site-packages", contents);
    snprintf(appdir, sizeof appdir, "%s/Resources/app", contents);
    snprintf(script, sizeof script, "%s/menubar.py", appdir);
    snprintf(python, sizeof python, "%s/bin/python3", pyhome);

    /* A child process of Wisper (multiprocessing, tqdm locks…) re-runs
       sys.executable: hand it to the real Python. Recognised by the
       WISPER_LAUNCHED marker we set below. Arguments macOS itself passes
       on launch (e.g. -psn_0_… after a Gatekeeper prompt) are ignored. */
    if (getenv("WISPER_LAUNCHED")) {
        argv[0] = python;
        execv(python, argv);
        perror("execv");
        return 127;
    }

    const char *home = getenv("HOME");
    if (home) {
        char log[PATH_MAX];
        snprintf(log, sizeof log, "%s/Library/Logs/Wisper.log", home);
        if (!freopen(log, "a", stdout)) {}
        if (!freopen(log, "a", stderr)) {}
        setvbuf(stdout, NULL, _IOLBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
    }
    setenv("PYTHONHOME", pyhome, 1);
    setenv("WISPER_SITE", site, 1);
    setenv("WISPER_APP", app, 1);
    setenv("WISPER_PYTHON", python, 1);
    setenv("WISPER_LAUNCHED", "1", 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);  /* never write into the signed bundle */
    unsetenv("PYTHONPATH");
    if (chdir(appdir) != 0) {}

    char *args[] = { argv[0], script, NULL };
    return Py_BytesMain(2, args);
}
CSRC

clang -O2 "$TMPC/launcher.c" -o "$C/MacOS/Wisper" \
  -I"$RES/python/include/python$PYVER" \
  -L"$RES/python/lib" -lpython"$PYVER" \
  -Wl,-rpath,@executable_path/../Resources/python/lib
LIB="$RES/python/lib/libpython$PYVER.dylib"
LIBNAME="$(otool -D "$LIB" | tail -n 1)"
if [[ "$LIBNAME" != @rpath/* ]]; then
  install_name_tool -id "@rpath/libpython$PYVER.dylib" "$LIB"
  install_name_tool -change "$LIBNAME" "@rpath/libpython$PYVER.dylib" "$C/MacOS/Wisper"
fi
rm -rf "$TMPC"

# Icon
(
  set +e
  TMP="$(mktemp -d)"
  "$PY" - "$TMP/icon.png" <<'PYICON' 2>/dev/null
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
PYICON
  if [ -f "$TMP/icon.png" ]; then
    ICONSET="$TMP/AppIcon.iconset"; mkdir -p "$ICONSET"
    for s in 16 32 128 256 512; do
      sips -z $s $s "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
      sips -z $((s*2)) $((s*2)) "$TMP/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
  fi
  rm -rf "$TMP"
)

echo "→ Self-test (bundled Python + packages load)"
if ! WISPER_SELFTEST=1 "$C/MacOS/Wisper"; then
  echo "❌ Self-test failed:"; tail -40 ~/Library/Logs/Wisper.log 2>/dev/null; exit 1
fi
find "$APP" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "→ Removing helper scripts not needed at runtime"
# pip/2to3/pydoc/idle wrappers are plain scripts. Signing them stores the
# signature in extended attributes, which zip/download/unzip can lose — and a
# lost signature breaks the whole bundle on the target Mac. Keep only the
# python binaries (needed when Wisper re-runs its interpreter).
find "$RES/python/bin" \( -type f -o -type l \) ! -name "python*" -delete
find "$RES/python/bin" -name "python*-config" -delete

echo "→ Signing (ad-hoc)"
xattr -cr "$APP"   # strip stray attributes (provenance, quarantine, Finder info)
# Sign every Mach-O file inside (libraries, extensions, the bundled python),
# deepest first, then the app itself. Never sign non-Mach-O files.
MACHO_COUNT=0
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q "Mach-O"; then
    codesign --force --sign - "$f"
    MACHO_COUNT=$((MACHO_COUNT + 1))
  fi
done < <(find "$RES" -type f \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) -print0)
echo "   signed $MACHO_COUNT inner binaries"
codesign --force --sign - --identifier com.vnovikov.wisper "$APP"
codesign --verify --deep --strict "$APP" && echo "   signature ok"

echo "→ Zipping"
# Apple's recommended way to zip an app bundle (keeps symlinks, permissions).
ditto -c -k --sequesterRsrc --keepParent "$APP" "$DIST/Wisper.zip"

echo "→ Verifying the zip (unpack + check signature, like the user's Mac will)"
CHECK="$(mktemp -d)"
ditto -x -k "$DIST/Wisper.zip" "$CHECK"
if ! codesign --verify --deep --strict -vv "$CHECK/Wisper.app"; then
  echo "❌ The app's signature breaks after zip/unzip:"
  codesign --verify --deep --strict -vvvv "$CHECK/Wisper.app" 2>&1 | tail -20
  exit 1
fi
if ! WISPER_SELFTEST=1 "$CHECK/Wisper.app/Contents/MacOS/Wisper"; then
  echo "❌ Unzipped app failed the self-test:"; tail -40 ~/Library/Logs/Wisper.log 2>/dev/null; exit 1
fi
BAD_LINKS="$(find "$CHECK/Wisper.app" -type l | while read -r l; do
  t="$(cd "$(dirname "$l")" && readlink "$l")"
  case "$t" in /*) echo "$l -> $t";; esac
  [ -e "$l" ] || echo "$l -> $t (dangling)"
done)"
if [ -n "$BAD_LINKS" ]; then
  echo "❌ Symlinks that won't exist on other Macs:"; echo "$BAD_LINKS" | head -20; exit 1
fi
rm -rf "$CHECK"
echo "   unzipped copy: signature ok, self-test ok, no external symlinks"

echo
echo "✅ $APP  ($(du -sh "$APP" | cut -f1))"
echo "✅ $DIST/Wisper.zip  ($(du -sh "$DIST/Wisper.zip" | cut -f1)) — send this file"
