# Wisper

Local push-to-talk dictation for macOS (Apple Silicon). Hold a key, speak, release — your speech is transcribed on-device with Whisper (via MLX) and typed into whatever text field has focus. An internet connection is only needed once, to download the model.

- Works in any app: browsers, chats, editors, Spotlight, etc.
- Ukrainian + English out of the box (language is picked per phrase).
- Menu-bar app with a status icon.
- Local by default (no audio leaves your Mac); optional OpenAI cloud recognition and Claude text cleanup.

## Install

Open **Terminal** and run:

```bash
curl -fsSL https://raw.githubusercontent.com/vldnovikov/whisper/main/install.sh | bash
```

It downloads the latest release, installs `Wisper.app` into Applications and launches it — no Python or anything else needed, and no "Apple could not verify…" dialog. Run the same command again to update.

Prefer a manual download? Get `Wisper.zip` from **[Releases](https://github.com/vldnovikov/whisper/releases/latest)**. Because the app isn't notarized by Apple, macOS blocks the first launch of a browser-downloaded copy: click **Done**, then System Settings → Privacy & Security → **Open Anyway**.

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

**Menu:** permissions status, copy last text, recognition engine, Claude cleanup, API keys, language, hotkey, press Enter after inserting, type character by character, keep microphone open, sounds, launch at login, personal dictionary, log.

By default the microphone is only open while you hold the hotkey, so the orange mic indicator appears only while recording. If the first syllable sometimes gets cut, turn on **Keep Microphone Open (Faster Start)** — the mic then stays open with a 0.3 s buffer, and macOS shows the indicator all the time.

`Wisper.app` built this way is a thin launcher: a small native binary (compiled with `clang`) that embeds Python from this folder's `.venv` and runs `menubar.py`. After editing the code just restart Wisper — no rebuild needed. Re-run `build_app.sh` only if you move the project folder.

### Permissions

macOS treats Wisper as a separate app, so grant the permissions to **Wisper** (System Settings → Privacy & Security):

- **Microphone** — asked automatically on first use
- **Accessibility** — needed to insert text
- **Input Monitoring** — needed to detect the hotkey

The ⚠️ *Missing permission* item at the top of the menu opens the right settings page. Wisper picks up newly granted permissions without a restart.

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

## Recognition engines and Claude cleanup

Menu → **Recognition** lets you pick how speech is turned into text:

| Engine | Where it runs | Cost | Notes |
|---|---|---|---|
| Local — Whisper | on your Mac | free | default, works offline, audio never leaves the Mac |
| OpenAI `gpt-4o-transcribe` | OpenAI cloud | ~$0.006 / min | most accurate, best with mixed Ukrainian/English |
| OpenAI `gpt-transcribe` | OpenAI cloud | ~$0.0045 / min | |
| OpenAI `gpt-4o-mini-transcribe` | OpenAI cloud | ~$0.003 / min | cheapest cloud option |

Menu → **Local Model** chooses the on-device Whisper model. **Auto** (default) picks `large` (most accurate, ~3 GB) on Macs with 16 GB of RAM or more and `turbo` (about 2–3× faster, ~1.6 GB) on 8 GB Macs, where `large` would push the system into swap and become very slow. The model is downloaded on first use.

Menu → **Fix Text with Claude Haiku** sends the recognized *text* (never audio) to Claude Haiku, which fixes spelling, punctuation and Russian-style spellings without changing the meaning. Works with any engine; adds ~0.5–1 s.

**API keys:** menu → **API Keys**. Paste your OpenAI key (platform.openai.com) and/or Anthropic key (console.anthropic.com). Keys are stored in the macOS Keychain (service "Wisper"), never in files. Selecting a cloud engine or turning on cleanup without a key asks for it automatically.

If a cloud request fails (no internet, invalid key), Wisper falls back to local Whisper / the uncleaned text, so dictation keeps working. Details are in the log.

Rough cost for ~1,000 dictated words a day (~8–10 min of audio): `gpt-4o-transcribe` ≈ $1.50–1.80 / month, `gpt-4o-mini-transcribe` ≈ $0.75–0.90 / month, Claude cleanup ≈ $0.10 / month.

## Personal dictionary

Menu → **Dictionary…** opens `~/Library/Application Support/Wisper/dictionary.txt`. Changes apply immediately.

```text
# Hint words — one per line: names, terms, slang Whisper should know
Wispr
Kubernetes

# Replacements — "what was recognized => what it should be" (whole words, case-insensitive)
whisper flow => Wispr Flow
```

## Publishing a release

Every push to `main` triggers GitHub Actions (`.github/workflows/release.yml`): it builds the self-contained app on an Apple Silicon runner and publishes a new release `v<VERSION>.<build number>` (e.g. `v0.2.7`) with `Wisper.zip` attached and marked as latest.

- Bump the base version by editing the `VERSION` file (e.g. `0.3`).
- Pushes that change only `*.md` files don't trigger a build.
- A newer push cancels a build that is still running.
- Actions → Release → **Run workflow** starts a build manually.

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
| `--model auto` | `auto` (default: `large` on Macs with 16 GB+ RAM, `turbo` otherwise), `large` (most accurate, ~3 GB), `turbo` (fast, ~1.6 GB), `medium`, `small`, or any MLX Whisper repo on Hugging Face |
| `--enter` | press Enter after inserting the text |
| `--mode type` | type character by character instead of pasting with Cmd+V |
| `--prompt "..."` | extra vocabulary hints for Whisper |
| `--dict PATH` | personal dictionary file |
| `--postroll 0.35` | keep recording this many seconds after the key is released |
| `--mic-always-on` | keep the mic open with a 0.3 s pre-roll so the first syllable is never cut (the orange mic indicator stays on) |
| `--engine NAME` | `local` (default), `gpt-4o-transcribe`, `gpt-transcribe`, `gpt-4o-mini-transcribe` — cloud engines need `OPENAI_API_KEY` or a key saved in Wisper |
| `--cleanup` | fix the text with Claude Haiku — needs `ANTHROPIC_API_KEY` or a key saved in Wisper |
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
