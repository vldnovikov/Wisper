## Install

**Requirements:** Mac with Apple Silicon (M1 or newer), macOS 13 or later. Nothing else — Python and all libraries are inside the app.

**Recommended — one command in Terminal** (installs or updates, no Gatekeeper warning):

```bash
curl -fsSL https://raw.githubusercontent.com/vldnovikov/whisper/main/install.sh | bash
```

**Or manually:**

1. Download **Wisper.zip** below, double-click to unzip, and drag **Wisper.app** into **Applications**.
2. Open Wisper. macOS will say **"Wisper" Not Opened** — expected, the app isn't notarized by Apple. Click **Done**, then go to **System Settings → Privacy & Security** and click **Open Anyway**.

**Then:**

- Wait until the menu-bar icon changes from ⏳ to 🎙 — the speech model (~3 GB) is downloaded once on first launch.
- Grant permissions in **System Settings → Privacy & Security**: **Microphone** (asked automatically), **Accessibility** and **Input Monitoring** (enable **Wisper**). After an update you may need to re-enable Wisper there.

## Use

Hold **Right Option**, speak, release — the text is typed where your cursor is. Press **Esc** while holding to cancel.

Settings are in the menu-bar icon: recognition engine (local Whisper or OpenAI cloud), Claude text cleanup, language, hotkey, personal dictionary.

Logs: `~/Library/Logs/Wisper.log`
