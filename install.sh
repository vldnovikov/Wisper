#!/bin/bash
# Install or update Wisper — local push-to-talk dictation for macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/vldnovikov/whisper/main/install.sh | bash
#
# Downloads the latest release, installs it into /Applications (or
# ~/Applications if /Applications isn't writable) and launches it.
# Run the same command again to update.
set -euo pipefail

REPO="vldnovikov/whisper"
URL="https://github.com/$REPO/releases/latest/download/Wisper.zip"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "Wisper only runs on macOS."
[ "$(uname -m)" = "arm64" ]  || fail "Wisper needs a Mac with Apple Silicon (M1 or newer)."
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$MACOS_MAJOR" -ge 13 ] || fail "Wisper needs macOS 13 or newer (you have $(sw_vers -productVersion))."

DEST="/Applications"
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
APP="$DEST/Wisper.app"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say "→ Downloading the latest Wisper…"
curl -fL --progress-bar "$URL" -o "$TMP/Wisper.zip" \
  || fail "Download failed. Check your internet connection or https://github.com/$REPO/releases"

say "→ Unpacking…"
ditto -x -k "$TMP/Wisper.zip" "$TMP"
[ -d "$TMP/Wisper.app" ] || fail "The download doesn't contain Wisper.app."

if pgrep -x Wisper >/dev/null; then
  say "→ Quitting the running Wisper…"
  pkill -x Wisper || true
  sleep 1
fi

if [ -d "$APP" ]; then
  say "→ Replacing the existing $APP"
  chmod -R u+w "$APP" 2>/dev/null || true
  rm -rf "$APP"
fi

say "→ Installing to $APP"
mv "$TMP/Wisper.app" "$APP"
# Downloaded with curl, so there is no quarantine flag — but clear it anyway
# in case the zip was copied in from a browser download.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

say "→ Launching Wisper"
open "$APP"

cat <<'EOF'

✅ Wisper is installed.

Next steps:
  1. Look for the icon in the menu bar: ⏳ while the speech model downloads
     (~3 GB, first launch only), then 🎙 when it's ready.
  2. Grant permissions in System Settings → Privacy & Security:
       • Microphone        — asked automatically on first use
       • Accessibility     — enable Wisper
       • Input Monitoring  — enable Wisper
     (After an update you may need to re-enable Wisper there.)
  3. Hold Right Option, speak, release — the text is typed where your cursor is.

To update later, run the same install command again.
EOF
