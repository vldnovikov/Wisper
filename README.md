# Wisper

Local push-to-talk dictation for macOS (Apple Silicon). Hold a key, speak, release — your speech is transcribed on-device with Whisper (via MLX) and typed into whatever text field has focus. An internet connection is only needed once, to download the model.

- Works in any app: browsers, chats, editors, Spotlight, etc.
- Ukrainian + English out of the box (language is picked per phrase).
- Menu-bar app with a status icon; no audio ever leaves your Mac.

## Requirements

- Mac with Apple Silicon (M1 or newer), macOS 13+
- Python **3.11–3.12** for development (the system `/usr/bin/python3` 3.9 won't work — no prebuilt wheels for pyobjc/mlx)
- Xcode Command Line Tools (`xcode-select --install`) — needed to build the app launcher

## Setup

The easiest way is [uv](https://docs.astral.sh/uv/):

```bash
brew install uv
cd wisper
uv venv -p 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Menu-bar app (for your own Mac)

```bash
./build_app.sh                 # creates /Applications/Wisper.app
open /Applications/Wisper.app
```

The menu-bar icon shows the current state: ⏳ loading model → 🎙 ready → 🔴 recording → 💭 transcribing.

**Usage:** hold **Right Option**, speak, release. Press **Esc** while holding to cancel.

**Menu:** permissions status, copy last text, language, hotkey, press Enter after inserting, type character by character, sounds, launch at login, personal dictionary, log.

`Wisper.app` built this way is a thin launcher: a small native binary (compiled with `clang`) that embeds Python from this folder's `.venv` and runs `menubar.py`. After editing the code just restart Wisper — no rebuild needed. Re-run `build_app.sh` only if you move the project folder.

### Permissions

macOS treats Wisper as a separate app, so grant the permissions to **Wisper** (System Settings → Privacy & Security):

- **Microphone** — asked automatically on first use
- **Accessibility** — needed to insert text
- **Input Monitoring** — needed to detect the hotkey

The ⚠️ permissions item at the top of the menu opens the right settings page. Wisper picks up newly granted permissions without a restart.

> Every rebuild with `build_app.sh` changes the app's signature, so macOS forgets the old grants. The script resets them; just enable Wisper again in Accessibility and Input Monitoring.

## Sharing the app (self-contained build)

```bash
./package_app.sh      # -> dist/Wisper.app and dist/Wisper.zip
```

`Wisper.zip` (~200 MB) contains everything — Python runtime, libraries and code — and doesn't depend on this folder. The Whisper model (~3 GB) is downloaded on first launch.

For the person installing it:

1. Unzip and drag `Wisper.app` into **Applications**.
2. The app isn't notarized by Apple, so macOS blocks the first launch. Either go to System Settings → Privacy & Security → **Open Anyway**, or run:
   ```bash
   xattr -dr com.apple.quarantine /Applications/Wisper.app
   ```
3. Wait for the menu-bar icon to turn from ⏳ to 🎙 (model download).
4. Grant Microphone, Accessibility and Input Monitoring.

## Personal dictionary

Menu → **Dictionary…** opens `~/Library/Application Support/Wisper/dictionary.txt`. Changes apply immediately.

```text
# Hint words — one per line: names, terms, slang Whisper should know
Wispr
Kubernetes

# Replacements — "what was recognized => what it should be" (whole words, case-insensitive)
Віспар => Wispr
```

## Running from the terminal

```bash
python dictate.py
```

When running this way, grant Microphone / Accessibility / Input Monitoring to your **terminal app** (Terminal, iTerm, Warp, VS Code…) and restart it.

### Options

| Flag | Description |
|---|---|
| `--key alt_r` | hotkey to hold: `alt_r`, `ctrl_r`, `cmd_r`, `shift_r`, `f13`… |
| `--lang uk,en` | allowed languages (default `uk,en` — the model picks one of them per phrase). `--lang uk` = always Ukrainian, `--lang ""` = any language |
| `--model large` | `large` (default, most accurate, ~3 GB), `turbo` (faster, ~1.6 GB), `medium`, `small`, or any MLX Whisper repo on Hugging Face |
| `--enter` | press Enter after inserting the text |
| `--mode type` | type character by character instead of pasting with Cmd+V |
| `--prompt "..."` | extra vocabulary hints for Whisper |
| `--dict PATH` | personal dictionary file |
| `--postroll 0.35` | keep recording this many seconds after the key is released |
| `--mic-on-demand` | open the mic only while the key is held (no orange indicator, but the first ~0.2 s may be cut) |
| `--no-sounds` | disable start/stop sounds |

## How text is inserted

- **Default:** the text is put on the clipboard, Cmd+V is sent, then the previous clipboard content is restored.
- **Type mode:** characters are sent as keyboard events (for apps that ignore paste).
- **Game mode (automatic):** some full-screen games ignore both. For known game clients Wisper types each character as a real key press, slowly, and also leaves the text on the clipboard as a fallback.

## Troubleshooting

- **Logs:** `~/Library/Logs/Wisper.log` (menu → Open log).
- **Hotkey does nothing:** check Accessibility and Input Monitoring for Wisper (or your terminal).
- **Poor recognition:** recent takes are saved to `~/Library/Application Support/Wisper/recordings/`. Run `python retest.py` to re-transcribe the latest one with different settings (models, prompt, language) and see audio-quality stats.
- **Bluetooth headsets** (AirPods etc.) switch to a low-quality mic mode — the built-in Mac microphone usually gives better results.
