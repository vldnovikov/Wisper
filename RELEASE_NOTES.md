## Install

**Requirements:** Mac with Apple Silicon (M1 or newer), macOS 13 or later. Nothing else — Python and all libraries are inside the app.

1. Download **Wisper.zip** below and double-click it to unzip.
2. Drag **Wisper.app** into your **Applications** folder.
3. Open Wisper. macOS will say **"Wisper" Not Opened** (or "can't be opened") — this is expected, the app isn't notarized by Apple. Click **Done**, then:
   - open **System Settings → Privacy & Security**, scroll down to *"Wisper" was blocked…* and click **Open Anyway**, or
   - run in Terminal: `xattr -dr com.apple.quarantine /Applications/Wisper.app` and open Wisper again.
4. Wait until the menu-bar icon changes from ⏳ to 🎙 — the speech model (~3 GB) is downloaded once on first launch.
5. Grant permissions in **System Settings → Privacy & Security**:
   - **Microphone** — asked automatically on first use
   - **Accessibility** and **Input Monitoring** — enable **Wisper**

## Use

Hold **Right Option**, speak, release — the text is typed where your cursor is. Press **Esc** while holding to cancel.

Settings are in the menu-bar icon: recognition engine (local Whisper or OpenAI cloud), Claude text cleanup, language, hotkey, personal dictionary.

Logs: `~/Library/Logs/Wisper.log`
